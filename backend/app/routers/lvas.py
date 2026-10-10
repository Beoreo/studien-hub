"""LVAs auflisten und Farbe, Markierungen sowie TUWEL-Kurs-ID setzen."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Lva, Termin
from ..schemas import LvaOut, LvaUpdate

router = APIRouter(prefix="/api/lvas", tags=["LVAs"])


def _lva_out(lva: Lva, anzahl: int) -> LvaOut:
    return LvaOut.model_validate(lva).model_copy(update={"anzahl_termine": anzahl})


@router.get("", response_model=list[LvaOut])
def lvas_auflisten(semester: str | None = None, session: Session = Depends(get_session)):
    abfrage = (
        select(Lva, func.count(Termin.id))
        .outerjoin(Termin)
        .group_by(Lva.id)
        .order_by(Lva.semester.desc(), Lva.titel)
    )
    if semester:
        abfrage = abfrage.where(Lva.semester == semester)
    return [_lva_out(lva, anzahl) for lva, anzahl in session.execute(abfrage)]


@router.patch("/{lva_id}", response_model=LvaOut)
def lva_aendern(lva_id: int, daten: LvaUpdate, session: Session = Depends(get_session)):
    lva = session.get(Lva, lva_id)
    if lva is None:
        raise HTTPException(404, "LVA nicht gefunden")
    for feld, wert in daten.model_dump(exclude_unset=True).items():
        setattr(lva, feld, wert)
    session.commit()
    anzahl = session.scalar(select(func.count(Termin.id)).where(Termin.lva_id == lva.id))
    return _lva_out(lva, anzahl or 0)
