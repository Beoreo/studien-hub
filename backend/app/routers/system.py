"""Betrieb: Status-Seite, Jetzt synchronisieren, Autostart, Sicherungen, Ordner öffnen, Einrichtungsassistent."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import autostart, einrichtung, jobs, sicherung
from ..config import (
    DATEN_ORDNER,
    ERWEITERUNG_ID,
    ERWEITERUNG_ORDNER,
    LOG_ORDNER,
    PRODUKTION,
    PROGRAMM_ORDNER,
    VERSION,
    mbcloud_zugang,
    tuwel_token,
)
from ..db import SessionLocal, get_session
from ..models import lies_einstellung, setze_einstellung
from ..protokoll import letzte_meldungen

router = APIRouter(prefix="/api", tags=["Betrieb"])

TUWEL_ANGEFORDERT = "tuwel_sync_angefordert"


def _json(wert: str | None):
    if not wert:
        return None
    try:
        return json.loads(wert)
    except json.JSONDecodeError:
        return {"meldung": wert}


def quellen(session: Session) -> list[dict]:
    """Letzter Sync und letzter Fehler je Quelle."""
    from ..lva_auswahl import tiss_stand
    from ..tuwel_sync import status as tuwel_status

    tuwel = tuwel_status(session)
    steop = tiss_stand(session)
    tiss_fehler = lies_einstellung(session, "tiss_letzter_fehler")
    mb_fehler = lies_einstellung(session, "mbcloud_letzter_fehler")
    return [
        {"id": "tiss", "name": "TISS-Kalender", "letzter_sync": lies_einstellung(session, "tiss_letzter_import"),
         "fehler": {"meldung": tiss_fehler} if tiss_fehler else None,
         "eingerichtet": bool(lies_einstellung(session, "tiss_ical_url"))},
        {"id": "tuwel", "name": "TUWEL (Browser-Erweiterung)", "letzter_sync": tuwel["letzter_erfolg"],
         "fehler": tuwel["letzter_fehler"] or ({"meldung": tuwel["warnung"]} if tuwel["warnung"] else None),
         "eingerichtet": tuwel["letzter_erfolg"] is not None},
        {"id": "steop", "name": "STEOP-Status (TISS)", "letzter_sync": (steop or {}).get("zeit"), "fehler": None,
         "eingerichtet": steop is not None},
        {"id": "mbcloud", "name": "MB Cloud", "letzter_sync": lies_einstellung(session, "mbcloud_letzter_lauf"),
         "fehler": _json(mb_fehler), "eingerichtet": mbcloud_zugang() is not None},
    ]


def fehlerzustand(session: Session) -> list[str]:
    """Kurze Fehlertexte für das Symbol im Infobereich (leer = alles in Ordnung)."""
    fehler = [f"{q['name']}: {q['fehler']['meldung']}" for q in quellen(session)
              if q["eingerichtet"] and q["fehler"] and q["fehler"].get("meldung")]
    fehler += [f"{j['name']}: {j['fehler']['meldung']}" for j in jobs.uebersicht() if j.get("fehler")]
    return fehler


@router.get("/system/status")
def system_status(request: Request, session: Session = Depends(get_session)):
    scheduler = getattr(request.app.state, "scheduler", None)
    return {
        "version": VERSION,
        "modus": "produktion" if PRODUKTION else "entwicklung",
        "daten_ordner": str(DATEN_ORDNER),
        "programm_ordner": str(PROGRAMM_ORDNER),
        "quellen": quellen(session),
        "jobs": jobs.uebersicht(scheduler),
        "meldungen": letzte_meldungen(),
        "fehler": fehlerzustand(session),
        "autostart": {"verfuegbar": autostart.verfuegbar(), "aktiv": autostart.aktiv()},
        "sicherungen": sicherung.liste(),
        "tuwel_angefordert": lies_einstellung(session, TUWEL_ANGEFORDERT),
    }


def jetzt_synchronisieren() -> list[str]:
    """TISS und MB Cloud sofort; TUWEL holt sich die Erweiterung, sobald sie die Anforderung sieht."""
    gestartet = []
    for job_id in ("tiss-sync", "mbcloud"):
        if not jobs.laeuft(job_id):
            jobs.im_hintergrund(job_id)
            gestartet.append(job_id)
    with SessionLocal() as session:
        setze_einstellung(session, TUWEL_ANGEFORDERT, datetime.now().isoformat(timespec="seconds"))
        session.commit()
    return gestartet


@router.post("/system/sync")
def sync_starten():
    return {"gestartet": jetzt_synchronisieren(), "tuwel_angefordert": True}


class AutostartIn(BaseModel):
    aktiv: bool


@router.put("/system/autostart")
def autostart_setzen(daten: AutostartIn):
    if not autostart.verfuegbar():
        raise HTTPException(409, "Autostart gibt es nur für den installierten Hub (StudienHub.exe).")
    return {"verfuegbar": True, "aktiv": autostart.setzen(daten.aktiv)}


@router.post("/system/sicherungen")
def sicherung_anlegen():
    try:
        return {"name": sicherung.sichern("manuell").name, "sicherungen": sicherung.liste()}
    except sicherung.SicherungsFehler as fehler:
        raise HTTPException(409, str(fehler)) from fehler


@router.post("/system/sicherungen/{name}/wiederherstellen")
def sicherung_wiederherstellen(name: str):
    try:
        vorher = sicherung.wiederherstellen(name)
    except sicherung.SicherungsFehler as fehler:
        raise HTTPException(404, str(fehler)) from fehler
    return {"wiederhergestellt": name, "vorheriger_stand": vorher.name, "sicherungen": sicherung.liste()}


ORDNER = {"erweiterung": ERWEITERUNG_ORDNER, "daten": DATEN_ORDNER, "logs": LOG_ORDNER}


@router.post("/system/ordner/{art}")
def ordner_oeffnen(art: str):
    """Öffnet einen Ordner im Explorer (nur lokal; der Hub hört nur auf 127.0.0.1)."""
    if art not in ORDNER:
        raise HTTPException(404, "Unbekannter Ordner")
    ORDNER[art].mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(ORDNER[art])  # noqa: S606 – fester Pfad, keine Eingabe
    return {"ordner": str(ORDNER[art])}


# --- Einrichtungsassistent --------------------------------------------------------------------------

@router.get("/einrichtung")
def einrichtung_status(session: Session = Depends(get_session)):
    from .. import ki_einrichtung
    from ..tuwel_sync import status as tuwel_status

    quelle = einrichtung.entwicklungs_daten()
    return {
        "abgeschlossen": lies_einstellung(session, einrichtung.ABGESCHLOSSEN) is not None,
        "daten": {"quelle": str(quelle) if quelle else None,
                  "uebernommen": lies_einstellung(session, einrichtung.UEBERNOMMEN),
                  "stand": einrichtung.uebernahme_stand()},
        "tiss": {"eingerichtet": bool(lies_einstellung(session, "tiss_ical_url"))},
        "tuwel": {"eingerichtet": tuwel_token() is not None},
        "mbcloud": {"eingerichtet": mbcloud_zugang() is not None},
        "erweiterung": {"ordner": str(ERWEITERUNG_ORDNER), "id": ERWEITERUNG_ID,
                        "verbunden": tuwel_status(session)["letzter_lauf"] is not None},
        "ki": {"eingerichtet": ki_einrichtung.status()["aktuell"]},
        "modelle": einrichtung.modelle_stand(),
    }


@router.post("/einrichtung/daten")
def daten_uebernehmen():
    quelle = einrichtung.entwicklungs_daten()
    if quelle is None:
        raise HTTPException(404, "Keine Daten aus einer Entwicklungsumgebung gefunden.")
    if not einrichtung.uebernahme_starten(quelle):
        raise HTTPException(409, "Die Übernahme läuft bereits.")
    return einrichtung.uebernahme_stand()


class TokenIn(BaseModel):
    eingabe: str


@router.put("/einrichtung/tuwel-token")
def tuwel_token_setzen(daten: TokenIn):
    from ..tuwel_token import TokenFehler

    try:
        einrichtung.tuwel_token_setzen(daten.eingabe)
    except TokenFehler as fehler:
        raise HTTPException(422, str(fehler)) from fehler
    return {"eingerichtet": True}


@router.post("/einrichtung/modelle/{name}")
def modell_laden(name: str):
    if name not in einrichtung.MODELLE:
        raise HTTPException(404, "Unbekanntes Modell")
    einrichtung.modell_laden(name)
    return einrichtung.modelle_stand()


@router.post("/einrichtung/abschliessen")
def einrichtung_abschliessen(session: Session = Depends(get_session)):
    setze_einstellung(session, einrichtung.ABGESCHLOSSEN, datetime.now().isoformat(timespec="seconds"))
    session.commit()
    return {"abgeschlossen": True}


# --- Erweiterung: TUWEL-Sync auf Anforderung ---------------------------------------------------------

@router.get("/tuwel/sync/anforderung")
def tuwel_anforderung(session: Session = Depends(get_session)):
    """Die Erweiterung fragt regelmäßig nach; liegt eine Anforderung nach ihrem letzten Lauf, startet sie einen."""
    return {"angefordert": lies_einstellung(session, TUWEL_ANGEFORDERT)}
