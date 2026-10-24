# PyInstaller: StudienHub.exe im onedir-Modus (aufgerufen von build.ps1, nicht direkt).
# Erwartet im Ordner ../build: studienhub.ico und build_info.json (von build.ps1 erzeugt) und ../frontend/dist.
# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

BACKEND = Path(SPECPATH)
WURZEL = BACKEND.parent
BUILD = WURZEL / "build"

datas = [
    (str(WURZEL / "frontend" / "dist"), "frontend"),
    (str(WURZEL / "VERSION"), "."),
    (str(BUILD / "build_info.json"), "."),
]
binaries = []
hiddenimports = collect_submodules("app") + collect_submodules("uvicorn") + [
    # numpy 2.5 lädt Teile dynamisch (z. B. numpy._core._exceptions), die PyInstaller 6.11 nicht findet; fehlt einer,
    # scheitert der erste Import still (sqlite_vec fängt ihn ab) und jeder spätere mit „cannot load module more than once“
    *collect_submodules("numpy", filter=lambda n: ".tests" not in n and not n.endswith(".conftest")),
    "keyring.backends.Windows",
    "pystray._win32",
]

# Pakete mit DLLs, Modell-/Datendateien oder dynamischen Importen vollständig einsammeln
def _ohne_cli(name: str) -> bool:
    return not name.startswith("mcp.cli")  # Kommandozeile des MCP-SDK braucht typer – gebraucht wird sie nicht


for paket in ("sqlite_vec", "fastembed", "faster_whisper", "ctranslate2", "onnxruntime", "tokenizers", "holidays",
              "apscheduler", "mcp", "fpdf", "icalendar", "tzdata", "pymupdf"):
    # nicht „av“ (PyAV): dafür hat PyInstaller einen eigenen Hook; collect_all lädt dessen Module sonst doppelt
    # („cannot load module more than once per process“ beim Import von faster_whisper)
    d, b, h = collect_all(paket, filter_submodules=_ohne_cli, on_error="warn once")
    datas += d
    binaries += b
    hiddenimports += h
# APScheduler 3 findet seine Auslöser (cron, interval) über die Paket-Metadaten
for paket in ("apscheduler", "fastembed", "faster_whisper", "keyring", "mcp", "huggingface_hub", "tokenizers"):
    datas += copy_metadata(paket)

a = Analysis(
    [str(BACKEND / "studienhub_start.py")],
    pathex=[str(BACKEND)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["pytest", "_pytest", "tkinter", "matplotlib", "IPython", "torch", "tensorflow", "pip"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="StudienHub",
    icon=str(BUILD / "studienhub.ico"),
    console=False,  # kein Konsolenfenster; --mcp stellt stdin/stdout selbst her (app/desktop.py)
    upx=False,
    version=str(BUILD / "version_info.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="StudienHub", upx=False)
