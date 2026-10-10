"""Verbindet den Verteilungs-Algorithmus mit der Datenbank."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload

from .feiertage import gesperrte_tage
from .models import (
    ART_FLEXIBEL,
    STANDARD_GEWICHTE,
    STATUS_BESTAETIGT,
    STATUS_VORSCHLAG,
    LERN_BESTAETIGT,
    LERN_VORSCHLAG,
    TYP_ABGABE,
    TYP_PRUEFUNG,
    TYP_UE,
    TYP_VO,
    TYP_VU,
    Arbeitsblock,
    Arbeitsregel,
    Lernblock,
    Lva,
    Termin,
)
from .lernaufwand import offene_unterlagen, wochenbedarf
from .lernplanung import LernRegeln, LernStoff, plane_lernbloecke
from .planung import PAUSE, Arbeitsregeln, Gewichte, Intervall, PlanTermin, verteile_arbeitszeit, wochenbeginn

REGEL_ID = 1


class KeineRegelFehler(Exception):
    """Es wurde noch keine Arbeitsregel angelegt."""


def lade_regel(session: Session) -> Arbeitsregel | None:
    return session.get(Arbeitsregel, REGEL_ID)


def regeln_aus_db(regel: Arbeitsregel, woche: date) -> Arbeitsregeln:
    """Baut die Regeln für eine Woche; Feiertage und freie Tage dieser Woche werden gesperrt."""
    montag = wochenbeginn(woche)
    freie = gesperrte_tage(regel.freie_tage or [], montag, montag + timedelta(days=6))
    return Arbeitsregeln(
        stunden_pro_woche=regel.stunden_pro_woche,
        tage=frozenset(regel.tage or []),
        bevorzugte_tage=frozenset(regel.bevorzugte_tage or []),
        fruehester_beginn=regel.fruehester_beginn,
        spaetestes_ende=regel.spaetestes_ende,
        min_block=timedelta(minutes=regel.min_block_minuten),
        max_block=timedelta(minutes=regel.max_block_minuten),
        puffer=timedelta(minutes=regel.puffer_minuten),
        freie_tage=frozenset(freie),
        max_tag=timedelta(hours=_oder(regel.max_tag_stunden, 9)),
        lernfenster=timedelta(minutes=_oder(regel.lernfenster_minuten, 120)),
        voller_unitag=timedelta(hours=_oder(regel.voller_unitag_stunden, 6)),
        min_freie_tage=_oder(regel.min_freie_tage, 1),
        gewichte=Gewichte(**{**STANDARD_GEWICHTE, **(regel.gewichte or {})}),
    )


def _oder(wert, standard):
    """Standardwert für Spalten, die in alten Datenbanken NULL sein können."""
    return standard if wert is None else wert


def plan_termin(termin: Termin) -> PlanTermin:
    return PlanTermin(
        start=termin.start,
        ende=termin.ende,
        titel=termin.anzeigename,
        anwesenheitspflicht=termin.hat_anwesenheitspflicht,
        aufzeichnung=termin.wird_aufgezeichnet,
        pruefung=termin.ist_pruefung,
        abgabe=termin.ist_abgabe,
        vorlesung=termin.typ in (TYP_VO, TYP_VU),
        termin_id=termin.id,
    )


def _wochen_grenzen(woche: date) -> tuple[datetime, datetime]:
    start = datetime.combine(wochenbeginn(woche), time())
    return start, start + timedelta(days=7)


def lern_regeln_aus_db(regel: Arbeitsregel) -> LernRegeln:
    return LernRegeln(
        tage=frozenset(_oder(regel.lern_tage, [0, 1, 2, 3, 4, 5])),
        fruehester_beginn=regel.fruehester_beginn,
        spaetestes_ende=regel.spaetestes_ende,
        min_block=timedelta(minutes=_oder(regel.lern_min_block_minuten, 45)),
        max_block=timedelta(minutes=_oder(regel.lern_max_block_minuten, 120)),
        max_tag=timedelta(hours=_oder(regel.max_tag_stunden, 9)),
    )


def _fristen(session: Session, termine: list[Termin]) -> dict[int, list[datetime]]:
    """Übungen, Abgaben und Prüfungen je LVA – auch die der gleichnamigen LVA (VO und UE haben eigene Nummern)."""
    verwandt: dict[tuple[str, str], list[int]] = defaultdict(list)
    for lva in session.scalars(select(Lva)):
        verwandt[(lva.semester, lva.titel.casefold())].append(lva.id)
    fristen: dict[int, list[datetime]] = defaultdict(list)
    for t in termine:
        if t.typ in (TYP_UE, TYP_ABGABE, TYP_PRUEFUNG):
            for lva_id in verwandt[(t.lva.semester, t.lva.titel.casefold())]:
                fristen[lva_id].append(t.start)
    return fristen


def _lernen_planen(session: Session, regel: Arbeitsregel, woche: date, termine: list[Termin],
                   arbeit: list[Arbeitsblock], lern_fest: list[Lernblock]):
    """Schritt 1: Lernblöcke für den offenen Stoff, vor der Arbeitszeit."""
    regeln = regeln_aus_db(regel, woche)
    plan_termine = [plan_termin(t) for t in termine]
    besucht = [t for t in plan_termine if t.ist_pflicht or (not t.aufzeichnung and not t.abgabe)]
    sperren = [t.intervall.erweitert(regeln.puffer) for t in besucht]
    sperren += [Intervall(b.start, b.ende).erweitert(PAUSE) for b in arbeit + lern_fest]

    grundlast: dict[date, timedelta] = defaultdict(timedelta)
    for t in besucht:
        grundlast[t.start.date()] += t.ende - t.start
    for b in arbeit + lern_fest:
        grundlast[b.start.date()] += b.ende - b.start

    stoff = [LernStoff(o.dokument_id, o.lva_id, o.titel, o.erschienen, o.minuten) for o in offene_unterlagen(session, woche)]
    namen = {lva.id: lva.kurzname or lva.titel for lva in session.scalars(select(Lva))}
    plan = plane_lernbloecke(woche, lern_regeln_aus_db(regel), stoff, sperren, grundlast, _fristen(session, termine), namen)
    return plan, namen


def schlage_woche_vor(session: Session, woche: date) -> dict:
    """Ersetzt die offenen Vorschläge einer Woche: zuerst Lernblöcke, danach Arbeitszeit.

    Bestätigte Blöcke bleiben unverändert. Passen Lernen und Arbeit nicht beide in die Woche,
    wird der Konflikt gemeldet statt still gekürzt.
    """
    regel = lade_regel(session)
    if regel is None:
        raise KeineRegelFehler("Bitte zuerst die Arbeitsregel festlegen.")
    von, bis = _wochen_grenzen(woche)

    session.execute(delete(Arbeitsblock).where(
        Arbeitsblock.status == STATUS_VORSCHLAG, Arbeitsblock.start >= von, Arbeitsblock.start < bis))
    session.execute(delete(Lernblock).where(
        Lernblock.status == LERN_VORSCHLAG, Lernblock.start >= von, Lernblock.start < bis))
    # bis eine Woche danach laden: Fristen der Folgewoche und Prüfungen am Montag danach
    termine = session.scalars(
        select(Termin).options(joinedload(Termin.lva)).where(Termin.start < bis + timedelta(days=7), Termin.ende > von)
    ).all()
    termine_woche = [t for t in termine if t.start < bis + timedelta(days=1)]
    arbeit_fest = list(session.scalars(select(Arbeitsblock).where(
        Arbeitsblock.status == STATUS_BESTAETIGT, Arbeitsblock.start < bis, Arbeitsblock.ende > von)))
    lern_fest = list(session.scalars(select(Lernblock).where(
        Lernblock.status == LERN_BESTAETIGT, Lernblock.start < bis, Lernblock.ende > von)))

    # 1. Lernen
    # alle geladenen Termine: auch Fristen der Folgewoche zählen (Übung am Montag danach)
    lernplan, namen = _lernen_planen(session, regel, von.date(), list(termine), arbeit_fest, lern_fest)
    neue_lernbloecke = []
    for v in lernplan.bloecke:
        block = Lernblock(
            lva_id=v.lva_id, start=v.intervall.start, ende=v.intervall.ende, status=LERN_VORSCHLAG,
            thema=", ".join(v.titel)[:500], zuteilung={str(k): m for k, m in v.zuteilung.items()},
        )
        session.add(block)
        neue_lernbloecke.append(block)

    # 2. Arbeit – Lernblöcke sind belegt und zählen zur Tageslast
    regeln = regeln_aus_db(regel, von.date())
    plan_termine = [plan_termin(t) for t in termine_woche]
    feste_arbeit = [Intervall(b.start, b.ende) for b in arbeit_fest]
    feste_lernzeit = [Intervall(b.start, b.ende) for b in lern_fest]
    neue_lernzeit = [v.intervall for v in lernplan.bloecke]
    verteilung = verteile_arbeitszeit(von.date(), regeln, plan_termine, feste_arbeit, feste_lernzeit + neue_lernzeit)

    neue_bloecke = []
    for vorschlag in verteilung.bloecke:
        notiz = None
        if vorschlag.ueberplante_termine:
            notiz = "Überplant: " + ", ".join(t.titel for t in vorschlag.ueberplante_termine)
        block = Arbeitsblock(
            start=vorschlag.intervall.start, ende=vorschlag.intervall.ende, art=ART_FLEXIBEL,
            status=STATUS_VORSCHLAG, arbeitgeber=regel.arbeitgeber, notiz=notiz,
        )
        session.add(block)
        neue_bloecke.append(block)

    # 3. Konflikte sichtbar machen statt still zu kürzen
    konflikte = []
    for lva_id, minuten in lernplan.offen.items():
        konflikte.append(f"Lernen {namen.get(lva_id, lva_id)}: {stunden_text(minuten / 60)} finden diese Woche keinen Platz")
    if verteilung.fehlend > timedelta(0) and neue_lernzeit:
        ohne_lernen = verteile_arbeitszeit(von.date(), regeln, plan_termine, feste_arbeit, feste_lernzeit)
        if ohne_lernen.fehlend < verteilung.fehlend:
            konflikte.append(
                f"Arbeit: {stunden_text(verteilung.fehlend / timedelta(hours=1))} fehlen, weil "
                f"{stunden_text(lernplan.minuten() / 60)} Lernblöcke Vorrang haben (ohne sie fehlten "
                f"{stunden_text(ohne_lernen.fehlend / timedelta(hours=1))}). Lernblöcke verschieben oder verwerfen "
                f"oder weniger Arbeitsstunden einplanen."
            )
    bedarf = wochenbedarf(session, von.date(), _oder(regel.ects_warnschwelle, 0.5))
    session.commit()

    def stunden(d: timedelta) -> float:
        return round(d.total_seconds() / 3600, 2)

    return {
        "woche": von.date(),
        "punktzahl": verteilung.punktzahl,
        "begruendungen": lernplan.begruendungen + verteilung.begruendungen,
        "soll_stunden": stunden(verteilung.soll),
        "verplant_stunden": stunden(verteilung.verplant),
        "fehlende_stunden": stunden(verteilung.fehlend),
        "bloecke": neue_bloecke,
        "lernbloecke": neue_lernbloecke,
        "lern_stunden": round(lernplan.minuten() / 60, 2),
        "lern_offen_stunden": round(sum(lernplan.offen.values()) / 60, 2),
        "konflikte": konflikte,
        "lernbedarf": bedarf,
        "ects_warnungen": [b.warnung for b in bedarf if b.warnung],
        "geopferte_termine": [
            {"id": t.termin_id, "titel": t.titel, "start": t.start, "ende": t.ende}
            for t in verteilung.geopferte_termine
        ],
    }


def stunden_text(h: float) -> str:
    return f"{h:.1f}".replace(".", ",") + " h"


def bestaetige_woche(session: Session, woche: date) -> int:
    """Übernimmt alle Vorschläge der Woche (Arbeit und Lernen) als bestätigte Blöcke."""
    von, bis = _wochen_grenzen(woche)
    anzahl = 0
    for modell, vorschlag, fest in (
        (Arbeitsblock, STATUS_VORSCHLAG, STATUS_BESTAETIGT),
        (Lernblock, LERN_VORSCHLAG, LERN_BESTAETIGT),
    ):
        for block in session.scalars(select(modell).where(modell.status == vorschlag, modell.start >= von, modell.start < bis)):
            block.status = fest
            anzahl += 1
    session.commit()
    return anzahl


def verwerfe_woche(session: Session, woche: date) -> int:
    """Löscht die noch nicht bestätigten Vorschläge der Woche (Abbrechen vor der Bestätigung)."""
    von, bis = _wochen_grenzen(woche)
    anzahl = 0
    for modell, vorschlag in ((Arbeitsblock, STATUS_VORSCHLAG), (Lernblock, LERN_VORSCHLAG)):
        anzahl += session.execute(
            delete(modell).where(modell.status == vorschlag, modell.start >= von, modell.start < bis)
        ).rowcount
    session.commit()
    return anzahl


def plane_wochen_neu(session: Session, wochen: Iterable[date], heute: date | None = None) -> list[date]:
    """Plant nur die betroffenen Wochen ab der aktuellen Woche neu (wenn eine Regel existiert)."""
    if lade_regel(session) is None:
        return []
    ab = wochenbeginn(heute or date.today())
    geplant = []
    for woche in sorted({wochenbeginn(w) for w in wochen}):
        if woche >= ab:
            schlage_woche_vor(session, woche)
            geplant.append(woche)
    return geplant
