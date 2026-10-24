"""Vor PyInstaller (build.ps1): Symbol, Build-Info und Versions-Ressource nach studien-hub/build schreiben.

build_info.json enthält den Entwicklungsordner – daran erkennt die installierte exe beim ersten Start die
bisherigen Daten (Datenübernahme im Einrichtungsassistenten).
"""

import json
import sys
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
WURZEL = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from app.desktop import symbol_bild  # noqa: E402

VERSIONS_RESSOURCE = """VSVersionInfo(
  ffi=FixedFileInfo(filevers=({a}, {b}, {c}, 0), prodvers=({a}, {b}, {c}, 0)),
  kids=[
    StringFileInfo([StringTable('040704b0', [
      StringStruct('CompanyName', 'Studien-Hub'),
      StringStruct('FileDescription', 'Studien-Hub'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('ProductName', 'Studien-Hub'),
      StringStruct('ProductVersion', '{version}'),
      StringStruct('OriginalFilename', 'StudienHub.exe')])]),
    VarFileInfo([VarStruct('Translation', [1031, 1200])])
  ]
)
"""


def main() -> None:
    ziel = WURZEL / "build"
    ziel.mkdir(exist_ok=True)
    version = (WURZEL / "VERSION").read_text(encoding="utf-8").strip()
    a, b, c = (int(t) for t in version.split("."))

    groessen = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    bild = symbol_bild(groesse=256)
    bild.save(ziel / "studienhub.ico", sizes=[(g, g) for g in groessen])
    (ziel / "build_info.json").write_text(json.dumps({
        "version": version,
        "erstellt": datetime.now().isoformat(timespec="seconds"),
        "entwicklungsordner": str(WURZEL),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (ziel / "version_info.txt").write_text(VERSIONS_RESSOURCE.format(a=a, b=b, c=c, version=version), encoding="utf-8")
    print(f"Build vorbereitet: Version {version}")


if __name__ == "__main__":
    main()
