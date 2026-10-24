"""Tests für den Verteilungs-Algorithmus: beste Woche nach Punktzahl statt „möglichst früh“."""

from collections import defaultdict
from datetime import date, datetime, time, timedelta

from app.planung import (
    Arbeitsregeln,
    Gewichte,
    Intervall,
    PlanTermin,
    abziehen,
    finde_luecken,
    vereinige,
    verteile_arbeitszeit,
    wochenbeginn,
    zaehle_wechsel,
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


def pflicht(tag: int, von: float, bis: float, titel: str = "UE") -> PlanTermin:
    return PlanTermin(dt(tag, von), dt(tag, bis), titel, anwesenheitspflicht=True)


def arbeit_pro_tag(v) -> dict[int, timedelta]:
    summe: dict[int, timedelta] = defaultdict(timedelta)
    for b in v.bloecke:
        summe[b.intervall.start.weekday()] += b.intervall.dauer
    return dict(summe)


def tageslast(v, termine) -> dict[int, timedelta]:
    """Uni (besuchte Termine) plus Arbeit pro Wochentag."""
    last: dict[int, timedelta] = defaultdict(timedelta)
    for t in termine:
        last[t.start.weekday()] += t.ende - t.start
    for tag, dauer in arbeit_pro_tag(v).items():
        last[tag] += dauer
    return dict(last)


def pruefe_grundregeln(v, r: Arbeitsregeln):
    for vorschlag in v.bloecke:
        b = vorschlag.intervall
        assert r.min_block <= b.dauer <= r.max_block
        assert b.start.weekday() in r.tage
        assert b.start.time() >= r.fruehester_beginn and b.ende.time() <= r.spaetestes_ende
        assert b.start.minute % 15 == 0 and b.ende.minute % 15 == 0
    bloecke = sorted((x.intervall for x in v.bloecke), key=lambda i: i.start)
    for a, b in zip(bloecke, bloecke[1:]):
        assert not a.ueberschneidet(b)
    pro_tag = defaultdict(int)
    for b in bloecke:
        pro_tag[b.start.date()] += 1
    assert all(n <= 2 for n in pro_tag.values())


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
    # 08:00–09:00 ist kürzer als 2 h; 12:15–18:00 bleibt
    assert list(finde_luecken(MONTAG, r, sperren)) == [Intervall(dt(0, 12.25), dt(0, 18))]


def test_zaehle_wechsel():
    uni = [Intervall(dt(0, 8), dt(0, 10)), Intervall(dt(0, 14), dt(0, 16))]
    assert zaehle_wechsel(uni, []) == 0
    assert zaehle_wechsel(uni, [Intervall(dt(0, 17), dt(0, 19))]) == 1
    assert zaehle_wechsel(uni, [Intervall(dt(0, 11), dt(0, 13))]) == 2


# --- Grundverhalten ----------------------------------------------------------

def test_leere_woche_verteilt_alle_stunden():
    r = regeln(bevorzugte_tage=frozenset({1, 3}))
    v = verteile_arbeitszeit(MONTAG, r, [], [])
    assert v.verplant == 20 * H and v.fehlend == timedelta(0)
    assert v.geopferte_termine == []
    pruefe_grundregeln(v, r)
    assert all(last <= r.max_tag for last in tageslast(v, []).values())
    assert v.begruendungen  # es gibt immer eine kurze Erklärung


def test_volle_woche_zeigt_fehlende_stunden():
    termine = [pflicht(t, 8, 18, "Labor") for t in range(5)]
    v = verteile_arbeitszeit(MONTAG, regeln(), termine, [])
    assert v.bloecke == []
    assert v.fehlend == 20 * H
    assert any("passen nicht" in b for b in v.begruendungen)


def test_null_stunden_ergibt_keinen_vorschlag():
    v = verteile_arbeitszeit(MONTAG, regeln(stunden_pro_woche=0), [], [])
    assert v.bloecke == [] and v.fehlend == timedelta(0)


def test_pflichttermine_mit_puffer_werden_freigehalten():
    r = regeln(stunden_pro_woche=30, max_block=8 * H)
    termin = pflicht(0, 12, 14, "Übung")
    pruefung = PlanTermin(dt(2, 9), dt(2, 11), "Prüfung", pruefung=True)
    v = verteile_arbeitszeit(MONTAG, r, [termin, pruefung], [])
    pruefe_grundregeln(v, r)
    for b in v.bloecke:
        assert not b.intervall.ueberschneidet(termin.intervall.erweitert(r.puffer))
        assert not b.intervall.ueberschneidet(pruefung.intervall.erweitert(r.puffer))


def test_bestaetigte_bloecke_zaehlen_und_sperren():
    fix = Intervall(dt(0, 8), dt(0, 14))  # 6 h bereits fix
    v = verteile_arbeitszeit(MONTAG, regeln(stunden_pro_woche=10), [], [fix])
    assert v.soll == 4 * H and v.verplant == 4 * H
    assert all(not b.intervall.ueberschneidet(fix.erweitert(timedelta(minutes=29))) for b in v.bloecke)


def test_termine_ausserhalb_der_woche_werden_ignoriert():
    v = verteile_arbeitszeit(MONTAG, regeln(stunden_pro_woche=6, tage=frozenset({0})), [pflicht(7, 8, 18)], [])
    assert v.verplant == 6 * H


def test_nur_erlaubte_tage_und_zeiten():
    r = regeln(stunden_pro_woche=12, tage=frozenset({5, 6}), fruehester_beginn=time(10), spaetestes_ende=time(16))
    v = verteile_arbeitszeit(date(2026, 10, 7), r, [], [])
    pruefe_grundregeln(v, r)
    assert v.verplant == 12 * H
    assert set(arbeit_pro_tag(v)) == {5, 6}


# --- Aufgezeichnete und nicht aufgezeichnete Vorlesungen ----------------------

def test_aufgezeichnete_vorlesung_darf_ueberplant_werden():
    r = regeln(stunden_pro_woche=8, tage=frozenset({0}), max_block=8 * H)
    vo = PlanTermin(dt(0, 10), dt(0, 12), "Analysis VO", aufzeichnung=True, vorlesung=True)
    v = verteile_arbeitszeit(MONTAG, r, [vo], [])
    assert v.verplant == 8 * H
    assert v.geopferte_termine == []  # aufgezeichnet -> kein Opfer
    assert v.bloecke[0].ueberplante_termine == [vo]


def test_lernfenster_nach_vorlesung_und_lockerung():
    vo = PlanTermin(dt(0, 10), dt(0, 12), "Algebra VO", vorlesung=True)  # ohne Aufzeichnung: man geht hin

    # Genug Platz: nach der VO bleiben 2 h Lernzeit plus Weg frei
    r = regeln(stunden_pro_woche=3, tage=frozenset({0}))
    v = verteile_arbeitszeit(MONTAG, r, [vo], [])
    assert v.verplant == 3 * H
    assert all(b.intervall.start >= dt(0, 14.5) for b in v.bloecke)
    assert any("Lernzeit freigehalten" in b for b in v.begruendungen)

    # Etwas knapper: das Lernfenster wird gekürzt, die VO bleibt aber frei
    r = regeln(stunden_pro_woche=5, tage=frozenset({0}))
    v = verteile_arbeitszeit(MONTAG, r, [vo], [])
    assert v.verplant == 5 * H and v.geopferte_termine == []
    assert any("gekürzt" in b for b in v.begruendungen)

    # Zu wenig Platz: die VO wird geopfert und gemeldet
    r = regeln(stunden_pro_woche=8, tage=frozenset({0}), max_block=8 * H)
    v = verteile_arbeitszeit(MONTAG, r, [vo], [])
    assert v.geopferte_termine == [vo]
    assert v.verplant == 8 * H


# --- Kriterien der entspannten Woche -------------------------------------------

def test_alte_version_haette_ueberladene_woche_erzeugt():
    """Regressionstest gegen den früheren Greedy-Algorithmus („möglichst früh, lange Lücken zuerst“).

    Mo–Do Pflicht-Übung 8–12 Uhr, Freitag frei, 20 h Arbeit, Fenster 8–20 Uhr, Blöcke 2–8 h.
    Die alte Version lieferte:
        Mo 12:30–20:00 Arbeit 7,5 h  -> Tag gesamt 11,5 h (überladen)
        Di 12:30–17:00 Arbeit 4,5 h  -> Tag gesamt  8,5 h
        Fr 08:00–16:00 Arbeit 8,0 h  -> Tag gesamt  8,0 h
    """
    termine = [pflicht(t, 8, 12) for t in range(4)]
    r = regeln(fruehester_beginn=time(8), spaetestes_ende=time(20), max_block=8 * H)
    v = verteile_arbeitszeit(MONTAG, r, termine, [])

    assert v.verplant == 20 * H
    pruefe_grundregeln(v, r)
    last = tageslast(v, termine)
    assert max(last.values()) <= 9 * H  # kein Tag mehr über der Tagesgrenze
    assert last[0] < 11.5 * H
    # gleichmäßiger als vorher: Spanne zwischen vollstem und leerstem Werktag kleiner
    werktage = [last.get(t, timedelta(0)) for t in range(5)]
    assert max(werktage) - min(werktage) < 11.5 * H - 4 * H
    assert 4 in arbeit_pro_tag(v)  # der unifreie Freitag wird als Arbeitstag gebündelt


def test_tagesgrenze_ist_einstellbar():
    termine = [pflicht(t, 8, 12) for t in range(5)]
    r = regeln(stunden_pro_woche=20, fruehester_beginn=time(8), spaetestes_ende=time(20), max_tag=7 * H)
    v = verteile_arbeitszeit(MONTAG, r, termine, [])
    assert all(last <= 7 * H for last in tageslast(v, termine).values())
    assert v.verplant == 15 * H and v.fehlend == 5 * H  # 5 Tage × 3 h


def test_arbeit_wird_an_tagen_ohne_uni_gebuendelt():
    termine = [pflicht(t, 9, 11) for t in range(3)]  # Mo–Mi kurze Pflichttermine
    v = verteile_arbeitszeit(MONTAG, regeln(stunden_pro_woche=12), termine, [])
    assert set(arbeit_pro_tag(v)) == {3, 4}
    assert any("gebündelt" in b and "Do" in b and "Fr" in b for b in v.begruendungen)


def test_lernzeit_vor_pruefung():
    pruefung = PlanTermin(dt(2, 10), dt(2, 12), "Algebra", pruefung=True)
    r = regeln(stunden_pro_woche=12)
    v = verteile_arbeitszeit(MONTAG, r, [pruefung], [])
    assert 1 not in arbeit_pro_tag(v)  # Dienstag bleibt frei
    assert "Di frei gehalten: Prüfung Algebra Mi" in v.begruendungen
    # Am Prüfungstag selbst bleibt das Lernfenster davor frei
    lernfenster = Intervall(dt(2, 10) - r.puffer - r.lernfenster, dt(2, 10))
    assert all(not b.intervall.ueberschneidet(lernfenster) for b in v.bloecke)


def test_vortag_einer_abgabe_arbeit_geht_vor_wenn_knapp():
    abgabe = PlanTermin(dt(1, 23.75), dt(1, 23.75), "Übungsblatt 3", abgabe=True)
    # Wochenstunden sind Pflicht: reicht der Platz nicht, fällt das Lernfenster am Vortag weg
    r = regeln(stunden_pro_woche=10, tage=frozenset({0}), max_block=8 * H, max_tag=10 * H)
    v = verteile_arbeitszeit(MONTAG, r, [abgabe], [])
    assert v.verplant > 8 * H  # mehr als Fenster (10 h) minus Lernfenster (2 h)
    assert any("Lernzeit vor Prüfungen/Abgaben" in b for b in v.begruendungen)

    # passen die Stunden auch so, bleibt das Lernfenster frei
    v = verteile_arbeitszeit(MONTAG, regeln(**{**r.__dict__, "stunden_pro_woche": 6}), [abgabe], [])
    assert v.verplant == 6 * H and any("Lernzeit vor Abgabe Di" in b for b in v.begruendungen)


def test_kein_arbeitsblock_am_abend_nach_vollem_unitag():
    termine = [pflicht(0, 8, 15, "Labor")]  # 7 h Uni
    r = regeln(stunden_pro_woche=4, tage=frozenset({0}), fruehester_beginn=time(8), spaetestes_ende=time(21))
    v = verteile_arbeitszeit(MONTAG, r, termine, [])
    assert v.bloecke == [] and v.fehlend == 4 * H
    assert "Mo abends frei: voller Unitag (7 h)" in v.begruendungen

    # Mit höherer Schwelle für den vollen Unitag ist der Abend wieder verfügbar
    v = verteile_arbeitszeit(MONTAG, regeln(**{**r.__dict__, "voller_unitag": 8 * H}), termine, [])
    assert v.verplant == 2 * H  # Tagesgrenze 9 h: 7 h Uni + 2 h


def test_mindestens_ein_komplett_freier_tag():
    r = regeln(stunden_pro_woche=30, tage=frozenset(range(7)), max_block=8 * H)
    v = verteile_arbeitszeit(MONTAG, r, [], [])
    assert v.verplant == 30 * H
    assert len(arbeit_pro_tag(v)) <= 6
    assert any(b.startswith("Komplett frei") for b in v.begruendungen)

    # Mit zwei geforderten freien Tagen bleiben zwei Tage leer
    v = verteile_arbeitszeit(MONTAG, regeln(**{**r.__dict__, "min_freie_tage": 2}), [], [])
    assert len(arbeit_pro_tag(v)) <= 5


def test_gewichte_steuern_zerstueckelung_gegen_gleichmaessigkeit():
    basis = dict(stunden_pro_woche=16, max_block=8 * H)
    # Nur Zerstückelung zählt: wenige lange Blöcke
    lang = verteile_arbeitszeit(MONTAG, regeln(**basis, gewichte=Gewichte(gleichmaessig=0, zerstueckelung=10)), [], [])
    assert len(lang.bloecke) == 2 and all(b.intervall.dauer == 8 * H for b in lang.bloecke)
    # Nur Gleichmäßigkeit zählt: auf alle Werktage verteilt
    gleich = verteile_arbeitszeit(MONTAG, regeln(**basis, gewichte=Gewichte(gleichmaessig=10, zerstueckelung=0)), [], [])
    assert len(arbeit_pro_tag(gleich)) == 5
    assert gleich.punktzahl != lang.punktzahl


def test_feste_regeln_gelten_auch_ohne_gewichte():
    null = Gewichte(0, 0, 0, 0, 0)
    termine = [pflicht(t, 8, 12) for t in range(4)]
    r = regeln(fruehester_beginn=time(8), spaetestes_ende=time(20), max_block=8 * H, gewichte=null)
    v = verteile_arbeitszeit(MONTAG, r, termine, [])
    assert max(tageslast(v, termine).values()) <= 9 * H


def test_zwei_bloecke_am_stueck_statt_loch_in_der_mitte():
    # freier Freitag 7–18 Uhr, 8,5 h Arbeit, Blöcke höchstens 6 h: zwei Blöcke nur mit Pause dazwischen
    r = regeln(stunden_pro_woche=8.5, tage=frozenset({4}), fruehester_beginn=time(7), spaetestes_ende=time(18),
               max_block=6 * H, max_tag=9 * H, min_freie_tage=0)
    v = verteile_arbeitszeit(MONTAG, r, [], [])
    assert v.verplant == 8.5 * H
    erster, zweiter = (b.intervall for b in v.bloecke)
    assert zweiter.start - erster.ende == timedelta(minutes=30)  # kein Leerlauf


def test_leerlauf_zaehlt_nur_ohne_uni_dazwischen():
    from app.planung import Intervall, leerlauf

    a, b = Intervall(dt(0, 7), dt(0, 9)), Intervall(dt(0, 12), dt(0, 16))
    assert leerlauf([a, b], []) == timedelta(hours=2, minutes=30)
    assert leerlauf([b, a], [Intervall(dt(0, 10), dt(0, 11))]) == timedelta(0)  # Uni dazwischen
    assert leerlauf([a, Intervall(dt(0, 9.5), dt(0, 12))], []) == timedelta(0)  # nur die Pause
