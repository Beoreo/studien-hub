"""Schätzung des Lernaufwands, Korrektur aus Rückmeldungen, Lernbedarf je Woche und ECTS-Abgleich."""

import zipfile
from datetime import date, datetime, timedelta

import pytest
from fpdf import FPDF

import app.lernaufwand as lernaufwand
from app.lernaufwand import (
    Korrektur,
    bestimme_lernart,
    grundaufwand_minuten,
    korrekturfaktor,
    offene_unterlagen,
    seiten_und_format,
    semesterwochen,
    wochenbedarf,
)
from app.models import STANDARD_LERNPARAMETER, Dokument, Lernblock, Lva, Termin

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


def test_korrekturfaktor_lernt_aus_rueckmeldungen(session, lva):
    assert korrekturfaktor(session, lva.id) == Korrektur(1.0, 0)
    for _ in range(3):  # jeweils 60 min geplant, 120 min gebraucht
        session.add(Lernblock(lva_id=lva.id, start=datetime(2026, 10, 5, 10), ende=datetime(2026, 10, 5, 11),
                              tatsaechliche_minuten=120, erledigt=True, status="bestaetigt"))
    session.commit()
    k = korrekturfaktor(session, lva.id)
    assert k.rueckmeldungen == 3 and k.faktor == pytest.approx((360 + 120) / (180 + 120), abs=0.01)  # 1,6
    # ohne eingetragene Zeit zählt ein Block nicht
    session.add(Lernblock(lva_id=lva.id, start=datetime(2026, 10, 6, 10), ende=datetime(2026, 10, 6, 11), erledigt=True))
    session.commit()
    assert korrekturfaktor(session, lva.id).rueckmeldungen == 3


def test_offene_unterlagen_abzueglich_eingeplanter_zeit(session, lva, ordner):
    a = unterlage(session, lva, ordner, "a.pdf", seiten=30)  # 60 min
    unterlage(session, lva, ordner, "alt.pdf", seiten=30, erschienen=datetime(2026, 9, 1), cm=2)  # zu alt
    b = unterlage(session, lva, ordner, "b.pdf", seiten=15, erschienen=datetime(2026, 9, 25), cm=3)  # Rückstand: 30 min
    session.add(Lernblock(lva_id=lva.id, start=datetime(2026, 10, 1, 10), ende=datetime(2026, 10, 1, 10, 20),
                          status="bestaetigt", zuteilung={str(b.id): 20}))
    session.commit()
    offen = {o.dokument_id: o.minuten for o in offene_unterlagen(session, MONTAG)}
    assert offen == {a.id: 60, b.id: 10}
    # Seitenzahl und Art wurden dabei einmalig bestimmt und gespeichert
    session.refresh(a)
    assert (a.seiten, a.lernart) == (30, "folien")


def test_wochenbedarf_mit_ects_abgleich(session, lva, ordner):
    # 6 ECTS = 150 h; Termine über 10 Wochen -> Soll 15 h pro Woche
    for woche in range(10):
        start = datetime(2026, 10, 5, 10) + timedelta(weeks=woche)
        session.add(Termin(lva_id=lva.id, typ="VU", titel="VU", start=start, ende=start + timedelta(hours=2)))
    session.commit()
    assert semesterwochen(session, lva) == 10

    unterlage(session, lva, ordner, "skript.pdf", seiten=100, quer=False)  # 600 min
    bedarf = wochenbedarf(session, MONTAG)[0]
    assert (bedarf.unterlagen_minuten, bedarf.praesenz_minuten, bedarf.soll_minuten) == (600, 120, 900)
    assert bedarf.warnung is None  # 12 h zu 15 h liegt innerhalb ±50 %

    unterlage(session, lva, ordner, "skript2.pdf", seiten=200, quer=False, cm=2)  # +1200 min
    bedarf = wochenbedarf(session, MONTAG)[0]
    assert "deutlich über dem ECTS-Soll von 15,0 h (6 ECTS)" in bedarf.warnung
    assert bedarf.warnung.startswith("EP1: 32,0 h diese Woche")

    # ohne Unterlagen nur 2 h Präsenz: deutlich unter dem Soll
    spaeter = wochenbedarf(session, MONTAG + timedelta(weeks=1))[0]
    assert "unter" in spaeter.warnung
    # strengere Schwelle
    assert wochenbedarf(session, MONTAG, warnschwelle=0.1)[0].warnung


def test_wochenbedarf_ohne_ects_ohne_warnung(session, lva, ordner):
    lva.ects = None
    session.commit()
    unterlage(session, lva, ordner)
    bedarf = wochenbedarf(session, MONTAG)[0]
    assert bedarf.soll_minuten is None and bedarf.warnung is None
    assert bedarf.unterlagen[0]["lernart"] == "folien" and bedarf.unterlagen[0]["minuten"] == 60


def test_abschnittsname_macht_noch_kein_uebungsblatt():
    assert bestimme_lernart(dok(dateiname="Präsentation_HTL.pdf", abschnitt="Übungen"), quer=True) == "folien"
    assert bestimme_lernart(dok(dateiname="Angabe_Welle.pdf", abschnitt="Übungen"), quer=False) == "uebung"


def test_eigene_lernzeit_je_unterlage(session, lva, ordner):
    bericht = unterlage(session, lva, ordner, "jahresbericht.pdf", seiten=350, quer=False)  # geschätzt 35 h
    skript = unterlage(session, lva, ordner, "skript.pdf", seiten=10, quer=False, cm=2)
    bericht.lern_minuten = 0  # Nachschlagematerial: nicht lernen
    skript.lern_minuten = 25  # eigene Einschätzung statt 60 min
    session.commit()
    offen = {o.dokument_id: o.minuten for o in offene_unterlagen(session, MONTAG)}
    assert offen == {skript.id: 25}
    assert wochenbedarf(session, MONTAG)[0].unterlagen_minuten == 25
