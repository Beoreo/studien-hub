from datetime import date, datetime, time

from sqlalchemy import select

from app.models import TYP_PRUEFUNG, TYP_UE, TYP_VO, TYP_VU, Arbeitsblock, Arbeitsregel, Lva, Termin
from app.tiss_import import (
    importiere_ical,
    importiere_termine,
    parse_ical,
    semester_von,
    zerlege_zusammenfassung,
    zu_lokaler_zeit,
)


def test_zerlege_zusammenfassung_mit_nummer():
    assert zerlege_zusammenfassung("185.A91 VU Einführung in die Programmierung 1") == (
        "185.A91", "Einführung in die Programmierung 1", "VU",
    )


def test_zerlege_zusammenfassung_kurzform_ohne_nummer():
    assert zerlege_zusammenfassung("EP1 VU") == (None, "EP1", "VU")


def test_zerlege_zusammenfassung_nummer_aus_beschreibung():
    nummer, titel, typ = zerlege_zusammenfassung("Analysis VO", "101.123 VO Analysis")
    assert (nummer, titel, typ) == ("101.123", "Analysis", "VO")


def test_semester_von():
    assert semester_von(datetime(2026, 10, 5)) == "2026W"
    assert semester_von(datetime(2027, 1, 20)) == "2026W"
    assert semester_von(datetime(2027, 2, 10)) == "2026W"
    assert semester_von(datetime(2027, 3, 1)) == "2027S"


def test_zu_lokaler_zeit_rechnet_utc_um():
    from zoneinfo import ZoneInfo

    utc = datetime(2026, 10, 7, 12, 0, tzinfo=ZoneInfo("UTC"))
    assert zu_lokaler_zeit(utc) == datetime(2026, 10, 7, 14, 0)  # Sommerzeit: UTC+2
    assert zu_lokaler_zeit(date(2026, 10, 7)) == datetime(2026, 10, 7)


def test_parse_ical(tiss_ics):
    termine = parse_ical(tiss_ics)
    assert len(termine) == 5
    erster = termine[0]
    assert erster.lva_nummer == "185.A91"
    assert erster.typ == TYP_VU
    assert erster.start == datetime(2026, 10, 5, 10, 0)
    assert erster.ort == "GM 1 Audi. Max."
    assert termine[1].start == datetime(2026, 10, 7, 14, 0)  # UTC-Zeit umgerechnet
    assert [t.typ for t in termine[2:]] == [TYP_VO, TYP_UE, TYP_PRUEFUNG]
    assert termine[4].lva_titel == "Einführung in die Programmierung 1"


def test_import_ordnet_lvas_zu(session, tiss_ics):
    ergebnis = importiere_ical(session, tiss_ics)
    assert (ergebnis.neu, ergebnis.geaendert, ergebnis.geloescht) == (5, 0, 0)
    lvas = {l.nummer: l for l in session.scalars(select(Lva))}
    assert set(lvas) == {"185.A91", "104.271", "104.272"}
    assert lvas["185.A91"].titel == "Einführung in die Programmierung 1"
    assert lvas["185.A91"].semester == "2026W"
    assert len(lvas["185.A91"].termine) == 3  # zwei VU-Termine + Prüfung
    assert len({l.farbe for l in lvas.values()}) == 3  # unterschiedliche Farben


def test_erneuter_import_uebernimmt_nur_aenderungen(session, tiss_ics):
    importiere_ical(session, tiss_ics)
    termin = session.scalar(select(Termin).where(Termin.tiss_uid == "tiss-2001@tiss.tuwien.ac.at"))
    termin.anwesenheit_abweichung = True  # eigene Abweichung
    session.commit()

    unveraendert = importiere_ical(session, tiss_ics)
    assert (unveraendert.neu, unveraendert.geaendert, unveraendert.geloescht, unveraendert.unveraendert) == (0, 0, 0, 5)

    geaendert = tiss_ics.replace(b"20261006T090000", b"20261006T100000").replace(
        b"20261006T110000", b"20261006T120000"
    )
    geaendert = geaendert.replace(b"UID:tiss-2002", b"UID:tiss-2099")  # einer weg, einer neu
    ergebnis = importiere_ical(session, geaendert)
    assert (ergebnis.neu, ergebnis.geaendert, ergebnis.geloescht, ergebnis.unveraendert) == (1, 1, 1, 3)
    assert ergebnis.betroffene_wochen == {date(2026, 10, 5)}

    session.refresh(termin)
    assert termin.start == datetime(2026, 10, 6, 10, 0)
    assert termin.anwesenheit_abweichung is True  # Abweichung bleibt erhalten


def test_import_plant_betroffene_wochen_neu(session, tiss_ics):
    session.add(Arbeitsregel(id=1, stunden_pro_woche=10, tage=[0, 1, 2, 3, 4],
                             fruehester_beginn=time(8), spaetestes_ende=time(18)))
    session.commit()
    ergebnis = importiere_termine(session, parse_ical(tiss_ics))
    from app.planung_service import plane_wochen_neu

    geplant = plane_wochen_neu(session, ergebnis.betroffene_wochen, heute=date(2026, 10, 1))
    assert geplant == [date(2026, 10, 5)]
    assert session.query(Arbeitsblock).count() > 0

    # Woche liegt in der Vergangenheit: nichts wird neu geplant
    assert plane_wochen_neu(session, ergebnis.betroffene_wochen, heute=date(2026, 11, 1)) == []


def test_abgabe_wird_erkannt():
    ics = (
        "BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:a1\nDTSTART;TZID=Europe/Vienna:20261014T235900\n"
        "DTEND;TZID=Europe/Vienna:20261014T235900\nSUMMARY:185.A91 VU Einführung in die Programmierung 1 - Abgabe Blatt 2\n"
        "END:VEVENT\nEND:VCALENDAR\n"
    )
    termin = parse_ical(ics)[0]
    assert termin.typ == "ABGABE"
    assert termin.lva_nummer == "185.A91"
