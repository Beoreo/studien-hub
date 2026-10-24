"""Logs mit Rotation (5 Dateien à 2 MB unter logs/) und die letzten Warnungen/Fehler für die Status-Seite."""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import LOG_ORDNER

LOG_DATEI = "studienhub.log"
FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_letzte: deque[dict] = deque(maxlen=50)


class _Merker(logging.Handler):
    """Hält Warnungen und Fehler im Speicher, damit die Status-Seite sie ohne Dateizugriff zeigen kann."""

    def emit(self, eintrag: logging.LogRecord) -> None:
        meldung = eintrag.getMessage()
        if eintrag.exc_info and eintrag.exc_info[1] is not None:
            meldung = f"{meldung}: {eintrag.exc_info[1]}"
        _letzte.append({
            "zeit": datetime.fromtimestamp(eintrag.created).isoformat(timespec="seconds"),
            "stufe": eintrag.levelname,
            "quelle": eintrag.name,
            "meldung": meldung[:500],
        })


def einrichten(ordner: Path = LOG_ORDNER, datei: bool = True) -> None:
    """Einmal beim Start; weitere Aufrufe ändern nichts."""
    wurzel = logging.getLogger()
    if any(isinstance(h, _Merker) for h in wurzel.handlers):
        return
    wurzel.setLevel(logging.INFO)
    merker = _Merker(level=logging.WARNING)
    wurzel.addHandler(merker)
    if datei:
        ordner.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(ordner / LOG_DATEI, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
        handler.setFormatter(logging.Formatter(FORMAT))
        wurzel.addHandler(handler)
    # Zugriffe einzeln zu loggen bläht die Datei nur auf
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def letzte_meldungen(anzahl: int = 20) -> list[dict]:
    """Neueste zuerst."""
    return list(reversed(_letzte))[:anzahl]
