"""Durchstich über die HTTP-API: Import, LVA-Markierungen, Arbeit, Kalender, Export."""

from datetime import date

REGEL = {
    "stunden_pro_woche": 12,
    "tage": [0, 1, 2, 3, 4],
    "bevorzugte_tage": [4],
    "fruehester_beginn": "08:00:00",
    "spaetestes_ende": "18:00:00",
    "min_block_minuten": 120,
    "max_block_minuten": 360,
    "puffer_minuten": 30,
    "arbeitgeber": "Firma",
}


def importieren(client, tiss_ics):
    antwort = client.post("/api/tiss/import-datei", files={"datei": ("tiss.ics", tiss_ics, "text/calendar")})
    assert antwort.status_code == 200, antwort.text
    return antwort.json()


def test_status(client):
    assert client.get("/api/status").json() == {"ok": True}


def test_import_und_lvas(client, tiss_ics):
    ergebnis = importieren(client, tiss_ics)
    assert ergebnis["neu"] == 5
    lvas = client.get("/api/lvas").json()
    assert {l["nummer"] for l in lvas} == {"185.A91", "104.271", "104.272"}
    ep1 = next(l for l in lvas if l["nummer"] == "185.A91")
    assert ep1["anzahl_termine"] == 3

    geaendert = client.patch(f"/api/lvas/{ep1['id']}", json={"farbe": "#123456", "steop": True, "kurzname": "EP1"}).json()
    assert geaendert["farbe"] == "#123456" and geaendert["steop"] is True
    assert client.patch(f"/api/lvas/{ep1['id']}", json={"farbe": "rot"}).status_code == 422

    einstellungen = client.get("/api/tiss/einstellungen").json()
    assert einstellungen["letzter_import"] is not None


def test_ungueltiger_feed(client):
    antwort = client.post("/api/tiss/import-datei", files={"datei": ("x.ics", b"kein kalender", "text/calendar")})
    assert antwort.status_code == 422
    assert client.get("/api/tiss/einstellungen").json()["letzter_fehler"]


def test_import_ohne_link(client):
    assert client.post("/api/tiss/import").status_code == 409


def test_termin_abweichung_setzen_und_zuruecksetzen(client, tiss_ics):
    importieren(client, tiss_ics)
    termin = client.get("/api/termine", params={"typ": "UE"}).json()[0]
    assert termin["anwesenheitspflicht"] is False
    gesetzt = client.patch(f"/api/termine/{termin['id']}", json={"anwesenheit_abweichung": True}).json()
    assert gesetzt["anwesenheitspflicht"] is True
    zurueck = client.patch(f"/api/termine/{termin['id']}", json={"anwesenheit_abweichung": None}).json()
    assert zurueck["anwesenheit_abweichung"] is None and zurueck["anwesenheitspflicht"] is False
    einzeln = client.get(f"/api/termine/{termin['id']}").json()
    assert einzeln["id"] == termin["id"] and einzeln["lva_anwesenheitspflicht"] is False
    assert client.get("/api/termine/9999").status_code == 404


def test_kalender_liefert_fullcalendar_events(client, tiss_ics):
    importieren(client, tiss_ics)
    events = client.get("/api/kalender", params={"von": "2026-10-05T00:00:00+02:00", "bis": "2026-10-12T00:00:00+02:00"}).json()
    assert len(events) == 5
    pruefung = next(e for e in events if e["extendedProps"]["pruefung"])
    assert "pruefung" in pruefung["classNames"]
    assert {"id", "title", "start", "end", "backgroundColor"} <= set(events[0])


def test_arbeitsregel_validierung(client):
    assert client.get("/api/arbeit/regel").json() is None
    falsch = dict(REGEL, min_block_minuten=600)
    assert client.put("/api/arbeit/regel", json=falsch).status_code == 422
    assert client.put("/api/arbeit/regel", json=REGEL).json()["stunden_pro_woche"] == 12


def test_vorschlag_bestaetigen_und_verschieben(client, tiss_ics):
    importieren(client, tiss_ics)
    assert client.post("/api/arbeit/vorschlag", params={"woche": "2026-10-07"}).status_code == 409
    client.put("/api/arbeit/regel", json=REGEL)

    vorschlag = client.post("/api/arbeit/vorschlag", params={"woche": "2026-10-07"}).json()
    assert vorschlag["woche"] == "2026-10-05"
    assert vorschlag["verplant_stunden"] == 12
    assert all(b["status"] == "vorschlag" for b in vorschlag["bloecke"])

    # Erneuter Vorschlag ersetzt die alten Vorschläge statt sie zu verdoppeln
    erneut = client.post("/api/arbeit/vorschlag", params={"woche": "2026-10-05"}).json()
    alle = client.get("/api/arbeit/bloecke").json()
    assert len(alle) == len(erneut["bloecke"])

    # Verschieben macht den Block fix
    block = alle[0]
    verschoben = client.patch(f"/api/arbeit/bloecke/{block['id']}", json={
        "start": block["start"], "ende": block["ende"], "notiz": "verschoben",
    }).json()
    assert verschoben["status"] == "bestaetigt"

    anzahl = client.post("/api/arbeit/bestaetigen", params={"woche": "2026-10-05"}).json()["bestaetigt"]
    assert anzahl == len(alle) - 1
    # Nach Bestätigung bleibt kein Bedarf übrig
    danach = client.post("/api/arbeit/vorschlag", params={"woche": "2026-10-05"}).json()
    assert danach["soll_stunden"] == 0 and danach["bloecke"] == []


def test_serie_anlegen_und_loeschen(client):
    client.put("/api/arbeit/regel", json=REGEL)
    bloecke = client.post("/api/arbeit/serien", json={
        "wochentage": [0, 2], "beginn": "08:00", "ende": "12:00", "von": "2026-10-05", "bis": "2026-10-18",
    }).json()
    assert len(bloecke) == 4
    assert all(b["arbeitgeber"] == "Firma" and b["art"] == "fix" for b in bloecke)
    serien = client.get("/api/arbeit/serien").json()
    assert serien[0]["anzahl"] == 4

    assert client.delete(f"/api/arbeit/serien/{serien[0]['serie_id']}", params={"ab": "2026-10-12"}).status_code == 204
    assert len(client.get("/api/arbeit/bloecke").json()) == 2

    # Serie mit bestätigten 8 h reduziert den Bedarf der Woche
    vorschlag = client.post("/api/arbeit/vorschlag", params={"woche": "2026-10-05"}).json()
    assert vorschlag["soll_stunden"] == 4


def test_manueller_block_und_loeschen(client):
    neu = client.post("/api/arbeit/bloecke", json={"start": "2026-10-05T08:00:00", "ende": "2026-10-05T10:00:00"})
    assert neu.status_code == 201 and neu.json()["dauer_stunden"] == 2
    assert client.post("/api/arbeit/bloecke", json={"start": "2026-10-05T10:00:00", "ende": "2026-10-05T08:00:00"}).status_code == 422
    assert client.delete(f"/api/arbeit/bloecke/{neu.json()['id']}").status_code == 204
    assert client.delete("/api/arbeit/bloecke/999").status_code == 404


def test_export_endpunkte(client, tiss_ics):
    importieren(client, tiss_ics)
    client.post("/api/arbeit/bloecke", json={"start": "2026-10-05T13:00:00", "ende": "2026-10-05T17:00:00"})
    params = {"arbeit": "nur", "von": "2026-10-01T00:00:00", "bis": "2026-11-01T00:00:00"}

    csv = client.get("/api/export/csv", params=params)
    assert csv.status_code == 200
    assert "arbeitszeiten" in csv.headers["content-disposition"]
    assert csv.content.decode("utf-8-sig").count("\r\n") == 3  # Kopf, Block, Summe

    ics = client.get("/api/export/ics", params={"typ": "VO", "arbeit": "ohne"})
    assert ics.content.count(b"BEGIN:VEVENT") == 1

    pdf = client.get("/api/export/pdf", params=params)
    assert pdf.content.startswith(b"%PDF")
    assert client.get("/api/export/docx").status_code == 404


def test_vorschlag_verwerfen_vor_bestaetigung(client):
    client.put("/api/arbeit/regel", json=REGEL)
    fix = client.post("/api/arbeit/bloecke", json={"start": "2026-10-05T08:00:00", "ende": "2026-10-05T10:00:00"}).json()
    vorschlag = client.post("/api/arbeit/vorschlag", params={"woche": "2026-10-05"}).json()
    assert vorschlag["bloecke"] and vorschlag["begruendungen"]
    assert isinstance(vorschlag["punktzahl"], float)

    verworfen = client.post("/api/arbeit/verwerfen", params={"woche": "2026-10-07"}).json()["verworfen"]
    assert verworfen == len(vorschlag["bloecke"])
    uebrig = client.get("/api/arbeit/bloecke").json()
    assert [b["id"] for b in uebrig] == [fix["id"]]  # bestätigter Block bleibt
    assert client.post("/api/arbeit/verwerfen", params={"woche": "2026-10-05"}).json()["verworfen"] == 0


def test_regel_mit_kriterien_speichern(client):
    regel = dict(REGEL, max_tag_stunden=8, lernfenster_minuten=90, voller_unitag_stunden=5, min_freie_tage=2,
                 gewichte={"gleichmaessig": 3, "buendeln": 10, "lernzeit": 7, "erholung": 0, "zerstueckelung": 1})
    gespeichert = client.put("/api/arbeit/regel", json=regel).json()
    assert gespeichert["max_tag_stunden"] == 8 and gespeichert["min_freie_tage"] == 2
    assert gespeichert["gewichte"]["buendeln"] == 10
    assert client.get("/api/arbeit/regel").json()["lernfenster_minuten"] == 90
    # Standardwerte, wenn nichts angegeben ist
    standard = client.put("/api/arbeit/regel", json=REGEL).json()
    assert standard["max_tag_stunden"] == 9 and standard["lernfenster_minuten"] == 120
    assert standard["gewichte"] == {"gleichmaessig": 5, "buendeln": 5, "lernzeit": 5, "erholung": 5, "zerstueckelung": 5}
    assert client.put("/api/arbeit/regel", json=dict(REGEL, gewichte={"lernzeit": 11})).status_code == 422
