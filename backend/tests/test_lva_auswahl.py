"""Kursauswahl nach STEOP-Status, manuelles Ein-/Ausblenden und Löschen aller Arbeitsvorschläge."""

from datetime import date, datetime, timedelta

import pytest

from app.lva_auswahl import (
    Auswahl,
    Kandidat,
    aktuelles_semester,
    auffuellen,
    besuchte_lva_ids,
    semester_am,
    setze_steop_abgeschlossen,
    variante_aendern,
)
from app.models import Arbeitsblock, Lernblock, Lva, LvaTeil, Termin, lies_einstellung
from app.planung_service import auswahl_geaendert, schlage_woche_vor

MONTAG = date(2026, 10, 5)
WOCHE = MONTAG.isoformat()


def regel(**kw):
    basis = {"stunden_pro_woche": 16, "tage": [0, 1, 2, 3, 4], "fruehester_beginn": "08:00", "spaetestes_ende": "18:00",
             "min_block_minuten": 120, "max_block_minuten": 480, "min_freie_tage": 0}
    basis.update(kw)
    return basis


@pytest.fixture
def semester(session):
    """Mathe (STEOP über die UE), Makro (keine STEOP) – jeweils Mo–Fr Termine; STEOP noch nicht abgeschlossen."""
    setze_steop_abgeschlossen(session, False)

    def lva(titel, teile):
        l = Lva(schluessel=titel.casefold(), titel=titel, semester="2026W", ects=6)
        session.add(l)
        session.flush()
        for typ, steop in teile:
            session.add(LvaTeil(lva=l, typ=typ, steop=steop))
        for w in range(10):
            for tag in range(5):  # jeden Werktag 8–10 Uhr
                start = datetime.combine(MONTAG + timedelta(weeks=w, days=tag), datetime.min.time()) + timedelta(hours=8)
                session.add(Termin(lva_id=l.id, typ="VO", titel=f"{titel} VO", start=start, ende=start + timedelta(hours=2),
                                   anwesenheit_abweichung=True))
        # Prüfung in der ersten Woche: gelernt wird nur im Fenster vor Prüfungen
        session.add(Termin(lva_id=l.id, typ="PRUEFUNG", titel=f"{titel} Prüfung", start=datetime(2026, 10, 9, 14),
                           ende=datetime(2026, 10, 9, 16)))
        return l

    mathe = lva("Mathematik 1", [("VO", False), ("UE", True)])
    makro = lva("Makroökonomie", [("VO", False)])
    session.commit()
    return {"mathe": mathe, "makro": makro}


def test_auswahl_nach_abschluss_und_manuelle_wahl():
    frei = Lva(id=1, titel="B", steop=False, besuchen=None)
    frei.teile = [LvaTeil(steop=False)]
    assert Auswahl(fertig=True).besucht(frei)  # nach Abschluss: alle
    assert not Auswahl(fertig=False, variante=set()).besucht(frei)  # offen: nur die Variante
    assert Auswahl(fertig=False, variante={1}).besucht(frei)
    frei.besuchen = False
    assert not Auswahl(fertig=True).besucht(frei)  # manuell ausgeblendet nach Abschluss
    assert Auswahl(fertig=False, variante={1}).besucht(frei)  # solange offen zählt nur die Variante


def k(id, ects, steop, titel=None):
    return Kandidat(id, titel or f"L{id}", ects, steop)


def test_auffuellen_bis_zu_den_erlaubten_ects():
    kandidaten = [k(1, 6, True), k(10, 6, False), k(11, 5, False), k(12, 4.5, False), k(13, None, False)]
    # Budget 10: 5 + 4,5 = 9,5 schlägt 6 allein; STEOP-LVAs gehören nicht dazu, ohne ECTS bleibt draußen
    assert auffuellen(kandidaten, 10) == {11, 12}
    assert auffuellen(kandidaten, 22) == {10, 11, 12}
    assert auffuellen(kandidaten, 4) == set()
    assert auffuellen(kandidaten, None) == set()
    assert auffuellen(kandidaten, 6) == {10}  # Gleichstand (6): die zuerst gefundene Auswahl


def test_api_zeigt_auswahl_und_variante_bearbeiten(client, semester):
    lvas = {l["titel"]: l for l in client.get("/api/lvas").json()}
    assert (lvas["Mathematik 1"]["besucht"], lvas["Mathematik 1"]["ist_steop"]) == (True, True)
    assert lvas["Makroökonomie"]["besucht"] is False  # ohne erlaubte Non-STEOP-ECTS nur STEOP
    status = client.get("/api/lvas/steop").json()
    assert status["abgeschlossen"] is False and not status["variante_bearbeitet"]
    assert (status["steop_gesamt"], status["steop_gewaehlt"], status["semester"]) == (1, 1, "2026W")

    # Variante bearbeiten: Makro aufnehmen – mehr als erlaubt wird gemeldet
    makro = semester["makro"].id
    status = client.put(f"/api/lvas/steop/variante/{makro}", json={"enthalten": True}).json()
    assert status["variante_bearbeitet"] and status["vorgezogen_ects"] == 6 and status["warnungen"]
    assert next(l for l in client.get("/api/lvas").json() if l["id"] == makro)["besucht"]

    # Mathe herausnehmen: ohne Kriterien aus TISS fehlt eine STEOP-LVA
    status = client.put(f"/api/lvas/steop/variante/{semester['mathe'].id}", json={"enthalten": False}).json()
    assert status["steop_gewaehlt"] == 0 and any("STEOP-LVAs" in w for w in status["warnungen"])

    # neu erzeugen: wieder automatisch
    status = client.post("/api/lvas/steop/variante").json()
    assert not status["variante_bearbeitet"] and status["steop_gewaehlt"] == 1 and not status["warnungen"]

    # erlaubte ECTS von Hand: Makro kommt in die erzeugte Variante
    status = client.put("/api/lvas/steop", json={"erlaubte_ects": 6}).json()
    assert (status["erlaubte_ects"], status["erlaubte_ects_quelle"]) == (6, "manuell")
    assert all(l["besucht"] for l in client.get("/api/lvas").json())

    # STEOP abgeschlossen: alles wird besucht, Variante bearbeiten nicht mehr möglich
    client.put("/api/lvas/steop", json={"erlaubte_ects": None})
    status = client.put("/api/lvas/steop", json={"abgeschlossen": True}).json()
    assert (status["abgeschlossen"], status["quelle"]) == (True, "manuell")
    assert all(l["besucht"] for l in client.get("/api/lvas").json())
    assert client.put(f"/api/lvas/steop/variante/{makro}", json={"enthalten": False}).status_code == 409


def test_steop_markierung_aendert_erzeugte_variante(client, semester):
    teil = semester["makro"].teile[0].id
    client.patch(f"/api/lvas/teile/{teil}", json={"steop": True})
    assert all(l["besucht"] for l in client.get("/api/lvas").json())  # ohne Kriterien: alle STEOP-LVAs


def test_variante_aus_den_tiss_kriterien(client, session, semester):
    """P1: 6 ECTS aus: 1 aus (Mathe | Makro). Eine der beiden genügt; Physik (P2, Alle aus) wird nicht angeboten."""
    mathe, makro = semester["mathe"], semester["makro"]
    mathe.teile[0].nummer, mathe.teile[1].nummer, makro.teile[0].nummer = "104.297", "104.298", "105.704"
    mathe.teile[1].steop = False
    session.commit()
    blatt = lambda n: {"art": "lva", "nummer": n, "titel": n, "ects": None, "erfuellt": False}  # noqa: E731
    kriterien = [
        {"name": "P1", "art": "ects", "wert": 6, "erfuellt": False, "kinder": [
            {"name": None, "art": "anzahl", "wert": 1, "erfuellt": False, "kinder": [blatt("104.297"), blatt("105.704")]},
        ]},
        {"name": "P2", "art": "alle", "wert": None, "erfuellt": False, "kinder": [blatt("134.001")]},
    ]
    daten = {**TISS_OFFEN, "erlaubte_ects": 0, "kriterien": kriterien}
    client.post("/api/tiss/steop", json=daten, headers=schluessel(client))

    lvas = {l["titel"]: l for l in client.get("/api/lvas").json()}
    assert lvas["Makroökonomie"]["ist_steop"]  # über die Nummer in den Kriterien
    assert sum(l["besucht"] for l in lvas.values()) == 1  # nur eine der beiden

    status = client.get("/api/lvas/steop").json()
    p1, p2 = status["kriterien"]
    assert p1["erfuellt_variante"] and not p2["erfuellt_variante"]
    assert p2["kinder"][0]["lva_id"] is None  # dieses Semester nicht angeboten
    assert status["warnungen"] == ["P2 ist mit den LVAs dieses Semesters nicht erfüllbar – folgt später."]

    # beide abwählen: P1 nicht erfüllt, obwohl möglich
    for l in lvas.values():
        client.put(f"/api/lvas/steop/variante/{l['id']}", json={"enthalten": False})
    assert "P1 ist mit dieser Variante nicht erfüllt." in client.get("/api/lvas/steop").json()["warnungen"]

    # später ohne aufgeklappte Detailansicht: Kriterien bleiben erhalten
    client.post("/api/tiss/steop", json=TISS_OFFEN, headers=schluessel(client))
    assert len(client.get("/api/lvas/steop").json()["kriterien"]) == 2

    # Abruf im Hintergrund: P-Kriterien zugeklappt (ohne LVAs) – die zuletzt gesehenen LVAs bleiben
    zugeklappt = [{**k, "kinder": []} for k in kriterien]
    client.post("/api/tiss/steop", json={**daten, "kriterien": zugeklappt, "detail_html": "<div>P1</div>"},
                headers=schluessel(client))
    p1, p2 = client.get("/api/lvas/steop").json()["kriterien"]
    assert p1["kinder"][0]["kinder"][0]["nummer"] == "104.297" and p2["kinder"][0]["nummer"] == "134.001"
    assert lies_einstellung(session, "steop_tiss_html_letzt") == "<div>P1</div>"
    assert "detail_html" not in client.get("/api/lvas/steop").json()["tiss"]


def test_steop_lvas_nur_mit_titel(client, session, semester):
    blatt = lambda t: {"art": "lva", "nummer": None, "titel": t, "ects": 6, "erfuellt": False}  # noqa: E731
    semester["mathe"].teile[1].steop = False
    session.commit()
    kriterien = [{"name": "P3", "art": "alle", "wert": None, "erfuellt": False, "kinder": [blatt("VO Makroökonomie")]}]
    client.post("/api/tiss/steop", json={**TISS_OFFEN, "erlaubte_ects": 0, "kriterien": kriterien},
                headers=schluessel(client))
    lvas = {l["titel"]: l for l in client.get("/api/lvas").json()}
    assert lvas["Makroökonomie"]["ist_steop"] and lvas["Makroökonomie"]["besucht"]
    assert not lvas["Mathematik 1"]["besucht"]
    assert client.get("/api/lvas/steop").json()["warnungen"] == []


def test_laufendes_semester_nach_datum(session):
    for s in ("2026W", "2027S"):
        session.add(Lva(schluessel=s, titel=s, semester=s))
    session.commit()
    assert semester_am(date(2026, 10, 11)) == "2026W" and semester_am(date(2027, 2, 1)) == "2026W"
    assert semester_am(date(2027, 4, 1)) == "2027S"
    assert aktuelles_semester(session, date(2026, 10, 11)) == "2026W"  # nicht das höchste
    assert aktuelles_semester(session, date(2027, 4, 1)) == "2027S"
    assert aktuelles_semester(session, date(2028, 4, 1)) == "2027S"  # nichts Neueres: das letzte


def test_ausgeblendete_lva_im_kalender_ausgegraut_und_nicht_im_export(client, semester):
    params = {"von": "2026-10-05T00:00:00", "bis": "2026-10-12T00:00:00"}
    events = client.get("/api/kalender", params=params).json()
    makro = [e for e in events if "Makro" in e["title"]]
    mathe = [e for e in events if "Mathematik" in e["title"]]
    assert makro and all("ausgeblendet" in e["classNames"] and e["extendedProps"]["ausgeblendet"] for e in makro)
    assert all(e["title"].endswith("(nicht besucht)") and e["backgroundColor"] == "#e5e7eb" for e in makro)
    assert mathe and not any("ausgeblendet" in e["classNames"] for e in mathe)
    assert "Makro" not in client.get("/api/export/csv", params=params).text


def test_ausgeblendete_lva_sperrt_keine_arbeit_und_bekommt_keine_lernzeit(client, semester):
    # Mathe und Makro belegen beide Mo–Fr 8–10; nur Mathe wird besucht
    client.put("/api/arbeit/regel", json=regel())
    v = client.post("/api/arbeit/vorschlag", params={"woche": WOCHE}).json()
    assert [b["lva_name"] for b in v["lernbedarf"]] == ["Mathematik 1"]
    assert all(l["lva_id"] == semester["mathe"].id for l in v["lernbloecke"])
    u = client.get("/api/planung/woche", params={"woche": WOCHE}).json()
    assert u["stunden"]["uni"] == 12  # nur Mathe: 5 × 2 h VO + 2 h Prüfung, Makro zählt nicht

    # in die Variante aufgenommen: Makro bekommt Lernbedarf
    client.put(f"/api/lvas/steop/variante/{semester['makro'].id}", json={"enthalten": True})
    v = client.post("/api/arbeit/vorschlag", params={"woche": WOCHE}).json()
    assert {b["lva_name"] for b in v["lernbedarf"]} == {"Mathematik 1", "Makroökonomie"}


def test_ausblenden_entfernt_lernvorschlaege_und_plant_neu(session, client, semester):
    client.put("/api/arbeit/regel", json=regel())
    variante_aendern(session, semester["makro"].id, True)
    session.commit()
    schlage_woche_vor(session, MONTAG)
    assert session.query(Lernblock).filter(Lernblock.lva_id == semester["makro"].id).count() > 0

    variante_aendern(session, semester["makro"].id, False)
    session.commit()
    assert auswahl_geaendert(session, heute=MONTAG) == [MONTAG]  # Woche mit Vorschlägen neu geplant
    assert session.query(Lernblock).filter(Lernblock.lva_id == semester["makro"].id).count() == 0
    assert semester["makro"].id not in besuchte_lva_ids(session)


def test_alle_arbeitsvorschlaege_loeschen(client, session, semester):
    client.put("/api/arbeit/regel", json=regel())
    for w in (0, 1):
        client.post("/api/arbeit/vorschlag", params={"woche": (MONTAG + timedelta(weeks=w)).isoformat()})
    fix = client.post("/api/arbeit/bloecke", json={"start": "2026-10-10T09:00:00", "ende": "2026-10-10T12:00:00"}).json()
    vorschlaege = session.query(Arbeitsblock).filter(Arbeitsblock.status == "vorschlag").count()
    lernen = session.query(Lernblock).count()
    assert vorschlaege > 0

    assert client.post("/api/arbeit/vorschlaege-loeschen").json() == {"geloescht": vorschlaege}
    bloecke = client.get("/api/arbeit/bloecke").json()
    assert [b["id"] for b in bloecke] == [fix["id"]]  # bestätigte Blöcke bleiben
    assert session.query(Lernblock).count() == lernen  # Lernblöcke bleiben unberührt
    assert client.post("/api/arbeit/vorschlaege-loeschen").json() == {"geloescht": 0}


# --- STEOP-Status aus TISS (über die Browser-Erweiterung) -------------------------------------------

def schluessel(client):
    return {"X-Studienhub-Schluessel": client.get("/api/tuwel/einrichtung").json()["schluessel"]}


TISS_OFFEN = {
    "studien": [{"studium": "033282 Wirtschaftsingenieurwesen - Maschinenbau", "status": "offen", "erlaubte_ects": 22.0}],
    "abgeschlossen": False, "erlaubte_ects": 22.0, "steop_nummern": [],
}


def test_steop_status_aus_tiss(client, session, semester):
    setze_steop_abgeschlossen(session, True)  # vorher von Hand gesetzt
    session.commit()
    assert client.post("/api/tiss/steop", json=TISS_OFFEN).status_code == 401  # nur mit Schlüssel der Erweiterung

    antwort = client.post("/api/tiss/steop", json=TISS_OFFEN, headers=schluessel(client)).json()
    assert antwort["uebernommen"] and antwort["abgeschlossen"] is False
    status = client.get("/api/lvas/steop").json()
    assert (status["quelle"], status["erlaubte_ects"]) == ("tiss", 22.0)
    assert status["tiss"]["studien"][0]["status"] == "offen" and status["tiss"]["zeit"]
    # erzeugte Variante: STEOP-LVA plus Nicht-STEOP-LVAs bis zu den erlaubten 22 ECTS
    lvas = {l["titel"]: l["besucht"] for l in client.get("/api/lvas").json()}
    assert lvas == {"Mathematik 1": True, "Makroökonomie": True}
    status = client.get("/api/lvas/steop").json()
    assert (status["vorgezogen_ects"], status["erlaubte_ects_quelle"], status["warnungen"]) == (6, "tiss", [])

    # abgeschlossen in TISS: alle LVAs
    fertig = {**TISS_OFFEN, "abgeschlossen": True, "studien": [{**TISS_OFFEN["studien"][0], "status": "abgeschlossen"}]}
    client.post("/api/tiss/steop", json=fertig, headers=schluessel(client))
    assert client.get("/api/lvas/steop").json()["abgeschlossen"] is True


def test_tiss_nennt_steop_lvas_ueber_ihre_nummer(client, session, semester):
    makro = semester["makro"]
    makro.teile[0].nummer = "105.704"
    session.commit()
    daten = {**TISS_OFFEN, "steop_nummern": ["105.704", "330.001"]}
    client.post("/api/tiss/steop", json=daten, headers=schluessel(client))
    lva = next(l for l in client.get("/api/lvas").json() if l["id"] == makro.id)
    assert lva["ist_steop"] and lva["besucht"]

    # später ohne aufgeklappte Detailansicht: die zuletzt gesehenen Nummern bleiben
    client.post("/api/tiss/steop", json=TISS_OFFEN, headers=schluessel(client))
    assert next(l for l in client.get("/api/lvas").json() if l["id"] == makro.id)["besucht"]


def test_unsicherer_tiss_status_aendert_nichts(client, session, semester):
    setze_steop_abgeschlossen(session, True)
    session.commit()
    unsicher = {**TISS_OFFEN, "abgeschlossen": None, "studien": [{**TISS_OFFEN["studien"][0], "status": None}]}
    antwort = client.post("/api/tiss/steop", json=unsicher, headers=schluessel(client)).json()
    assert antwort["uebernommen"] is False and antwort["abgeschlossen"] is True
    assert client.post("/api/tiss/steop", json={**TISS_OFFEN, "studien": [{"studium": "x", "status": "kaputt"}]},
                       headers=schluessel(client)).status_code == 422
