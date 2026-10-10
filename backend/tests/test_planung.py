"""Tests für den Verteilungs-Algorithmus: leere, volle und teilweise belegte Wochen."""

from collections import Counter
from datetime import date, datetime, time, timedelta

from app.planung import (
    Arbeitsregeln,
    Intervall,
    PlanTermin,
    abziehen,
    blocklaenge,
    bewerte_luecke,
    finde_luecken,
    vereinige,
    verteile_arbeitszeit,
    wochenbeginn,
)

MONTAG = date(2026, 10, 5)
H = timedelta(hours=1)


def dt(tag: int, stunde: float) -> datetime:
    """Zeitpunkt am Tag `tag` (0 = Montag) der Testwoche."""
    return datetime.combine(MONTAG + timedelta(days=tag), time()) + timedelta(hours=stunde)


def regeln(**kw) -> Arbeitsregeln:
    basis = dict(stunden_pro_woche=20, min_block=2 * H, max_block=6 * H, puffer=timedelta(minutes=30))
    basis.update(kw)
    return Arbeitsregeln(**basis)


def summe(verteilung) -> timedelta:
    return verteilung.verplant


def pruefe_grundregeln(verteilung, r: Arbeitsregeln):
    for v in verteilung.bloecke:
        b = v.intervall
        assert r.min_block <= b.dauer <= r.max_block
        assert b.start.weekday() in r.tage
        assert b.start.time() >= r.fruehester_beginn and b.ende.time() <= r.spaetestes_ende
        assert b.start.minute % 15 == 0 and b.ende.minute % 15 == 0
    bloecke = sorted((v.intervall for v in verteilung.bloecke), key=lambda i: i.start)
    for a, b in zip(bloecke, bloecke[1:]):
        assert not a.ueberschneidet(b)


# --- Hilfsfunktionen ---------------------------------------------------------

def test_wochenbeginn():
    assert wochenbeginn(date(2026, 10, 8)) == MONTAG
    assert wochenbeginn(MONTAG) == MONTAG


def test_vereinige_und_abziehen():
    assert vereinige([Intervall(dt(0, 10), dt(0, 12)), Intervall(dt(0, 11), dt(0, 13))]) == [
        Intervall(dt(0, 10), dt(0, 13))
    ]
    frei = abziehen(Intervall(dt(0, 8), dt(0, 18)), [Intervall(dt(0, 10), dt(0, 12)), Intervall(dt(0, 15), dt(0, 20))])
    assert frei == [Intervall(dt(0, 8), dt(0, 10)), Intervall(dt(0, 12), dt(0, 15))]


def test_finde_luecken_rundet_und_ignoriert_kurze():
    r = regeln(tage=frozenset({0}))
    sperren = [Intervall(dt(0, 9.1), dt(0, 12.2))]  # 09:06–12:12
    luecken = list(finde_luecken(MONTAG, r, sperren))
    # 08:00–09:00 ist kürzer als 2 h; 12:15–18:00 bleibt
    assert luecken == [Intervall(dt(0, 12.25), dt(0, 18))]


def test_blocklaenge():
    r = regeln()
    assert blocklaenge(10 * H, 20 * H, r) == 6 * H  # Maximallänge
    assert blocklaenge(10 * H, 7 * H, r) == 5 * H  # Rest von 1 h wäre zu kurz -> 5 + 2
    assert blocklaenge(10 * H, 1 * H, r) is None  # Mindestlänge nicht erreichbar
    assert blocklaenge(1.5 * H, 5 * H, r) is None  # Lücke zu kurz


def test_bewertung_bevorzugt_tage_und_vermeidet_wechsel():
    r = regeln(bevorzugte_tage=frozenset({2}))
    montag, mittwoch = Intervall(dt(0, 8), dt(0, 14)), Intervall(dt(2, 8), dt(2, 14))
    leer = Counter()
    assert bewerte_luecke(mittwoch, 20 * H, r, leer, leer) > bewerte_luecke(montag, 20 * H, r, leer, leer)
    uni = Counter({MONTAG: 1})
    assert bewerte_luecke(montag, 20 * H, r, uni, leer) < bewerte_luecke(montag, 20 * H, r, leer, leer)


# --- Verteilung ----------------------------------------------------------------

def test_leere_woche_verteilt_alle_stunden():
    r = regeln(bevorzugte_tage=frozenset({1, 3}))
    v = verteile_arbeitszeit(MONTAG, r, [], [])
    assert summe(v) == 20 * H
    assert v.fehlend == timedelta(0)
    assert v.geopferte_termine == []
    pruefe_grundregeln(v, r)
    # bevorzugte Tage (Di, Do) werden zuerst belegt
    tage = {b.intervall.start.weekday() for b in v.bloecke}
    assert {1, 3} <= tage
    # lange Blöcke: 6 + 6 + 6 + 2 oder ähnlich, also höchstens 4 Blöcke
    assert len(v.bloecke) <= 4


def test_volle_woche_zeigt_fehlende_stunden():
    r = regeln()
    # Jeden Werktag 8–18 Uhr Pflichttermine
    termine = [PlanTermin(dt(t, 8), dt(t, 18), "Labor", anwesenheitspflicht=True) for t in range(5)]
    v = verteile_arbeitszeit(MONTAG, r, termine, [])
    assert v.bloecke == []
    assert v.fehlend == 20 * H


def test_null_stunden_ergibt_keinen_vorschlag():
    v = verteile_arbeitszeit(MONTAG, regeln(stunden_pro_woche=0), [], [])
    assert v.bloecke == [] and v.fehlend == timedelta(0)


def test_pflichttermine_mit_puffer_werden_freigehalten():
    r = regeln(stunden_pro_woche=40, max_block=10 * H)
    termin = PlanTermin(dt(0, 12), dt(0, 14), "Übung", anwesenheitspflicht=True)
    pruefung = PlanTermin(dt(2, 9), dt(2, 11), "Prüfung", pruefung=True)
    v = verteile_arbeitszeit(MONTAG, r, [termin, pruefung], [])
    pruefe_grundregeln(v, r)
    for b in v.bloecke:
        assert not b.intervall.ueberschneidet(termin.intervall.erweitert(r.puffer))
        assert not b.intervall.ueberschneidet(pruefung.intervall.erweitert(r.puffer))


def test_bestaetigte_bloecke_zaehlen_und_sperren():
    r = regeln(stunden_pro_woche=10)
    fix = Intervall(dt(0, 8), dt(0, 14))  # 6 h bereits fix
    v = verteile_arbeitszeit(MONTAG, r, [], [fix])
    assert v.soll == 4 * H
    assert summe(v) == 4 * H
    for b in v.bloecke:
        assert not b.intervall.ueberschneidet(fix)


def test_aufgezeichnete_vorlesung_darf_ueberplant_werden():
    # Nur Montag erlaubt, dort liegt eine aufgezeichnete VO ohne Anwesenheitspflicht
    r = regeln(stunden_pro_woche=10, tage=frozenset({0}), max_block=10 * H)
    vo = PlanTermin(dt(0, 10), dt(0, 12), "Analysis VO", aufzeichnung=True)
    v = verteile_arbeitszeit(MONTAG, r, [vo], [])
    assert summe(v) == 10 * H
    assert v.geopferte_termine == []  # aufgezeichnet -> kein Opfer
    assert v.bloecke[0].ueberplante_termine == [vo]


def test_nicht_aufgezeichnete_vorlesung_nur_wenn_noetig():
    vo = PlanTermin(dt(0, 10), dt(0, 12), "Algebra VO", aufzeichnung=False)

    # Genug Platz: die VO bleibt frei
    r = regeln(stunden_pro_woche=4, tage=frozenset({0}))
    v = verteile_arbeitszeit(MONTAG, r, [vo], [])
    assert summe(v) == 4 * H
    assert v.geopferte_termine == []
    assert all(not b.intervall.ueberschneidet(vo.intervall.erweitert(r.puffer)) for b in v.bloecke)

    # Zu wenig Platz: die VO wird geopfert und gemeldet
    r = regeln(stunden_pro_woche=10, tage=frozenset({0}), max_block=10 * H)
    v = verteile_arbeitszeit(MONTAG, r, [vo], [])
    assert v.geopferte_termine == [vo]
    assert summe(v) > 4 * H


def test_termine_ausserhalb_der_woche_werden_ignoriert():
    r = regeln(stunden_pro_woche=6, tage=frozenset({0}))
    naechste_woche = PlanTermin(dt(7, 8), dt(7, 18), "später", anwesenheitspflicht=True)
    v = verteile_arbeitszeit(MONTAG, r, [naechste_woche], [])
    assert summe(v) == 6 * H


def test_nur_erlaubte_tage_und_zeiten():
    r = regeln(stunden_pro_woche=12, tage=frozenset({5, 6}), fruehester_beginn=time(10), spaetestes_ende=time(16))
    v = verteile_arbeitszeit(date(2026, 10, 7), r, [], [])  # irgendein Tag der Woche
    pruefe_grundregeln(v, r)
    assert summe(v) == 12 * H
    assert {b.intervall.start.weekday() for b in v.bloecke} == {5, 6}
