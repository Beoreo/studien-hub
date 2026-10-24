"""Zugriff auf die MB Cloud (Nextcloud) per WebDAV – schonend: eine Anfrage nach der anderen, mit Pause.

Anmeldung über den Nextcloud-Login-Flow v2 (so melden sich auch die Nextcloud-Programme bei TU-Login an):
`login_starten` liefert eine Adresse, die man im Browser öffnet und dort mit dem TU Login bestätigt;
`login_abfragen` liefert danach Benutzer und App-Passwort. Das TU-Passwort sieht der Hub nie.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from urllib.parse import quote

import httpx

from .config import MBCLOUD_PAUSE_SEKUNDEN
from .mbcloud import PROPFIND_KOERPER, DavEintrag, propfind_lesen

KENNUNG = "Studien-Hub (lokal, nur lesend)"


class MbCloudFehler(Exception):
    """Fehler beim Zugriff – wird im Reiter „MB Cloud“ angezeigt."""


class MbCloud:
    def __init__(self, url: str, benutzer: str, passwort: str, pause: float = MBCLOUD_PAUSE_SEKUNDEN,
                 transport: httpx.BaseTransport | None = None, schlafen: Callable[[float], None] = time.sleep):
        self.url = url.rstrip("/")
        self.benutzer = benutzer
        self.dav_wurzel = f"/remote.php/dav/files/{quote(benutzer)}/"
        self.pause = pause
        self.schlafen = schlafen
        self.anfragen = 0
        self._letzte = 0.0
        self.http = httpx.Client(base_url=self.url, auth=(benutzer, passwort), timeout=60, transport=transport,
                                 headers={"User-Agent": KENNUNG, "OCS-APIRequest": "true"}, follow_redirects=True)

    def _warten(self) -> None:
        """Mindestabstand zwischen zwei Anfragen."""
        rest = self.pause - (time.monotonic() - self._letzte)
        if self.anfragen and rest > 0:
            self.schlafen(rest)
        self._letzte = time.monotonic()
        self.anfragen += 1

    def _pfad(self, pfad: str) -> str:
        return self.dav_wurzel + quote(pfad.strip("/"))

    def liste(self, pfad: str) -> list[DavEintrag]:
        """Inhalt eines Ordners (Tiefe 1). Der erste Eintrag ist der Ordner selbst."""
        self._warten()
        antwort = self.http.request("PROPFIND", self._pfad(pfad) + "/", content=PROPFIND_KOERPER,
                                    headers={"Depth": "1", "Content-Type": "application/xml"})
        if antwort.status_code == 401:
            raise MbCloudFehler("Anmeldung abgelehnt – App-Passwort widerrufen? Im Reiter „MB Cloud“ neu verbinden.")
        if antwort.status_code == 404:
            raise MbCloudFehler(f"Ordner nicht gefunden: {pfad}")
        if antwort.status_code >= 400:
            raise MbCloudFehler(f"MB Cloud antwortet mit HTTP {antwort.status_code} ({pfad})")
        return propfind_lesen(antwort.content, self.dav_wurzel)

    @contextmanager
    def herunterladen(self, pfad: str) -> Iterator[Iterator[bytes]]:
        """Datei als Datenstrom; ein Download zur Zeit."""
        self._warten()
        with self.http.stream("GET", self._pfad(pfad)) as antwort:
            if antwort.status_code >= 400:
                raise MbCloudFehler(f"Download fehlgeschlagen (HTTP {antwort.status_code}): {pfad}")
            yield antwort.iter_bytes(1024 * 1024)

    def schliessen(self) -> None:
        self.http.close()


# --- Login-Flow v2 ---------------------------------------------------------------------------------

def login_starten(url: str, transport: httpx.BaseTransport | None = None) -> dict:
    """Startet die Anmeldung: {"login": Adresse für den Browser, "token": …, "endpoint": …}."""
    with httpx.Client(timeout=30, transport=transport, headers={"User-Agent": KENNUNG}) as http:
        antwort = http.post(f"{url.rstrip('/')}/index.php/login/v2")
    if antwort.status_code >= 400:
        raise MbCloudFehler(f"Anmeldung nicht möglich (HTTP {antwort.status_code}) – Login-Flow in der MB Cloud gesperrt?")
    daten = antwort.json()
    return {"login": daten["login"], "token": daten["poll"]["token"], "endpoint": daten["poll"]["endpoint"]}


def login_abfragen(endpoint: str, token: str, transport: httpx.BaseTransport | None = None) -> dict | None:
    """None, solange im Browser noch nicht bestätigt; sonst {"server", "loginName", "appPassword"}."""
    with httpx.Client(timeout=30, transport=transport, headers={"User-Agent": KENNUNG}) as http:
        antwort = http.post(endpoint, data={"token": token})
    if antwort.status_code == 404:
        return None
    if antwort.status_code >= 400:
        raise MbCloudFehler(f"Anmeldung fehlgeschlagen (HTTP {antwort.status_code})")
    return antwort.json()
