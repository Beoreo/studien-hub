"""Sicherungen der Datenbank: täglich eine, die 14 neuesten bleiben; Wiederherstellen per Klick im Hub.

Gesichert und wiederhergestellt wird mit der Backup-API von SQLite – das ist auch bei laufendem Hub konsistent.
Vor jedem Wiederherstellen wird der aktuelle Stand selbst gesichert, damit nichts verloren geht.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from .config import DATENBANK_DATEI, SICHERUNG_ORDNER

BEHALTEN = 14
MUSTER = re.compile(r"^studienhub-(\d{8}-\d{6})(?:-([a-z-]+))?\.db$")
log = logging.getLogger("studienhub.sicherung")


class SicherungsFehler(Exception):
    pass


def _kopieren(quelle: Path, ziel: Path) -> None:
    von, nach = sqlite3.connect(quelle), sqlite3.connect(ziel)
    try:
        von.backup(nach)
    finally:
        von.close()
        nach.close()


def sichern(anlass: str | None = None, datenbank: Path = DATENBANK_DATEI, ordner: Path = SICHERUNG_ORDNER,
            jetzt: datetime | None = None, mit_aufraeumen: bool = True) -> Path:
    """Legt eine Sicherung an und räumt danach auf (die neuesten BEHALTEN bleiben)."""
    if not datenbank.exists():
        raise SicherungsFehler(f"Keine Datenbank unter {datenbank}.")
    ordner.mkdir(parents=True, exist_ok=True)
    name = f"studienhub-{(jetzt or datetime.now()):%Y%m%d-%H%M%S}{f'-{anlass}' if anlass else ''}.db"
    ziel = ordner / name
    _kopieren(datenbank, ziel)
    if mit_aufraeumen:
        aufraeumen(ordner)
    log.info("Sicherung angelegt: %s", ziel.name)
    return ziel


def liste(ordner: Path = SICHERUNG_ORDNER) -> list[dict]:
    """Neueste zuerst."""
    if not ordner.exists():
        return []
    eintraege = []
    for datei in ordner.iterdir():
        treffer = MUSTER.match(datei.name)
        if treffer:
            eintraege.append({
                "name": datei.name,
                "zeit": datetime.strptime(treffer.group(1), "%Y%m%d-%H%M%S").isoformat(timespec="seconds"),
                "anlass": treffer.group(2),
                "groesse": datei.stat().st_size,
            })
    return sorted(eintraege, key=lambda e: e["name"], reverse=True)


def aufraeumen(ordner: Path = SICHERUNG_ORDNER, behalten: int = BEHALTEN) -> list[str]:
    geloescht = []
    for eintrag in liste(ordner)[behalten:]:
        (ordner / eintrag["name"]).unlink(missing_ok=True)
        geloescht.append(eintrag["name"])
    return geloescht


def wiederherstellen(name: str, datenbank: Path = DATENBANK_DATEI, ordner: Path = SICHERUNG_ORDNER) -> Path:
    """Spielt eine Sicherung in die laufende Datenbank zurück; vorher wird der aktuelle Stand gesichert.
    Gibt die Sicherung des bisherigen Stands zurück."""
    if not MUSTER.match(name) or not (ordner / name).is_file():
        raise SicherungsFehler(f"Sicherung „{name}“ gibt es nicht.")
    # erst nach dem Zurückspielen aufräumen – sonst fiele die älteste Sicherung weg, bevor sie gelesen ist
    vorher = sichern("vor-wiederherstellung", datenbank, ordner, mit_aufraeumen=False)
    _kopieren(ordner / name, datenbank)
    aufraeumen(ordner)
    from .db import verbindungen_erneuern

    verbindungen_erneuern()
    log.warning("Datenbank aus %s wiederhergestellt (vorheriger Stand: %s)", name, vorher.name)
    return vorher


def taegliche_sicherung() -> None:
    """Vom Scheduler aufgerufen; ohne Datenbankdatei (Tests im Speicher) nichts zu tun."""
    if DATENBANK_DATEI.exists():
        sichern()
