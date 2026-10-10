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
import time
from pathlib import Path
from urllib.parse import unquote

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import PROJEKT_ORDNER, TUWEL_URL, tuwel_token  # noqa: E402
from app.tuwel_token import schreibe_env_wert  # noqa: E402

APP_USER_AGENT = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) MoodleMobile 4.4.0 (44000)"
NUR_APP_UA = False  # per --nur-app-ua: jeder Aufruf mit Token nur mit App-User-Agent
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
    varianten = [("mit App-User-Agent", {"User-Agent": APP_USER_AGENT})]
    if not NUR_APP_UA:
        varianten.insert(0, ("ohne App-User-Agent", {}))
    for name, kopf in varianten:
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
                return  # der alte Wert ist überschrieben, ihn erneut zu testen wäre irreführend
        if gespeichert:
            teste_token(http, "Bisher gespeicherter (alter) Token", gespeichert)
    elif gespeichert:
        teste_token(http, "Gespeicherter Token" + (" (= Link)" if link_token else ""), gespeichert)
    else:
        print("Übersprungen: kein Token vorhanden.")


def kurzstatus(http: httpx.Client, token: str) -> str:
    """Ergebnis eines einzelnen site_info-Aufrufs als kurzer Text (ohne Token)."""
    try:
        d = http.post(
            f"{TUWEL_URL}/webservice/rest/server.php",
            data={"wstoken": token, "wsfunction": "core_webservice_get_site_info", "moodlewsrestformat": "json"},
            headers={"User-Agent": APP_USER_AGENT} if NUR_APP_UA else {},
        ).json()
    except (httpx.HTTPError, ValueError) as fehler:
        return f"keine Antwort ({type(fehler).__name__})"
    if isinstance(d, dict) and "errorcode" in d:
        return f"{d['errorcode']} – {str(d.get('message', '')).replace(token, '***')}"
    return "OK"


def beobachten(http: httpx.Client, token: str, takt: int, minuten: int) -> None:
    """Misst, wie lange der Token gilt: fragt im Takt nach und meldet jede Zustandsänderung."""
    ua = "nur App-User-Agent" if NUR_APP_UA else "Standard-User-Agent"
    print(f"\n== Lebensdauer: alle {takt} s, höchstens {minuten} min, {ua} (Strg+C beendet) ==")
    beginn = time.monotonic()
    letzter = None
    try:
        while time.monotonic() - beginn < minuten * 60:
            status = kurzstatus(http, token)
            vergangen = int(time.monotonic() - beginn)
            if status != letzter:
                print(f"{time.strftime('%H:%M:%S')}  nach {vergangen // 60:>2} min {vergangen % 60:02d} s: {status}", flush=True)
                letzter = status
            if status.startswith("invalidtoken"):
                print("Token ist gelöscht – Beobachtung beendet.")
                return
            time.sleep(takt)
        print(f"Nach {minuten} min noch gültig: {letzter}")
    except KeyboardInterrupt:
        print(f"\nAbgebrochen nach {int(time.monotonic() - beginn)} s, letzter Zustand: {letzter}")


def main() -> int:
    sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--link", action="store_true", help="Schritt 1 mit verdeckter Eingabe des Links")
    parser.add_argument("--passport", default="12345")
    parser.add_argument("--beobachten", action="store_true", help="Lebensdauer des Tokens messen")
    parser.add_argument("--takt", type=int, default=20, help="Sekunden zwischen zwei Abfragen")
    parser.add_argument("--minuten", type=int, default=45, help="höchstens so lange beobachten")
    parser.add_argument("--nur-app-ua", action="store_true", help="alle Aufrufe mit Token nur mit App-User-Agent")
    argumente = parser.parse_args()
    global NUR_APP_UA
    NUR_APP_UA = argumente.nur_app_ua

    link_token = schritt1(argumente.passport) if argumente.link else None
    gespeicherter_token()
    with httpx.Client(timeout=30, follow_redirects=True) as http:
        schritt2(http)
        schritt3(http, link_token)
        if argumente.beobachten:
            ziel = link_token or tuwel_token()
            if ziel:
                beobachten(http, ziel, argumente.takt, argumente.minuten)
    return 0


if __name__ == "__main__":
    sys.exit(main())
