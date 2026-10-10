"""Fragt den Text nach `moodledownloader://token=` ab, gewinnt daraus den TUWEL-Token,
schreibt ihn als TUWEL_TOKEN in studien-hub/.env und prüft die Verbindung.

Die Eingabe ist verdeckt; der Token wird nie angezeigt oder protokolliert.

Aufruf:  & C:\\Users\\Benedikt\\Studycrawler\\studien-hub\\backend\\.venv\\Scripts\\python.exe
           C:\\Users\\Benedikt\\Studycrawler\\studien-hub\\backend\\scripts\\tuwel_token_setzen.py
"""

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import PROJEKT_ORDNER, TUWEL_URL, tuwel_token  # noqa: E402
from app.tuwel_client import TuwelClient, TuwelFehler  # noqa: E402
from app.tuwel_token import TokenFehler, schreibe_env_wert, token_aus_link  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(errors="replace")
    print("Füge den Text nach  moodledownloader://token=  ein (oder den ganzen Link).")
    print("Die Eingabe bleibt unsichtbar. Danach Enter drücken.")
    try:
        eingabe = getpass.getpass("Token-Link: ")
    except (KeyboardInterrupt, EOFError):
        print("\nAbgebrochen, nichts geändert.")
        return 1

    try:
        token = token_aus_link(eingabe)
    except TokenFehler as fehler:
        print(f"Nicht übernommen: {fehler}")
        return 1
    finally:
        eingabe = None  # noqa: F841

    env = PROJEKT_ORDNER / ".env"
    schreibe_env_wert(env, "TUWEL_TOKEN", token)
    print(f"Token gespeichert in {env} ({len(token)} Zeichen).")

    # Verbindungstest mit dem frisch gespeicherten Wert
    client = TuwelClient(TUWEL_URL, tuwel_token() or "")
    try:
        info = client.seiteninfo()
        print(f"Verbindung ok: angemeldet als {info.get('fullname')} bei {info.get('sitename')}.")
        return 0
    except TuwelFehler as fehler:
        print(f"Token gespeichert, aber der Test schlug fehl: {fehler}")
        return 1
    finally:
        client.schliessen()


if __name__ == "__main__":
    sys.exit(main())
