"""Wochenbericht aus den TUWEL-Daten: neue und geänderte Unterlagen je LVA, Nachholen, API – ohne Claude."""

from datetime import date, datetime, timedelta

import pytest

from app.models import Dokument, Lva, Termin, Wochenbericht
from app.wochenbericht import NeueUnterlage, bericht_erstellen, bericht_text, berichtswoche, nachholen_woche, setze_aktiv

WOCHE = date(2026, 10, 19)  # Montag


@pytest.fixture
def lvas(session):
    mech = Lva(schluessel="309.019", nummer="309.019", titel="Mechanik 1", typ="VO", semester="2026W")
    mathe = Lva(schluessel="104.297", nummer="104.297", titel="Mathematik 1", typ="VO", semester="2026W")
    session.add_all([mech, mathe])
    session.commit()
    return {"mech": mech, "mathe": mathe}


def dokument(session, lva, name, erschienen, **kw):
    werte = dict(lva_id=lva.id, tuwel_kurs_id=1, tuwel_cm_id=len(name), schluessel=name, dateiname=name, typ="pdf",
                 quelle_url="u", abschnitt="Woche 3", erschienen_am=erschienen, erstellt_am=erschienen, geaendert_am=erschienen,
                 lern_minuten=30)
    werte.update(kw)
    doc = Dokument(**werte)
    session.add(doc)
    session.commit()
    return doc


def test_berichtstext_ueberblick_je_lva_und_pruefungen():
    unterlagen = [
        NeueUnterlage("Mechanik 1 VO", "Folien 3.pdf", "Woche 3", video=False, geaendert=False, seiten=30, stoff_minuten=60),
        NeueUnterlage("Mechanik 1 VO", "VO 3", "Aufzeichnungen", video=True, geaendert=False, dauer_sekunden=5400, stoff_minuten=135),
        NeueUnterlage("Mechanik 1 VO", "Übung 2.pdf", "Übungen", video=False, geaendert=True, seiten=2, stoff_minuten=180),
    ]
    text = bericht_text(WOCHE, unterlagen, ["Mathematik 1 VO"], [("Mechanik 1 VO", datetime(2026, 11, 6, 9))])
    assert text.startswith("## Woche vom 19.10. bis 25.10.2026")
    assert "**1** neue Unterlagen, **1** neue Aufzeichnungen, **1** geändert – in 1 LVA" in text
    assert "geschätzter neuer Stoff: **6,2 h**" in text
    assert "### Mechanik 1 VO (6,2 h Stoff)" in text
    assert "| Folien 3.pdf | Woche 3 | 30 Seiten | 60 min |" in text
    assert "| VO 3 | Aufzeichnungen | Video, 1:30 h | 135 min |" in text
    assert "| Übung 2.pdf *(geändert)* |" in text
    assert "## Ohne Neues\n\n- Mathematik 1 VO" in text
    assert "- **Mechanik 1 VO**: Fr 06.11.2026 09:00" in text
    leer = bericht_text(WOCHE, [], [], [])
    assert "nichts Neues" in leer and "###" not in leer


def test_bericht_aus_der_datenbank(session, lvas):
    mech, mathe = lvas["mech"], lvas["mathe"]
    dokument(session, mech, "folien3.pdf", datetime(2026, 10, 20, 9))
    dokument(session, mech, "alt.pdf", datetime(2026, 10, 1, 9))  # früher erschienen
    dokument(session, mech, "uebung.pdf", datetime(2026, 10, 1, 9), status="geaendert", geaendert_am=datetime(2026, 10, 22, 9))
    dokument(session, mech, "spaeter.pdf", datetime(2026, 10, 27, 9))  # nächste Woche
    dokument(session, mathe, "skript.pdf", datetime(2026, 9, 30, 9))
    dokument(session, mech, "Altpruefung.pdf", datetime(2026, 10, 20, 9), quelle="mbcloud")  # nicht aus TUWEL
    session.add(Termin(lva_id=mech.id, typ="PRUEFUNG", titel="Prüfung", start=datetime(2026, 11, 6, 9), ende=datetime(2026, 11, 6, 11)))
    session.commit()

    bericht = bericht_erstellen(session, WOCHE, jetzt=datetime(2026, 10, 25, 19))
    assert (bericht.status, bericht.neue_unterlagen, bericht.woche) == ("ok", 2, WOCHE)
    assert "folien3.pdf" in bericht.text and "uebung.pdf *(geändert)*" in bericht.text
    assert "alt.pdf" not in bericht.text and "spaeter.pdf" not in bericht.text and "Altpruefung" not in bericht.text
    assert "- Mathematik 1 VO" in bericht.text  # hat Unterlagen, aber nichts Neues
    assert "Prüfungen in den nächsten Wochen" in bericht.text

    # derselbe Bericht neu erstellt ersetzt den alten
    bericht_erstellen(session, WOCHE, jetzt=datetime(2026, 10, 25, 20))
    assert session.query(Wochenbericht).count() == 1


def test_berichtswoche_und_nachholen(session, lvas):
    assert berichtswoche(datetime(2026, 10, 25, 19)) == WOCHE  # Sonntag: die laufende Woche
    assert nachholen_woche(session, datetime(2026, 10, 25, 20)) == WOCHE  # Sonntag nach dem Lauf, kein Bericht
    assert nachholen_woche(session, datetime(2026, 10, 26, 8)) == WOCHE  # Montag: die Vorwoche
    assert nachholen_woche(session, datetime(2026, 10, 22, 8)) is None  # Donnerstag: nichts
    bericht_erstellen(session, WOCHE, anlass="zeitplan")
    assert nachholen_woche(session, datetime(2026, 10, 26, 8)) is None
    setze_aktiv(session, False)
    assert nachholen_woche(session, datetime(2026, 11, 2, 8)) is None


def test_api(client, session, lvas):
    dokument(session, lvas["mech"], "folien3.pdf", datetime.now())
    status = client.get("/api/wochenbericht/status").json()
    assert status == {"aktiv": True, "stunde": 19}  # Standard: eingeschaltet
    assert client.put("/api/wochenbericht/einstellung", json={"aktiv": False}).json()["aktiv"] is False

    neu = client.post("/api/wochenbericht/erstellen").json()
    assert neu["status"] == "ok" and neu["neue_unterlagen"] == 1 and "folien3.pdf" in neu["text"]
    vorwoche = (date.today() - timedelta(days=7)).isoformat()
    alt = client.post("/api/wochenbericht/erstellen", params={"woche": vorwoche}).json()
    assert alt["neue_unterlagen"] == 0
    liste = client.get("/api/wochenbericht").json()
    assert [b["id"] for b in liste] == [neu["id"], alt["id"]] and liste[0]["text"] is None
    assert client.get(f"/api/wochenbericht/{neu['id']}").json()["text"] == neu["text"]
    assert client.delete(f"/api/wochenbericht/{alt['id']}").status_code == 204
    assert client.get(f"/api/wochenbericht/{alt['id']}").status_code == 404
