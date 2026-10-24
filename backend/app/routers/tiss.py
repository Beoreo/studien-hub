"""TISS-iCal-Link verwalten und Import auslösen (per Link oder Datei-Upload)."""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import SessionLocal, get_session
from ..lva_auswahl import steop_aus_tiss_speichern, steop_abgeschlossen
from ..models import FreierZeitraum, lies_einstellung, setze_einstellung
from ..planung_service import auswahl_geaendert, planung_aktuell_halten
from ..schemas import ImportErgebnisOut, SteopTissIn, TissEinstellungen
from .tuwel import pruefe_schluessel
from ..tiss_import import ImportErgebnis, importiere_ical, lade_feed

router = APIRouter(prefix="/api/tiss", tags=["TISS"])

URL_SCHLUESSEL = "tiss_ical_url"
LETZTER_IMPORT = "tiss_letzter_import"
LETZTER_FEHLER = "tiss_letzter_fehler"


def _ergebnis_out(ergebnis: ImportErgebnis, zeitpunkt: datetime) -> ImportErgebnisOut:
    return ImportErgebnisOut(
        neu=ergebnis.neu,
        geaendert=ergebnis.geaendert,
        geloescht=ergebnis.geloescht,
        unveraendert=ergebnis.unveraendert,
        neue_lvas=ergebnis.neue_lvas,
        freie_zeitraeume=ergebnis.freie_zeitraeume,
        entfernte_lvas=ergebnis.entfernte_lvas,
        neu_geplante_wochen=ergebnis.neu_geplante_wochen,
        letzter_import=zeitpunkt,
    )


def _importieren(session: Session, daten: bytes) -> ImportErgebnisOut:
    try:
        ergebnis = importiere_ical(session, daten)
    except ValueError as fehler:
        session.rollback()
        setze_einstellung(session, LETZTER_FEHLER, f"Ungültiger iCal-Feed: {fehler}")
        session.commit()
        raise HTTPException(422, f"Ungültiger iCal-Feed: {fehler}") from fehler
    jetzt = datetime.now()
    setze_einstellung(session, LETZTER_IMPORT, jetzt.isoformat(timespec="seconds"))
    setze_einstellung(session, LETZTER_FEHLER, None)
    session.commit()
    planung_aktuell_halten(session)  # neue oder entfernte LVAs können die Kursauswahl ändern
    return _ergebnis_out(ergebnis, jetzt)


@router.post("/steop", dependencies=[Depends(pruefe_schluessel)])
def steop_aus_tiss(daten: SteopTissIn, session: Session = Depends(get_session)):
    """STEOP-Status von der Browser-Erweiterung (TISS-Seite „STEOP Status“, mit der Browser-Sitzung gelesen)."""
    uebernommen = steop_aus_tiss_speichern(session, daten.model_dump())
    session.commit()
    neu_geplant = auswahl_geaendert(session)
    return {
        "uebernommen": uebernommen,
        "abgeschlossen": steop_abgeschlossen(session),
        "steop_nummern": len(daten.steop_nummern),
        "neu_geplante_wochen": neu_geplant,
    }


@router.get("/einstellungen")
def einstellungen_lesen(session: Session = Depends(get_session)):
    bericht = lies_einstellung(session, "lva_struktur_bericht")
    return {
        "ical_url": lies_einstellung(session, URL_SCHLUESSEL),
        "letzter_import": lies_einstellung(session, LETZTER_IMPORT),
        "letzter_fehler": lies_einstellung(session, LETZTER_FEHLER),
        # einmaliger Bericht der Bereinigung (Ferien-Einträge, zusammengefasste LVAs, Sicherungskopie)
        "bereinigung": json.loads(bericht) if bericht else None,
    }


@router.get("/freie-zeitraeume")
def freie_zeitraeume(session: Session = Depends(get_session)):
    """Vorlesungsfreie Zeiten aus TISS – sperren Arbeit und Lernen wie Feiertage."""
    abfrage = select(FreierZeitraum).order_by(FreierZeitraum.von)
    return [{"id": z.id, "bezeichnung": z.bezeichnung, "von": z.von, "bis": z.bis} for z in session.scalars(abfrage)]


@router.put("/einstellungen")
def einstellungen_speichern(daten: TissEinstellungen, session: Session = Depends(get_session)):
    setze_einstellung(session, URL_SCHLUESSEL, (daten.ical_url or "").strip() or None)
    session.commit()
    return einstellungen_lesen(session)


@router.post("/import", response_model=ImportErgebnisOut)
def import_von_link(session: Session = Depends(get_session)):
    url = lies_einstellung(session, URL_SCHLUESSEL)
    if not url:
        raise HTTPException(409, "Bitte zuerst den TISS-iCal-Link speichern.")
    try:
        daten = lade_feed(url)
    except Exception as fehler:  # Netzwerkfehler sichtbar melden
        setze_einstellung(session, LETZTER_FEHLER, f"Abruf fehlgeschlagen: {fehler}")
        session.commit()
        raise HTTPException(502, f"TISS-Feed konnte nicht geladen werden: {fehler}") from fehler
    return _importieren(session, daten)


@router.post("/import-datei", response_model=ImportErgebnisOut)
async def import_von_datei(datei: UploadFile = File(...), session: Session = Depends(get_session)):
    return _importieren(session, await datei.read())


def taeglicher_sync() -> None:
    """Wird vom Scheduler aufgerufen; Fehler landen in den Einstellungen und in der Oberfläche."""
    with SessionLocal() as session:
        if not lies_einstellung(session, URL_SCHLUESSEL):
            return
        try:
            import_von_link(session)
        except HTTPException:
            pass  # Fehler wurde bereits gespeichert
