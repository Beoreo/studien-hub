"""Verteilungs-Algorithmus für flexible Arbeitszeiten.

Ziel ist nicht, die Stunden möglichst früh unterzubringen, sondern die entspannteste und
effizienteste Woche fürs Studium. Dazu wird jede mögliche Verteilung bewertet und die beste gewählt:

1. Pro Tag werden alle sinnvollen Tagespläne erzeugt (kein Block, ein oder zwei Blöcke in
   verschiedenen Längen und Lagen innerhalb der freien Lücken).
2. Jeder Tagesplan bekommt Kosten nach den Kriterien unten.
3. Eine dynamische Programmierung über die sieben Tage findet die Kombination mit den geringsten
   Gesamtkosten (= höchste Punktzahl), die die Wochenstunden erreicht.

Harte Regeln (werden nie verletzt):
- Pflichttermine (Anwesenheitspflicht, Prüfungen) mit Wegpuffer, bestätigte Blöcke, Feiertage
  und freie Tage, erlaubte Tage und Uhrzeiten, Mindest- und Maximallänge pro Block.
- Tagesgrenze: Uni plus Arbeit höchstens `max_tag` pro Tag.
- Lernfenster vor Prüfungen und Abgaben am selben Tag; am Vortag bleibt mindestens ein
  Lernfenster frei.
- Kein Arbeitsblock am Abend nach einem vollen Unitag.

Gewichtete Kriterien (`Gewichte`, je 0–10):
- gleichmaessig: Uni plus Arbeit pro Tag möglichst ähnlich (Summe der quadrierten Tageslast).
- buendeln: wenige Wechsel zwischen Uni und Arbeit, Arbeit bevorzugt an Tagen ohne Uni.
- lernzeit: Tag vor einer Prüfung oder Abgabe möglichst arbeitsfrei.
- erholung: mindestens `min_freie_tage` komplett freie Tage pro Woche.
- zerstueckelung: lieber wenige lange Blöcke als viele kurze.

Reichen die Stunden nicht, werden die Regeln stufenweise gelockert: zuerst das Lernfenster nach
Vorlesungen, dann dürfen nicht aufgezeichnete Vorlesungen ohne Anwesenheitspflicht überplant
werden (diese werden als „geopfert“ gemeldet). Aufgezeichnete Vorlesungen ohne
Anwesenheitspflicht dürfen immer überplant werden.

Das Modul greift nicht auf die Datenbank zu und ist deshalb isoliert testbar.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from itertools import combinations

RASTER = timedelta(minutes=15)
PAUSE = timedelta(minutes=30)  # Mindestabstand zwischen zwei Arbeitsblöcken
LAENGEN_SCHRITT = timedelta(minutes=30)  # Abstufung der Blocklängen bei der Suche
MAX_BLOECKE_PRO_TAG = 2
NULL = timedelta(0)
STUNDE = timedelta(hours=1)
WOCHENTAGE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

# Kostenfaktoren pro Gewichtspunkt; Gewichte liegen zwischen 0 und 10
FAKTOR_GLEICHMAESSIG = 0.1  # pro (Stunden Tageslast)²
FAKTOR_WECHSEL = 1.0  # pro Wechsel zwischen Uni und Arbeit
FAKTOR_BLOCK = 0.8  # pro Arbeitsblock
FAKTOR_VORTAG = 0.6  # pro Arbeitsstunde am Tag vor Prüfung oder Abgabe
FAKTOR_ERHOLUNG = 4.0  # pro fehlendem freien Tag
BONUS_BEVORZUGT = 0.3  # pro Arbeitsstunde an einem bevorzugten Tag
KOSTEN_OPFER = 8.0  # pro Stunde überplanter Vorlesung ohne Aufzeichnung
KOSTEN_FEHLEND = 1000.0  # pro fehlender Stunde – Stunden unterbringen geht vor


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
    abgabe: bool = False  # Frist, kein Anwesenheitstermin
    vorlesung: bool = False  # VO/VU: danach wird ein Lernfenster freigehalten
    termin_id: int | None = None

    @property
    def intervall(self) -> Intervall:
        return Intervall(self.start, self.ende)

    @property
    def ist_pflicht(self) -> bool:
        return not self.abgabe and (self.pruefung or self.anwesenheitspflicht)

    @property
    def ist_frist(self) -> bool:
        """Prüfung oder Abgabe – davor wird Lernzeit geschützt."""
        return self.pruefung or self.abgabe


@dataclass(frozen=True)
class Gewichte:
    gleichmaessig: float = 5
    buendeln: float = 5
    lernzeit: float = 5
    erholung: float = 5
    zerstueckelung: float = 5


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
    # Feiertage und zusätzliche freie Tage: dort wird nichts vorgeschlagen
    freie_tage: frozenset[date] = frozenset()
    max_tag: timedelta = timedelta(hours=9)  # Uni plus Arbeit pro Tag
    lernfenster: timedelta = timedelta(hours=2)
    voller_unitag: timedelta = timedelta(hours=6)  # ab so viel Uni kein Arbeitsblock am Abend
    min_freie_tage: int = 1
    gewichte: Gewichte = Gewichte()


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
    # kurze Erklärungen, warum der Vorschlag so aussieht
    begruendungen: list[str] = field(default_factory=list)
    punktzahl: float = 0.0  # höher = entspanntere Woche; nur innerhalb einer Woche vergleichbar

    @property
    def verplant(self) -> timedelta:
        return sum((b.intervall.dauer for b in self.bloecke), NULL)

    @property
    def fehlend(self) -> timedelta:
        return max(self.soll - self.verplant, NULL)


# --- Hilfsfunktionen ------------------------------------------------------------

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


def _summe(intervalle: Iterable[Intervall]) -> timedelta:
    return sum((i.dauer for i in intervalle), NULL)


def _stunden(dauer: timedelta) -> str:
    wert = round(dauer / STUNDE, 2)
    return (f"{wert:g}").replace(".", ",") + " h"


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


def _tagesfenster(tag: date, regeln: Arbeitsregeln) -> Intervall:
    return Intervall(datetime.combine(tag, regeln.fruehester_beginn), datetime.combine(tag, regeln.spaetestes_ende))


def _ist_arbeitstag(tag: date, regeln: Arbeitsregeln) -> bool:
    return tag.weekday() in regeln.tage and tag not in regeln.freie_tage


def luecken_am_tag(tag: date, regeln: Arbeitsregeln, sperren: list[Intervall]) -> list[Intervall]:
    """Freie Fenster eines Arbeitstags, auf 15 Minuten gerundet und mindestens `min_block` lang."""
    if not _ist_arbeitstag(tag, regeln):
        return []
    fenster = _tagesfenster(tag, regeln)
    if fenster.dauer <= NULL:
        return []
    luecken = []
    for stueck in abziehen(fenster, sperren):
        luecke = Intervall(_auf_raster(stueck.start, True), _auf_raster(stueck.ende, False))
        if luecke.dauer >= regeln.min_block:
            luecken.append(luecke)
    return luecken


def finde_luecken(woche_start: date, regeln: Arbeitsregeln, sperren: list[Intervall]) -> Iterator[Intervall]:
    """Freie Fenster aller Arbeitstage der Woche."""
    for i in range(7):
        yield from luecken_am_tag(woche_start + timedelta(days=i), regeln, sperren)


def zaehle_wechsel(uni: Iterable[Intervall], arbeit: Iterable[Intervall]) -> int:
    """Anzahl der Wechsel zwischen Uni und Arbeit in der zeitlichen Abfolge eines Tages."""
    abfolge = sorted([(i.start, "uni") for i in uni] + [(i.start, "arbeit") for i in arbeit])
    return sum(1 for (_, a), (_, b) in zip(abfolge, abfolge[1:]) if a != b)


# --- Ausgangslage pro Tag --------------------------------------------------------

@dataclass(frozen=True)
class _Stufe:
    """Wie streng die Regeln in einem Durchlauf sind."""

    lernfenster_nach_vorlesung: bool = True
    weich_ueberplanen: bool = False  # nicht aufgezeichnete Vorlesungen dürfen überplant werden


STUFEN = [_Stufe(), _Stufe(lernfenster_nach_vorlesung=False), _Stufe(False, True)]


@dataclass
class _Tag:
    datum: date
    pflicht: list[PlanTermin]
    weich: list[PlanTermin]  # ohne Anwesenheitspflicht und ohne Aufzeichnung: man geht hin
    fix: list[Intervall]  # bestätigte Arbeitsblöcke
    fristen_morgen: list[PlanTermin]  # Prüfungen/Abgaben am Folgetag
    voller_unitag: bool
    uni_dauer: timedelta
    belegt: list[Intervall] = field(default_factory=list)  # z. B. Lernblöcke: Tageslast, aber keine Arbeit


@dataclass(frozen=True)
class _Tagesplan:
    bloecke: tuple[Intervall, ...]
    arbeit: timedelta  # neue Arbeit dieses Plans
    last: timedelta  # Uni plus gesamte Arbeit
    kosten: float
    frei: bool  # komplett freier Tag (weder Uni noch Arbeit)
    geopfert: tuple[PlanTermin, ...] = ()


def _baue_tage(
    woche_start: date,
    regeln: Arbeitsregeln,
    termine: list[PlanTermin],
    bestehend: list[Intervall],
    belegt: list[Intervall] | None = None,
) -> list[_Tag]:
    tage = []
    for i in range(7):
        datum = woche_start + timedelta(days=i)
        am_tag = [t for t in termine if t.start.date() == datum]
        pflicht = [t for t in am_tag if t.ist_pflicht]
        weich = [t for t in am_tag if not t.ist_pflicht and not t.aufzeichnung and not t.abgabe]
        uni_dauer = _summe(vereinige(t.intervall for t in pflicht + weich))
        tage.append(_Tag(
            datum=datum,
            pflicht=pflicht,
            weich=weich,
            fix=[b for b in bestehend if b.start.date() == datum],
            belegt=[b for b in belegt or [] if b.start.date() == datum],
            fristen_morgen=[t for t in termine if t.ist_frist and t.start.date() == datum + timedelta(days=1)],
            voller_unitag=uni_dauer >= regeln.voller_unitag > NULL,
            uni_dauer=uni_dauer,
        ))
    return tage


def _sperren(tag: _Tag, regeln: Arbeitsregeln, stufe: _Stufe, alle_termine: list[PlanTermin]) -> list[Intervall]:
    sperren = [t.intervall.erweitert(regeln.puffer) for t in tag.pflicht]
    sperren += [b.erweitert(PAUSE) for b in tag.fix + tag.belegt]
    if not stufe.weich_ueberplanen:
        sperren += [t.intervall.erweitert(regeln.puffer) for t in tag.weich]
    besucht = tag.pflicht + ([] if stufe.weich_ueberplanen else tag.weich)
    if regeln.lernfenster > NULL:
        # Lernfenster vor Prüfungen und Abgaben am selben Tag
        for frist in (t for t in alle_termine if t.ist_frist and t.start.date() == tag.datum):
            beginn = frist.start - regeln.puffer - regeln.lernfenster
            sperren.append(Intervall(beginn, frist.start))
        # Lernfenster nach besuchten Vorlesungen
        if stufe.lernfenster_nach_vorlesung:
            for vo in (t for t in besucht if t.vorlesung):
                sperren.append(Intervall(vo.ende, vo.ende + regeln.puffer + regeln.lernfenster))
    # Erholung: kein Arbeitsblock am Abend nach einem vollen Unitag
    if tag.voller_unitag and besucht:
        letzte = max(t.ende for t in besucht)
        sperren.append(Intervall(letzte, datetime.combine(tag.datum + timedelta(days=1), time())))
    return sperren


def _blockkandidaten(luecken: list[Intervall], regeln: Arbeitsregeln) -> list[Intervall]:
    """Einzelblöcke in jeder Lücke: verschiedene Längen, am Anfang oder Ende der Lücke."""
    kandidaten: set[Intervall] = set()
    for luecke in luecken:
        groesste = min(luecke.dauer, regeln.max_block)
        laengen = set()
        laenge = regeln.min_block
        while laenge <= groesste:
            laengen.add(laenge)
            laenge += LAENGEN_SCHRITT
        laengen.add(_dauer_abrunden(groesste))
        for laenge in laengen:
            if laenge < regeln.min_block:
                continue
            kandidaten.add(Intervall(luecke.start, luecke.start + laenge))
            kandidaten.add(Intervall(luecke.ende - laenge, luecke.ende))
    return sorted(kandidaten, key=lambda i: (i.start, i.ende))


def _bewerte_tag(tag: _Tag, bloecke: tuple[Intervall, ...], regeln: Arbeitsregeln) -> _Tagesplan | None:
    """Kosten eines Tagesplans; None, wenn er die Tagesgrenze verletzt."""
    g = regeln.gewichte
    neu = _summe(bloecke)
    arbeit = neu + _summe(tag.fix)
    geopfert = tuple(t for t in tag.weich if any(t.intervall.erweitert(regeln.puffer).ueberschneidet(b) for b in bloecke))
    uni = vereinige(t.intervall for t in tag.pflicht + [w for w in tag.weich if w not in geopfert])
    last = _summe(uni) + arbeit + _summe(tag.belegt)
    if bloecke and last > regeln.max_tag:
        return None

    kosten = g.gleichmaessig * FAKTOR_GLEICHMAESSIG * (last / STUNDE) ** 2
    kosten += g.buendeln * FAKTOR_WECHSEL * zaehle_wechsel(uni, list(bloecke) + tag.fix)
    kosten += g.zerstueckelung * FAKTOR_BLOCK * len(bloecke)
    if tag.fristen_morgen:
        kosten += g.lernzeit * FAKTOR_VORTAG * (neu / STUNDE)
    if tag.datum.weekday() in regeln.bevorzugte_tage:
        kosten -= BONUS_BEVORZUGT * (neu / STUNDE)
    kosten += KOSTEN_OPFER * (_summe(t.intervall for t in geopfert) / STUNDE)
    return _Tagesplan(bloecke, neu, last, kosten, frei=last == NULL, geopfert=geopfert)


def _tagesplaene(tag: _Tag, regeln: Arbeitsregeln, sperren: list[Intervall]) -> dict[int, _Tagesplan]:
    """Bester Tagesplan je Arbeitsmenge (in Rastereinheiten)."""
    leer = _bewerte_tag(tag, (), regeln)
    plaene: dict[int, _Tagesplan] = {0: leer}
    luecken = luecken_am_tag(tag.datum, regeln, sperren)
    if not luecken:
        return plaene

    obergrenze = regeln.max_tag - _summe(tag.fix) - _summe(tag.belegt)
    if tag.fristen_morgen:
        # Am Vortag einer Prüfung oder Abgabe bleibt mindestens ein Lernfenster frei
        fenster = _tagesfenster(tag.datum, regeln)
        uni_im_fenster = _summe(
            Intervall(max(i.start, fenster.start), min(i.ende, fenster.ende))
            for i in vereinige(t.intervall for t in tag.pflicht + tag.weich)
            if i.ueberschneidet(fenster)
        )
        obergrenze = min(obergrenze, fenster.dauer - uni_im_fenster - regeln.lernfenster)

    einzeln = [b for b in _blockkandidaten(luecken, regeln) if b.dauer <= obergrenze]
    kombinationen: list[tuple[Intervall, ...]] = [(b,) for b in einzeln]
    if MAX_BLOECKE_PRO_TAG >= 2:
        kombinationen += [
            (a, b) for a, b in combinations(einzeln, 2) if b.start >= a.ende + PAUSE and a.dauer + b.dauer <= obergrenze
        ]
    for bloecke in kombinationen:
        plan = _bewerte_tag(tag, bloecke, regeln)
        if plan is None:
            continue
        einheiten = plan.arbeit // RASTER
        if einheiten not in plaene or plan.kosten < plaene[einheiten].kosten:
            plaene[einheiten] = plan
    return plaene


def _beste_woche(tage: list[_Tag], plaene: list[dict[int, _Tagesplan]], bedarf: timedelta, regeln: Arbeitsregeln):
    """Dynamische Programmierung: beste Kombination der Tagespläne."""
    ziel = bedarf // RASTER
    mindestens_frei = max(regeln.min_freie_tage, 0)
    # Zustand: (verplante Einheiten, freie Tage bis zur Mindestzahl) -> (Kosten, gewählte Pläne)
    zustaende: dict[tuple[int, int], tuple[float, list[_Tagesplan]]] = {(0, 0): (0.0, [])}
    for tagesplaene in plaene:
        neu: dict[tuple[int, int], tuple[float, list[_Tagesplan]]] = {}
        for (einheiten, frei), (kosten, wahl) in zustaende.items():
            for plan_einheiten, plan in tagesplaene.items():
                summe = einheiten + plan_einheiten
                if summe > ziel:
                    continue
                schluessel = (summe, min(frei + plan.frei, mindestens_frei))
                gesamt = kosten + plan.kosten
                if schluessel not in neu or gesamt < neu[schluessel][0]:
                    neu[schluessel] = (gesamt, wahl + [plan])
        zustaende = neu

    def endkosten(eintrag):
        (einheiten, frei), (kosten, _) = eintrag
        fehlend = (ziel - einheiten) * (RASTER / STUNDE)
        return kosten + KOSTEN_FEHLEND * fehlend + regeln.gewichte.erholung * FAKTOR_ERHOLUNG * (mindestens_frei - frei)

    bester = min(zustaende.items(), key=endkosten)
    return bester[1][1], endkosten(bester)


# --- Begründungen ----------------------------------------------------------------

def _begruendungen(
    tage: list[_Tag], wahl: list[_Tagesplan], regeln: Arbeitsregeln, stufe: _Stufe, fehlend: timedelta
) -> list[str]:
    texte: list[str] = []
    for tag, plan in zip(tage, wahl):
        name = WOCHENTAGE[tag.datum.weekday()]
        arbeitstag = _ist_arbeitstag(tag.datum, regeln)
        for frist in tag.fristen_morgen:
            art = "Prüfung" if frist.pruefung else "Abgabe"
            morgen = WOCHENTAGE[(tag.datum.weekday() + 1) % 7]
            if plan.arbeit == NULL and arbeitstag:
                texte.append(f"{name} frei gehalten: {art} {frist.titel} {morgen}".replace("  ", " "))
            elif plan.arbeit > NULL:
                texte.append(f"{name} nur {_stunden(plan.arbeit)} Arbeit: Lernzeit vor {art} {morgen}")
        if tag.voller_unitag and arbeitstag:
            texte.append(f"{name} abends frei: voller Unitag ({_stunden(tag.uni_dauer)})")
        if plan.arbeit > NULL and plan.last >= regeln.max_tag - RASTER:
            texte.append(f"{name} an der Tagesgrenze von {_stunden(regeln.max_tag)}")

    gebuendelt = [
        WOCHENTAGE[t.datum.weekday()] for t, p in zip(tage, wahl) if p.arbeit > NULL and not t.pflicht and not t.weich
    ]
    if gebuendelt:
        texte.append("Arbeit gebündelt an Tagen ohne Uni: " + ", ".join(gebuendelt))
    freie = [WOCHENTAGE[t.datum.weekday()] for t, p in zip(tage, wahl) if p.frei]
    if freie:
        texte.append("Komplett frei: " + ", ".join(freie))
    elif regeln.min_freie_tage > 0:
        texte.append("Kein komplett freier Tag möglich")

    hat_vorlesung = any(t.vorlesung for tag in tage for t in tag.pflicht + tag.weich)
    if hat_vorlesung and regeln.lernfenster > NULL:
        if stufe.lernfenster_nach_vorlesung:
            texte.append(f"Nach Vorlesungen je {_stunden(regeln.lernfenster)} Lernzeit freigehalten")
        else:
            texte.append("Lernfenster nach Vorlesungen gekürzt – sonst reichen die Stunden nicht")
    if fehlend > NULL:
        texte.append(f"{_stunden(fehlend)} passen nicht unter die Regeln (Tagesgrenze, Lernzeit, Erholung)")
    return texte


# --- Einstieg --------------------------------------------------------------------

def verteile_arbeitszeit(
    woche: date,
    regeln: Arbeitsregeln,
    termine: Iterable[PlanTermin],
    bestaetigte_bloecke: Iterable[Intervall],
    belegte_zeiten: Iterable[Intervall] = (),
) -> Verteilung:
    """Berechnet den Vorschlag für die flexiblen Arbeitsblöcke einer Woche."""
    woche_start = wochenbeginn(woche)
    woche_iv = Intervall(datetime.combine(woche_start, time()), datetime.combine(woche_start + timedelta(days=7), time()))
    # Termine am Montag danach werden für das Lernfenster am Sonntag gebraucht
    erweitert = Intervall(woche_iv.start, woche_iv.ende + timedelta(days=1))
    termine = [t for t in termine if t.intervall.ueberschneidet(erweitert)]
    bestehend = [b for b in bestaetigte_bloecke if b.ueberschneidet(woche_iv)]

    gesamt = _dauer_abrunden(timedelta(hours=regeln.stunden_pro_woche))
    bereits = sum((min(b.ende, woche_iv.ende) - max(b.start, woche_iv.start) for b in bestehend), NULL)
    bedarf = _dauer_abrunden(max(gesamt - bereits, NULL))
    verteilung = Verteilung(soll=bedarf)
    if bedarf <= NULL:
        return verteilung

    # Lernblöcke: gesperrt und Teil der Tageslast, zählen aber nicht zu den Wochenstunden
    belegt = [b for b in belegte_zeiten if b.ueberschneidet(woche_iv)]
    tage = _baue_tage(woche_start, regeln, termine, bestehend, belegt)
    hat_weiche = any(tag.weich for tag in tage)

    ergebnis = None
    for stufe in STUFEN:
        if stufe.weich_ueberplanen and not hat_weiche:
            continue
        plaene = [_tagesplaene(tag, regeln, _sperren(tag, regeln, stufe, termine)) for tag in tage]
        wahl, kosten = _beste_woche(tage, plaene, bedarf, regeln)
        verplant = sum((p.arbeit for p in wahl), NULL)
        if ergebnis is None or verplant > ergebnis[2]:
            ergebnis = (stufe, wahl, verplant, kosten)
        if verplant >= bedarf:
            break

    stufe, wahl, verplant, kosten = ergebnis
    aufgezeichnet = [t for t in termine if not t.ist_pflicht and t.aufzeichnung and not t.abgabe]
    for plan in wahl:
        for block in plan.bloecke:
            ueberplant = [t for t in plan.geopfert if t.intervall.erweitert(regeln.puffer).ueberschneidet(block)]
            ueberplant += [t for t in aufgezeichnet if t.intervall.ueberschneidet(block)]
            verteilung.bloecke.append(Vorschlag(block, sorted(ueberplant, key=lambda t: t.start)))
    verteilung.bloecke.sort(key=lambda v: v.intervall.start)
    verteilung.geopferte_termine = [t for plan in wahl for t in plan.geopfert]
    verteilung.punktzahl = round(-kosten, 1)
    verteilung.begruendungen = _begruendungen(tage, wahl, regeln, stufe, bedarf - verplant)
    return verteilung
