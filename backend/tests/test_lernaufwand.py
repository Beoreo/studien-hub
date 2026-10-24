"""Stoffmenge je Unterlage, Prüfungen und Lernbedarf je Woche aus den ECTS (mit Datenbank)."""

import zipfile
from datetime import date, datetime, timedelta

import pytest
from fpdf import FPDF

import app.lernaufwand as lernaufwand
from app.lernaufwand import (
    bestimme_lernart,
    gelernte_minuten,
    grundaufwand_minuten,
    lerntage_verfuegbar,
    lva_plandaten,
    offene_unterlagen,
    pruefungen,
    pruefungstermine,
    seiten_und_format,
    wochenbedarf,
)
from app.models import STANDARD_LERNPARAMETER, Arbeitsregel, Dokument, FreierZeitraum, Lernblock, Lva, Pruefungstermin, Termin

MONTAG = date(2026, 10, 5)


@pytest.fixture
def ordner(tmp_path, monkeypatch):
    monkeypatch.setattr(lernaufwand, "UNTERLAGEN_ORDNER", tmp_path)
    return tmp_path


def pdf(pfad, seiten, quer=False):
    datei = FPDF(orientation="L" if quer else "P")
    for _ in range(seiten):
        datei.add_page()
    datei.output(str(pfad))
    return pfad


def zip_datei(pfad, inhalte: dict[str, bytes]):
    with zipfile.ZipFile(pfad, "w") as z:
        for name, inhalt in inhalte.items():
            z.writestr(name, inhalt)
    return pfad


def dok(**kw):
    basis = dict(lva_id=1, tuwel_kurs_id=1, tuwel_cm_id=1, schluessel="x", dateiname="skript.pdf", typ="pdf",
                 ist_link=False, quelle_url="u", abschnitt="", aktivitaet="")
    basis.update(kw)
    return Dokument(**basis)


# --- Seiten und Art ------------------------------------------------------------------------

def test_seiten_und_format(tmp_path):
    assert seiten_und_format(pdf(tmp_path / "skript.pdf", 7)) == (7, False)
    assert seiten_und_format(pdf(tmp_path / "folien.pdf", 4, quer=True)) == (4, True)
    pptx = zip_datei(tmp_path / "f.pptx", {f"ppt/slides/slide{i}.xml": b"<x/>" for i in range(1, 13)} | {"ppt/slides/_rels/slide1.xml.rels": b""})
    assert seiten_und_format(pptx) == (12, True)
    docx = zip_datei(tmp_path / "s.docx", {"docProps/app.xml": b"<Properties><Pages>9</Pages></Properties>", "word/document.xml": b""})
    assert seiten_und_format(docx) == (9, False)
    ohne_angabe = zip_datei(tmp_path / "t.docx", {"word/document.xml": ("<w>" + "wort " * 1050 + "</w>").encode()})
    assert seiten_und_format(ohne_angabe) == (3, False)
    (tmp_path / "kaputt.pdf").write_bytes(b"kein pdf")
    assert seiten_und_format(tmp_path / "kaputt.pdf") == (None, None)
    assert seiten_und_format(tmp_path / "code.zip") == (None, None)


def test_lernart():
    assert bestimme_lernart(dok(), quer=True) == "folien"
    assert bestimme_lernart(dok(), quer=False) == "skript"
    assert bestimme_lernart(dok(typ="folien", dateiname="vo3.pptx"), None) == "folien"
    assert bestimme_lernart(dok(dateiname="Übungsblatt 3.pdf"), quer=False) == "uebung"
    assert bestimme_lernart(dok(dateiname="angabe.pdf", aktivitaet="Hausübung 2"), None) == "uebung"
    assert bestimme_lernart(dok(dateiname="blatt4.pdf"), None) == "uebung"
    assert bestimme_lernart(dok(ist_link=True, typ="video"), None) == "video"
    assert bestimme_lernart(dok(typ="sonstiges", dateiname="code.zip"), None) == "sonstiges"


def test_grundaufwand_nach_art_und_lva_werten():
    p = dict(STANDARD_LERNPARAMETER)
    assert grundaufwand_minuten(dok(lernart="folien", seiten=30), p) == 60  # 30 × 2 min
    assert grundaufwand_minuten(dok(lernart="skript", seiten=10), p) == 60  # 10 × 6 min
    assert grundaufwand_minuten(dok(lernart="uebung"), p) == 180
    assert grundaufwand_minuten(dok(lernart="video", ist_link=True, dauer_sekunden=5400), p) == 135  # 90 min × 1,5
    assert grundaufwand_minuten(dok(lernart="video", ist_link=True), p) == 135  # unbekannte Dauer: 90 min
    assert grundaufwand_minuten(dok(lernart="folien", seiten=None), p) == 15  # Seiten unbekannt
    eigene = {**p, "minuten_pro_folie": 4, "video_faktor": 2}
    assert grundaufwand_minuten(dok(lernart="folien", seiten=30), eigene) == 120
    assert grundaufwand_minuten(dok(lernart="video", ist_link=True, dauer_sekunden=3600), eigene) == 120


# --- mit Datenbank -----------------------------------------------------------------------------

@pytest.fixture
def lva(session):
    lva = Lva(schluessel="185.A91", nummer="185.A91", titel="EP1", semester="2026W", ects=6)
    session.add(lva)
    session.commit()
    return lva


def unterlage(session, lva, ordner, name="folien1.pdf", seiten=30, quer=True, erschienen=datetime(2026, 10, 5, 9), cm=1, **kw):
    pdf(ordner / name, seiten, quer)
    d = Dokument(lva_id=lva.id, tuwel_kurs_id=1, tuwel_cm_id=cm, schluessel=name, dateiname=name, typ="pdf",
                 ist_link=False, quelle_url=name, pfad=name, erschienen_am=erschienen, erschienen_quelle="tuwel", **kw)
    session.add(d)
    session.commit()
    return d


def semester(session, lva, wochen=10, pruefung: datetime | None = None):
    """Je Woche 2 h VU ab MONTAG, optional ein Prüfungstermin aus TISS."""
    for w in range(wochen):
        start = datetime(2026, 10, 5, 10) + timedelta(weeks=w)
        session.add(Termin(lva_id=lva.id, typ="VU", titel="VU", start=start, ende=start + timedelta(hours=2)))
    if pruefung:
        session.add(Termin(lva_id=lva.id, typ="PRUEFUNG", titel="Prüfung", start=pruefung, ende=pruefung + timedelta(hours=2)))
    session.commit()


def test_offene_unterlagen_auch_alter_stoff_abzueglich_abgedecktem(session, lva, ordner):
    a = unterlage(session, lva, ordner, "a.pdf", seiten=30)  # 60 min Stoff
    alt = unterlage(session, lva, ordner, "alt.pdf", seiten=30, erschienen=datetime(2026, 9, 1), cm=2)  # alt, aber offen
    b = unterlage(session, lva, ordner, "b.pdf", seiten=15, erschienen=datetime(2026, 9, 25), cm=3)  # 30 min
    unterlage(session, lva, ordner, "spaeter.pdf", seiten=15, erschienen=datetime(2026, 10, 20), cm=4)  # erscheint später
    session.add(Lernblock(lva_id=lva.id, start=datetime(2026, 10, 1, 10), ende=datetime(2026, 10, 1, 10, 20),
                          status="bestaetigt", zuteilung={str(b.id): 20}))
    session.commit()
    offen = {o.dokument_id: o.minuten for o in offene_unterlagen(session, MONTAG)}
    assert offen == {a.id: 60, alt.id: 60, b.id: 10}
    session.refresh(a)
    assert (a.seiten, a.lernart) == (30, "folien")  # einmalig bestimmt und gespeichert


def test_eigene_stoffmenge_je_unterlage(session, lva, ordner):
    bericht = unterlage(session, lva, ordner, "jahresbericht.pdf", seiten=350, quer=False)
    skript = unterlage(session, lva, ordner, "skript.pdf", seiten=10, quer=False, cm=2)
    bericht.lern_minuten = 0  # Nachschlagematerial: nicht lernen
    skript.lern_minuten = 25
    session.commit()
    assert {o.dokument_id: o.minuten for o in offene_unterlagen(session, MONTAG)} == {skript.id: 25}


def pruefungstermin(session, lva, start, **kw):
    termin = Pruefungstermin(lva_id=lva.id, start=start, **kw)
    session.add(termin)
    session.commit()
    return termin


def test_angemeldete_pruefungstermine_zusammen_mit_dem_feed(session, lva):
    assert pruefungen(session, lva) == ()
    pruefungstermin(session, lva, datetime(2026, 12, 10, 9), angemeldet=True)
    pruefungstermin(session, lva, datetime(2027, 1, 29, 9), quelle="tuwel", extern_id="tuwel:1", angemeldet=True)
    pruefungstermin(session, lva, datetime(2027, 3, 5, 9), quelle="tiss", extern_id="tiss:2")  # nur angeboten
    assert pruefungstermine(session, lva) == [(datetime(2026, 12, 10, 9), "manuell"), (datetime(2027, 1, 29, 9), "tuwel")]
    # Prüfung aus dem TISS-Feed am selben Tag ersetzt den Termin, andere bleiben
    session.add(Termin(lva_id=lva.id, typ="PRUEFUNG", titel="Prüfung", start=datetime(2027, 1, 29, 14),
                       ende=datetime(2027, 1, 29, 16)))
    session.commit()
    assert pruefungstermine(session, lva) == [(datetime(2026, 12, 10, 9), "manuell"), (datetime(2027, 1, 29, 14), "tiss")]
    assert pruefungen(session, lva) == (datetime(2026, 12, 10, 9), datetime(2027, 1, 29, 14))


def test_ohne_anmeldung_gilt_der_naechste_termin_als_vorschlag(session, lva):
    a = pruefungstermin(session, lva, datetime(2026, 11, 20, 9), quelle="tiss", extern_id="tiss:a")
    b = pruefungstermin(session, lva, datetime(2027, 1, 22, 9), quelle="tiss", extern_id="tiss:b")
    assert pruefungstermine(session, lva, heute=date(2026, 10, 24)) == [(a.start, "vorschlag")]
    assert pruefungstermine(session, lva, heute=date(2026, 12, 1)) == [(b.start, "vorschlag")]
    a.angemeldet = b.angemeldet = False  # „bei keinem Termin angemeldet“
    session.commit()
    assert pruefungstermine(session, lva, heute=date(2026, 10, 24)) == []
    b.angemeldet, b.tiss_angemeldet = None, True  # automatisch: TISS meldet die Anmeldung
    session.commit()
    assert pruefungstermine(session, lva, heute=date(2026, 10, 24)) == [(b.start, "tiss")]


def test_plandaten_mit_mehreren_angemeldeten_pruefungen(session, lva):
    semester(session, lva, wochen=10)
    pruefungstermin(session, lva, datetime(2026, 11, 20, 9), angemeldet=True)
    pruefungstermin(session, lva, datetime(2027, 1, 22, 9), angemeldet=True)
    daten = lva_plandaten(session, lva, MONTAG)
    assert daten.pruefungen == (date(2026, 11, 20), date(2027, 1, 22))
    assert daten.ende_woche == date(2027, 1, 18)  # verteilt bis zur letzten Prüfung


def test_plandaten_praesenz_semester_und_gelernte_zeit(session, lva):
    semester(session, lva, wochen=10, pruefung=datetime(2026, 12, 16, 9))
    session.add(Termin(lva_id=lva.id, typ="ABGABE", titel="Abgabe", start=datetime(2026, 10, 9, 23), ende=datetime(2026, 10, 9, 23)))
    session.add_all([
        Lernblock(lva_id=lva.id, start=datetime(2026, 10, 6, 14), ende=datetime(2026, 10, 6, 16), status="bestaetigt",
                  tatsaechliche_minuten=60, erledigt=True),  # eingetragen: 60 statt 120 min
        Lernblock(lva_id=lva.id, start=datetime(2026, 10, 13, 14), ende=datetime(2026, 10, 13, 15), status="bestaetigt"),
    ])
    session.commit()
    d = lva_plandaten(session, lva, MONTAG + timedelta(weeks=2))
    assert d.praesenz_minuten == 10 * 120  # ohne Prüfung und Abgabe
    assert (d.erste_woche, d.letzte_woche, d.pruefungen) == (MONTAG, MONTAG + timedelta(weeks=9), (date(2026, 12, 16),))
    assert d.ende_woche == date(2026, 12, 14)
    assert d.erste_planwoche == MONTAG and d.gelernt_vorher == 60 + 60
    assert gelernte_minuten(session.scalars(__import__("sqlalchemy").select(Lernblock)).first()) == 60


def test_wochenbedarf_aus_ects_statt_aus_seiten(session, lva, ordner):
    # 20 h Präsenz, Prüfung am Mittwoch der Woche 9; gelernt wird in den 9 Wochen davor und in der Prüfungswoche
    semester(session, lva, wochen=10, pruefung=datetime(2026, 12, 9, 9))
    for i in range(30):  # 30 Skripte mit 100 Seiten = 300 h geschätzter Stoff
        unterlage(session, lva, ordner, f"s{i}.pdf", seiten=100, quer=False, cm=i + 1)
    regel = Arbeitsregel(id=1, lernphase_wochen=9)
    (bedarf, daten), = wochenbedarf(session, MONTAG, regel)
    # (150 h − 20 h) × 0,7 × 0,8 = 72,8 h über 10 Wochen
    assert bedarf.gesamt_minuten == round(130 * 60 * 0.56)
    # ein Zehntel, etwas mehr: die Wochen mit Nationalfeiertag und Mariä Empfängnis haben einen Lerntag weniger
    assert round(130 * 60 * 0.56 / 10) < bedarf.soll_minuten < round(130 * 60 * 0.56 / 9)
    assert bedarf.pruefung == date(2026, 12, 9) and bedarf.lernphase
    assert wochenbedarf(session, MONTAG) == []  # Standard 2 Wochen: Anfang Oktober noch kein Lernbedarf

    regel = Arbeitsregel(id=1, stunden_pro_woche=10, ects_faktor=1.0, lernphase_wochen=9)
    lva.ziel, lva.bedarf_faktor = "bestehen", 0.5
    session.commit()
    (bedarf, _), = wochenbedarf(session, MONTAG, regel)
    assert bedarf.gesamt_minuten == round(130 * 60 * 1.0 * 0.6 * 0.5)


def test_ferien_zaehlen_weniger(session, lva):
    session.add(FreierZeitraum(tiss_uid="f", bezeichnung="Herbstferien", von=date(2026, 10, 12), bis=date(2026, 10, 18)))
    session.commit()
    anteile = lerntage_verfuegbar(None, MONTAG, MONTAG + timedelta(weeks=2), session)
    assert anteile[MONTAG + timedelta(weeks=1)] == 0 and anteile[MONTAG + timedelta(weeks=2)] == 1
    assert anteile[MONTAG] == 1


def test_lva_ohne_termine_und_ohne_pruefung_hat_keinen_bedarf(session, lva):
    assert wochenbedarf(session, MONTAG) == []


def test_abschnittsname_macht_noch_kein_uebungsblatt():
    assert bestimme_lernart(dok(dateiname="Präsentation_HTL.pdf", abschnitt="Übungen"), quer=True) == "folien"
    assert bestimme_lernart(dok(dateiname="Angabe_Welle.pdf", abschnitt="Übungen"), quer=False) == "uebung"
