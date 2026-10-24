"""StudienHub.exe: Hub im Hintergrund mit Symbol im Infobereich – und Hilfsaufrufe für Installer und Claude Desktop.

Aufrufe:
    StudienHub.exe                 Hub starten und im Browser öffnen (läuft er schon: nur den Browser öffnen)
    StudienHub.exe --hintergrund   wie oben, aber ohne Browserfenster (Autostart bei der Anmeldung)
    StudienHub.exe --mcp           nur den MCP-Server für Claude Desktop (stdio)
    StudienHub.exe --eintragen     MCP-Server in Claude Desktop eintragen (Installer, mit Sicherung)
    StudienHub.exe --austragen     Eintrag in Claude Desktop und Autostart entfernen (Deinstallation)
    StudienHub.exe --daten-loeschen  gespeicherte Zugangsdaten löschen (Deinstallation mit „Daten löschen“)
    StudienHub.exe --import-pruefen numpy faster_whisper …   Diagnose: Module im Paket importieren, Fehler ausgeben
Im Entwicklungsmodus geht dasselbe mit `python -m app.desktop`.
"""

from __future__ import annotations

import io
import logging
import sys
import threading
import time
import webbrowser

MUTEX_NAME = "Local\\StudienHub-Hub"
log = logging.getLogger("studienhub.desktop")


# --- Hilfen ------------------------------------------------------------------------------------------

def _meldung(text: str, titel: str = "Studien-Hub") -> None:
    """Fehlerfenster – die exe hat keine Konsole."""
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, titel, 0x10)
    else:
        print(text, file=sys.stderr)


def _stdio_reparieren() -> None:
    """Eine exe ohne Konsole hat unter Umständen kein sys.stdin/stdout, obwohl Claude Desktop Pipes übergibt.
    Dann die Ströme aus den Windows-Handles neu aufbauen (stdout gehört dem MCP-Protokoll)."""
    if sys.platform != "win32" or (sys.stdin and sys.stdout):
        return
    import ctypes
    import msvcrt

    for nummer, name, modus in ((-10, "stdin", "rb"), (-11, "stdout", "wb"), (-12, "stderr", "wb")):
        if getattr(sys, name) is not None:
            continue
        handle = ctypes.windll.kernel32.GetStdHandle(nummer)
        if handle in (0, -1, None):
            continue
        roh = open(msvcrt.open_osfhandle(handle, 0), modus, buffering=0)  # noqa: SIM115 – lebt so lange wie der Prozess
        puffer = io.BufferedReader(roh) if "r" in modus else io.BufferedWriter(roh)
        setattr(sys, name, io.TextIOWrapper(puffer, encoding="utf-8", write_through=name != "stdin"))


def _stille_ausgabe() -> None:
    """Hub ohne Konsole: sys.stdout/stderr sind None; Bibliotheken mit Fortschrittsbalken oder print (fastembed,
    tqdm, huggingface_hub) scheitern daran. Dann ins Leere schreiben – Wichtiges steht ohnehin im Log."""
    import os

    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))  # noqa: SIM115 – lebt so lange wie der Prozess


def _einziges_exemplar() -> bool:
    """True, wenn kein anderer Hub läuft. Der Mutex lebt bis zum Prozessende (Handle bleibt offen)."""
    if sys.platform != "win32":
        return True
    import ctypes

    kernel32 = ctypes.windll.kernel32
    _einziges_exemplar.handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    return kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def adresse(pfad: str = "") -> str:
    from .config import HOST, PORT

    return f"http://{HOST}:{PORT}/{pfad}"


def symbol_bild(fehler: bool = False, groesse: int = 64):
    """Symbol des Hubs: Primärfarbe mit „S“; bei Fehlern rot mit „!“ (Farben aus design.css)."""
    from PIL import Image, ImageDraw, ImageFont

    farbe = (223, 41, 53) if fehler else (0, 101, 152)
    bild = Image.new("RGBA", (groesse, groesse), (0, 0, 0, 0))
    zeichnen = ImageDraw.Draw(bild)
    zeichnen.rounded_rectangle((0, 0, groesse - 1, groesse - 1), radius=groesse // 5, fill=farbe)
    try:
        schrift = ImageFont.truetype("segoeuib.ttf", int(groesse * 0.62))
    except OSError:
        schrift = ImageFont.load_default()
    zeichnen.text((groesse / 2, groesse / 2), "!" if fehler else "S", fill="white", font=schrift, anchor="mm")
    return bild


# --- Server und Infobereich -----------------------------------------------------------------------------

def _server_starten():
    import uvicorn

    from .config import HOST, PORT
    from .main import app

    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=PORT, log_config=None, access_log=False))
    faden = threading.Thread(target=server.run, name="uvicorn", daemon=True)
    faden.start()
    for _ in range(600):  # bis zu 60 s: Datenbank, Planung, Scheduler
        if server.started:
            return server
        if not faden.is_alive():
            return None
        time.sleep(0.1)
    return server if server.started else None


def _infobereich(server, browser_oeffnen: bool) -> None:
    import pystray

    from .db import SessionLocal
    from .routers.system import fehlerzustand, jetzt_synchronisieren

    zustand = {"fehler": []}

    def oeffnen(*_):
        webbrowser.open(adresse())

    def synchronisieren(*_):
        jetzt_synchronisieren()
        symbol.notify("TISS und MB Cloud laufen; TUWEL holt die Browser-Erweiterung in den nächsten Minuten.", "Studien-Hub")

    def status(*_):
        webbrowser.open(adresse("#status"))

    def beenden(*_):
        server.should_exit = True
        symbol.stop()

    symbol = pystray.Icon(
        "StudienHub",
        symbol_bild(),
        "Studien-Hub",
        menu=pystray.Menu(
            pystray.MenuItem("Hub öffnen", oeffnen, default=True),
            pystray.MenuItem("Jetzt synchronisieren", synchronisieren),
            pystray.MenuItem("Status", status),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Beenden", beenden),
        ),
    )

    def ueberwachen():
        while not server.should_exit:
            try:
                with SessionLocal() as session:
                    fehler = fehlerzustand(session)
            except Exception:
                log.exception("Status für das Symbol im Infobereich nicht lesbar")
                fehler = ["Status nicht lesbar – siehe Log"]
            if fehler != zustand["fehler"]:
                neu = [f for f in fehler if f not in zustand["fehler"]]
                zustand["fehler"] = fehler
                symbol.icon = symbol_bild(fehler=bool(fehler))
                # Tooltip ist unter Windows auf 127 Zeichen begrenzt
                symbol.title = ("Studien-Hub – " + fehler[0])[:120] if fehler else "Studien-Hub"
                if neu:
                    symbol.notify(neu[0][:200], "Studien-Hub: Fehler")
            time.sleep(60)

    def bereit(icon):
        icon.visible = True
        threading.Thread(target=ueberwachen, name="infobereich", daemon=True).start()
        if browser_oeffnen:
            oeffnen()

    symbol.run(setup=bereit)  # blockiert bis „Beenden“


def hub_starten(hintergrund: bool) -> int:
    if not _einziges_exemplar():
        if not hintergrund:
            webbrowser.open(adresse())  # zweiter Start: nur den Browser öffnen
        return 0
    from . import protokoll

    _stille_ausgabe()
    protokoll.einrichten()
    server = _server_starten()
    if server is None:
        from .config import PORT

        _meldung(f"Der Studien-Hub konnte nicht starten. Ist Port {PORT} belegt (z. B. vom Entwicklungsmodus)?\n"
                 "Details im Log: %LOCALAPPDATA%\\StudienHub\\logs")
        return 1
    try:
        _infobereich(server, browser_oeffnen=not hintergrund)
    finally:
        server.should_exit = True
    return 0


# --- Hilfsaufrufe für Installer und Claude Desktop ---------------------------------------------------

def mcp_starten() -> int:
    _stdio_reparieren()
    from .mcp_server import main

    main()
    return 0


def eintragen() -> int:
    from . import ki_einrichtung

    try:
        ki_einrichtung.eintragen()
    except ki_einrichtung.EinrichtungsFehler as fehler:
        _meldung(f"Eintrag in Claude Desktop nicht möglich:\n{fehler}")
        return 1
    return 0


def austragen() -> int:
    from . import autostart, ki_einrichtung

    try:
        ki_einrichtung.austragen()
    except ki_einrichtung.EinrichtungsFehler:
        pass  # kaputte Konfiguration nicht anfassen
    if sys.platform == "win32":
        autostart.setzen(False)
    return 0


def daten_loeschen() -> int:
    from . import geheimnisse

    geheimnisse.alle_loeschen()
    return 0


def import_pruefen(module: list[str]) -> int:
    """Diagnose fürs Paketieren: importiert Module in der exe und gibt Fehler mit vollem Traceback aus."""
    import importlib
    import traceback

    _stdio_reparieren()
    fehler = 0
    for name in module:
        try:
            importlib.import_module(name)
            print(f"ok      {name}", flush=True)
        except BaseException:  # noqa: BLE001 – genau das soll sichtbar werden
            fehler += 1
            print(f"FEHLER  {name}\n{traceback.format_exc()}", flush=True)
    return 1 if fehler else 0


def main(argumente: list[str] | None = None) -> int:
    argumente = sys.argv[1:] if argumente is None else argumente
    if "--mcp" in argumente:
        return mcp_starten()
    if "--import-pruefen" in argumente:
        return import_pruefen(argumente[argumente.index("--import-pruefen") + 1:])
    if "--eintragen" in argumente:
        return eintragen()
    if "--austragen" in argumente:
        return austragen()
    if "--daten-loeschen" in argumente:
        return daten_loeschen()
    return hub_starten(hintergrund="--hintergrund" in argumente)


if __name__ == "__main__":
    sys.exit(main())
