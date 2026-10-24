"""Stufe 4: Wissensstand (Stufen, Wiederholung), Themen aus der Kapitelstruktur, Lernereignisse, API."""

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select

from app.embedding import HashEmbedder
from app.extraktion import AbschnittRoh
from app.models import Dokument, Lernereignis, Lva, Termin, Thema, Wissensstand
from app.suche import abschnitte_speichern
from app.themen import ereignis_eintragen, faellige_wiederholungen, themen_ableiten, titel_aus_kapitel, uebersicht
from app.wissensstand import faellig, naechste_wiederholung, neue_stufe

HEUTE = date(2026, 10, 12)


# --- Regeln ------------------------------------------------------------------------------------------

def test_stufen_nach_ergebnis():
    assert neue_stufe(2, 0.9) == 3 and neue_stufe(4, 1.0) == 4  # hinauf, höchstens 4
    assert neue_stufe(2, 0.6) == 2 and neue_stufe(0, 0.6) == 1  # bleibt, mindestens „gesehen“
    assert neue_stufe(2, 0.3) == 1 and neue_stufe(0, 0.0) == 0  # hinunter, mindestens 0


def test_wiederholung_wird_laenger_endet_vor_der_pruefung():
    assert [naechste_wiederholung(s, HEUTE) - HEUTE for s in range(5)] == [timedelta(days=d) for d in (1, 2, 4, 9, 21)]
    assert naechste_wiederholung(4, HEUTE, pruefung=HEUTE + timedelta(days=10)) == HEUTE + timedelta(days=9)
    assert naechste_wiederholung(4, HEUTE, pruefung=HEUTE + timedelta(days=1)) == HEUTE + timedelta(days=1)
    assert naechste_wiederholung(2, HEUTE, pruefung=HEUTE - timedelta(days=3)) == HEUTE + timedelta(days=4)  # vorbei
    assert faellig(HEUTE, HEUTE) and faellig(HEUTE - timedelta(days=1), HEUTE) and not faellig(None, HEUTE)


def test_titel_aus_kapitel():
    assert titel_aus_kapitel("2 Statik starrer Körper") == "Statik starrer Körper"
    assert titel_aus_kapitel("Kapitel 3: Reibung") == "Reibung"
    assert titel_aus_kapitel("Einleitung") == "Einleitung"


# --- Themen aus der Kapitelstruktur ----------------------------------------------------------------

@pytest.fixture
def mechanik(session):
    lva = Lva(schluessel="mech", titel="Mechanik 1", kurzname="Mech", semester="2026W")
    session.add(lva)
    session.flush()

    def dok(name, lernart, quelle="tuwel"):
        d = Dokument(lva_id=lva.id, tuwel_kurs_id=1, tuwel_cm_id=len(name), schluessel=name, dateiname=name, typ="pdf",
                     quelle_url="u", lernart=lernart, quelle=quelle)
        session.add(d)
        session.flush()
        return d

    e = HashEmbedder()
    abschnitte_speichern(session, dok("Skript.pdf", "skript"), [
        AbschnittRoh("Gleichgewicht der Kräfte", "1 Statik", "1 Statik", 1, 2),
        AbschnittRoh("Schnittprinzip", "1 Statik", "1 Statik > 1.2 Schnitt", 3, 3),
        AbschnittRoh("Haftreibung nach Coulomb", "2 Reibung", "2 Reibung", 10, 11),
        AbschnittRoh("Polarkoordinaten", "3 Kinematik", "3 Kinematik", 20, 21),
    ], "tuwel", e)
    abschnitte_speichern(session, dok("VO 1 Folien.pdf", "folien"), [AbschnittRoh("Einführung", "Überblick", None, 1, 1)], "tuwel", e)
    session.add(Termin(lva_id=lva.id, typ="PRUEFUNG", titel="Prüfung", start=datetime(2026, 10, 30, 9), ende=datetime(2026, 10, 30, 11)))
    session.commit()
    return lva


def test_themen_aus_dem_skript_und_eigene_bleiben(session, mechanik):
    neue = themen_ableiten(session, mechanik, HashEmbedder())
    assert [(t.titel, t.kapitel, t.reihenfolge) for t in neue] == [
        ("Statik", "1 Statik", 1), ("Reibung", "2 Reibung", 2), ("Kinematik", "3 Kinematik", 3)]
    statik = neue[0]
    assert len(statik.abschnitte) >= 2 and all(a.lva_id == mechanik.id for a in statik.abschnitte)

    # eigenes Thema und Wissensstand bleiben beim erneuten Ableiten erhalten, nichts doppelt
    session.add(Thema(lva_id=mechanik.id, titel="Prüfungsaufgaben", quelle="manuell", reihenfolge=4))
    ereignis_eintragen(session, statik, "quiz", 0.9, heute=HEUTE)
    assert themen_ableiten(session, mechanik) == []
    assert session.query(Thema).count() == 4 and session.get(Wissensstand, statik.id).stufe == 1


def test_ohne_gegliedertes_skript_dienen_foliensaetze_als_themen(session):
    lva = Lva(schluessel="gbuf", titel="GBUF", semester="2026W")
    session.add(lva)
    session.flush()
    for name in ("VO 1 Strategie.pdf", "VO 2 Organisation.pdf"):
        session.add(Dokument(lva_id=lva.id, tuwel_kurs_id=1, tuwel_cm_id=len(name), schluessel=name, dateiname=name,
                             typ="pdf", quelle_url="u", lernart="folien", erschienen_am=datetime(2026, 10, len(name) % 20 + 1)))
    session.commit()
    assert {t.titel for t in themen_ableiten(session, lva)} == {"VO 1 Strategie", "VO 2 Organisation"}


def test_lernereignisse_stufen_und_faellige_wiederholungen(session, mechanik):
    themen_ableiten(session, mechanik)
    statik, reibung, kinematik = session.scalars(select(Thema).order_by(Thema.reihenfolge)).all()
    e1 = ereignis_eintragen(session, statik, "quiz", 0.9, "8/9 richtig", heute=HEUTE)
    assert (e1.stufe_vorher, e1.stufe_nachher) == (0, 1)
    ereignis_eintragen(session, statik, "altpruefung", 0.85, heute=HEUTE + timedelta(days=2))
    stand = session.get(Wissensstand, statik.id)
    assert stand.stufe == 2 and stand.letzte_uebung == HEUTE + timedelta(days=2)
    assert stand.naechste_wiederholung == HEUTE + timedelta(days=6)  # Stufe 2: 4 Tage
    ereignis_eintragen(session, reibung, "selbsteinschaetzung", stufe=4, heute=HEUTE)
    assert session.get(Wissensstand, reibung.id).naechste_wiederholung == date(2026, 10, 29)  # Tag vor der Prüfung

    assert [t["titel"] for t in faellige_wiederholungen(session, heute=date(2026, 10, 18))] == ["Statik"]
    assert faellige_wiederholungen(session, heute=HEUTE) == []
    protokoll = session.scalars(select(Lernereignis).order_by(Lernereignis.id)).all()
    assert [(e.art, e.ergebnis) for e in protokoll] == [("quiz", 0.9), ("altpruefung", 0.85), ("selbsteinschaetzung", None)]

    (u,) = uebersicht(session, mechanik.id, heute=HEUTE)
    assert u["tage_bis_pruefung"] == 18 and u["verteilung"] == {0: 1, 1: 0, 2: 1, 3: 0, 4: 1}
    assert u["fortschritt"] == round((2 + 4) / 12, 2) and [t["stufe"] for t in u["themen"]] == [2, 4, 0]


# --- API ---------------------------------------------------------------------------------------------------

def test_api_themen_bearbeiten_und_wissensstand(client, session, mechanik):
    assert client.post("/api/wissen/themen/ableiten", params={"lva_id": mechanik.id}).json() == {"neue_themen": {"Mech": 3}}
    (u,) = client.get("/api/wissen/uebersicht").json()
    assert [t["titel"] for t in u["themen"]] == ["Statik", "Reibung", "Kinematik"]
    neu = client.post("/api/wissen/themen", json={"lva_id": mechanik.id, "titel": "Prüfungsbeispiele"}).json()
    assert neu["quelle"] == "manuell" and neu["reihenfolge"] == 4

    # umbenennen und an die erste Stelle schieben
    kinematik = u["themen"][2]
    geaendert = client.patch(f"/api/wissen/themen/{kinematik['id']}", json={"titel": "Kinematik des Punktes", "reihenfolge": 1}).json()
    assert geaendert["titel"] == "Kinematik des Punktes" and geaendert["quelle"] == "manuell"
    (u,) = client.get("/api/wissen/uebersicht").json()
    assert [t["titel"] for t in u["themen"]] == ["Kinematik des Punktes", "Statik", "Reibung", "Prüfungsbeispiele"]

    antwort = client.post(f"/api/wissen/themen/{kinematik['id']}/ereignis", json={"art": "quiz", "ergebnis": 0.95}).json()
    assert antwort["stufe_nachher"] == 1 and antwort["thema"]["naechste_wiederholung"]
    assert client.post(f"/api/wissen/themen/{kinematik['id']}/ereignis", json={"art": "quiz"}).status_code == 422
    assert client.post(f"/api/wissen/themen/{kinematik['id']}/ereignis", json={"art": "raten", "ergebnis": 1}).status_code == 422
    assert client.post(f"/api/wissen/themen/{kinematik['id']}/ereignis", json={"art": "quiz", "ergebnis": 2}).status_code == 422
    assert client.get("/api/wissen/ereignisse").json()[0]["thema"] == "Kinematik des Punktes"
    assert client.get(f"/api/wissen/themen/{u['themen'][1]['id']}/abschnitte").json()[0]["fundstelle"].startswith("S. ")
    assert client.delete(f"/api/wissen/themen/{neu['id']}").status_code == 204
    assert client.delete(f"/api/wissen/themen/{neu['id']}").status_code == 404
