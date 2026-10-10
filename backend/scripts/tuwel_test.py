"""Stufe 2, Schritt 1: Verbindungstest für TUWEL.

Ruft mit dem Token aus der .env core_webservice_get_site_info und core_enrol_get_users_courses
auf und listet die Kurse. Der Token wird nie ausgegeben.

Aufruf (im Ordner backend):  .\\.venv\\Scripts\\python scripts\\tuwel_test.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import TUWEL_URL, tuwel_token  # noqa: E402
from app.tuwel_client import TuwelClient, TuwelFehler  # noqa: E402

BENOETIGT = ["core_webservice_get_site_info", "core_enrol_get_users_courses", "core_course_get_contents"]


def main() -> int:
    # Windows-Konsolen (cp1252) können nicht jedes Zeichen aus Kursnamen darstellen
    sys.stdout.reconfigure(errors="replace")
    token = tuwel_token()
    if not token:
        print("Kein Token: bitte TUWEL_TOKEN in studien-hub/.env eintragen (Vorlage: .env.example).")
        return 2

    client = TuwelClient(TUWEL_URL, token)
    try:
        info = client.seiteninfo()
        print(f"Verbunden mit {info.get('sitename')} ({TUWEL_URL})")
        print(f"Angemeldet als {info.get('fullname')} ({info.get('username')}), Benutzer-ID {info.get('userid')}")

        # Ist die Funktionsliste leer, gibt Moodle sie nicht preis – dann einfach ausprobieren
        erlaubt = {f.get("name") for f in info.get("functions", [])}
        if erlaubt:
            for funktion in BENOETIGT:
                print(f"  {'ok  ' if funktion in erlaubt else 'FEHLT'} {funktion}")

        kurse = client.kurse(info["userid"])
        print(f"\n{len(kurse)} Kurse:")
        for kurs in sorted(kurse, key=lambda k: k.get("fullname", "")):
            print(f"  [{kurs.get('id'):>6}] {kurs.get('shortname', '')}  –  {kurs.get('fullname', '')}"
                  + (f"  (idnumber: {kurs['idnumber']})" if kurs.get("idnumber") else ""))

        if kurse:
            inhalte = client.kursinhalte(kurse[0]["id"])
            dateien = sum(len(m.get("contents", []) or []) for a in inhalte for m in a.get("modules", []))
            print(f"\nProbe core_course_get_contents für Kurs {kurse[0]['id']}: "
                  f"{len(inhalte)} Abschnitte, {dateien} Dateieinträge – Zugriff ok.")
        return 0
    except TuwelFehler as fehler:
        print(f"Fehler: {fehler}")
        return 1
    finally:
        client.schliessen()


if __name__ == "__main__":
    sys.exit(main())
