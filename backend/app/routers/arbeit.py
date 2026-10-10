"""Arbeitsregel, Arbeitsblöcke, fixe Serien und Verteilungsvorschläge."""

import uuid
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..db import get_session
from ..filter import zu_lokal
from ..models import ART_FIX, STATUS_BESTAETIGT, Arbeitsblock, Arbeitsregel
from ..planung_service import (
    REGEL_ID,
    KeineRegelFehler,
    bestaetige_woche,
    lade_regel,
    schlage_woche_vor,
    verwerfe_woche,
)
from ..schemas import (
    ArbeitsblockIn,
    ArbeitsblockOut,
    ArbeitsblockUpdate,
    ArbeitsregelSchema,
    SerieIn,
    SerieOut,
    VorschlagOut,
)

router = APIRouter(prefix="/api/arbeit", tags=["Arbeitszeiten"])


@router.get("/regel", response_model=ArbeitsregelSchema | None)
def regel_lesen(session: Session = Depends(get_session)):
    return lade_regel(session)


@router.put("/regel", response_model=ArbeitsregelSchema)
def regel_speichern(daten: ArbeitsregelSchema, session: Session = Depends(get_session)):
    regel = lade_regel(session) or Arbeitsregel(id=REGEL_ID)
    werte = daten.model_dump()
    # Datumswerte der freien Tage als ISO-Text in der JSON-Spalte ablegen
    werte["freie_tage"] = daten.model_dump(mode="json")["freie_tage"]
    werte["gewichte"] = daten.gewichte.model_dump()
    for feld, wert in werte.items():
        setattr(regel, feld, wert)
    session.add(regel)
    session.commit()
    return regel


@router.get("/bloecke", response_model=list[ArbeitsblockOut])
def bloecke_auflisten(
    von: datetime | None = None, bis: datetime | None = None, session: Session = Depends(get_session)
):
    abfrage = select(Arbeitsblock).order_by(Arbeitsblock.start)
    if von:
        abfrage = abfrage.where(Arbeitsblock.ende > zu_lokal(von))
    if bis:
        abfrage = abfrage.where(Arbeitsblock.start < zu_lokal(bis))
    return session.scalars(abfrage).all()


@router.post("/bloecke", response_model=ArbeitsblockOut, status_code=201)
def block_anlegen(daten: ArbeitsblockIn, session: Session = Depends(get_session)):
    regel = lade_regel(session)
    block = Arbeitsblock(
        start=zu_lokal(daten.start),
        ende=zu_lokal(daten.ende),
        art=ART_FIX,
        status=STATUS_BESTAETIGT,
        arbeitgeber=daten.arbeitgeber or (regel.arbeitgeber if regel else None),
        notiz=daten.notiz,
    )
    session.add(block)
    session.commit()
    return block


@router.patch("/bloecke/{block_id}", response_model=ArbeitsblockOut)
def block_aendern(block_id: int, daten: ArbeitsblockUpdate, session: Session = Depends(get_session)):
    block = session.get(Arbeitsblock, block_id)
    if block is None:
        raise HTTPException(404, "Arbeitsblock nicht gefunden")
    werte = daten.model_dump(exclude_unset=True)
    for feld in ("start", "ende"):
        if werte.get(feld) is not None:
            werte[feld] = zu_lokal(werte[feld])
    for feld, wert in werte.items():
        setattr(block, feld, wert)
    if block.ende <= block.start:
        raise HTTPException(422, "Ende muss nach dem Beginn liegen")
    # Ein verschobener Vorschlag gilt danach als fix (KONZEPT.md, Schritt 6)
    if "start" in werte or "ende" in werte:
        block.status = STATUS_BESTAETIGT
    session.commit()
    return block


@router.delete("/bloecke/{block_id}", status_code=204)
def block_loeschen(block_id: int, session: Session = Depends(get_session)):
    block = session.get(Arbeitsblock, block_id)
    if block is None:
        raise HTTPException(404, "Arbeitsblock nicht gefunden")
    session.delete(block)
    session.commit()


@router.get("/serien", response_model=list[SerieOut])
def serien_auflisten(session: Session = Depends(get_session)):
    zeilen = session.execute(
        select(
            Arbeitsblock.serie_id,
            func.count(Arbeitsblock.id),
            func.min(Arbeitsblock.start),
            func.max(Arbeitsblock.start),
            func.max(Arbeitsblock.arbeitgeber),
            func.max(Arbeitsblock.notiz),
        )
        .where(Arbeitsblock.serie_id.is_not(None))
        .group_by(Arbeitsblock.serie_id)
        .order_by(func.min(Arbeitsblock.start))
    )
    return [
        SerieOut(serie_id=s, anzahl=n, erster=a, letzter=b, arbeitgeber=g, notiz=t) for s, n, a, b, g, t in zeilen
    ]


def erzeuge_serie(daten: SerieIn, arbeitgeber: str | None) -> list[Arbeitsblock]:
    """Legt für jeden passenden Wochentag im Zeitraum einen fixen Block an."""
    serie_id = uuid.uuid4().hex[:12]
    bloecke = []
    tag = daten.von
    while tag <= daten.bis:
        if tag.weekday() in daten.wochentage:
            bloecke.append(
                Arbeitsblock(
                    start=datetime.combine(tag, daten.beginn),
                    ende=datetime.combine(tag, daten.ende),
                    art=ART_FIX,
                    status=STATUS_BESTAETIGT,
                    arbeitgeber=daten.arbeitgeber or arbeitgeber,
                    notiz=daten.notiz,
                    serie_id=serie_id,
                )
            )
        tag += timedelta(days=1)
    return bloecke


@router.post("/serien", response_model=list[ArbeitsblockOut], status_code=201)
def serie_anlegen(daten: SerieIn, session: Session = Depends(get_session)):
    regel = lade_regel(session)
    bloecke = erzeuge_serie(daten, regel.arbeitgeber if regel else None)
    if not bloecke:
        raise HTTPException(422, "Im Zeitraum liegt kein passender Wochentag")
    session.add_all(bloecke)
    session.commit()
    return bloecke


@router.delete("/serien/{serie_id}", status_code=204)
def serie_loeschen(
    serie_id: str, ab: date | None = Query(None, description="nur Blöcke ab diesem Tag löschen"),
    session: Session = Depends(get_session),
):
    bedingung = [Arbeitsblock.serie_id == serie_id]
    if ab:
        bedingung.append(Arbeitsblock.start >= datetime.combine(ab, datetime.min.time()))
    session.execute(delete(Arbeitsblock).where(*bedingung))
    session.commit()


@router.post("/vorschlag", response_model=VorschlagOut)
def vorschlag_berechnen(
    woche: date = Query(..., description="ein beliebiger Tag der Woche"), session: Session = Depends(get_session)
):
    try:
        return schlage_woche_vor(session, woche)
    except KeineRegelFehler as fehler:
        raise HTTPException(409, str(fehler)) from fehler


@router.post("/bestaetigen")
def vorschlaege_bestaetigen(woche: date = Query(...), session: Session = Depends(get_session)):
    return {"bestaetigt": bestaetige_woche(session, woche)}


@router.post("/verwerfen")
def vorschlaege_verwerfen(woche: date = Query(...), session: Session = Depends(get_session)):
    """Bricht die noch nicht bestätigten Vorschläge der Woche ab; bestätigte Blöcke bleiben."""
    return {"verworfen": verwerfe_woche(session, woche)}
