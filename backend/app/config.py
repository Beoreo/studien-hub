"""Zentrale Einstellungen des Studien-Hubs (Pfade, Zeitzone, Schalter).

Zwei Betriebsarten:
- Entwicklung (start.ps1, npm run dev): Code und Daten im Projektordner (`studien-hub/daten`).
- Produktion (StudienHub.exe aus dem Installer): Programm unter %LOCALAPPDATA%\\Programs\\StudienHub,
  Daten unter %LOCALAPPDATA%\\StudienHub (Datenbank, Unterlagen, Modelle, Logs, Sicherungen).
Zugangsdaten liegen in beiden Fällen in der Windows-Anmeldeinformationsverwaltung (geheimnisse.py).
"""

import json
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from . import geheimnisse

PRODUKTION = getattr(sys, "frozen", False) or os.environ.get("STUDIENHUB_MODUS") == "produktion"

if getattr(sys, "frozen", False):
    PROGRAMM_ORDNER = Path(sys.executable).resolve().parent  # StudienHub.exe und browser-erweiterung
    PAKET_ORDNER = Path(getattr(sys, "_MEIPASS", PROGRAMM_ORDNER))  # mitgelieferte Dateien (Frontend, VERSION)
    PROJEKT_ORDNER = PROGRAMM_ORDNER
else:
    PROJEKT_ORDNER = Path(__file__).resolve().parents[2]
    PROGRAMM_ORDNER = PAKET_ORDNER = PROJEKT_ORDNER


def _standard_datenordner() -> Path:
    if PRODUKTION:
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "StudienHub"
    return PROJEKT_ORDNER / "daten"


DATEN_ORDNER = Path(os.environ.get("STUDIENHUB_DATEN", _standard_datenordner()))
DATENBANK_DATEI = DATEN_ORDNER / "studienhub.db"
DATENBANK_URL = os.environ.get("STUDIENHUB_DB_URL", f"sqlite:///{DATENBANK_DATEI.as_posix()}")
# Heruntergeladene TUWEL-Unterlagen, je Semester und LVA ein Ordner
UNTERLAGEN_ORDNER = Path(os.environ.get("STUDIENHUB_UNTERLAGEN", DATEN_ORDNER / "unterlagen"))
MODELL_ORDNER = DATEN_ORDNER / "modelle"
LOG_ORDNER = DATEN_ORDNER / "logs"
SICHERUNG_ORDNER = DATEN_ORDNER / "sicherungen"

if getattr(sys, "frozen", False):
    FRONTEND_DIST = PAKET_ORDNER / "frontend"
    ERWEITERUNG_ORDNER = PROGRAMM_ORDNER / "browser-erweiterung"
else:
    FRONTEND_DIST = PROJEKT_ORDNER / "frontend" / "dist"
    ERWEITERUNG_ORDNER = PROJEKT_ORDNER / "browser-erweiterung"


def _version() -> str:
    for datei in (PAKET_ORDNER / "VERSION", PROJEKT_ORDNER / "VERSION"):
        if datei.exists():
            return datei.read_text(encoding="utf-8").strip()
    return "0.0.0"


VERSION = _version()


def build_info() -> dict:
    """Beim Paketieren eingetragen (build.ps1): u. a. der Entwicklungsordner für die Datenübernahme."""
    datei = PAKET_ORDNER / "build_info.json"
    return json.loads(datei.read_text(encoding="utf-8")) if datei.exists() else {}


# Nur Anfragen dieser Seiten/Erweiterungen dürfen den Hub aus dem Browser aufrufen (CORS)
ERWEITERUNG_ID = "jdjohgkcmmpkpgflffjffeaojfmiahcj"  # aus dem festen `key` in browser-erweiterung/manifest.json
HOST, PORT = "127.0.0.1", int(os.environ.get("STUDIENHUB_PORT", "8000"))

# Alle Zeiten werden als naive lokale Zeit in dieser Zone gespeichert.
ZEITZONE = ZoneInfo("Europe/Vienna")

# Tägliche Läufe über APScheduler; in Tests abgeschaltet.
SCHEDULER_AKTIV = os.environ.get("STUDIENHUB_SCHEDULER", "1") == "1"
SYNC_UHRZEIT = int(os.environ.get("STUDIENHUB_SYNC_STUNDE", "6"))

# TUWEL (Moodle) – Stufe 2
TUWEL_URL = os.environ.get("TUWEL_URL", "https://tuwel.tuwien.ac.at").rstrip("/")


def alte_env_uebernehmen() -> list[str]:
    """Entwicklungsmodus: Zugangsdaten aus studien-hub/.env einmalig in die Anmeldeinformationsverwaltung."""
    if PRODUKTION:
        return []
    return geheimnisse.aus_env_uebernehmen(PROJEKT_ORDNER / ".env")


def tuwel_token() -> str | None:
    """Bei jedem Aufruf frisch lesen, damit ein neuer Token ohne Neustart greift."""
    return geheimnisse.lies("TUWEL_TOKEN")


# MB Cloud der Fachschaft (Nextcloud, WebDAV) – App-Passwort statt TU-Passwort
MBCLOUD_STANDARD_URL = "https://mbcloud.at"
MBCLOUD_WURZEL = os.environ.get("MBCLOUD_WURZEL", "MB_VT_WIMB")  # Team-Ordner mit den LVA-Ordnern
MBCLOUD_PAUSE_SEKUNDEN = float(os.environ.get("MBCLOUD_PAUSE_SEKUNDEN", "1.0"))  # schonend: Pause je Anfrage


def mbcloud_zugang() -> tuple[str, str, str] | None:
    """(URL, Benutzer, App-Passwort); None, solange nicht verbunden."""
    url = (geheimnisse.lies("MBCLOUD_URL") or "").strip().rstrip("/") or MBCLOUD_STANDARD_URL
    benutzer = (geheimnisse.lies("MBCLOUD_BENUTZER") or "").strip()
    passwort = (geheimnisse.lies("MBCLOUD_APP_PASSWORT") or "").strip()
    return (url, benutzer, passwort) if benutzer and passwort else None


def zugangsdaten_setzen(werte: dict[str, str | None]) -> None:
    """Mehrere Zugangsdaten auf einmal setzen (None = löschen)."""
    for name, wert in werte.items():
        geheimnisse.setze(name, wert)
