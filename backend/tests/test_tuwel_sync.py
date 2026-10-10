"""TUWEL-Sync auf Hub-Seite: Zuordnung, Abgleich, Prüfsummen, Ablage, API mit Schlüssel."""

import io
import json
from datetime import datetime, timedelta

import pytest

import app.routers.tuwel as tuwel_router
import app.tuwel_sync as sync
from app.models import Dokument, Lva, TuwelKurs
from app.tuwel_sync import (
    Eintrag,
    datei_speichern,
    inhalt_abgleichen,
    kurse_registrieren,
    ordne_kurs_zu,
    semester_aus_text,
    sicherer_name,
)


@pytest.fixture
def unterlagen(tmp_path, monkeypatch):
    monkeypatch.setattr(sync, "UNTERLAGEN_ORDNER", tmp_path)
    monkeypatch.setattr(tuwel_router, "UNTERLAGEN_ORDNER", tmp_path)
    return tmp_path


@pytest.fixture
def lvas(session):
    ep1 = Lva(schluessel="185.A91", nummer="185.A91", titel="Einführung in die Programmierung 1", semester="2026W",
              kurzname="EP1")
    ep1_alt = Lva(schluessel="185.A91", nummer="185.A91", titel="Einführung in die Programmierung 1", semester="2025W")
    algebra = Lva(schluessel="104.271", nummer="104.271", titel="Algebra und Diskrete Mathematik", semester="2026W")
    ohne_nummer = Lva(schluessel="Technische Grundlagen", titel="Technische Grundlagen der Informatik", semester="2026W")
    session.add_all([ep1, ep1_alt, algebra, ohne_nummer])
    session.commit()
    return {"ep1": ep1, "ep1_alt": ep1_alt, "algebra": algebra, "tgi": ohne_nummer}


def kurs(session, id_, kurzname, name=""):
    return kurse_registrieren(session, [{"id": id_, "kurzname": kurzname, "name": name}])[0]


# --- Zuordnung ------------------------------------------------------------------------

def test_semester_aus_text():
    assert semester_aus_text("185.A91-2026W") == "2026W"
    assert semester_aus_text("EP1 (VU 2026WS)") == "2026W"
    assert semester_aus_text("Algebra WS 2026/27") == "2026W"
    assert semester_aus_text("SS2027 Analysis") == "2027S"
    assert semester_aus_text("ohne Angabe") is None


def test_zuordnung_ueber_nummer_und_semester(session, lvas):
    assert kurs(session, 1, "185.A91-2026W", "EP1").lva_id == lvas["ep1"].id
    assert kurs(session, 2, "185.A91-2025W").lva_id == lvas["ep1_alt"].id
    # ohne Semester: neuestes Semester
    assert kurs(session, 3, "185.A91 EP1").lva_id == lvas["ep1"].id
    # Zuordnung wird in der LVA vermerkt (nur wenn dort noch leer)
    assert lvas["ep1"].tuwel_kurs_id == 1


def test_zuordnung_ueber_titel_und_keine(session, lvas):
    assert kurs(session, 4, "TGI", "Technische Grundlagen der Informatik (VU 2026W)").lva_id == lvas["tgi"].id
    assert kurs(session, 5, "XYZ", "Ganz anderer Kurs 2026W").lva_id is None
    assert kurs(session, 6, "999.999-2026W", "Unbekannt").lva_id is None


def test_manuelle_zuordnung_hat_vorrang(session, lvas):
    k = kurs(session, 7, "Sonderkurs", "Tutorium")
    k.zuordnung, k.lva_id = "manuell", lvas["algebra"].id
    session.commit()
    assert kurse_registrieren(session, [{"id": 7, "kurzname": "185.A91-2026W"}])[0].lva_id == lvas["algebra"].id
    # in der LVA-Liste eingetragene TUWEL-Kurs-ID gewinnt vor der Nummer
    lvas["tgi"].tuwel_kurs_id = 8
    session.commit()
    assert kurs(session, 8, "185.A91-2026W").lva_id == lvas["tgi"].id


# --- Abgleich und Ablage ---------------------------------------------------------------

def eintrag(**kw):
    basis = dict(cm_id=100, url="https://tuwel/pluginfile.php/1/mod_resource/content/3/folien.pdf",
                 abschnitt="Woche 1", aktivitaet="Folien", dateiname="folien.pdf")
    basis.update(kw)
    return Eintrag(**basis)


def test_neue_datei_wird_angefordert_gespeichert_und_beim_naechsten_lauf_uebersprungen(session, lvas, unterlagen):
    k = kurs(session, 1, "185.A91-2026W")
    e = eintrag()
    assert inhalt_abgleichen(session, k, [e])["herunterladen"] == [e.url]

    ergebnis = datei_speichern(session, k, e, io.BytesIO(b"%PDF-1"))
    assert ergebnis["status"] == "neu"
    assert ergebnis["pfad"] == "2026W/EP1/Woche 1/folien.pdf"
    assert (unterlagen / ergebnis["pfad"]).read_bytes() == b"%PDF-1"
    doc = session.get(Dokument, ergebnis["id"])
    assert doc.typ == "pdf" and doc.groesse == 6 and len(doc.pruefsumme) == 64

    # Zweiter Lauf, gleiche URL: nichts herunterladen
    zweiter = inhalt_abgleichen(session, k, [e])
    assert zweiter["herunterladen"] == [] and zweiter["unveraendert"] == 1


def test_geaenderte_datei_behaelt_alte_version(session, lvas, unterlagen):
    k = kurs(session, 1, "185.A91-2026W")
    datei_speichern(session, k, eintrag(), io.BytesIO(b"Version 1"))
    neu = eintrag(url="https://tuwel/pluginfile.php/1/mod_resource/content/4/folien.pdf")  # neue Revision
    assert inhalt_abgleichen(session, k, [neu])["herunterladen"] == [neu.url]

    ergebnis = datei_speichern(session, k, neu, io.BytesIO(b"Version 2"))
    assert ergebnis["status"] == "geaendert"
    ordner = unterlagen / "2026W/EP1/Woche 1"
    assert (ordner / "folien.pdf").read_bytes() == b"Version 2"
    alte = [p for p in ordner.iterdir() if "(alt " in p.name]
    assert len(alte) == 1 and alte[0].read_bytes() == b"Version 1"


def test_neue_url_gleicher_inhalt_ist_unveraendert(session, lvas, unterlagen):
    k = kurs(session, 1, "185.A91-2026W")
    datei_speichern(session, k, eintrag(), io.BytesIO(b"gleich"))
    ergebnis = datei_speichern(session, k, eintrag(url="https://tuwel/x/5/folien.pdf"), io.BytesIO(b"gleich"))
    assert ergebnis["status"] == "unveraendert"
    assert len(list((unterlagen / "2026W/EP1/Woche 1").iterdir())) == 1  # keine Kopie, keine Altversion


def test_fehlende_datei_wird_erneut_angefordert(session, lvas, unterlagen):
    k = kurs(session, 1, "185.A91-2026W")
    ergebnis = datei_speichern(session, k, eintrag(), io.BytesIO(b"x"))
    (unterlagen / ergebnis["pfad"]).unlink()
    assert inhalt_abgleichen(session, k, [eintrag()])["herunterladen"] == [eintrag().url]


def test_ordnerdateien_und_namensgleichheit(session, lvas, unterlagen):
    k = kurs(session, 1, "185.A91-2026W")
    a = datei_speichern(session, k, eintrag(cm_id=200, dateiname="blatt.pdf", unterordner="Übungen/Teil 1"), io.BytesIO(b"a"))
    assert a["pfad"] == "2026W/EP1/Woche 1/Übungen/Teil 1/blatt.pdf"
    # andere Aktivität, gleicher Name im selben Abschnitt -> eigener Name statt Überschreiben
    b = datei_speichern(session, k, eintrag(cm_id=300, dateiname="folien.pdf"), io.BytesIO(b"b"))
    c = datei_speichern(session, k, eintrag(cm_id=301, dateiname="folien.pdf"), io.BytesIO(b"c"))
    assert b["pfad"] != c["pfad"] and c["pfad"].endswith("folien (301).pdf")


def test_videos_nur_als_link(session, lvas, unterlagen):
    k = kurs(session, 1, "185.A91-2026W")
    video = eintrag(cm_id=400, art="video", url="https://lecturetube.tuwien.ac.at/v/123", aktivitaet="VO 1 Aufzeichnung")
    ergebnis = inhalt_abgleichen(session, k, [video])
    assert ergebnis == {"herunterladen": [], "unveraendert": 0, "videos_neu": 1}
    doc = session.query(Dokument).one()
    assert doc.ist_link and doc.typ == "video" and doc.pfad is None and doc.dateiname == "VO 1 Aufzeichnung"
    assert inhalt_abgleichen(session, k, [video])["videos_neu"] == 0
    assert not any(unterlagen.rglob("*.*"))  # nichts heruntergeladen


def test_kurs_ohne_lva_wird_abgelehnt(session, lvas, unterlagen):
    k = kurs(session, 9, "Unbekannt")
    with pytest.raises(ValueError):
        inhalt_abgleichen(session, k, [eintrag()])


def test_sicherer_name():
    assert sicherer_name('a<b>:c"/d\\e|f?g*.pdf') == "a_b__c__d_e_f_g_.pdf"
    assert sicherer_name("CON.txt") == "_CON.txt"
    assert sicherer_name("ende. ") == "ende"
    lang = sicherer_name("x" * 300 + ".pdf")
    assert len(lang) == 100 and lang.endswith(".pdf")


def test_status_warnung(session):
    assert "Noch kein" in sync.status(session)["warnung"]
    sync.sync_beenden(session, {"neu": 1, "fehler": []})
    assert sync.status(session)["warnung"] is None
    spaeter = datetime.now() + timedelta(hours=40)
    assert "kein erfolgreicher" in sync.status(session, jetzt=spaeter)["warnung"]


# --- API mit Schlüssel ------------------------------------------------------------------

def test_api_sync_ablauf(client, session, lvas, unterlagen):
    assert client.post("/api/tuwel/sync/kurse", json={"kurse": []}).status_code == 401
    schluessel = client.get("/api/tuwel/einrichtung").json()["schluessel"]
    assert client.post("/api/tuwel/sync/kurse", json={"kurse": []}, headers={"X-Studienhub-Schluessel": "falsch"}).status_code == 401
    kopf = {"X-Studienhub-Schluessel": schluessel}
    assert client.get("/api/tuwel/sync/pruefen", headers=kopf).json() == {"ok": True}

    kurse = client.post("/api/tuwel/sync/kurse", headers=kopf, json={"kurse": [
        {"id": 1, "kurzname": "185.A91-2026W", "name": "EP1"},
        {"id": 2, "kurzname": "XYZ", "name": "Fremdkurs"},
    ]}).json()["kurse"]
    assert [(k["id"], k["synchronisieren"]) for k in kurse] == [(1, True), (2, False)]

    e = {"cm_id": 100, "url": "https://tuwel/pluginfile.php/1/mod_resource/content/3/folien.pdf",
         "abschnitt": "Woche 1", "aktivitaet": "Folien", "dateiname": "folien.pdf"}
    inhalt = client.post("/api/tuwel/sync/inhalt", headers=kopf, json={"kurs_id": 1, "eintraege": [
        e, {"cm_id": 101, "url": "https://youtu.be/abc", "art": "video", "aktivitaet": "Video"},
    ]}).json()
    assert inhalt["herunterladen"] == [e["url"]] and inhalt["videos_neu"] == 1
    assert client.post("/api/tuwel/sync/inhalt", headers=kopf, json={"kurs_id": 2, "eintraege": []}).status_code == 409

    hoch = client.post("/api/tuwel/sync/datei", headers=kopf,
                       data={"kurs_id": "1", "eintrag": json.dumps(e)},
                       files={"datei": ("folien.pdf", b"%PDF-test", "application/pdf")})
    assert hoch.json()["status"] == "neu"

    client.post("/api/tuwel/sync/ende", headers=kopf, json={"statistik": {"neu": 1, "fehler": []}})
    status = client.get("/api/tuwel/status").json()
    assert status["warnung"] is None and status["dateien"] == 1 and status["videos"] == 1
    assert status["kurse_ohne_lva"] == 1

    doks = client.get("/api/tuwel/dokumente", params={"lva_id": lvas["ep1"].id}).json()
    datei = next(d for d in doks if not d["ist_link"])
    assert client.get(f"/api/tuwel/dokumente/{datei['id']}/datei").content == b"%PDF-test"
    video = next(d for d in doks if d["ist_link"])
    assert video["url"] == "https://youtu.be/abc"
    assert client.get(f"/api/tuwel/dokumente/{video['id']}/datei").status_code == 404


def test_api_fehler_und_manuelle_zuordnung(client, session, lvas):
    schluessel = client.get("/api/tuwel/einrichtung").json()["schluessel"]
    kopf = {"X-Studienhub-Schluessel": schluessel}
    client.post("/api/tuwel/sync/fehler", headers=kopf, json={"meldung": "Nicht in TUWEL eingeloggt", "art": "login"})
    assert client.get("/api/tuwel/status").json()["letzter_fehler"]["art"] == "login"

    client.post("/api/tuwel/sync/kurse", headers=kopf, json={"kurse": [{"id": 2, "kurzname": "XYZ"}]})
    zugeordnet = client.patch("/api/tuwel/kurse/2", json={"lva_id": lvas["algebra"].id}).json()
    assert zugeordnet["zuordnung"] == "manuell" and zugeordnet["synchronisieren"]
    aus = client.patch("/api/tuwel/kurse/2", json={"aus": True}).json()
    assert aus["zuordnung"] == "aus" and not aus["synchronisieren"]
    assert client.patch("/api/tuwel/kurse/999", json={"aus": True}).status_code == 404

    alt = client.get("/api/tuwel/einrichtung").json()["schluessel"]
    neu = client.post("/api/tuwel/einrichtung/neuer-schluessel").json()["schluessel"]
    assert neu != alt
    assert client.get("/api/tuwel/sync/pruefen", headers={"X-Studienhub-Schluessel": alt}).status_code == 401
