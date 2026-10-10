"""Wochenvorschlag mit Lernblöcken über die API: Lernen vor Arbeit, Konflikte, Rückmeldung."""

from datetime import datetime, timedelta

import pytest
from fpdf import FPDF

import app.lernaufwand as lernaufwand
from app.models import Dokument, Lva, Termin

WOCHE = "2026-10-05"


def regel(**kw):
    basis = {
        "stunden_pro_woche": 16, "tage": [0, 1, 2, 3, 4], "fruehester_beginn": "08:00", "spaetestes_ende": "18:00",
        "min_block_minuten": 120, "max_block_minuten": 480, "puffer_minuten": 30, "min_freie_tage": 1,
        "lern_min_block_minuten": 45, "lern_max_block_minuten": 120, "lern_tage": [0, 1, 2, 3, 4, 5],
    }
    basis.update(kw)
    return basis


@pytest.fixture
def ordner(tmp_path, monkeypatch):
    monkeypatch.setattr(lernaufwand, "UNTERLAGEN_ORDNER", tmp_path)
    return tmp_path


@pytest.fixture
def daten(session, ordner):
    """EP1 VO mit Folien vom Montag; Übung der gleichnamigen UE-LVA am Donnerstag 10 Uhr."""
    vo = Lva(schluessel="185.A91", nummer="185.A91", titel="Programmierung", kurzname="EP1", semester="2026W", ects=6)
    ue = Lva(schluessel="185.A92", nummer="185.A92", titel="Programmierung", kurzname="EP1 UE", semester="2026W")
    session.add_all([vo, ue])
    session.flush()
    session.add(Termin(lva_id=ue.id, typ="UE", titel="UE", start=datetime(2026, 10, 8, 10), ende=datetime(2026, 10, 8, 12),
                       anwesenheit_abweichung=True))
    folien = FPDF(orientation="L")
    for _ in range(60):  # 60 Folien × 2 min = 120 min
        folien.add_page()
    folien.output(str(ordner / "vo1.pdf"))
    doc = Dokument(lva_id=vo.id, tuwel_kurs_id=1, tuwel_cm_id=1, schluessel="vo1.pdf", dateiname="VO 1 Folien.pdf",
                   typ="pdf", ist_link=False, quelle_url="u", pfad="vo1.pdf",
                   erschienen_am=datetime(2026, 10, 5, 9), erschienen_quelle="tuwel")
    session.add(doc)
    session.commit()
    return {"vo": vo, "ue": ue, "doc": doc}


def test_vorschlag_plant_erst_lernen_dann_arbeit(client, daten):
    client.put("/api/arbeit/regel", json=regel())
    v = client.post("/api/arbeit/vorschlag", params={"woche": WOCHE}).json()

    assert v["lern_stunden"] == 2 and v["lern_offen_stunden"] == 0
    lernen = v["lernbloecke"]
    assert sum(b["geplante_minuten"] for b in lernen) == 120
    assert all(b["lva_name"] == "EP1" and b["status"] == "vorschlag" for b in lernen)
    erster = datetime.fromisoformat(lernen[0]["start"])
    assert datetime(2026, 10, 5, 9) <= erster  # nicht vor Erscheinen
    assert all(datetime.fromisoformat(b["ende"]) <= datetime(2026, 10, 8, 10) for b in lernen)  # vor der Übung
    assert any(b.startswith("Lernen EP1") for b in v["begruendungen"])
    assert lernen[0]["zuteilung"] == {str(daten["doc"].id): lernen[0]["geplante_minuten"]}

    # Arbeit füllt die Wochenstunden und überschneidet keinen Lernblock
    assert v["verplant_stunden"] == 16 and v["konflikte"] == []
    for a in v["bloecke"]:
        for l in lernen:
            assert datetime.fromisoformat(a["ende"]) <= datetime.fromisoformat(l["start"]) or datetime.fromisoformat(a["start"]) >= datetime.fromisoformat(l["ende"])

    # Lernbedarf je LVA mit ECTS-Abgleich ist Teil der Antwort
    ep1 = next(b for b in v["lernbedarf"] if b["lva_name"] == "EP1")
    assert ep1["unterlagen_minuten"] == 120 and ep1["soll_minuten"] is not None

    # Kalender zeigt die Lernblöcke in der Farbe der LVA
    events = client.get("/api/kalender", params={"von": "2026-10-05T00:00:00", "bis": "2026-10-12T00:00:00"}).json()
    lern_events = [e for e in events if e["extendedProps"].get("art") == "lernen"]
    assert len(lern_events) == len(lernen) and "vorschlag" in lern_events[0]["classNames"]


def test_konflikt_wird_gemeldet_statt_still_zu_kuerzen(client, daten, session):
    # Nur Montag und Dienstag 8–14 Uhr, 10 h Arbeit, 4 h Stoff: beides zusammen passt nicht
    daten["doc"].seiten = None
    session.commit()
    client.put("/api/arbeit/regel", json=regel(
        stunden_pro_woche=10, tage=[0, 1], lern_tage=[0, 1], spaetestes_ende="14:00", min_block_minuten=60,
    ))
    client.patch(f"/api/lvas/{daten['vo'].id}", json={"lernparameter": {"minuten_pro_folie": 4}})  # 60 × 4 = 240 min
    v = client.post("/api/arbeit/vorschlag", params={"woche": WOCHE}).json()

    assert v["lern_stunden"] > 0
    assert v["fehlende_stunden"] > 0
    arbeit = next(k for k in v["konflikte"] if k.startswith("Arbeit:"))
    assert "Lernblöcke Vorrang haben" in arbeit and "verschieben oder verwerfen" in arbeit
    # Summe aus Geplantem und Gemeldetem: nichts verschwindet unbemerkt
    assert v["verplant_stunden"] + v["fehlende_stunden"] == v["soll_stunden"]


def test_kein_doppeltes_einplanen_und_bestaetigen_verwerfen(client, daten):
    client.put("/api/arbeit/regel", json=regel())
    client.post("/api/arbeit/vorschlag", params={"woche": WOCHE})
    assert client.post("/api/arbeit/bestaetigen", params={"woche": WOCHE}).json()["bestaetigt"] > 0
    bloecke = client.get("/api/lernen/bloecke").json()
    assert bloecke and all(b["status"] == "bestaetigt" for b in bloecke)

    # Stoff ist abgedeckt: der nächste Vorschlag plant ihn nicht erneut
    v = client.post("/api/arbeit/vorschlag", params={"woche": WOCHE}).json()
    assert v["lernbloecke"] == [] and v["lern_stunden"] == 0
    assert len(client.get("/api/lernen/bloecke").json()) == len(bloecke)

    # Vorschläge lassen sich verwerfen, bestätigte bleiben
    assert client.post("/api/arbeit/verwerfen", params={"woche": WOCHE}).status_code == 200
    assert len(client.get("/api/lernen/bloecke").json()) == len(bloecke)


def test_tatsaechliche_zeit_verbessert_die_schaetzung(client, daten):
    client.put("/api/arbeit/regel", json=regel())
    v = client.post("/api/arbeit/vorschlag", params={"woche": WOCHE}).json()
    block = v["lernbloecke"][0]
    ep1 = lambda: next(l for l in client.get("/api/lvas").json() if l["id"] == daten["vo"].id)  # noqa: E731
    assert ep1()["korrektur_faktor"] == 1.0

    eingetragen = client.patch(f"/api/lernen/bloecke/{block['id']}",
                               json={"tatsaechliche_minuten": block["geplante_minuten"] * 3}).json()
    assert eingetragen["erledigt"] and eingetragen["status"] == "bestaetigt"
    faktor = ep1()["korrektur_faktor"]
    assert faktor > 1.3 and ep1()["korrektur_rueckmeldungen"] == 1

    # die Schätzung derselben Unterlage wächst mit dem Faktor
    bedarf = client.get("/api/lernen/bedarf", params={"woche": WOCHE}).json()
    assert next(b for b in bedarf if b["lva_name"] == "EP1")["unterlagen_minuten"] == round(120 * faktor)


def test_lernblock_verschieben_loeschen_und_validierung(client, daten):
    client.put("/api/arbeit/regel", json=regel())
    block = client.post("/api/arbeit/vorschlag", params={"woche": WOCHE}).json()["lernbloecke"][0]
    verschoben = client.patch(f"/api/lernen/bloecke/{block['id']}",
                              json={"start": "2026-10-06T16:00:00", "ende": "2026-10-06T17:00:00"}).json()
    assert verschoben["status"] == "bestaetigt" and verschoben["geplante_minuten"] == 60
    assert client.patch(f"/api/lernen/bloecke/{block['id']}", json={"ende": "2026-10-06T15:00:00"}).status_code == 422
    assert client.patch(f"/api/lernen/bloecke/{block['id']}", json={"tatsaechliche_minuten": -5}).status_code == 422
    assert client.delete(f"/api/lernen/bloecke/{block['id']}").status_code == 204
    assert client.delete(f"/api/lernen/bloecke/{block['id']}").status_code == 404


def test_lva_lernwerte_und_ects_einstellen(client, daten):
    lva_id = daten["vo"].id
    antwort = client.patch(f"/api/lvas/{lva_id}", json={"ects": 4.5, "lernparameter": {"video_faktor": 2.0}}).json()
    assert antwort["ects"] == 4.5
    assert antwort["lernparameter"]["video_faktor"] == 2.0 and antwort["lernparameter"]["minuten_pro_folie"] == 2.0
    # Zurück auf den Standardwert speichert keine Abweichung mehr
    client.patch(f"/api/lvas/{lva_id}", json={"lernparameter": {"video_faktor": 1.5}})
    assert client.get("/api/lvas").json()[0]["lernparameter"]["video_faktor"] == 1.5
    assert client.patch(f"/api/lvas/{lva_id}", json={"lernparameter": {"unbekannt": 1}}).status_code == 422
    assert client.patch(f"/api/lvas/{lva_id}", json={"lernparameter": {"video_faktor": -1}}).status_code == 422
    assert client.patch(f"/api/lvas/{lva_id}", json={"ects": 100}).status_code == 422


def test_regel_mit_lerneinstellungen(client):
    gespeichert = client.put("/api/arbeit/regel", json=regel(lern_max_block_minuten=90, ects_warnschwelle=0.3)).json()
    assert gespeichert["lern_max_block_minuten"] == 90 and gespeichert["ects_warnschwelle"] == 0.3
    assert client.put("/api/arbeit/regel", json=regel(lern_tage=[9])).status_code == 422
    assert client.put("/api/arbeit/regel", json=regel(lern_min_block_minuten=120, lern_max_block_minuten=60)).status_code == 422


def test_unterlagen_zeigen_schaetzung_und_eigene_lernzeit(client, daten):
    doc_id = daten["doc"].id
    eintrag = next(d for d in client.get("/api/tuwel/dokumente").json() if d["id"] == doc_id)
    assert (eintrag["lernart"], eintrag["seiten"], eintrag["lern_minuten_geschaetzt"], eintrag["lern_minuten"]) == ("folien", 60, 120, None)

    assert client.patch(f"/api/tuwel/dokumente/{doc_id}", json={"lern_minuten": 0}).json()["lern_minuten"] == 0
    client.put("/api/arbeit/regel", json=regel())
    v = client.post("/api/arbeit/vorschlag", params={"woche": WOCHE}).json()
    assert v["lernbloecke"] == []  # „nicht lernen“ erzeugt keinen Lernblock

    client.patch(f"/api/tuwel/dokumente/{doc_id}", json={"lern_minuten": None})  # zurück zur Schätzung
    assert client.post("/api/arbeit/vorschlag", params={"woche": WOCHE}).json()["lern_stunden"] == 2
    assert client.patch(f"/api/tuwel/dokumente/{doc_id}", json={"lern_minuten": -1}).status_code == 422
    assert client.patch("/api/tuwel/dokumente/9999", json={"lern_minuten": 5}).status_code == 404
