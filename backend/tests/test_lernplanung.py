"""Lernblöcke: Zeit aus dem Wochenbedarf, nahe Prüfung zuletzt kürzen, Stoff nur verteilen."""

from datetime import date, datetime, time, timedelta

from app.lernplanung import LernBedarf, LernRegeln, LernStoff, LernVorschlag, plane_lernbloecke, stoff_zuteilen
from app.planung import Arbeitsregeln, Intervall, PlanTermin, verteile_arbeitszeit

MONTAG = date(2026, 10, 5)
H = timedelta(hours=1)
MIN = timedelta(minutes=1)


def dt(tag: int, stunde: float) -> datetime:
    return datetime.combine(MONTAG + timedelta(days=tag), time()) + timedelta(hours=stunde)


def stoff(dok_id=1, lva=1, tag=0, stunde=9, minuten=90, titel="Folien"):
    return LernStoff(dok_id, lva, titel, dt(tag, stunde), minuten)


REGELN = LernRegeln(fruehester_beginn=time(8), spaetestes_ende=time(20))


def minuten(plan, lva_id=None):
    return plan.minuten(lva_id)


def test_plant_genau_den_wochenbedarf_verteilt_ueber_die_woche():
    plan = plane_lernbloecke(MONTAG, REGELN, [LernBedarf(1, 360)], [])
    assert minuten(plan) == 360 and plan.offen == {}
    assert all(b.intervall.dauer <= 120 * MIN for b in plan.bloecke)
    tage = [b.intervall.start.date() for b in plan.bloecke]
    assert len(tage) == len(set(tage))  # höchstens ein Block derselben LVA pro Tag
    assert "Lernen LVA 1: 6,0 h in 3 Blöcken" in plan.begruendungen[0]


def test_sperren_tagesgrenze_und_freie_tage():
    regeln = LernRegeln(fruehester_beginn=time(8), spaetestes_ende=time(20), max_tag=4 * H,
                        freie_tage=frozenset({MONTAG + timedelta(days=1)}))
    sperren = [Intervall(dt(0, 8), dt(0, 18))]
    plan = plane_lernbloecke(MONTAG, regeln, [LernBedarf(1, 600)], sperren, grundlast={MONTAG: 3 * H})
    for b in plan.bloecke:
        assert not b.intervall.ueberschneidet(sperren[0])
        assert b.intervall.start.date() != MONTAG + timedelta(days=1)  # gesperrter Tag
        if b.intervall.start.date() == MONTAG:
            assert b.intervall.dauer <= 1 * H  # 3 h Last + höchstens 1 h


def test_mindestlaenge_nur_erlaubte_tage_und_kleine_reste():
    regeln = LernRegeln(tage=frozenset({2}), fruehester_beginn=time(8), spaetestes_ende=time(20))
    plan = plane_lernbloecke(MONTAG, regeln, [LernBedarf(1, 30)], [])
    assert plan.bloecke[0].intervall.start.weekday() == 2 and plan.bloecke[0].intervall.dauer == 45 * MIN
    # weniger als ein halber Mindestblock: kein Block, aber auch kein Konflikt (geht in den Rückstand)
    assert plane_lernbloecke(MONTAG, regeln, [LernBedarf(1, 15)], []).bloecke == []


def test_ohne_nahe_pruefung_wird_zuerst_gekuerzt():
    # Platz für 4 h: Mathe (Prüfung nahe) bekommt alles, Mechanik und GBUF teilen sich den Rest und werden gekürzt
    regeln = LernRegeln(tage=frozenset({0, 1}), fruehester_beginn=time(8), spaetestes_ende=time(10))
    bedarf = [LernBedarf(1, 120, prioritaet=1), LernBedarf(2, 120, prioritaet=0), LernBedarf(3, 120, prioritaet=1)]
    plan = plane_lernbloecke(MONTAG, regeln, bedarf, [], lva_namen={1: "Mechanik", 2: "Mathe", 3: "GBUF"})
    assert minuten(plan, 2) == 120 and 2 not in plan.offen
    assert minuten(plan) == 240
    assert plan.offen.get(1, 0) + plan.offen.get(3, 0) == 120
    assert any("Lernen Mathe" in t and "Lernphase" in t for t in plan.begruendungen)


def test_pruefungswoche_kein_lernblock_nach_der_pruefung():
    pruefung = dt(2, 9)  # Mittwoch 9 Uhr
    regeln = LernRegeln(fruehester_beginn=time(8), spaetestes_ende=time(20), max_tag=2 * H)
    plan = plane_lernbloecke(MONTAG, regeln, [LernBedarf(1, 480, prioritaet=0, pruefung=pruefung)], [])
    assert plan.bloecke and all(b.intervall.ende <= pruefung for b in plan.bloecke)
    # Mo und Di je 2 h, Mi bis 9 Uhr 1 h – danach bringt Lernen für diese Prüfung nichts mehr
    assert minuten(plan) == 300 and plan.offen == {1: 180}


def test_vor_der_naechsten_uebung_bevorzugt():
    plan = plane_lernbloecke(MONTAG, REGELN, [LernBedarf(1, 90)], [], fristen={1: [dt(1, 10)]})
    assert plan.bloecke[0].intervall.ende <= dt(1, 10) and not plan.bloecke[0].nach_frist


def test_kein_bedarf_kein_block():
    assert plane_lernbloecke(MONTAG, REGELN, [LernBedarf(1, 0)], []).bloecke == []


# --- Stoff zuteilen ----------------------------------------------------------------------------

def block(lva, tag, stunden):
    return LernVorschlag(lva, Intervall(dt(tag, 10), dt(tag, 10 + stunden)))


def test_viel_alter_stoff_wird_ueber_die_wochen_verteilt():
    # 40 alte Unterlagen à 60 min Stoff, 10 Wochen bis zur Lernphase: diese Woche ist ein Zehntel dran
    alt = [stoff(i, tag=-30 + i // 2, minuten=60, titel=f"VO {i}") for i in range(40)]
    bloecke = [block(1, 0, 2), block(1, 2, 1)]
    stoff_zuteilen(bloecke, alt, {1: 0.1})
    abgedeckt = sum(sum(b.zuteilung.values()) for b in bloecke)
    assert abgedeckt == 240  # 2400 × 0,1 – nicht der ganze Rückstand
    assert sum(bloecke[0].zuteilung.values()) == 160  # im Verhältnis der Blocklängen
    assert bloecke[0].titel[0] == "VO 0"  # älteste Unterlagen zuerst
    assert set(bloecke[0].zuteilung).isdisjoint(set(bloecke[1].zuteilung) - {max(bloecke[0].zuteilung)})


def test_ohne_offenen_stoff_wiederholung_oder_pruefungsvorbereitung():
    bloecke = [block(1, 0, 1), block(2, 1, 1)]
    stoff_zuteilen(bloecke, [], {1: 0.5, 2: 1.0}, lernphase=frozenset({2}))
    assert bloecke[0].titel == ["Wiederholung und Übungen"] and bloecke[1].titel == ["Prüfungsvorbereitung"]
    assert bloecke[0].zuteilung == {}


def test_stoff_erst_nach_seinem_erscheinen():
    bloecke = [block(1, 0, 1)]
    stoff_zuteilen(bloecke, [stoff(1, tag=3, minuten=60)], {1: 1.0})
    assert bloecke[0].zuteilung == {}  # Unterlage erscheint erst am Donnerstag


# --- Arbeitsplaner mit belegten und gesperrten Zeiten ---------------------------------------------

def test_arbeit_meidet_belegte_zeiten_und_rechnet_sie_zur_tageslast():
    regeln = Arbeitsregeln(stunden_pro_woche=16, fruehester_beginn=time(8), spaetestes_ende=time(20),
                           max_block=8 * H, max_tag=9 * H)
    lernen = [Intervall(dt(t, 8), dt(t, 12)) for t in range(5)]  # bestätigte Lernblöcke
    v = verteile_arbeitszeit(MONTAG, regeln, [], [], lernen)
    assert v.verplant == 16 * H
    for b in v.bloecke:
        assert not any(b.intervall.ueberschneidet(l.erweitert(timedelta(minutes=29))) for l in lernen)
        tag = b.intervall.start.date()
        arbeit = sum((x.intervall.dauer for x in v.bloecke if x.intervall.start.date() == tag), timedelta())
        assert arbeit + 4 * H <= 9 * H
    assert v.soll == 16 * H


def test_gesperrte_zeiten_ohne_tageslast():
    regeln = Arbeitsregeln(stunden_pro_woche=8, tage=frozenset({0}), fruehester_beginn=time(8), spaetestes_ende=time(20),
                           max_block=8 * H, max_tag=9 * H)
    verworfen = [Intervall(dt(0, 8), dt(0, 12))]
    v = verteile_arbeitszeit(MONTAG, regeln, [], [], gesperrte_zeiten=verworfen)
    assert v.verplant == 8 * H and all(b.intervall.start >= dt(0, 12) for b in v.bloecke)


def test_ohne_lernbloecke_unveraendert():
    regeln = Arbeitsregeln(stunden_pro_woche=12)
    termine = [PlanTermin(dt(0, 8), dt(0, 12), "UE", anwesenheitspflicht=True)]
    assert verteile_arbeitszeit(MONTAG, regeln, termine, []).bloecke == verteile_arbeitszeit(MONTAG, regeln, termine, [], []).bloecke
