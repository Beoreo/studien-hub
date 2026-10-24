"""Hintergrundverarbeitung (Stufe 3): Text und Abschnitte je Unterlage, Transkripte der Videos.

- `verarbeite_offene`: neue oder geänderte Dateien (Prüfsumme) lesen, in Abschnitte zerlegen, einbetten.
- `transkribiere_naechstes`: ein Video nach dem anderen mit faster-whisper (lokal, CPU). Die Audiodaten
  kommen von der direkten Videoadresse, die der TUWEL-Sync speichert (`Dokument.medien_url`); die
  heruntergeladene Datei wird nach der Transkription gelöscht.
Beide laufen per Scheduler im Hintergrund, nie parallel zu sich selbst.
"""

from __future__ import annotations

import logging
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Protocol

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .config import DATEN_ORDNER, UNTERLAGEN_ORDNER
from .embedding import Embedder
from .extraktion import abschnitte_bilden, lesen, transkript_abschnitte
from .models import QUELLE_LECTURETUBE, QUELLE_MBCLOUD, QUELLE_TUWEL, Dokument
from .suche import abschnitte_speichern

log = logging.getLogger("studienhub")
WHISPER_MODELL = os.environ.get("STUDIENHUB_WHISPER_MODELL", "small")
_sperre_text = threading.Lock()
_sperre_video = threading.Lock()


def quelle_von(doc: Dokument) -> str:
    if doc.quelle == QUELLE_MBCLOUD:
        return QUELLE_MBCLOUD
    if doc.episode_id or doc.ist_link:
        return QUELLE_LECTURETUBE
    return QUELLE_TUWEL


# --- Text -------------------------------------------------------------------------------------------

def offene_dokumente(session: Session) -> list[Dokument]:
    """Dateien ohne Abschnitte oder mit geänderter Fassung (Prüfsumme)."""
    return list(session.scalars(
        select(Dokument).where(
            Dokument.ist_link.is_(False), Dokument.pfad.is_not(None),
            or_(Dokument.text_status.is_(None), Dokument.text_pruefsumme.is_(None),
                Dokument.text_pruefsumme != Dokument.pruefsumme),
        ).order_by(Dokument.erschienen_am.desc().nulls_last())
    ))


def dokument_verarbeiten(session: Session, doc: Dokument, embedder: Embedder | None) -> str:
    """Liest eine Unterlage und ersetzt ihre Abschnitte. Ergebnis: fertig | leer | fehler."""
    try:
        gelesen = lesen(UNTERLAGEN_ORDNER / doc.pfad)
        rohe = abschnitte_bilden(gelesen) if gelesen else []
        abschnitte_speichern(session, doc, rohe, quelle_von(doc), embedder)
        doc.text_status, doc.text_fehler = ("fertig" if rohe else "leer"), None
    except Exception as fehler:  # beschädigte Datei, fehlendes Modell …: sichtbar machen, nicht abbrechen
        session.rollback()
        doc = session.get(Dokument, doc.id)
        doc.text_status, doc.text_fehler = "fehler", str(fehler)[:500]
    doc.text_pruefsumme = doc.pruefsumme or "ohne"
    session.commit()
    return doc.text_status


def verarbeite_offene(session: Session, embedder: Embedder | None, hoechstens: int | None = 25) -> dict:
    ergebnis = {"fertig": 0, "leer": 0, "fehler": 0}
    for doc in offene_dokumente(session)[:hoechstens]:
        ergebnis[dokument_verarbeiten(session, doc, embedder)] += 1
    return ergebnis


# --- Videos -----------------------------------------------------------------------------------------

class Transkribierer(Protocol):
    def transkribieren(self, pfad: Path) -> list[tuple[float, float, str]]: ...


class WhisperTranskribierer:
    """faster-whisper auf der CPU (int8); Modell einmalig nach daten/modelle/whisper."""

    def __init__(self, modell: str = WHISPER_MODELL):
        self.modell_name = modell
        self._modell = None

    def transkribieren(self, pfad: Path) -> list[tuple[float, float, str]]:
        if self._modell is None:
            from faster_whisper import WhisperModel

            self._modell = WhisperModel(self.modell_name, device="cpu", compute_type="int8",
                                        download_root=str(DATEN_ORDNER / "modelle" / "whisper"),
                                        local_files_only=os.environ.get("STUDIENHUB_OFFLINE") == "1")
        segmente, _ = self._modell.transcribe(str(pfad), language="de", vad_filter=True)
        return [(s.start, s.end, s.text) for s in segmente]


def offene_videos(session: Session) -> list[Dokument]:
    return list(session.scalars(
        select(Dokument).where(Dokument.ist_link.is_(True), Dokument.medien_url.is_not(None),
                               Dokument.transkript_status.is_(None))
        .order_by(Dokument.aufnahme_am.desc().nulls_last(), Dokument.id)
    ))


def _video_laden(url: str, ziel: Path, transport: httpx.BaseTransport | None = None) -> None:
    with httpx.Client(timeout=120, follow_redirects=True, transport=transport) as http, http.stream("GET", url) as antwort:
        if antwort.status_code in (401, 403, 404, 410):
            raise RuntimeError(f"Videoadresse nicht mehr gültig (HTTP {antwort.status_code}) – nach dem nächsten TUWEL-Sync erneut")
        antwort.raise_for_status()
        with open(ziel, "wb") as aus:
            for block in antwort.iter_bytes(1024 * 1024):
                aus.write(block)


def transkribiere_naechstes(session: Session, transkribierer: Transkribierer, embedder: Embedder | None,
                            transport: httpx.BaseTransport | None = None) -> Dokument | None:
    """Transkribiert das nächste offene Video; None, wenn keines wartet."""
    offen = offene_videos(session)
    if not offen:
        return None
    doc = offen[0]
    fd, temp = tempfile.mkstemp(prefix="studienhub-video-", suffix=".mp4")
    os.close(fd)
    try:
        _video_laden(doc.medien_url, Path(temp), transport)
        segmente = transkribierer.transkribieren(Path(temp))
        abschnitte_speichern(session, doc, transkript_abschnitte(segmente), QUELLE_LECTURETUBE, embedder)
        doc.transkript_status, doc.transkript_fehler = "fertig", None
    except Exception as fehler:
        session.rollback()
        doc = session.get(Dokument, doc.id)
        doc.transkript_status, doc.transkript_fehler = "fehler", str(fehler)[:500]
    finally:
        Path(temp).unlink(missing_ok=True)
    session.commit()
    return doc


# --- Hintergrundjobs ---------------------------------------------------------------------------------

AKTIV_TEXT = "ki_verarbeitung_aktiv"  # erst nach Einschalten auf „KI verbinden“: Modell wird einmal geladen
AKTIV_VIDEO = "ki_transkription_aktiv"


def ist_aktiv(session: Session, schluessel: str) -> bool:
    from .models import lies_einstellung

    return lies_einstellung(session, schluessel) == "ja"


def verarbeitungs_lauf(erzwingen: bool = False) -> None:
    """Scheduler: neue Unterlagen lesen und einbetten (höchstens 25 je Lauf)."""
    if not _sperre_text.acquire(blocking=False):
        return
    try:
        from .db import SessionLocal
        from .embedding import standard_embedder

        with SessionLocal() as session:
            if not (erzwingen or ist_aktiv(session, AKTIV_TEXT)):
                return
            ergebnis = verarbeite_offene(session, standard_embedder())
        if any(ergebnis.values()):
            log.info("Unterlagen verarbeitet: %s", ergebnis)
    finally:
        _sperre_text.release()


def transkriptions_lauf(erzwingen: bool = False) -> None:
    """Scheduler: ein Video je Lauf transkribieren (CPU-lastig, daher nacheinander)."""
    if not _sperre_video.acquire(blocking=False):
        return
    try:
        from .db import SessionLocal
        from .embedding import standard_embedder

        with SessionLocal() as session:
            if not (erzwingen or ist_aktiv(session, AKTIV_VIDEO)):
                return
            doc = transkribiere_naechstes(session, WhisperTranskribierer(), standard_embedder())
        if doc is not None:
            log.info("Transkript %s: %s", doc.dateiname, doc.transkript_status)
    finally:
        _sperre_video.release()


def status(session: Session) -> dict:
    """Stand der Verarbeitung für die Seite „KI verbinden“."""
    from sqlalchemy import func

    from .db import VEKTORSUCHE
    from .models import Abschnitt

    zaehle = lambda *bed: session.scalar(select(func.count(Dokument.id)).where(*bed))  # noqa: E731
    return {
        "abschnitte": session.scalar(select(func.count(Abschnitt.id))),
        "dokumente_fertig": zaehle(Dokument.text_status == "fertig"),
        "dokumente_offen": len(offene_dokumente(session)),
        "dokumente_fehler": zaehle(Dokument.text_status == "fehler"),
        "videos_fertig": zaehle(Dokument.transkript_status == "fertig"),
        "videos_offen": len(offene_videos(session)),
        "videos_fehler": zaehle(Dokument.transkript_status == "fehler"),
        "vektorsuche": VEKTORSUCHE["verfuegbar"],
        "verarbeitung_aktiv": ist_aktiv(session, AKTIV_TEXT),
        "transkription_aktiv": ist_aktiv(session, AKTIV_VIDEO),
        "laeuft_text": _sperre_text.locked(),
        "laeuft_video": _sperre_video.locked(),
        "stand": datetime.now().isoformat(timespec="seconds"),
    }
