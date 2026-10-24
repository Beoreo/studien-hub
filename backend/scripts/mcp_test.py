"""Testet den MCP-Server so, wie Claude Desktop ihn nutzt: Start über stdio, dann jedes Werkzeug einmal.

    cd backend
    .\\.venv\\Scripts\\python scripts\\mcp_test.py            # mit einer Kopie der echten Datenbank
    .\\.venv\\Scripts\\python scripts\\mcp_test.py --frage "Haftreibung"

Schreibende Werkzeuge (Lernereignis, Wissensstand, Notiz, Lernblock-Vorschlag) laufen gegen eine temporäre
Kopie von daten/studienhub.db – die echte Datenbank bleibt unverändert. Ausgabe: je Werkzeug OK/FEHLER und
ein kurzer Auszug der Antwort.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from mcp.client.session import ClientSession  # noqa: E402
from mcp.client.stdio import StdioServerParameters, stdio_client  # noqa: E402

from app.config import DATEN_ORDNER  # noqa: E402
from app.ki_einrichtung import server_eintrag  # noqa: E402


def inhalt(ergebnis) -> object:
    if getattr(ergebnis, "is_error", False):
        raise RuntimeError(" ".join(getattr(c, "text", "") for c in ergebnis.content))
    daten = ergebnis.structured_content
    if daten is None:
        return json.loads(ergebnis.content[0].text) if ergebnis.content else None
    return daten.get("result", daten) if set(daten) == {"result"} else daten


def kurz(wert, laenge=160) -> str:
    text = json.dumps(wert, ensure_ascii=False, default=str)
    return text if len(text) <= laenge else text[:laenge] + " …"


async def lauf(frage: str, datenbank: Path) -> int:
    eintrag = server_eintrag()
    env = {**eintrag["env"], "STUDIENHUB_DB_URL": f"sqlite:///{datenbank.as_posix()}"}
    parameter = StdioServerParameters(command=eintrag["command"], args=eintrag["args"], env=env, cwd=str(BACKEND))
    fehler = 0
    async with stdio_client(parameter) as (lesen, schreiben), ClientSession(lesen, schreiben) as sitzung:
        await sitzung.initialize()
        werkzeuge = {t.name for t in (await sitzung.list_tools()).tools}
        print(f"{len(werkzeuge)} Werkzeuge: {', '.join(sorted(werkzeuge))}\n")

        async def rufe(name, **argumente):
            nonlocal fehler
            try:
                ergebnis = inhalt(await sitzung.call_tool(name, argumente))
                print(f"OK      {name}: {kurz(ergebnis)}")
                return ergebnis
            except Exception as f:  # Werkzeugfehler zeigen, weitermachen
                fehler += 1
                print(f"FEHLER  {name}: {f}")
                return None

        lvas = await rufe("liste_lvas") or []
        lva = lvas[0]["kurzname"] or lvas[0]["titel"] if lvas else None
        treffer = await rufe("suche_unterlagen", frage=frage, lva=lva) or []
        if treffer:
            await rufe("lies_abschnitt", abschnitt_id=treffer[0]["abschnitt_id"])
        else:
            print("–       lies_abschnitt: keine Treffer (Verarbeitung auf „KI verbinden“ eingeschaltet?)")
        await rufe("termine")
        await rufe("wochenplan")
        await rufe("pruefungen")
        stand = await rufe("wissensstand", lva=lva) or []
        await rufe("faellige_wiederholungen")
        if lva:
            await rufe("altpruefungen", lva=lva)
        themen = [t for e in stand for t in e["themen"]]
        if themen:
            thema = themen[0]
            await rufe("lernereignis_eintragen", thema=str(thema["id"]), art="quiz", ergebnis=0.8, notiz="Testskript")
            await rufe("wissensstand_setzen", thema=str(thema["id"]), stufe=thema["stufe"])
        else:
            print("–       lernereignis_eintragen/wissensstand_setzen: noch keine Themen (im Hub „Themen ableiten“)")
        await rufe("notiz_speichern", text="Testnotiz aus scripts/mcp_test.py", lva=lva)
        await rufe("rueckblick")
        await rufe("neue_unterlagen", tage=14)
        if treffer:
            await rufe("lies_dokument", dokument_id=treffer[0]["dokument_id"], max_zeichen=3000)
        vergangene = await rufe("termine", von=(datetime.now() - timedelta(days=7)).date().isoformat(),
                                bis=(datetime.now() - timedelta(days=1)).date().isoformat()) or []
        if vergangene:
            await rufe("aufzeichnung_zu_termin", termin=str(vergangene[0]["termin_id"]))
        alt = (await rufe("altpruefungen", lva=lva) or []) if lva else []
        if alt:
            await rufe("altpruefung_bearbeitet", dokument_id=alt[0]["dokument_id"], minuten=60, punkte=10, punkte_max=20)
        else:
            print("–       altpruefung_bearbeitet: keine Altprüfungen in der MB Cloud für diese LVA")
        await rufe("wochenplan_vorschlagen", grund="Testskript")

        # Prompt-Vorlagen: auflisten und mit Beispielwerten abrufen
        vorlagen = (await sitzung.list_prompts()).prompts
        print(f"\n{len(vorlagen)} Vorlagen: {', '.join(p.name for p in vorlagen)}")
        beispiele = {"thema_lernen": {"lva": lva or "Mechanik", "thema": "Reibung"}, "wochenstart": {},
                     "wiederholung": {}, "pruefung_simulieren": {"lva": lva or "Mechanik", "minuten": "90"},
                     "vorlesung_nachholen": {"termin": "Mechanik 14.10."}, "plan_anpassen": {"grund": "krank am Mittwoch"}}
        for p in vorlagen:
            try:
                ergebnis = await sitzung.get_prompt(p.name, beispiele.get(p.name, {}))
                print(f"OK      Vorlage {p.name}: {kurz(ergebnis.messages[0].content.text, 90)}")
            except Exception as f:
                fehler += 1
                print(f"FEHLER  Vorlage {p.name}: {f}")
        if lva:
            morgen = datetime.now().replace(hour=7, minute=0, second=0, microsecond=0) + timedelta(days=1)
            await rufe("lernblock_vorschlagen", lva=lva, start=morgen.isoformat(), ende=(morgen + timedelta(minutes=45)).isoformat(),
                       thema="Test")
    print(f"\n{'Alles in Ordnung.' if not fehler else f'{fehler} Werkzeug(e) mit Fehler.'}")
    return 1 if fehler else 0


def main() -> int:
    argumente = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    argumente.add_argument("--frage", default="Gleichgewicht der Kräfte")
    argumente.add_argument("--datenbank", type=Path, default=DATEN_ORDNER / "studienhub.db")
    a = argumente.parse_args()
    with tempfile.TemporaryDirectory() as ordner:
        kopie = Path(ordner) / "studienhub.db"
        if a.datenbank.exists():
            shutil.copy2(a.datenbank, kopie)
        return asyncio.run(lauf(a.frage, kopie))


if __name__ == "__main__":
    sys.exit(main())
