"""Diagnose des TUWEL-Zugangs. Gibt den Token nie aus, nur Ja/Nein und Längen.

Schritt 1 (nur mit --link, verdeckte Eingabe): Aufbau des moodledownloader-Links prüfen.
Schritt 2: tool_mobile_get_public_config ohne Token (/lib/ajax/service-nologin.php).
Schritt 3: core_webservice_get_site_info mit Token, einmal normal und einmal mit App-User-Agent.

Aufruf:  python scripts/tuwel_diagnose.py [--link] [--passport 12345]
"""

import argparse
import base64
import binascii
import getpass
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import unquote

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import PROJEKT_ORDNER, TUWEL_URL, tuwel_token  # noqa: E402
from app.tuwel_token import schreibe_env_wert  # noqa: E402

APP_USER_AGENT = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) MoodleMobile 4.4.0 (44000)"
LOGIN_TYPEN = {1: "1 = Login in der App", 2: "2 = Login im Browser (SSO)", 3: "3 = eingebetteter Browser"}


def ja(wert: bool) -> str:
    return "Ja" if wert else "Nein"


def schritt1(passport: str) -> str | None:
    """Prüft den Link und liefert den Token daraus (zweiter Teil) für Schritt 3."""
    print("\n== Schritt 1: Aufbau des Links ==")
    eingabe = getpass.getpass("Text nach moodledownloader://token= (unsichtbar): ")
    roh = unquote(eingabe.strip().strip("'\""))
    if "token=" in roh:
        roh = roh.split("token=", 1)[1]
    roh = "".join(roh.split()).rstrip("/")
    try:
        text = base64.b64decode(roh + "=" * (-len(roh) % 4)).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        print("Base64 dekodierbar: Nein")
        return None
    teile = text.split(":::")
    print(f"Base64 dekodierbar: Ja")
    print(f"Drei Teile: {ja(len(teile) == 3)} (Anzahl {len(teile)}, Längen {[len(t) for t in teile]})")
    erwartet = hashlib.md5((TUWEL_URL + passport).encode()).hexdigest()
    print(f"Erster Teil == md5('{TUWEL_URL}' + '{passport}'): {ja(teile[0] == erwartet)}")
    if teile[0] != erwartet:
        # häufige Varianten der Website-Adresse
        for variante in (TUWEL_URL + "/", TUWEL_URL.replace("https://", "http://")):
            if teile[0] == hashlib.md5((variante + passport).encode()).hexdigest():
                print(f"  passt stattdessen zu md5('{variante}' + '{passport}'): Ja")
    gespeichert = tuwel_token()
    print(f"Zweiter Teil == gespeicherter TUWEL_TOKEN: {ja(len(teile) > 1 and teile[1] == gespeichert)}")
    if len(teile) > 2:
        print(f"Dritter Teil (privater Token) vorhanden: {ja(bool(teile[2]))}, Länge {len(teile[2])}")
    return teile[1] if len(teile) > 1 else None


def gespeicherter_token() -> None:
    token = tuwel_token()
    print("\n== Gespeicherter Token ==")
    print(f"TUWEL_TOKEN gesetzt: {ja(bool(token))}" + (f", Länge {len(token)}" if token else ""))
    if token:
        print(f"Nur 0-9/a-f: {ja(all(c in '0123456789abcdef' for c in token))}")


def schritt2(http: httpx.Client) -> None:
    print("\n== Schritt 2: tool_mobile_get_public_config (ohne Token) ==")
    anfrage = [{"index": 0, "methodname": "tool_mobile_get_public_config", "args": {}}]
    antwort = http.post(f"{TUWEL_URL}/lib/ajax/service-nologin.php", json=anfrage)
    print(f"HTTP {antwort.status_code}")
    try:
        ergebnis = antwort.json()[0]
    except (ValueError, KeyError, IndexError, TypeError):
        print(f"Keine erwartete JSON-Antwort: {antwort.text[:200]}")
        return
    if ergebnis.get("error"):
        print(f"Fehler: {json.dumps(ergebnis.get('exception', ergebnis), ensure_ascii=False)[:300]}")
        return
    d = ergebnis.get("data", {})
    print(f"Webservices aktiviert (enablewebservices): {ja(bool(d.get('enablewebservices')))}")
    print(f"Mobile App aktiviert (enablemobilewebservice): {ja(bool(d.get('enablemobilewebservice')))}")
    typ = d.get("typeoflogin")
    print(f"Login-Typ (typeoflogin): {LOGIN_TYPEN.get(typ, typ)}")
    for feld in ("launchurl", "httpswwwroot", "wwwroot", "release", "version", "maintenanceenabled",
                 "tool_mobile_minimumversion", "tool_mobile_forcelogout", "identityproviders"):
        if feld in d:
            wert = d[feld]
            if feld == "identityproviders":
                wert = [p.get("name") for p in wert or []]
            print(f"  {feld}: {wert}")


def teste_token(http: httpx.Client, bezeichnung: str, token: str) -> bool:
    """Ruft core_webservice_get_site_info ohne und mit App-User-Agent auf; True, wenn einer klappt."""
    ok = False
    for name, kopf in (("ohne App-User-Agent", {}), ("mit App-User-Agent", {"User-Agent": APP_USER_AGENT})):
        antwort = http.post(
            f"{TUWEL_URL}/webservice/rest/server.php",
            data={"wstoken": token, "wsfunction": "core_webservice_get_site_info", "moodlewsrestformat": "json"},
            headers=kopf,
        )
        try:
            d = antwort.json()
        except ValueError:
            print(f"{bezeichnung}, {name}: HTTP {antwort.status_code}, keine JSON-Antwort")
            continue
        if isinstance(d, dict) and "errorcode" in d:
            meldung = str(d.get("message", "")).replace(token, "***")
            debug = str(d.get("debuginfo", "")).replace(token, "***")
            print(f"{bezeichnung}, {name}: FEHLER {d['errorcode']} – {meldung}" + (f" | debuginfo: {debug}" if debug else ""))
        else:
            ok = True
            funktionen = {f.get("name") for f in d.get("functions", [])}
            print(f"{bezeichnung}, {name}: OK – angemeldet als {d.get('fullname')}, {len(funktionen)} Funktionen freigegeben")
            for f in ("core_enrol_get_users_courses", "core_course_get_contents"):
                print(f"   {f}: {ja(f in funktionen) if funktionen else 'Liste nicht geliefert'}")
    return ok


def schritt3(http: httpx.Client, link_token: str | None) -> None:
    print("\n== Schritt 3: core_webservice_get_site_info mit Token ==")
    gespeichert = tuwel_token()
    if link_token and link_token != gespeichert:
        # Den frischen Token aus dem Link sofort testen – ältere Tokens verwirft TUWEL offenbar
        if teste_token(http, "Token aus dem Link", link_token):
            antwort = input("Diesen Token als TUWEL_TOKEN in der .env speichern? [j/N] ").strip().lower()
            if antwort in ("j", "ja", "y"):
                schreibe_env_wert(PROJEKT_ORDNER / ".env", "TUWEL_TOKEN", link_token)
                print("Gespeichert.")
        if gespeichert:
            teste_token(http, "Gespeicherter Token", gespeichert)
    elif gespeichert:
        teste_token(http, "Gespeicherter Token" + (" (= Link)" if link_token else ""), gespeichert)
    else:
        print("Übersprungen: kein Token vorhanden.")


def main() -> int:
    sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--link", action="store_true", help="Schritt 1 mit verdeckter Eingabe des Links")
    parser.add_argument("--passport", default="12345")
    argumente = parser.parse_args()

    link_token = schritt1(argumente.passport) if argumente.link else None
    gespeicherter_token()
    with httpx.Client(timeout=30, follow_redirects=True) as http:
        schritt2(http)
        schritt3(http, link_token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
