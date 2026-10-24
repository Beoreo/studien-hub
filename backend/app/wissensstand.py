"""Wissensstand je Thema (Stufe 0–4) und verteilte Wiederholung – reine Logik ohne Datenbank.

Stufen: 0 neu · 1 gesehen · 2 mit Hilfe lösbar · 3 sicher · 4 prüfungsfest.
Nach einem Lernereignis mit Ergebnis (0–1, z. B. Quiz- oder Prüfungspunkte):
- ab 80 %: eine Stufe hinauf,
- 50–80 %: Stufe bleibt (mindestens 1),
- unter 50 %: eine Stufe hinunter.
Die nächste Wiederholung folgt nach `INTERVALLE[stufe]` Tagen, spätestens am Tag vor der Prüfung.
"""

from __future__ import annotations

from datetime import date, timedelta

STUFEN = {0: "neu", 1: "gesehen", 2: "mit Hilfe", 3: "sicher", 4: "prüfungsfest"}
INTERVALLE = {0: 1, 1: 2, 2: 4, 3: 9, 4: 21}  # Tage bis zur nächsten Wiederholung
ARTEN = ("quiz", "altpruefung", "selbsteinschaetzung", "lernblock")


def neue_stufe(stufe: int, ergebnis: float) -> int:
    if ergebnis >= 0.8:
        return min(stufe + 1, 4)
    if ergebnis >= 0.5:
        return max(stufe, 1)
    return max(stufe - 1, 0)


def naechste_wiederholung(stufe: int, heute: date, pruefung: date | None = None) -> date:
    termin = heute + timedelta(days=INTERVALLE[max(0, min(stufe, 4))])
    if pruefung and heute < pruefung:
        termin = max(min(termin, pruefung - timedelta(days=1)), heute + timedelta(days=1))
    return termin


def faellig(naechste: date | None, heute: date) -> bool:
    return naechste is not None and naechste <= heute
