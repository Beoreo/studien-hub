"""Autostart bei der Windows-Anmeldung über HKCU\\...\\Run (ohne Adminrechte), im Hub ein- und ausschaltbar.

Nur für die installierte StudienHub.exe; im Entwicklungsmodus gibt es keinen Autostart.
Der Installer setzt denselben Eintrag, wenn die Option „Beim Anmelden starten“ gewählt ist.
"""

from __future__ import annotations

import sys

REG_PFAD = r"Software\Microsoft\Windows\CurrentVersion\Run"
NAME = "StudienHub"


def befehl() -> str:
    # --hintergrund: nur Symbol im Infobereich, kein Browserfenster
    return f'"{sys.executable}" --hintergrund'


def verfuegbar() -> bool:
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


def aktiv() -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PFAD) as schluessel:
            winreg.QueryValueEx(schluessel, NAME)
        return True
    except FileNotFoundError:
        return False


def setzen(an: bool, wert: str | None = None) -> bool:
    """Schaltet den Autostart; gibt den neuen Zustand zurück."""
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_PFAD) as schluessel:
        if an:
            winreg.SetValueEx(schluessel, NAME, 0, winreg.REG_SZ, wert or befehl())
        else:
            try:
                winreg.DeleteValue(schluessel, NAME)
            except FileNotFoundError:
                pass
    return aktiv()
