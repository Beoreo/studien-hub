"""Zentrale Einstellungen des Studien-Hubs (Pfade, Zeitzone, Schalter)."""

import os
from pathlib import Path
from zoneinfo import ZoneInfo

PROJEKT_ORDNER = Path(__file__).resolve().parents[2]
DATEN_ORDNER = Path(os.environ.get("STUDIENHUB_DATEN", PROJEKT_ORDNER / "daten"))
DATENBANK_URL = os.environ.get(
    "STUDIENHUB_DB_URL", f"sqlite:///{(DATEN_ORDNER / 'studienhub.db').as_posix()}"
)
FRONTEND_DIST = PROJEKT_ORDNER / "frontend" / "dist"

# Alle Zeiten werden als naive lokale Zeit in dieser Zone gespeichert.
ZEITZONE = ZoneInfo("Europe/Vienna")

# Täglicher TISS-Import über APScheduler; in Tests abgeschaltet.
SCHEDULER_AKTIV = os.environ.get("STUDIENHUB_SCHEDULER", "1") == "1"
SYNC_UHRZEIT = int(os.environ.get("STUDIENHUB_SYNC_STUNDE", "6"))
