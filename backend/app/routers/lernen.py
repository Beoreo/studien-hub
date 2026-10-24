"""Lernblöcke (Vorschläge des Planers) und Lernbedarf je Woche."""

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..filter import zu_lokal
from ..lernaufwand import wochenbedarf
from ..models import LERN_BESTAETIGT, LERN_VORSCHLAG, Lernblock
from ..planung_service import _bedarf_out, lade_regel, rest_neu_planen, vorschlag_verwerfen
from ..schemas import LernblockOut, LernblockUpdate, WochenbedarfOut

router = APIRouter(prefix="/api/lernen", tags=["Lernen"])


def lernblock_out(b: Lernblock) -> LernblockOut:
    return LernblockOut(
        id=b.id, lva_id=b.lva_id, lva_name=b.lva.anzeigename, lva_farbe=b.lva.farbe, thema=b.thema,
        start=b.start, ende=b.ende, status=b.status, erledigt=b.erledigt,
        tatsaechliche_minuten=b.tatsaechliche_minuten, geplante_minuten=b.geplante_minuten, notiz=b.notiz,
        zuteilung={str(k): int(v) for k, v in (b.zuteilung or {}).items()},
        altpruefung=_altpruefung(b),
    )


def _altpruefung(b: Lernblock) -> dict | None:
    """Altprüfung aus der MB Cloud, die dieser Block behandelt (für „erledigt“ mit Zeit und Punkten)."""
    from sqlalchemy.orm import object_session

    from ..models import Dokument

    session = object_session(b)
    for dok_id in (b.zuteilung or {}):
        doc = session.get(Dokument, int(dok_id)) if session else None
        if doc is not None and doc.quelle == "mbcloud" and doc.kategorie == "altpruefung":
            return {"dokument_id": doc.id, "dateiname": doc.dateiname, "jahr": doc.jahr,
                    "bearbeitet_am": doc.bearbeitet_am, "punkte": doc.punkte, "punkte_max": doc.punkte_max}
    return None


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
    if {"start", "ende", "status"} & werte.keys():
        rest_neu_planen(session, block.start.date())  # nur den Rest der Woche neu planen
    session.refresh(block)
    return lernblock_out(block)


@router.delete("/bloecke/{block_id}", status_code=204)
def block_loeschen(block_id: int, session: Session = Depends(get_session)):
    block = session.get(Lernblock, block_id)
    if block is None:
        raise HTTPException(404, "Lernblock nicht gefunden")
    if block.status == LERN_VORSCHLAG:
        vorschlag_verwerfen(session, "lernen", block)
    tag = block.start.date()
    session.delete(block)
    session.commit()
    rest_neu_planen(session, tag)


@router.get("/bedarf", response_model=list[WochenbedarfOut])
def bedarf(woche: date = Query(...), session: Session = Depends(get_session)):
    """Lernbedarf je LVA aus den ECTS: Soll dieser Woche, Rückstand, nächste Prüfung."""
    ergebnis = []
    for b, _ in wochenbedarf(session, woche, lade_regel(session)):
        geplant = sum(x.geplante_minuten for x in session.scalars(select(Lernblock).where(
            Lernblock.lva_id == b.lva_id, Lernblock.start >= _montag(woche), Lernblock.start < _montag(woche) + timedelta(days=7))))
        ergebnis.append(WochenbedarfOut(**_bedarf_out(b, geplant)))
    return ergebnis


def _montag(tag: date) -> datetime:
    return datetime.combine(tag - timedelta(days=tag.weekday()), datetime.min.time())
