"""KI verbinden: MCP-Server in Claude Desktop eintragen, Verarbeitung (Text, Embeddings, Transkripte), Suche."""

import threading

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import ki_einrichtung, verarbeitung
from ..db import get_session
from ..models import setze_einstellung
from ..suche import suchen

router = APIRouter(prefix="/api/ki", tags=["KI"])


@router.get("/status")
def ki_status(session: Session = Depends(get_session)):
    return {"einrichtung": ki_einrichtung.status(), "verarbeitung": verarbeitung.status(session)}


@router.post("/einrichten")
def einrichten():
    """Trägt den Server in claude_desktop_config.json ein (vorher Sicherungskopie)."""
    try:
        return ki_einrichtung.eintragen()
    except ki_einrichtung.EinrichtungsFehler as fehler:
        raise HTTPException(409, str(fehler)) from fehler


@router.post("/austragen")
def austragen():
    try:
        return ki_einrichtung.austragen()
    except ki_einrichtung.EinrichtungsFehler as fehler:
        raise HTTPException(409, str(fehler)) from fehler


@router.post("/verarbeitung")
def verarbeitung_schalten(text: bool | None = None, video: bool | None = None, session: Session = Depends(get_session)):
    """Einschalten lädt beim ersten Lauf das Modell (einmalig), danach läuft alles offline im Hintergrund."""
    if text is not None:
        setze_einstellung(session, verarbeitung.AKTIV_TEXT, "ja" if text else "nein")
    if video is not None:
        setze_einstellung(session, verarbeitung.AKTIV_VIDEO, "ja" if video else "nein")
    session.commit()
    if text:
        threading.Thread(target=verarbeitung.verarbeitungs_lauf, name="verarbeitung", daemon=True).start()
    if video:
        threading.Thread(target=verarbeitung.transkriptions_lauf, name="transkription", daemon=True).start()
    return verarbeitung.status(session)


@router.get("/vorlagen")
def vorlagen():
    """Die Prompt-Vorlagen mit ihren Feldern (für das Kopierfeld auf „KI verbinden“)."""
    from ..mcp_vorlagen import VORLAGEN

    return [{"name": n, "titel": t, "pflicht": p, "optional": o} for n, (t, p, o) in VORLAGEN.items()]


@router.get("/vorlage")
def vorlage(name: str, lva: str | None = None, thema: str | None = None, termin: str | None = None,
            grund: str | None = None, woche: str | None = None, minuten: str | None = None):
    """Fertiger Vorlagentext zum Kopieren in Claude Desktop – falls der Client Prompt-Vorlagen nicht anzeigt."""
    from ..mcp_vorlagen import vorlage_text

    try:
        text = vorlage_text(name, {"lva": lva, "thema": thema, "termin": termin, "grund": grund, "woche": woche, "minuten": minuten})
    except ValueError as fehler:
        raise HTTPException(422, str(fehler)) from fehler
    return {"name": name, "text": text}


@router.get("/suche")
def suche(frage: str, lva_id: int | None = None, anzahl: int = 8, session: Session = Depends(get_session)):
    """Dieselbe Suche, die Claude über MCP nutzt – zum Ausprobieren im Hub."""
    from ..embedding import standard_embedder

    embedder = standard_embedder() if verarbeitung.ist_aktiv(session, verarbeitung.AKTIV_TEXT) else None
    return [t.als_dict() for t in suchen(session, frage, lva_id, min(anzahl, 25), embedder)]
