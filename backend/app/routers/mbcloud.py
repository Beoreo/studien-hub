"""MB Cloud der Fachschaft: Verbinden, Index-Lauf, Ordner-Zuordnung, Treffer je LVA, Downloads, Altprüfungen."""

import json
import threading
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import MBCLOUD_STANDARD_URL, MBCLOUD_WURZEL, mbcloud_zugang, zugangsdaten_setzen
from ..db import SessionLocal, get_session
from ..mbcloud import KATEGORIE_NAMEN, automatisch_laden
from ..mbcloud_client import MbCloud, MbCloudFehler, login_abfragen, login_starten
from ..mbcloud_sync import herunterladen, lauf
from ..models import (
    MB_ABGELEHNT,
    MB_BESTAETIGT,
    Dokument,
    Lva,
    MbCloudDatei,
    MbCloudOrdner,
    lies_einstellung,
)

router = APIRouter(prefix="/api/mbcloud", tags=["MB Cloud"])

_lauf_sperre = threading.Lock()
_anmeldung: dict = {}  # laufender Login-Flow (nur im Speicher, nie in der Datenbank)


def verbindung() -> MbCloud:
    zugang = mbcloud_zugang()
    if zugang is None:
        raise HTTPException(409, "MB Cloud ist noch nicht verbunden – im Reiter „MB Cloud“ auf „Verbinden“ klicken.")
    return MbCloud(*zugang)


def lauf_im_hintergrund() -> bool:
    """Ein Lauf zur Zeit; True, wenn gestartet."""
    if mbcloud_zugang() is None or not _lauf_sperre.acquire(blocking=False):
        return False

    def arbeiten():
        try:
            cloud = MbCloud(*mbcloud_zugang())
            with SessionLocal() as session:
                lauf(session, cloud)
            cloud.schliessen()
        finally:
            _lauf_sperre.release()

    threading.Thread(target=arbeiten, name="mbcloud-lauf", daemon=True).start()
    return True


def taeglicher_lauf() -> None:
    """Vom Scheduler aufgerufen (nach dem TISS-Import)."""
    lauf_im_hintergrund()


# --- Status und Verbinden ------------------------------------------------------------------------

@router.get("/status")
def status(session: Session = Depends(get_session)):
    zugang = mbcloud_zugang()
    bericht = lies_einstellung(session, "mbcloud_bericht")
    zaehle = lambda *bed: session.scalar(select(func.count(MbCloudDatei.id)).where(MbCloudDatei.ist_ordner.is_(False), *bed))  # noqa: E731
    return {
        "verbunden": zugang is not None,
        "url": zugang[0] if zugang else MBCLOUD_STANDARD_URL,
        "benutzer": zugang[1] if zugang else None,
        "wurzel": MBCLOUD_WURZEL,
        "laeuft": _lauf_sperre.locked(),
        "anmeldung_offen": bool(_anmeldung),
        "letzter_lauf": lies_einstellung(session, "mbcloud_letzter_lauf"),
        "letzter_fehler": lies_einstellung(session, "mbcloud_letzter_fehler"),
        "bericht": json.loads(bericht) if bericht else None,
        "ordner": session.scalar(select(func.count(MbCloudOrdner.id))),
        "dateien": zaehle(),
        "heruntergeladen": zaehle(MbCloudDatei.dokument_id.is_not(None)),
    }


class VerbindenIn(BaseModel):
    url: str = MBCLOUD_STANDARD_URL


@router.post("/verbinden")
def verbinden(daten: VerbindenIn):
    """Startet den Nextcloud-Login: Adresse im Browser öffnen, mit TU Login anmelden, Zugriff erlauben."""
    try:
        _anmeldung.clear()
        _anmeldung.update(login_starten(daten.url), url=daten.url.rstrip("/"))
    except (MbCloudFehler, Exception) as fehler:
        raise HTTPException(502, f"MB Cloud nicht erreichbar: {fehler}") from fehler
    return {"login_url": _anmeldung["login"]}


@router.post("/verbinden/pruefen")
def verbinden_pruefen():
    """Fragt ab, ob die Anmeldung im Browser bestätigt wurde; dann landen die Zugangsdaten in der
    Windows-Anmeldeinformationsverwaltung."""
    if not _anmeldung:
        return {"verbunden": mbcloud_zugang() is not None}
    try:
        ergebnis = login_abfragen(_anmeldung["endpoint"], _anmeldung["token"])
    except MbCloudFehler as fehler:
        _anmeldung.clear()
        raise HTTPException(502, str(fehler)) from fehler
    if ergebnis is None:
        return {"verbunden": False}
    zugangsdaten_setzen({
        "MBCLOUD_URL": (ergebnis.get("server") or _anmeldung["url"]).rstrip("/"),
        "MBCLOUD_BENUTZER": ergebnis["loginName"],
        "MBCLOUD_APP_PASSWORT": ergebnis["appPassword"],
    })
    _anmeldung.clear()
    lauf_im_hintergrund()  # erster Index gleich im Anschluss
    return {"verbunden": True}


@router.post("/lauf")
def lauf_starten():
    if mbcloud_zugang() is None:
        raise HTTPException(409, "MB Cloud ist noch nicht verbunden.")
    return {"gestartet": lauf_im_hintergrund(), "laeuft": True}


# --- Ordner-Zuordnung --------------------------------------------------------------------------------

def ordner_out(o: MbCloudOrdner, anzahl: int = 0) -> dict:
    return {
        "id": o.id, "name": o.name, "pfad": o.pfad, "groesse": o.groesse, "lva_id": o.lva_id,
        "lva_name": (o.lva.anzeigename) if o.lva else None, "zuordnung": o.zuordnung,
        "aehnlichkeit": o.aehnlichkeit, "gelesen": o.gelesen_etag is not None, "dateien": anzahl,
    }


@router.get("/ordner")
def ordner_auflisten(session: Session = Depends(get_session)):
    anzahl = dict(session.execute(
        select(MbCloudDatei.ordner_id, func.count(MbCloudDatei.id)).where(MbCloudDatei.ist_ordner.is_(False))
        .group_by(MbCloudDatei.ordner_id)
    ).all())
    return [ordner_out(o, anzahl.get(o.id, 0)) for o in session.scalars(select(MbCloudOrdner).order_by(MbCloudOrdner.name))]


class OrdnerUpdate(BaseModel):
    lva_id: int | None = None
    zuordnung: str = Field(MB_BESTAETIGT, pattern="^(bestaetigt|abgelehnt)$")


@router.patch("/ordner/{ordner_id}")
def ordner_zuordnen(ordner_id: int, daten: OrdnerUpdate, session: Session = Depends(get_session)):
    """Bestätigen, eine andere LVA wählen oder ablehnen – gilt auch für alle künftigen Dateien im Ordner."""
    ordner = session.get(MbCloudOrdner, ordner_id)
    if ordner is None:
        raise HTTPException(404, "Ordner nicht gefunden")
    if daten.zuordnung == MB_ABGELEHNT:
        ordner.zuordnung, ordner.lva_id = MB_ABGELEHNT, None
    else:
        lva_id = daten.lva_id or ordner.lva_id
        if lva_id is None or session.get(Lva, lva_id) is None:
            raise HTTPException(422, "Bitte eine LVA wählen")
        ordner.lva_id, ordner.zuordnung = lva_id, MB_BESTAETIGT
        ordner.gelesen_etag = None  # beim nächsten Lauf lesen
        # schon gelesene Dateien wandern mit
        for doc in session.scalars(select(Dokument).join(MbCloudDatei, MbCloudDatei.dokument_id == Dokument.id).where(
                MbCloudDatei.ordner_id == ordner.id, MbCloudDatei.duplikat.is_(False))):
            doc.lva_id = lva_id
    session.commit()
    lauf_im_hintergrund()
    return ordner_out(ordner)


# --- Treffer je LVA, Downloads ---------------------------------------------------------------------

def datei_out(d: MbCloudDatei, heute) -> dict:
    doc = d.dokument
    return {
        "id": d.id, "name": d.name, "pfad": d.pfad, "unterordner": d.eltern_pfad.removeprefix(d.ordner.pfad).strip("/"),
        "groesse": d.groesse, "geaendert": d.geaendert, "kategorie": d.kategorie,
        "kategorie_name": KATEGORIE_NAMEN.get(d.kategorie or "", "Sonstiges"), "datum": d.datum, "jahr": d.jahr,
        "jahr_geschaetzt": d.jahr_geschaetzt, "gedankenprotokoll": d.gedankenprotokoll,
        "loesung_zu_id": d.loesung_zu_id, "automatisch": automatisch_laden(d.kategorie, d.jahr, heute),
        "dokument_id": d.dokument_id, "duplikat": d.duplikat,
        "duplikat_von": (doc.quelle if doc else None) if d.duplikat else None,
        "bearbeitet_am": doc.bearbeitet_am if doc else None, "bearbeitet_minuten": doc.bearbeitet_minuten if doc else None,
        "punkte": doc.punkte if doc else None, "punkte_max": doc.punkte_max if doc else None,
    }


@router.get("/dateien")
def dateien_auflisten(lva_id: int, session: Session = Depends(get_session)):
    """Treffer einer LVA, neueste zuerst; die Oberfläche gruppiert nach Kategorie."""
    heute = datetime.now().date()
    dateien = session.scalars(
        select(MbCloudDatei).join(MbCloudOrdner).where(
            MbCloudOrdner.lva_id == lva_id, MbCloudOrdner.zuordnung.in_(["auto", "bestaetigt"]),
            MbCloudDatei.ist_ordner.is_(False),
        ).order_by(MbCloudDatei.datum.desc().nulls_last(), MbCloudDatei.jahr.desc().nulls_last(), MbCloudDatei.name)
    )
    return [datei_out(d, heute) for d in dateien]


@router.post("/dateien/{datei_id}/laden")
def datei_laden(datei_id: int, session: Session = Depends(get_session)):
    """Einzelne Datei per Klick herunterladen."""
    datei = session.get(MbCloudDatei, datei_id)
    if datei is None or datei.ist_ordner:
        raise HTTPException(404, "Datei nicht gefunden")
    if datei.dokument_id:
        return datei_out(datei, datetime.now().date())
    cloud = verbindung()
    try:
        herunterladen(session, cloud, datei)
    except (MbCloudFehler, ValueError) as fehler:
        raise HTTPException(502, str(fehler)) from fehler
    finally:
        cloud.schliessen()
    session.refresh(datei)
    return datei_out(datei, datetime.now().date())


class BearbeitungIn(BaseModel):
    erledigt: bool = True
    minuten: int | None = Field(None, ge=0, le=24 * 60)
    punkte: float | None = Field(None, ge=0)
    punkte_max: float | None = Field(None, gt=0)


@router.patch("/dokumente/{dokument_id}/bearbeitung")
def altpruefung_bearbeitet(dokument_id: int, daten: BearbeitungIn, session: Session = Depends(get_session)):
    """Altprüfung als erledigt markieren (Zeitbedarf, erreichte Punkte); erledigte plant der Hub nicht mehr ein."""
    doc = session.get(Dokument, dokument_id)
    if doc is None:
        raise HTTPException(404, "Unterlage nicht gefunden")
    if daten.punkte is not None and daten.punkte_max is not None and daten.punkte > daten.punkte_max:
        raise HTTPException(422, "Mehr Punkte als möglich")
    doc.bearbeitet_am = datetime.now() if daten.erledigt else None
    doc.bearbeitet_minuten, doc.punkte, doc.punkte_max = (
        (daten.minuten, daten.punkte, daten.punkte_max) if daten.erledigt else (None, None, None))
    session.commit()
    return {"id": doc.id, "bearbeitet_am": doc.bearbeitet_am, "bearbeitet_minuten": doc.bearbeitet_minuten,
            "punkte": doc.punkte, "punkte_max": doc.punkte_max}
