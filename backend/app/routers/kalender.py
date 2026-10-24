"""Kalenderdaten im FullCalendar-Format und Export (iCal, CSV, PDF)."""

from dataclasses import replace
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..feiertage import feiertage, freie_tage_expandieren, tiss_freie_tage
from ..export import als_csv, als_ical, als_pdf, sammle_eintraege
from ..filter import Filter, arbeitsbloecke_filtern, filter_aus_anfrage, termine_filtern
from ..lva_auswahl import ausgeblendete_lva_ids
from .lernen import _altpruefung
from ..models import (
    LERN_VORSCHLAG,
    STATUS_VORSCHLAG,
    TYP_PRUEFUNG,
    Arbeitsblock,
    Lernblock,
    Lva,
    PersoenlicherTermin,
    Pruefungstermin,
    Termin,
)
from ..planung_service import lade_regel
from ..pruefungen import feed_pruefungstage, ist_angemeldet, termine_der_lva

router = APIRouter(prefix="/api", tags=["Kalender und Export"])

ARBEIT_FARBE = "#475569"
FEIERTAG_FARBE = "#9ca3af"
FREI_FARBE = "#d1d5db"
PRUEFUNG_FARBE_RAND = "#b91c1c"
AUSGEBLENDET_FARBE = "#e5e7eb"  # LVAs, die dieses Semester nicht besucht werden (lva_auswahl.py)
AUSGEBLENDET_TEXT = "#6b7280"


def ausgrauen(event: dict) -> dict:
    """Ausgeblendete LVA: grau, nicht verschiebbar, für die Planung ohne Bedeutung."""
    event.update(backgroundColor=AUSGEBLENDET_FARBE, borderColor="#9ca3af", textColor=AUSGEBLENDET_TEXT,
                 title=f"{event['title']} (nicht besucht)")
    event["classNames"] = [*event["classNames"], "ausgeblendet"]
    event["extendedProps"]["ausgeblendet"] = True
    return event


def termin_event(t: Termin) -> dict:
    return {
        "id": f"t{t.id}",
        "title": t.anzeigename,  # Symbole (Prüfung, STEOP …) setzt die Oberfläche aus extendedProps
        "start": t.start.isoformat(),
        "end": t.ende.isoformat(),
        "backgroundColor": t.lva.farbe,
        "borderColor": PRUEFUNG_FARBE_RAND if t.ist_pruefung else t.lva.farbe,
        "editable": t.quelle == "manuell",  # selbst angelegt: verschiebbar; TISS-Termine bestimmt TISS
        "classNames": ["termin"] + (["pruefung"] if t.ist_pruefung else []) + (["abgabe"] if t.ist_abgabe else []),
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
            "abgabe": t.ist_abgabe,
            "quelle": t.quelle,
        },
    }


def persoenlich_events(session: Session, f: Filter) -> list[dict]:
    """Persönliche Termine (ohne LVA); ausgeblendet bei „nur Arbeit“, LVA- oder Typ-Filter."""
    if f.arbeit == "nur" or f.lva_ids or f.typen or not (f.von and f.bis):
        return []
    abfrage = select(PersoenlicherTermin).where(PersoenlicherTermin.start < f.bis, PersoenlicherTermin.ende > f.von)
    return [{
        "id": f"e{p.id}",
        "title": p.titel,
        "start": p.start.isoformat(),
        "end": p.ende.isoformat(),
        "backgroundColor": ARBEIT_FARBE,
        "borderColor": ARBEIT_FARBE,
        "editable": True,
        "classNames": ["persoenlich"],
        "extendedProps": {"art": "persoenlich", "persoenlichId": p.id, "ort": p.ort, "notiz": p.notiz},
    } for p in session.scalars(abfrage.order_by(PersoenlicherTermin.start))]


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
    belegt = {e["start"] for e in events}
    regel = lade_regel(session)
    eigene = freie_tage_expandieren(regel.freie_tage, von, bis) if regel and regel.freie_tage else {}
    # vorlesungsfreie Zeit aus TISS, dann eigene freie Tage – je Tag nur ein Eintrag
    for quelle in (tiss_freie_tage(session, von, bis), eigene):
        for tag, name in quelle.items():
            if tag.isoformat() not in belegt:
                events.append(tages_event(tag, f"Frei: {name}", "frei"))
                belegt.add(tag.isoformat())
    return events


def _pruefungs_lvas(session: Session, f: Filter) -> list[Lva]:
    """LVAs mit Prüfungsterminen, sofern der Filter Prüfungen zeigt."""
    if f.arbeit == "nur" or not (f.von and f.bis) or (f.typen and TYP_PRUEFUNG not in f.typen):
        return []
    abfrage = select(Lva).where(Lva.id.in_(select(Pruefungstermin.lva_id)))
    if f.lva_ids:
        abfrage = abfrage.where(Lva.id.in_(f.lva_ids))
    return list(session.scalars(abfrage))


def pruefungstermin_events(session: Session, f: Filter) -> list[dict]:
    """Angemeldete Prüfungstermine (Reiter „Prüfungen“). Tage mit einer Prüfung aus dem TISS-Feed zeigt schon der
    Termin; ohne bekannte Uhrzeit ganztägig."""
    events = []
    ausgeblendet = ausgeblendete_lva_ids(session)
    for lva in _pruefungs_lvas(session, f):
        feed = feed_pruefungstage(session, lva.id)
        for t in termine_der_lva(session, lva.id):
            if not ist_angemeldet(t, feed) or t.start.date() in feed or not f.von <= t.start < f.bis:
                continue
            ganztags = t.ende is None
            events.append({
                "id": f"p{t.id}",
                "title": f"Prüfung {lva.anzeigename}",
                "start": t.start.date().isoformat() if ganztags else t.start.isoformat(),
                "end": (t.start.date() + timedelta(days=1)).isoformat() if ganztags else t.ende.isoformat(),
                "allDay": ganztags,
                "backgroundColor": lva.farbe,
                "borderColor": PRUEFUNG_FARBE_RAND,
                "editable": False,
                "classNames": ["termin", "pruefung"],
                "extendedProps": {"art": "pruefung", "lvaId": lva.id, "pruefungId": t.id, "pruefung": True,
                                  "titel": t.titel, "ort": t.ort},
            })
            if lva.id in ausgeblendet:
                ausgrauen(events[-1])
    return events


def anmeldung_events(session: Session, f: Filter) -> list[dict]:
    """Tage, ab denen man sich zu einer Prüfung anmelden kann – ganztägig, je LVA und Tag ein Eintrag. Ist schon ein
    Termin gewählt, nur dessen Anmeldebeginn; sonst die aller angebotenen Termine. Nicht besuchte LVAs fehlen."""
    events = []
    ausgeblendet = ausgeblendete_lva_ids(session)
    for lva in _pruefungs_lvas(session, f):
        if lva.id in ausgeblendet:
            continue
        feed = feed_pruefungstage(session, lva.id)
        termine = termine_der_lva(session, lva.id)
        gewaehlt = [t for t in termine if ist_angemeldet(t, feed)]
        je_tag: dict[date, list[Pruefungstermin]] = {}
        for t in gewaehlt or termine:
            if t.anmeldung_von and f.von <= t.anmeldung_von < f.bis:
                je_tag.setdefault(t.anmeldung_von.date(), []).append(t)
        for tag, liste in sorted(je_tag.items()):
            events.append({
                "id": f"anm{lva.id}-{tag.isoformat()}",
                "title": f"Anmeldung {lva.anzeigename}",
                "start": tag.isoformat(),
                "end": (tag + timedelta(days=1)).isoformat(),
                "allDay": True,
                "backgroundColor": lva.farbe,
                "borderColor": lva.farbe,
                "editable": False,
                "classNames": ["anmeldung"],
                "extendedProps": {
                    "art": "anmeldung", "lvaId": lva.id,
                    "anmeldungAb": min(t.anmeldung_von for t in liste).isoformat(),
                    "pruefungen": [{"id": t.id, "titel": t.titel, "start": t.start.isoformat(),
                                    "anmeldungBis": t.anmeldung_bis.isoformat() if t.anmeldung_bis else None}
                                   for t in liste],
                },
            })
    return events


def lernblock_event(b: Lernblock) -> dict:
    vorschlag = b.status == LERN_VORSCHLAG
    return {
        "id": f"l{b.id}",
        "title": ("Vorschlag von Claude: " if vorschlag and b.quelle == "ki" else "Vorschlag: " if vorschlag else "")
        + f"Lernen {b.lva.anzeigename}",
        "start": b.start.isoformat(),
        "end": b.ende.isoformat(),
        "backgroundColor": b.lva.farbe,
        "borderColor": b.lva.farbe,
        "editable": not b.erledigt,
        "classNames": ["lernen"] + (["vorschlag"] if vorschlag else []) + (["erledigt"] if b.erledigt else []),
        "extendedProps": {
            "art": "lernen",
            "lernblockId": b.id,
            "lvaId": b.lva_id,
            "status": b.status,
            "thema": b.thema,
            "erledigt": b.erledigt,
            "altpruefung": _altpruefung(b),
        },
    }


def lernbloecke_filtern(session: Session, f: Filter) -> list[Lernblock]:
    if f.arbeit == "nur":
        return []
    abfrage = select(Lernblock).order_by(Lernblock.start)
    if f.von:
        abfrage = abfrage.where(Lernblock.ende > f.von)
    if f.bis:
        abfrage = abfrage.where(Lernblock.start < f.bis)
    if f.lva_ids:
        abfrage = abfrage.where(Lernblock.lva_id.in_(f.lva_ids))
    if not f.vorschlaege:
        abfrage = abfrage.where(Lernblock.status != LERN_VORSCHLAG)
    if not f.ausgeblendete:
        abfrage = abfrage.where(Lernblock.lva_id.not_in(ausgeblendete_lva_ids(session)))
    return list(session.scalars(abfrage))


@router.get("/kalender")
def kalender(f: Filter = Depends(filter_aus_anfrage), session: Session = Depends(get_session)) -> list[dict]:
    """Kalenderdaten; Termine ausgeblendeter LVAs erscheinen ausgegraut (für die Planung zählen sie nicht)."""
    ausgeblendet = ausgeblendete_lva_ids(session)
    termine = [
        ausgrauen(termin_event(t)) if t.lva_id in ausgeblendet else termin_event(t)
        for t in termine_filtern(session, replace(f, ausgeblendete=True))
    ]
    return (
        freie_tage_events(session, f)
        + anmeldung_events(session, f)
        + pruefungstermin_events(session, f)
        + termine
        + persoenlich_events(session, f)
        + [block_event(b) for b in arbeitsbloecke_filtern(session, f)]
        + [lernblock_event(b) for b in lernbloecke_filtern(session, f)]
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
