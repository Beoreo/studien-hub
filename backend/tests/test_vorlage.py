"""Schutz vor versehentlich eingecheckten Geheimnissen in der Vorlage .env.example."""

import re
from pathlib import Path

VORLAGE = Path(__file__).resolve().parents[2] / ".env.example"
GEHEIM = re.compile(r"TOKEN|SECRET|PASSWORT|PASSWORD|KEY", re.IGNORECASE)


def test_vorlage_enthaelt_keine_geheimnisse():
    for zeile in VORLAGE.read_text(encoding="utf-8").splitlines():
        if zeile.lstrip().startswith("#") or "=" not in zeile:
            continue
        name, wert = zeile.split("=", 1)
        if GEHEIM.search(name):
            assert wert.strip() == "", f"{name.strip()} in .env.example muss leer bleiben"
