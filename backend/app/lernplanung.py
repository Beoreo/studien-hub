"""Lernblöcke planen – vor der Arbeitszeit (siehe planung_service.schlage_woche_vor).

Ziel: neuer Stoff wird bald nach seinem Erscheinen gelernt und vor der nächsten zugehörigen
Übung, Abgabe oder Prüfung. Ablauf:

1. Je LVA eine Warteschlange offener Unterlagen, älteste zuerst.
2. Die LVA mit der dringendsten Frist bekommt den nächsten Block.
3. Für den Block wird jede freie Lücke ab dem Erscheinen des Stoffs bewertet:
   wenig Verzögerung, vor der Frist, gleichmäßige Tageslast. Die beste gewinnt.
4. Findet eine LVA keinen Platz mehr, bleibt der Rest als „offen“ stehen – er wird gemeldet,
   nicht stillschweigend gestrichen.

Feste Regeln: erlaubte Lerntage und Uhrzeiten, Sperrzeiten (Pflichttermine mit Weg, besuchte
Vorlesungen, bestätigte Arbeits- und Lernblöcke), Tagesgrenze Uni + Arbeit + Lernen,
Mindest- und Maximallänge eines Lernblocks.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from .planung import NULL, PAUSE, RASTER, STUNDE, WOCHENTAGE, Intervall, abziehen, wochenbeginn

FAKTOR_VERZOEGERUNG = 0.15  # pro Stunde zwischen Erscheinen und Lernblock
STRAFE_NACH_FRIST = 50.0  # Block endet erst nach der Übung/Abgabe
FAKTOR_TAGESLAST = 0.2  # pro (Stunden Tageslast)²


@dataclass(frozen=True)
class LernStoff:
    """Noch nicht eingeplanter Lernaufwand einer Unterlage."""

    dokument_id: int
    lva_id: int
    titel: str
    erschienen: datetime
    minuten: int


@dataclass(frozen=True)
class LernRegeln:
    tage: frozenset[int] = frozenset({0, 1, 2, 3, 4, 5})
    fruehester_beginn: time = time(8, 0)
    spaetestes_ende: time = time(18, 0)
    min_block: timedelta = timedelta(minutes=45)
    max_block: timedelta = timedelta(minutes=120)
    max_tag: timedelta = timedelta(hours=9)  # Uni + Arbeit + Lernen


@dataclass
class LernVorschlag:
    lva_id: int
    intervall: Intervall
    zuteilung: dict[int, int] = field(default_factory=dict)  # dokument_id -> Minuten
    titel: list[str] = field(default_factory=list)
    nach_frist: bool = False


@dataclass
class LernPlan:
    bloecke: list[LernVorschlag] = field(default_factory=list)
    offen: dict[int, int] = field(default_factory=dict)  # lva_id -> Minuten ohne Platz
    begruendungen: list[str] = field(default_factory=list)

    def minuten(self, lva_id: int | None = None) -> int:
        return sum(
            int(b.intervall.dauer / timedelta(minutes=1)) for b in self.bloecke if lva_id is None or b.lva_id == lva_id
        )


def _auf_raster(dt: datetime) -> datetime:
    mitternacht = datetime.combine(dt.date(), time())
    schritte, rest = divmod(dt - mitternacht, RASTER)
    return mitternacht + (schritte + (1 if rest else 0)) * RASTER


def _ab_raster(dt: datetime) -> datetime:
    mitternacht = datetime.combine(dt.date(), time())
    return mitternacht + ((dt - mitternacht) // RASTER) * RASTER


def _naechste_frist(fristen: list[datetime], ab: datetime) -> datetime | None:
    return next((f for f in sorted(fristen) if f > ab), None)


def plane_lernbloecke(
    woche: date,
    regeln: LernRegeln,
    stoff: list[LernStoff],
    sperren: list[Intervall],
    grundlast: dict[date, timedelta] | None = None,
    fristen: dict[int, list[datetime]] | None = None,
    lva_namen: dict[int, str] | None = None,
) -> LernPlan:
    """Plant Lernblöcke für eine Woche. `grundlast`: Uni + bestätigte Blöcke je Tag."""
    woche_start = datetime.combine(wochenbeginn(woche), time())
    woche_ende = woche_start + timedelta(days=7)
    fristen = fristen or {}
    lva_namen = lva_namen or {}
    last: dict[date, timedelta] = defaultdict(timedelta, grundlast or {})
    belegt: list[Intervall] = list(sperren)
    plan = LernPlan()

    # 1. Warteschlangen je LVA: [Stoff, Restminuten]
    schlangen: dict[int, deque[list]] = defaultdict(deque)
    for s in sorted(stoff, key=lambda s: (s.erschienen, s.dokument_id)):
        if s.minuten > 0 and s.erschienen < woche_ende:
            schlangen[s.lva_id].append([s, s.minuten])

    def frueheste(lva_id: int) -> datetime:
        return _auf_raster(max(schlangen[lva_id][0][0].erschienen, woche_start))

    def dringlichkeit(lva_id: int):
        frist = _naechste_frist(fristen.get(lva_id, []), frueheste(lva_id))
        return (frist or datetime.max, frueheste(lva_id), lva_id)

    def block_setzen(lva_id: int) -> bool:
        schlange = schlangen[lva_id]
        ab = frueheste(lva_id)
        frist = _naechste_frist(fristen.get(lva_id, []), ab)
        bester = None
        for i in range(7):
            tag = woche_start.date() + timedelta(days=i)
            if tag.weekday() not in regeln.tage:
                continue
            kapazitaet = regeln.max_tag - last[tag]
            if kapazitaet < regeln.min_block:
                continue
            fenster = Intervall(
                max(datetime.combine(tag, regeln.fruehester_beginn), ab), datetime.combine(tag, regeln.spaetestes_ende)
            )
            if fenster.dauer < regeln.min_block:
                continue
            for stueck in abziehen(fenster, belegt):
                luecke = Intervall(_auf_raster(stueck.start), _ab_raster(stueck.ende))
                if luecke.dauer < regeln.min_block:
                    continue
                # nur Stoff, der zu Blockbeginn schon erschienen ist
                verfuegbar = sum(rest for s, rest in schlange if s.erschienen <= luecke.start)
                if verfuegbar <= 0:
                    continue
                laenge = min(timedelta(minutes=verfuegbar), regeln.max_block, luecke.dauer, kapazitaet)
                laenge = max((laenge // RASTER) * RASTER, regeln.min_block)
                if laenge > luecke.dauer or laenge > kapazitaet:
                    continue
                block = Intervall(luecke.start, luecke.start + laenge)
                spaet = frist is not None and block.ende > frist
                punkte = FAKTOR_VERZOEGERUNG * ((block.start - ab) / STUNDE)
                punkte += STRAFE_NACH_FRIST if spaet else 0
                punkte += FAKTOR_TAGESLAST * ((last[tag] + laenge) / STUNDE) ** 2
                if bester is None or punkte < bester[0]:
                    bester = (punkte, block, spaet)
        if bester is None:
            return False

        _, block, spaet = bester
        vorschlag = LernVorschlag(lva_id, block, nach_frist=spaet)
        uebrig = int(block.dauer / timedelta(minutes=1))
        for eintrag in list(schlange):
            s, rest = eintrag
            if uebrig <= 0 or s.erschienen > block.start:
                break
            nimm = min(rest, uebrig)
            vorschlag.zuteilung[s.dokument_id] = vorschlag.zuteilung.get(s.dokument_id, 0) + nimm
            if s.titel not in vorschlag.titel:
                vorschlag.titel.append(s.titel)
            eintrag[1] -= nimm
            uebrig -= nimm
            if eintrag[1] <= 0:
                schlange.popleft()
        plan.bloecke.append(vorschlag)
        belegt.append(block.erweitert(PAUSE))
        last[block.start.date()] += block.dauer
        return True

    # 2./3. Blöcke vergeben, dringendste LVA zuerst
    while schlangen:
        reihenfolge = sorted((l for l in schlangen if schlangen[l]), key=dringlichkeit)
        if not reihenfolge:
            break
        lva_id = reihenfolge[0]
        if not block_setzen(lva_id):
            # 4. kein Platz mehr: Rest offen melden
            plan.offen[lva_id] = plan.offen.get(lva_id, 0) + sum(rest for _, rest in schlangen[lva_id])
            del schlangen[lva_id]
        elif not schlangen[lva_id]:
            del schlangen[lva_id]

    plan.bloecke.sort(key=lambda b: b.intervall.start)
    plan.begruendungen = _begruendungen(plan, lva_namen, fristen)
    return plan


def _begruendungen(plan: LernPlan, lva_namen: dict[int, str], fristen: dict[int, list[datetime]]) -> list[str]:
    texte = []
    for lva_id in sorted({b.lva_id for b in plan.bloecke}, key=lambda l: lva_namen.get(l, "")):
        bloecke = [b for b in plan.bloecke if b.lva_id == lva_id]
        name = lva_namen.get(lva_id, f"LVA {lva_id}")
        tage = ", ".join(dict.fromkeys(WOCHENTAGE[b.intervall.start.weekday()] for b in bloecke))
        dauer = f"{plan.minuten(lva_id) / 60:.1f}".replace(".", ",")
        anzahl = "1 Block" if len(bloecke) == 1 else f"{len(bloecke)} Blöcken"
        text = f"Lernen {name}: {dauer} h in {anzahl} ({tage})"
        if any(b.nach_frist for b in bloecke):
            text += " – teils erst nach der Übung/Abgabe, vorher war kein Platz"
        elif fristen.get(lva_id):
            text += " – vor der nächsten Übung/Abgabe"
        texte.append(text)
    return texte
