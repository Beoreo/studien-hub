"""TUWEL-Token aus dem Anmelde-Link gewinnen und in der .env ablegen.

Nach der Anmeldung über die Moodle-App-Schnittstelle liefert TUWEL einen Link der Form
`moodledownloader://token=<Base64>`. Dekodiert ergibt das `<Prüfwert>:::<Token>[:::<privater Token>]`;
gebraucht wird der zweite Teil. Funktionen hier geben den Token nie aus.
"""

from __future__ import annotations

import base64
import binascii
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import unquote

PRAEFIX = re.compile(r"^.*?token=", re.IGNORECASE | re.DOTALL)
TOKEN_FORM = re.compile(r"^[0-9A-Za-z]{16,128}$")


class TokenFehler(ValueError):
    """Der eingegebene Text enthält keinen brauchbaren Token (Meldung enthält nie den Token)."""


def token_aus_link(text: str) -> str:
    """Akzeptiert den ganzen Link oder nur den Teil nach `token=` und liefert den Webservice-Token."""
    roh = unquote(text.strip().strip("'\""))
    roh = PRAEFIX.sub("", roh) if "token=" in roh.lower() else roh
    roh = re.sub(r"\s+", "", roh).rstrip("/")
    if not roh:
        raise TokenFehler("Leere Eingabe.")

    dekodiert = None
    auffuellung = "=" * (-len(roh) % 4)
    for dekodierer in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            dekodiert = dekodierer(roh + auffuellung).decode("utf-8")
            break
        except (binascii.Error, ValueError, UnicodeDecodeError):
            continue
    if dekodiert is None:
        raise TokenFehler("Der Text ist kein gültiges Base64 – bitte nur den Teil nach moodledownloader://token= einfügen.")

    teile = dekodiert.split(":::")
    if len(teile) < 2:
        raise TokenFehler("Dekodierter Text enthält kein ':::' – falscher Link?")
    token = teile[1].strip()
    if not TOKEN_FORM.fullmatch(token):
        raise TokenFehler(f"Der zweite Teil sieht nicht wie ein Token aus ({len(token)} Zeichen).")
    return token


def schreibe_env_wert(pfad: Path, schluessel: str, wert: str) -> None:
    """Setzt `SCHLUESSEL=wert` in der .env; andere Zeilen bleiben unverändert. Schreibt atomar."""
    zeilen = pfad.read_text(encoding="utf-8").splitlines() if pfad.exists() else []
    neu = f"{schluessel}={wert}"
    gefunden = False
    for i, zeile in enumerate(zeilen):
        if re.match(rf"^\s*{re.escape(schluessel)}\s*=", zeile):
            zeilen[i] = neu
            gefunden = True
    if not gefunden:
        zeilen.append(neu)

    pfad.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=pfad.parent, prefix=".env.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as datei:
            datei.write("\n".join(zeilen) + "\n")
        os.replace(temp, pfad)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise
