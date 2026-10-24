"""Lernblöcke planen – nach der Arbeitszeit, in die verbleibenden Lücken (siehe planung_service).

Die Lernzeit je LVA kommt aus dem Wochenbedarf (lernbedarf.py, aus den ECTS); die Unterlagen
bestimmen nur, welcher Stoff in einem Block dran ist (`stoff_zuteilen`). Ablauf:

1. LVAs mit naher Prüfung (Lernphase) bekommen ihre Blöcke zuerst, die übrigen reihum – reicht
   die Zeit nicht, wird zuerst die Lernzeit von LVAs ohne nahe Prüfung gekürzt.
2. Für jeden Block wird jede freie Lücke der Woche bewertet: gleichmäßige Tageslast, höchstens ein
   Block derselben LVA pro Tag, vor der nächsten Übung/Abgabe, nie nach der Prüfung. Die beste gewinnt.
3. Findet eine LVA keinen Platz mehr, bleibt der Rest als „offen“ stehen – er wird gemeldet,
   nicht stillschweigend gestrichen.

Feste Regeln: erlaubte Lerntage und Uhrzeiten, gesperrte Tage, Sperrzeiten (Pflichttermine mit Weg,
besuchte Vorlesungen, Arbeit, bestätigte Lernblöcke), Tagesgrenze Uni + Arbeit + Lernen,
Mindest- und Maximallänge eines Lernblocks.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from .planung import PAUSE, RASTER, STUNDE, WOCHENTAGE, Intervall, abziehen, wochenbeginn

FAKTOR_FRUEH = 0.02  # pro Stunde ab Wochenbeginn: bei Gleichstand lieber früher
STRAFE_GLEICHER_TAG = 6.0  # zweiter Block derselben LVA am selben Tag
STRAFE_NACH_FRIST = 3.0  # Block endet erst nach der nächsten Übung/Abgabe
FAKTOR_TAGESLAST = 0.2  # pro (Stunden Tageslast)²


@dataclass(frozen=True)
class LernStoff:
    """Noch nicht abgedeckter Stoff einer Unterlage; `minuten` ist die geschätzte Menge (Gewicht)."""

    dokument_id: int
    lva_id: int
    titel: str
    erschienen: datetime
    minuten: int


@dataclass(frozen=True)
class LernBedarf:
    """Lernzeit, die einer LVA in dieser Woche noch einzuplanen ist."""

    lva_id: int
    minuten: int
    prioritaet: int = 1  # Wochen bis zur Prüfung: je kleiner, desto später gekürzt
    pruefung: datetime | None = None  # Prüfung in dieser Woche: Blöcke nur davor


@dataclass(frozen=True)
class LernRegeln:
    tage: frozenset[int] = frozenset({0, 1, 2, 3, 4, 5})
    fruehester_beginn: time = time(8, 0)
    spaetestes_ende: time = time(18, 0)
    min_block: timedelta = timedelta(minutes=45)
    max_block: timedelta = timedelta(minutes=120)
    max_tag: timedelta = timedelta(hours=9)  # Uni + Arbeit + Lernen
    freie_tage: frozenset[date] = frozenset()  # Feiertage und vorlesungsfreie Zeit: kein Lernblock


@dataclass
class LernVorschlag:
    lva_id: int
    intervall: Intervall
    zuteilung: dict[int, int] = field(default_factory=dict)  # dokument_id -> abgedeckte Stoffmenge
    titel: list[str] = field(default_factory=list)
    nach_frist: bool = False

    @property
    def minuten(self) -> int:
        return int(self.intervall.dauer / timedelta(minutes=1))


@dataclass
class LernPlan:
    bloecke: list[LernVorschlag] = field(default_factory=list)
    offen: dict[int, int] = field(default_factory=dict)  # lva_id -> Minuten ohne Platz
    begruendungen: list[str] = field(default_factory=list)

    def minuten(self, lva_id: int | None = None) -> int:
        return sum(b.minuten for b in self.bloecke if lva_id is None or b.lva_id == lva_id)


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
    bedarf: list[LernBedarf],
    sperren: list[Intervall],
    grundlast: dict[date, timedelta] | None = None,
    fristen: dict[int, list[datetime]] | None = None,
    lva_namen: dict[int, str] | None = None,
) -> LernPlan:
    """Plant die Lernzeit einer Woche. `grundlast`: Uni + Arbeit + bestätigte Lernblöcke je Tag."""
    woche_start = datetime.combine(wochenbeginn(woche), time())
    fristen = fristen or {}
    lva_namen = lva_namen or {}
    last: dict[date, timedelta] = defaultdict(timedelta, grundlast or {})
    belegt: list[Intervall] = list(sperren)
    plan = LernPlan()
    tage_mit_block: dict[int, set[date]] = defaultdict(set)

    rest = {b.lva_id: b.minuten for b in bedarf if b.minuten > 0}
    info = {b.lva_id: b for b in bedarf}
    vergeben: dict[int, int] = defaultdict(int)

    def block_setzen(lva_id: int) -> bool:
        wunsch = timedelta(minutes=rest[lva_id])
        pruefung = info[lva_id].pruefung
        bester = None
        for i in range(7):
            tag = woche_start.date() + timedelta(days=i)
            if tag.weekday() not in regeln.tage or tag in regeln.freie_tage:
                continue
            if pruefung is not None and tag > pruefung.date():
                continue  # nach der Prüfung bringt Lernen für sie nichts mehr
            kapazitaet = regeln.max_tag - last[tag]
            if kapazitaet < regeln.min_block:
                continue
            ende = datetime.combine(tag, regeln.spaetestes_ende)
            if pruefung is not None:
                ende = min(ende, pruefung)
            fenster = Intervall(datetime.combine(tag, regeln.fruehester_beginn), ende)
            if fenster.dauer < regeln.min_block:
                continue
            for stueck in abziehen(fenster, belegt):
                luecke = Intervall(_auf_raster(stueck.start), _ab_raster(stueck.ende))
                laenge = min(wunsch, regeln.max_block, luecke.dauer, kapazitaet)
                laenge = max((laenge // RASTER) * RASTER, regeln.min_block)
                if laenge > luecke.dauer or laenge > kapazitaet:
                    continue
                block = Intervall(luecke.start, luecke.start + laenge)
                frist = _naechste_frist(fristen.get(lva_id, []), woche_start)
                spaet = frist is not None and block.ende > frist
                punkte = FAKTOR_FRUEH * ((block.start - woche_start) / STUNDE)
                punkte += STRAFE_NACH_FRIST if spaet else 0
                punkte += STRAFE_GLEICHER_TAG if tag in tage_mit_block[lva_id] else 0
                punkte += FAKTOR_TAGESLAST * ((last[tag] + laenge) / STUNDE) ** 2
                if bester is None or punkte < bester[0]:
                    bester = (punkte, block, spaet)
        if bester is None:
            return False
        _, block, spaet = bester
        vorschlag = LernVorschlag(lva_id, block, nach_frist=spaet)
        plan.bloecke.append(vorschlag)
        belegt.append(block.erweitert(PAUSE))
        last[block.start.date()] += block.dauer
        tage_mit_block[lva_id].add(block.start.date())
        rest[lva_id] -= vorschlag.minuten
        vergeben[lva_id] += vorschlag.minuten
        return True

    # Reste unter einem halben Mindestblock lohnen keinen eigenen Block
    def offen_genug(lva_id: int) -> bool:
        return rest[lva_id] >= regeln.min_block / timedelta(minutes=1) / 2

    while True:
        kandidaten = [l for l in rest if offen_genug(l)]
        if not kandidaten:
            break
        # nahe Prüfung zuerst, sonst reihum: wer anteilig am wenigsten bekommen hat
        lva_id = min(kandidaten, key=lambda l: (info[l].prioritaet, vergeben[l] / info[l].minuten, l))
        if not block_setzen(lva_id):
            plan.offen[lva_id] = rest.pop(lva_id)
    # kleine Reste fallen nicht weg: sie gehen als Rückstand in die Folgewochen (lernbedarf.py)

    plan.bloecke.sort(key=lambda b: b.intervall.start)
    plan.begruendungen = _begruendungen(plan, lva_namen, info)
    return plan


def stoff_zuteilen(
    bloecke: list[LernVorschlag], stoff: list[LernStoff], stoff_anteil: dict[int, float],
    lernphase: frozenset[int] = frozenset(), altpruefungen: dict[int, list[tuple[int, str]]] | None = None,
) -> None:
    """Legt fest, welcher Stoff in welchem Block dran ist.

    In der Lernphase bekommt jeder Block einer LVA eine konkrete Altprüfung (`altpruefungen`: je LVA
    (dokument_id, Titel), neueste zuerst) – eine Prüfung pro Block. Sind sie aufgebraucht, gilt das Folgende.

    Vom offenen Stoff einer LVA ist diese Woche `stoff_anteil` dran (älteste Unterlagen zuerst); er
    verteilt sich im Verhältnis der Blocklängen. So wird viel alter Stoff über die verbleibenden Wochen
    verteilt statt in eine Woche gepackt. Ohne offenen Stoff: Wiederholung bzw. Prüfungsvorbereitung.
    """
    schlangen: dict[int, list[list]] = defaultdict(list)
    for s in sorted(stoff, key=lambda s: (s.erschienen, s.dokument_id)):
        if s.minuten > 0:
            schlangen[s.lva_id].append([s, s.minuten])
    je_lva: dict[int, list[LernVorschlag]] = defaultdict(list)
    for b in sorted(bloecke, key=lambda b: b.intervall.start):
        je_lva[b.lva_id].append(b)

    altpruefungen = altpruefungen or {}
    for lva_id, lva_bloecke in list(je_lva.items()):
        if lva_id not in lernphase or not altpruefungen.get(lva_id):
            continue
        frei = list(altpruefungen[lva_id])
        rest = []
        for b in lva_bloecke:
            if frei:
                dok_id, titel = frei.pop(0)
                b.zuteilung[dok_id] = b.minuten
                b.titel.append(titel)
            else:
                rest.append(b)
        je_lva[lva_id] = rest

    for lva_id, lva_bloecke in je_lva.items():
        schlange = schlangen.get(lva_id, [])
        ziel = sum(rest for _, rest in schlange) * min(max(stoff_anteil.get(lva_id, 1.0), 0), 1)
        gesamt = sum(b.minuten for b in lva_bloecke) or 1
        for b in lva_bloecke:
            uebrig = ziel * b.minuten / gesamt
            for eintrag in schlange:
                s, rest = eintrag
                if uebrig < 1:
                    break
                if rest <= 0 or s.erschienen > b.intervall.ende:
                    continue
                nimm = min(rest, round(uebrig) or 1)
                b.zuteilung[s.dokument_id] = b.zuteilung.get(s.dokument_id, 0) + nimm
                if s.titel not in b.titel:
                    b.titel.append(s.titel)
                eintrag[1] -= nimm
                uebrig -= nimm
            if not b.titel:
                b.titel.append("Prüfungsvorbereitung" if lva_id in lernphase else "Wiederholung und Übungen")


def _begruendungen(plan: LernPlan, lva_namen: dict[int, str], info: dict[int, LernBedarf]) -> list[str]:
    texte = []
    for lva_id in sorted({b.lva_id for b in plan.bloecke}, key=lambda l: lva_namen.get(l, "")):
        bloecke = [b for b in plan.bloecke if b.lva_id == lva_id]
        name = lva_namen.get(lva_id, f"LVA {lva_id}")
        tage = ", ".join(dict.fromkeys(WOCHENTAGE[b.intervall.start.weekday()] for b in bloecke))
        dauer = f"{plan.minuten(lva_id) / 60:.1f}".replace(".", ",")
        anzahl = "1 Block" if len(bloecke) == 1 else f"{len(bloecke)} Blöcken"
        text = f"Lernen {name}: {dauer} h in {anzahl} ({tage})"
        if info[lva_id].prioritaet == 0:
            text += " – Lernphase, Prüfung diese Woche: wird zuletzt gekürzt"
        elif info[lva_id].prioritaet < 99:
            text += f" – Lernphase, Prüfung in {info[lva_id].prioritaet} Wo."
        if any(b.nach_frist for b in bloecke):
            text += " – teils erst nach der Übung/Abgabe, vorher war kein Platz"
        texte.append(text)
    return texte
