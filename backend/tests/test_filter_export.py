from datetime import datetime

from icalendar import Calendar

from app.export import als_csv, als_ical, als_pdf, eintrag_aus_block, eintrag_aus_termin, sammle_eintraege
from app.filter import Filter, arbeitsbloecke_filtern, termin_hat_markierung, termine_filtern
from app.models import STATUS_BESTAETIGT, STATUS_VORSCHLAG, Arbeitsblock, Lva, Termin


def befuelle(session):
    algebra = Lva(schluessel="104.271", nummer="104.271", titel="Algebra", semester="2026W",
                  farbe="#ff0000", steop=True, aufzeichnung=True)
    ep1 = Lva(schluessel="185.A91", nummer="185.A91", titel="Programmierung", semester="2026W", farbe="#00ff00")
    session.add_all([algebra, ep1])
    session.flush()
    session.add_all([
        Termin(lva_id=algebra.id, typ="VO", titel="Algebra VO", start=datetime(2026, 10, 5, 9), ende=datetime(2026, 10, 5, 11)),
        Termin(lva_id=ep1.id, typ="UE", titel="EP1 UE", start=datetime(2026, 10, 6, 9), ende=datetime(2026, 10, 6, 11),
               anwesenheit_abweichung=True, ort="EI 7"),
        Termin(lva_id=ep1.id, typ="VU", titel="EP1 VU", start=datetime(2026, 11, 2, 9), ende=datetime(2026, 11, 2, 11)),
        Arbeitsblock(start=datetime(2026, 10, 7, 8), ende=datetime(2026, 10, 7, 12), status=STATUS_BESTAETIGT, arbeitgeber="Firma"),
        Arbeitsblock(start=datetime(2026, 10, 8, 8), ende=datetime(2026, 10, 8, 10), status=STATUS_VORSCHLAG, art="flexibel"),
        Arbeitsblock(start=datetime(2026, 11, 3, 8), ende=datetime(2026, 11, 3, 12), status=STATUS_BESTAETIGT),
    ])
    session.commit()
    return algebra, ep1


def test_termin_markierungen_mit_abweichung(session):
    befuelle(session)
    ue = termine_filtern(session, Filter(typen=["UE"]))[0]
    assert termin_hat_markierung(ue, "anwesenheit") is True
    assert termin_hat_markierung(ue, "steop") is False


def test_filter_nach_lva_typ_und_zeitraum(session):
    algebra, ep1 = befuelle(session)
    assert len(termine_filtern(session, Filter())) == 3
    assert [t.typ for t in termine_filtern(session, Filter(lva_ids=[ep1.id]))] == ["UE", "VU"]
    assert [t.typ for t in termine_filtern(session, Filter(typen=["VO", "UE"]))] == ["VO", "UE"]
    oktober = Filter(von=datetime(2026, 10, 1), bis=datetime(2026, 11, 1))
    assert len(termine_filtern(session, oktober)) == 2
    assert len(arbeitsbloecke_filtern(session, oktober)) == 2


def test_filter_nach_markierung(session):
    befuelle(session)
    steop = termine_filtern(session, Filter(markierungen=["steop"]))
    assert [t.titel for t in steop] == ["Algebra VO"]
    pflicht_oder_aufz = termine_filtern(session, Filter(markierungen=["anwesenheit", "aufzeichnung"]))
    assert [t.titel for t in pflicht_oder_aufz] == ["Algebra VO", "EP1 UE"]


def test_filter_arbeit(session):
    befuelle(session)
    assert termine_filtern(session, Filter(arbeit="nur")) == []
    assert arbeitsbloecke_filtern(session, Filter(arbeit="ohne")) == []
    assert len(arbeitsbloecke_filtern(session, Filter(arbeit="nur"))) == 3
    assert len(arbeitsbloecke_filtern(session, Filter(vorschlaege=False))) == 2


def test_eintraege_und_ical_export(session):
    befuelle(session)
    eintraege = sammle_eintraege(termine_filtern(session, Filter()), arbeitsbloecke_filtern(session, Filter()))
    assert [e.start for e in eintraege] == sorted(e.start for e in eintraege)
    kalender = Calendar.from_ical(als_ical(eintraege))
    ereignisse = list(kalender.walk("VEVENT"))
    assert len(ereignisse) == 6
    algebra = next(e for e in ereignisse if "Algebra" in str(e["SUMMARY"]))
    assert "STEOP" in str(algebra["SUMMARY"])
    assert algebra.decoded("DTSTART").hour == 9


def test_csv_export_mit_summe(session):
    befuelle(session)
    nur_arbeit = Filter(arbeit="nur", von=datetime(2026, 10, 1), bis=datetime(2026, 11, 1), vorschlaege=False)
    eintraege = sammle_eintraege([], arbeitsbloecke_filtern(session, nur_arbeit))
    text = als_csv(eintraege).decode("utf-8-sig")
    zeilen = text.strip().split("\r\n")
    assert zeilen[0].startswith("Art;Titel;LVA-Nummer")
    assert len(zeilen) == 3  # Kopf, ein Block, Summe
    assert "07.10.2026;08:00;12:00;4,00" in zeilen[1]
    assert zeilen[2].startswith("Summe Arbeit") and "4,00" in zeilen[2]


def test_pdf_export(session):
    befuelle(session)
    eintraege = [eintrag_aus_termin(t) for t in termine_filtern(session, Filter())]
    eintraege += [eintrag_aus_block(b) for b in arbeitsbloecke_filtern(session, Filter())]
    pdf = als_pdf(eintraege, "Test – Übersicht")
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000
