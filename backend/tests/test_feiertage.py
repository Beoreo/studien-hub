"""Feiertage (AT) und zusätzliche freie Tage: keine Arbeitsvorschläge, Anzeige im Kalender."""

from datetime import date, datetime, time, timedelta

from sqlalchemy import create_engine, inspect, text

from app.db import init_db
from app.feiertage import feiertage, freie_tage_expandieren, gesperrte_tage
from app.models import Arbeitsregel
from app.planung import Arbeitsregeln, verteile_arbeitszeit
from app.planung_service import schlage_woche_vor

NATIONALFEIERTAG = date(2026, 10, 26)  # Montag
WOCHE = NATIONALFEIERTAG
H = timedelta(hours=1)

REGEL = {
    "stunden_pro_woche": 20,
    "tage": [0, 1, 2, 3, 4],
    "bevorzugte_tage": [0],  # Montag wäre bevorzugt – trotzdem frei wegen Feiertag
    "fruehester_beginn": "08:00",
    "spaetestes_ende": "18:00",
    "min_block_minuten": 120,
    "max_block_minuten": 360,
    "puffer_minuten": 30,
}


# --- Feiertage und freie Tage ---------------------------------------------------

def test_nationalfeiertag_2026_ist_ein_montag():
    tage = feiertage(WOCHE, WOCHE + timedelta(days=6))
    # Allerheiligen fällt 2026 auf den Sonntag derselben Woche
    assert tage == {NATIONALFEIERTAG: "Nationalfeiertag", date(2026, 11, 1): "Allerheiligen"}
    assert NATIONALFEIERTAG.weekday() == 0


def test_feiertage_ueber_jahreswechsel():
    tage = feiertage(date(2026, 12, 20), date(2027, 1, 10))
    assert set(tage) == {date(2026, 12, 25), date(2026, 12, 26), date(2027, 1, 1), date(2027, 1, 6)}
    assert feiertage(date(2026, 5, 2), date(2026, 5, 1)) == {}


def test_freie_tage_jaehrlich_und_urlaub():
    eintraege = [
        {"von": "2026-12-24", "bezeichnung": "Heiliger Abend", "jaehrlich": True},
        {"von": "2026-12-31", "jaehrlich": True},
        {"von": "2027-08-02", "bis": "2027-08-06", "bezeichnung": "Urlaub"},
    ]
    tage = freie_tage_expandieren(eintraege, date(2027, 1, 1), date(2027, 12, 31))
    assert tage[date(2027, 12, 24)] == "Heiliger Abend"  # jährlich wiederholt
    assert tage[date(2027, 12, 31)] == "frei"  # ohne Bezeichnung
    assert [t for t, n in tage.items() if n == "Urlaub"] == [date(2027, 8, d) for d in range(2, 7)]
    assert date(2026, 12, 24) not in tage  # außerhalb des Zeitraums


def test_jaehrlicher_zeitraum_ueber_jahreswechsel():
    eintraege = [{"von": "2026-12-27", "bis": "2027-01-02", "bezeichnung": "Betriebsurlaub", "jaehrlich": True}]
    tage = freie_tage_expandieren(eintraege, date(2028, 12, 1), date(2029, 1, 31))
    assert sorted(tage) == [date(2028, 12, d) for d in range(27, 32)] + [date(2029, 1, d) for d in (1, 2)]


def test_gesperrte_tage_vereinigt_beides_feiertag_hat_vorrang():
    eintraege = [{"von": "2026-10-26", "bis": "2026-10-27", "bezeichnung": "Urlaub"}]
    tage = gesperrte_tage(eintraege, WOCHE, WOCHE + timedelta(days=6))
    assert tage == {
        NATIONALFEIERTAG: "Nationalfeiertag",
        date(2026, 10, 27): "Urlaub",
        date(2026, 11, 1): "Allerheiligen",
    }


# --- Algorithmus -----------------------------------------------------------------

def test_algorithmus_ueberspringt_freie_tage():
    regeln = Arbeitsregeln(stunden_pro_woche=20, bevorzugte_tage=frozenset({0}), freie_tage=frozenset({NATIONALFEIERTAG}))
    v = verteile_arbeitszeit(WOCHE, regeln, [], [])
    assert v.verplant == 20 * H
    assert all(b.intervall.start.date() != NATIONALFEIERTAG for b in v.bloecke)


def test_alle_tage_frei_ergibt_fehlende_stunden():
    alle = frozenset(WOCHE + timedelta(days=i) for i in range(7))
    v = verteile_arbeitszeit(WOCHE, Arbeitsregeln(stunden_pro_woche=10, freie_tage=alle), [], [])
    assert v.bloecke == [] and v.fehlend == 10 * H


# --- Woche ab 26.10.2026 über Service und API ----------------------------------

def test_woche_ab_26_10_2026_kein_vorschlag_am_nationalfeiertag(session):
    session.add(Arbeitsregel(
        id=1, stunden_pro_woche=20, tage=[0, 1, 2, 3, 4], bevorzugte_tage=[0],
        fruehester_beginn=time(8), spaetestes_ende=time(18),
        min_block_minuten=120, max_block_minuten=360, puffer_minuten=30,
    ))
    session.commit()

    ergebnis = schlage_woche_vor(session, WOCHE)
    tage = {b.start.date() for b in ergebnis["bloecke"]}
    assert NATIONALFEIERTAG not in tage
    assert tage <= {WOCHE + timedelta(days=i) for i in range(1, 5)}  # Di–Fr
    assert ergebnis["verplant_stunden"] == 20
    assert ergebnis["fehlende_stunden"] == 0


def test_woche_ab_26_10_2026_mit_urlaub_ueber_api(client):
    regel = dict(REGEL, freie_tage=[
        {"von": "2026-10-27", "bis": "2026-10-28", "bezeichnung": "Urlaub"},
        {"von": "2026-12-24", "bezeichnung": "Heiliger Abend", "jaehrlich": True},
    ])
    gespeichert = client.put("/api/arbeit/regel", json=regel).json()
    assert gespeichert["freie_tage"][0] == {"von": "2026-10-27", "bis": "2026-10-28", "bezeichnung": "Urlaub", "jaehrlich": False}

    vorschlag = client.post("/api/arbeit/vorschlag", params={"woche": "2026-10-26"}).json()
    tage = {datetime.fromisoformat(b["start"]).date() for b in vorschlag["bloecke"]}
    assert tage == {date(2026, 10, 29), date(2026, 10, 30)}  # nur Do und Fr bleiben
    # Zwei Tage à 08–18 Uhr reichen nicht für 20 h (max. 6 h pro Block, 30 min Pause): Rest wird gemeldet
    assert vorschlag["verplant_stunden"] == 18
    assert vorschlag["fehlende_stunden"] == 2


def test_ungueltiger_freier_zeitraum(client):
    regel = dict(REGEL, freie_tage=[{"von": "2026-10-28", "bis": "2026-10-27"}])
    assert client.put("/api/arbeit/regel", json=regel).status_code == 422


def test_kalender_zeigt_feiertag_und_freie_tage_ganztaegig_grau(client):
    client.put("/api/arbeit/regel", json=dict(REGEL, freie_tage=[
        {"von": "2026-10-26", "bezeichnung": "Urlaub"},  # fällt auf den Feiertag -> kein Doppel
        {"von": "2026-10-30", "bezeichnung": "Urlaub"},
    ]))
    events = client.get("/api/kalender", params={"von": "2026-10-26T00:00:00", "bis": "2026-11-02T00:00:00"}).json()
    ganztaegig = [e for e in events if e.get("allDay")]
    assert [(e["start"], e["title"], e["extendedProps"]["art"]) for e in ganztaegig] == [
        ("2026-10-26", "Nationalfeiertag", "feiertag"),
        ("2026-11-01", "Allerheiligen", "feiertag"),  # Sonntag, liegt aber im Zeitraum
        ("2026-10-30", "Frei: Urlaub", "frei"),
    ]
    feiertag = ganztaegig[0]
    assert feiertag["end"] == "2026-10-27" and feiertag["backgroundColor"] == "#9ca3af"
    assert feiertag["editable"] is False


def test_migration_ergaenzt_spalte_freie_tage(tmp_path):
    url = f"sqlite:///{(tmp_path / 'alt.db').as_posix()}"
    alt = create_engine(url)
    with alt.begin() as v:  # Tabelle wie in der ersten Version, ohne freie_tage
        v.execute(text(
            "CREATE TABLE arbeitsregel (id INTEGER PRIMARY KEY, stunden_pro_woche FLOAT, tage JSON, "
            "bevorzugte_tage JSON, fruehester_beginn TIME, spaetestes_ende TIME, min_block_minuten INTEGER, "
            "max_block_minuten INTEGER, puffer_minuten INTEGER, arbeitgeber VARCHAR(200))"
        ))
    alt.dispose()
    engine = init_db(url)
    assert "freie_tage" in {s["name"] for s in inspect(engine).get_columns("arbeitsregel")}
    engine.dispose()
