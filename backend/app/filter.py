"""Gemeinsame Filterlogik für Kalenderansicht und Export.

Filter nach LVA, Typ (VO/UE/…), Markierung und Arbeit (KONZEPT.md, Bereich „Filter und Export“).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fastapi import Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .config import ZEITZONE
from .models import STATUS_BESTAETIGT, Arbeitsblock, Termin

MARKIERUNGEN = ("steop", "anwesenheit", "aufzeichnung")
ARBEIT_MIT, ARBEIT_OHNE, ARBEIT_NUR = "mit", "ohne", "nur"


@dataclass
class Filter:
    von: datetime | None = None
    bis: datetime | None = None
    lva_ids: list[int] | None = None
    typen: list[str] | None = None
    markierungen: list[str] | None = None  # Termin muss mindestens eine davon tragen
    arbeit: str = ARBEIT_MIT
    vorschlaege: bool = True  # unbestätigte Arbeitsvorschläge einbeziehen


def termin_hat_markierung(termin: Termin, markierung: str) -> bool:
    return {
        "steop": termin.ist_steop,
        "anwesenheit": termin.hat_anwesenheitspflicht,
        "aufzeichnung": termin.wird_aufgezeichnet,
    }[markierung]


def termine_filtern(session: Session, f: Filter) -> list[Termin]:
    if f.arbeit == ARBEIT_NUR:
        return []
    abfrage = select(Termin).options(joinedload(Termin.lva)).order_by(Termin.start)
    if f.von:
        abfrage = abfrage.where(Termin.ende > f.von)
    if f.bis:
        abfrage = abfrage.where(Termin.start < f.bis)
    if f.lva_ids:
        abfrage = abfrage.where(Termin.lva_id.in_(f.lva_ids))
    if f.typen:
        abfrage = abfrage.where(Termin.typ.in_(f.typen))
    termine = list(session.scalars(abfrage).unique())
    if f.markierungen:
        termine = [t for t in termine if any(termin_hat_markierung(t, m) for m in f.markierungen)]
    return termine


def arbeitsbloecke_filtern(session: Session, f: Filter) -> list[Arbeitsblock]:
    if f.arbeit == ARBEIT_OHNE:
        return []
    abfrage = select(Arbeitsblock).order_by(Arbeitsblock.start)
    if f.von:
        abfrage = abfrage.where(Arbeitsblock.ende > f.von)
    if f.bis:
        abfrage = abfrage.where(Arbeitsblock.start < f.bis)
    if not f.vorschlaege:
        abfrage = abfrage.where(Arbeitsblock.status == STATUS_BESTAETIGT)
    return list(session.scalars(abfrage))


def _liste(wert: str | None) -> list[str] | None:
    if not wert:
        return None
    teile = [t.strip() for t in wert.split(",") if t.strip()]
    return teile or None


def zu_lokal(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is not None:
        return dt.astimezone(ZEITZONE).replace(tzinfo=None)
    return dt


def filter_aus_anfrage(
    von: datetime | None = Query(None, description="Beginn des Zeitraums"),
    bis: datetime | None = Query(None, description="Ende des Zeitraums (exklusiv)"),
    lva: str | None = Query(None, description="LVA-IDs, kommagetrennt"),
    typ: str | None = Query(None, description="Typen, kommagetrennt (VO,UE,VU,PRUEFUNG,SONSTIGE)"),
    markierung: str | None = Query(None, description="steop,anwesenheit,aufzeichnung"),
    arbeit: str = Query(ARBEIT_MIT, pattern="^(mit|ohne|nur)$"),
    vorschlaege: bool = Query(True),
) -> Filter:
    """FastAPI-Abhängigkeit: baut den Filter aus den Query-Parametern."""
    lva_ids = [int(x) for x in _liste(lva) or []] or None
    markierungen = [m for m in _liste(markierung) or [] if m in MARKIERUNGEN] or None
    return Filter(
        von=zu_lokal(von),
        bis=zu_lokal(bis),
        lva_ids=lva_ids,
        typen=_liste(typ),
        markierungen=markierungen,
        arbeit=arbeit,
        vorschlaege=vorschlaege,
    )
