"""STEOP-Kriterien aus TISS auswerten und eine Variante wählen."""

from app.steop_kriterien import (
    auswerten,
    erfuellte_kriterien,
    gesamt_erfuellt,
    nummern,
    pflicht_nummern,
    titel_normal,
    variante_waehlen,
    zuordnen,
)


def lva(nummer, ects=None, erfuellt=None):
    return {"art": "lva", "nummer": nummer, "titel": f"LVA {nummer}", "ects": ects, "erfuellt": erfuellt}


def knoten(art, wert, *kinder, name=None, erfuellt=None):
    return {"name": name, "art": art, "wert": wert, "erfuellt": erfuellt, "kinder": list(kinder)}


# P4: 9 ECTS aus: 1 aus (BWL 4 | VWL 3), 1 aus (Mathe 9 | Statistik 5), Alle aus (Mechanik VO 4, UE 2)
P4 = knoten(
    "ects", 9,
    knoten("anzahl", 1, lva("330.001", 4), lva("330.002", 3)),
    knoten("anzahl", 1, lva("104.297", 9), lva("107.001", 5)),
    knoten("alle", None, lva("302.001", 4), lva("302.002", 2)),
    name="P4",
)


def test_bewertung_ects_anzahl_alle():
    ects = {}
    assert erfuellte_kriterien([P4], set(), ects) == [False]
    assert erfuellte_kriterien([P4], {"104.297"}, ects) == [True]  # 9 ECTS über einen Zweig
    assert erfuellte_kriterien([P4], {"330.001", "302.001"}, ects) == [False]  # Alle aus unvollständig: nur 4
    assert erfuellte_kriterien([P4], {"330.001", "302.001", "302.002"}, ects) == [True]  # 4 + 6
    assert erfuellte_kriterien([P4], {"330.002", "107.001"}, ects) == [False]  # 3 + 5 = 8 < 9
    assert nummern([P4]) == {"330.001", "330.002", "104.297", "107.001", "302.001", "302.002"}


def test_in_tiss_erledigt_zaehlt_mit():
    erledigt = knoten("ects", 9, knoten("anzahl", 1, lva("330.001", 4, erfuellt=True)), lva("107.001", 5), name="P1")
    assert erfuellte_kriterien([erledigt], {"107.001"}, {}) == [True]
    assert erfuellte_kriterien([knoten("alle", None, lva("1", 1), erfuellt=True)], set(), {}) == [True]


def test_verknuepfung_und_pflicht():
    p1 = knoten("alle", None, lva("100.001", 3), lva("100.002", 3), name="P1")
    p2 = knoten("anzahl", 1, lva("200.001", 3), lva("200.002", 3), name="P2")
    assert gesamt_erfuellt([p1, p2], "OR", {"200.002"}, {}) and not gesamt_erfuellt([p1, p2], "AND", {"200.002"}, {})
    assert pflicht_nummern([p1, p2]) == {"100.001", "100.002"}
    assert pflicht_nummern([p1, p2], "OR") == set()
    assert pflicht_nummern([P4]) == set()  # unter einem ECTS-Kriterium ist nichts Pflicht


def test_variante_minimal_nach_ects():
    # Hub-LVAs: 1 = BWL, 2 = VWL, 3 = Mathe, 4 = Statistik, 5 = Mechanik (VO + UE als Teile)
    angebot = {1: {"330.001"}, 2: {"330.002"}, 3: {"104.297"}, 4: {"107.001"}, 5: {"302.001", "302.002"}}
    ects = {1: 4, 2: 3, 3: 9, 4: 5, 5: 6}
    assert variante_waehlen([P4], "AND", angebot, ects) == {3}  # 9 ECTS mit einer LVA
    # Mathe nicht angeboten: billigste Kombination mit ≥ 9 ECTS – BWL 4 + Statistik 5 (gleich teuer wie VWL + Mechanik)
    ohne_mathe = {i: n for i, n in angebot.items() if i != 3}
    assert variante_waehlen([P4], "AND", ohne_mathe, ects) == {1, 4}


def test_variante_nimmt_pflicht_auch_wenn_nicht_erfuellbar():
    p1 = knoten("alle", None, lva("100.001", 3), lva("100.002", 3), name="P1")  # 100.002 erst im Sommer
    p2 = knoten("anzahl", 1, lva("200.001", 3), lva("200.002", 6), name="P2")
    angebot = {1: {"100.001"}, 2: {"200.001"}, 3: {"200.002"}, 4: {"999.999"}}
    assert variante_waehlen([p1, p2], "AND", angebot, {1: 3, 2: 3, 3: 6, 4: 6}) == {1, 2}
    # OR: ein Kriterium genügt
    assert variante_waehlen([p1, p2], "OR", angebot, {1: 3, 2: 3, 3: 6, 4: 6}) == {2}


def test_lvas_ohne_nummer_ueber_den_titel_zuordnen():
    p3 = knoten("alle", None, {"art": "lva", "nummer": None, "titel": "VO Mechanik 1", "ects": 4, "erfuellt": None},
                {"art": "lva", "nummer": None, "titel": "UE Mechanik 1 2026W", "ects": 2, "erfuellt": None},
                {"art": "lva", "nummer": None, "titel": "Darstellende Geometrie", "ects": 3, "erfuellt": None}, name="P3")
    lvas = [(1, "Mechanik 1", set()), (2, "Mechanik 12", set()), (3, "Darstellende Geometrie für WIMB", {"104.001"})]
    angebot = zuordnen([p3], lvas)
    assert angebot[1] == {"titel:vo:mechanik 1", "titel:ue:mechanik 1"}  # LVA ohne Typ: beide landen hier
    assert angebot[2] == set()  # „Mechanik 12“ ist nicht „Mechanik 1“
    assert angebot[3] == {"104.001", "titel:darstellende geometrie"}  # enthält den Titel
    assert titel_normal("VU Grundlagen der BWL (2026W)") == "grundlagen der bwl"
    assert variante_waehlen([p3], "AND", angebot, {1: 6, 2: 6, 3: 3}) == {1, 3}  # Alle aus: beide Pflicht


def test_auswertung_fuer_die_anzeige():
    angebot = {1: {"330.001"}, 3: {"104.297"}}
    [p4] = auswerten([P4], angebot, {3}, {1: 4, 3: 9})
    assert p4["erfuellt_variante"] is True
    bwl, vwl = p4["kinder"][0]["kinder"]
    assert (bwl["lva_id"], bwl["in_variante"]) == (1, False)
    assert vwl["lva_id"] is None  # dieses Semester nicht angeboten
    assert p4["kinder"][1]["kinder"][0]["in_variante"] is True


def test_vo_und_ue_gleichen_titels_ueber_den_typ_zuordnen():
    """VO und UE sind eigene LVAs mit gleichem Titel: der Typ im Blatt entscheidet."""
    p = {"name": "P1", "art": "alle", "kinder": [
        {"art": "lva", "nummer": None, "titel": "VO Mechanik 1", "ects": 4.0},
        {"art": "lva", "nummer": None, "titel": "UE Mechanik 1", "ects": 2.0},
    ]}
    lvas = [(1, "Mechanik 1", {"309.019"}, "VO"), (2, "Mechanik 1", {"309.021"}, "UE")]
    angebot = zuordnen([p], lvas)
    assert angebot[1] == {"309.019", "titel:vo:mechanik 1"} and angebot[2] == {"309.021", "titel:ue:mechanik 1"}
    # ohne Typ im Blatt: wie bisher die erste passende LVA
    nur_titel = {"name": "P2", "art": "alle", "kinder": [{"art": "lva", "nummer": None, "titel": "Mechanik 1"}]}
    assert zuordnen([nur_titel], lvas)[1] == {"309.019", "titel:mechanik 1"}
