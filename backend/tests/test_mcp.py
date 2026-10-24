"""MCP-Server: alle Werkzeuge über das SDK aufgerufen (in-process), Einrichtung in Claude Desktop."""

import asyncio
import json
from datetime import date, datetime, timedelta

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from app import ki_einrichtung
from app.embedding import HashEmbedder, setze_standard_embedder
from app.extraktion import AbschnittRoh
from app.mcp_server import server
from app.models import Dokument, Lernblock, Lva, LvaTeil, MbCloudDatei, MbCloudOrdner, Notiz, Termin, Thema
from app.suche import abschnitte_speichern

HEUTE = date.today()


def aufrufen(name: str, **argumente):
    ergebnis = asyncio.run(server.call_tool(name, argumente))
    inhalt = ergebnis.structured_content
    if inhalt is None:
        return json.loads(ergebnis.content[0].text)
    return inhalt.get("result", inhalt) if set(inhalt) == {"result"} else inhalt


@pytest.fixture
def daten(session):
    setze_standard_embedder(HashEmbedder())
    mech = Lva(schluessel="mech", titel="Mechanik 1", kurzname="Mech", semester="2026W", ects=6)
    session.add(mech)
    session.flush()
    session.add(LvaTeil(lva=mech, nummer="309.019", typ="VO", steop=True))
    morgen = datetime.combine(HEUTE + timedelta(days=1), datetime.min.time())
    session.add(Termin(lva_id=mech.id, typ="VO", titel="VO", start=morgen + timedelta(hours=10), ende=morgen + timedelta(hours=12)))
    pruefung = morgen + timedelta(days=20, hours=9)
    session.add(Termin(lva_id=mech.id, typ="PRUEFUNG", titel="Prüfung", start=pruefung, ende=pruefung + timedelta(hours=2)))
    skript = Dokument(lva_id=mech.id, tuwel_kurs_id=1, tuwel_cm_id=1, schluessel="s", dateiname="Skript.pdf", typ="pdf",
                      quelle_url="u", lernart="skript")
    alt = Dokument(lva_id=mech.id, tuwel_kurs_id=0, tuwel_cm_id=0, schluessel="mbcloud:x", dateiname="2025-01-27-Pruefung.pdf",
                   typ="pdf", quelle_url="u", quelle="mbcloud", kategorie="altpruefung", jahr=2025)
    session.add_all([skript, alt])
    session.flush()
    e = HashEmbedder()
    abschnitte_speichern(session, skript, [
        AbschnittRoh("Gleichgewicht: Summe der Kräfte ist null.", "1 Statik", "1 Statik", 2, 2),
        AbschnittRoh("Haftreibung nach Coulomb mit Reibungszahl.", "2 Reibung", "2 Reibung", 10, 10),
        AbschnittRoh("Gleitreibung bei bewegten Körpern.", "2 Reibung", "2 Reibung", 11, 11),
    ], "tuwel", e)
    abschnitte_speichern(session, alt, [AbschnittRoh("Aufgabe 2: Haftreibung an der schiefen Ebene.", seite_von=1, seite_bis=1)], "mbcloud", e)
    ordner = MbCloudOrdner(pfad="MB_VT_WIMB/Mechanik 1 VO 309.019", name="Mechanik 1 VO 309.019", lva_id=mech.id, zuordnung="auto")
    session.add(ordner)
    session.flush()
    session.add(MbCloudDatei(ordner_id=ordner.id, pfad=ordner.pfad + "/p.pdf", eltern_pfad=ordner.pfad, name="2025-01-27-Pruefung.pdf",
                             kategorie="altpruefung", datum=date(2025, 1, 27), jahr=2025, dokument_id=alt.id))
    session.add(Thema(lva_id=mech.id, titel="Reibung", kapitel="2 Reibung", reihenfolge=1))
    session.commit()
    yield mech
    setze_standard_embedder(None)


def test_alle_werkzeuge_sind_registriert():
    namen = {t.name for t in asyncio.run(server.list_tools())}
    assert namen == {
        "suche_unterlagen", "lies_abschnitt", "liste_lvas", "termine", "wochenplan", "pruefungen", "wissensstand",
        "faellige_wiederholungen", "altpruefungen", "lernereignis_eintragen", "wissensstand_setzen", "notiz_speichern",
        "lernblock_vorschlagen", "rueckblick", "neue_unterlagen", "lies_dokument", "aufzeichnung_zu_termin",
        "altpruefung_bearbeitet", "wochenplan_vorschlagen", "vorlage",
    }


def test_lesende_werkzeuge(daten):
    treffer = aufrufen("suche_unterlagen", frage="Haftreibung Coulomb", lva="Mech")
    assert treffer[0]["dokument"] == "Skript.pdf" and treffer[0]["fundstelle"] == "S. 10" and treffer[0]["offiziell"]
    inoffiziell = next(t for t in treffer if t["quelle"] == "mbcloud")
    assert inoffiziell["offiziell"] is False and inoffiziell["jahr"] == 2025
    assert all(t["quelle"] == "tuwel" for t in aufrufen("suche_unterlagen", frage="Haftreibung", nur_offiziell=True))

    abschnitt = aufrufen("lies_abschnitt", abschnitt_id=treffer[0]["abschnitt_id"], umgebung=1)
    assert "[S. 10]" in abschnitt["text"] and "[S. 11]" in abschnitt["text"] and abschnitt["kapitel"] == "2 Reibung"

    (lva,) = aufrufen("liste_lvas")
    assert lva["kurzname"] == "Mech" and lva["teile"] == ["VO 309.019"] and len(lva["pruefungen"]) == 1
    assert [t["titel"] for t in aufrufen("termine")] == ["Mech VO"]
    assert aufrufen("termine", lva="309.019")[0]["anwesenheitspflicht"] is False
    plan = aufrufen("wochenplan")
    assert set(plan) >= {"stunden", "pruefungen", "lernstand", "arbeit", "lernen"}
    (pruefung,) = aufrufen("pruefungen")
    assert pruefung["lva"] == "Mech" and pruefung["tage"] == 21
    (stand,) = aufrufen("wissensstand", lva="Mechanik")
    assert stand["themen"][0]["titel"] == "Reibung" and stand["tage_bis_pruefung"] == 21
    assert aufrufen("faellige_wiederholungen") == []
    (alt,) = aufrufen("altpruefungen", lva="Mech")
    assert alt["datum"] == "2025-01-27" and alt["inoffiziell"] and alt["abschnitte"] and not alt["bearbeitet"]


def test_schreibende_werkzeuge(daten, session, client):
    e = aufrufen("lernereignis_eintragen", thema="Reibung", art="quiz", ergebnis=0.9, notiz="Quiz mit Claude")
    assert (e["stufe_vorher"], e["stufe_nachher"]) == (0, 1) and e["thema"]["naechste_wiederholung"]
    assert aufrufen("wissensstand_setzen", thema="reibung", stufe=3)["stufe"] == 3
    notiz = aufrufen("notiz_speichern", text="Schiefe Ebene üben", lva="Mech", thema="Reibung")
    assert session.get(Notiz, notiz["notiz_id"]).quelle == "ki"

    start = datetime.combine(HEUTE + timedelta(days=1), datetime.min.time())
    vorschlag = aufrufen("lernblock_vorschlagen", lva="Mech", start=(start + timedelta(hours=11)).isoformat(),
                         ende=(start + timedelta(hours=13)).isoformat(), thema="Reibung wiederholen")
    assert vorschlag["status"].startswith("vorschlag") and vorschlag["konflikte"]  # überschneidet die VO
    block = session.get(Lernblock, vorschlag["lernblock_id"])
    assert (block.status, block.quelle) == ("vorschlag", "ki")

    # beim automatischen Neuplanen bleibt der Vorschlag von Claude stehen
    client.put("/api/arbeit/regel", json={"stunden_pro_woche": 4, "tage": [0, 1, 2, 3, 4]})
    client.post("/api/arbeit/vorschlag", params={"woche": block.start.date().isoformat()})
    session.expire_all()
    assert session.get(Lernblock, block.id) is not None


def test_fehler_werden_verstaendlich_gemeldet(daten):
    with pytest.raises(ToolError, match="Keine LVA"):
        aufrufen("suche_unterlagen", frage="x", lva="Quantenphysik")
    with pytest.raises(ToolError, match="Art muss"):
        aufrufen("lernereignis_eintragen", thema="Reibung", art="raten")
    with pytest.raises(ToolError, match="zwischen 0 und 1"):
        aufrufen("lernereignis_eintragen", thema="Reibung", art="quiz", ergebnis=7)
    with pytest.raises(ToolError, match="Kein Thema"):
        aufrufen("wissensstand_setzen", thema="Thermodynamik", stufe=2)
    with pytest.raises(ToolError, match="Ende muss"):
        aufrufen("lernblock_vorschlagen", lva="Mech", start="2026-10-14T12:00", ende="2026-10-14T11:00")


# --- Einrichtung in Claude Desktop -------------------------------------------------------------------

def test_eintragen_mit_sicherung_und_anderen_servern(tmp_path):
    config = tmp_path / "Claude" / "claude_desktop_config.json"
    config.parent.mkdir()
    config.write_text(json.dumps({"mcpServers": {"anderer": {"command": "x"}}, "theme": "dark"}), encoding="utf-8")

    ergebnis = ki_einrichtung.eintragen(config)
    daten = json.loads(config.read_text(encoding="utf-8"))
    assert daten["theme"] == "dark" and daten["mcpServers"]["anderer"] == {"command": "x"}  # Rest unverändert
    eintrag = daten["mcpServers"]["studien-hub"]
    assert eintrag["args"] == ["-m", "app.mcp_server"] and eintrag["env"]["STUDIENHUB_OFFLINE"] == "1"
    assert eintrag["env"]["PYTHONPATH"].endswith("backend")
    assert ergebnis["eingetragen"] and ergebnis["aktuell"]
    sicherung = json.loads(open(ergebnis["sicherung"], encoding="utf-8").read())
    assert "studien-hub" not in sicherung["mcpServers"]  # Sicherung = Stand vorher

    ki_einrichtung.austragen(config)
    assert "studien-hub" not in json.loads(config.read_text(encoding="utf-8"))["mcpServers"]


def test_neue_datei_und_kaputtes_json(tmp_path):
    neu = tmp_path / "leer" / "claude_desktop_config.json"
    ergebnis = ki_einrichtung.eintragen(neu)
    assert ergebnis["sicherung"] is None and json.loads(neu.read_text(encoding="utf-8"))["mcpServers"]["studien-hub"]

    kaputt = tmp_path / "kaputt.json"
    kaputt.write_text("{ das ist kein json", encoding="utf-8")
    with pytest.raises(ki_einrichtung.EinrichtungsFehler):
        ki_einrichtung.eintragen(kaputt)
    assert kaputt.read_text(encoding="utf-8") == "{ das ist kein json"  # nicht überschrieben
    assert ki_einrichtung.status(kaputt)["fehler"]
