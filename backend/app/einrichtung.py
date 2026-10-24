"""Einrichtungsassistent beim ersten Start: Daten übernehmen, Zugänge, Erweiterung, KI, Modelle laden.

Datenübernahme: Die installierte exe kennt den Entwicklungsordner (build_info.json, beim Paketieren eingetragen).
Nach Rückfrage im Hub wird dessen Datenbank in die laufende Datenbank gespielt (SQLite-Backup-API, vorher Sicherung
des bisherigen Stands), Unterlagen und Modelle werden kopiert und Zugangsdaten aus der dortigen .env in die
Anmeldeinformationsverwaltung übernommen. Der Entwicklungsordner selbst bleibt unverändert (bis auf die .env).

Modelle: Embedding (Suche) und Whisper (Transkription) werden auf Wunsch heruntergeladen; Fortschritt über die
Größe des Zielordners im Verhältnis zur bekannten Modellgröße.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from . import geheimnisse
from .config import DATEN_ORDNER, DATENBANK_DATEI, MODELL_ORDNER, PRODUKTION, build_info

log = logging.getLogger("studienhub.einrichtung")

ABGESCHLOSSEN = "einrichtung_abgeschlossen"
UEBERNOMMEN = "daten_uebernommen"


# --- Datenübernahme aus dem Entwicklungsordner ---------------------------------------------------------

def entwicklungs_daten(info: dict | None = None) -> Path | None:
    """Datenordner der Entwicklungsumgebung, falls vorhanden und nicht derselbe wie der aktuelle."""
    if not PRODUKTION:
        return None
    projekt = (info if info is not None else build_info()).get("entwicklungsordner")
    if not projekt:
        return None
    ordner = Path(projekt) / "daten"
    if not (ordner / "studienhub.db").is_file() or ordner.resolve() == DATEN_ORDNER.resolve():
        return None
    return ordner


_uebernahme: dict = {"laeuft": False}


def _ordnergroesse(ordner: Path) -> int:
    return sum(d.stat().st_size for d in ordner.rglob("*") if d.is_file()) if ordner.exists() else 0


def _ordner_kopieren(quelle: Path, ziel: Path, fortschritt: dict) -> None:
    """Kopiert alle Dateien, die im Ziel fehlen oder eine andere Größe haben."""
    for datei in quelle.rglob("*"):
        if not datei.is_file():
            continue
        neu = ziel / datei.relative_to(quelle)
        if not (neu.exists() and neu.stat().st_size == datei.stat().st_size):
            neu.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(datei, neu)
        fortschritt["kopiert"] += datei.stat().st_size


def daten_uebernehmen(quelle: Path, datenbank: Path = DATENBANK_DATEI, daten_ordner: Path = DATEN_ORDNER) -> dict:
    """Übernimmt Datenbank, Unterlagen, Modelle und Zugangsdaten. Läuft synchron; für die Oberfläche über
    `uebernahme_starten` in einem Hintergrund-Thread mit Fortschritt."""
    from .db import verbindungen_erneuern
    from .sicherung import sichern

    fortschritt = _uebernahme
    ordner = [("unterlagen", quelle / "unterlagen"), ("modelle", quelle / "modelle")]
    fortschritt.update(kopiert=0, gesamt=sum(_ordnergroesse(o) for _, o in ordner) + quelle.joinpath("studienhub.db").stat().st_size)

    fortschritt["schritt"] = "Datenbank"
    vorher = sichern("vor-uebernahme", datenbank, daten_ordner / "sicherungen") if datenbank.exists() else None
    von, nach = sqlite3.connect(quelle / "studienhub.db"), sqlite3.connect(datenbank)
    try:
        von.backup(nach)
    finally:
        von.close()
        nach.close()
    verbindungen_erneuern()
    fortschritt["kopiert"] += (quelle / "studienhub.db").stat().st_size

    for name, ordner_quelle in ordner:
        fortschritt["schritt"] = name.capitalize()
        if ordner_quelle.exists():
            _ordner_kopieren(ordner_quelle, daten_ordner / name, fortschritt)

    fortschritt["schritt"] = "Zugangsdaten"
    zugaenge = geheimnisse.aus_env_uebernehmen(quelle.parent / ".env")

    from .db import SessionLocal
    from .models import lies_einstellung, setze_einstellung
    from .tuwel_sync import SCHLUESSEL_ERWEITERUNG

    with SessionLocal() as session:
        # Den Schlüssel, den die Erweiterung schon kennt, behalten (statt eines beim ersten Start neu erzeugten)
        if bekannt := lies_einstellung(session, SCHLUESSEL_ERWEITERUNG):
            geheimnisse.setze("ERWEITERUNG_SCHLUESSEL", bekannt)
            setze_einstellung(session, SCHLUESSEL_ERWEITERUNG, None)
        setze_einstellung(session, UEBERNOMMEN, f"{quelle} ({datetime.now():%d.%m.%Y %H:%M})")
        session.commit()
    log.warning("Daten aus %s übernommen (Sicherung vorher: %s)", quelle, vorher.name if vorher else "keine")
    return {"sicherung": vorher.name if vorher else None, "zugaenge": zugaenge}


def uebernahme_starten(quelle: Path) -> bool:
    if _uebernahme.get("laeuft"):
        return False
    _uebernahme.clear()
    _uebernahme.update(laeuft=True, fertig=False, fehler=None, schritt="Vorbereiten", kopiert=0, gesamt=0)

    def lauf():
        try:
            _uebernahme["ergebnis"] = daten_uebernehmen(quelle)
            _uebernahme["fertig"] = True
        except Exception as fehler:
            log.exception("Datenübernahme fehlgeschlagen")
            _uebernahme["fehler"] = str(fehler)
        finally:
            _uebernahme["laeuft"] = False

    threading.Thread(target=lauf, name="datenuebernahme", daemon=True).start()
    return True


def uebernahme_stand() -> dict:
    return dict(_uebernahme)


# --- Modelle ------------------------------------------------------------------------------------------

MODELLE = {
    "embedding": {"name": "Suche (Embedding-Modell)", "groesse": 240_000_000, "ordner": MODELL_ORDNER,
                  "muster": "models--*paraphrase-multilingual*/**/*.onnx", "ohne": "whisper"},
    "whisper": {"name": "Transkription (Whisper small)", "groesse": 484_000_000, "ordner": MODELL_ORDNER / "whisper",
                "muster": "models--*faster-whisper-small*/**/model.bin", "ohne": None},
}
_laden: dict[str, dict] = {}


def modell_vorhanden(name: str) -> bool:
    info = MODELLE[name]
    return info["ordner"].exists() and any(info["ordner"].glob(info["muster"]))


def _modell_herunterladen(name: str) -> None:
    if name == "embedding":
        from fastembed import TextEmbedding

        from .embedding import MODELL

        TextEmbedding(MODELL, cache_dir=str(MODELL_ORDNER))
    else:
        from faster_whisper.utils import download_model

        from .verarbeitung import WHISPER_MODELL

        download_model(WHISPER_MODELL, cache_dir=str(MODELL_ORDNER / "whisper"))


def modell_laden(name: str) -> bool:
    if _laden.get(name, {}).get("laeuft"):
        return False
    info = MODELLE[name]
    info["ordner"].mkdir(parents=True, exist_ok=True)
    _laden[name] = {"laeuft": True, "fehler": None, "start": _belegt(name)}

    def lauf():
        try:
            _modell_herunterladen(name)
        except Exception as fehler:
            log.exception("Modell %s konnte nicht geladen werden", name)
            _laden[name]["fehler"] = str(fehler)
        finally:
            _laden[name]["laeuft"] = False

    threading.Thread(target=lauf, name=f"modell-{name}", daemon=True).start()
    return True


def _belegt(name: str) -> int:
    info = MODELLE[name]
    groesse = _ordnergroesse(info["ordner"])
    if info["ohne"]:
        groesse -= _ordnergroesse(info["ordner"] / info["ohne"])
    return groesse


def modelle_stand() -> list[dict]:
    ergebnis = []
    for name, info in MODELLE.items():
        laden = _laden.get(name, {})
        vorhanden = modell_vorhanden(name)
        prozent = 100 if vorhanden and not laden.get("laeuft") else 0
        if laden.get("laeuft"):
            geladen = max(0, _belegt(name) - laden.get("start", 0))
            prozent = min(99, round(100 * geladen / info["groesse"]))
        ergebnis.append({
            "id": name, "name": info["name"], "groesse_mb": info["groesse"] // 1_000_000, "vorhanden": vorhanden,
            "laeuft": bool(laden.get("laeuft")), "prozent": prozent, "fehler": laden.get("fehler"),
        })
    return ergebnis


# --- TUWEL-Token -------------------------------------------------------------------------------------

def tuwel_token_setzen(eingabe: str) -> None:
    """Nimmt den Anmelde-Link (moodledownloader://token=…) oder den Token selbst."""
    from .tuwel_token import TOKEN_FORM, TokenFehler, token_aus_link

    text = eingabe.strip()
    try:
        token = token_aus_link(text)
    except TokenFehler:
        if not TOKEN_FORM.fullmatch(text):
            raise
        token = text
    geheimnisse.setze("TUWEL_TOKEN", token)
