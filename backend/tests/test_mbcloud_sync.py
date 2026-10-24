"""MB Cloud mit nachgebautem WebDAV-Server: Index nur mit Änderungen, Zuordnung, Downloads, Planung, API."""

import hashlib
from datetime import date, datetime, timedelta, timezone
from email.utils import format_datetime
from urllib.parse import quote, unquote

import httpx
import pytest
from sqlalchemy import select

import app.mbcloud_sync as mbcloud_sync
import app.routers.mbcloud as mbcloud_router
from app.config import mbcloud_zugang, zugangsdaten_setzen
from app.mbcloud_client import MbCloud, login_abfragen, login_starten
from app.mbcloud_sync import automatische_downloads, index_aktualisieren, lauf
from app.models import Dokument, Lernblock, Lva, LvaTeil, MbCloudDatei, MbCloudOrdner, Termin

HEUTE = date(2026, 10, 11)
W = "MB_VT_WIMB"
MECH = f"{W}/Mechanik 1 VO 309.019"


class FakeCloud:
    """Verzeichnisbaum im Speicher; ETags von Ordnern ändern sich mit ihrem Inhalt (wie in Nextcloud)."""

    def __init__(self):
        self.dateien: dict[str, bytes] = {}
        self.anfragen: list[tuple[str, str]] = []
        self.version = 0

    def datei(self, pfad: str, inhalt: bytes | None = None):
        self.version += 1
        self.dateien[pfad] = inhalt if inhalt is not None else f"{pfad}#{self.version}".encode()

    def ordner_von(self, pfad):
        return {"/".join(p.split("/")[:i]) for p in self.dateien for i in range(1, p.count("/") + 1)} | {""}

    def etag(self, pfad):
        if pfad in self.dateien:
            return hashlib.md5(self.dateien[pfad]).hexdigest()[:12]
        inhalt = sorted((p, self.dateien[p]) for p in self.dateien if p.startswith(pfad + "/"))
        return hashlib.md5(repr(inhalt).encode()).hexdigest()[:12]

    def antwort(self, pfad, ist_ordner):
        href = "/remote.php/dav/files/ben/" + quote(pfad) + ("/" if ist_ordner else "")
        zeit = format_datetime(datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc), usegmt=True)
        typ = "<d:collection/>" if ist_ordner else ""
        groesse = f"<oc:size>{1}</oc:size>" if ist_ordner else f"<d:getcontentlength>{len(self.dateien[pfad])}</d:getcontentlength>"
        return (f'<d:response><d:href>{href}</d:href><d:propstat><d:prop><d:getlastmodified>{zeit}</d:getlastmodified>'
                f'<d:getetag>"{self.etag(pfad)}"</d:getetag><d:resourcetype>{typ}</d:resourcetype>{groesse}</d:prop>'
                f'<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>')

    def handler(self, request: httpx.Request) -> httpx.Response:
        pfad = unquote(request.url.path).removeprefix("/remote.php/dav/files/ben/").strip("/")
        self.anfragen.append((request.method, pfad))
        if request.method == "PROPFIND":
            ordner = self.ordner_von(pfad)
            if pfad not in ordner:
                return httpx.Response(404)
            kinder = {p[len(pfad) + 1:].split("/")[0] for p in list(self.dateien) if p.startswith(pfad + "/")}
            teile = [self.antwort(pfad, True)]
            for k in sorted(kinder):
                kind = f"{pfad}/{k}"
                teile.append(self.antwort(kind, kind not in self.dateien))
            xml = '<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns">' + "".join(teile) + "</d:multistatus>"
            return httpx.Response(207, content=xml.encode())
        if request.method == "GET" and pfad in self.dateien:
            return httpx.Response(200, content=self.dateien[pfad])
        return httpx.Response(404)

    def client(self):
        return MbCloud("https://mbcloud.test", "ben", "app-passwort", pause=0, transport=httpx.MockTransport(self.handler))

    def listings(self):
        return [p for m, p in self.anfragen if m == "PROPFIND"]


@pytest.fixture
def cloud():
    c = FakeCloud()
    c.datei(f"{MECH}/Prüfungsunterlagen/2025-01-27-Pruefung-Mechanik 1.pdf", b"pruefung-2025")
    c.datei(f"{MECH}/Prüfungsunterlagen/2025-01-27-Loesung-Mechanik 1.pdf", b"loesung-2025")
    c.datei(f"{MECH}/Prüfungsunterlagen/2023-06-30-Gedankenprotokoll-Mechanik 1.pdf", b"protokoll-2023")
    c.datei(f"{MECH}/Prüfungsunterlagen/Alt/Pruefung 2015.pdf", b"pruefung-2015")
    c.datei(f"{MECH}/Zusammenfassungen/Zusammenfassung 2024.pdf", b"zusammenfassung")
    c.datei(f"{MECH}/Formelsammlung 2022.pdf", b"skript-gleich-wie-tuwel")
    c.datei(f"{W}/Mechanik 1 UE 309.021/Theoriefragen/Fragen 2024.pdf", b"theorie")
    c.datei(f"{W}/Mathematik 1 für MB und WIMB/Prüfungen/Test 2024.pdf", b"mathe")
    c.datei(f"{W}/Analytische Chemie/Altklausur 2023.pdf", b"chemie")
    c.datei("Folgt uns auf Insta/x.txt", b"x")
    return c


@pytest.fixture
def lvas(session, tmp_path, monkeypatch):
    monkeypatch.setattr(mbcloud_sync, "UNTERLAGEN_ORDNER", tmp_path)

    def lva(titel, nummern, kurz=None):
        l = Lva(schluessel=titel.casefold(), titel=titel, kurzname=kurz, semester="2026W", ects=6)
        session.add(l)
        session.flush()
        for n in nummern:
            session.add(LvaTeil(lva=l, nummer=n, typ="VO", steop=True))
        return l

    mech = lva("Mechanik 1", ["309.019", "309.021"])
    mathe = lva("Mathematik 1 für MB, WIMB und VT", ["104.297"], "Mathe 1")
    session.commit()
    return {"mech": mech, "mathe": mathe}


def test_erster_lauf_liest_nur_zugeordnete_ordner(session, cloud, lvas):
    bericht = index_aktualisieren(session, cloud.client(), HEUTE)
    ordner = {o.name: o for o in session.scalars(select(MbCloudOrdner))}
    assert set(ordner) == {"Mechanik 1 VO 309.019", "Mechanik 1 UE 309.021", "Mathematik 1 für MB und WIMB", "Analytische Chemie"}
    assert ordner["Mechanik 1 VO 309.019"].zuordnung == "auto" and ordner["Mechanik 1 VO 309.019"].lva_id == lvas["mech"].id
    assert ordner["Mathematik 1 für MB und WIMB"].zuordnung == "vorschlag"  # nur Titel: wartet auf Bestätigung
    assert ordner["Analytische Chemie"].lva_id is None
    # gelesen: Wurzel + die zwei Mechanik-Ordner samt Unterordnern – nicht Mathe (Vorschlag) und nicht Chemie
    gelesen = cloud.listings()
    assert gelesen[0] == W and not any("Mathematik" in p or "Chemie" in p or "Insta" in p for p in gelesen)
    assert bericht.vorschlaege == 1 and bericht.zugeordnet == 2 and bericht.neue_dateien == 7

    dateien = {d.name: d for d in session.scalars(select(MbCloudDatei).where(MbCloudDatei.ist_ordner.is_(False)))}
    p, l = dateien["2025-01-27-Pruefung-Mechanik 1.pdf"], dateien["2025-01-27-Loesung-Mechanik 1.pdf"]
    assert (p.kategorie, p.datum, p.jahr) == ("altpruefung", date(2025, 1, 27), 2025)
    assert l.kategorie == "loesung" and l.loesung_zu_id == p.id  # Lösung mit ihrer Prüfung verknüpft
    assert dateien["2023-06-30-Gedankenprotokoll-Mechanik 1.pdf"].gedankenprotokoll
    assert dateien["Fragen 2024.pdf"].kategorie == "altpruefung"  # Ordner „Theoriefragen“
    assert dateien["Zusammenfassung 2024.pdf"].kategorie == "ausarbeitung"
    assert dateien["Formelsammlung 2022.pdf"].kategorie == "formelsammlung"


def test_folgelaeufe_lesen_nur_aenderungen(session, cloud, lvas):
    index_aktualisieren(session, cloud.client(), HEUTE)
    cloud.anfragen.clear()
    index_aktualisieren(session, cloud.client(), HEUTE)
    assert cloud.listings() == [W]  # nichts geändert: nur die Liste der LVA-Ordner

    # neue Datei in einem Unterordner: nur dieser Zweig wird gelesen
    cloud.datei(f"{MECH}/Prüfungsunterlagen/2026-01-30-Pruefung-Mechanik 1.pdf", b"neu-2026")
    cloud.anfragen.clear()
    bericht = index_aktualisieren(session, cloud.client(), HEUTE)
    assert cloud.listings() == [W, MECH, f"{MECH}/Prüfungsunterlagen"]  # nicht „Alt“, nicht „Zusammenfassungen“
    assert bericht.neue_dateien == 1 and bericht.gelesen == ["Mechanik 1 VO 309.019"]

    # gelöschte Datei verschwindet aus dem Index
    del cloud.dateien[f"{MECH}/Zusammenfassungen/Zusammenfassung 2024.pdf"]
    cloud.version += 1
    bericht = index_aktualisieren(session, cloud.client(), HEUTE)
    assert bericht.entfernte_dateien == 1
    assert session.scalar(select(MbCloudDatei).where(MbCloudDatei.name == "Zusammenfassung 2024.pdf")) is None


def test_bestaetigung_gilt_fuer_kuenftige_dateien(client, session, cloud, lvas, monkeypatch):
    monkeypatch.setattr(mbcloud_router, "lauf_im_hintergrund", lambda: False)
    index_aktualisieren(session, cloud.client(), HEUTE)
    mathe = session.scalar(select(MbCloudOrdner).where(MbCloudOrdner.name.like("Mathematik%")))
    antwort = client.patch(f"/api/mbcloud/ordner/{mathe.id}", json={"zuordnung": "bestaetigt"}).json()
    assert antwort["zuordnung"] == "bestaetigt" and antwort["lva_id"] == lvas["mathe"].id
    chemie = session.scalar(select(MbCloudOrdner).where(MbCloudOrdner.name == "Analytische Chemie"))
    assert client.patch(f"/api/mbcloud/ordner/{chemie.id}", json={"zuordnung": "bestaetigt"}).status_code == 422
    client.patch(f"/api/mbcloud/ordner/{chemie.id}", json={"lva_id": lvas["mech"].id, "zuordnung": "abgelehnt"})

    session.expire_all()
    cloud.datei(f"{W}/Mathematik 1 für MB und WIMB/Prüfungen/Test 2025.pdf", b"mathe-2025")
    index_aktualisieren(session, cloud.client(), HEUTE)
    session.expire_all()
    mathe = session.get(MbCloudOrdner, mathe.id)
    assert mathe.zuordnung == "bestaetigt"  # bleibt bei weiteren Läufen
    namen = {d.name for d in session.scalars(select(MbCloudDatei).where(MbCloudDatei.ordner_id == mathe.id))}
    assert {"Test 2024.pdf", "Test 2025.pdf"} <= namen
    assert session.get(MbCloudOrdner, chemie.id).zuordnung == "abgelehnt"


def test_automatische_downloads_und_duplikate(session, cloud, lvas, tmp_path):
    # dieselbe Formelsammlung gibt es schon aus TUWEL
    summe = hashlib.sha256(b"skript-gleich-wie-tuwel").hexdigest()
    session.add(Dokument(lva_id=lvas["mech"].id, tuwel_kurs_id=1, tuwel_cm_id=7, schluessel="f", dateiname="Formeln.pdf",
                         typ="pdf", quelle_url="u", pfad="x/Formeln.pdf", pruefsumme=summe))
    session.commit()
    c = cloud.client()
    index_aktualisieren(session, c, HEUTE)
    c.anfragen = 0
    neu, duplikate, fehler = automatische_downloads(session, c, HEUTE)
    assert (neu, duplikate, fehler) == (4, 1, [])  # Prüfung, Lösung, Protokoll, Theoriefragen; Formel = Duplikat
    geladen = {m_p.rsplit("/", 1)[-1] for m, m_p in cloud.anfragen if m == "GET"}
    assert "Pruefung 2015.pdf" not in geladen and "Zusammenfassung 2024.pdf" not in geladen  # zu alt / per Klick

    doc = session.scalar(select(Dokument).where(Dokument.dateiname == "2025-01-27-Pruefung-Mechanik 1.pdf"))
    assert (doc.quelle, doc.kategorie, doc.jahr, doc.lva_id) == ("mbcloud", "altpruefung", 2025, lvas["mech"].id)
    assert doc.pfad == "2026W/Mechanik 1/MB Cloud/Altprüfung/2025-01-27-Pruefung-Mechanik 1.pdf"
    assert (tmp_path / doc.pfad).read_bytes() == b"pruefung-2025"
    formel = session.scalar(select(MbCloudDatei).where(MbCloudDatei.name == "Formelsammlung 2022.pdf"))
    assert formel.duplikat and formel.dokument.quelle == "tuwel"
    # zweiter Lauf lädt nichts erneut
    assert automatische_downloads(session, c, HEUTE) == (0, 0, [])


def test_ausgeblendete_lva_bekommt_keine_downloads(session, cloud, lvas):
    from app.lva_auswahl import setze_steop_abgeschlossen

    lvas["mech"].besuchen = False
    session.commit()
    c = cloud.client()
    index_aktualisieren(session, c, HEUTE)
    assert automatische_downloads(session, c, HEUTE) == (0, 0, [])
    setze_steop_abgeschlossen(session, True)


def test_lauf_meldet_fehler_sichtbar(session, lvas):
    kaputt = MbCloud("https://mbcloud.test", "ben", "falsch", pause=0, transport=httpx.MockTransport(lambda r: httpx.Response(401)))
    bericht = lauf(session, kaputt, HEUTE)
    assert bericht.fehler and "App-Passwort" in bericht.fehler[0]
    from app.models import lies_einstellung

    assert "App-Passwort" in lies_einstellung(session, "mbcloud_letzter_fehler")


def test_pause_zwischen_anfragen(cloud):
    pausen = []
    c = MbCloud("https://mbcloud.test", "ben", "pw", pause=1.0, transport=httpx.MockTransport(cloud.handler), schlafen=pausen.append)
    c.liste(W)
    c.liste(MECH)
    assert len(pausen) == 1 and 0 < pausen[0] <= 1.0  # vor der ersten Anfrage keine Pause, danach ein Abstand


# --- API und Planung ----------------------------------------------------------------------------------

@pytest.fixture
def geladen(session, cloud, lvas):
    c = cloud.client()
    index_aktualisieren(session, c, HEUTE)
    automatische_downloads(session, c, HEUTE)
    return c


def test_api_treffer_je_lva_laden_per_klick_und_bearbeitung(client, session, cloud, lvas, geladen, monkeypatch):
    monkeypatch.setattr(mbcloud_router, "verbindung", lambda: cloud.client())
    treffer = client.get("/api/mbcloud/dateien", params={"lva_id": lvas["mech"].id}).json()
    assert treffer[0]["name"].startswith("2025-01-27")  # neueste zuerst
    zusammenfassung = next(t for t in treffer if t["kategorie"] == "ausarbeitung")
    assert not zusammenfassung["automatisch"] and zusammenfassung["dokument_id"] is None
    geladen_jetzt = client.post(f"/api/mbcloud/dateien/{zusammenfassung['id']}/laden").json()
    assert geladen_jetzt["dokument_id"] is not None

    pruefung = next(t for t in treffer if t["name"] == "2025-01-27-Pruefung-Mechanik 1.pdf")
    erledigt = client.patch(f"/api/mbcloud/dokumente/{pruefung['dokument_id']}/bearbeitung",
                            json={"minuten": 150, "punkte": 34, "punkte_max": 50}).json()
    assert erledigt["bearbeitet_minuten"] == 150 and erledigt["punkte"] == 34 and erledigt["bearbeitet_am"]
    assert client.patch(f"/api/mbcloud/dokumente/{pruefung['dokument_id']}/bearbeitung",
                        json={"punkte": 60, "punkte_max": 50}).status_code == 422

    # Unterlagenliste: Herkunft erkennbar und filterbar
    docs = client.get("/api/tuwel/dokumente").json()
    assert {d["quelle"] for d in docs} == {"mbcloud"} and all(d["kategorie"] for d in docs)


def test_lernphase_fuellt_bloecke_mit_altpruefungen(client, session, lvas, geladen):
    mech = lvas["mech"]
    pruefung = datetime(2026, 10, 30, 9)  # Prüfung in drei Wochen: Lernphase ab der Woche des 19.10.
    for w in range(4):
        start = datetime(2026, 10, 5, 10) + timedelta(weeks=w)
        session.add(Termin(lva_id=mech.id, typ="VO", titel="VO", start=start, ende=start + timedelta(hours=2)))
    session.add(Termin(lva_id=mech.id, typ="PRUEFUNG", titel="Prüfung", start=pruefung, ende=pruefung + timedelta(hours=2)))
    session.commit()
    client.put("/api/arbeit/regel", json={"stunden_pro_woche": 10, "tage": [0, 1, 2, 3, 4], "min_freie_tage": 0})
    v = client.post("/api/arbeit/vorschlag", params={"woche": "2026-10-19"}).json()
    mech_bloecke = [b for b in v["lernbloecke"] if b["lva_id"] == mech.id]
    assert mech_bloecke
    themen = [b["thema"] for b in mech_bloecke]
    # neueste zuerst, eine Prüfung pro Block, als inoffiziell gekennzeichnet
    assert themen[0].startswith("Altprüfung 27.01.2025") and "(mit Lösung)" in themen[0] and "MB Cloud, inoffiziell" in themen[0]
    altpruefungen = [b for b in mech_bloecke if b["thema"].startswith("Altprüfung")]
    assert all(len(b["zuteilung"]) == 1 for b in altpruefungen)
    assert len({tuple(b["zuteilung"]) for b in altpruefungen}) == len(altpruefungen)
    assert mech_bloecke[0]["altpruefung"]["jahr"] == 2025

    # erledigte Altprüfung wird nicht mehr eingeplant
    dok_id = mech_bloecke[0]["altpruefung"]["dokument_id"]
    client.patch(f"/api/mbcloud/dokumente/{dok_id}/bearbeitung", json={"minuten": 120})
    v = client.post("/api/arbeit/vorschlag", params={"woche": "2026-10-19"}).json()
    assert all(str(dok_id) not in b["zuteilung"] for b in v["lernbloecke"])


# --- Verbinden (Login-Flow) ----------------------------------------------------------------------

def test_login_flow_und_env(tmp_path):
    zustand = {"bestaetigt": False}

    def handler(request):
        if request.url.path == "/index.php/login/v2":
            return httpx.Response(200, json={"poll": {"token": "t1", "endpoint": "https://mbcloud.test/login/v2/poll"},
                                             "login": "https://mbcloud.test/login/v2/flow/abc"})
        if request.url.path == "/login/v2/poll":
            if not zustand["bestaetigt"]:
                return httpx.Response(404)
            return httpx.Response(200, json={"server": "https://mbcloud.test", "loginName": "ben", "appPassword": "geheim"})
        return httpx.Response(500)

    transport = httpx.MockTransport(handler)
    start = login_starten("https://mbcloud.test", transport)
    assert start["login"].endswith("/flow/abc")
    assert login_abfragen(start["endpoint"], start["token"], transport) is None
    zustand["bestaetigt"] = True
    assert login_abfragen(start["endpoint"], start["token"], transport)["appPassword"] == "geheim"

    # Zugangsdaten landen in der Anmeldeinformationsverwaltung (in Tests: im Speicher)
    zugangsdaten_setzen({"MBCLOUD_URL": "https://mbcloud.test/", "MBCLOUD_BENUTZER": "ben", "MBCLOUD_APP_PASSWORT": "geheim"})
    assert mbcloud_zugang() == ("https://mbcloud.test", "ben", "geheim")
    zugangsdaten_setzen({"MBCLOUD_BENUTZER": None, "MBCLOUD_APP_PASSWORT": None, "MBCLOUD_URL": None})
    assert mbcloud_zugang() is None


def test_api_ohne_verbindung(client, monkeypatch):
    monkeypatch.setattr(mbcloud_router, "mbcloud_zugang", lambda: None)
    status = client.get("/api/mbcloud/status").json()
    assert status["verbunden"] is False and status["url"] == "https://mbcloud.at" and status["wurzel"] == "MB_VT_WIMB"
    assert client.post("/api/mbcloud/lauf").status_code == 409
