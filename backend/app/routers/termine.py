"""Termine abfragen und einzelne Abweichungen von den LVA-Markierungen setzen."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_session
from ..filter import Filter, filter_aus_anfrage, termine_filtern
from ..models import Termin
from ..schemas import TerminOut, TerminUpdate

router = APIRouter(prefix="/api/termine", tags=["Termine"])


def termin_out(t: Termin) -> TerminOut:
    return TerminOut(
        id=t.id,
        lva_id=t.lva_id,
        lva_titel=t.lva.anzeigename,
        lva_farbe=t.lva.farbe,
        typ=t.typ,
        titel=t.titel,
        start=t.start,
        ende=t.ende,
        ort=t.ort,
        beschreibung=t.beschreibung,
        steop_abweichung=t.steop_abweichung,
        anwesenheit_abweichung=t.anwesenheit_abweichung,
        aufzeichnung_abweichung=t.aufzeichnung_abweichung,
        steop=t.ist_steop,
        anwesenheitspflicht=t.hat_anwesenheitspflicht,
        aufzeichnung=t.wird_aufgezeichnet,
        lva_steop=t.lva.steop,
        lva_anwesenheitspflicht=t.lva.anwesenheitspflicht,
        lva_aufzeichnung=t.lva.aufzeichnung,
    )


@router.get("", response_model=list[TerminOut])
def termine_auflisten(f: Filter = Depends(filter_aus_anfrage), session: Session = Depends(get_session)):
    return [termin_out(t) for t in termine_filtern(session, f)]


@router.get("/{termin_id}", response_model=TerminOut)
def termin_lesen(termin_id: int, session: Session = Depends(get_session)):
    termin = session.get(Termin, termin_id)
    if termin is None:
        raise HTTPException(404, "Termin nicht gefunden")
    return termin_out(termin)


@router.patch("/{termin_id}", response_model=TerminOut)
def termin_aendern(termin_id: int, daten: TerminUpdate, session: Session = Depends(get_session)):
    termin = session.get(Termin, termin_id)
    if termin is None:
        raise HTTPException(404, "Termin nicht gefunden")
    # Nur mitgeschickte Felder ändern; ein explizites null setzt auf den LVA-Wert zurück
    for feld in daten.model_fields_set:
        setattr(termin, feld, getattr(daten, feld))
    session.commit()
    return termin_out(termin)
