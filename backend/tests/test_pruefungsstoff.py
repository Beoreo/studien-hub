"""Prüfungsstoff: Themen aus Stoffliste/Skript/Folien, Themen je Prüfung, Zeitstrahl im Wissensstand, Upload."""

from datetime import date, datetime, timedelta

import pytest

from app.extraktion import Gliederungspunkt, Text
from app.models import Lva, Pruefungsstoff, Termin, Thema
from app.pruefungsstoff import themen_aus_text, titel_bereinigen, zeitabschnitte
from app.themen import ereignis_eintragen, stoff_uebernehmen, uebersicht

HEUTE = date(2026, 11, 1)


# --- Themen aus dem Stoff (reine Logik) ----------------------------------------------------------------

def test_titel_bereinigen():
    assert [titel_bereinigen(z) for z in ("2.3 Reibung", "- Haftung und Gleiten:", "b) Seilreibung", "• Kapitel 4 Kinematik",
                                           "Schwerpunkt ........ 23")] == [
        "Reibung", "Haftung und Gleiten", "Seilreibung", "Kinematik", "Schwerpunkt"]


def test_stoffliste_jede_zeile_ein_thema():
    text = Text(seiten=[(1, "Prüfungsstoff:\n1. Kräfte und Momente\n2. Gleichgewicht\n- Reibung\n\n- Reibung\n3/12\nSchwerpunkt")])
    assert themen_aus_text(text) == ["Kräfte und Momente", "Gleichgewicht", "Reibung", "Schwerpunkt"]


def test_skript_mit_gliederung_oberste_ebene():
    gliederung = [Gliederungspunkt(1, "1 Statik", 1), Gliederungspunkt(2, "1.1 Kräfte", 2), Gliederungspunkt(1, "2 Kinematik", 9),
                  Gliederungspunkt(1, "3 Kinetik", 20), Gliederungspunkt(2, "3.1 Impuls", 21)]
    assert themen_aus_text(Text(seiten=[(1, "x")], gliederung=gliederung)) == ["Statik", "Kinematik", "Kinetik"]
    # nur zwei Kapitel: Unterkapitel kommen dazu
    zwei = [Gliederungspunkt(1, "1 Statik", 1), Gliederungspunkt(2, "1.1 Kräfte", 2), Gliederungspunkt(1, "2 Kinematik", 9)]
    assert themen_aus_text(Text(gliederung=zwei)) == ["Statik", "Kräfte", "Kinematik"]


def test_folien_titel_ohne_kopfzeilen():
    folien = [(1, "Mechanik 1\nWS 2026")] + [(i, f"Mechanik 1\nx") for i in range(2, 8)]
    folien += [(8, "Reibung\nHaftung"), (9, "Agenda\n…"), (10, "Seilreibung\nEuler"), (11, "Reibung\nnoch mehr")]
    assert themen_aus_text(Text(seiten=folien, art="folien")) == ["Reibung", "Seilreibung"]


def test_zeitabschnitte_bis_zu_jeder_pruefung():
    a, b = zeitabschnitte(date(2026, 10, 1), [date(2026, 12, 1), date(2026, 11, 1)], HEUTE)
    assert (a.von, a.bis, a.vorbei, a.zeit_anteil) == (date(2026, 10, 1), date(2026, 11, 1), False, 1.0)
    assert (b.von, b.bis, b.zeit_anteil) == (date(2026, 11, 2), date(2026, 12, 1), 0.0)
    assert zeitabschnitte(date(2026, 10, 1), [], HEUTE) == []


# --- Datenbank ----------------------------------------------------------------------------------------

@pytest.fixture
def mech(session):
    lva = Lva(schluessel="309.019", nummer="309.019", titel="Mechanik 1", typ="VO", semester="2026W")
    session.add(lva)
    session.flush()
    session.add(Termin(lva_id=lva.id, typ="VO", titel="VO", start=datetime(2026, 10, 5, 9), ende=datetime(2026, 10, 5, 11)))
    for tag in (date(2026, 11, 20), date(2027, 1, 29)):
        start = datetime.combine(tag, datetime.min.time()) + timedelta(hours=9)
        session.add(Termin(lva_id=lva.id, typ="PRUEFUNG", titel="Prüfung", start=start, ende=start + timedelta(hours=2)))
    session.commit()
    return lva


def test_stoff_bestimmt_die_themen_der_pruefung(session, mech):
    allgemein = Thema(lva_id=mech.id, titel="Statik", reihenfolge=1, quelle="auto")
    session.add(allgemein)
    session.commit()
    test1 = date(2026, 11, 20)
    assert stoff_uebernehmen(session, mech, test1, ["Statik", "Reibung", "Schwerpunkt"]) == {"neu": 2, "zugeordnet": 1, "entfernt": 0}
    themen = {t.titel: t for t in session.query(Thema)}
    assert themen["Statik"].pruefungen == ["2026-11-20"] and themen["Reibung"].quelle == "stoff"

    # Lernstand bleibt; neuer Stoff ersetzt die Zuordnung
    ereignis_eintragen(session, themen["Schwerpunkt"], "selbsteinschaetzung", stufe=3, heute=HEUTE)
    ergebnis = stoff_uebernehmen(session, mech, test1, ["Statik", "Kinematik"])
    assert ergebnis == {"neu": 1, "zugeordnet": 0, "entfernt": 2}
    session.expire_all()
    themen = {t.titel: t for t in session.query(Thema)}
    assert "Reibung" not in themen  # aus dem Stoff, ohne Lernstand: weg
    assert themen["Schwerpunkt"].pruefungen == []  # Lernstand bleibt, aber keiner Prüfung mehr zugeordnet


def test_zeitstrahl_in_der_uebersicht(session, mech):
    session.add_all([Thema(lva_id=mech.id, titel="Statik", reihenfolge=1), Thema(lva_id=mech.id, titel="Dynamik", reihenfolge=2)])
    session.commit()
    stoff_uebernehmen(session, mech, date(2026, 11, 20), ["Reibung"])
    reibung = session.query(Thema).filter_by(titel="Reibung").one()
    ereignis_eintragen(session, reibung, "selbsteinschaetzung", stufe=2, heute=HEUTE)

    (lva,) = uebersicht(session, lva_ids={mech.id}, heute=HEUTE)
    erster, zweiter = lva["zeitstrahl"]
    namen = {t["id"]: t["titel"] for t in lva["themen"]}
    assert (erster["datum"], erster["von"], erster["vorbei"]) == (date(2026, 11, 20), date(2026, 10, 5), False)
    assert [namen[i] for i in erster["themen"]] == ["Reibung"] and erster["fortschritt"] == 0.5
    # zweite Prüfung ohne eigenen Stoff: die allgemeinen Themen
    assert [namen[i] for i in zweiter["themen"]] == ["Statik", "Dynamik"] and zweiter["fortschritt"] == 0
    assert zweiter["von"] == date(2026, 11, 21) and 0 < erster["zeit_anteil"] < 1


def test_upload_api(client, session, mech, tmp_path, monkeypatch):
    import app.routers.wissen as wissen

    monkeypatch.setattr(wissen, "UNTERLAGEN_ORDNER", tmp_path)
    stoffliste = "Stoff für den 1. Test:\n- Kräfte\n- Reibung\n- Schwerpunkt\n".encode()
    antwort = client.post("/api/wissen/stoff", data={"lva_id": mech.id, "pruefung_am": "2026-11-20"},
                          files={"datei": ("Stoff Test 1.txt", stoffliste, "text/plain")})
    assert antwort.status_code == 201
    daten = antwort.json()
    assert daten["themen"] == ["Kräfte", "Reibung", "Schwerpunkt"] and daten["neu"] == 3
    gespeichert = session.get(Pruefungsstoff, daten["stoff"]["id"])
    assert (tmp_path / gespeichert.pfad).read_bytes() == stoffliste
    assert client.get(f"/api/wissen/stoff/{gespeichert.id}/datei").content == stoffliste

    uebersicht_ = client.get("/api/wissen/uebersicht").json()
    (lva,) = [l for l in uebersicht_ if l["lva_id"] == mech.id]
    assert lva["zeitstrahl"][0]["stoff"][0]["dateiname"] == "Stoff Test 1.txt" and len(lva["zeitstrahl"][0]["themen"]) == 3

    # neuer Stoff ersetzt den alten; falsches Format und leere Datei werden abgelehnt
    neu = client.post("/api/wissen/stoff", data={"lva_id": mech.id, "pruefung_am": "2026-11-20"},
                      files={"datei": ("neu.md", b"- Kinematik\n", "text/markdown")}).json()
    assert session.query(Pruefungsstoff).count() == 1 and not (tmp_path / gespeichert.pfad).exists()
    assert client.post("/api/wissen/stoff", data={"lva_id": mech.id, "pruefung_am": "2026-11-20"},
                       files={"datei": ("bild.png", b"x", "image/png")}).status_code == 422
    assert client.post("/api/wissen/stoff", data={"lva_id": mech.id, "pruefung_am": "2026-11-20"},
                       files={"datei": ("leer.txt", b"\n\n", "text/plain")}).status_code == 422
    assert client.post("/api/wissen/stoff", data={"lva_id": 999, "pruefung_am": "2026-11-20"},
                       files={"datei": ("x.txt", b"- A\n", "text/plain")}).status_code == 404

    assert client.delete(f"/api/wissen/stoff/{neu['stoff']['id']}").status_code == 204
    assert session.query(Pruefungsstoff).count() == 0
    session.expire_all()
    assert session.query(Thema).filter_by(titel="Kinematik").count() == 0  # aus dem Stoff, ohne Lernstand
