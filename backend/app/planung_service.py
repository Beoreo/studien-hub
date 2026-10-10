"""Verbindet den Verteilungs-Algorithmus mit der Datenbank."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, time, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload

from .feiertage import gesperrte_tage
from .models import ART_FLEXIBEL, STATUS_BESTAETIGT, STATUS_VORSCHLAG, Arbeitsblock, Arbeitsregel, Termin
from .planung import Arbeitsregeln, Intervall, PlanTermin, verteile_arbeitszeit, wochenbeginn

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
    )


def plan_termin(termin: Termin) -> PlanTermin:
    return PlanTermin(
        start=termin.start,
        ende=termin.ende,
        titel=termin.anzeigename,
        anwesenheitspflicht=termin.hat_anwesenheitspflicht,
        aufzeichnung=termin.wird_aufgezeichnet,
        pruefung=termin.ist_pruefung,
        termin_id=termin.id,
    )


def _wochen_grenzen(woche: date) -> tuple[datetime, datetime]:
    start = datetime.combine(wochenbeginn(woche), time())
    return start, start + timedelta(days=7)


def schlage_woche_vor(session: Session, woche: date) -> dict:
    """Ersetzt die offenen Vorschläge einer Woche durch einen neuen Vorschlag.

    Bestätigte Blöcke bleiben unverändert und zählen zu den Wochenstunden.
    """
    regel = lade_regel(session)
    if regel is None:
        raise KeineRegelFehler("Bitte zuerst die Arbeitsregel festlegen.")
    von, bis = _wochen_grenzen(woche)

    session.execute(
        delete(Arbeitsblock).where(
            Arbeitsblock.status == STATUS_VORSCHLAG, Arbeitsblock.start >= von, Arbeitsblock.start < bis
        )
    )
    termine = session.scalars(
        select(Termin).options(joinedload(Termin.lva)).where(Termin.start < bis, Termin.ende > von)
    ).all()
    bestaetigt = session.scalars(
        select(Arbeitsblock).where(
            Arbeitsblock.status == STATUS_BESTAETIGT, Arbeitsblock.start < bis, Arbeitsblock.ende > von
        )
    ).all()

    verteilung = verteile_arbeitszeit(
        von.date(),
        regeln_aus_db(regel, von.date()),
        [plan_termin(t) for t in termine],
        [Intervall(b.start, b.ende) for b in bestaetigt],
    )

    neue_bloecke = []
    for vorschlag in verteilung.bloecke:
        notiz = None
        if vorschlag.ueberplante_termine:
            notiz = "Überplant: " + ", ".join(t.titel for t in vorschlag.ueberplante_termine)
        block = Arbeitsblock(
            start=vorschlag.intervall.start,
            ende=vorschlag.intervall.ende,
            art=ART_FLEXIBEL,
            status=STATUS_VORSCHLAG,
            arbeitgeber=regel.arbeitgeber,
            notiz=notiz,
        )
        session.add(block)
        neue_bloecke.append(block)
    session.commit()

    stunden = lambda d: round(d.total_seconds() / 3600, 2)  # noqa: E731
    return {
        "woche": von.date(),
        "soll_stunden": stunden(verteilung.soll),
        "verplant_stunden": stunden(verteilung.verplant),
        "fehlende_stunden": stunden(verteilung.fehlend),
        "bloecke": neue_bloecke,
        "geopferte_termine": [
            {"id": t.termin_id, "titel": t.titel, "start": t.start, "ende": t.ende}
            for t in verteilung.geopferte_termine
        ],
    }


def bestaetige_woche(session: Session, woche: date) -> int:
    """Übernimmt alle Vorschläge der Woche als bestätigte (fixe) Blöcke."""
    von, bis = _wochen_grenzen(woche)
    bloecke = session.scalars(
        select(Arbeitsblock).where(
            Arbeitsblock.status == STATUS_VORSCHLAG, Arbeitsblock.start >= von, Arbeitsblock.start < bis
        )
    ).all()
    for block in bloecke:
        block.status = STATUS_BESTAETIGT
    session.commit()
    return len(bloecke)


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
