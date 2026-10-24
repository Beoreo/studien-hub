"""Freie Zeiträume aus TISS und LVA-Teile (VO, UE, Gruppen) – Import, Planung, Bereinigung."""

import json
import sqlite3
from datetime import date, datetime, time, timedelta

import pytest
from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.lva_struktur import (
    beim_start_bereinigen,
    bereinige_datenbank,
    braucht_bereinigung,
    freier_name,
    gruppen_schluessel,
    ist_freier_eintrag,
    zerlege_gruppe,
)
from app.models import (
    Dokument,
    FreierZeitraum,
    Lernblock,
    Lva,
    LvaTeil,
    Termin,
    TuwelKurs,
    lies_einstellung,
    setze_einstellung,
)
from app.tiss_import import importiere_ical

# --- Erkennen und Zerlegen --------------------------------------------------------------------


@pytest.mark.parametrize("titel", [
    "Nationalfeiertag, vorlesungsfrei", "Osterferien, vorlesungsfrei", "Rektorstag, vorlesungsfrei",
    "Weihnachtsferien", "Tag des Landespatrons, vorlesungsfrei", "Allerseelen, vorlesungsfrei", "Semesterferien",
])
def test_freie_eintraege_werden_erkannt(titel):
    assert ist_freier_eintrag(titel)


@pytest.mark.parametrize("titel, nummer", [
    ("Mathematik 1 für MB", "104.297"), ("185.A91 VU Einführung", None), ("Ferienkurs Analysis 104.111", None),
    ("Mechanik 1", None),
])
def test_lvas_sind_keine_freien_eintraege(titel, nummer):
    assert not ist_freier_eintrag(titel, nummer)


def test_namen_und_gruppen():
    assert freier_name("Osterferien, vorlesungsfrei") == "Osterferien"
    assert freier_name("Rektorstag") == "Rektorstag"
    assert zerlege_gruppe("Mathematik 1 für MB, WIMB und VT - Gruppe 8") == ("Mathematik 1 für MB, WIMB und VT", "Gruppe 8")
    assert zerlege_gruppe("Mechanik 1") == ("Mechanik 1", None)
    assert gruppen_schluessel("Mathematik 1 für MB, WIMB und VT - Gruppe 8") == gruppen_schluessel("Mathematik 1 für MB, WIMB und VT")
    assert gruppen_schluessel("Mechanik 1 (VO 4,0)") == gruppen_schluessel("Mechanik 1")


# --- Import --------------------------------------------------------------------------------

def ics(*ereignisse: str) -> str:
    return "BEGIN:VCALENDAR\nVERSION:2.0\n" + "".join(ereignisse) + "END:VCALENDAR\n"


def ereignis(uid, summary, start, ende, ganztag=False):
    art = ";VALUE=DATE" if ganztag else ";TZID=Europe/Vienna"
    return f"BEGIN:VEVENT\nUID:{uid}\nDTSTART{art}:{start}\nDTEND{art}:{ende}\nSUMMARY:{summary}\nEND:VEVENT\n"


FEED = ics(
    ereignis("v1", "104.297 VO Mathematik 1 für MB, WIMB und VT", "20261005T090000", "20261005T110000"),
    ereignis("v2", "104.297 VO Mathematik 1 für MB, WIMB und VT", "20261007T090000", "20261007T110000"),
    ereignis("u1", "104.604 UE Mathematik 1 für MB, WIMB und VT - Gruppe 8", "20261006T160000", "20261006T180000"),
    ereignis("u2", "104.604 UE Mathematik 1 für MB, WIMB und VT - Gruppe 3", "20261008T160000", "20261008T180000"),
    ereignis("p1", "Prüfung 104.297 Mathematik 1 für MB, WIMB und VT", "20270130T090000", "20270130T110000"),
    ereignis("m1", "309.019 VO Mechanik 1", "20261005T130000", "20261005T150000"),
    ereignis("f1", "Nationalfeiertag, vorlesungsfrei", "20261026", "20261027", ganztag=True),
    ereignis("f2", "Weihnachtsferien, vorlesungsfrei", "20261224", "20270107", ganztag=True),
)


def test_import_eine_lva_je_nummer_und_freie_zeiten(session):
    ergebnis = importiere_ical(session, FEED, neu_planen=False)
    assert ergebnis.neu == 6 and ergebnis.freie_zeitraeume == 2

    lvas = {l.nummer: l for l in session.scalars(select(Lva))}
    assert set(lvas) == {"104.297", "104.604", "309.019"}  # VO und UE getrennt, keine Ferien-LVAs
    vo, ue = lvas["104.297"], lvas["104.604"]
    assert (vo.titel, vo.typ, ue.titel, ue.typ) == ("Mathematik 1 für MB, WIMB und VT", "VO", "Mathematik 1 für MB, WIMB und VT", "UE")
    assert (vo.anzeigename, ue.anzeigename) == ("Mathematik 1 für MB, WIMB und VT VO", "Mathematik 1 für MB, WIMB und VT UE")
    assert [(t.nummer, t.typ, t.gruppe) for t in vo.teile] == [("104.297", "VO", None)]
    assert [(t.nummer, t.typ, t.gruppe) for t in ue.teile] == [("104.604", "UE", "Gruppe 8"), ("104.604", "UE", "Gruppe 3")]
    assert (len(vo.termine), len(ue.termine)) == (3, 2)
    assert any(t.typ == "PRUEFUNG" for t in vo.termine)  # Prüfung landet bei ihrer Nummer
    assert next(t for t in ue.termine if t.tiss_uid == "u1").anzeigename == "Mathematik 1 für MB, WIMB und VT UE Gruppe 8"

    freie = {z.bezeichnung: (z.von, z.bis) for z in session.scalars(select(FreierZeitraum))}
    assert freie == {
        "Nationalfeiertag": (date(2026, 10, 26), date(2026, 10, 26)),
        "Weihnachtsferien": (date(2026, 12, 24), date(2027, 1, 6)),
    }

    # erneuter Import: nichts doppelt
    zweiter = importiere_ical(session, FEED, neu_planen=False)
    assert (zweiter.neu, zweiter.geaendert, zweiter.freie_zeitraeume) == (0, 0, 0)
    assert session.query(LvaTeil).count() == 4 and session.query(FreierZeitraum).count() == 2

    # Ferien aus dem Feed entfernt -> freier Zeitraum gelöscht
    ohne_weihnachten = FEED.replace(ereignis("f2", "Weihnachtsferien, vorlesungsfrei", "20261224", "20270107", ganztag=True), "")
    importiere_ical(session, ohne_weihnachten, neu_planen=False)
    assert [z.bezeichnung for z in session.scalars(select(FreierZeitraum))] == ["Nationalfeiertag"]


def test_markierungen_je_teil(session):
    importiere_ical(session, FEED, neu_planen=False)
    vo, gruppe8 = session.scalars(select(LvaTeil).order_by(LvaTeil.id)).all()[:2]
    vo.aufzeichnung = True
    gruppe8.anwesenheitspflicht = True
    session.commit()
    termine = {t.tiss_uid: t for t in session.scalars(select(Termin))}
    assert termine["v1"].wird_aufgezeichnet and not termine["v1"].hat_anwesenheitspflicht
    assert termine["u1"].hat_anwesenheitspflicht and not termine["u1"].wird_aufgezeichnet
    assert not termine["u2"].hat_anwesenheitspflicht  # andere Gruppe, eigene Markierung


def test_plenartermine_ohne_gruppe_gehoeren_zum_teil_ihrer_nummer(session):
    """TISS nennt die Gruppe nicht bei jedem Termin derselben Nummer – kein zweiter Teil, Markierungen bleiben."""
    feed = ics(
        ereignis("p1", "309.021 UE Mechanik 1", "20261005T090000", "20261005T110000"),
        ereignis("g1", "309.021 UE Mechanik 1 - Gruppe 22", "20261006T090000", "20261006T110000"),
        ereignis("p2", "309.021 UE Mechanik 1", "20261007T090000", "20261007T110000"),
    )
    importiere_ical(session, feed, neu_planen=False)
    (teil,) = session.scalars(select(LvaTeil)).all()
    assert (teil.typ, teil.gruppe) == ("UE", "Gruppe 22")
    teil.anwesenheitspflicht = True
    session.commit()

    zweiter = importiere_ical(session, feed, neu_planen=False)
    assert (zweiter.neu, zweiter.geaendert) == (0, 0) and session.query(LvaTeil).count() == 1
    assert all(t.hat_anwesenheitspflicht for t in session.scalars(select(Termin)))

    # eine weitere Gruppe derselben Nummer ist ein eigener Teil und übernimmt die Markierungen als Vorgabe
    importiere_ical(session, ics(ereignis("g2", "309.021 UE Mechanik 1 - Gruppe 5", "20261008T090000", "20261008T110000")),
                    neu_planen=False)
    gruppe5 = session.scalar(select(LvaTeil).where(LvaTeil.gruppe == "Gruppe 5"))
    assert gruppe5.lva_id == teil.lva_id and gruppe5.typ == "UE" and gruppe5.anwesenheitspflicht


# --- Freie Zeiten sperren Arbeit und Lernen --------------------------------------------------------

def test_tiss_ferien_sperren_arbeit_und_lernen(client, session, tmp_path, monkeypatch):
    import app.lernaufwand as lernaufwand
    from fpdf import FPDF

    monkeypatch.setattr(lernaufwand, "UNTERLAGEN_ORDNER", tmp_path)
    importiere_ical(session, FEED, neu_planen=False)
    # Mo–Mi der Woche ab 26.10. zusätzlich als „Ferien“ aus TISS
    session.add(FreierZeitraum(tiss_uid="x", bezeichnung="Herbstferien", von=date(2026, 10, 27), bis=date(2026, 10, 28)))
    mathe = session.scalar(select(Lva).where(Lva.titel.like("Mathematik%")))
    mathe.ects = 9  # Lernzeit kommt aus den ECTS – nur im Fenster vor einer Prüfung
    session.add(Termin(lva_id=mathe.id, typ="PRUEFUNG", titel="Prüfung", start=datetime(2026, 11, 6, 9),
                       ende=datetime(2026, 11, 6, 11)))
    datei = FPDF()
    for _ in range(40):
        datei.add_page()
    datei.output(str(tmp_path / "skript.pdf"))
    session.add(Dokument(lva_id=mathe.id, tuwel_kurs_id=1, tuwel_cm_id=1, schluessel="s", dateiname="skript.pdf", typ="pdf",
                         ist_link=False, quelle_url="u", pfad="skript.pdf", erschienen_am=datetime(2026, 10, 26, 8)))
    session.commit()
    client.put("/api/arbeit/regel", json={"stunden_pro_woche": 12, "tage": [0, 1, 2, 3, 4], "lern_tage": [0, 1, 2, 3, 4, 5]})

    v = client.post("/api/arbeit/vorschlag", params={"woche": "2026-10-26"}).json()
    gesperrt = {date(2026, 10, 26), date(2026, 10, 27), date(2026, 10, 28)}  # Nationalfeiertag + Herbstferien
    tage = {datetime.fromisoformat(b["start"]).date() for b in v["bloecke"] + v["lernbloecke"]}
    assert v["lernbloecke"] and v["bloecke"]
    assert not tage & gesperrt

    events = client.get("/api/kalender", params={"von": "2026-10-26T00:00:00", "bis": "2026-11-02T00:00:00"}).json()
    ganztaegig = [(e["start"], e["title"]) for e in events if e.get("allDay")]
    assert ("2026-10-26", "Nationalfeiertag") in ganztaegig  # gesetzlicher Name hat Vorrang
    assert ("2026-10-27", "Frei: Herbstferien") in ganztaegig
    assert not any("vorlesungsfrei" in e["title"] for e in events)


# --- Bereinigung der bestehenden Datenbank --------------------------------------------------------

def alte_datenbank(session):
    """Stand vor dieser Version: jede TISS-LVA einzeln, Ferien als LVA, Markierungen an der LVA."""
    def lva(titel, nummer, semester="2026W", **kw):
        l = Lva(schluessel=nummer or titel, nummer=nummer, titel=titel, semester=semester, **kw)
        session.add(l)
        session.flush()
        return l

    def termin(l, uid, typ, tag, **kw):
        start = datetime(2026, 10, tag, 9)
        session.add(Termin(lva_id=l.id, tiss_uid=uid, typ=typ, titel=l.titel, start=start, ende=start + timedelta(hours=2), **kw))

    vo = lva("Mathematik 1 für MB, WIMB und VT", "104.297", farbe="#9333ea", steop=True, aufzeichnung=True,
             tuwel_kurs_id=83611, kurzname="Mathe 1", ects=None)
    ue = lva("Mathematik 1 für MB, WIMB und VT - Gruppe 8", "104.604", farbe="#ca8a04", anwesenheitspflicht=True,
             tuwel_kurs_id=84754, ects=4.0, lernparameter={"video_faktor": 2.0})
    vo_ss = lva("Mathematik 1 für MB, WIMB und VT", "104.297", semester="2027S")
    frei = lva("Osterferien, vorlesungsfrei", None, semester="2027S")
    for i, tag in enumerate((5, 7)):
        termin(vo, f"vo{i}", "VO", tag)
    termin(ue, "ue0", "UE", 6, anwesenheit_abweichung=False)  # eigene Abweichung an einem Termin
    termin(vo_ss, "ss0", "VO", 9)
    session.add(Termin(lva_id=frei.id, tiss_uid="ostern", typ="SONSTIGE", titel=frei.titel,
                       start=datetime(2027, 3, 22), ende=datetime(2027, 4, 5)))
    session.add_all([
        Dokument(lva_id=vo.id, tuwel_kurs_id=83611, tuwel_cm_id=1, schluessel="a", dateiname="a.pdf", typ="pdf", quelle_url="u"),
        Dokument(lva_id=ue.id, tuwel_kurs_id=84754, tuwel_cm_id=2, schluessel="b", dateiname="b.pdf", typ="pdf", quelle_url="u"),
        Lernblock(lva_id=ue.id, start=datetime(2026, 10, 8, 10), ende=datetime(2026, 10, 8, 11), tatsaechliche_minuten=90),
        TuwelKurs(id=83611, kurzname="104.297-2026W", lva_id=vo.id),
        TuwelKurs(id=84754, kurzname="104.604-2026W", lva_id=ue.id),
    ])
    session.commit()
    return {"vo": vo.id, "ue": ue.id, "vo_ss": vo_ss.id, "frei": frei.id}


def test_bereinigung_ohne_markierungen_zu_verlieren(session):
    ids = alte_datenbank(session)
    setze_einstellung(session, "lva_struktur", None)
    session.commit()
    assert braucht_bereinigung(session)

    bericht = bereinige_datenbank(session)
    assert bericht.freie_zeitraeume == ["Osterferien (2027S)"]
    assert session.get(Lva, ids["frei"]) is None
    assert [(z.bezeichnung, z.von, z.bis) for z in session.scalars(select(FreierZeitraum))] == [
        ("Osterferien", date(2027, 3, 22), date(2027, 4, 4))
    ]

    # VO und UE-Gruppe bleiben eigene LVAs (mit Typ); das Sommersemester auch
    vo, ue = session.get(Lva, ids["vo"]), session.get(Lva, ids["ue"])
    assert (vo.titel, vo.typ, ue.titel, ue.typ) == ("Mathematik 1 für MB, WIMB und VT", "VO", "Mathematik 1 für MB, WIMB und VT", "UE")
    assert (vo.farbe, vo.kurzname, ue.ects, ue.lernparameter) == ("#9333ea", "Mathe 1", 4.0, {"video_faktor": 2.0})
    (teil_vo,), (teil_ue,) = vo.teile, ue.teile
    assert (teil_vo.typ, teil_vo.steop, teil_vo.aufzeichnung, teil_vo.tuwel_kurs_id) == ("VO", True, True, 83611)
    assert (teil_ue.typ, teil_ue.gruppe, teil_ue.anwesenheitspflicht, teil_ue.tuwel_kurs_id) == ("UE", "Gruppe 8", True, 84754)
    assert (vo.schluessel, ue.schluessel) == ("104.297", "104.604")
    assert session.get(Lva, ids["vo_ss"]).semester == "2027S"
    assert bericht.getrennt == []

    # Termine hängen an ihrem Teil, Abweichungen bleiben, Markierungen wirken wie vorher
    termine = {t.tiss_uid: t for t in session.scalars(select(Termin))}
    assert termine["vo0"].teil.nummer == "104.297" and termine["vo0"].wird_aufgezeichnet and termine["vo0"].ist_steop
    assert termine["ue0"].teil.gruppe == "Gruppe 8" and termine["ue0"].anwesenheit_abweichung is False
    assert not termine["ue0"].hat_anwesenheitspflicht  # die Abweichung gilt weiterhin
    assert "ostern" not in termine

    # zweiter Lauf ändert nichts
    assert not braucht_bereinigung(session)
    vorher = session.query(Lva).count(), session.query(LvaTeil).count()
    bereinige_datenbank(session)
    assert (session.query(Lva).count(), session.query(LvaTeil).count()) == vorher


def test_zusammengefasste_lva_wird_getrennt(session):
    """Stand der Version 2: VO und UE gleichen Titels unter einer LVA – jede Nummer wird wieder eine eigene LVA."""
    from app.lva_auswahl import VARIANTE_SCHLUESSEL

    mathe = Lva(schluessel="mathematik 1", nummer="104.297", titel="Mathematik 1", semester="2026W", farbe="#2a6a8f",
                ects=6, ziel="gut", kurzname=None)
    mathe.teile = [LvaTeil(nummer="104.297", typ="VO", tuwel_kurs_id=83611),
                   LvaTeil(nummer="104.604", typ="UE", gruppe="Gruppe 8", tuwel_kurs_id=84754, anwesenheitspflicht=True)]
    session.add(mathe)
    session.flush()
    vo_teil, ue_teil = mathe.teile
    for uid, teil, tag in (("v", vo_teil, 5), ("u", ue_teil, 6)):
        start = datetime(2026, 10, tag, 9)
        session.add(Termin(lva_id=mathe.id, teil_id=teil.id, tiss_uid=uid, typ=teil.typ, titel="x", start=start,
                           ende=start + timedelta(hours=2)))
    session.add_all([
        TuwelKurs(id=83611, lva_id=mathe.id), TuwelKurs(id=84754, lva_id=mathe.id),
        Dokument(lva_id=mathe.id, tuwel_kurs_id=84754, tuwel_cm_id=2, schluessel="b", dateiname="ue.pdf", typ="pdf", quelle_url="u"),
        Dokument(lva_id=mathe.id, tuwel_kurs_id=83611, tuwel_cm_id=1, schluessel="a", dateiname="vo.pdf", typ="pdf", quelle_url="u"),
    ])
    setze_einstellung(session, VARIANTE_SCHLUESSEL, json.dumps({"semester": "2026W", "ids": [mathe.id]}))
    setze_einstellung(session, "lva_struktur", "2")
    session.commit()

    bericht = bereinige_datenbank(session)
    session.expire_all()
    vo = session.get(Lva, mathe.id)
    ue = session.scalar(select(Lva).where(Lva.nummer == "104.604"))
    assert bericht.getrennt == ["Mathematik 1 (2026W): UE 104.604"]
    assert (vo.typ, vo.schluessel, vo.ects, [t.nummer for t in vo.teile]) == ("VO", "104.297", 6, ["104.297"])
    assert (ue.typ, ue.schluessel, ue.ects, ue.ziel, ue.anwesenheitspflicht) == ("UE", "104.604", None, "gut", True)
    assert ue.farbe != vo.farbe
    assert [t.tiss_uid for t in ue.termine] == ["u"] and [t.tiss_uid for t in vo.termine] == ["v"]
    assert {d.dateiname: d.lva_id for d in session.scalars(select(Dokument))} == {"vo.pdf": vo.id, "ue.pdf": ue.id}
    assert session.get(TuwelKurs, 84754).lva_id == ue.id
    assert sorted(json.loads(lies_einstellung(session, VARIANTE_SCHLUESSEL))["ids"]) == sorted([vo.id, ue.id])

    # der nächste Import ordnet die Termine den getrennten LVAs zu, ohne neue anzulegen
    importiere_ical(session, ics(
        ereignis("v", "104.297 VO Mathematik 1", "20261005T090000", "20261005T110000"),
        ereignis("u", "104.604 UE Mathematik 1 - Gruppe 8", "20261006T090000", "20261006T110000"),
    ), neu_planen=False)
    assert session.query(Lva).count() == 2


def test_bereinigung_nimmt_gruppe_aus_den_terminen(session):
    """Die alte LVA hieß nach einem Plenartermin; die Gruppe steht nur in den übrigen Termintiteln."""
    ue = Lva(schluessel="309.021", nummer="309.021", titel="Mechanik 1", semester="2026W", anwesenheitspflicht=True)
    session.add(ue)
    session.flush()
    for tag, titel in ((5, "309.021 UE Mechanik 1"), (6, "309.021 UE Mechanik 1 - Gruppe 22")):
        start = datetime(2026, 10, tag, 9)
        session.add(Termin(lva_id=ue.id, tiss_uid=f"t{tag}", typ="UE", titel=titel, start=start, ende=start + timedelta(hours=2)))
    setze_einstellung(session, "lva_struktur", None)
    session.commit()

    bereinige_datenbank(session)
    (teil,) = session.scalars(select(LvaTeil)).all()
    assert (teil.typ, teil.gruppe, teil.anwesenheitspflicht) == ("UE", "Gruppe 22", True)

    # der nächste Import ordnet beide Titelformen diesem Teil zu
    importiere_ical(session, ics(
        ereignis("t5", "309.021 UE Mechanik 1", "20261005T090000", "20261005T110000"),
        ereignis("t6", "309.021 UE Mechanik 1 - Gruppe 22", "20261006T090000", "20261006T110000"),
    ), neu_planen=False)
    assert session.query(LvaTeil).count() == 1
    assert {t.teil_id for t in session.scalars(select(Termin))} == {teil.id}


def test_bereinigung_beim_start_mit_sicherung(tmp_path):
    url = f"sqlite:///{(tmp_path / 'hub.db').as_posix()}"
    engine = init_db(url)
    with SessionLocal() as session:
        alte_datenbank(session)
        setze_einstellung(session, "lva_struktur", None)  # wie eine Datenbank vor dieser Version
        session.commit()

    bericht = beim_start_bereinigen(SessionLocal, url)
    assert bericht and bericht.sicherung
    sicherung = sqlite3.connect(bericht.sicherung)
    assert sicherung.execute("select count(*) from lva").fetchone()[0] == 4  # Stand vor dem Umbau
    sicherung.close()
    with SessionLocal() as session:
        assert session.query(Lva).count() == 3  # Ferien-LVA weg, VO und UE getrennt
        gespeichert = json.loads(lies_einstellung(session, "lva_struktur_bericht"))
        assert gespeichert["freie_zeitraeume"] == ["Osterferien (2027S)"] and gespeichert["sicherung"]
    assert beim_start_bereinigen(SessionLocal, url) is None  # nur einmal
    assert len(list(tmp_path.glob("hub.vor-lva-umbau-*.db"))) == 1
    engine.dispose()


def test_neue_datenbank_braucht_keine_sicherung(tmp_path):
    url = f"sqlite:///{(tmp_path / 'leer.db').as_posix()}"
    engine = init_db(url)  # bereinigt beim Start selbst – bei leerer Datenbank ohne Sicherungskopie
    with SessionLocal() as session:
        assert not braucht_bereinigung(session)
    assert beim_start_bereinigen(SessionLocal, url) is None
    assert not list(tmp_path.glob("*.vor-lva-umbau-*.db"))
    engine.dispose()


# --- API -------------------------------------------------------------------------------------------

def test_api_zeigt_teile_und_aendert_markierungen_je_teil(client, session):
    importiere_ical(session, FEED, neu_planen=False)
    lvas = client.get("/api/lvas").json()
    mathe = next(l for l in lvas if l["nummer"] == "104.604")
    assert mathe["typ"] == "UE"
    assert [(t["bezeichnung"], t["nummer"], t["anzahl_termine"]) for t in mathe["teile"]] == [
        ("UE Gruppe 8", "104.604", 1), ("UE Gruppe 3", "104.604", 1),
    ]
    gruppe8 = mathe["teile"][0]
    geaendert = client.patch(f"/api/lvas/teile/{gruppe8['id']}", json={"anwesenheitspflicht": True, "tuwel_kurs_id": 84754}).json()
    assert geaendert["anwesenheitspflicht"] and geaendert["tuwel_kurs_id"] == 84754
    assert client.patch("/api/lvas/teile/9999", json={"steop": True}).status_code == 404

    termin = next(t for t in client.get("/api/termine").json() if t["teil_bezeichnung"] == "UE Gruppe 8")
    assert termin["anwesenheitspflicht"] and termin["lva_anwesenheitspflicht"]
    # Markierung an der LVA gilt als Vorgabe für alle Teile
    client.patch(f"/api/lvas/{mathe['id']}", json={"steop": True, "ects": 6})
    mathe = next(l for l in client.get("/api/lvas").json() if l["id"] == mathe["id"])
    assert all(t["steop"] for t in mathe["teile"]) and mathe["ects"] == 6


def test_tuwel_kurse_landen_bei_der_lva_ihrer_nummer(client, session):
    importiere_ical(session, FEED, neu_planen=False)
    schluessel = client.get("/api/tuwel/einrichtung").json()["schluessel"]
    kurse = client.post("/api/tuwel/sync/kurse", headers={"X-Studienhub-Schluessel": schluessel}, json={"kurse": [
        {"id": 83611, "kurzname": "104.297-2026W", "name": "104.297 Mathematik 1 (VO 4,0) 2026W"},
        {"id": 84754, "kurzname": "104.604-2026W", "name": "104.604 Mathematik 1 (UE 2,0) 2026W"},
    ]}).json()["kurse"]
    nummer = {l.id: l.nummer for l in session.scalars(select(Lva))}
    assert [nummer[k["lva_id"]] for k in kurse] == ["104.297", "104.604"]
    session.expire_all()  # die API schreibt in einer eigenen Session
    teile =[(t.nummer, t.gruppe, t.tuwel_kurs_id) for t in session.scalars(select(LvaTeil).order_by(LvaTeil.id))]
    assert teile[:3] == [("104.297", None, 83611), ("104.604", "Gruppe 8", 84754), ("104.604", "Gruppe 3", 84754)]


def test_api_freie_zeitraeume_und_bericht(client, session):
    importiere_ical(session, FEED, neu_planen=False)
    freie = client.get("/api/tiss/freie-zeitraeume").json()
    assert [(z["bezeichnung"], z["von"], z["bis"]) for z in freie] == [
        ("Nationalfeiertag", "2026-10-26", "2026-10-26"), ("Weihnachtsferien", "2026-12-24", "2027-01-06"),
    ]
    assert client.get("/api/tiss/einstellungen").json()["bereinigung"] is None


def test_alte_standardfarben_werden_umgestellt(session):
    from app.db import farben_umstellen
    from app.models import ALTE_STANDARD_FARBEN, STANDARD_FARBEN

    alt = Lva(schluessel="a", titel="A", semester="2026W", farbe=ALTE_STANDARD_FARBEN[2].upper())
    eigen = Lva(schluessel="b", titel="B", semester="2026W", farbe="#123456")
    session.add_all([alt, eigen])
    session.commit()
    assert farben_umstellen(session.get_bind()) == 1
    session.expire_all()
    assert (alt.farbe, eigen.farbe) == (STANDARD_FARBEN[2], "#123456")
    assert farben_umstellen(session.get_bind()) == 0  # mehrfach aufrufbar


def test_altes_pruefungsdatum_wird_in_die_liste_uebernommen(session):
    from sqlalchemy import text

    from app.db import pruefungen_uebernehmen

    lva = Lva(schluessel="a", titel="A", semester="2026W")
    session.add(lva)
    session.commit()
    session.execute(text("UPDATE lva SET pruefung_am = '2027-01-20' WHERE id = :id"), {"id": lva.id})
    session.commit()
    assert pruefungen_uebernehmen(session.get_bind()) == 1
    session.expire_all()
    assert lva.eigene_pruefungen == ["2027-01-20"]
    assert session.execute(text("SELECT pruefung_am FROM lva")).scalar() is None
    assert pruefungen_uebernehmen(session.get_bind()) == 0  # mehrfach aufrufbar
