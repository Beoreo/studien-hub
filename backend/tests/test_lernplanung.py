"""Lernblöcke: bald nach Erscheinen, vor Übungen/Abgaben, Konflikte statt stillem Kürzen."""

from datetime import date, datetime, time, timedelta

from app.lernplanung import LernRegeln, LernStoff, plane_lernbloecke
from app.planung import Arbeitsregeln, Intervall, PlanTermin, verteile_arbeitszeit

MONTAG = date(2026, 10, 5)
H = timedelta(hours=1)
MIN = timedelta(minutes=1)


def dt(tag: int, stunde: float) -> datetime:
    return datetime.combine(MONTAG + timedelta(days=tag), time()) + timedelta(hours=stunde)


def stoff(dok_id=1, lva=1, tag=0, stunde=9, minuten=90, titel="Folien"):
    return LernStoff(dok_id, lva, titel, dt(tag, stunde), minuten)


REGELN = LernRegeln(fruehester_beginn=time(8), spaetestes_ende=time(20))


def test_bald_nach_erscheinen_und_nie_davor():
    plan = plane_lernbloecke(MONTAG, REGELN, [stoff(tag=1, stunde=13, minuten=90)], [])
    assert len(plan.bloecke) == 1
    block = plan.bloecke[0].intervall
    assert block.start == dt(1, 13) and block.dauer == 90 * MIN  # direkt nach Erscheinen am Dienstag
    assert plan.bloecke[0].zuteilung == {1: 90}
    assert plan.offen == {}


def test_vor_der_uebung_und_um_sperren_herum():
    # Stoff Montag 9 Uhr, Übung Dienstag 10 Uhr, Montag ganztägig Pflichttermine bis 18 Uhr
    sperren = [Intervall(dt(0, 8), dt(0, 18))]
    plan = plane_lernbloecke(MONTAG, REGELN, [stoff(minuten=120)], sperren, fristen={1: [dt(1, 10)]})
    block = plan.bloecke[0].intervall
    assert block.ende <= dt(1, 10) and not plan.bloecke[0].nach_frist
    assert not block.ueberschneidet(sperren[0])
    assert block.start >= dt(0, 18) or block.start.date() == dt(1, 8).date()
    assert "vor der nächsten Übung/Abgabe" in plan.begruendungen[0]


def test_nach_der_frist_nur_wenn_vorher_kein_platz():
    sperren = [Intervall(dt(0, 8), dt(0, 20)), Intervall(dt(1, 8), dt(1, 10))]
    plan = plane_lernbloecke(MONTAG, REGELN, [stoff(minuten=60)], sperren, fristen={1: [dt(1, 10)]})
    assert plan.bloecke[0].nach_frist
    assert "erst nach der Übung/Abgabe" in plan.begruendungen[0]


def test_lange_unterlagen_werden_in_bloecke_geteilt_und_tagesgrenze_gilt():
    regeln = LernRegeln(fruehester_beginn=time(8), spaetestes_ende=time(20), max_block=120 * MIN, max_tag=4 * H)
    plan = plane_lernbloecke(MONTAG, regeln, [stoff(minuten=600)], [], grundlast={MONTAG: 2 * H})
    assert all(b.intervall.dauer <= 120 * MIN for b in plan.bloecke)
    assert sum(b.zuteilung[1] for b in plan.bloecke) == 600
    montag = sum((b.intervall.dauer for b in plan.bloecke if b.intervall.start.date() == MONTAG), timedelta())
    assert montag <= 2 * H  # 2 h Uni + höchstens 2 h Lernen
    for a, b in zip(plan.bloecke, plan.bloecke[1:]):
        assert b.intervall.start >= a.intervall.ende + timedelta(minutes=30) or b.intervall.start.date() != a.intervall.start.date()


def test_mindestlaenge_und_nur_erlaubte_tage():
    regeln = LernRegeln(tage=frozenset({2}), fruehester_beginn=time(8), spaetestes_ende=time(20))
    plan = plane_lernbloecke(MONTAG, regeln, [stoff(minuten=10)], [])
    assert plan.bloecke[0].intervall.start.weekday() == 2
    assert plan.bloecke[0].intervall.dauer == 45 * MIN  # Mindestlänge


def test_kein_platz_wird_als_offen_gemeldet():
    regeln = LernRegeln(tage=frozenset({0}), fruehester_beginn=time(8), spaetestes_ende=time(12))
    plan = plane_lernbloecke(MONTAG, regeln, [stoff(minuten=600, stunde=8)], [])
    verplant = sum(b.zuteilung[1] for b in plan.bloecke)
    assert verplant < 600 and plan.offen == {1: 600 - verplant}


def test_dringendste_lva_zuerst_und_mehrere_unterlagen_in_einem_block():
    # 8:00–10:30: nach 1,5 h Algebra und 30 min Pause bleibt kein Mindestblock für Analysis
    regeln = LernRegeln(tage=frozenset({0}), fruehester_beginn=time(8), spaetestes_ende=time(10, 30))
    plan = plane_lernbloecke(
        MONTAG, regeln,
        [stoff(1, lva=1, stunde=8, minuten=60), stoff(2, lva=2, stunde=8, minuten=40), stoff(3, lva=2, stunde=8, minuten=50)],
        [], fristen={2: [dt(0, 11)]}, lva_namen={1: "Analysis", 2: "Algebra"},
    )
    erster = plan.bloecke[0]
    assert erster.lva_id == 2 and erster.intervall.start == dt(0, 8)  # Algebra hat die frühere Frist
    assert erster.zuteilung == {2: 40, 3: 50} and erster.titel == ["Folien"]
    assert 1 in plan.offen  # Analysis passt nicht mehr hinein


def test_stoff_aus_spaeteren_wochen_wird_ignoriert():
    plan = plane_lernbloecke(MONTAG, REGELN, [stoff(tag=8)], [])
    assert plan.bloecke == [] and plan.offen == {}


# --- Arbeitsplaner mit Lernblöcken ------------------------------------------------------------

def test_arbeit_meidet_lernbloecke_und_rechnet_sie_zur_tageslast():
    regeln = Arbeitsregeln(stunden_pro_woche=16, fruehester_beginn=time(8), spaetestes_ende=time(20),
                           max_block=8 * H, max_tag=9 * H)
    lernen = [Intervall(dt(t, 8), dt(t, 12)) for t in range(5)]  # jeden Werktag 4 h Lernen
    v = verteile_arbeitszeit(MONTAG, regeln, [], [], lernen)
    assert v.verplant == 16 * H
    for b in v.bloecke:
        assert not any(b.intervall.ueberschneidet(l.erweitert(timedelta(minutes=29))) for l in lernen)
        tag = b.intervall.start.date()
        arbeit = sum((x.intervall.dauer for x in v.bloecke if x.intervall.start.date() == tag), timedelta())
        assert arbeit + 4 * H <= 9 * H  # Tagesgrenze inklusive Lernen
    assert v.soll == 16 * H  # Lernzeit zählt nicht zu den Arbeitsstunden


def test_ohne_lernbloecke_unveraendert():
    regeln = Arbeitsregeln(stunden_pro_woche=12)
    termine = [PlanTermin(dt(0, 8), dt(0, 12), "UE", anwesenheitspflicht=True)]
    assert verteile_arbeitszeit(MONTAG, regeln, termine, []).bloecke == verteile_arbeitszeit(MONTAG, regeln, termine, [], []).bloecke
