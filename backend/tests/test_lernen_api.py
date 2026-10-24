"""Wochenplanung über die API: Pflicht → Arbeit → Lernen nach ECTS → Freizeit."""

from datetime import date, datetime, timedelta

import pytest
from fpdf import FPDF

import app.lernaufwand as lernaufwand
from app.models import Dokument, Lva, Termin
from app.planung_service import wochenuebersicht

MONTAG = date(2026, 10, 5)
WOCHE = MONTAG.isoformat()


def regel(**kw):
    basis = {
        "stunden_pro_woche": 16, "tage": [0, 1, 2, 3, 4], "fruehester_beginn": "08:00", "spaetestes_ende": "18:00",
        "min_block_minuten": 120, "max_block_minuten": 480, "puffer_minuten": 30, "min_freie_tage": 1,
        "lern_min_block_minuten": 45, "lern_max_block_minuten": 120, "lern_tage": [0, 1, 2, 3, 4, 5],
        "lernphase_wochen": 12,  # Lernfenster deckt die Testwochen ab Oktober ab
    }
    basis.update(kw)
    return basis


def iso(text: str) -> datetime:
    return datetime.fromisoformat(text)


def ueberschneiden(a: dict, b: dict) -> bool:
    return iso(a["start"]) < iso(b["ende"]) and iso(b["start"]) < iso(a["ende"])


@pytest.fixture
def ordner(tmp_path, monkeypatch):
    monkeypatch.setattr(lernaufwand, "UNTERLAGEN_ORDNER", tmp_path)
    return tmp_path


STANDARD_PRUEFUNG = datetime(2026, 12, 16, 9)  # Mittwoch der Woche 10; gelernt wird nur im Fenster davor


def lva_mit_semester(session, titel, kurz, ects=6, wochen=10, pruefung: datetime | None = STANDARD_PRUEFUNG, tag_vo=0):
    """VO jeden `tag_vo` 10–12 Uhr über `wochen` Wochen ab MONTAG, optional Prüfung aus TISS."""
    lva = Lva(schluessel=titel.casefold(), titel=titel, kurzname=kurz, semester="2026W", ects=ects)
    session.add(lva)
    session.flush()
    for w in range(wochen):
        start = datetime.combine(MONTAG + timedelta(weeks=w, days=tag_vo), datetime.min.time()) + timedelta(hours=10)
        session.add(Termin(lva_id=lva.id, typ="VO", titel=f"{kurz} VO", start=start, ende=start + timedelta(hours=2)))
    if pruefung:
        session.add(Termin(lva_id=lva.id, typ="PRUEFUNG", titel=f"Prüfung {kurz}", start=pruefung,
                           ende=pruefung + timedelta(hours=2)))
    session.commit()
    return lva


def folien(session, ordner, lva, name, erschienen, seiten=30, cm=1):
    datei = FPDF(orientation="L")
    for _ in range(seiten):
        datei.add_page()
    datei.output(str(ordner / name))
    doc = Dokument(lva_id=lva.id, tuwel_kurs_id=1, tuwel_cm_id=cm, schluessel=name, dateiname=name, typ="pdf",
                   ist_link=False, quelle_url=name, pfad=name, erschienen_am=erschienen, erschienen_quelle="tuwel")
    session.add(doc)
    session.commit()
    return doc


@pytest.fixture
def ep1(session, ordner):
    lva = lva_mit_semester(session, "Einführung in die Programmierung", "EP1")
    folien(session, ordner, lva, "vo1.pdf", datetime(2026, 10, 5, 9))
    return lva


def bedarf_von(antwort, name):
    return next(b for b in antwort["lernbedarf"] if b["lva_name"] == name)


# --- Reihenfolge ---------------------------------------------------------------------------------

def test_arbeit_voll_dann_lernen_bis_zum_wochenbedarf(client, ep1):
    client.put("/api/arbeit/regel", json=regel())
    v = client.post("/api/arbeit/vorschlag", params={"woche": WOCHE}).json()

    # 2. Arbeit: die Wochenstunden sind Pflicht
    assert v["verplant_stunden"] == 16 and v["fehlende_stunden"] == 0
    # 3. Lernen: genau der Wochenbedarf aus den ECTS – (150 h − 20 h VO) × 0,7 × 0,8 über 10 Wochen
    b = bedarf_von(v, "EP1")
    assert b["gesamt_minuten"] == round(130 * 60 * 0.56) and not b["ohne_ects"]
    lern_minuten = sum(x["geplante_minuten"] for x in v["lernbloecke"])
    assert abs(lern_minuten - b["soll_minuten"]) <= 30 and b["geplant_minuten"] == lern_minuten
    assert v["konflikte"] == [] and v["lern_offen_stunden"] == 0
    for a in v["bloecke"]:
        assert not any(ueberschneiden(a, l) for l in v["lernbloecke"])
    assert v["begruendungen"][-1].startswith("Lernen EP1")
    # die Unterlage bestimmt nur den Stoff des Blocks
    assert any(x["thema"] == "vo1.pdf" for x in v["lernbloecke"])

    events = client.get("/api/kalender", params={"von": "2026-10-05T00:00:00", "bis": "2026-10-12T00:00:00"}).json()
    lern_events = [e for e in events if e["extendedProps"].get("art") == "lernen"]
    assert len(lern_events) == len(v["lernbloecke"]) and "vorschlag" in lern_events[0]["classNames"]


def test_ohne_ects_keine_lernzeit_aber_hinweis(client, ep1, session):
    ep1.ects = None
    session.commit()
    client.put("/api/arbeit/regel", json=regel())
    v = client.post("/api/arbeit/vorschlag", params={"woche": WOCHE}).json()
    assert v["lernbloecke"] == [] and v["verplant_stunden"] == 16
    assert any("EP1: keine ECTS" in h for h in v["hinweise"])


# --- Erster Sync mit vielen alten Unterlagen -------------------------------------------------------

def test_erster_sync_mit_vielen_alten_unterlagen(client, session, ordner):
    lva = lva_mit_semester(session, "Mechanik 1", "Mech", wochen=12)
    # 40 Foliensätze aus den ersten fünf Wochen (je 30 Folien = 60 min Stoff), Hub kommt erst in Woche 5 dazu
    for i in range(40):
        folien(session, ordner, lva, f"vo{i:02}.pdf", datetime(2026, 10, 5, 9) + timedelta(days=i * 35 // 40), cm=i + 1)
    client.put("/api/arbeit/regel", json=regel())
    woche5 = (MONTAG + timedelta(weeks=5)).isoformat()
    v = client.post("/api/arbeit/vorschlag", params={"woche": woche5}).json()

    # Arbeit bleibt vollständig, die Lernzeit ist der normale Wochenanteil – nicht 40 Stunden Rückstand
    assert v["verplant_stunden"] == 16 and v["konflikte"] == []
    b = bedarf_von(v, "Mech")
    assert b["rueckstand_minuten"] == 0  # Wochen vor dem Hub zählen nicht als Rückstand
    lern = sum(x["geplante_minuten"] for x in v["lernbloecke"])
    assert lern <= b["plan_minuten"] + 30 and lern < 8 * 60
    # Stoff: 2400 min verteilt auf die 6 Wochen bis zur Prüfungswoche, älteste zuerst
    abgedeckt = sum(sum(x["zuteilung"].values()) for x in v["lernbloecke"])
    assert abgedeckt == pytest.approx(2400 / 6, abs=len(v["lernbloecke"]) + 1)
    assert v["lernbloecke"][0]["thema"].startswith("vo00.pdf")

    # Nächste Woche: der nächste Teil des alten Stoffs, nichts doppelt
    bestaetigt = client.post("/api/arbeit/bestaetigen", params={"woche": woche5}).json()["bestaetigt"]
    assert bestaetigt > 0
    v2 = client.post("/api/arbeit/vorschlag", params={"woche": (MONTAG + timedelta(weeks=6)).isoformat()}).json()
    themen_vorher = {d for x in v["lernbloecke"] for d in x["zuteilung"]}
    themen_jetzt = {d for x in v2["lernbloecke"] for d in x["zuteilung"]}
    assert len(themen_vorher & themen_jetzt) <= 1  # höchstens die angefangene Unterlage
    assert sum(sum(x["zuteilung"].values()) for x in v2["lernbloecke"]) == pytest.approx((2400 - abgedeckt) / 5, abs=6)


# --- Prüfungswoche ---------------------------------------------------------------------------------

def test_pruefungswoche(client, session, ordner):
    pruefung = datetime(2026, 12, 9, 9)  # Mittwoch der Woche 9
    lva = lva_mit_semester(session, "Mathematik 1", "Mathe", pruefung=pruefung)
    folien(session, ordner, lva, "kap1.pdf", datetime(2026, 10, 5, 9))
    client.put("/api/arbeit/regel", json=regel(stunden_pro_woche=12))
    woche = date(2026, 12, 7).isoformat()

    normal = client.get("/api/lernen/bedarf", params={"woche": "2026-10-12"}).json()[0]
    v = client.post("/api/arbeit/vorschlag", params={"woche": woche}).json()
    b = bedarf_von(v, "Mathe")
    assert b["lernphase"] and b["pruefung"] == "2026-12-09"
    # jede Woche im Lernfenster zählt gleich; am 8.12. (Mariä Empfängnis) ist einer von sechs Lerntagen gesperrt
    assert b["plan_minuten"] == pytest.approx(normal["plan_minuten"] * 5 / 6, abs=3)

    # Lernen nur vor der Prüfung, Arbeit trotzdem vollständig
    assert v["lernbloecke"] and all(iso(x["ende"]) <= pruefung for x in v["lernbloecke"])
    assert v["verplant_stunden"] == 12
    assert any("Lernphase" in t for t in v["begruendungen"])
    # passt nicht alles vor die Prüfung, wird es gemeldet statt still gekürzt
    gemeldet = sum(r["fehlend_minuten"] for r in v["rueckstaende"])
    assert sum(x["geplante_minuten"] for x in v["lernbloecke"]) + gemeldet >= b["soll_minuten"] - 30

    # Kalender und Wochenübersicht zeigen die Prüfung deutlich
    events = client.get("/api/kalender", params={"von": "2026-12-07T00:00:00", "bis": "2026-12-14T00:00:00"}).json()
    pruef = next(e for e in events if e["extendedProps"].get("pruefung"))
    assert "Prüfung" in pruef["title"] and "pruefung" in pruef["classNames"]
    uebersicht = wochenuebersicht(session, date(2026, 12, 7), heute=date(2026, 12, 7))
    (countdown,) = uebersicht["pruefungen"]
    assert (countdown["lva_name"], countdown["tage"], countdown["in_dieser_woche"], countdown["quelle"]) == ("Mathe", 2, True, "tiss")

    # nach der Prüfung: kein Lernbedarf mehr
    assert client.get("/api/lernen/bedarf", params={"woche": "2026-12-14"}).json() == []


# --- Konflikte -----------------------------------------------------------------------------------

def test_konflikt_kuerzt_lernen_mit_ferner_pruefung_nie_die_arbeit(client, session, ordner):
    nah = lva_mit_semester(session, "Analysis", "Ana", ects=1, pruefung=datetime(2026, 10, 16, 9), wochen=2)
    fern = lva_mit_semester(session, "Mechanik", "Mech", pruefung=datetime(2027, 1, 29, 9), wochen=10, tag_vo=1)
    # nur Mo/Di 8–17 Uhr: VO und 8 h Arbeit lassen kaum Platz zum Lernen
    client.put("/api/arbeit/regel", json=regel(stunden_pro_woche=8, tage=[0, 1], lern_tage=[0, 1], spaetestes_ende="17:00",
                                               min_block_minuten=60, lernphase_wochen=20))
    v = client.post("/api/arbeit/vorschlag", params={"woche": WOCHE}).json()

    assert v["verplant_stunden"] == 8 and v["fehlende_stunden"] == 0  # Arbeit nie gekürzt
    gelernt = {lva_id: sum(x["geplante_minuten"] for x in v["lernbloecke"] if x["lva_id"] == lva_id) for lva_id in (nah.id, fern.id)}
    assert bedarf_von(v, "Ana")["lernphase"] and bedarf_von(v, "Mech")["lernphase"]  # beide im Lernfenster
    # die knappe Lernzeit geht an die LVA mit näherer Prüfung, Mechanik wird zuerst gekürzt
    assert gelernt[nah.id] >= 180 and gelernt[fern.id] == 0
    (r,) = [r for r in v["rueckstaende"] if r["lva_name"] == "Mech"]
    assert r["fehlend_minuten"] == bedarf_von(v, "Mech")["soll_minuten"]
    assert r["nachholen_pro_woche_minuten"] > 0 and r["bis"] == "2027-01-29"
    assert "hinter dem Plan" in r["text"] and "nachzuholen bis zur Prüfung am 29.01." in r["text"]


# --- Bearbeiten: verschieben, löschen, fixieren ---------------------------------------------------

def test_verschieben_loeschen_fixieren_plant_nur_den_rest(client, ep1):
    client.put("/api/arbeit/regel", json=regel())
    v = client.post("/api/arbeit/vorschlag", params={"woche": WOCHE}).json()
    soll = bedarf_von(v, "EP1")["soll_minuten"]

    # Lernblock verschieben: gilt als fix, die übrigen Vorschläge werden darum herum neu geplant
    block = v["lernbloecke"][0]
    verschoben = client.patch(f"/api/lernen/bloecke/{block['id']}",
                              json={"start": "2026-10-10T09:00:00", "ende": "2026-10-10T10:30:00"}).json()
    assert verschoben["status"] == "bestaetigt" and verschoben["geplante_minuten"] == 90
    lernen = client.get("/api/lernen/bloecke").json()
    assert abs(sum(b["geplante_minuten"] for b in lernen) - soll) <= 30  # Bedarf bleibt gleich, nicht doppelt
    assert sum(1 for b in lernen if b["status"] == "bestaetigt") == 1

    # Arbeitsvorschlag löschen: der Platz bleibt frei, die Stunden landen woanders
    arbeit = [b for b in client.get("/api/arbeit/bloecke").json() if b["status"] == "vorschlag"]
    geloescht = arbeit[0]
    assert client.delete(f"/api/arbeit/bloecke/{geloescht['id']}").status_code == 204
    neu = client.get("/api/arbeit/bloecke").json()
    assert sum(b["dauer_stunden"] for b in neu) == 16
    assert not any(ueberschneiden(geloescht, b) for b in neu)

    # Fixieren: bleibt beim nächsten Neuplanen unverändert
    fix = neu[0]
    assert client.patch(f"/api/arbeit/bloecke/{fix['id']}", json={"status": "bestaetigt"}).json()["status"] == "bestaetigt"
    client.post("/api/arbeit/vorschlag", params={"woche": WOCHE})
    nach = {b["id"]: b for b in client.get("/api/arbeit/bloecke").json()}
    assert nach[fix["id"]]["start"] == fix["start"] and nach[fix["id"]]["status"] == "bestaetigt"

    # Woche verwerfen: Vorschläge weg, auch verworfene Plätze sind wieder frei
    client.post("/api/arbeit/verwerfen", params={"woche": WOCHE})
    assert all(b["status"] == "bestaetigt" for b in client.get("/api/arbeit/bloecke").json())


def test_ohne_vorschlag_kein_ungefragtes_neuplanen(client, ep1):
    client.put("/api/arbeit/regel", json=regel())
    fix = client.post("/api/arbeit/bloecke", json={"start": "2026-10-06T08:00:00", "ende": "2026-10-06T12:00:00"}).json()
    client.patch(f"/api/arbeit/bloecke/{fix['id']}", json={"start": "2026-10-06T09:00:00", "ende": "2026-10-06T13:00:00"})
    assert client.get("/api/lernen/bloecke").json() == []
    assert len(client.get("/api/arbeit/bloecke").json()) == 1


def test_lernblock_validierung_und_doppeltes_loeschen(client, ep1):
    client.put("/api/arbeit/regel", json=regel())
    block = client.post("/api/arbeit/vorschlag", params={"woche": WOCHE}).json()["lernbloecke"][0]
    assert client.patch(f"/api/lernen/bloecke/{block['id']}", json={"ende": "2026-10-04T15:00:00"}).status_code == 422
    assert client.patch(f"/api/lernen/bloecke/{block['id']}", json={"tatsaechliche_minuten": -5}).status_code == 422
    assert client.delete(f"/api/lernen/bloecke/{block['id']}").status_code == 204
    assert client.delete("/api/lernen/bloecke/9999").status_code == 404


def test_eingetragene_zeit_zaehlt_als_gelernt(client, ep1):
    client.put("/api/arbeit/regel", json=regel())
    v = client.post("/api/arbeit/vorschlag", params={"woche": WOCHE}).json()
    for b in v["lernbloecke"]:  # nichts gelernt
        client.patch(f"/api/lernen/bloecke/{b['id']}", json={"tatsaechliche_minuten": 0})
    naechste = client.get("/api/lernen/bedarf", params={"woche": "2026-10-12"}).json()[0]
    assert naechste["rueckstand_minuten"] > 0 and naechste["soll_minuten"] > naechste["plan_minuten"]


# --- Einstellungen je LVA und Regel -----------------------------------------------------------------

def test_lva_ziel_regler_und_eigene_pruefung(client, ep1):
    client.put("/api/arbeit/regel", json=regel())
    start = next(l for l in client.get("/api/lvas").json() if l["id"] == ep1.id)
    assert (start["ziel"], start["bedarf_faktor"], start["pruefung"], start["pruefung_quelle"]) == (
        "normal", 1.0, "2026-12-16T09:00:00", "tiss")
    assert start["gesamtbedarf_minuten"] == round(130 * 60 * 0.56) and start["wochenbedarf_minuten"] > 0

    gut = client.patch(f"/api/lvas/{ep1.id}", json={"ziel": "gut"}).json()
    assert gut["gesamtbedarf_minuten"] == round(130 * 60 * 0.7)
    weniger = client.patch(f"/api/lvas/{ep1.id}", json={"bedarf_faktor": 0.5}).json()
    assert weniger["gesamtbedarf_minuten"] == round(130 * 60 * 0.7 * 0.5)
    assert weniger["wochenbedarf_minuten"] < gut["wochenbedarf_minuten"]

    ids = [client.post("/api/pruefungen", json={"lva_id": ep1.id, "start": tag}).json()["id"]
           for tag in ("2027-01-29T09:00:00", "2026-12-01T09:00:00")]
    mit_pruefung = next(l for l in client.get("/api/lvas").json() if l["id"] == ep1.id)
    assert mit_pruefung["pruefung_quelle"] == "manuell" and mit_pruefung["pruefung"].startswith("2026-12-01")
    events = client.get("/api/kalender", params={"von": "2026-11-30T00:00:00", "bis": "2027-02-01T00:00:00"}).json()
    eigene = [e for e in events if e["extendedProps"].get("art") == "pruefung"]
    assert [e["start"] for e in eigene] == ["2026-12-01", "2027-01-29"]  # ohne Uhrzeit-Ende: ganztägig
    assert all(e["allDay"] and e["title"] == "Prüfung EP1" for e in eigene)
    assert len({e["id"] for e in eigene}) == 2

    for i in ids:
        assert client.delete(f"/api/pruefungen/{i}").status_code == 204
    ohne = next(l for l in client.get("/api/lvas").json() if l["id"] == ep1.id)
    assert ohne["pruefung"].startswith("2026-12-16")  # wieder die aus dem TISS-Feed

    assert client.patch(f"/api/lvas/{ep1.id}", json={"ziel": "perfekt"}).status_code == 422
    assert client.patch(f"/api/lvas/{ep1.id}", json={"bedarf_faktor": 5}).status_code == 422


def test_regel_mit_lerneinstellungen(client):
    gespeichert = client.put("/api/arbeit/regel", json=regel(ects_faktor=0.6, lernphase_wochen=3)).json()
    assert gespeichert["ects_faktor"] == 0.6 and gespeichert["lernphase_wochen"] == 3
    assert client.get("/api/arbeit/regel").json()["ects_faktor"] == 0.6
    standard = client.put("/api/arbeit/regel", json={k: v for k, v in regel().items() if k != "lernphase_wochen"}).json()
    assert (standard["ects_faktor"], standard["lernphase_wochen"]) == (0.7, 2)
    assert client.put("/api/arbeit/regel", json=regel(ects_faktor=0)).status_code == 422
    assert client.put("/api/arbeit/regel", json=regel(lernphase_wochen=21)).status_code == 422
    assert client.put("/api/arbeit/regel", json=regel(lern_tage=[9])).status_code == 422


def test_wochenuebersicht_balken(client, ep1):
    client.put("/api/arbeit/regel", json=regel())
    v = client.post("/api/arbeit/vorschlag", params={"woche": WOCHE}).json()
    u = client.get("/api/planung/woche", params={"woche": "2026-10-07"}).json()
    s = u["stunden"]
    assert u["woche"] == WOCHE and s["arbeit"] == 16 and s["arbeit_soll"] == 16 and s["vorschlaege"]
    assert s["uni"] == 2  # eine VO
    assert s["lernen"] == round(sum(x["geplante_minuten"] for x in v["lernbloecke"]) / 60, 1)
    assert s["uni"] + s["arbeit"] + s["lernen"] + s["freizeit"] == pytest.approx(s["wach"], abs=0.2)
    assert u["lernstand"][0]["lva_name"] == "EP1"


def test_unterlage_nicht_lernen_aendert_nur_den_stoff(client, ep1, session):
    doc = session.query(Dokument).one()
    eintrag = next(d for d in client.get("/api/tuwel/dokumente").json() if d["id"] == doc.id)
    assert (eintrag["lernart"], eintrag["seiten"], eintrag["lern_minuten_geschaetzt"]) == ("folien", 30, 60)
    client.patch(f"/api/tuwel/dokumente/{doc.id}", json={"lern_minuten": 0})
    client.put("/api/arbeit/regel", json=regel())
    v = client.post("/api/arbeit/vorschlag", params={"woche": WOCHE}).json()
    assert v["lernbloecke"]  # Lernzeit kommt aus den ECTS
    assert all(b["thema"] == "Prüfungsvorbereitung" and b["zuteilung"] == {} for b in v["lernbloecke"])
