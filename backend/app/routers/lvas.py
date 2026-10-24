"""LVAs auflisten und Farbe, Markierungen, TUWEL-Kurs-ID, Ziel und Lernbedarf setzen (Prüfungen: pruefungen.py)."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..db import get_session
from ..lernaufwand import lernparameter, pruefungstermine, typischer_wochenbedarf
from ..models import STANDARD_LERNPARAMETER, Arbeitsregel, Dokument, Lva, LvaTeil, Termin
from ..lva_auswahl import (
    QUELLE_SCHLUESSEL,
    Auswahl,
    erlaubte_ects,
    lade_auswahl,
    setze_erlaubte_ects,
    setze_steop_abgeschlossen,
    steop_abgeschlossen,
    tiss_stand,
    variante_aendern,
    variante_verwerfen,
)
from ..steop_kriterien import auswerten, hat_lvas
from ..models import lies_einstellung
from ..planung_service import auswahl_geaendert, lade_regel
from ..schemas import LvaOut, LvaUpdate, SteopStatus, SteopStatusOut, TeilOut, TeilUpdate, VarianteAenderung

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


def _lva_out(lva: Lva, anzahl: int, videos: tuple[int, int, int] | None, session: Session,
             regel: Arbeitsregel | None, auswahl: Auswahl) -> LvaOut:
    anzahl_videos, dauer, ohne = videos or (0, 0, 0)
    termine = pruefungstermine(session, lva)
    naechste = next((p for p in termine if p[0].date() >= date.today()), termine[-1] if termine else (None, None))
    gesamt, woche = typischer_wochenbedarf(session, lva, regel)
    return LvaOut.model_validate(lva).model_copy(update={
        "ist_steop": auswahl.ist_steop(lva),
        "besucht": auswahl.besucht(lva),
        "lernparameter": lernparameter(lva),
        "lernwochen_standard": regel.lernphase_wochen if regel and regel.lernphase_wochen is not None else 2,
        "pruefung": naechste[0],
        "pruefung_quelle": naechste[1],
        "gesamtbedarf_minuten": gesamt,
        "wochenbedarf_minuten": woche,
        "anzahl_termine": anzahl,
        "anzahl_videos": anzahl_videos,
        "video_dauer_sekunden": dauer,
        "videos_ohne_dauer": ohne,
        "teile": [teil_out(t, session) for t in lva.teile],
    })


def teil_out(teil: LvaTeil, session: Session | None) -> TeilOut:
    anzahl = session.scalar(select(func.count(Termin.id)).where(Termin.teil_id == teil.id)) if session else 0
    return TeilOut.model_validate(teil).model_copy(update={"anzahl_termine": anzahl or 0})


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
    regel = lade_regel(session)
    auswahl = lade_auswahl(session)
    return [_lva_out(lva, anzahl, videos.get(lva.id), session, regel, auswahl)
            for lva, anzahl in session.execute(abfrage)]


def steop_status_out(session: Session) -> SteopStatusOut:
    auswahl = lade_auswahl(session)
    erlaubt, erlaubt_quelle = erlaubte_ects(session)
    semester_lvas = session.scalars(select(Lva).where(Lva.semester == auswahl.semester)).all()
    steop = [l for l in semester_lvas if auswahl.ist_steop(l)]
    gewaehlt = sum(1 for l in steop if l.id in auswahl.variante)
    vorgezogen = sum(l.ects or 0 for l in semester_lvas if l.id in auswahl.variante and not auswahl.ist_steop(l))
    warnungen, kriterien = [], []
    if not auswahl.fertig:
        kriterien = auswerten(auswahl.kriterien, auswahl.angebot, auswahl.variante, auswahl.ects)
        # was mit allen LVAs dieses Semesters ginge – unterscheidet „nicht gewählt“ von „nicht angeboten“
        moeglich = auswerten(auswahl.kriterien, auswahl.angebot, set(auswahl.angebot), auswahl.ects)
        for k, m in zip(kriterien, moeglich):
            name = k.get("name") or "Ein Kriterium"
            if not hat_lvas(k):
                warnungen.append(f"{name}: keine LVAs aus TISS bekannt – in TISS „STEOP Status“ das Kriterium aufklappen.")
            elif not m["erfuellt_variante"]:
                warnungen.append(f"{name} ist mit den LVAs dieses Semesters nicht erfüllbar – folgt später.")
            elif not k["erfuellt_variante"]:
                warnungen.append(f"{name} ist mit dieser Variante nicht erfüllt.")
        if not auswahl.kriterien and len(steop) > gewaehlt:
            warnungen.append(f"Nur {gewaehlt} von {len(steop)} STEOP-LVAs in der Variante.")
        if vorgezogen > (erlaubt or 0):
            warnungen.append("Mehr Nicht-STEOP-ECTS in der Variante als erlaubt.")
    return SteopStatusOut(
        abgeschlossen=auswahl.fertig, quelle=lies_einstellung(session, QUELLE_SCHLUESSEL), tiss=tiss_stand(session),
        erlaubte_ects=erlaubt, erlaubte_ects_quelle=erlaubt_quelle, vorgezogen_ects=0 if auswahl.fertig else vorgezogen,
        semester=auswahl.semester, steop_gesamt=len(steop), steop_gewaehlt=0 if auswahl.fertig else gewaehlt,
        variante_bearbeitet=auswahl.bearbeitet, kriterien=kriterien, verknuepfung=auswahl.verknuepfung,
        warnungen=warnungen,
    )


@router.get("/steop", response_model=SteopStatusOut)
def steop_status(session: Session = Depends(get_session)):
    """STEOP-Status (aus TISS oder von Hand) und die geltende Variante, solange die STEOP offen ist."""
    return steop_status_out(session)


@router.put("/steop", response_model=SteopStatusOut)
def steop_status_setzen(daten: SteopStatus, session: Session = Depends(get_session)):
    """Status (der nächste Stand aus TISS überschreibt ihn wieder) und erlaubte ECTS von Hand setzen.
    Eine neue ECTS-Grenze erzeugt die Variante neu."""
    werte = daten.model_dump(exclude_unset=True)
    if werte.get("abgeschlossen") is not None:
        setze_steop_abgeschlossen(session, werte["abgeschlossen"], quelle="manuell")
    if "erlaubte_ects" in werte:
        setze_erlaubte_ects(session, werte["erlaubte_ects"])
    session.commit()
    auswahl_geaendert(session)
    return steop_status_out(session)


@router.post("/steop/variante", response_model=SteopStatusOut)
def steop_variante_neu(session: Session = Depends(get_session)):
    """Bearbeitete Variante verwerfen und neu erzeugen."""
    variante_verwerfen(session)
    session.commit()
    auswahl_geaendert(session)
    return steop_status_out(session)


@router.put("/steop/variante/{lva_id}", response_model=SteopStatusOut)
def steop_variante_aendern(lva_id: int, daten: VarianteAenderung, session: Session = Depends(get_session)):
    """Eine LVA in die Variante aufnehmen oder herausnehmen (nur solange die STEOP offen ist)."""
    if session.get(Lva, lva_id) is None:
        raise HTTPException(404, "LVA nicht gefunden")
    if steop_abgeschlossen(session):
        raise HTTPException(409, "STEOP ist abgeschlossen – keine Variante nötig")
    variante_aendern(session, lva_id, daten.enthalten)
    session.commit()
    auswahl_geaendert(session)
    return steop_status_out(session)


@router.patch("/{lva_id}", response_model=LvaOut)
def lva_aendern(lva_id: int, daten: LvaUpdate, session: Session = Depends(get_session)):
    lva = session.get(Lva, lva_id)
    if lva is None:
        raise HTTPException(404, "LVA nicht gefunden")
    werte = daten.model_dump(exclude_unset=True)
    if "lernparameter" in werte:
        neu = werte.pop("lernparameter") or {}
        unbekannt = set(neu) - set(STANDARD_LERNPARAMETER)
        if unbekannt or any(v < 0 for v in neu.values()):
            raise HTTPException(422, f"Ungültige Lernparameter: {sorted(unbekannt) or 'negative Werte'}")
        # nur Abweichungen vom Standard speichern, damit spätere Standardänderungen greifen
        abweichend = {**(lva.lernparameter or {}), **neu}
        lva.lernparameter = {k: v for k, v in abweichend.items() if v != STANDARD_LERNPARAMETER[k]} or None
    for feld, wert in werte.items():
        setattr(lva, feld, wert)
        # Markierungen an der LVA gelten als Vorgabe für alle Teile
        if feld in ("steop", "anwesenheitspflicht", "aufzeichnung"):
            for teil in lva.teile:
                setattr(teil, feld, wert)
    session.commit()
    if {"besuchen", "steop", "ects", "lernwochen", "ziel", "bedarf_faktor"} & werte.keys():
        # Kalender und Planung folgen der Auswahl (ECTS ändern die erzeugte Variante); Lernwerte ändern die Lernblöcke
        auswahl_geaendert(session)
    anzahl = session.scalar(select(func.count(Termin.id)).where(Termin.lva_id == lva.id))
    return _lva_out(lva, anzahl or 0, video_statistik(session, [lva.id]).get(lva.id), session, lade_regel(session),
                    lade_auswahl(session))


@router.patch("/teile/{teil_id}", response_model=TeilOut)
def teil_aendern(teil_id: int, daten: TeilUpdate, session: Session = Depends(get_session)):
    """Markierungen, TUWEL-Kurs und Gruppenname eines Teils (VO, UE, Gruppe …)."""
    teil = session.get(LvaTeil, teil_id)
    if teil is None:
        raise HTTPException(404, "Teil nicht gefunden")
    werte = daten.model_dump(exclude_unset=True)
    for feld, wert in werte.items():
        setattr(teil, feld, wert)
    session.commit()
    if "steop" in werte:
        auswahl_geaendert(session)  # STEOP-Markierung entscheidet, ob die LVA besucht wird
    return teil_out(teil, session)
