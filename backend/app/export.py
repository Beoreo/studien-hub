"""Export gefilterter Termine und Arbeitszeiten als iCal, CSV oder PDF."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime

from fpdf import FPDF
from icalendar import Calendar, Event

from .config import ZEITZONE
from .models import STATUS_VORSCHLAG, Arbeitsblock, Termin


@dataclass
class ExportEintrag:
    """Gemeinsame Sicht auf Termine und Arbeitsblöcke für alle Exportformate."""

    uid: str
    art: str  # "Termin" oder "Arbeit"
    titel: str
    start: datetime
    ende: datetime
    lva_nummer: str = ""
    lva_titel: str = ""
    typ: str = ""
    ort: str = ""
    steop: bool = False
    anwesenheitspflicht: bool = False
    aufzeichnung: bool = False
    status: str = ""
    notiz: str = ""

    @property
    def dauer_stunden(self) -> float:
        return round((self.ende - self.start).total_seconds() / 3600, 2)

    @property
    def markierungen_text(self) -> str:
        teile = []
        if self.steop:
            teile.append("STEOP")
        if self.anwesenheitspflicht:
            teile.append("Anwesenheitspflicht")
        if self.aufzeichnung:
            teile.append("Aufzeichnung")
        return ", ".join(teile)


def eintrag_aus_termin(t: Termin) -> ExportEintrag:
    return ExportEintrag(
        uid=f"termin-{t.id}@studien-hub",
        art="Termin",
        titel=t.anzeigename,
        start=t.start,
        ende=t.ende,
        lva_nummer=t.lva.nummer or "",
        lva_titel=t.lva.titel,
        typ="Prüfung" if t.ist_pruefung else t.typ,
        ort=t.ort or "",
        steop=t.ist_steop,
        anwesenheitspflicht=t.hat_anwesenheitspflicht,
        aufzeichnung=t.wird_aufgezeichnet,
    )


def eintrag_aus_block(b: Arbeitsblock) -> ExportEintrag:
    titel = "Arbeit" + (f" – {b.arbeitgeber}" if b.arbeitgeber else "")
    return ExportEintrag(
        uid=f"arbeit-{b.id}@studien-hub",
        art="Arbeit",
        titel=titel,
        start=b.start,
        ende=b.ende,
        typ=b.art,
        status="Vorschlag" if b.status == STATUS_VORSCHLAG else "bestätigt",
        notiz=b.notiz or "",
    )


def sammle_eintraege(termine: list[Termin], bloecke: list[Arbeitsblock]) -> list[ExportEintrag]:
    eintraege = [eintrag_aus_termin(t) for t in termine] + [eintrag_aus_block(b) for b in bloecke]
    return sorted(eintraege, key=lambda e: (e.start, e.art))


def als_ical(eintraege: list[ExportEintrag]) -> bytes:
    kalender = Calendar()
    kalender.add("prodid", "-//Studien-Hub//DE")
    kalender.add("version", "2.0")
    kalender.add("x-wr-calname", "Studien-Hub")
    for e in eintraege:
        ereignis = Event()
        ereignis.add("uid", e.uid)
        titel = e.titel + (f" [{e.markierungen_text}]" if e.markierungen_text else "")
        ereignis.add("summary", titel)
        ereignis.add("dtstart", e.start.replace(tzinfo=ZEITZONE))
        ereignis.add("dtend", e.ende.replace(tzinfo=ZEITZONE))
        ereignis.add("dtstamp", datetime.now(ZEITZONE))
        if e.ort:
            ereignis.add("location", e.ort)
        beschreibung = [x for x in (e.lva_titel, e.markierungen_text, e.status, e.notiz) if x]
        if beschreibung:
            ereignis.add("description", "\n".join(beschreibung))
        ereignis.add("categories", [e.art])
        kalender.add_component(ereignis)
    if hasattr(kalender, "add_missing_timezones"):
        kalender.add_missing_timezones()
    return kalender.to_ical()


CSV_SPALTEN = [
    "Art", "Titel", "LVA-Nummer", "LVA", "Typ", "Datum", "Beginn", "Ende", "Dauer (h)",
    "Ort", "STEOP", "Anwesenheitspflicht", "Aufzeichnung", "Status", "Notiz",
]


def _ja_nein(wert: bool) -> str:
    return "ja" if wert else ""


def _zahl(wert: float) -> str:
    return f"{wert:.2f}".replace(".", ",")  # deutsches Excel


def als_csv(eintraege: list[ExportEintrag]) -> bytes:
    """CSV mit Semikolon und BOM, damit Excel Umlaute und Spalten korrekt erkennt."""
    puffer = io.StringIO()
    schreiber = csv.writer(puffer, delimiter=";", lineterminator="\r\n")
    schreiber.writerow(CSV_SPALTEN)
    for e in eintraege:
        schreiber.writerow([
            e.art, e.titel, e.lva_nummer, e.lva_titel, e.typ,
            e.start.strftime("%d.%m.%Y"), e.start.strftime("%H:%M"), e.ende.strftime("%H:%M"),
            _zahl(e.dauer_stunden), e.ort,
            _ja_nein(e.steop), _ja_nein(e.anwesenheitspflicht), _ja_nein(e.aufzeichnung),
            e.status, e.notiz,
        ])
    arbeit = sum(e.dauer_stunden for e in eintraege if e.art == "Arbeit")
    if arbeit:
        schreiber.writerow(["Summe Arbeit", "", "", "", "", "", "", "", _zahl(arbeit)] + [""] * 6)
    return ("﻿" + puffer.getvalue()).encode("utf-8")


def _latin1(text: str) -> str:
    # Die Standardschriften von fpdf2 können nur Latin-1 (Umlaute gehen, Sonderzeichen nicht)
    return text.replace("–", "-").encode("latin-1", "replace").decode("latin-1")


WOCHENTAGE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def als_pdf(eintraege: list[ExportEintrag], ueberschrift: str = "Studien-Hub") -> bytes:
    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 9, _latin1(ueberschrift), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(0, 5, _latin1(f"Erstellt am {datetime.now():%d.%m.%Y %H:%M}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    spalten = [("Datum", 26), ("Zeit", 22), ("Std.", 12), ("Art", 15), ("Titel", 80),
               ("Typ", 18), ("Ort", 45), ("Markierungen / Status", 55)]
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(230, 230, 230)
    for name, breite in spalten:
        pdf.cell(breite, 6, _latin1(name), border=1, fill=True)
    pdf.ln()
    pdf.set_font("Helvetica", "", 8)
    for e in eintraege:
        zellen = [
            f"{WOCHENTAGE[e.start.weekday()]} {e.start:%d.%m.%Y}",
            f"{e.start:%H:%M}-{e.ende:%H:%M}",
            _zahl(e.dauer_stunden),
            e.art,
            e.titel,
            e.typ,
            e.ort,
            ", ".join(x for x in (e.markierungen_text, e.status) if x),
        ]
        for (_, breite), text in zip(spalten, zellen):
            text = _latin1(text)
            while text and pdf.get_string_width(text) > breite - 2:
                text = text[:-1]
            pdf.cell(breite, 5, text, border=1)
        pdf.ln()

    arbeit = sum(e.dauer_stunden for e in eintraege if e.art == "Arbeit")
    if arbeit:
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(0, 6, _latin1(f"Summe Arbeitszeit: {_zahl(arbeit)} Stunden"))
    return bytes(pdf.output())
