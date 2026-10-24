"""Lernbedarf je LVA und Woche (aus den ECTS) und der Stoff, den die Unterlagen liefern.

Wie viel Zeit eine LVA pro Woche bekommt, rechnet lernbedarf.py aus den ECTS. Die Unterlagen bestimmen
nur, welcher Stoff in einem Lernblock dran ist. Damit große und kleine Unterlagen einer LVA sinnvoll
verteilt werden, bekommt jede Unterlage eine geschätzte Stoffmenge (Gewicht, Werte je LVA einstellbar,
Standard in models.STANDARD_LERNPARAMETER):
- Folien:      Seitenzahl × Minuten pro Folie (PDF im Querformat, PowerPoint/Impress)
- Skripte:     Seitenzahl × Minuten pro Seite (PDF im Hochformat, Word/Writer)
- Übungsblätter: fester Wert (erkannt am Namen der Datei oder der Aktivität)
- Videos:      Dauer × Faktor
- Sonstiges:   fester Wert
`Dokument.lern_minuten` überschreibt die Schätzung (0 = nicht lernen).
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import UNTERLAGEN_ORDNER
from .feiertage import gesperrte_tage
from .lernbedarf import (
    STANDARD_ECTS_FAKTOR,
    STANDARD_LERNPHASE_WOCHEN,
    BedarfWoche,
    LvaPlanDaten,
    bedarf_fuer_woche,
    gesamtbedarf_minuten,
    montag,
    wochen_von_bis,
    wochengewichte,
)
from .models import (
    LERN_VORSCHLAG,
    STANDARD_LERNPARAMETER,
    TYP_ABGABE,
    TYP_PRUEFUNG,
    Arbeitsregel,
    Dokument,
    Lernblock,
    Lva,
    Termin,
)
from .pruefungen import ist_angemeldet, termine_der_lva

UEBUNG = re.compile(
    r"übung|uebung|\bblatt\b|blatt\s*\d|aufgabe|angabe|exercise|assignment|homework|hausübung|hausaufgabe|"
    r"tutorium|worksheet",
    re.IGNORECASE,
)
VIDEO_OHNE_DAUER_MINUTEN = 90  # Annahme, wenn die Dauer einer Aufzeichnung unbekannt ist
STANDARD_LERNTAGE = [0, 1, 2, 3, 4, 5]


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


# --- Stoffmenge je Unterlage ---------------------------------------------------------------------

def lernparameter(lva: Lva) -> dict[str, float]:
    return {**STANDARD_LERNPARAMETER, **(lva.lernparameter or {})}


def grundaufwand_minuten(doc: Dokument, parameter: dict[str, float]) -> float:
    """Geschätzte Stoffmenge einer Unterlage in Minuten."""
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


def stoff_minuten(doc: Dokument, lva: Lva) -> int:
    """Stoffmenge einer Unterlage; eine selbst eingetragene Zeit gilt unverändert (0 = nicht lernen)."""
    if doc.lern_minuten is not None:
        return doc.lern_minuten
    dokument_aufbereiten(doc)
    return round(grundaufwand_minuten(doc, lernparameter(lva)))


def erscheinungszeit(doc: Dokument) -> datetime:
    return doc.erschienen_am or doc.erstellt_am


def _wochengrenzen(woche: date) -> tuple[datetime, datetime]:
    start = datetime.combine(montag(woche), time())
    return start, start + timedelta(days=7)


def abgedeckte_minuten(session: Session, ausser_woche: tuple[datetime, datetime] | None = None) -> dict[int, int]:
    """Stoffmenge je Dokument, die schon Lernblöcke abdecken (Vorschläge der neu geplanten Woche ausgenommen)."""
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
    minuten: int  # noch nicht abgedeckte Stoffmenge


def offene_unterlagen(session: Session, woche: date) -> list[OffeneUnterlage]:
    """Aller Stoff, der bis zum Ende der Woche erschienen und noch nicht abgedeckt ist – egal wie alt."""
    von, bis = _wochengrenzen(woche)
    abgedeckt = abgedeckte_minuten(session, (von, bis))
    offen = []
    for doc in session.scalars(select(Dokument).where(Dokument.quelle.is_not("mbcloud"))):  # MB Cloud: nur Altprüfungen
        zeit = erscheinungszeit(doc)
        if zeit >= bis:
            continue
        rest = stoff_minuten(doc, doc.lva) - abgedeckt.get(doc.id, 0)
        if rest > 0:
            offen.append(OffeneUnterlage(doc.id, doc.lva_id, doc.dateiname, max(zeit, von), rest))
    session.flush()
    return sorted(offen, key=lambda o: (o.erschienen, o.dokument_id))


# --- Prüfungen ---------------------------------------------------------------------------------

def pruefungstermine(session: Session, lva: Lva, heute: date | None = None) -> list[tuple[datetime, str]]:
    """Prüfungen, zu denen man antritt, als (Zeitpunkt, Quelle), sortiert: Prüfungen aus dem TISS-Feed („tiss“, dort
    stehen nur angemeldete) und die angemeldeten Prüfungstermine (Quelle des Termins: tiss, tuwel, manuell); ein
    Termin am Tag einer Feed-Prüfung zählt nicht doppelt. Ist nichts angemeldet, gilt der nächste angebotene Termin
    als „vorschlag“, damit der Lernbedarf trotzdem ein Ziel hat."""
    aus_feed = list(session.scalars(
        select(Termin.start).where(Termin.lva_id == lva.id, Termin.typ == TYP_PRUEFUNG).order_by(Termin.start)
    ))
    feed_tage = {z.date() for z in aus_feed}
    termine = termine_der_lva(session, lva.id)
    angemeldet = [(t.start, t.quelle) for t in termine if ist_angemeldet(t, feed_tage) and t.start.date() not in feed_tage]
    ergebnis = sorted([(z, "tiss") for z in aus_feed] + angemeldet)
    if ergebnis:
        return ergebnis
    heute = heute or date.today()
    naechster = next((t for t in termine if t.start.date() >= heute and t.angemeldet is not False), None)
    return [(naechster.start, "vorschlag")] if naechster else []


def pruefungen(session: Session, lva: Lva) -> tuple[datetime, ...]:
    """Zeitpunkte aller Prüfungen der LVA (TISS und selbst eingetragen), sortiert."""
    return tuple(z for z, _ in pruefungstermine(session, lva))


# --- Lernbedarf je Woche ------------------------------------------------------------------------

def gelernte_minuten(block: Lernblock) -> int:
    """Eingetragene tatsächliche Zeit, sonst die geplante."""
    return block.tatsaechliche_minuten if block.tatsaechliche_minuten is not None else block.geplante_minuten


def lerntage_verfuegbar(regel: Arbeitsregel | None, von: date, bis: date, session: Session) -> dict[date, float]:
    """Je Woche der Anteil der Lerntage, die nicht gesperrt sind (Feiertage, Ferien, eigene freie Tage)."""
    lerntage = set(regel.lern_tage if regel and regel.lern_tage is not None else STANDARD_LERNTAGE) or set(range(7))
    gesperrt = gesperrte_tage(regel.freie_tage or [] if regel else [], montag(von), montag(bis) + timedelta(days=6), session)
    anteile = {}
    for w in wochen_von_bis(von, bis):
        tage = [w + timedelta(days=i) for i in range(7) if i in lerntage]
        anteile[w] = sum(1 for t in tage if t not in gesperrt) / len(tage)
    return anteile


def lva_plandaten(session: Session, lva: Lva, woche: date) -> LvaPlanDaten | None:
    """Alles, was lernbedarf.py über die LVA braucht; None ohne Termine und Prüfung."""
    termine = session.execute(
        select(Termin.start, Termin.ende, Termin.typ).where(Termin.lva_id == lva.id)
    ).all()
    unterricht = [(s, e) for s, e, typ in termine if typ not in (TYP_PRUEFUNG, TYP_ABGABE)]
    zeitpunkte = pruefungen(session, lva)
    if not unterricht and not zeitpunkte:
        return None
    alle = [s for s, _ in unterricht] + list(zeitpunkte)
    erste = montag(min(alle).date())
    letzte = montag(max(s for s, _ in unterricht).date()) if unterricht else montag(max(zeitpunkte).date())

    von, _ = _wochengrenzen(woche)
    bloecke = list(session.scalars(select(Lernblock).where(Lernblock.lva_id == lva.id)))
    erste_planwoche = montag(min(b.start for b in bloecke).date()) if bloecke else None
    gelernt = sum(gelernte_minuten(b) for b in bloecke if b.start < von)
    je_woche: dict[date, int] = {}
    for b in bloecke:
        if b.start < von:
            w = montag(b.start.date())
            je_woche[w] = je_woche.get(w, 0) + gelernte_minuten(b)
    return LvaPlanDaten(
        lva_id=lva.id,
        name=lva.anzeigename,
        ects=lva.ects,
        praesenz_minuten=int(sum((e - s).total_seconds() for s, e in unterricht) // 60),
        erste_woche=erste,
        letzte_woche=letzte,
        pruefungen=tuple(sorted(z.date() for z in zeitpunkte)),
        ziel=lva.ziel or "normal",
        anpassung=1.0 if lva.bedarf_faktor is None else lva.bedarf_faktor,
        erste_planwoche=erste_planwoche,
        gelernt_vorher=gelernt,
        lernwochen=lva.lernwochen,
        gelernt_je_woche=je_woche,
    )


def _regelwerte(regel: Arbeitsregel | None) -> tuple[float, int]:
    ects_faktor = regel.ects_faktor if regel and regel.ects_faktor is not None else STANDARD_ECTS_FAKTOR
    lernphase = regel.lernphase_wochen if regel and regel.lernphase_wochen is not None else STANDARD_LERNPHASE_WOCHEN
    return ects_faktor, lernphase


def bedarf_einer_lva(session: Session, lva: Lva, woche: date, regel: Arbeitsregel | None) -> tuple[BedarfWoche, LvaPlanDaten] | None:
    daten = lva_plandaten(session, lva, woche)
    if daten is None:
        return None
    ects_faktor, lernphase = _regelwerte(regel)
    verfuegbar = lerntage_verfuegbar(regel, daten.erste_woche, daten.ende_woche, session)
    return bedarf_fuer_woche(daten, woche, ects_faktor, lernphase, verfuegbar), daten


def wochenbedarf(session: Session, woche: date, regel: Arbeitsregel | None = None) -> list[tuple[BedarfWoche, LvaPlanDaten]]:
    """Lernbedarf aller LVAs, die in dieser Woche laufen oder noch eine Prüfung vor sich haben."""
    from .lva_auswahl import besuchte_lva_ids

    ergebnis = []
    for lva in session.scalars(select(Lva).where(Lva.id.in_(besuchte_lva_ids(session)))):  # ausgeblendete: kein Bedarf
        eintrag = bedarf_einer_lva(session, lva, woche, regel)
        if eintrag is None:
            continue
        bedarf, _ = eintrag
        if bedarf.lernphase:  # nur in den Lernfenstern vor Prüfungen
            ergebnis.append(eintrag)
    return sorted(ergebnis, key=lambda e: e[0].lva_name)


def typischer_wochenbedarf(session: Session, lva: Lva, regel: Arbeitsregel | None) -> tuple[int, int]:
    """(Gesamtbedarf, Bedarf einer Woche im Lernfenster vor einer Prüfung) in Minuten – für die LVA-Liste."""
    daten = lva_plandaten(session, lva, date.today())
    if daten is None:
        return 0, 0
    ects_faktor, lernphase = _regelwerte(regel)
    gesamt = gesamtbedarf_minuten(daten.ects, daten.praesenz_minuten, ects_faktor, daten.ziel, daten.anpassung)
    gewichte = wochengewichte(daten, lernphase, lerntage_verfuegbar(regel, daten.erste_woche, daten.ende_woche, session))
    summe = sum(gewichte.values())
    return gesamt, round(gesamt / summe) if summe else 0


def stunden(minuten: int | float) -> str:
    return f"{minuten / 60:.1f}".replace(".", ",") + " h"

