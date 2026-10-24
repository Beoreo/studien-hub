"""Schlanker Client für die Moodle-Webservice-REST-Schnittstelle von TUWEL.

Moodle meldet Fehler meist mit HTTP 200 und einem JSON-Objekt mit `exception`/`errorcode`;
diese werden hier in `TuwelFehler` mit verständlicher Meldung übersetzt. Der Token wird nie
in Fehlermeldungen oder Logs ausgegeben.
"""

from __future__ import annotations

from typing import Any

import httpx

REST_PFAD = "/webservice/rest/server.php"

# Häufige Moodle-Fehlercodes mit Hinweis, was zu tun ist
HINWEISE = {
    "invalidtoken": "Token ungültig oder abgelaufen – in TUWEL unter Profil > Einstellungen > Sicherheitsschlüssel neu erzeugen.",
    "accessexception": "TUWEL erlaubt diesem Token den Zugriff auf diese Funktion nicht.",
    "servicenotavailable": "Der Webservice ist für dieses Token nicht freigeschaltet.",
    "webservicesnotenabled": "Webservices sind in TUWEL deaktiviert.",
    "invalidparameter": "Ungültiger Parameter beim Aufruf.",
}


class TuwelFehler(Exception):
    def __init__(self, meldung: str, fehlercode: str | None = None, funktion: str | None = None):
        super().__init__(meldung)
        self.fehlercode = fehlercode
        self.funktion = funktion


def flache_parameter(werte: dict[str, Any], praefix: str = "") -> dict[str, str]:
    """Moodle erwartet verschachtelte Parameter als `name[0][feld]=wert`."""
    flach: dict[str, str] = {}
    for schluessel, wert in werte.items():
        name = f"{praefix}[{schluessel}]" if praefix else str(schluessel)
        if isinstance(wert, dict):
            flach.update(flache_parameter(wert, name))
        elif isinstance(wert, (list, tuple)):
            flach.update(flache_parameter(dict(enumerate(wert)), name))
        elif isinstance(wert, bool):
            flach[name] = "1" if wert else "0"
        elif wert is not None:
            flach[name] = str(wert)
    return flach


class TuwelClient:
    def __init__(self, url: str, token: str, http: httpx.Client | None = None, timeout: float = 30):
        if not token:
            raise TuwelFehler("Kein TUWEL-Token gesetzt – bitte im Hub unter „Einrichtung“ eintragen.")
        self.url = url.rstrip("/")
        self._token = token
        self._http = http or httpx.Client(timeout=timeout, follow_redirects=True)

    def aufruf(self, funktion: str, **parameter: Any) -> Any:
        daten = {"wstoken": self._token, "wsfunction": funktion, "moodlewsrestformat": "json"}
        daten.update(flache_parameter(parameter))
        try:
            antwort = self._http.post(self.url + REST_PFAD, data=daten)
        except httpx.HTTPError as fehler:
            raise TuwelFehler(f"TUWEL nicht erreichbar: {type(fehler).__name__}", funktion=funktion) from None
        if antwort.status_code != 200:
            raise TuwelFehler(f"TUWEL antwortet mit HTTP {antwort.status_code}", funktion=funktion)
        try:
            ergebnis = antwort.json()
        except ValueError:
            raise TuwelFehler("TUWEL lieferte keine JSON-Antwort (Wartung oder Login-Seite?)", funktion=funktion) from None
        if isinstance(ergebnis, dict) and ("exception" in ergebnis or "errorcode" in ergebnis):
            code = ergebnis.get("errorcode")
            # Originaltext von Moodle mitgeben (unterscheidet z. B. „nicht gefunden“ und „abgelaufen“)
            original = str(ergebnis.get("message") or "").replace(self._token, "***")
            meldung = HINWEISE.get(code, original or "Unbekannter Moodle-Fehler")
            if original and original != meldung:
                meldung += f" TUWEL meldet: „{original}“"
            raise TuwelFehler(f"{funktion}: {meldung} ({code})", fehlercode=code, funktion=funktion)
        return ergebnis

    def datei_url(self, url: str) -> str:
        """Datei-Links aus TUWEL brauchen den Token als Parameter, um ohne Browser-Login zu laden."""
        trenner = "&" if "?" in url else "?"
        return f"{url}{trenner}token={self._token}"

    # --- bequeme Hüllen für die benötigten Funktionen -------------------------

    def seiteninfo(self) -> dict:
        return self.aufruf("core_webservice_get_site_info")

    def kurse(self, benutzer_id: int) -> list[dict]:
        return self.aufruf("core_enrol_get_users_courses", userid=benutzer_id)

    def kursinhalte(self, kurs_id: int) -> list[dict]:
        return self.aufruf("core_course_get_contents", courseid=kurs_id)

    def schliessen(self) -> None:
        self._http.close()
