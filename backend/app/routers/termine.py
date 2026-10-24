"""Termine abfragen, Abweichungen von den LVA-Markierungen setzen, eigene Termine im Kalender anlegen.

Eigene Termine gibt es zu einer LVA (`Termin` mit quelle „manuell“ – der TISS-Import lässt sie stehen) und ohne LVA
(`PersoenlicherTermin`). Beide halten Arbeits- und Lernplanung frei; wer sie anlegt, ändert oder löscht, bekommt die
Vorschläge der Woche neu geplant.
"""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from ..db import get_session
from ..filter import Filter, filter_aus_anfrage, termine_filtern
from ..models import Lva, PersoenlicherTermin, Termin
from ..planung_service import rest_neu_planen
from ..schemas import PersoenlichAenderung, PersoenlichNeu, PersoenlichOut, TerminNeu, TerminOut, TerminUpdate

router = APIRouter(prefix="/api/termine", tags=["Termine"])

MANUELL = "manuell"
NUR_EIGENE = {"titel", "start", "ende", "ort", "typ"}  # bei TISS-Terminen bestimmt TISS diese Felder


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
        lva_steop=t.markierungsquelle.steop,
        lva_anwesenheitspflicht=t.markierungsquelle.anwesenheitspflicht,
        lva_aufzeichnung=t.markierungsquelle.aufzeichnung,
        teil_id=t.teil_id,
        teil_bezeichnung=t.teil.bezeichnung if t.teil else None,
        quelle=t.quelle,
    )


def _neu_planen(session: Session, *zeiten) -> None:
    """Wochen der alten und neuen Zeit neu planen (nur Wochen mit Vorschlägen)."""
    for tag in {z.date() for z in zeiten if z is not None}:
        rest_neu_planen(session, tag)


# --- Persönliche Termine (ohne LVA) – vor /{termin_id}, sonst passt „persoenlich“ dort als ID --------------------

@router.post("/persoenlich", response_model=PersoenlichOut, status_code=201)
def persoenlich_anlegen(daten: PersoenlichNeu, session: Session = Depends(get_session)):
    termin = PersoenlicherTermin(**daten.model_dump())
    session.add(termin)
    session.commit()
    _neu_planen(session, termin.start)
    return termin


@router.patch("/persoenlich/{termin_id}", response_model=PersoenlichOut)
def persoenlich_aendern(termin_id: int, daten: PersoenlichAenderung, session: Session = Depends(get_session)):
    termin = session.get(PersoenlicherTermin, termin_id)
    if termin is None:
        raise HTTPException(404, "Termin nicht gefunden")
    vorher = termin.start
    for feld, wert in daten.model_dump(exclude_unset=True).items():
        if wert is None and feld in ("titel", "start", "ende"):
            continue
        setattr(termin, feld, wert)
    if termin.ende <= termin.start:
        session.rollback()
        raise HTTPException(422, "Ende muss nach dem Beginn liegen")
    session.commit()
    _neu_planen(session, vorher, termin.start)
    return termin


@router.delete("/persoenlich/{termin_id}", status_code=204)
def persoenlich_loeschen(termin_id: int, session: Session = Depends(get_session)):
    termin = session.get(PersoenlicherTermin, termin_id)
    if termin is None:
        raise HTTPException(404, "Termin nicht gefunden")
    start = termin.start
    session.delete(termin)
    session.commit()
    _neu_planen(session, start)
    return Response(status_code=204)


# --- Termine einer LVA -------------------------------------------------------------------------------------

@router.get("", response_model=list[TerminOut])
def termine_auflisten(f: Filter = Depends(filter_aus_anfrage), session: Session = Depends(get_session)):
    return [termin_out(t) for t in termine_filtern(session, f)]


@router.post("", response_model=TerminOut, status_code=201)
def termin_anlegen(daten: TerminNeu, session: Session = Depends(get_session)):
    """Eigener Termin zu einer LVA; gehört zum ersten Teil der LVA (Markierungen wie dort, einzeln änderbar)."""
    lva = session.get(Lva, daten.lva_id)
    if lva is None:
        raise HTTPException(404, "LVA nicht gefunden")
    termin = Termin(**daten.model_dump(), teil_id=lva.teile[0].id if lva.teile else None, quelle=MANUELL)
    session.add(termin)
    session.commit()
    _neu_planen(session, termin.start)
    return termin_out(termin)


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
    felder = daten.model_fields_set
    if felder & NUR_EIGENE and termin.quelle != MANUELL:
        raise HTTPException(409, "Zeit, Titel, Ort und Typ eines TISS-Termins kommen aus TISS.")
    vorher = termin.start
    # Nur mitgeschickte Felder ändern; ein explizites null setzt eine Abweichung auf den LVA-Wert zurück
    for feld in felder:
        wert = getattr(daten, feld)
        if wert is None and feld in NUR_EIGENE - {"ort"}:
            continue
        setattr(termin, feld, wert)
    if termin.ende <= termin.start:
        session.rollback()
        raise HTTPException(422, "Ende muss nach dem Beginn liegen")
    session.commit()
    if felder & {"start", "ende", "typ"}:
        _neu_planen(session, vorher, termin.start)
    return termin_out(termin)


@router.delete("/{termin_id}", status_code=204)
def termin_loeschen(termin_id: int, session: Session = Depends(get_session)):
    termin = session.get(Termin, termin_id)
    if termin is None:
        raise HTTPException(404, "Termin nicht gefunden")
    if termin.quelle != MANUELL:
        raise HTTPException(409, "TISS-Termine lassen sich nicht löschen – sie kommen beim nächsten Import wieder.")
    start = termin.start
    session.delete(termin)
    session.commit()
    _neu_planen(session, start)
    return Response(status_code=204)
