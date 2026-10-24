"""Lernbedarf aus den ECTS: Formel, Verteilung bis zur Prüfung, Lernphase, Nachholen (reine Logik)."""

from datetime import date, timedelta

import pytest

from app.lernbedarf import (
    LvaPlanDaten,
    bedarf_fuer_woche,
    gesamtbedarf_minuten,
    in_lernphase,
    nachholen_pro_woche,
    wochengewichte,
)

MONTAG = date(2026, 10, 5)
W = timedelta(weeks=1)


def woche(n: int) -> date:
    return MONTAG + n * W


def daten(**kw) -> LvaPlanDaten:
    """6 ECTS, 30 h Präsenz, Termine in den Wochen 0–9, Prüfung am Mittwoch der Woche 11."""
    basis = dict(lva_id=1, name="Mechanik", ects=6, praesenz_minuten=30 * 60, erste_woche=woche(0),
                 letzte_woche=woche(9), pruefungen=(woche(11) + timedelta(days=2),))
    basis.update(kw)
    return LvaPlanDaten(**basis)


# (150 h − 30 h) × 0,7 × 0,8 = 67,2 h
GESAMT = 4032


def test_gesamtbedarf_aus_ects_minus_praesenz_mal_faktoren():
    assert gesamtbedarf_minuten(6, 30 * 60) == GESAMT
    assert gesamtbedarf_minuten(6, 30 * 60, ziel="bestehen") == round(7200 * 0.7 * 0.6)
    assert gesamtbedarf_minuten(6, 30 * 60, ziel="gut") == round(7200 * 0.7 * 1.0)
    assert gesamtbedarf_minuten(6, 30 * 60, ects_faktor=1.0, ziel="gut") == 7200
    assert gesamtbedarf_minuten(6, 30 * 60, anpassung=0.5) == GESAMT // 2  # Regler
    assert gesamtbedarf_minuten(None, 0) == 0 and gesamtbedarf_minuten(0, 0) == 0
    assert gesamtbedarf_minuten(1, 40 * 60) == 0  # mehr Präsenz als ECTS-Stunden: kein negativer Bedarf


def test_lernfenster_vor_der_pruefung():
    pruefung = (woche(11) + timedelta(days=2),)
    # Prüfungswoche und die 2 Wochen davor
    assert [in_lernphase(woche(n), pruefung, 2) for n in (8, 9, 10, 11, 12)] == [False, True, True, True, False]
    assert not in_lernphase(woche(11), pruefung, 0)
    assert not in_lernphase(woche(3), (), 2)


def test_gelernt_wird_nur_in_den_wochen_vor_der_pruefung():
    d = daten()
    gewichte = wochengewichte(d, 2)
    assert list(gewichte) == [woche(9), woche(10), woche(11)]
    fenster = [bedarf_fuer_woche(d, woche(n)) for n in (9, 10, 11)]
    assert all(b.plan_minuten == b.soll_minuten == GESAMT // 3 and b.lernphase for b in fenster)
    assert [b.prioritaet for b in fenster] == [2, 1, 0]  # Wochen bis zur Prüfung: die nächste wird zuletzt gekürzt
    assert fenster[0].pruefung == woche(11) + timedelta(days=2)
    # vor dem Fenster, nach der Prüfung: nichts
    for n in (0, 5, 8, 12):
        assert bedarf_fuer_woche(d, woche(n)).soll_minuten == 0 and not bedarf_fuer_woche(d, woche(n)).lernphase
    # eigene Fensterlänge der LVA geht vor; nie vor dem ersten Termin
    assert list(wochengewichte(daten(lernwochen=4), 2)) == [woche(n) for n in range(7, 12)]
    assert list(wochengewichte(daten(lernwochen=20), 2)) == [woche(n) for n in range(0, 12)]


def test_ohne_pruefung_kein_lernbedarf():
    d = daten(pruefungen=())
    assert wochengewichte(d, 2) == {}
    assert bedarf_fuer_woche(d, woche(9)).soll_minuten == 0


def test_mehrere_pruefungen_eigene_fenster():
    d = daten(pruefungen=(woche(5) + timedelta(days=1), woche(11) + timedelta(days=2)))
    assert list(wochengewichte(d, 1)) == [woche(4), woche(5), woche(10), woche(11)]
    assert bedarf_fuer_woche(d, woche(4), lernphase_wochen=1).soll_minuten == GESAMT // 4
    assert bedarf_fuer_woche(d, woche(7), lernphase_wochen=1).soll_minuten == 0


def test_gesperrte_lerntage_verringern_den_anteil_der_woche():
    verfuegbar = {woche(9): 0.0, woche(10): 0.5}  # Ferien, halbe Woche frei
    d = daten()
    assert bedarf_fuer_woche(d, woche(9), verfuegbar=verfuegbar).soll_minuten == 0
    halb = bedarf_fuer_woche(d, woche(10), verfuegbar=verfuegbar).soll_minuten
    voll = bedarf_fuer_woche(d, woche(11), verfuegbar=verfuegbar).soll_minuten
    assert halb == pytest.approx(voll / 2, abs=1) and voll == round(GESAMT / 1.5)


def test_rueckstand_im_fenster_wird_auf_die_restlichen_wochen_verteilt():
    # Fenster ab Woche 9, in Woche 9 nichts gelernt: ein Drittel Rückstand
    d = daten(erste_planwoche=woche(9), gelernt_je_woche={woche(9): 0})
    b = bedarf_fuer_woche(d, woche(10))
    assert b.rueckstand_minuten == GESAMT // 3
    assert b.soll_minuten == GESAMT // 2  # alles auf die zwei restlichen Wochen
    # Vorsprung senkt das Soll; was vor einem früheren Fenster gelernt wurde, zählt nicht
    vorne = bedarf_fuer_woche(daten(erste_planwoche=woche(9), gelernt_je_woche={woche(9): 2000}), woche(10))
    assert vorne.rueckstand_minuten < 0 and vorne.soll_minuten < b.plan_minuten
    frueher = bedarf_fuer_woche(daten(erste_planwoche=woche(2), gelernt_je_woche={woche(2): 5000}), woche(9))
    assert frueher.soll_minuten == frueher.plan_minuten


def test_wochen_vor_der_nutzung_des_hubs_erzeugen_keinen_rueckstand():
    # Erster Sync in Woche 10: Woche 9 zählt nicht als Rückstand
    b = bedarf_fuer_woche(daten(), woche(10))
    assert b.rueckstand_minuten == 0 and b.soll_minuten == b.plan_minuten


def test_stoff_verteilt_sich_bis_zur_pruefung():
    d = daten()
    assert bedarf_fuer_woche(d, woche(9)).stoff_anteil == pytest.approx(1 / 3)  # Wochen 9–11
    assert bedarf_fuer_woche(d, woche(11)).stoff_anteil == 1.0

def test_nachholen_pro_woche_bis_zur_pruefung():
    pro_woche, bis = nachholen_pro_woche(600, daten(), woche(5))
    assert bis == woche(11) + timedelta(days=2) and pro_woche == 100  # 6 Wochen bis zur Prüfungswoche
    pro_woche, bis = nachholen_pro_woche(600, daten(pruefungen=()), woche(5))
    assert bis is None and pro_woche == 150  # bis zur letzten Terminwoche
