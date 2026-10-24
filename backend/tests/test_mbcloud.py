"""MB Cloud – reine Logik: Einteilung, Jahreserkennung, Zuordnung, Lösung zur Prüfung, WebDAV-Antwort."""

from datetime import date, datetime

import pytest

from app.mbcloud import (
    ALTPRUEFUNG,
    AUSARBEITUNG,
    FORMELSAMMLUNG,
    LOESUNG,
    MITSCHRIFT,
    SONSTIGES,
    IndexEintrag,
    LvaKandidat,
    automatisch_laden,
    datum_erkennen,
    kategorie_erkennen,
    loesungen_verknuepfen,
    ordner_titel,
    ordner_zuordnen,
    propfind_lesen,
    titel_aehnlichkeit,
)

# --- Einteilung ----------------------------------------------------------------------------------


@pytest.mark.parametrize("name, ordner, kategorie, protokoll", [
    ("2025-10-09-Gedankenprotokoll-Auslegung von Werkzeugmaschinen-311.093.pdf", [], ALTPRUEFUNG, True),
    ("Pruefung_2023-01-27.pdf", [], ALTPRUEFUNG, False),
    ("Klausur WS22.pdf", [], ALTPRUEFUNG, False),
    ("Prüfung 27.01.2023 Lösung.pdf", [], LOESUNG, False),
    ("Musterloesung_Test2.pdf", [], LOESUNG, False),
    ("Formelsammlung Mechanik.pdf", [], FORMELSAMMLUNG, False),
    ("Mitschrift VO 3.pdf", [], MITSCHRIFT, False),
    ("Zusammenfassung Kapitel 1-5.pdf", [], AUSARBEITUNG, False),
    # Ordnername entscheidet, wenn der Dateiname nichts verrät
    ("2021-06-25.pdf", ["Prüfungsunterlagen"], ALTPRUEFUNG, False),
    ("Fragen_Teil_A.pdf", ["Theoriefragen"], ALTPRUEFUNG, False),
    ("Scan 12.pdf", ["Zusammenfassungen"], AUSARBEITUNG, False),
    ("Bsp 4.pdf", ["Prüfungsunterlagen", "Lösungen"], LOESUNG, False),  # tiefster Ordner zuerst
    ("Bsp 4.pdf", ["Beispielsammlungen"], SONSTIGES, False),
    ("Folien VO 1.pdf", ["Allgemeine Unterlagen zur VO"], SONSTIGES, False),
    # Dateiname hat Vorrang vor dem Ordner
    ("Formelsammlung.pdf", ["Prüfungsunterlagen"], FORMELSAMMLUNG, False),
    ("Lösung 2022.pdf", ["Prüfungsunterlagen"], LOESUNG, False),
    ("Kapitel 3.pdf", ["Prüfungsunterlagen", "Gedankenprotokolle"], ALTPRUEFUNG, True),
])
def test_einteilung(name, ordner, kategorie, protokoll):
    e = kategorie_erkennen(name, ordner)
    assert (e.kategorie, e.gedankenprotokoll) == (kategorie, protokoll)


# --- Jahr und Prüfungsdatum ---------------------------------------------------------------------

@pytest.mark.parametrize("name, ordner, erwartet", [
    ("2025-10-09-Gedankenprotokoll-Auslegung von Werkzeugmaschinen-311.093.pdf", [], (date(2025, 10, 9), 2025)),
    ("Pruefung_2023_01_27.pdf", [], (date(2023, 1, 27), 2023)),
    ("Prüfung 20230127.pdf", [], (date(2023, 1, 27), 2023)),
    ("Prüfung 27.01.2023.pdf", [], (date(2023, 1, 27), 2023)),
    ("Test 3.2.21.pdf", [], (date(2021, 2, 3), 2021)),
    ("Klausur WS2022.pdf", [], (None, 2022)),
    ("Klausur SS 23.pdf", [], (None, 2023)),
    ("Prüfung WiSe 2021/22.pdf", [], (None, 2021)),
    ("Prüfung Juni 2019.pdf", [], (None, 2019)),
    ("Theorie 2018 Teil B.pdf", [], (None, 2018)),
    ("Angabe.pdf", ["Prüfungsunterlagen", "2020-11-18"], (date(2020, 11, 18), 2020)),
    # LVA-Nummern und sonstige Zahlen sind kein Datum
    ("Mechanik 309.019 Bsp 12.pdf", [], (None, None)),
    ("Kapitel 31.12.pdf", [], (None, None)),
    ("Prüfung 2023-13-45.pdf", [], (None, 2023)),  # ungültiges Datum, aber Jahr
])
def test_jahreserkennung(name, ordner, erwartet):
    assert datum_erkennen(name, ordner) == erwartet


# --- Zuordnung -------------------------------------------------------------------------------------

LVAS = [
    LvaKandidat(1, "Mechanik 1", frozenset({"309.019", "309.021"})),
    LvaKandidat(2, "Mathematik 1 für MB, WIMB und VT", frozenset({"104.297", "104.604"}), "Mathe 1"),
    LvaKandidat(3, "Grundlagen der Betriebs- und Unternehmensführung", frozenset({"330.001"}), "GBUF"),
    LvaKandidat(4, "Werkstoffkunde metallischer Werkstoffe", frozenset({"308.862"})),
]


def test_ordnername_zerlegen():
    assert ordner_titel("Mechanik 1 VO 309.019") == ("Mechanik 1", "VO", "309.019")
    assert ordner_titel("Angewandte Maschinenelemente Rechenübung UE 307.449") == (
        "Angewandte Maschinenelemente Rechenübung", "UE", "307.449")
    assert ordner_titel("Analytische Chemie") == ("Analytische Chemie", None, None)


def test_zuordnung_sicher_ueber_die_nummer():
    assert ordner_zuordnen("Mechanik 1 VO 309.019", LVAS) == ordner_zuordnen("Mechanik 1 UE 309.021", LVAS)
    z = ordner_zuordnen("Mechanik 1 UE 309.021", LVAS)
    assert (z.lva_id, z.sicher) == (1, True)
    # Nummer gewinnt auch gegen einen abweichenden Titel
    assert ordner_zuordnen("GBUF Betriebsführung VO 330.001", LVAS).lva_id == 3


def test_zuordnung_ueber_den_titel_nur_als_vorschlag():
    z = ordner_zuordnen("Mathematik 1 für MB und WIMB", LVAS)  # keine Nummer, Titel ähnlich
    assert z.lva_id == 2 and not z.sicher and 0.6 <= z.aehnlichkeit < 1
    gleich = ordner_zuordnen("Werkstoffkunde metallischer Werkstoffe VO", LVAS)  # identischer Titel
    assert (gleich.lva_id, gleich.sicher) == (4, True)
    assert ordner_zuordnen("Mathe 1", LVAS).lva_id == 2  # Kurzname


def test_keine_zuordnung_bei_anderer_zahl_oder_fremder_lva():
    assert titel_aehnlichkeit("Mechanik 2", "Mechanik 1") == 0
    assert ordner_zuordnen("Mechanik 2 VO 309.020", LVAS).lva_id is None
    assert ordner_zuordnen("Analytische Chemie", LVAS).lva_id is None
    # andere LVA-Nummer, ähnlicher Titel: nur Vorschlag, nicht sicher
    assert not ordner_zuordnen("Mathematik 1 für MB, WIMB und VT VO 104.999", LVAS).sicher


def test_vorrang_nach_reihenfolge_der_kandidaten():
    # gleiche Nummer in zwei Semestern: der erste Kandidat (z. B. besucht, aktuelles Semester) gewinnt
    kandidaten = [LvaKandidat(10, "Mathematik 1", frozenset({"104.297"})), LvaKandidat(11, "Mathematik 1", frozenset({"104.297"}))]
    assert ordner_zuordnen("Mathematik 1 VO 104.297", kandidaten).lva_id == 10


# --- Lösung zur Altprüfung -----------------------------------------------------------------------

def test_loesungen_verknuepfen():
    e = [
        IndexEintrag(1, "Prüfung 2023-01-27.pdf", "P", ALTPRUEFUNG, date(2023, 1, 27), 2023),
        IndexEintrag(2, "Lösung 27.01.2023.pdf", "P", LOESUNG, date(2023, 1, 27), 2023),
        IndexEintrag(3, "Test2_WS22.pdf", "P", ALTPRUEFUNG, None, 2022),
        IndexEintrag(4, "Test2_WS22_Loesung.pdf", "P", LOESUNG, None, 2022),
        IndexEintrag(5, "Klausur 2019.pdf", "P", ALTPRUEFUNG, None, 2019),
        IndexEintrag(6, "Musterlösung Teil B 2019.pdf", "P", LOESUNG, None, 2019),
        IndexEintrag(7, "Lösung 2015.pdf", "P", LOESUNG, None, 2015),  # keine passende Prüfung
    ]
    assert loesungen_verknuepfen(e) == {2: 1, 4: 3, 6: 5}


# --- Download-Regel ------------------------------------------------------------------------------

def test_automatisch_nur_pruefungen_loesungen_formeln_der_letzten_5_jahre():
    heute = date(2026, 10, 11)
    assert automatisch_laden(ALTPRUEFUNG, 2021, heute) and automatisch_laden(LOESUNG, 2026, heute)
    assert automatisch_laden(FORMELSAMMLUNG, 2024, heute)
    assert not automatisch_laden(ALTPRUEFUNG, 2020, heute)
    assert not automatisch_laden(AUSARBEITUNG, 2025, heute) and not automatisch_laden(SONSTIGES, 2025, heute)
    assert not automatisch_laden(ALTPRUEFUNG, None, heute)


# --- WebDAV ----------------------------------------------------------------------------------------

PROPFIND = """<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns">
 <d:response><d:href>/remote.php/dav/files/abc123/MB_VT_WIMB/Mechanik%201%20VO%20309.019/</d:href>
  <d:propstat><d:prop><d:getlastmodified>Wed, 23 Sep 2026 10:00:00 GMT</d:getlastmodified><d:getetag>"ord1"</d:getetag>
   <d:resourcetype><d:collection/></d:resourcetype><oc:size>1500000000</oc:size></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat>
  <d:propstat><d:prop><d:getcontentlength/></d:prop><d:status>HTTP/1.1 404 Not Found</d:status></d:propstat></d:response>
 <d:response><d:href>/remote.php/dav/files/abc123/MB_VT_WIMB/Mechanik%201%20VO%20309.019/Pr%C3%BCfungsunterlagen/</d:href>
  <d:propstat><d:prop><d:getlastmodified>Wed, 23 Sep 2026 10:00:00 GMT</d:getlastmodified><d:getetag>"p1"</d:getetag>
   <d:resourcetype><d:collection/></d:resourcetype><oc:size>1017700000</oc:size></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>
 <d:response><d:href>/remote.php/dav/files/abc123/MB_VT_WIMB/Mechanik%201%20VO%20309.019/Formelsammlung.pdf</d:href>
  <d:propstat><d:prop><d:getlastmodified>Tue, 01 Dec 2020 08:30:00 GMT</d:getlastmodified><d:getetag>"f1"</d:getetag>
   <d:resourcetype/><d:getcontentlength>123456</d:getcontentlength></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>
</d:multistatus>"""


def test_propfind_lesen():
    eintraege = propfind_lesen(PROPFIND, "/remote.php/dav/files/abc123/")
    assert [e.pfad for e in eintraege] == [
        "MB_VT_WIMB/Mechanik 1 VO 309.019",
        "MB_VT_WIMB/Mechanik 1 VO 309.019/Prüfungsunterlagen",
        "MB_VT_WIMB/Mechanik 1 VO 309.019/Formelsammlung.pdf",
    ]
    ordner, unter, datei = eintraege
    assert (ordner.ist_ordner, ordner.etag, ordner.groesse, ordner.name) == (True, "ord1", 1500000000, "Mechanik 1 VO 309.019")
    assert (datei.ist_ordner, datei.groesse, datei.etag) == (False, 123456, "f1")
    assert isinstance(datei.geaendert, datetime) and datei.geaendert.year == 2020
