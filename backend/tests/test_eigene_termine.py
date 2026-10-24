"""Eigene Termine im Kalender: zu einer LVA (bleiben beim TISS-Import) und persönlich ohne LVA (sperren die Planung)."""

from datetime import date, datetime, timedelta

import pytest

from app.models import Lva, LvaTeil, PersoenlicherTermin, Termin
from app.tiss_import import importiere_ical

MONTAG = date(2026, 10, 5)
REGEL = {"stunden_pro_woche": 30, "tage": [0, 1, 2, 3, 4], "fruehester_beginn": "08:00", "spaetestes_ende": "18:00",
         "min_block_minuten": 120, "max_block_minuten": 480, "puffer_minuten": 0, "min_freie_tage": 0}


@pytest.fixture
def mechanik(session):
    lva = Lva(schluessel="309.019", nummer="309.019", titel="Mechanik 1", typ="VO", semester="2026W")
    lva.teile = [LvaTeil(nummer="309.019", typ="VO", anwesenheitspflicht=True)]
    session.add(lva)
    session.commit()
    return lva


def ueberschneidet(block, von, bis):
    return datetime.fromisoformat(block["start"]) < bis and datetime.fromisoformat(block["ende"]) > von


def test_eigener_lva_termin_anlegen_aendern_loeschen(client, session, mechanik):
    neu = client.post("/api/termine", json={"lva_id": mechanik.id, "titel": "Tutorium", "typ": "UE",
                                            "start": "2026-10-06T16:00:00", "ende": "2026-10-06T18:00:00", "ort": "HS 1"})
    assert neu.status_code == 201
    t = neu.json()
    assert (t["quelle"], t["typ"], t["teil_bezeichnung"], t["anwesenheitspflicht"]) == ("manuell", "UE", "VO", True)
    events = client.get("/api/kalender", params={"von": "2026-10-05T00:00:00", "bis": "2026-10-12T00:00:00"}).json()
    (event,) = [e for e in events if e["extendedProps"].get("terminId") == t["id"]]
    assert event["editable"] and event["extendedProps"]["quelle"] == "manuell"

    verschoben = client.patch(f"/api/termine/{t['id']}", json={"start": "2026-10-07T10:00:00", "ende": "2026-10-07T11:00:00",
                                                                 "titel": "Tutorium (verlegt)"}).json()
    assert (verschoben["start"], verschoben["titel"]) == ("2026-10-07T10:00:00", "Tutorium (verlegt)")
    assert client.patch(f"/api/termine/{t['id']}", json={"ende": "2026-10-07T09:00:00"}).status_code == 422
    assert client.post("/api/termine", json={"lva_id": 999, "titel": "x", "start": "2026-10-06T16:00:00",
                                             "ende": "2026-10-06T18:00:00"}).status_code == 404

    # der TISS-Import lässt eigene Termine stehen
    importiere_ical(session, "BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:v1\nDTSTART;TZID=Europe/Vienna:20261005T090000\n"
                             "DTEND;TZID=Europe/Vienna:20261005T110000\nSUMMARY:309.019 VO Mechanik 1\nEND:VEVENT\nEND:VCALENDAR\n",
                    neu_planen=False)
    assert session.get(Termin, t["id"]) is not None
    assert client.delete(f"/api/termine/{t['id']}").status_code == 204
    assert client.delete(f"/api/termine/{t['id']}").status_code == 404


def test_tiss_termine_bleiben_tiss_termine(client, session, mechanik):
    tiss = Termin(lva_id=mechanik.id, teil_id=mechanik.teile[0].id, tiss_uid="x", typ="VO", titel="VO",
                  start=datetime(2026, 10, 5, 9), ende=datetime(2026, 10, 5, 11))
    session.add(tiss)
    session.commit()
    assert client.patch(f"/api/termine/{tiss.id}", json={"start": "2026-10-05T10:00:00"}).status_code == 409
    assert client.delete(f"/api/termine/{tiss.id}").status_code == 409
    # Abweichungen der Markierungen bleiben möglich
    assert client.patch(f"/api/termine/{tiss.id}", json={"aufzeichnung_abweichung": True}).json()["aufzeichnung"] is True


def test_persoenlicher_termin_haelt_arbeit_und_lernen_frei(client, session):
    client.put("/api/arbeit/regel", json=REGEL)
    arzt = client.post("/api/termine/persoenlich", json={"titel": "Arzt", "start": "2026-10-06T08:00:00",
                                                          "ende": "2026-10-06T18:00:00", "ort": "Praxis"})
    assert arzt.status_code == 201
    a = arzt.json()
    v = client.post("/api/arbeit/vorschlag", params={"woche": MONTAG.isoformat()}).json()
    von, bis = datetime(2026, 10, 6, 8), datetime(2026, 10, 6, 18)
    assert v["bloecke"] and not any(ueberschneidet(b, von, bis) for b in v["bloecke"])

    events = client.get("/api/kalender", params={"von": "2026-10-05T00:00:00", "bis": "2026-10-12T00:00:00"}).json()
    (event,) = [e for e in events if e["extendedProps"]["art"] == "persoenlich"]
    assert (event["title"], event["editable"], event["extendedProps"]["ort"]) == ("Arzt", True, "Praxis")
    nur_arbeit = client.get("/api/kalender", params={"von": "2026-10-05T00:00:00", "bis": "2026-10-12T00:00:00",
                                                     "arbeit": "nur"}).json()
    assert not [e for e in nur_arbeit if e["extendedProps"]["art"] == "persoenlich"]

    # verschieben plant die Woche mit Vorschlägen neu: jetzt ist der Dienstag wieder frei, der Mittwoch belegt
    client.patch(f"/api/termine/persoenlich/{a['id']}", json={"start": "2026-10-07T08:00:00", "ende": "2026-10-07T18:00:00"})
    bloecke = client.get("/api/arbeit/bloecke").json()
    assert not any(ueberschneidet(b, datetime(2026, 10, 7, 8), datetime(2026, 10, 7, 18)) for b in bloecke)
    assert client.patch(f"/api/termine/persoenlich/{a['id']}", json={"ende": "2026-10-07T07:00:00"}).status_code == 422
    assert client.delete(f"/api/termine/persoenlich/{a['id']}").status_code == 204
    assert session.query(PersoenlicherTermin).count() == 0
    assert client.post("/api/termine/persoenlich", json={"titel": "x", "start": "2026-10-06T10:00:00",
                                                         "ende": "2026-10-06T09:00:00"}).status_code == 422
