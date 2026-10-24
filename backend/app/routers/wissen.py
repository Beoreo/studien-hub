"""Wissensstand: Themen je LVA (ableiten, bearbeiten), Lernereignisse, fällige Wiederholungen, Notizen."""

from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import UNTERLAGEN_ORDNER
from ..db import get_session
from ..extraktion import lesen as extraktion_lesen
from ..lva_auswahl import besuchte_lva_ids, lade_auswahl
from ..models import Lernereignis, Lva, Notiz, Pruefungsstoff, Thema
from ..pruefungsstoff import themen_aus_text
from ..themen import ereignis_eintragen, faellige_wiederholungen, stoff_uebernehmen, thema_out, themen_ableiten, uebersicht
from ..tuwel_sync import lva_ordner, sicherer_name
from ..wissensstand import ARTEN

router = APIRouter(prefix="/api/wissen", tags=["Wissensstand"])


@router.get("/uebersicht")
def wissens_uebersicht(lva_id: int | None = None, alle: bool = False, session: Session = Depends(get_session)):
    """Je LVA Zeitstrahl, Themen mit Stufe, fällige Wiederholungen und Tage bis zur Prüfung. Standard: alle besuchten
    LVAs des laufenden Semesters (auch ohne Themen); `alle`: jede LVA mit Themen."""
    if lva_id is not None or alle:
        return uebersicht(session, lva_id)
    semester = lade_auswahl(session).semester
    ids = {l.id for l in session.scalars(select(Lva).where(Lva.semester == semester))} & besuchte_lva_ids(session)
    return uebersicht(session, lva_ids=ids)


STOFF_ENDUNGEN = {".pdf", ".docx", ".pptx", ".ppsx", ".odp", ".txt", ".md"}


def stoff_out(s: Pruefungsstoff) -> dict:
    return {"id": s.id, "lva_id": s.lva_id, "pruefung_am": s.pruefung_am, "dateiname": s.dateiname, "themen": s.themen,
            "hochgeladen_am": s.hochgeladen_am}


def _stoff_entfernen(stoff: Pruefungsstoff) -> None:
    (UNTERLAGEN_ORDNER / stoff.pfad).unlink(missing_ok=True)


@router.post("/stoff", status_code=201)
async def stoff_hochladen(lva_id: int = Form(...), pruefung_am: date = Form(...), datei: UploadFile = File(...),
                          session: Session = Depends(get_session)):
    """Prüfungsstoff einer Prüfung hochladen (Stoffliste, Skript oder Folien): Die Themen dieser Prüfung werden daraus
    neu bestimmt; ein früherer Stoff derselben Prüfung wird ersetzt."""
    lva = session.get(Lva, lva_id)
    if lva is None:
        raise HTTPException(404, "LVA nicht gefunden")
    name = Path(datei.filename or "stoff.txt").name
    if Path(name).suffix.lower() not in STOFF_ENDUNGEN:
        raise HTTPException(422, "Bitte PDF, Word (.docx), PowerPoint (.pptx), Impress (.odp) oder Text (.txt/.md) hochladen.")
    relativ = lva_ordner(lva) / "Prüfungsstoff" / sicherer_name(f"{pruefung_am.isoformat()} {name}", 120)
    ziel = UNTERLAGEN_ORDNER / relativ
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_bytes(await datei.read())
    try:
        gelesen = extraktion_lesen(ziel)
    except Exception as fehler:  # beschädigte Datei: sichtbar melden
        ziel.unlink(missing_ok=True)
        raise HTTPException(422, f"Datei nicht lesbar: {fehler}") from fehler
    titel = themen_aus_text(gelesen) if gelesen else []
    if not titel:
        ziel.unlink(missing_ok=True)
        raise HTTPException(422, "Keine Themen erkannt – eine Liste mit einem Thema je Zeile oder ein Skript mit Kapiteln hochladen.")
    for alt in session.scalars(select(Pruefungsstoff).where(Pruefungsstoff.lva_id == lva.id,
                                                            Pruefungsstoff.pruefung_am == pruefung_am)):
        if alt.pfad != relativ.as_posix():
            _stoff_entfernen(alt)
        session.delete(alt)
    stoff = Pruefungsstoff(lva_id=lva.id, pruefung_am=pruefung_am, dateiname=name, pfad=relativ.as_posix(), themen=len(titel))
    session.add(stoff)
    ergebnis = stoff_uebernehmen(session, lva, pruefung_am, titel, _embedder(session))
    return {"stoff": stoff_out(stoff), "themen": titel, **ergebnis}


@router.delete("/stoff/{stoff_id}", status_code=204)
def stoff_loeschen(stoff_id: int, session: Session = Depends(get_session)):
    """Stoff entfernen: Die Prüfung hat danach keine eigenen Themen mehr (es gelten wieder die allgemeinen)."""
    stoff = session.get(Pruefungsstoff, stoff_id)
    if stoff is None:
        raise HTTPException(404, "Prüfungsstoff nicht gefunden")
    lva, tag = session.get(Lva, stoff.lva_id), stoff.pruefung_am
    _stoff_entfernen(stoff)
    session.delete(stoff)
    stoff_uebernehmen(session, lva, tag, [])
    return Response(status_code=204)


@router.get("/stoff/{stoff_id}/datei")
def stoff_datei(stoff_id: int, session: Session = Depends(get_session)):
    stoff = session.get(Pruefungsstoff, stoff_id)
    if stoff is None or not (UNTERLAGEN_ORDNER / stoff.pfad).exists():
        raise HTTPException(404, "Datei nicht gefunden")
    return FileResponse(UNTERLAGEN_ORDNER / stoff.pfad, filename=stoff.dateiname)


def _embedder(session: Session):
    from ..embedding import standard_embedder
    from ..verarbeitung import AKTIV_TEXT, ist_aktiv

    return standard_embedder() if ist_aktiv(session, AKTIV_TEXT) else None


@router.post("/themen/ableiten")
def ableiten(lva_id: int | None = None, session: Session = Depends(get_session)):
    """Themen aus der Kapitelstruktur der Skripte anlegen (fehlende ergänzen, vorhandene bleiben)."""
    from ..embedding import standard_embedder
    from ..verarbeitung import AKTIV_TEXT, ist_aktiv

    embedder = standard_embedder() if ist_aktiv(session, AKTIV_TEXT) else None
    ids = [lva_id] if lva_id else sorted(besuchte_lva_ids(session))
    neu = {}
    for i in ids:
        lva = session.get(Lva, i)
        if lva is None:
            raise HTTPException(404, "LVA nicht gefunden")
        neu[lva.anzeigename] = len(themen_ableiten(session, lva, embedder))
    return {"neue_themen": neu}


class ThemaIn(BaseModel):
    lva_id: int
    titel: str = Field(min_length=1, max_length=300)


class ThemaUpdate(BaseModel):
    titel: str | None = Field(None, min_length=1, max_length=300)
    reihenfolge: int | None = Field(None, ge=1)


@router.post("/themen", status_code=201)
def thema_anlegen(daten: ThemaIn, session: Session = Depends(get_session)):
    if session.get(Lva, daten.lva_id) is None:
        raise HTTPException(404, "LVA nicht gefunden")
    letzte = session.scalar(select(func.max(Thema.reihenfolge)).where(Thema.lva_id == daten.lva_id)) or 0
    thema = Thema(lva_id=daten.lva_id, titel=daten.titel.strip(), reihenfolge=letzte + 1, quelle="manuell")
    session.add(thema)
    session.commit()
    return thema_out(session, thema, date.today())


@router.patch("/themen/{thema_id}")
def thema_aendern(thema_id: int, daten: ThemaUpdate, session: Session = Depends(get_session)):
    """Umbenennen (gilt danach als eigenes Thema) oder an eine neue Position verschieben."""
    thema = session.get(Thema, thema_id)
    if thema is None:
        raise HTTPException(404, "Thema nicht gefunden")
    if daten.titel is not None:
        thema.titel, thema.quelle = daten.titel.strip(), "manuell"
    if daten.reihenfolge is not None:
        themen = [t for t in session.scalars(select(Thema).where(Thema.lva_id == thema.lva_id).order_by(Thema.reihenfolge, Thema.id))
                  if t.id != thema.id]
        themen.insert(min(daten.reihenfolge - 1, len(themen)), thema)
        for i, t in enumerate(themen, start=1):
            t.reihenfolge = i
    session.commit()
    return thema_out(session, thema, date.today())


@router.delete("/themen/{thema_id}", status_code=204)
def thema_loeschen(thema_id: int, session: Session = Depends(get_session)):
    thema = session.get(Thema, thema_id)
    if thema is None:
        raise HTTPException(404, "Thema nicht gefunden")
    session.delete(thema)
    session.commit()


class EreignisIn(BaseModel):
    art: str = Field(pattern="^(" + "|".join(ARTEN) + ")$")
    ergebnis: float | None = Field(None, ge=0, le=1)
    stufe: int | None = Field(None, ge=0, le=4)
    notiz: str | None = None


@router.post("/themen/{thema_id}/ereignis")
def ereignis(thema_id: int, daten: EreignisIn, session: Session = Depends(get_session)):
    """Lernereignis (Quiz, Altprüfung, Selbsteinschätzung, Lernblock) – passt Stufe und Wiederholung an."""
    thema = session.get(Thema, thema_id)
    if thema is None:
        raise HTTPException(404, "Thema nicht gefunden")
    if daten.ergebnis is None and daten.stufe is None:
        raise HTTPException(422, "Ergebnis (0–1) oder Stufe (0–4) angeben")
    e = ereignis_eintragen(session, thema, daten.art, daten.ergebnis, daten.notiz, stufe=daten.stufe)
    return {"ereignis_id": e.id, "stufe_vorher": e.stufe_vorher, "stufe_nachher": e.stufe_nachher,
            "thema": thema_out(session, thema, date.today())}


@router.get("/themen/{thema_id}/abschnitte")
def thema_abschnitte(thema_id: int, session: Session = Depends(get_session)):
    thema = session.get(Thema, thema_id)
    if thema is None:
        raise HTTPException(404, "Thema nicht gefunden")
    return [{"id": a.id, "dokument": a.dokument.dateiname, "dokument_id": a.dokument_id, "fundstelle": a.fundstelle,
             "quelle": a.quelle, "offiziell": a.offiziell, "jahr": a.jahr, "text": a.text[:300]} for a in thema.abschnitte]


@router.get("/faellig")
def faellig(lva_id: int | None = None, session: Session = Depends(get_session)):
    return faellige_wiederholungen(session, lva_id)


@router.get("/ereignisse")
def ereignisse(lva_id: int | None = None, anzahl: int = Query(50, le=500), session: Session = Depends(get_session)):
    abfrage = select(Lernereignis).order_by(Lernereignis.zeitpunkt.desc(), Lernereignis.id.desc()).limit(anzahl)
    if lva_id is not None:
        abfrage = abfrage.where(Lernereignis.lva_id == lva_id)
    return [{"id": e.id, "lva_id": e.lva_id, "thema": e.thema.titel if e.thema else None, "art": e.art,
             "zeitpunkt": e.zeitpunkt, "ergebnis": e.ergebnis, "stufe_vorher": e.stufe_vorher,
             "stufe_nachher": e.stufe_nachher, "notiz": e.notiz, "quelle": e.quelle} for e in session.scalars(abfrage)]


@router.get("/notizen")
def notizen(lva_id: int | None = None, session: Session = Depends(get_session)):
    abfrage = select(Notiz).order_by(Notiz.erstellt_am.desc())
    if lva_id is not None:
        abfrage = abfrage.where(Notiz.lva_id == lva_id)
    return [{"id": n.id, "lva_id": n.lva_id, "thema_id": n.thema_id, "text": n.text, "erstellt_am": n.erstellt_am,
             "quelle": n.quelle} for n in session.scalars(abfrage)]


@router.delete("/notizen/{notiz_id}", status_code=204)
def notiz_loeschen(notiz_id: int, session: Session = Depends(get_session)):
    notiz = session.get(Notiz, notiz_id)
    if notiz is None:
        raise HTTPException(404, "Notiz nicht gefunden")
    session.delete(notiz)
    session.commit()
