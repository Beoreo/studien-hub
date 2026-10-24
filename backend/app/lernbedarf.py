"""Lernbedarf je LVA und Woche aus den ECTS (reine Logik, ohne Datenbank).

Ziel ist das Minimum, das das Studium machbar hält, nicht das Maximum:

    Gesamtbedarf = (ECTS × 25 h − Präsenzstunden) × ECTS-Faktor × Zielfaktor × Anpassung

- ECTS-Faktor (Arbeitsregel, Standard 0,7): ECTS-Werte sind meist zu hoch angesetzt.
- Zielfaktor je LVA: „bestehen“ 0,6, „normal“ 0,8, „gute Note“ 1,0.
- Anpassung je LVA: Regler in der LVA-Liste (1,0 = unverändert).

Gelernt wird nur vor Prüfungen: Der Gesamtbedarf verteilt sich auf die Lernfenster – je Prüfung die
Prüfungswoche und die `lernwochen` Wochen davor (je LVA einstellbar, Standard aus der Arbeitsregel).
Ohne Prüfung gibt es keinen Lernbedarf. Wochen mit gesperrten Lerntagen (Ferien, Feiertage) zählen
anteilig weniger.

Was in früheren Wochen eines Fensters nicht gelernt wurde (oder mehr), verteilt sich auf die
verbleibenden Wochen bis zur Prüfung. Gezählt wird ab der ersten Woche, in der der Hub für die LVA
Lernblöcke hatte – Wochen vor der Nutzung des Hubs erzeugen keinen Rückstand.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

STUNDEN_PRO_ECTS = 25
ZIELE = {"bestehen": 0.6, "normal": 0.8, "gut": 1.0}
STANDARD_ZIEL = "normal"
STANDARD_ECTS_FAKTOR = 0.7
STANDARD_LERNPHASE_WOCHEN = 2  # Wochen vor der Prüfungswoche, in denen gelernt wird
WOCHE = timedelta(days=7)


def montag(tag: date) -> date:
    return tag - timedelta(days=tag.weekday())


def gesamtbedarf_minuten(
    ects: float | None, praesenz_minuten: int, ects_faktor: float = STANDARD_ECTS_FAKTOR,
    ziel: str | None = STANDARD_ZIEL, anpassung: float | None = 1.0,
) -> int:
    """Lernminuten fürs ganze Semester; ohne ECTS 0."""
    if not ects:
        return 0
    selbststudium = max(ects * STUNDEN_PRO_ECTS * 60 - praesenz_minuten, 0)
    faktor = ects_faktor * ZIELE.get(ziel or STANDARD_ZIEL, ZIELE[STANDARD_ZIEL]) * (1.0 if anpassung is None else anpassung)
    return round(selbststudium * max(faktor, 0))


@dataclass(frozen=True)
class LvaPlanDaten:
    """Was die Bedarfsrechnung über eine LVA wissen muss."""

    lva_id: int
    name: str
    ects: float | None
    praesenz_minuten: int  # alle Termine des Semesters außer Prüfungen und Abgaben
    erste_woche: date  # Montag der ersten Woche mit Termin
    letzte_woche: date  # Montag der letzten Woche mit Termin (ohne Prüfungen)
    pruefungen: tuple[date, ...] = ()
    ziel: str = STANDARD_ZIEL
    anpassung: float = 1.0
    erste_planwoche: date | None = None  # erste Woche mit Lernblöcken dieser LVA
    gelernt_vorher: int = 0  # Lernminuten ab `erste_planwoche` bis vor die betrachtete Woche
    lernwochen: int | None = None  # eigene Fensterlänge der LVA; None = Wert der Arbeitsregel
    gelernt_je_woche: dict[date, int] = field(default_factory=dict)  # Montag -> gelernte Minuten (vor der Woche)

    @property
    def ende_woche(self) -> date:
        """Bis hierher wird gelernt: Woche der letzten Prüfung, sonst die letzte Terminwoche."""
        return montag(max(self.pruefungen)) if self.pruefungen else self.letzte_woche


def wochen_von_bis(von: date, bis: date) -> list[date]:
    wochen, w = [], montag(von)
    while w <= montag(bis):
        wochen.append(w)
        w += WOCHE
    return wochen


def naechste_pruefung(pruefungen: tuple[date, ...], ab: date) -> date | None:
    return next((p for p in sorted(pruefungen) if p >= ab), None)


def in_lernphase(woche: date, pruefungen: tuple[date, ...], lernphase_wochen: int) -> bool:
    """Liegt die Woche im Lernfenster einer Prüfung: Prüfungswoche oder bis zu `lernphase_wochen` Wochen davor?"""
    pruefung = naechste_pruefung(pruefungen, montag(woche))
    if pruefung is None or lernphase_wochen <= 0:
        return False
    return (montag(pruefung) - montag(woche)).days // 7 <= lernphase_wochen


def fensterwochen(daten: LvaPlanDaten, lernphase_wochen: int) -> int:
    return lernphase_wochen if daten.lernwochen is None else daten.lernwochen


def wochengewichte(
    daten: LvaPlanDaten, lernphase_wochen: int, verfuegbar: dict[date, float] | None = None
) -> dict[date, float]:
    """Gewicht jeder Woche in den Lernfenstern vor den Prüfungen; `verfuegbar` = Anteil nicht gesperrter
    Lerntage (0–1). Wochen außerhalb der Fenster kommen nicht vor."""
    verfuegbar = verfuegbar or {}
    n = fensterwochen(daten, lernphase_wochen)
    if not daten.pruefungen or n <= 0:
        return {}
    gewichte = {}
    # frühestens ab dem ersten Termin der LVA: vor dem Semester gibt es nichts zu lernen
    beginn = max(montag(min(daten.pruefungen)) - WOCHE * n, daten.erste_woche)
    for w in wochen_von_bis(beginn, daten.ende_woche):
        if in_lernphase(w, daten.pruefungen, n):
            gewichte[w] = verfuegbar.get(w, 1.0)
    return gewichte


@dataclass
class BedarfWoche:
    lva_id: int
    lva_name: str
    gesamt_minuten: int  # Semesterbedarf
    plan_minuten: int  # Anteil dieser Woche ohne Nachholen
    soll_minuten: int  # Anteil dieser Woche inklusive Nachholen (oder abzüglich Vorsprung)
    rueckstand_minuten: int  # positiv = hinter dem Plan
    pruefung: date | None  # nächste Prüfung ab dieser Woche
    lernphase: bool
    stoff_anteil: float  # Anteil des offenen Stoffs, der diese Woche dran ist
    ohne_ects: bool = False

    woche: date | None = None  # Montag der betrachteten Woche

    @property
    def prioritaet(self) -> int:
        """Wochen bis zur Prüfung (0 = Prüfungswoche): je näher, desto später wird gekürzt."""
        if self.pruefung is None or self.woche is None:
            return 99
        return max((montag(self.pruefung) - self.woche).days // 7, 0)


def bedarf_fuer_woche(
    daten: LvaPlanDaten, woche: date, ects_faktor: float = STANDARD_ECTS_FAKTOR,
    lernphase_wochen: int = STANDARD_LERNPHASE_WOCHEN, verfuegbar: dict[date, float] | None = None,
) -> BedarfWoche:
    """Lernbedarf einer LVA in einer Woche."""
    woche = montag(woche)
    gesamt = gesamtbedarf_minuten(daten.ects, daten.praesenz_minuten, ects_faktor, daten.ziel, daten.anpassung)
    gewichte = wochengewichte(daten, lernphase_wochen, verfuegbar)
    summe = sum(gewichte.values())
    pruefung = naechste_pruefung(daten.pruefungen, woche)
    lernphase = in_lernphase(woche, daten.pruefungen, fensterwochen(daten, lernphase_wochen))
    ergebnis = BedarfWoche(
        daten.lva_id, daten.name, gesamt, 0, 0, 0, pruefung, lernphase,
        _stoff_anteil(daten, woche), ohne_ects=not daten.ects, woche=woche,
    )
    if woche not in gewichte or summe <= 0 or gesamt <= 0:
        return ergebnis

    def anteil(wochen) -> float:
        return gesamt * sum(gewichte[w] for w in wochen) / summe

    # Rückstand und Nachholen nur innerhalb des Fensters dieser Prüfung – ein früheres Fenster ist abgeschlossen
    start = min(daten.erste_planwoche or woche, woche)
    pruefungswoche = montag(pruefung) if pruefung else woche
    fenster = [w for w in gewichte if naechste_pruefung(daten.pruefungen, w) == pruefung]
    vorher = [w for w in fenster if start <= w < woche]
    ab_jetzt = [w for w in fenster if woche <= w <= pruefungswoche]
    # gelernt in den bisherigen Wochen dieses Fensters (ohne Angabe je Woche: alles bisher Gelernte)
    gelernt = sum(daten.gelernt_je_woche.get(w, 0) for w in vorher) if daten.gelernt_je_woche else daten.gelernt_vorher
    soll_bisher = anteil(vorher)
    rest = anteil(vorher + ab_jetzt) - (gelernt if vorher else 0)
    gewicht_rest = sum(gewichte[w] for w in ab_jetzt)
    ergebnis.plan_minuten = round(anteil([woche]))
    ergebnis.soll_minuten = round(max(rest, 0) * gewichte[woche] / gewicht_rest) if gewicht_rest else 0
    ergebnis.rueckstand_minuten = round(soll_bisher - gelernt) if vorher else 0
    return ergebnis


def _stoff_anteil(daten: LvaPlanDaten, woche: date) -> float:
    """Offener Stoff verteilt sich auf die Wochen bis zur nächsten Prüfung."""
    pruefung = naechste_pruefung(daten.pruefungen, woche)
    ziel = montag(pruefung) if pruefung is not None else daten.letzte_woche
    wochen = (ziel - woche).days // 7 + 1
    return 1.0 / max(wochen, 1)


def nachholen_pro_woche(minuten: int, daten: LvaPlanDaten, woche: date) -> tuple[int, date | None]:
    """Verteilt einen Rückstand auf die Wochen nach `woche` bis zur Prüfung: (Minuten pro Woche, bis)."""
    pruefung = naechste_pruefung(daten.pruefungen, montag(woche) + WOCHE) or naechste_pruefung(daten.pruefungen, woche)
    bis = montag(pruefung) if pruefung else daten.ende_woche
    wochen = max((bis - montag(woche)).days // 7, 1)
    return round(minuten / wochen), pruefung
