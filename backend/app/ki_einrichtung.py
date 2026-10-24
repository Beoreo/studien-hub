"""Den MCP-Server in Claude Desktop eintragen (claude_desktop_config.json) – mit Sicherungskopie.

Claude Desktop startet den Server selbst (stdio): installiert `StudienHub.exe --mcp`, in der Entwicklung das Python
der venv:
    {"mcpServers": {"studien-hub": {"command": ".../backend/.venv/Scripts/python.exe",
                                    "args": ["-m", "app.mcp_server"],
                                    "env": {"PYTHONPATH": ".../backend", "STUDIENHUB_OFFLINE": "1", ...}}}}
Andere Einträge der Datei bleiben unverändert. Nach dem Eintragen Claude Desktop ganz beenden und neu starten.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

from .config import PROJEKT_ORDNER

SERVER_NAME = "studien-hub"
BACKEND = PROJEKT_ORDNER / "backend"


class EinrichtungsFehler(Exception):
    pass


def config_kandidaten() -> list[Path]:
    """Mögliche Orte der Konfiguration; die erste vorhandene gewinnt."""
    kandidaten = []
    if sys.platform == "win32":
        if appdata := os.environ.get("APPDATA"):
            kandidaten.append(Path(appdata) / "Claude" / "claude_desktop_config.json")
        if lokal := os.environ.get("LOCALAPPDATA"):  # Version aus dem Microsoft Store (MSIX)
            kandidaten += sorted(Path(lokal, "Packages").glob("Claude_*/LocalCache/Roaming/Claude/claude_desktop_config.json"))
    elif sys.platform == "darwin":
        kandidaten.append(Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json")
    else:
        kandidaten.append(Path.home() / ".config" / "Claude" / "claude_desktop_config.json")
    return kandidaten


def config_pfad() -> Path:
    kandidaten = config_kandidaten()
    return next((p for p in kandidaten if p.exists()), kandidaten[0])


def python_pfad() -> Path:
    """Programm, das Claude Desktop startet: die installierte StudienHub.exe, sonst das Python der venv."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    for kandidat in (BACKEND / ".venv" / "Scripts" / "python.exe", BACKEND / ".venv" / "bin" / "python"):
        if kandidat.exists():
            return kandidat
    return Path(sys.executable)


def server_eintrag() -> dict:
    if getattr(sys, "frozen", False):
        # dieselbe exe wie der Hub; --mcp startet nur den MCP-Server über stdio
        return {
            "command": str(python_pfad()),
            "args": ["--mcp"],
            "env": {"PYTHONIOENCODING": "utf-8", "STUDIENHUB_OFFLINE": "1", "HF_HUB_OFFLINE": "1"},
        }
    return {
        "command": str(python_pfad()),
        "args": ["-m", "app.mcp_server"],
        "env": {
            "PYTHONPATH": str(BACKEND),
            "PYTHONIOENCODING": "utf-8",
            "STUDIENHUB_OFFLINE": "1",  # kein Netz: Modelle nur aus daten/modelle
            "HF_HUB_OFFLINE": "1",
        },
    }


def _lesen(pfad: Path) -> dict:
    if not pfad.exists() or not pfad.read_text(encoding="utf-8").strip():
        return {}
    try:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
    except json.JSONDecodeError as fehler:
        raise EinrichtungsFehler(f"{pfad} ist kein gültiges JSON ({fehler}) – bitte erst von Hand reparieren.") from fehler
    if not isinstance(daten, dict):
        raise EinrichtungsFehler(f"{pfad} hat ein unerwartetes Format.")
    return daten


def status(pfad: Path | None = None) -> dict:
    pfad = pfad or config_pfad()
    try:
        daten = _lesen(pfad)
        fehler = None
    except EinrichtungsFehler as f:
        daten, fehler = {}, str(f)
    eintrag = (daten.get("mcpServers") or {}).get(SERVER_NAME)
    return {
        "config_pfad": str(pfad), "config_vorhanden": pfad.exists(), "eingetragen": eintrag is not None,
        "aktuell": eintrag == server_eintrag(), "eintrag": server_eintrag(), "python": str(python_pfad()),
        "python_vorhanden": python_pfad().exists(), "fehler": fehler,
    }


def eintragen(pfad: Path | None = None) -> dict:
    """Trägt den Server ein (oder aktualisiert ihn); vorher Sicherung der bisherigen Datei."""
    pfad = pfad or config_pfad()
    daten = _lesen(pfad)
    sicherung = None
    if pfad.exists():
        sicherung = pfad.with_name(f"claude_desktop_config.vor-studienhub-{datetime.now():%Y%m%d-%H%M%S}.json")
        shutil.copy2(pfad, sicherung)
    daten.setdefault("mcpServers", {})[SERVER_NAME] = server_eintrag()
    pfad.parent.mkdir(parents=True, exist_ok=True)
    temp = pfad.with_suffix(".tmp")
    temp.write_text(json.dumps(daten, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, pfad)
    return {**status(pfad), "sicherung": str(sicherung) if sicherung else None}


def austragen(pfad: Path | None = None) -> dict:
    pfad = pfad or config_pfad()
    daten = _lesen(pfad)
    if SERVER_NAME in (daten.get("mcpServers") or {}):
        shutil.copy2(pfad, pfad.with_name(f"claude_desktop_config.vor-studienhub-{datetime.now():%Y%m%d-%H%M%S}.json"))
        del daten["mcpServers"][SERVER_NAME]
        pfad.write_text(json.dumps(daten, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return status(pfad)
