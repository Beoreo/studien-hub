"""Lernaufwand je Unterlage, Lernbedarf je Woche und LVA, Abgleich mit den ECTS.

Schätzung (Werte pro LVA einstellbar, Standard in models.STANDARD_LERNPARAMETER):
- Folien:      Seitenzahl × Minuten pro Folie (PDF im Querformat, PowerPoint/Impress)
- Skripte:     Seitenzahl × Minuten pro Seite (PDF im Hochformat, Word/Writer)
- Übungsblätter: fester Wert (erkannt am Namen der Datei, Aktivität oder des Abschnitts)
- Videos:      Dauer × Faktor
- Sonstiges:   fester Wert
Jede Schätzung wird mit dem Korrekturfaktor der LVA multipliziert, der aus den selbst
eingetragenen tatsächlichen Zeiten der Lernblöcke gelernt wird.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import UNTERLAGEN_ORDNER
from .models import (
    LERN_VORSCHLAG,
    STANDARD_LERNPARAMETER,
    TYP_PRUEFUNG,
    Dokument,
    Lernblock,
    Lva,
    Termin,
)
from .planung import wochenbeginn

UEBUNG = re.compile(
    r"übung|uebung|\bblatt\b|blatt\s*\d|aufgabe|angabe|exercise|assignment|homework|hausübung|hausaufgabe|"
    r"tutorium|worksheet",
    re.IGNORECASE,
)
STUNDEN_PRO_ECTS = 25
STANDARD_SEMESTERWOCHEN = 15
VIDEO_OHNE_DAUER_MINUTEN = 90  # Annahme, wenn die Dauer einer Aufzeichnung unbekannt ist
RUECKSTAND_WOCHEN = 2  # so weit zurück wird noch nicht abgedeckter Stoff eingeplant
KALIBRIER_GEWICHT = 120  # Minuten „Vorwissen“: die ersten Rückmeldungen ändern die Schätzung behutsam


# --- Seiten zählen und Art bestimmen -------------------------------------------------------

def seiten_und_format(pfad: Path) -> tuple[int | None, bool | None]:
    """(Seitenzahl, überwiegend Querformat?) einer Datei; None, wenn unbekannt."""
    endung = pfad.suffix.lower()
    try:
        if endung == ".pdf":
            import pymupdf

            with pymupdf.open(pfad) as pdf:
                proben = [pdf[i].rect for i in range(min(3, pdf.page_count))]
                quer = sum(1 for r in proben if r.width > r.height) > len(proben) / 2 if proben else None
                return pdf.page_count, quer
        if endung in (".pptx", ".ppsx"):
            with zipfile.ZipFile(pfad) as z:
                folien = [n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]
                return len(folien) or None, True
        if endung == ".odp":
            with zipfile.ZipFile(pfad) as z:
                return z.read("content.xml").count(b"<draw:page ") or None, True
        if endung == ".docx":
            with zipfile.ZipFile(pfad) as z:
                if "docProps/app.xml" in z.namelist():
                    treffer = re.search(rb"<Pages>(\d+)</Pages>", z.read("docProps/app.xml"))
                    if treffer:
                        return int(treffer.group(1)), False
                woerter = len(re.sub(rb"<[^>]+>", b" ", z.read("word/document.xml")).split())
                return max(1, round(woerter / 350)), False
        if endung == ".odt":
            with zipfile.ZipFile(pfad) as z:
                treffer = re.search(rb'meta:page-count="(\d+)"', z.read("meta.xml"))
                return (int(treffer.group(1)) if treffer else None), False
    except Exception:  # beschädigte oder geschützte Datei: Aufwand bleibt eine Schätzung ohne Seiten
        return None, None
    return None, None


def bestimme_lernart(doc: Dokument, quer: bool | None) -> str:
    if doc.ist_link:
        return "video"
    # nur Datei- und Aktivitätsname: ein Abschnitt „Übungen“ enthält oft auch Folien
    if UEBUNG.search(" ".join(filter(None, [doc.dateiname, doc.aktivitaet]))):
        return "uebung"
    if doc.typ == "folien":
        return "folien"
    if doc.typ == "pdf":
        return "folien" if quer else "skript"
    if doc.typ == "dokument":
        return "skript"
    return "sonstiges"


def dokument_aufbereiten(doc: Dokument) -> None:
    """Bestimmt Seitenzahl und Lernart einmalig (auch nachträglich für ältere Unterlagen)."""
    if doc.lernart is not None:
        return
    quer = None
    if not doc.ist_link and doc.pfad:
        pfad = UNTERLAGEN_ORDNER / doc.pfad
        if pfad.exists():
            doc.seiten, quer = seiten_und_format(pfad)
    doc.lernart = bestimme_lernart(doc, quer)


# --- Schätzung ------------------------------------------------------------------------------

def lernparameter(lva: Lva) -> dict[str, float]:
    return {**STANDARD_LERNPARAMETER, **(lva.lernparameter or {})}


def grundaufwand_minuten(doc: Dokument, parameter: dict[str, float]) -> float:
    """Geschätzte Lernzeit ohne Korrektur."""
    art = doc.lernart
    if art == "video":
        dauer = doc.dauer_sekunden / 60 if doc.dauer_sekunden else VIDEO_OHNE_DAUER_MINUTEN
        return dauer * parameter["video_faktor"]
    if art == "uebung":
        return parameter["minuten_pro_uebungsblatt"]
    if art == "folien" and doc.seiten:
        return doc.seiten * parameter["minuten_pro_folie"]
    if art == "skript" and doc.seiten:
        return doc.seiten * parameter["minuten_pro_skriptseite"]
    return parameter["minuten_sonstiges"]


@dataclass
class Korrektur:
    faktor: float
    rueckmeldungen: int


def korrekturfaktor(session: Session, lva_id: int) -> Korrektur:
    """Verhältnis tatsächlicher zu geplanter Lernzeit, mit Vorwissen geglättet."""
    bloecke = session.scalars(
        select(Lernblock).where(Lernblock.lva_id == lva_id, Lernblock.tatsaechliche_minuten.is_not(None))
    ).all()
    geplant = sum(b.geplante_minuten for b in bloecke)
    tatsaechlich = sum(b.tatsaechliche_minuten for b in bloecke)
    faktor = (tatsaechlich + KALIBRIER_GEWICHT) / (geplant + KALIBRIER_GEWICHT)
    return Korrektur(round(min(max(faktor, 0.25), 4.0), 2), len(bloecke))


def aufwand_minuten(doc: Dokument, lva: Lva, korrektur: Korrektur) -> int:
    """Geschätzte Lernzeit inklusive Korrektur; eine selbst eingetragene Zeit gilt unverändert."""
    if doc.lern_minuten is not None:
        return doc.lern_minuten
    dokument_aufbereiten(doc)
    return round(grundaufwand_minuten(doc, lernparameter(lva)) * korrektur.faktor)


def erscheinungszeit(doc: Dokument) -> datetime:
    return doc.erschienen_am or doc.erstellt_am


# --- Lernbedarf je Woche ----------------------------------------------------------------------

def _wochengrenzen(woche: date) -> tuple[datetime, datetime]:
    start = datetime.combine(wochenbeginn(woche), time())
    return start, start + timedelta(days=7)


def semesterwochen(session: Session, lva: Lva) -> int:
    """Wochen zwischen erstem und letztem Termin der LVA (ohne Prüfungen)."""
    termine = session.scalars(select(Termin.start).where(Termin.lva_id == lva.id, Termin.typ != TYP_PRUEFUNG)).all()
    if not termine:
        return STANDARD_SEMESTERWOCHEN
    erste, letzte = wochenbeginn(min(termine).date()), wochenbeginn(max(termine).date())
    return max(1, (letzte - erste).days // 7 + 1)


def abgedeckte_minuten(session: Session, ausser_woche: tuple[datetime, datetime] | None = None) -> dict[int, int]:
    """Minuten je Dokument, die schon Lernblöcke abdecken (Vorschläge der neu geplanten Woche ausgenommen)."""
    abgedeckt: dict[int, int] = {}
    for block in session.scalars(select(Lernblock)):
        if ausser_woche and block.status == LERN_VORSCHLAG and ausser_woche[0] <= block.start < ausser_woche[1]:
            continue
        for dok_id, minuten in (block.zuteilung or {}).items():
            abgedeckt[int(dok_id)] = abgedeckt.get(int(dok_id), 0) + int(minuten)
    return abgedeckt


@dataclass
class OffeneUnterlage:
    dokument_id: int
    lva_id: int
    titel: str
    erschienen: datetime
    minuten: int  # noch nicht durch Lernblöcke abgedeckt


def offene_unterlagen(session: Session, woche: date) -> list[OffeneUnterlage]:
    """Stoff, der in dieser Woche oder bis zu zwei Wochen davor erschienen und noch nicht eingeplant ist."""
    von, bis = _wochengrenzen(woche)
    ab = von - timedelta(weeks=RUECKSTAND_WOCHEN)
    abgedeckt = abgedeckte_minuten(session, (von, bis))
    korrekturen: dict[int, Korrektur] = {}
    offen = []
    for doc in session.scalars(select(Dokument)):
        zeit = erscheinungszeit(doc)
        if not (ab <= zeit < bis):
            continue
        korrektur = korrekturen.setdefault(doc.lva_id, korrekturfaktor(session, doc.lva_id))
        rest = aufwand_minuten(doc, doc.lva, korrektur) - abgedeckt.get(doc.id, 0)
        if rest > 0:
            offen.append(OffeneUnterlage(doc.id, doc.lva_id, doc.dateiname, max(zeit, von), rest))
    session.flush()
    return sorted(offen, key=lambda o: (o.erschienen, o.dokument_id))


@dataclass
class Wochenbedarf:
    lva_id: int
    lva_name: str
    unterlagen_minuten: int = 0  # neuer Stoff dieser Woche (geschätzt, korrigiert)
    praesenz_minuten: int = 0  # Termine der LVA in dieser Woche
    soll_minuten: int | None = None  # aus ECTS
    korrektur: float = 1.0
    unterlagen: list[dict] = field(default_factory=list)
    warnung: str | None = None

    @property
    def gesamt_minuten(self) -> int:
        return self.unterlagen_minuten + self.praesenz_minuten


def wochenbedarf(session: Session, woche: date, warnschwelle: float = 0.5) -> list[Wochenbedarf]:
    """Lernbedarf je LVA für eine Woche und Abgleich mit dem ECTS-Soll."""
    von, bis = _wochengrenzen(woche)
    ergebnis: dict[int, Wochenbedarf] = {}

    def eintrag(lva: Lva) -> Wochenbedarf:
        if lva.id not in ergebnis:
            ergebnis[lva.id] = Wochenbedarf(lva.id, lva.kurzname or lva.titel, korrektur=korrekturfaktor(session, lva.id).faktor)
        return ergebnis[lva.id]

    for doc in session.scalars(select(Dokument)):
        if not (von <= erscheinungszeit(doc) < bis):
            continue
        b = eintrag(doc.lva)
        minuten = aufwand_minuten(doc, doc.lva, Korrektur(b.korrektur, 0))
        b.unterlagen_minuten += minuten
        b.unterlagen.append({"id": doc.id, "titel": doc.dateiname, "lernart": doc.lernart, "seiten": doc.seiten, "minuten": minuten})
    for termin in session.scalars(select(Termin).where(Termin.start >= von, Termin.start < bis)):
        eintrag(termin.lva).praesenz_minuten += int((termin.ende - termin.start).total_seconds() // 60)
    session.flush()

    for b in ergebnis.values():
        lva = session.get(Lva, b.lva_id)
        if not lva.ects:
            continue
        b.soll_minuten = round(lva.ects * STUNDEN_PRO_ECTS * 60 / semesterwochen(session, lva))
        if b.soll_minuten and abs(b.gesamt_minuten - b.soll_minuten) > warnschwelle * b.soll_minuten:
            richtung = "über" if b.gesamt_minuten > b.soll_minuten else "unter"
            b.warnung = (f"{b.lva_name}: {stunden(b.gesamt_minuten)} diese Woche liegt deutlich {richtung} "
                         f"dem ECTS-Soll von {stunden(b.soll_minuten)} ({str(lva.ects).replace('.', ',').removesuffix(',0')} ECTS)")
    return sorted(ergebnis.values(), key=lambda b: b.lva_name)


def stunden(minuten: int | float) -> str:
    return f"{minuten / 60:.1f}".replace(".", ",") + " h"
