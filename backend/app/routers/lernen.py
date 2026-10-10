"""Lernblöcke (Vorschläge des Planers) und Lernbedarf je Woche."""

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..filter import zu_lokal
from ..lernaufwand import wochenbedarf
from ..models import LERN_BESTAETIGT, Lernblock
from ..planung_service import _oder, lade_regel
from ..schemas import LernblockOut, LernblockUpdate, WochenbedarfOut

router = APIRouter(prefix="/api/lernen", tags=["Lernen"])


def lernblock_out(b: Lernblock) -> LernblockOut:
    return LernblockOut(
        id=b.id, lva_id=b.lva_id, lva_name=b.lva.kurzname or b.lva.titel, lva_farbe=b.lva.farbe, thema=b.thema,
        start=b.start, ende=b.ende, status=b.status, erledigt=b.erledigt,
        tatsaechliche_minuten=b.tatsaechliche_minuten, geplante_minuten=b.geplante_minuten, notiz=b.notiz,
        zuteilung={str(k): int(v) for k, v in (b.zuteilung or {}).items()},
    )


@router.get("/bloecke", response_model=list[LernblockOut])
def bloecke_auflisten(von: datetime | None = None, bis: datetime | None = None, session: Session = Depends(get_session)):
    abfrage = select(Lernblock).order_by(Lernblock.start)
    if von:
        abfrage = abfrage.where(Lernblock.ende > zu_lokal(von))
    if bis:
        abfrage = abfrage.where(Lernblock.start < zu_lokal(bis))
    return [lernblock_out(b) for b in session.scalars(abfrage)]


@router.patch("/bloecke/{block_id}", response_model=LernblockOut)
def block_aendern(block_id: int, daten: LernblockUpdate, session: Session = Depends(get_session)):
    """Verschieben, bestätigen, als erledigt markieren und die tatsächlich gebrauchte Zeit eintragen."""
    block = session.get(Lernblock, block_id)
    if block is None:
        raise HTTPException(404, "Lernblock nicht gefunden")
    werte = daten.model_dump(exclude_unset=True)
    for feld in ("start", "ende"):
        if werte.get(feld) is not None:
            werte[feld] = zu_lokal(werte[feld])
    for feld, wert in werte.items():
        setattr(block, feld, wert)
    if block.ende <= block.start:
        raise HTTPException(422, "Ende muss nach dem Beginn liegen")
    # verschoben oder erledigt: gilt als bestätigt und wird nicht mehr neu geplant
    if {"start", "ende"} & werte.keys() or block.erledigt or block.tatsaechliche_minuten is not None:
        block.status = LERN_BESTAETIGT
    if block.tatsaechliche_minuten is not None:
        block.erledigt = True
    session.commit()
    return lernblock_out(block)


@router.delete("/bloecke/{block_id}", status_code=204)
def block_loeschen(block_id: int, session: Session = Depends(get_session)):
    block = session.get(Lernblock, block_id)
    if block is None:
        raise HTTPException(404, "Lernblock nicht gefunden")
    session.delete(block)
    session.commit()


@router.get("/bedarf", response_model=list[WochenbedarfOut])
def bedarf(woche: date = Query(...), session: Session = Depends(get_session)):
    regel = lade_regel(session)
    schwelle = _oder(regel.ects_warnschwelle, 0.5) if regel else 0.5
    ergebnis = wochenbedarf(session, woche, schwelle)
    session.commit()  # Seitenzahlen, die dabei ermittelt wurden, speichern
    return [WochenbedarfOut.model_validate(b) for b in ergebnis]
