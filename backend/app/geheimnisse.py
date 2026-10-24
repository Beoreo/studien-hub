"""Zugangsdaten in der Windows-Anmeldeinformationsverwaltung (Paket keyring) statt in der .env.

Namen: TUWEL_TOKEN, MBCLOUD_URL, MBCLOUD_BENUTZER, MBCLOUD_APP_PASSWORT, ERWEITERUNG_SCHLUESSEL – alle unter dem
Dienst „StudienHub“. Entwicklungs- und Produktionsmodus teilen sich die Einträge (gleicher Windows-Benutzer).
Mit `STUDIENHUB_GEHEIMNISSE=speicher` (Tests) bleibt alles im Arbeitsspeicher – die echte Verwaltung wird nie berührt.

Beim Start wandern Werte aus einer alten .env einmalig hierher; die Zeilen in der .env werden auskommentiert.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

DIENST = "StudienHub"
NAMEN = ("TUWEL_TOKEN", "MBCLOUD_URL", "MBCLOUD_BENUTZER", "MBCLOUD_APP_PASSWORT", "ERWEITERUNG_SCHLUESSEL")

_speicher: dict[str, str] = {}
log = logging.getLogger("studienhub")


def _im_speicher() -> bool:
    return os.environ.get("STUDIENHUB_GEHEIMNISSE") == "speicher"


def lies(name: str) -> str | None:
    if _im_speicher():
        return _speicher.get(name)
    import keyring

    try:
        return keyring.get_password(DIENST, name) or None
    except Exception:  # Verwaltung nicht erreichbar: wie „nicht gesetzt“ behandeln, aber sichtbar im Log
        log.exception("Zugangsdaten %s konnten nicht gelesen werden", name)
        return None


def setze(name: str, wert: str | None) -> None:
    """Setzt einen Wert; None oder leer löscht ihn."""
    if _im_speicher():
        if wert:
            _speicher[name] = wert
        else:
            _speicher.pop(name, None)
        return
    import keyring
    from keyring.errors import PasswordDeleteError

    if wert:
        keyring.set_password(DIENST, name, wert)
    else:
        try:
            keyring.delete_password(DIENST, name)
        except PasswordDeleteError:
            pass


def alle_loeschen() -> None:
    for name in NAMEN:
        setze(name, None)


def aus_env_uebernehmen(env_datei: Path) -> list[str]:
    """Übernimmt bekannte Zugangsdaten aus einer .env (nur wenn hier noch nichts steht) und kommentiert die Zeilen
    dort aus. Gibt die übernommenen Namen zurück; nicht vorhandene Datei = nichts zu tun."""
    try:
        zeilen = env_datei.read_text(encoding="utf-8").splitlines()
    except OSError:  # fehlt oder kein Zugriff (z. B. anderes Windows-Konto): nichts zu übernehmen
        return []
    uebernommen = []
    for i, zeile in enumerate(zeilen):
        if zeile.lstrip().startswith("#") or "=" not in zeile:
            continue
        name, wert = (t.strip() for t in zeile.split("=", 1))
        if name not in NAMEN or not wert:
            continue
        if not lies(name):
            setze(name, wert)
        uebernommen.append(name)
        zeilen[i] = f"# {name}=  (in die Windows-Anmeldeinformationsverwaltung verschoben, Dienst „{DIENST}“)"
    if uebernommen:
        try:
            env_datei.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
        except OSError:  # z. B. schreibgeschützt: übernommen ist trotzdem, nur die alte Zeile bleibt stehen
            log.warning("%s ließ sich nicht ändern – Zugangsdaten stehen dort weiterhin im Klartext", env_datei)
        log.warning("Zugangsdaten aus %s übernommen: %s", env_datei, ", ".join(uebernommen))
    return uebernommen
