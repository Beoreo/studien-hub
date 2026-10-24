"""Wochenbericht aus den TUWEL-Daten: Liste, Einstellung, sofort erstellen (siehe wochenbericht.py)."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import wochenbericht
from ..db import get_session
from ..models import Wochenbericht

router = APIRouter(prefix="/api/wochenbericht", tags=["Wochenbericht"])


def bericht_out(b: Wochenbericht, mit_text: bool = True) -> dict:
    return {
        "id": b.id, "woche": b.woche, "erstellt_am": b.erstellt_am, "status": b.status, "fehler": b.fehler,
        "neue_unterlagen": b.neue_unterlagen or 0, "anlass": b.anlass, "text": b.text if mit_text else None,
    }


@router.get("/status")
def status(session: Session = Depends(get_session)):
    return {"aktiv": wochenbericht.ist_aktiv(session), "stunde": wochenbericht.STUNDE}


class AktivIn(BaseModel):
    aktiv: bool


@router.put("/einstellung")
def einstellung(daten: AktivIn, session: Session = Depends(get_session)):
    wochenbericht.setze_aktiv(session, daten.aktiv)
    return status(session)


@router.post("/erstellen")
def erstellen(woche: date | None = None, session: Session = Depends(get_session)):
    """Bericht für die Woche (Standard: laufende) sofort erstellen; ein vorhandener Bericht der Woche wird ersetzt."""
    return bericht_out(wochenbericht.bericht_erstellen(session, woche, "manuell"))


@router.get("")
def liste(session: Session = Depends(get_session)):
    abfrage = select(Wochenbericht).order_by(Wochenbericht.woche.desc(), Wochenbericht.erstellt_am.desc()).limit(52)
    return [bericht_out(b, mit_text=False) for b in session.scalars(abfrage)]


@router.get("/{bericht_id}")
def lesen(bericht_id: int, session: Session = Depends(get_session)):
    b = session.get(Wochenbericht, bericht_id)
    if b is None:
        raise HTTPException(404, "Bericht nicht gefunden")
    return bericht_out(b)


@router.delete("/{bericht_id}", status_code=204)
def loeschen(bericht_id: int, session: Session = Depends(get_session)):
    b = session.get(Wochenbericht, bericht_id)
    if b is None:
        raise HTTPException(404, "Bericht nicht gefunden")
    session.delete(b)
    session.commit()
