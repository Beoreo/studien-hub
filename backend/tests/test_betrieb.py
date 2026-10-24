"""Alltagsbetrieb: Zugangsdaten, Sicherungen, Nachholen verpasster Läufe, Autostart, CORS, Status, Einrichtung."""

import sqlite3
import sys
from datetime import datetime, time, timedelta

import pytest

from app import autostart, einrichtung, geheimnisse, jobs, ki_einrichtung, sicherung
from app.config import ERWEITERUNG_ID
from app.models import lies_einstellung, setze_einstellung
from app.tuwel_sync import SCHLUESSEL_ERWEITERUNG, erweiterungs_schluessel


@pytest.fixture(autouse=True)
def leere_geheimnisse():
    geheimnisse.alle_loeschen()
    yield
    geheimnisse.alle_loeschen()


# --- Zugangsdaten -----------------------------------------------------------------------------------

def test_zugangsdaten_aus_env_uebernehmen(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# Kopf\nTUWEL_TOKEN=abc123\nTUWEL_URL=https://tuwel.test\nMBCLOUD_BENUTZER=ben\nMBCLOUD_APP_PASSWORT=\n",
                   encoding="utf-8")
    assert geheimnisse.aus_env_uebernehmen(env) == ["TUWEL_TOKEN", "MBCLOUD_BENUTZER"]
    assert geheimnisse.lies("TUWEL_TOKEN") == "abc123" and geheimnisse.lies("MBCLOUD_BENUTZER") == "ben"
    zeilen = env.read_text(encoding="utf-8").splitlines()
    assert zeilen[0] == "# Kopf" and zeilen[2] == "TUWEL_URL=https://tuwel.test"  # anderes bleibt
    assert zeilen[1].startswith("# TUWEL_TOKEN=") and "abc123" not in env.read_text(encoding="utf-8")
    assert geheimnisse.aus_env_uebernehmen(env) == []  # zweiter Start: nichts mehr zu tun
    assert geheimnisse.aus_env_uebernehmen(tmp_path / "fehlt.env") == []


def test_vorhandener_wert_wird_nicht_ueberschrieben(tmp_path):
    geheimnisse.setze("TUWEL_TOKEN", "neu")
    env = tmp_path / ".env"
    env.write_text("TUWEL_TOKEN=alt\n", encoding="utf-8")
    geheimnisse.aus_env_uebernehmen(env)
    assert geheimnisse.lies("TUWEL_TOKEN") == "neu"


def test_erweiterungs_schluessel_wandert_aus_der_datenbank(session):
    setze_einstellung(session, SCHLUESSEL_ERWEITERUNG, "alter-schluessel")
    session.commit()
    assert erweiterungs_schluessel(session) == "alter-schluessel"
    assert geheimnisse.lies("ERWEITERUNG_SCHLUESSEL") == "alter-schluessel"
    assert lies_einstellung(session, SCHLUESSEL_ERWEITERUNG) is None
    neu = erweiterungs_schluessel(session, neu=True)
    assert neu != "alter-schluessel" and erweiterungs_schluessel(session) == neu


# --- Sicherungen ------------------------------------------------------------------------------------

def datenbank(pfad, wert):
    verbindung = sqlite3.connect(pfad)
    verbindung.execute("CREATE TABLE IF NOT EXISTS t (wert TEXT)")
    verbindung.execute("DELETE FROM t")
    verbindung.execute("INSERT INTO t VALUES (?)", (wert,))
    verbindung.commit()
    verbindung.close()


def lesen(pfad):
    verbindung = sqlite3.connect(pfad)
    try:
        return verbindung.execute("SELECT wert FROM t").fetchone()[0]
    finally:
        verbindung.close()


def test_sichern_aufraeumen_und_wiederherstellen(tmp_path):
    db, ordner = tmp_path / "studienhub.db", tmp_path / "sicherungen"
    for tag in range(1, 17):  # 16 Tage – die 14 neuesten bleiben
        datenbank(db, f"Stand {tag}")
        sicherung.sichern(datenbank=db, ordner=ordner, jetzt=datetime(2026, 10, tag, 12))
    namen = [e["name"] for e in sicherung.liste(ordner)]
    assert len(namen) == 14 and namen[0] == "studienhub-20261016-120000.db" and namen[-1] == "studienhub-20261003-120000.db"

    # die älteste wiederherstellen: sie darf nicht vorher weggeräumt werden
    vorher = sicherung.wiederherstellen(namen[-1], datenbank=db, ordner=ordner)
    assert lesen(db) == "Stand 3"
    assert lesen(vorher) == "Stand 16" and "vor-wiederherstellung" in vorher.name
    assert len(sicherung.liste(ordner)) == 14

    with pytest.raises(sicherung.SicherungsFehler):
        sicherung.wiederherstellen("../studienhub.db", datenbank=db, ordner=ordner)
    with pytest.raises(sicherung.SicherungsFehler):
        sicherung.sichern(datenbank=tmp_path / "fehlt.db", ordner=ordner)


# --- Geplante Läufe und Nachholen -------------------------------------------------------------------

def test_verpasste_taegliche_laeufe():
    job = jobs.Job("x", "X", lambda: None, taeglich=time(6), nachholen=True)
    morgens, mittags = datetime(2026, 10, 12, 5), datetime(2026, 10, 12, 9)
    assert jobs.letzter_planzeitpunkt(job, morgens) == datetime(2026, 10, 11, 6)  # heute noch nicht dran
    assert jobs.letzter_planzeitpunkt(job, mittags) == datetime(2026, 10, 12, 6)
    assert jobs.verpasst(job, mittags, None)  # noch nie gelaufen
    assert jobs.verpasst(job, mittags, datetime(2026, 10, 11, 6, 1))  # gestern gelaufen, heute 6 Uhr verpasst
    assert not jobs.verpasst(job, mittags, datetime(2026, 10, 12, 7))
    assert not jobs.verpasst(job, morgens, datetime(2026, 10, 11, 18))  # Laptop gestern Abend an: nichts verpasst
    intervall = jobs.Job("y", "Y", lambda: None, intervall_minuten=10)
    assert not jobs.verpasst(intervall, mittags, None)


def test_ausfuehren_protokolliert_und_nachholen(session, monkeypatch):
    aufrufe = []
    test_jobs = {
        "gut": jobs.Job("gut", "Gut", lambda: aufrufe.append("gut"), taeglich=time(6), nachholen=True),
        "kaputt": jobs.Job("kaputt", "Kaputt", lambda: 1 / 0, taeglich=time(6), nachholen=True),
        "selten": jobs.Job("selten", "Selten", lambda: None, intervall_minuten=10),
    }
    monkeypatch.setattr(jobs, "JOBS", test_jobs)
    assert jobs.ausfuehren("gut") and aufrufe == ["gut"]
    assert jobs.stand("gut")["fehler"] is None and jobs.stand("gut")["letztes_ende"]
    jobs.ausfuehren("kaputt")  # Fehler wird gemerkt, nicht weitergereicht
    assert "division" in jobs.stand("kaputt")["fehler"]["meldung"]

    gestartet = []
    gelaufen = datetime.fromisoformat(jobs.stand("gut")["letzter_start"])
    abends = gelaufen.replace(hour=23)
    assert jobs.nachholen(abends, starten=gestartet.append) == ([] if gelaufen.hour >= 6 else ["gut", "kaputt"])
    morgen_frueh = (gelaufen + timedelta(days=1)).replace(hour=7)  # 6-Uhr-Lauf von morgen verpasst
    assert jobs.nachholen(morgen_frueh, starten=gestartet.append) == ["gut", "kaputt"]
    assert {j["id"]: j["fehler"] is not None for j in jobs.uebersicht()} == {"gut": False, "kaputt": True, "selten": False}


# --- Autostart --------------------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform != "win32", reason="Registry nur unter Windows")
def test_autostart_in_eigenem_testschluessel(monkeypatch):
    import winreg

    monkeypatch.setattr(autostart, "REG_PFAD", r"Software\StudienHubTest\Run")
    try:
        assert autostart.setzen(True, wert='"C:\\Test\\StudienHub.exe" --hintergrund') is True
        assert autostart.aktiv()
        assert autostart.setzen(False) is False
        assert autostart.setzen(False) is False  # zweimal aus: kein Fehler
    finally:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\StudienHubTest\Run")
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\StudienHubTest")
    assert not autostart.verfuegbar()  # nicht als exe: im Hub nicht schaltbar


# --- API: Status, Sync, CORS, Einrichtung -------------------------------------------------------------

def test_cors_nur_fuer_die_erweiterung(client):
    erlaubt = client.get("/api/status", headers={"Origin": f"chrome-extension://{ERWEITERUNG_ID}"})
    assert erlaubt.headers.get("access-control-allow-origin") == f"chrome-extension://{ERWEITERUNG_ID}"
    firefox = client.get("/api/status", headers={"Origin": "moz-extension://1234abcd-12ab-34cd-56ef-1234567890ab"})
    assert firefox.headers.get("access-control-allow-origin")
    for fremd in ("https://boese.example", "chrome-extension://aaaabbbbccccddddeeeeffffgggghhhh", "http://localhost:5173"):
        assert "access-control-allow-origin" not in client.get("/api/status", headers={"Origin": fremd}).headers
    vorab = client.options("/api/tuwel/sync/kurse", headers={
        "Origin": f"chrome-extension://{ERWEITERUNG_ID}", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-studienhub-schluessel"})
    assert vorab.status_code == 200


def test_status_seite_und_sync(client, monkeypatch):
    gestartet = []
    monkeypatch.setattr(jobs, "im_hintergrund", gestartet.append)
    status = client.get("/api/system/status").json()
    assert status["version"] and status["modus"] == "entwicklung"
    assert {q["id"] for q in status["quellen"]} == {"tiss", "tuwel", "steop", "mbcloud"}
    assert {j["id"] for j in status["jobs"]} >= {"tiss-sync", "mbcloud", "sicherung"}
    assert status["autostart"] == {"verfuegbar": False, "aktiv": status["autostart"]["aktiv"]}
    assert client.put("/api/system/autostart", json={"aktiv": True}).status_code == 409  # nur als exe

    assert client.post("/api/system/sync").json()["gestartet"] == ["tiss-sync", "mbcloud"]
    assert client.get("/api/tuwel/sync/anforderung").json()["angefordert"]
    assert client.post("/api/system/ordner/unbekannt").status_code == 404


def test_einrichtung_tuwel_token_und_abschluss(client):
    assert client.get("/api/einrichtung").json()["abgeschlossen"] is False
    assert client.put("/api/einrichtung/tuwel-token", json={"eingabe": "kein token!"}).status_code == 422
    token = "a" * 32
    assert client.put("/api/einrichtung/tuwel-token", json={"eingabe": token}).json() == {"eingerichtet": True}
    assert geheimnisse.lies("TUWEL_TOKEN") == token
    stand = client.get("/api/einrichtung").json()
    assert stand["tuwel"]["eingerichtet"] and stand["erweiterung"]["id"] == ERWEITERUNG_ID
    assert {m["id"] for m in stand["modelle"]} == {"embedding", "whisper"}
    assert stand["daten"]["quelle"] is None  # im Entwicklungsmodus nichts zu übernehmen
    client.post("/api/einrichtung/abschliessen")
    assert client.get("/api/einrichtung").json()["abgeschlossen"] is True


def test_daten_aus_entwicklung_uebernehmen(tmp_path, session, monkeypatch):
    projekt = tmp_path / "studien-hub"
    quelle = projekt / "daten"
    (quelle / "unterlagen" / "2026W").mkdir(parents=True)
    (quelle / "unterlagen" / "2026W" / "skript.pdf").write_bytes(b"%PDF")
    (quelle / "modelle").mkdir()
    (quelle / "modelle" / "m.onnx").write_bytes(b"x" * 10)
    datenbank(quelle / "studienhub.db", "aus der Entwicklung")
    (projekt / ".env").write_text("TUWEL_TOKEN=entwicklungstoken\n", encoding="utf-8")
    ziel = tmp_path / "StudienHub"
    ziel.mkdir()
    datenbank(ziel / "studienhub.db", "leer")
    geheimnisse.setze("ERWEITERUNG_SCHLUESSEL", "beim-ersten-start-erzeugt")
    # die laufende Datenbank (hier: In-Memory der Tests) enthält nach der Übernahme den alten Schlüssel der Erweiterung
    setze_einstellung(session, SCHLUESSEL_ERWEITERUNG, "kennt-die-erweiterung")
    session.commit()

    monkeypatch.setattr(einrichtung, "PRODUKTION", True)
    assert einrichtung.entwicklungs_daten({"entwicklungsordner": str(projekt)}) == quelle
    assert einrichtung.entwicklungs_daten({}) is None

    ergebnis = einrichtung.daten_uebernehmen(quelle, datenbank=ziel / "studienhub.db", daten_ordner=ziel)
    assert lesen(ziel / "studienhub.db") == "aus der Entwicklung"
    assert (ziel / "unterlagen" / "2026W" / "skript.pdf").read_bytes() == b"%PDF"
    assert (ziel / "modelle" / "m.onnx").exists()
    assert ergebnis["zugaenge"] == ["TUWEL_TOKEN"] and geheimnisse.lies("TUWEL_TOKEN") == "entwicklungstoken"
    assert ergebnis["sicherung"] and lesen(ziel / "sicherungen" / ergebnis["sicherung"]) == "leer"
    assert (quelle / "studienhub.db").exists()  # Entwicklungsordner bleibt
    assert geheimnisse.lies("ERWEITERUNG_SCHLUESSEL") == "kennt-die-erweiterung"


def test_claude_eintrag_der_exe(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Programme\StudienHub\StudienHub.exe")
    eintrag = ki_einrichtung.server_eintrag()
    assert eintrag["command"].endswith("StudienHub.exe") and eintrag["args"] == ["--mcp"]
    assert "PYTHONPATH" not in eintrag["env"] and eintrag["env"]["STUDIENHUB_OFFLINE"] == "1"
    config = tmp_path / "claude_desktop_config.json"
    config.write_text('{"mcpServers": {"anderer": {"command": "x"}}}', encoding="utf-8")
    assert ki_einrichtung.eintragen(config)["aktuell"]
    assert "anderer" in config.read_text(encoding="utf-8")
