"""TUWEL-Sync: Endpunkte für die Browser-Erweiterung (mit Schlüssel) und für die Oberfläche."""

import json
import secrets

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import ERWEITERUNG_ORDNER, UNTERLAGEN_ORDNER
from ..db import get_session
from ..models import ZUORDNUNG_AUS, ZUORDNUNG_AUTO, ZUORDNUNG_MANUELL, Dokument, Lva, TuwelKurs
from ..tuwel_sync import (
    Eintrag,
    datei_speichern,
    erweiterungs_schluessel,
    fehler_melden,
    inhalt_abgleichen,
    kurse_registrieren,
    soll_synchronisiert_werden,
    status,
    sync_beenden,
)

router = APIRouter(prefix="/api/tuwel", tags=["TUWEL"])


def pruefe_schluessel(
    x_studienhub_schluessel: str | None = Header(None), session: Session = Depends(get_session)
) -> None:
    """Nur die eigene Erweiterung darf Daten in den Hub schreiben (Schutz vor fremden Webseiten)."""
    erwartet = erweiterungs_schluessel(session)
    if not x_studienhub_schluessel or not secrets.compare_digest(x_studienhub_schluessel, erwartet):
        raise HTTPException(401, "Schlüssel fehlt oder ist falsch – in der Erweiterung neu eintragen.")


# --- Schemas -------------------------------------------------------------------------

class KursIn(BaseModel):
    id: int
    kurzname: str = ""
    name: str = ""
    idnumber: str | None = None


class KurseIn(BaseModel):
    kurse: list[KursIn]


class EintragIn(BaseModel):
    cm_id: int
    url: str
    art: str = Field("datei", pattern="^(datei|video)$")
    abschnitt: str = ""
    aktivitaet: str = ""
    dateiname: str = ""
    unterordner: str = ""


class InhaltIn(BaseModel):
    kurs_id: int
    eintraege: list[EintragIn]


class EndeIn(BaseModel):
    statistik: dict


class FehlerIn(BaseModel):
    meldung: str
    art: str = "fehler"


class ZuordnungIn(BaseModel):
    lva_id: int | None = None
    aus: bool = False  # Kurs nicht synchronisieren
    automatisch: bool = False  # zurück zur automatischen Zuordnung


def kurs_out(k: TuwelKurs) -> dict:
    return {
        "id": k.id,
        "kurzname": k.kurzname,
        "name": k.name,
        "lva_id": k.lva_id,
        "lva_name": (k.lva.kurzname or k.lva.titel) if k.lva else None,
        "lva_semester": k.lva.semester if k.lva else None,
        "zuordnung": k.zuordnung,
        "synchronisieren": soll_synchronisiert_werden(k),
        "zuletzt_gesehen": k.zuletzt_gesehen,
    }


# --- Für die Erweiterung ---------------------------------------------------------------

@router.post("/sync/kurse", dependencies=[Depends(pruefe_schluessel)])
def sync_kurse(daten: KurseIn, session: Session = Depends(get_session)):
    kurse = kurse_registrieren(session, [k.model_dump() for k in daten.kurse])
    return {"kurse": [kurs_out(k) for k in kurse]}


@router.post("/sync/inhalt", dependencies=[Depends(pruefe_schluessel)])
def sync_inhalt(daten: InhaltIn, session: Session = Depends(get_session)):
    kurs = session.get(TuwelKurs, daten.kurs_id)
    if kurs is None or not soll_synchronisiert_werden(kurs):
        raise HTTPException(409, "Kurs ist keiner LVA zugeordnet")
    return inhalt_abgleichen(session, kurs, [Eintrag(**e.model_dump()) for e in daten.eintraege])


@router.post("/sync/datei", dependencies=[Depends(pruefe_schluessel)])
def sync_datei(
    kurs_id: int = Form(...), eintrag: str = Form(...), datei: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    kurs = session.get(TuwelKurs, kurs_id)
    if kurs is None or not soll_synchronisiert_werden(kurs):
        raise HTTPException(409, "Kurs ist keiner LVA zugeordnet")
    try:
        e = Eintrag(**EintragIn(**json.loads(eintrag)).model_dump())
    except (ValueError, TypeError) as fehler:
        raise HTTPException(422, f"Ungültiger Eintrag: {fehler}") from fehler
    if not e.dateiname:
        raise HTTPException(422, "Dateiname fehlt")
    return datei_speichern(session, kurs, e, datei.file)


@router.post("/sync/ende", dependencies=[Depends(pruefe_schluessel)])
def sync_ende(daten: EndeIn, session: Session = Depends(get_session)):
    sync_beenden(session, daten.statistik)
    return {"ok": True}


@router.post("/sync/fehler", dependencies=[Depends(pruefe_schluessel)])
def sync_fehler(daten: FehlerIn, session: Session = Depends(get_session)):
    fehler_melden(session, daten.meldung, daten.art)
    return {"ok": True}


@router.get("/sync/pruefen", dependencies=[Depends(pruefe_schluessel)])
def sync_pruefen():
    """Für die Erweiterung: Verbindung und Schlüssel testen."""
    return {"ok": True}


# --- Für die Oberfläche ------------------------------------------------------------------

@router.get("/status")
def tuwel_status(session: Session = Depends(get_session)):
    return status(session)


@router.get("/einrichtung")
def einrichtung(session: Session = Depends(get_session)):
    return {"schluessel": erweiterungs_schluessel(session), "ordner": str(ERWEITERUNG_ORDNER),
            "unterlagen": str(UNTERLAGEN_ORDNER)}


@router.post("/einrichtung/neuer-schluessel")
def neuer_schluessel(session: Session = Depends(get_session)):
    return {"schluessel": erweiterungs_schluessel(session, neu=True)}


@router.get("/kurse")
def kurse_auflisten(session: Session = Depends(get_session)):
    kurse = session.scalars(select(TuwelKurs).order_by(TuwelKurs.name)).all()
    return [kurs_out(k) for k in kurse]


@router.patch("/kurse/{kurs_id}")
def kurs_zuordnen(kurs_id: int, daten: ZuordnungIn, session: Session = Depends(get_session)):
    kurs = session.get(TuwelKurs, kurs_id)
    if kurs is None:
        raise HTTPException(404, "Kurs nicht gefunden")
    if daten.automatisch:
        kurs.zuordnung = ZUORDNUNG_AUTO
    elif daten.aus:
        kurs.zuordnung, kurs.lva_id = ZUORDNUNG_AUS, None
    else:
        if daten.lva_id is not None and session.get(Lva, daten.lva_id) is None:
            raise HTTPException(404, "LVA nicht gefunden")
        kurs.zuordnung, kurs.lva_id = ZUORDNUNG_MANUELL, daten.lva_id
        if daten.lva_id is not None:
            session.get(Lva, daten.lva_id).tuwel_kurs_id = kurs.id
    session.commit()
    session.refresh(kurs)
    return kurs_out(kurs)


@router.get("/dokumente")
def dokumente_auflisten(lva_id: int | None = None, session: Session = Depends(get_session)):
    abfrage = select(Dokument).order_by(Dokument.lva_id, Dokument.abschnitt, Dokument.dateiname)
    if lva_id is not None:
        abfrage = abfrage.where(Dokument.lva_id == lva_id)
    return [
        {
            "id": d.id, "lva_id": d.lva_id, "abschnitt": d.abschnitt, "aktivitaet": d.aktivitaet,
            "dateiname": d.dateiname, "typ": d.typ, "ist_link": d.ist_link,
            "url": d.quelle_url if d.ist_link else None, "pfad": d.pfad, "groesse": d.groesse,
            "status": d.status, "erstellt_am": d.erstellt_am, "geaendert_am": d.geaendert_am,
        }
        for d in session.scalars(abfrage)
    ]


@router.get("/dokumente/{dokument_id}/datei")
def dokument_datei(dokument_id: int, session: Session = Depends(get_session)):
    doc = session.get(Dokument, dokument_id)
    if doc is None or doc.ist_link or not doc.pfad:
        raise HTTPException(404, "Keine Datei vorhanden")
    pfad = (UNTERLAGEN_ORDNER / doc.pfad).resolve()
    if UNTERLAGEN_ORDNER.resolve() not in pfad.parents or not pfad.exists():
        raise HTTPException(404, "Datei nicht gefunden")
    return FileResponse(pfad, filename=pfad.name, content_disposition_type="inline")
