"""Gesetzliche Feiertage in Österreich und zusätzliche freie Tage aus der Arbeitsregel.

An all diesen Tagen werden keine Arbeitszeiten vorgeschlagen.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta

import holidays

LAND = "AT"


def feiertage(von: date, bis: date) -> dict[date, str]:
    """Gesetzliche Feiertage im Zeitraum [von, bis] (beide inklusive) mit Namen."""
    if bis < von:
        return {}
    kalender = holidays.country_holidays(LAND, years=range(von.year, bis.year + 1), language="de")
    return {tag: name for tag, name in sorted(kalender.items()) if von <= tag <= bis}


def _tage(von: date, bis: date) -> Iterable[date]:
    tag = von
    while tag <= bis:
        yield tag
        tag += timedelta(days=1)


def freie_tage_expandieren(eintraege: Iterable[dict], von: date, bis: date) -> dict[date, str]:
    """Wandelt die freien Tage der Arbeitsregel in konkrete Tage im Zeitraum [von, bis] um.

    Ein Eintrag hat die Felder `von`, optional `bis` (für Zeiträume wie Urlaub), `bezeichnung`
    und `jaehrlich`. Jährliche Einträge (z. B. 24.12.) gelten in jedem Jahr am selben Kalendertag.
    """
    ergebnis: dict[date, str] = {}
    for eintrag in eintraege:
        start = _als_datum(eintrag["von"])
        ende = _als_datum(eintrag.get("bis") or eintrag["von"])
        bezeichnung = eintrag.get("bezeichnung") or "frei"
        if eintrag.get("jaehrlich"):
            for jahr in range(von.year - 1, bis.year + 1):
                try:
                    j_start = start.replace(year=jahr)
                    # Zeiträume über den Jahreswechsel (z. B. 24.12.–6.1.) enden im Folgejahr
                    j_ende = ende.replace(year=jahr + (ende.year - start.year))
                except ValueError:  # 29.02. in einem Nicht-Schaltjahr
                    continue
                for tag in _tage(max(j_start, von), min(j_ende, bis)):
                    ergebnis.setdefault(tag, bezeichnung)
        else:
            for tag in _tage(max(start, von), min(ende, bis)):
                ergebnis.setdefault(tag, bezeichnung)
    return dict(sorted(ergebnis.items()))


def tiss_freie_tage(session, von: date, bis: date) -> dict[date, str]:
    """Vorlesungsfreie Zeiten aus TISS (Ferien, Rektorstag …) als einzelne Tage im Zeitraum."""
    from sqlalchemy import select

    from .models import FreierZeitraum

    tage: dict[date, str] = {}
    abfrage = select(FreierZeitraum).where(FreierZeitraum.von <= bis, FreierZeitraum.bis >= von)
    for zeitraum in session.scalars(abfrage):
        for tag in _tage(max(zeitraum.von, von), min(zeitraum.bis, bis)):
            tage.setdefault(tag, zeitraum.bezeichnung)
    return tage


def gesperrte_tage(eintraege: Iterable[dict], von: date, bis: date, session=None) -> dict[date, str]:
    """Feiertage, eigene freie Tage und (mit Session) vorlesungsfreie Zeiten aus TISS."""
    gesperrt = freie_tage_expandieren(eintraege, von, bis)
    if session is not None:
        gesperrt.update(tiss_freie_tage(session, von, bis))
    gesperrt.update(feiertage(von, bis))  # Feiertagsnamen haben Vorrang
    return dict(sorted(gesperrt.items()))


def _als_datum(wert: date | str) -> date:
    return wert if isinstance(wert, date) else date.fromisoformat(wert)
