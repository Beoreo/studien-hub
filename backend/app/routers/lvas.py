"""LVAs auflisten und Farbe, Markierungen sowie TUWEL-Kurs-ID setzen."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Dokument, Lva, Termin
from ..schemas import LvaOut, LvaUpdate

router = APIRouter(prefix="/api/lvas", tags=["LVAs"])


def video_statistik(session: Session, lva_ids: list[int] | None = None) -> dict[int, tuple[int, int, int]]:
    """Je LVA: (Anzahl Videos, Gesamtdauer in Sekunden, Videos ohne bekannte Dauer)."""
    abfrage = (
        select(
            Dokument.lva_id,
            func.count(Dokument.id),
            func.coalesce(func.sum(Dokument.dauer_sekunden), 0),
            func.sum(case((Dokument.dauer_sekunden.is_(None), 1), else_=0)),
        )
        .where(Dokument.ist_link.is_(True))
        .group_by(Dokument.lva_id)
    )
    if lva_ids is not None:
        abfrage = abfrage.where(Dokument.lva_id.in_(lva_ids))
    return {lva_id: (anzahl, int(dauer), int(ohne or 0)) for lva_id, anzahl, dauer, ohne in session.execute(abfrage)}


def _lva_out(lva: Lva, anzahl: int, videos: tuple[int, int, int] | None = None) -> LvaOut:
    anzahl_videos, dauer, ohne = videos or (0, 0, 0)
    return LvaOut.model_validate(lva).model_copy(update={
        "anzahl_termine": anzahl,
        "anzahl_videos": anzahl_videos,
        "video_dauer_sekunden": dauer,
        "videos_ohne_dauer": ohne,
    })


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
    videos = video_statistik(session)
    return [_lva_out(lva, anzahl, videos.get(lva.id)) for lva, anzahl in session.execute(abfrage)]


@router.patch("/{lva_id}", response_model=LvaOut)
def lva_aendern(lva_id: int, daten: LvaUpdate, session: Session = Depends(get_session)):
    lva = session.get(Lva, lva_id)
    if lva is None:
        raise HTTPException(404, "LVA nicht gefunden")
    for feld, wert in daten.model_dump(exclude_unset=True).items():
        setattr(lva, feld, wert)
    session.commit()
    anzahl = session.scalar(select(func.count(Termin.id)).where(Termin.lva_id == lva.id))
    return _lva_out(lva, anzahl or 0, video_statistik(session, [lva.id]).get(lva.id))
