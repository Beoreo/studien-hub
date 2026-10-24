"""Wochenübersicht: Stunden für Uni, Arbeit, Lernen und Freizeit, Prüfungs-Countdown, Lernstand je LVA."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_session
from ..planung_service import wochenuebersicht
from ..schemas import WochenuebersichtOut

router = APIRouter(prefix="/api/planung", tags=["Planung"])


@router.get("/woche", response_model=WochenuebersichtOut)
def woche_ansehen(woche: date = Query(..., description="ein beliebiger Tag der Woche"), session: Session = Depends(get_session)):
    return wochenuebersicht(session, woche)
