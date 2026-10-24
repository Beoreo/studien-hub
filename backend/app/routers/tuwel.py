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
from ..lernaufwand import dokument_aufbereiten, grundaufwand_minuten, lernparameter
from ..models import DOK_GEAENDERT, DOK_NEU, ZUORDNUNG_AUS, ZUORDNUNG_AUTO, ZUORDNUNG_MANUELL, Dokument, Lva, TuwelKurs
from ..tuwel_sync import (
    Eintrag,
    datei_speichern,
    erweiterungs_schluessel,
    fehler_melden,
    inhalt_abgleichen,
    kurse_registrieren,
    setze_kurs_lva,
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
    episode_id: str | None = Field(None, max_length=100)
    datum_text: str = ""
    dauer_text: str = ""
    dauer_sekunden: int | None = Field(None, ge=0)
    medien_url: str | None = None
    tuwel_zeit: int | None = Field(None, ge=0)  # Unix-Zeit aus core_course_get_updates_since
    last_modified: str | None = Field(None, max_length=100)


class InhaltIn(BaseModel):
    kurs_id: int
    eintraege: list[EintragIn]
    nachtrag: bool = False  # Details neuer Aufzeichnungen im selben Lauf


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
        "lva_name": (k.lva.anzeigename) if k.lva else None,
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
    return inhalt_abgleichen(session, kurs, [Eintrag(**e.model_dump()) for e in daten.eintraege], daten.nachtrag)


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
        kurs.zuordnung = ZUORDNUNG_MANUELL
        # Unterlagen ziehen bei einem Wechsel mit um
        setze_kurs_lva(session, kurs, session.get(Lva, daten.lva_id) if daten.lva_id is not None else None)
    session.commit()
    session.refresh(kurs)
    return kurs_out(kurs)


class LernzeitIn(BaseModel):
    lern_minuten: int | None = Field(None, ge=0, le=100 * 60)  # None = Schätzung verwenden, 0 = nicht lernen


@router.patch("/dokumente/{dokument_id}")
def dokument_lernzeit(dokument_id: int, daten: LernzeitIn, session: Session = Depends(get_session)):
    doc = session.get(Dokument, dokument_id)
    if doc is None:
        raise HTTPException(404, "Unterlage nicht gefunden")
    doc.lern_minuten = daten.lern_minuten
    session.commit()
    return {"id": doc.id, "lern_minuten": doc.lern_minuten}


@router.get("/dokumente")
def dokumente_auflisten(lva_id: int | None = None, session: Session = Depends(get_session)):
    # pro LVA nach Erscheinungsdatum, neueste zuerst; ohne Datum ans Ende
    abfrage = select(Dokument).order_by(
        Dokument.lva_id, Dokument.erschienen_am.is_(None), Dokument.erschienen_am.desc(), Dokument.dateiname
    )
    if lva_id is not None:
        abfrage = abfrage.where(Dokument.lva_id == lva_id)
    def geschaetzt(d: Dokument) -> int:
        """Geschätzte Stoffmenge: gewichtet nur, welcher Stoff in einem Lernblock dran ist."""
        dokument_aufbereiten(d)
        return round(grundaufwand_minuten(d, lernparameter(d.lva)))

    liste = [
        {
            # Schätzung zuerst: sie bestimmt Lernart und Seitenzahl, falls noch unbekannt
            "lern_minuten_geschaetzt": geschaetzt(d), "lernart": d.lernart, "seiten": d.seiten,
            "lern_minuten": d.lern_minuten,
            "id": d.id, "lva_id": d.lva_id, "abschnitt": d.abschnitt, "aktivitaet": d.aktivitaet,
            "dateiname": d.dateiname, "typ": d.typ, "ist_link": d.ist_link,
            "url": d.quelle_url if d.ist_link else None, "pfad": d.pfad, "groesse": d.groesse,
            "status": d.status, "erstellt_am": d.erstellt_am, "geaendert_am": d.geaendert_am,
            "episode_id": d.episode_id, "aufnahme_am": d.aufnahme_am, "dauer_sekunden": d.dauer_sekunden,
            "medien_url": d.medien_url,
            "erschienen_am": d.erschienen_am, "erschienen_quelle": d.erschienen_quelle,
            "sync_am": d.geaendert_am,  # wann der Hub die aktuelle Fassung bekommen hat
            # Ergebnis des letzten Sync-Laufs: neu oder geändert
            "neu_seit_sync": d.status in (DOK_NEU, DOK_GEAENDERT),
            # Herkunft: offiziell (TUWEL) oder inoffiziell (MB Cloud der Fachschaft) mit Kategorie und Jahr
            "quelle": d.quelle or "tuwel", "kategorie": d.kategorie, "jahr": d.jahr,
        }
        for d in session.scalars(abfrage)
    ]
    session.commit()  # dabei ermittelte Seitenzahlen speichern
    return liste


@router.get("/dokumente/{dokument_id}/datei")
def dokument_datei(dokument_id: int, session: Session = Depends(get_session)):
    doc = session.get(Dokument, dokument_id)
    if doc is None or doc.ist_link or not doc.pfad:
        raise HTTPException(404, "Keine Datei vorhanden")
    pfad = (UNTERLAGEN_ORDNER / doc.pfad).resolve()
    if UNTERLAGEN_ORDNER.resolve() not in pfad.parents or not pfad.exists():
        raise HTTPException(404, "Datei nicht gefunden")
    return FileResponse(pfad, filename=pfad.name, content_disposition_type="inline")
