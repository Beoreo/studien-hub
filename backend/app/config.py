"""Zentrale Einstellungen des Studien-Hubs (Pfade, Zeitzone, Schalter)."""

import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

PROJEKT_ORDNER = Path(__file__).resolve().parents[2]
# Geheimnisse wie der TUWEL-Token stehen in studien-hub/.env (nicht in Git)
load_dotenv(PROJEKT_ORDNER / ".env")
DATEN_ORDNER = Path(os.environ.get("STUDIENHUB_DATEN", PROJEKT_ORDNER / "daten"))
DATENBANK_URL = os.environ.get(
    "STUDIENHUB_DB_URL", f"sqlite:///{(DATEN_ORDNER / 'studienhub.db').as_posix()}"
)
FRONTEND_DIST = PROJEKT_ORDNER / "frontend" / "dist"
# Heruntergeladene TUWEL-Unterlagen, je Semester und LVA ein Ordner
UNTERLAGEN_ORDNER = Path(os.environ.get("STUDIENHUB_UNTERLAGEN", DATEN_ORDNER / "unterlagen"))
ERWEITERUNG_ORDNER = PROJEKT_ORDNER / "browser-erweiterung"

# Alle Zeiten werden als naive lokale Zeit in dieser Zone gespeichert.
ZEITZONE = ZoneInfo("Europe/Vienna")

# Täglicher TISS-Import über APScheduler; in Tests abgeschaltet.
SCHEDULER_AKTIV = os.environ.get("STUDIENHUB_SCHEDULER", "1") == "1"
SYNC_UHRZEIT = int(os.environ.get("STUDIENHUB_SYNC_STUNDE", "6"))

# TUWEL (Moodle) – Stufe 2
TUWEL_URL = os.environ.get("TUWEL_URL", "https://tuwel.tuwien.ac.at").rstrip("/")


def tuwel_token() -> str | None:
    """Token bei jedem Aufruf frisch lesen, damit eine geänderte .env ohne Neustart greift."""
    load_dotenv(PROJEKT_ORDNER / ".env", override=True)
    return os.environ.get("TUWEL_TOKEN", "").strip() or None
