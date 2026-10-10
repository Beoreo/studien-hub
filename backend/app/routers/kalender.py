"""Kalenderdaten im FullCalendar-Format und Export (iCal, CSV, PDF)."""

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from ..db import get_session
from ..feiertage import feiertage, freie_tage_expandieren
from ..export import als_csv, als_ical, als_pdf, sammle_eintraege
from ..filter import Filter, arbeitsbloecke_filtern, filter_aus_anfrage, termine_filtern
from ..models import STATUS_VORSCHLAG, Arbeitsblock, Termin
from ..planung_service import lade_regel

router = APIRouter(prefix="/api", tags=["Kalender und Export"])

ARBEIT_FARBE = "#475569"
FEIERTAG_FARBE = "#9ca3af"
FREI_FARBE = "#d1d5db"
PRUEFUNG_FARBE_RAND = "#000000"


def termin_event(t: Termin) -> dict:
    return {
        "id": f"t{t.id}",
        "title": t.anzeigename,
        "start": t.start.isoformat(),
        "end": t.ende.isoformat(),
        "backgroundColor": t.lva.farbe,
        "borderColor": PRUEFUNG_FARBE_RAND if t.ist_pruefung else t.lva.farbe,
        "editable": False,
        "classNames": ["termin"] + (["pruefung"] if t.ist_pruefung else []),
        "extendedProps": {
            "art": "termin",
            "terminId": t.id,
            "lvaId": t.lva_id,
            "typ": t.typ,
            "ort": t.ort,
            "steop": t.ist_steop,
            "anwesenheitspflicht": t.hat_anwesenheitspflicht,
            "aufzeichnung": t.wird_aufgezeichnet,
            "pruefung": t.ist_pruefung,
        },
    }


def block_event(b: Arbeitsblock) -> dict:
    vorschlag = b.status == STATUS_VORSCHLAG
    return {
        "id": f"a{b.id}",
        "title": ("Vorschlag: " if vorschlag else "") + "Arbeit" + (f" ({b.arbeitgeber})" if b.arbeitgeber else ""),
        "start": b.start.isoformat(),
        "end": b.ende.isoformat(),
        "backgroundColor": ARBEIT_FARBE,
        "borderColor": ARBEIT_FARBE,
        "editable": True,
        "classNames": ["arbeit"] + (["vorschlag"] if vorschlag else []),
        "extendedProps": {
            "art": "arbeit",
            "blockId": b.id,
            "status": b.status,
            "blockArt": b.art,
            "notiz": b.notiz,
            "serieId": b.serie_id,
        },
    }


def tages_event(tag: date, titel: str, art: str) -> dict:
    """Ganztägiger grauer Eintrag für Feiertage und freie Tage."""
    farbe = FEIERTAG_FARBE if art == "feiertag" else FREI_FARBE
    return {
        "id": f"{art}-{tag.isoformat()}",
        "title": titel,
        "start": tag.isoformat(),
        "end": (tag + timedelta(days=1)).isoformat(),
        "allDay": True,
        "backgroundColor": farbe,
        "borderColor": farbe,
        "textColor": "#1f2937",
        "editable": False,
        "classNames": [art],
        "extendedProps": {"art": art},
    }


def freie_tage_events(session: Session, f: Filter) -> list[dict]:
    if not (f.von and f.bis):
        return []
    von, bis = f.von.date(), (f.bis - timedelta(microseconds=1)).date()
    events = [tages_event(tag, name, "feiertag") for tag, name in feiertage(von, bis).items()]
    regel = lade_regel(session)
    if regel and regel.freie_tage:
        gesetzlich = {e["start"] for e in events}
        events += [
            tages_event(tag, f"Frei: {name}", "frei")
            for tag, name in freie_tage_expandieren(regel.freie_tage, von, bis).items()
            if tag.isoformat() not in gesetzlich
        ]
    return events


@router.get("/kalender")
def kalender(f: Filter = Depends(filter_aus_anfrage), session: Session = Depends(get_session)) -> list[dict]:
    return (
        freie_tage_events(session, f)
        + [termin_event(t) for t in termine_filtern(session, f)]
        + [block_event(b) for b in arbeitsbloecke_filtern(session, f)]
    )


def _dateiname(f: Filter, endung: str) -> str:
    teile = ["studien-hub"]
    if f.arbeit == "nur":
        teile.append("arbeitszeiten")
    if f.von:
        teile.append(f.von.strftime("%Y-%m-%d"))
    if f.bis:
        teile.append(f.bis.strftime("%Y-%m-%d"))
    return "_".join(teile) + "." + endung


MEDIENTYPEN = {"ics": "text/calendar; charset=utf-8", "csv": "text/csv; charset=utf-8", "pdf": "application/pdf"}


@router.get("/export/{format}")
def exportieren(format: str, f: Filter = Depends(filter_aus_anfrage), session: Session = Depends(get_session)):
    if format not in MEDIENTYPEN:
        return Response("Unbekanntes Format (ics, csv, pdf)", status_code=404)
    eintraege = sammle_eintraege(termine_filtern(session, f), arbeitsbloecke_filtern(session, f))
    if format == "ics":
        inhalt = als_ical(eintraege)
    elif format == "csv":
        inhalt = als_csv(eintraege)
    else:
        zeitraum = ""
        if f.von and f.bis:
            zeitraum = f" {f.von:%d.%m.%Y} - {datetime.fromordinal(f.bis.toordinal() - 1):%d.%m.%Y}"
        titel = ("Arbeitszeiten" if f.arbeit == "nur" else "Termine") + zeitraum
        inhalt = als_pdf(eintraege, titel)
    return Response(
        inhalt,
        media_type=MEDIENTYPEN[format],
        headers={"Content-Disposition": f'attachment; filename="{_dateiname(f, format)}"'},
    )
