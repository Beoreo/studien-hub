"""Prüfungstermine: Import aus TISS/TUWEL, Anmeldung je LVA, eigene Termine, Kalender (Anmeldestart)."""

from datetime import date, datetime

import pytest
from sqlalchemy import select, text

from app.db import eigene_pruefungen_umziehen
from app.models import Lva, LvaTeil, Pruefungstermin, Termin, TuwelKurs
from app.pruefungen import (
    abgleichen,
    abruf_liste,
    angemeldet_setzen,
    angemeldete_termine,
    anmeldestatus,
    ist_angemeldet,
    naechstes_semester,
    termine_der_lva,
)

JETZT = datetime(2026, 10, 24, 12)


@pytest.fixture
def mathe(session):
    lva = Lva(schluessel="104.297", nummer="104.297", titel="Mathematik 1", kurzname="Mathe", semester="2026W", ects=9)
    lva.teile = [LvaTeil(nummer="104.298", typ="UE", gruppe="Gruppe 8"), LvaTeil(nummer="104.297", typ="VO",
                                                                                   tuwel_kurs_id=55)]
    session.add(lva)
    session.commit()
    return lva


def eintrag(nr, start, **kw):
    return {"extern_id": f"tiss:{nr}", "titel": f"Prüfung {nr}", "start": start, "ende": None, "ort": None,
            "anmeldung_von": None, "anmeldung_bis": None, "abmeldung_bis": None, "angemeldet": False, **kw}


# --- reine Logik ------------------------------------------------------------------------------

def test_anmeldestatus_und_semester():
    von, bis = datetime(2026, 12, 1, 8), datetime(2027, 1, 20, 23, 59)
    assert anmeldestatus(von, bis, datetime(2026, 11, 30)) == "bald"
    assert anmeldestatus(von, bis, datetime(2026, 12, 24)) == "offen"
    assert anmeldestatus(von, bis, datetime(2027, 1, 21)) == "vorbei"
    assert anmeldestatus(None, bis, datetime(2026, 1, 1)) == "offen"
    assert anmeldestatus(None, None, JETZT) is None
    assert (naechstes_semester("2026W"), naechstes_semester("2027S")) == ("2027S", "2027W")


def test_automatisch_angemeldet_ueber_tiss_oder_feed_selbst_gewaehlt_geht_vor():
    t = Pruefungstermin(start=datetime(2027, 1, 23, 9), tiss_angemeldet=False, angemeldet=None)
    assert not ist_angemeldet(t, set())
    assert ist_angemeldet(t, {date(2027, 1, 23)})  # Prüfung im TISS-Feed am selben Tag
    t.tiss_angemeldet = True
    assert ist_angemeldet(t, set())
    t.angemeldet = False
    assert not ist_angemeldet(t, {date(2027, 1, 23)})


# --- Abgleich -----------------------------------------------------------------------------------

def test_abgleich_neu_geaendert_entfernt(session, mathe):
    e = abgleichen(session, "tiss", mathe.id, [eintrag(1, datetime(2027, 1, 23, 9)), eintrag(2, datetime(2027, 3, 6, 9))],
                   jetzt=JETZT)
    assert (e.neu, e.geaendert, e.entfernt) == (2, 0, 0)
    e = abgleichen(session, "tiss", mathe.id, [
        eintrag(1, datetime(2027, 1, 23, 9), anmeldung_von=datetime(2026, 12, 1, 8)),  # Frist dazugekommen
        eintrag(3, datetime(2027, 6, 30, 9)),  # neu; 2 fehlt jetzt
    ], jetzt=JETZT)
    assert (e.neu, e.geaendert, e.entfernt, e.unveraendert) == (1, 1, 1, 0)
    assert [t.extern_id for t in termine_der_lva(session, mathe.id)] == ["tiss:1", "tiss:3"]
    assert termine_der_lva(session, mathe.id)[0].anmeldung_von == datetime(2026, 12, 1, 8)
    # unvollständige Liste (eine einzelne Seite aus dem Browser): nichts fällt weg
    e = abgleichen(session, "tiss", mathe.id, [eintrag(1, datetime(2027, 1, 23, 9), anmeldung_von=datetime(2026, 12, 1, 8))],
                   vollstaendig=False)
    assert (e.unveraendert, e.entfernt) == (1, 0)


def test_abgleich_schont_bearbeitete_und_angemeldete(session, mathe):
    abgleichen(session, "tiss", mathe.id, [eintrag(1, datetime(2027, 1, 23, 9)), eintrag(2, datetime(2027, 3, 6, 9)),
                                           eintrag(4, datetime(2027, 6, 1, 9))])
    t1, t2, t4 = termine_der_lva(session, mathe.id)
    t1.start, t1.bearbeitet = datetime(2027, 1, 23, 13), True  # eigene Uhrzeit
    t2.angemeldet = True
    t4.angemeldet = True
    # TISS verschiebt Termin 2 auf 10 Uhr (neue Kennung), Termin 4 fällt ganz weg, Termin 1 kommt um 9 Uhr
    abgleichen(session, "tiss", mathe.id, [eintrag(1, datetime(2027, 1, 23, 9)), eintrag(5, datetime(2027, 3, 6, 10))])
    termine = {t.extern_id: t for t in termine_der_lva(session, mathe.id)}
    assert termine["tiss:1"].start == datetime(2027, 1, 23, 13)  # selbst bearbeitet: Zeit bleibt
    assert "tiss:2" not in termine and termine["tiss:5"].angemeldet is True  # Anmeldung wandert mit
    assert termine["tiss:4"].angemeldet is True  # angemeldet und ohne Ersatz: bleibt


def test_tuwel_termin_am_tag_eines_tiss_termins_ist_derselbe(session, mathe):
    abgleichen(session, "tiss", mathe.id, [eintrag(1, datetime(2027, 1, 23, 9))])
    abgleichen(session, "tuwel", mathe.id, [
        {**eintrag(1, datetime(2027, 1, 23, 9)), "extern_id": "tuwel:77"},
        {**eintrag(2, datetime(2026, 11, 14, 10)), "extern_id": "tuwel:78", "titel": "1. Kurztest"},
    ])
    assert [(t.quelle, t.titel) for t in termine_der_lva(session, mathe.id)] == [("tuwel", "1. Kurztest"), ("tiss", "Prüfung 1")]


def test_angemeldet_setzen_genau_ein_termin(session, mathe):
    abgleichen(session, "tiss", mathe.id, [eintrag(1, datetime(2027, 1, 23, 9)), eintrag(2, datetime(2027, 3, 6, 9))])
    t1, t2 = termine_der_lva(session, mathe.id)
    t1.tiss_angemeldet = True
    assert angemeldete_termine(session, mathe.id) == [t1]
    angemeldet_setzen(session, mathe, t2.id)
    assert angemeldete_termine(session, mathe.id) == [t2]
    angemeldet_setzen(session, mathe, None)
    assert angemeldete_termine(session, mathe.id) == []
    with pytest.raises(ValueError):
        angemeldet_setzen(session, mathe, 9999)


def test_abruf_liste_nummern_semester_und_tuwel_kurse(session, mathe):
    session.add(TuwelKurs(id=77, name="Mathe 1 UE", lva_id=mathe.id))
    session.add(Lva(schluessel="alt", titel="Alt", semester="2025S"))  # anderes Semester: nicht dabei
    session.commit()
    (eintrag_,) = abruf_liste(session)
    assert eintrag_["nummern"] == ["104.297", "104.298"]  # VO zuerst
    assert eintrag_["semester"] == ["2026W", "2027S"]
    assert eintrag_["tuwel_kurse"] == [55, 77]


def test_eigene_pruefungen_werden_umgezogen(session, mathe):
    session.execute(text("UPDATE lva SET eigene_pruefungen = '[\"2027-01-20\", \"2027-01-20\", \"2027-03-01\"]'"))
    session.commit()
    assert eigene_pruefungen_umziehen(session.get_bind()) == 2
    session.expire_all()
    termine = termine_der_lva(session, mathe.id)
    assert [(t.start, t.quelle, t.angemeldet, t.ende) for t in termine] == [
        (datetime(2027, 1, 20, 9), "manuell", True, None), (datetime(2027, 3, 1, 9), "manuell", True, None)]
    assert session.get(Lva, mathe.id).eigene_pruefungen is None
    assert eigene_pruefungen_umziehen(session.get_bind()) == 0  # mehrfach aufrufbar


# --- API ------------------------------------------------------------------------------------------

def kopf(client):
    return {"X-Studienhub-Schluessel": client.get("/api/tuwel/einrichtung").json()["schluessel"]}


def sync(client, quelle, lva_id, termine, **kw):
    return client.post("/api/pruefungen/sync", headers=kopf(client),
                       json={"quelle": quelle, "lvas": [{"lva_id": lva_id, "termine": termine}], **kw})


def iso(t):
    return {k: v.isoformat() if isinstance(v, datetime) else v for k, v in t.items()}


def test_api_import_auswahl_bearbeiten_loeschen(client, session, mathe):
    assert client.post("/api/pruefungen/sync", json={"quelle": "tiss", "lvas": []}).status_code == 401
    assert client.get("/api/pruefungen/abruf", headers=kopf(client)).json()["lvas"][0]["lva_id"] == mathe.id

    termine = [iso(eintrag(1, datetime(2027, 1, 23, 9), ende=datetime(2027, 1, 23, 11),
                           anmeldung_von=datetime(2026, 12, 1, 8), anmeldung_bis=datetime(2027, 1, 20, 23, 59))),
               iso(eintrag(2, datetime(2027, 3, 6, 9), anmeldung_von=datetime(2027, 2, 1, 8)))]
    antwort = sync(client, "tiss", mathe.id, termine, fehler=["Seite X nicht lesbar"]).json()
    assert (antwort["neu"], antwort["fehler"]) == (2, ["Seite X nicht lesbar"])

    uebersicht = client.get("/api/pruefungen").json()
    assert uebersicht["sync"]["tiss"]["termine"] == 2 and uebersicht["sync"]["tuwel"] is None
    (lva,) = uebersicht["lvas"]
    assert lva["angemeldet_id"] is None and [t["anmeldestatus"] for t in lva["termine"]] == ["bald", "bald"]
    t1, t2 = (t["id"] for t in lva["termine"])
    # ohne Anmeldung zählt der nächste Termin als Vorschlag für den Lernbedarf
    assert next(l for l in client.get("/api/lvas").json() if l["id"] == mathe.id)["pruefung_quelle"] == "vorschlag"

    gewaehlt = client.put(f"/api/pruefungen/lva/{mathe.id}/angemeldet", json={"termin_id": t2}).json()
    assert gewaehlt["angemeldet_id"] == t2
    assert [t["angemeldet_automatisch"] for t in gewaehlt["termine"]] == [False, False]
    assert next(l for l in client.get("/api/lvas").json() if l["id"] == mathe.id)["pruefung"].startswith("2027-03-06")
    assert client.put(f"/api/pruefungen/lva/{mathe.id}/angemeldet", json={"termin_id": 9999}).status_code == 422

    # eigene Uhrzeit an einem importierten Termin bleibt beim nächsten Import
    geaendert = client.patch(f"/api/pruefungen/{t1}", json={"start": "2027-01-23T13:00:00", "ende": "2027-01-23T15:00:00"}).json()
    assert geaendert["bearbeitet"] is True
    assert client.patch(f"/api/pruefungen/{t1}", json={"ende": "2027-01-23T12:00:00"}).status_code == 422
    sync(client, "tiss", mathe.id, termine)
    assert session.get(Pruefungstermin, t1).start == datetime(2027, 1, 23, 13)

    # importierte Termine werden nur ausgeblendet und kommen beim Import nicht zurück
    assert client.delete(f"/api/pruefungen/{t1}").status_code == 204
    sync(client, "tiss", mathe.id, termine)
    assert [t["id"] for t in client.get("/api/pruefungen").json()["lvas"][0]["termine"]] == [t2]
    assert client.patch(f"/api/pruefungen/{t1}", json={"titel": "x"}).status_code == 404

    eigener = client.post("/api/pruefungen", json={"lva_id": mathe.id, "titel": "Zwischentest", "start": "2026-11-27T10:00:00",
                                                   "ende": "2026-11-27T11:00:00"})
    assert eigener.status_code == 201 and eigener.json()["angemeldet"] is True
    assert client.post("/api/pruefungen", json={"lva_id": mathe.id, "start": "2026-11-27T10:00:00",
                                                "ende": "2026-11-27T09:00:00"}).status_code == 422
    assert client.delete(f"/api/pruefungen/{eigener.json()['id']}").status_code == 204
    assert session.get(Pruefungstermin, eigener.json()["id"]) is None  # eigene werden gelöscht


def kalender(client, von, bis):
    return client.get("/api/kalender", params={"von": von, "bis": bis}).json()


def test_kalender_anmeldestart_und_angemeldete_pruefung(client, session, mathe):
    termine = [iso(eintrag(1, datetime(2027, 1, 23, 9), ende=datetime(2027, 1, 23, 11), anmeldung_von=datetime(2026, 12, 1, 8))),
               iso(eintrag(2, datetime(2027, 2, 6, 9), ende=datetime(2027, 2, 6, 11), anmeldung_von=datetime(2026, 12, 1, 8))),
               iso(eintrag(3, datetime(2027, 3, 6, 9), ende=datetime(2027, 3, 6, 11), anmeldung_von=datetime(2027, 2, 1, 8)))]
    sync(client, "tiss", mathe.id, termine)
    events = kalender(client, "2026-11-30T00:00:00", "2027-04-01T00:00:00")
    anmeldung = [e for e in events if e["extendedProps"]["art"] == "anmeldung"]
    # ohne Wahl: Anmeldestart aller Termine, je Tag ein Eintrag
    assert [(e["start"], len(e["extendedProps"]["pruefungen"])) for e in anmeldung] == [("2026-12-01", 2), ("2027-02-01", 1)]
    assert anmeldung[0]["allDay"] and anmeldung[0]["title"] == "Anmeldung Mathe"
    assert not [e for e in events if e["extendedProps"]["art"] == "pruefung"]  # nichts angemeldet

    t3 = session.scalar(select(Pruefungstermin).where(Pruefungstermin.extern_id == "tiss:3")).id
    client.put(f"/api/pruefungen/lva/{mathe.id}/angemeldet", json={"termin_id": t3})
    events = kalender(client, "2026-11-30T00:00:00", "2027-04-01T00:00:00")
    assert [e["start"] for e in events if e["extendedProps"]["art"] == "anmeldung"] == ["2027-02-01"]
    (pruefung,) = [e for e in events if e["extendedProps"]["art"] == "pruefung"]
    assert (pruefung["start"], pruefung["end"], pruefung["allDay"]) == ("2027-03-06T09:00:00", "2027-03-06T11:00:00", False)

    # Prüfung steht im TISS-Feed: dort erscheint sie schon als Termin, nicht doppelt
    session.add(Termin(lva_id=mathe.id, typ="PRUEFUNG", titel="Prüfung", start=datetime(2027, 3, 6, 9), ende=datetime(2027, 3, 6, 11)))
    session.commit()
    events = kalender(client, "2026-11-30T00:00:00", "2027-04-01T00:00:00")
    assert not [e for e in events if e["extendedProps"]["art"] == "pruefung"]
    assert [e for e in events if e["extendedProps"]["art"] == "termin" and e["extendedProps"]["pruefung"]]

    # Filter „nur Arbeit“ oder ohne Prüfungen: keine Anmeldungen
    nur_vo = client.get("/api/kalender", params={"von": "2026-11-30T00:00:00", "bis": "2027-04-01T00:00:00", "typ": "VO"}).json()
    assert not [e for e in nur_vo if e["extendedProps"]["art"] == "anmeldung"]
