"""Stufe 3: Textextraktion, Abschnitte, semantische Suche (sqlite-vec + Volltext), Verarbeitung und Transkripte."""

import hashlib
import zipfile
from datetime import datetime

import httpx
import pytest
from fpdf import FPDF
from sqlalchemy import select

import app.verarbeitung as verarbeitung
from app.db import VEKTORSUCHE
from app.embedding import HashEmbedder
from app.extraktion import (
    AbschnittRoh,
    Text,
    abschnitte_bilden,
    docx_lesen,
    folien_lesen,
    pdf_lesen,
    transkript_abschnitte,
    ueberschriften_erkennen,
)
from app.models import Abschnitt, Dokument, Lva
from app.suche import abschnitte_speichern, suchen

STATIK = "Das Kräftegleichgewicht verlangt, dass die Summe aller Kräfte und Momente verschwindet. Freikörperbild zeichnen."
REIBUNG = "Die Haftreibung begrenzt die übertragbare Tangentialkraft: Coulombsches Reibungsgesetz mit Reibungszahl mu."
KINEMATIK = "Geschwindigkeit und Beschleunigung eines Punktes in Polarkoordinaten; Bahnkurve und Tangentialbeschleunigung."


def skript_pdf(pfad, mit_inhaltsverzeichnis=True):
    pdf = FPDF()
    pdf.set_font("helvetica", size=11)
    for nr, (titel, text) in enumerate([("Statik", STATIK), ("Reibung", REIBUNG), ("Kinematik", KINEMATIK)], start=1):
        for teil in range(2):
            pdf.add_page()
            if teil == 0:
                if mit_inhaltsverzeichnis:
                    pdf.start_section(f"{nr} {titel}")
                pdf.cell(0, 10, f"{nr} {titel}", new_x="LMARGIN", new_y="NEXT")
            pdf.multi_cell(0, 6, (text + " ") * 6)
    pdf.output(str(pfad))
    return pfad


# --- Extraktion ---------------------------------------------------------------------------------------

def test_pdf_mit_inhaltsverzeichnis_ergibt_kapitel_und_seiten(tmp_path):
    gelesen = pdf_lesen(skript_pdf(tmp_path / "skript.pdf"))
    assert [(p.ebene, p.titel, p.seite) for p in gelesen.gliederung] == [(1, "1 Statik", 1), (1, "2 Reibung", 3), (1, "3 Kinematik", 5)]
    abschnitte = abschnitte_bilden(gelesen)
    assert {a.kapitel for a in abschnitte} == {"1 Statik", "2 Reibung", "3 Kinematik"}
    reibung = [a for a in abschnitte if a.kapitel == "2 Reibung"]
    assert all(3 <= a.seite_von <= a.seite_bis <= 4 for a in reibung)  # nie über die Kapitelgrenze
    assert all(len(a.text) <= 1500 + 2 for a in abschnitte)


def test_ueberschriften_ohne_inhaltsverzeichnis(tmp_path):
    gelesen = pdf_lesen(skript_pdf(tmp_path / "ohne.pdf", mit_inhaltsverzeichnis=False))
    assert [p.titel for p in gelesen.gliederung] == ["1 Statik", "2 Reibung", "3 Kinematik"]
    # Inhaltsverzeichnis am Anfang, Zahlen im Fließtext und Aufzählungen sind keine Kapitel
    seiten = [(1, "Inhalt\n1 Einleitung\n2 Statik\n"), (2, "1 Einleitung\nText 12 kg wiegt 3 Teile.\n"),
              (3, "2 Statik\n1 Hinweis zur Aufgabe\n"), (4, "2.1 Kräfte\nWeiter.\n"), (5, "9 Zahlen sind keine Kapitel\n")]
    assert [(p.titel, p.seite) for p in ueberschriften_erkennen(seiten)] == [
        ("1 Einleitung", 1), ("2 Statik", 1), ("2.1 Kräfte", 4)]


def test_kurze_folien_werden_zusammengelegt_lange_seiten_geteilt():
    gelesen = Text(seiten=[(1, "Titel"), (2, "Kurz"), (3, "x" * 4000)], art="folien")
    abschnitte = abschnitte_bilden(gelesen)
    assert abschnitte[0].text == "Titel\n\nKurz" and (abschnitte[0].seite_von, abschnitte[0].seite_bis) == (1, 2)
    lang = abschnitte[1:]  # eine lange Seite: eigene Abschnitte, jeder höchstens 1500 Zeichen
    assert len(lang) == 3 and all(a.seite_von == a.seite_bis == 3 and len(a.text) <= 1500 for a in lang)


def test_folien_und_word(tmp_path):
    pptx = tmp_path / "vo.pptx"
    with zipfile.ZipFile(pptx, "w") as z:
        for i, text in enumerate(["Einführung", "Kräftepaar &amp; Moment"], start=1):
            z.writestr(f"ppt/slides/slide{i}.xml", f"<p:sld><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:sld>")
    assert folien_lesen(pptx).seiten == [(1, "Einführung"), (2, "Kräftepaar & Moment")]
    docx = tmp_path / "ausarbeitung.docx"
    with zipfile.ZipFile(docx, "w") as z:
        z.writestr("word/document.xml",
                   '<w:document><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Reibung</w:t></w:r></w:p>'
                   "<w:p><w:r><w:t>Haftreibung und Gleitreibung.</w:t></w:r></w:p></w:document>")
    gelesen = docx_lesen(docx)
    assert gelesen.gliederung[0].titel == "Reibung"
    (a,) = abschnitte_bilden(gelesen)
    assert a.kapitel == "Reibung" and a.seite_von is None


def test_transkript_in_zeitfenster():
    segmente = [(0, 20, "Heute Reibung."), (20, 80, "Coulomb."), (95, 120, "Nun Kinematik."), (200, 230, "Polarkoordinaten.")]
    abschnitte = transkript_abschnitte(segmente, fenster=90)
    assert [(a.zeit_von, a.zeit_bis) for a in abschnitte] == [(0, 80), (95, 120), (200, 230)]
    assert abschnitte[0].text == "Heute Reibung. Coulomb."


# --- Suche ---------------------------------------------------------------------------------------------

@pytest.fixture
def lvas(session):
    mech = Lva(schluessel="mech", titel="Mechanik 1", semester="2026W")
    mathe = Lva(schluessel="mathe", titel="Mathematik 1", semester="2026W")
    session.add_all([mech, mathe])
    session.commit()
    return mech, mathe


def dokument(session, lva, name, quelle="tuwel", jahr=None, **kw):
    d = Dokument(lva_id=lva.id, tuwel_kurs_id=1, tuwel_cm_id=len(name), schluessel=name, dateiname=name, typ="pdf",
                 quelle_url="u", quelle=quelle, jahr=jahr, erschienen_am=datetime(2026, 10, 5), **kw)
    session.add(d)
    session.flush()
    return d


def test_vektorsuche_ist_verfuegbar(session):
    assert VEKTORSUCHE["verfuegbar"], "sqlite-vec sollte geladen sein"


def test_semantische_suche_mit_herkunft(session, lvas):
    mech, mathe = lvas
    e = HashEmbedder()
    skript = dokument(session, mech, "Skript Mechanik.pdf")
    abschnitte_speichern(session, skript, [
        AbschnittRoh(STATIK, "1 Statik", "1 Statik", 3, 3), AbschnittRoh(REIBUNG, "2 Reibung", "2 Reibung", 12, 13)], "tuwel", e)
    video = dokument(session, mech, "VO 4 Aufzeichnung", ist_link=True)
    abschnitte_speichern(session, video, [AbschnittRoh("Reibungszahl mu bestimmt die Haftreibung", zeit_von=754, zeit_bis=830)],
                         "lecturetube", e)
    abschnitte_speichern(session, dokument(session, mathe, "Analysis.pdf"), [AbschnittRoh(KINEMATIK, "Kurven", None, 1, 1)], "tuwel", e)
    session.commit()

    treffer = suchen(session, "Wie funktioniert die Haftreibung nach Coulomb?", embedder=e)
    erster = treffer[0].als_dict()
    assert erster["kapitel"] == "2 Reibung" and erster["fundstelle"] == "S. 12–13" and erster["quelle"] == "tuwel"
    assert erster["offiziell"] and erster["dokument"] == "Skript Mechanik.pdf" and erster["lva"] == "Mechanik 1"
    assert treffer[0].vektor_rang is not None and treffer[0].volltext_rang is not None
    zeitmarke = next(t.als_dict() for t in treffer if t.abschnitt.quelle == "lecturetube")
    assert zeitmarke["fundstelle"] == "12:34 min" and zeitmarke["zeit_von"] == 754

    # LVA-Filter
    nur_mathe = suchen(session, "Bahnkurve Beschleunigung", lva_id=mathe.id, embedder=e)
    assert nur_mathe and all(t.abschnitt.lva_id == mathe.id for t in nur_mathe)


def test_offizielle_unterlagen_vor_mb_cloud(session, lvas):
    mech, _ = lvas
    e = HashEmbedder()
    abschnitte_speichern(session, dokument(session, mech, "2024-Gedankenprotokoll.pdf", quelle="mbcloud", jahr=2024),
                         [AbschnittRoh(REIBUNG)], "mbcloud", e)
    abschnitte_speichern(session, dokument(session, mech, "Skript.pdf"), [AbschnittRoh(REIBUNG)], "tuwel", e)
    session.commit()
    treffer = [t.als_dict() for t in suchen(session, "Haftreibung Reibungszahl", embedder=e)]
    assert [t["quelle"] for t in treffer] == ["tuwel", "mbcloud"]
    assert treffer[1]["offiziell"] is False and treffer[1]["jahr"] == 2024
    assert [t.abschnitt.quelle for t in suchen(session, "Haftreibung", embedder=e, nur_offiziell=True)] == ["tuwel"]


def test_volltext_ohne_modell(session, lvas):
    mech, _ = lvas
    abschnitte_speichern(session, dokument(session, mech, "Skript.pdf"), [AbschnittRoh(STATIK), AbschnittRoh(REIBUNG)], "tuwel", None)
    session.commit()
    treffer = suchen(session, "Reibungsgesetz", embedder=None)  # Präfixsuche: „Reibungsgesetz“ trifft
    assert len(treffer) == 1 and "Coulombsches" in treffer[0].abschnitt.text
    assert suchen(session, "a", embedder=None) == []


def test_neu_verarbeiten_ersetzt_abschnitte(session, lvas):
    mech, _ = lvas
    e = HashEmbedder()
    doc = dokument(session, mech, "Skript.pdf")
    abschnitte_speichern(session, doc, [AbschnittRoh(STATIK), AbschnittRoh(REIBUNG)], "tuwel", e)
    abschnitte_speichern(session, doc, [AbschnittRoh(KINEMATIK)], "tuwel", e)
    session.commit()
    assert session.query(Abschnitt).count() == 1
    # alte Einträge auch aus Vektor- und Volltextindex weg: nur noch der neue Abschnitt kann kommen
    assert [t.abschnitt.text for t in suchen(session, "Haftreibung Coulomb", embedder=e)] in ([], [KINEMATIK])
    assert suchen(session, "Haftreibung Coulomb", embedder=None) == []


# --- Verarbeitung und Transkripte ---------------------------------------------------------------------

def test_unterlagen_verarbeiten(session, lvas, tmp_path, monkeypatch):
    monkeypatch.setattr(verarbeitung, "UNTERLAGEN_ORDNER", tmp_path)
    mech, _ = lvas
    skript_pdf(tmp_path / "skript.pdf")
    (tmp_path / "kaputt.pdf").write_bytes(b"kein pdf")
    gut = dokument(session, mech, "skript.pdf", pfad="skript.pdf", pruefsumme="a1", lernart="skript")
    kaputt = dokument(session, mech, "kaputt.pdf", pfad="kaputt.pdf", pruefsumme="b1")
    mb = dokument(session, mech, "Altpruefung.pdf", quelle="mbcloud", jahr=2025, pfad="skript.pdf", pruefsumme="c1")
    session.commit()

    assert verarbeitung.verarbeite_offene(session, HashEmbedder()) == {"fertig": 2, "leer": 0, "fehler": 1}
    assert kaputt.text_status == "fehler" and kaputt.text_fehler
    abschnitte = session.scalars(select(Abschnitt).where(Abschnitt.dokument_id == gut.id)).all()
    assert abschnitte and abschnitte[0].kapitel == "1 Statik" and abschnitte[0].seite_von == 1
    mb_abschnitt = session.scalar(select(Abschnitt).where(Abschnitt.dokument_id == mb.id))
    assert (mb_abschnitt.quelle, mb_abschnitt.offiziell, mb_abschnitt.jahr) == ("mbcloud", False, 2025)

    assert verarbeitung.offene_dokumente(session) == []  # nichts doppelt
    gut.pruefsumme = "a2"  # neue Fassung aus TUWEL
    session.commit()
    assert verarbeitung.offene_dokumente(session) == [gut]
    status = verarbeitung.status(session)
    assert status["dokumente_fehler"] == 1 and status["abschnitte"] > 0 and status["vektorsuche"]


class FakeWhisper:
    def __init__(self):
        self.pfade = []

    def transkribieren(self, pfad):
        self.pfade.append(pfad)
        assert pfad.read_bytes() == b"VIDEO"
        return [(0.0, 30.0, "Heute geht es um Reibung."), (30.0, 60.0, "Coulomb gilt.")]


def test_transkription_im_hintergrund(session, lvas):
    mech, _ = lvas
    ok = dokument(session, mech, "VO 3", ist_link=True, episode_id="e1", medien_url="https://opencast.test/ok.mp4")
    alt = dokument(session, mech, "VO 2", ist_link=True, episode_id="e2", medien_url="https://opencast.test/abgelaufen.mp4")
    session.commit()
    transport = httpx.MockTransport(lambda r: httpx.Response(200, content=b"VIDEO") if r.url.path == "/ok.mp4" else httpx.Response(403))
    whisper = FakeWhisper()

    erster = verarbeitung.transkribiere_naechstes(session, whisper, HashEmbedder(), transport)
    zweiter = verarbeitung.transkribiere_naechstes(session, whisper, HashEmbedder(), transport)
    assert {erster.id, zweiter.id} == {ok.id, alt.id}
    assert ok.transkript_status == "fertig" and alt.transkript_status == "fehler" and "nicht mehr gültig" in alt.transkript_fehler
    (a,) = session.scalars(select(Abschnitt).where(Abschnitt.dokument_id == ok.id)).all()
    assert (a.quelle, a.zeit_von, a.zeit_bis) == ("lecturetube", 0, 60)
    assert not whisper.pfade[0].exists()  # heruntergeladenes Video wieder gelöscht
    assert verarbeitung.transkribiere_naechstes(session, whisper, None, transport) is None  # nichts mehr offen


def test_ueberschriften_ueber_schriftgroesse_statt_aufzaehlungen(tmp_path):
    """Skript ohne Inhaltsverzeichnis: Überschriften groß und fett, Aufzählungen im Fließtext („3. Schritt …“)."""
    pdf = FPDF()
    for nr, titel in enumerate(["URFORMEN", "UMFORMEN"], start=1):
        pdf.add_page()
        pdf.set_font("helvetica", "B", 16)
        pdf.cell(0, 10, f"{nr} {titel}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("helvetica", size=12)
        for schritt in range(1, 4):
            pdf.cell(0, 8, f"{schritt}. Schritt: Formkasten vorbereiten", new_x="LMARGIN", new_y="NEXT")
        pdf.multi_cell(0, 6, "Fliesstext " * 80)
    pdf.output(str(tmp_path / "gft.pdf"))
    gliederung = pdf_lesen(tmp_path / "gft.pdf").gliederung
    assert [(p.titel, p.seite) for p in gliederung] == [("1 URFORMEN", 1), ("2 UMFORMEN", 2)]
