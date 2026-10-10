"""Verteilungs-Algorithmus für flexible Arbeitszeiten.

Umsetzung von KONZEPT.md, Abschnitt „Flexible Arbeitszeiten verteilen“:

1. Sperrzeiten sammeln: Pflichttermine (Anwesenheitspflicht, Prüfungen) mit Wegpuffer und
   bestätigte Arbeitsblöcke.
2. Weiche Termine gewichten: aufgezeichnete Termine ohne Anwesenheitspflicht dürfen überplant
   werden; nicht aufgezeichnete nur in einer zweiten Runde, wenn die Stunden sonst nicht reichen.
3. Lücken finden: pro erlaubtem Tag die freien Fenster zwischen frühestem Beginn und spätestem Ende.
4. Lücken bewerten: lange Blöcke vor kurzen, wenige Wechsel Uni/Arbeit, bevorzugte Tage zuerst.
5. Stunden verteilen: beste Lücken füllen, Mindest- und Maximallänge einhalten.
6. Das Ergebnis ist ein Vorschlag; das Speichern übernimmt `planung_service`.

Das Modul greift nicht auf die Datenbank zu und ist deshalb isoliert testbar.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

RASTER = timedelta(minutes=15)
PAUSE = timedelta(minutes=30)  # Mindestabstand zwischen zwei Arbeitsblöcken
NULL = timedelta(0)


@dataclass(frozen=True)
class Intervall:
    start: datetime
    ende: datetime

    @property
    def dauer(self) -> timedelta:
        return self.ende - self.start

    def ueberschneidet(self, anderes: Intervall) -> bool:
        return self.start < anderes.ende and anderes.start < self.ende

    def erweitert(self, puffer: timedelta) -> Intervall:
        return Intervall(self.start - puffer, self.ende + puffer)


@dataclass(frozen=True)
class PlanTermin:
    """Ein Uni-Termin, wie ihn der Algorithmus sieht (effektive Markierungen)."""

    start: datetime
    ende: datetime
    titel: str = ""
    anwesenheitspflicht: bool = False
    aufzeichnung: bool = False
    pruefung: bool = False
    termin_id: int | None = None

    @property
    def intervall(self) -> Intervall:
        return Intervall(self.start, self.ende)

    @property
    def ist_pflicht(self) -> bool:
        return self.pruefung or self.anwesenheitspflicht


@dataclass(frozen=True)
class Arbeitsregeln:
    stunden_pro_woche: float
    tage: frozenset[int] = frozenset({0, 1, 2, 3, 4})
    bevorzugte_tage: frozenset[int] = frozenset()
    fruehester_beginn: time = time(8, 0)
    spaetestes_ende: time = time(18, 0)
    min_block: timedelta = timedelta(hours=2)
    max_block: timedelta = timedelta(hours=8)
    puffer: timedelta = timedelta(minutes=30)


@dataclass
class Vorschlag:
    intervall: Intervall
    # weiche Termine, die dieser Block überdeckt
    ueberplante_termine: list[PlanTermin] = field(default_factory=list)


@dataclass
class Verteilung:
    soll: timedelta  # noch zu verteilende Zeit nach Abzug bestätigter Blöcke
    bloecke: list[Vorschlag] = field(default_factory=list)
    # nicht aufgezeichnete weiche Termine, die für die Stunden geopfert werden müssten
    geopferte_termine: list[PlanTermin] = field(default_factory=list)

    @property
    def verplant(self) -> timedelta:
        return sum((b.intervall.dauer for b in self.bloecke), NULL)

    @property
    def fehlend(self) -> timedelta:
        return max(self.soll - self.verplant, NULL)


def wochenbeginn(tag: date) -> date:
    """Liefert den Montag der Woche, in der `tag` liegt."""
    return tag - timedelta(days=tag.weekday())


def _auf_raster(dt: datetime, aufrunden: bool) -> datetime:
    mitternacht = datetime.combine(dt.date(), time())
    schritte, rest = divmod(dt - mitternacht, RASTER)
    if rest and aufrunden:
        schritte += 1
    return mitternacht + schritte * RASTER


def _dauer_abrunden(dauer: timedelta) -> timedelta:
    return (dauer // RASTER) * RASTER


def vereinige(intervalle: Iterable[Intervall]) -> list[Intervall]:
    """Fasst überlappende oder aneinanderstoßende Intervalle zusammen (sortiert)."""
    ergebnis: list[Intervall] = []
    for iv in sorted(intervalle, key=lambda i: i.start):
        if ergebnis and iv.start <= ergebnis[-1].ende:
            letztes = ergebnis[-1]
            ergebnis[-1] = Intervall(letztes.start, max(letztes.ende, iv.ende))
        else:
            ergebnis.append(iv)
    return ergebnis


def abziehen(fenster: Intervall, sperren: Iterable[Intervall]) -> list[Intervall]:
    """Zieht die Sperrzeiten vom Fenster ab und liefert die freien Teilstücke."""
    frei: list[Intervall] = []
    cursor = fenster.start
    for sperre in vereinige(sperren):
        if sperre.ende <= cursor or sperre.start >= fenster.ende:
            continue
        if sperre.start > cursor:
            frei.append(Intervall(cursor, sperre.start))
        cursor = max(cursor, sperre.ende)
    if cursor < fenster.ende:
        frei.append(Intervall(cursor, fenster.ende))
    return frei


def finde_luecken(woche_start: date, regeln: Arbeitsregeln, sperren: list[Intervall]) -> Iterator[Intervall]:
    """Schritt 3: freie Fenster je erlaubtem Arbeitstag, auf 15 Minuten gerundet."""
    for i in range(7):
        tag = woche_start + timedelta(days=i)
        if tag.weekday() not in regeln.tage:
            continue
        fenster = Intervall(
            datetime.combine(tag, regeln.fruehester_beginn), datetime.combine(tag, regeln.spaetestes_ende)
        )
        if fenster.dauer <= NULL:
            continue
        for stueck in abziehen(fenster, sperren):
            luecke = Intervall(_auf_raster(stueck.start, True), _auf_raster(stueck.ende, False))
            if luecke.dauer >= regeln.min_block:
                yield luecke


def blocklaenge(luecke: timedelta, bedarf: timedelta, regeln: Arbeitsregeln) -> timedelta | None:
    """Länge des nächsten Blocks in einer Lücke, oder None wenn kein gültiger Block passt.

    Bleibt nach dem Block ein Rest unter der Mindestlänge, wird der Block so gekürzt, dass der
    Rest einen eigenen gültigen Block ergibt.
    """
    laenge = min(luecke, regeln.max_block, bedarf)
    rest = bedarf - laenge
    if NULL < rest < regeln.min_block:
        kuerzer = bedarf - regeln.min_block
        if kuerzer >= regeln.min_block:
            laenge = min(laenge, kuerzer)
    laenge = _dauer_abrunden(laenge)
    return laenge if laenge >= regeln.min_block else None


def bewerte_luecke(
    luecke: Intervall,
    bedarf: timedelta,
    regeln: Arbeitsregeln,
    uni_tage: Counter,
    arbeit_tage: Counter,
) -> float:
    """Schritt 4: höhere Punktzahl = bessere Lücke."""
    tag = luecke.start.date()
    punkte = min(luecke.dauer, regeln.max_block, bedarf) / timedelta(hours=1)  # lange Blöcke zuerst
    if tag.weekday() in regeln.bevorzugte_tage:
        punkte += 2
    if uni_tage[tag]:
        punkte -= 1  # Arbeit an einem Uni-Tag bedeutet Wechsel
    if arbeit_tage[tag]:
        punkte -= 1.5  # ein zweiter Arbeitsblock am selben Tag bedeutet weitere Wechsel
    return punkte


def fuelle_luecken(
    woche_start: date,
    regeln: Arbeitsregeln,
    sperren: list[Intervall],
    bedarf: timedelta,
    uni_tage: Counter,
    arbeit_tage: Counter,
) -> list[Intervall]:
    """Schritt 5: füllt die jeweils beste Lücke, bis der Bedarf gedeckt ist oder nichts mehr passt."""
    luecken = list(finde_luecken(woche_start, regeln, sperren))
    neue: list[Intervall] = []
    while bedarf > NULL and luecken:
        luecken.sort(key=lambda l: (-bewerte_luecke(l, bedarf, regeln, uni_tage, arbeit_tage), l.start))
        for index, luecke in enumerate(luecken):
            laenge = blocklaenge(luecke.dauer, bedarf, regeln)
            if laenge is not None:
                break
        else:
            break
        luecken.pop(index)
        block = Intervall(luecke.start, luecke.start + laenge)
        rest = Intervall(block.ende + PAUSE, luecke.ende)
        if rest.dauer >= regeln.min_block:
            luecken.append(rest)
        neue.append(block)
        arbeit_tage[block.start.date()] += 1
        bedarf -= laenge
    return neue


def verteile_arbeitszeit(
    woche: date,
    regeln: Arbeitsregeln,
    termine: Iterable[PlanTermin],
    bestaetigte_bloecke: Iterable[Intervall],
) -> Verteilung:
    """Berechnet den Vorschlag für die flexiblen Arbeitsblöcke einer Woche."""
    woche_start = wochenbeginn(woche)
    woche_iv = Intervall(datetime.combine(woche_start, time()), datetime.combine(woche_start + timedelta(days=7), time()))
    termine = [t for t in termine if t.intervall.ueberschneidet(woche_iv)]
    bestehend = [b for b in bestaetigte_bloecke if b.ueberschneidet(woche_iv)]

    gesamt = _dauer_abrunden(timedelta(hours=regeln.stunden_pro_woche))
    bereits = sum((min(b.ende, woche_iv.ende) - max(b.start, woche_iv.start) for b in bestehend), NULL)
    bedarf = _dauer_abrunden(max(gesamt - bereits, NULL))
    verteilung = Verteilung(soll=bedarf)
    if bedarf <= NULL:
        return verteilung

    # Schritt 1 und 2: Sperrzeiten und weiche Termine
    pflicht = [t for t in termine if t.ist_pflicht]
    weich_ohne_aufzeichnung = [t for t in termine if not t.ist_pflicht and not t.aufzeichnung]
    weich_mit_aufzeichnung = [t for t in termine if not t.ist_pflicht and t.aufzeichnung]
    sperren = [t.intervall.erweitert(regeln.puffer) for t in pflicht]
    sperren += [b.erweitert(PAUSE) for b in bestehend]

    uni_tage = Counter(t.start.date() for t in pflicht + weich_ohne_aufzeichnung)
    arbeit_tage = Counter(b.start.date() for b in bestehend)

    # Runde 1: nicht aufgezeichnete weiche Termine bleiben gesperrt
    runde1 = fuelle_luecken(
        woche_start,
        regeln,
        sperren + [t.intervall.erweitert(regeln.puffer) for t in weich_ohne_aufzeichnung],
        bedarf,
        uni_tage,
        arbeit_tage,
    )
    bedarf -= sum((b.dauer for b in runde1), NULL)

    # Runde 2: nur wenn die Stunden nicht reichen, dürfen auch diese Termine überplant werden
    runde2: list[Intervall] = []
    if bedarf > NULL and weich_ohne_aufzeichnung:
        runde2 = fuelle_luecken(
            woche_start,
            regeln,
            sperren + [b.erweitert(PAUSE) for b in runde1],
            bedarf,
            uni_tage,
            arbeit_tage,
        )

    for block in sorted(runde1 + runde2, key=lambda b: b.start):
        ueberplant = [t for t in weich_ohne_aufzeichnung if t.intervall.erweitert(regeln.puffer).ueberschneidet(block)]
        ueberplant += [t for t in weich_mit_aufzeichnung if t.intervall.ueberschneidet(block)]
        verteilung.bloecke.append(Vorschlag(block, sorted(ueberplant, key=lambda t: t.start)))

    verteilung.geopferte_termine = [
        t
        for t in weich_ohne_aufzeichnung
        if any(t.intervall.erweitert(regeln.puffer).ueberschneidet(b) for b in runde2)
    ]
    return verteilung
