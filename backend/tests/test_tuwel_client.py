"""TUWEL-Client gegen eine nachgebaute Moodle-Schnittstelle (kein Netzwerk)."""

import json
from urllib.parse import parse_qs

import httpx
import pytest

from app.tuwel_client import TuwelClient, TuwelFehler, flache_parameter

TOKEN = "geheimer-token-123"


def client_mit(antworten: dict, aufrufe: list | None = None) -> TuwelClient:
    """Baut einen Client, dessen HTTP-Aufrufe von `antworten[wsfunction]` beantwortet werden."""

    def behandle(anfrage: httpx.Request) -> httpx.Response:
        daten = {k: v[0] for k, v in parse_qs(anfrage.content.decode()).items()}
        if aufrufe is not None:
            aufrufe.append(daten)
        antwort = antworten[daten["wsfunction"]]
        if isinstance(antwort, httpx.Response):
            return antwort
        return httpx.Response(200, json=antwort)

    return TuwelClient("https://tuwel.example", TOKEN, http=httpx.Client(transport=httpx.MockTransport(behandle)))


def test_flache_parameter():
    assert flache_parameter({"userid": 5}) == {"userid": "5"}
    assert flache_parameter({"options": [{"name": "x", "value": True}]}) == {
        "options[0][name]": "x",
        "options[0][value]": "1",
    }
    assert flache_parameter({"leer": None}) == {}


def test_seiteninfo_und_kurse():
    aufrufe = []
    client = client_mit({
        "core_webservice_get_site_info": {"sitename": "TUWEL", "userid": 42, "functions": []},
        "core_enrol_get_users_courses": [{"id": 7, "shortname": "185.A91-2026W", "fullname": "EP1"}],
    }, aufrufe)
    assert client.seiteninfo()["userid"] == 42
    assert client.kurse(42)[0]["id"] == 7
    assert aufrufe[1]["userid"] == "42"
    assert aufrufe[0]["wstoken"] == TOKEN and aufrufe[0]["moodlewsrestformat"] == "json"


def test_moodle_fehler_wird_verstaendlich_und_ohne_token_gemeldet():
    client = client_mit({"core_webservice_get_site_info": {
        "exception": "moodle_exception", "errorcode": "invalidtoken", "message": "Invalid token - token not found",
    }})
    with pytest.raises(TuwelFehler) as fehler:
        client.seiteninfo()
    assert fehler.value.fehlercode == "invalidtoken"
    assert "Sicherheitsschlüssel" in str(fehler.value)
    assert "token not found" in str(fehler.value)  # Originaltext von Moodle
    assert TOKEN not in str(fehler.value)


def test_http_fehler_und_kein_json():
    client = client_mit({
        "core_webservice_get_site_info": httpx.Response(503),
        "core_enrol_get_users_courses": httpx.Response(200, text="<html>Login</html>"),
    })
    with pytest.raises(TuwelFehler, match="HTTP 503"):
        client.seiteninfo()
    with pytest.raises(TuwelFehler, match="keine JSON"):
        client.kurse(1)


def test_netzwerkfehler_ohne_token_in_meldung():
    def kaputt(anfrage):
        raise httpx.ConnectError("verbindung weg", request=anfrage)

    client = TuwelClient("https://tuwel.example", TOKEN, http=httpx.Client(transport=httpx.MockTransport(kaputt)))
    with pytest.raises(TuwelFehler, match="nicht erreichbar") as fehler:
        client.seiteninfo()
    assert TOKEN not in str(fehler.value)


def test_ohne_token():
    with pytest.raises(TuwelFehler, match="Kein TUWEL-Token"):
        TuwelClient("https://tuwel.example", "")


def test_datei_url_haengt_token_an():
    client = client_mit({})
    assert client.datei_url("https://t/pluginfile.php/1/a.pdf") == f"https://t/pluginfile.php/1/a.pdf?token={TOKEN}"
    assert client.datei_url("https://t/x.php?forcedownload=1").endswith(f"&token={TOKEN}")
