"""Prüfungsstoff (reine Logik, ohne Datenbank): Themen aus einer hochgeladenen Datei und Zeitabschnitte je Prüfung.

Der Stoff einer Prüfung kann eine Stoffliste sein (Stoffabgrenzung, Kapitelliste: jede Zeile ein Thema) oder die
Unterlage selbst (Skript: Kapitel der obersten Ebene; Foliensatz: Folientitel). `themen_aus_text` erkennt das an
dem, was extraktion.lesen liefert. Der Zeitstrahl im Wissensstand teilt das Semester an den Prüfungen in Abschnitte:
jeder Abschnitt endet mit „seiner“ Prüfung.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta

from .extraktion import Text

MAX_THEMEN = 60
MIN_LAENGE, MAX_LAENGE = 3, 120
# Zeilen, die eine Liste einleiten oder Folien ohne Inhalt betiteln – keine Themen
KEIN_THEMA = re.compile(
    r"^(prüfungs?stoff|stoff(abgrenzung|umfang)?|inhalt(sverzeichnis)?|themen(liste)?|agenda|überblick|outline|"
    r"gliederung|literatur|quellen|references|danke.*|fragen\??|vielen dank.*|kontakt|seite \d+.*|\d+ ?/ ?\d+)$",
    re.IGNORECASE,
)
AUFZAEHLUNG = re.compile(r"^\s*(?:[-–—•·*▪◦►‣]+|\(?[0-9]{1,2}(?:\.[0-9]{1,2})*[.)]?|\(?[a-zA-Z][.)]|[IVX]{1,4}[.)])\s+")


def titel_bereinigen(zeile: str) -> str:
    """„2.3 Reibung“, „- Reibung“, „b) Reibung:“ -> „Reibung“."""
    zeile = re.sub(r"\s+", " ", zeile).strip()
    for _ in range(3):  # „• Kapitel 4 Kinematik“: Zeichen, „Kapitel“, Nummer – in beliebiger Folge
        vorher = zeile
        zeile = re.sub(r"^\s*(kapitel|chapter)\s+", "", AUFZAEHLUNG.sub("", zeile), flags=re.IGNORECASE)
        if zeile == vorher:
            break
    zeile = re.sub(r"\s*\.{3,}\s*\d*$", "", zeile)  # „Reibung ........ 23“ aus Inhaltsverzeichnissen
    return zeile.strip(" :;,–-")


def _sammeln(kandidaten: list[str]) -> list[str]:
    themen, gesehen = [], set()
    for k in kandidaten:
        titel = titel_bereinigen(k)
        schluessel = titel.casefold()
        if not MIN_LAENGE <= len(titel) <= MAX_LAENGE or KEIN_THEMA.match(titel) or schluessel in gesehen:
            continue
        if sum(z.isalpha() for z in titel) < 3:  # nur Zahlen, Formeln, Seitenangaben
            continue
        gesehen.add(schluessel)
        themen.append(titel)
        if len(themen) >= MAX_THEMEN:
            break
    return themen


def themen_aus_text(text: Text) -> list[str]:
    """Themen in Reihenfolge: Gliederung (oberste Ebene, bei wenigen Kapiteln mit Unterkapiteln), sonst Folientitel,
    sonst jede Zeile der Stoffliste."""
    if len(text.gliederung) >= 2:
        oben = min(p.ebene for p in text.gliederung)
        ebenen = {oben} if sum(1 for p in text.gliederung if p.ebene == oben) >= 3 else {oben, oben + 1}
        themen = _sammeln([p.titel for p in text.gliederung if p.ebene in ebenen])
        if len(themen) >= 2:
            return themen
    if text.art == "folien":
        titel = [next((z for z in s.splitlines() if z.strip()), "") for _, s in text.seiten]
        # Kopfzeilen, die auf fast jeder Folie stehen (LVA-Name, Logo-Text), sind keine Themen
        haeufig = {t for t, n in Counter(titel_bereinigen(t).casefold() for t in titel).items() if n > max(3, len(titel) // 3)}
        return _sammeln([t for t in titel if titel_bereinigen(t).casefold() not in haeufig])
    # Stoffliste; „Stoff für den 1. Test:“ (ohne Aufzählungszeichen, mit Doppelpunkt) leitet nur ein
    zeilen = [z for _, s in text.seiten for z in s.splitlines()]
    return _sammeln([z for z in zeilen if not (z.rstrip().endswith(":") and not AUFZAEHLUNG.match(z))])


# --- Zeitabschnitte zwischen Prüfungen -------------------------------------------------------------

@dataclass(frozen=True)
class Zeitabschnitt:
    von: date
    bis: date  # Prüfungstag
    zeit_anteil: float  # wie viel des Abschnitts heute vorbei ist (0–1)
    vorbei: bool


def zeitabschnitte(beginn: date, pruefungen: list[date], heute: date) -> list[Zeitabschnitt]:
    """Je Prüfung der Abschnitt seit der vorigen Prüfung (bzw. seit `beginn`) bis zum Prüfungstag."""
    abschnitte = []
    von = beginn
    for tag in sorted(set(pruefungen)):
        start = min(von, tag)
        dauer = max((tag - start).days, 1)
        anteil = min(max((heute - start).days / dauer, 0.0), 1.0)
        abschnitte.append(Zeitabschnitt(start, tag, round(anteil, 2), heute > tag))
        von = tag + timedelta(days=1)
    return abschnitte
