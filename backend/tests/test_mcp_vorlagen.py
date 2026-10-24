"""MCP-Server: Server-Anweisungen, Prompt-Vorlagen und die Werkzeuge, die die Vorlagen brauchen."""

import asyncio
from datetime import datetime, timedelta

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from sqlalchemy import select

from app.embedding import HashEmbedder
from app.extraktion import AbschnittRoh
from app.mcp_server import server
from app.models import Dokument, Lernblock
from app.suche import abschnitte_speichern
from tests.test_mcp import HEUTE, aufrufen, daten  # noqa: F401 – Fixture „daten“ wiederverwenden


def test_server_anweisungen_gelten_immer():
    text = server.instructions
    for regel in ("Quelle", "Seite", "Zeitmarke", "Vorrang", "inoffiziell, MB Cloud", "nicht in den Unterlagen",
                  "Wissensstand", "Lernereignis", "benoteten Abgaben", "keine fertigen"):
        assert regel in text, regel


def text(name, **argumente):
    ergebnis = asyncio.run(server.get_prompt(name, argumente))
    assert ergebnis.messages[0].role == "user"
    return ergebnis.messages[0].content.text


def test_prompt_vorlagen_mit_argumenten():
    vorlagen = {p.name: {a.name: a.required for a in (p.arguments or [])} for p in asyncio.run(server.list_prompts())}
    assert vorlagen == {
        "thema_lernen": {"lva": True, "thema": True}, "wochenstart": {}, "wiederholung": {"lva": False},
        "pruefung_simulieren": {"lva": True, "minuten": False}, "vorlesung_nachholen": {"termin": True},
        "plan_anpassen": {"grund": True, "woche": False},
    }
    titel = {p.name: p.title for p in asyncio.run(server.list_prompts())}
    assert titel["pruefung_simulieren"] == "Prüfung simulieren"


def test_inhalte_der_vorlagen():
    lernen = text("thema_lernen", lva="Mech", thema="Reibung")
    assert all(w in lernen for w in ("„Reibung“", "kleinen Schritten", "Verständnisfrage", "3 Kontrollfragen", "lernereignis_eintragen"))
    start = text("wochenstart")
    assert all(w in start for w in ("rueckblick", "neue_unterlagen", "pruefungen", "faellige_wiederholungen", "3 Prioritäten",
                                     "lernblock_vorschlagen"))
    assert "Spaced Repetition" in text("wiederholung") and "lva: „Mathe“" in text("wiederholung", lva="Mathe")
    simulation = text("pruefung_simulieren", lva="Mech", minuten="120")
    assert all(w in simulation for w in ("120 Minuten", "bearbeitet = false", "loesung_dokument_id", "Fehleranalyse pro Thema",
                                          "altpruefung_bearbeitet"))
    assert "90 Minuten" in text("pruefung_simulieren", lva="Mech")
    nachholen = text("vorlesung_nachholen", termin="Mechanik 14.10.")
    assert all(w in nachholen for w in ("aufzeichnung_zu_termin", "Zeitmarke", "Skript-Abschnitt", "3 Kontrollfragen"))
    plan = text("plan_anpassen", grund="krank am Mittwoch")
    assert all(w in plan for w in ("krank am Mittwoch", "wochenplan_vorschlagen", "nie gekürzt", "Vorschläge"))


def test_rueckblick_neue_unterlagen_ganzes_dokument(daten, session):  # noqa: F811
    heute = datetime.combine(HEUTE, datetime.min.time())
    session.add(Lernblock(lva_id=daten.id, start=heute + timedelta(hours=8), ende=heute + timedelta(hours=9), status="bestaetigt",
                          erledigt=True, tatsaechliche_minuten=50, thema="Reibung"))
    session.add(Lernblock(lva_id=daten.id, start=heute + timedelta(hours=14), ende=heute + timedelta(hours=15), status="bestaetigt"))
    session.commit()
    aufrufen("lernereignis_eintragen", thema="Reibung", art="quiz", ergebnis=0.7)
    r = aufrufen("rueckblick", woche=HEUTE.isoformat())
    assert (r["erledigt"], r["offen"], r["lernminuten"]) == (1, 1, 50) and r["lernereignisse"][0]["art"] == "quiz"

    skript = session.scalar(select(Dokument).where(Dokument.dateiname == "Skript.pdf"))
    skript.erschienen_am = datetime.now() - timedelta(days=2)
    session.commit()
    assert [u["datei"] for u in aufrufen("neue_unterlagen", tage=7)] == ["Skript.pdf"]
    dokument = aufrufen("lies_dokument", dokument_id=skript.id)
    assert "[S. 2]" in dokument["text"] and "[S. 11]" in dokument["text"] and dokument["offiziell"] and not dokument["gekuerzt"]


def test_altpruefung_bearbeitet_und_woche_neu_vorschlagen(daten, session, client):  # noqa: F811
    (alt,) = aufrufen("altpruefungen", lva="Mech")
    assert "loesung_dokument_id" in alt
    aufrufen("altpruefung_bearbeitet", dokument_id=alt["dokument_id"], minuten=95, punkte=30, punkte_max=40)
    assert aufrufen("altpruefungen", lva="Mech")[0]["bearbeitet"] is True
    skript = session.scalar(select(Dokument).where(Dokument.dateiname == "Skript.pdf"))
    with pytest.raises(ToolError, match="keine Altprüfung"):
        aufrufen("altpruefung_bearbeitet", dokument_id=skript.id)
    with pytest.raises(ToolError, match="Mehr Punkte"):
        aufrufen("altpruefung_bearbeitet", dokument_id=alt["dokument_id"], punkte=50, punkte_max=40)

    with pytest.raises(ToolError, match="Arbeitsregel"):
        aufrufen("wochenplan_vorschlagen")
    client.put("/api/arbeit/regel", json={"stunden_pro_woche": 6, "tage": [0, 1, 2, 3, 4]})
    plan = aufrufen("wochenplan_vorschlagen", grund="Test")
    assert plan["arbeit_stunden"] == 6 and plan["grund"] == "Test" and plan["arbeitsbloecke"]


def test_aufzeichnung_zu_termin(daten, session):  # noqa: F811
    morgen = HEUTE + timedelta(days=1)
    video = Dokument(lva_id=daten.id, tuwel_kurs_id=1, tuwel_cm_id=9, schluessel="v", dateiname="VO Reibung (Aufzeichnung)",
                     typ="video", ist_link=True, quelle_url="https://tuwel/x", episode_id="e1", aufnahme_am=morgen)
    session.add(video)
    session.flush()
    abschnitte_speichern(session, video, [AbschnittRoh("Heute Haftreibung.", zeit_von=0, zeit_bis=80),
                                          AbschnittRoh("Coulomb-Gesetz.", zeit_von=95, zeit_bis=170)], "lecturetube", HashEmbedder())
    session.commit()
    ergebnis = aufrufen("aufzeichnung_zu_termin", termin=f"Mech {morgen:%d.%m.}")
    assert ergebnis["aufzeichnung"]["titel"] == "VO Reibung (Aufzeichnung)"
    assert "[0:00 min] Heute Haftreibung." in ergebnis["transkript"] and "[1:35 min] Coulomb-Gesetz." in ergebnis["transkript"]
    termin_id = aufrufen("termine")[0]["termin_id"]
    assert aufrufen("aufzeichnung_zu_termin", termin=str(termin_id))["termin_id"] == termin_id
    with pytest.raises(ToolError, match="Kein Termin"):
        aufrufen("aufzeichnung_zu_termin", termin="Mech 01.01.2020")


def vorlage_rufen(**werte):
    """Wie `aufrufen`, aber das Werkzeug hat selbst ein Argument „name“."""
    import json

    ergebnis = asyncio.run(server.call_tool("vorlage", werte))
    return ergebnis.structured_content or json.loads(ergebnis.content[0].text)


def test_vorlage_als_werkzeug_und_zum_kopieren(client):
    """Für Clients, die Prompt-Vorlagen nicht anzeigen: Claude holt den Ablauf selbst, oder der Hub liefert den Text."""
    assert "Werkzeug `vorlage`" in server.instructions
    ergebnis = vorlage_rufen(name="thema_lernen", lva="Mechanik 1", thema="Reibung")
    assert ergebnis["ablauf"] == text("thema_lernen", lva="Mechanik 1", thema="Reibung")
    assert "120 Minuten" in vorlage_rufen(name="Pruefung simulieren", lva="Mathe", minuten="120")["ablauf"]
    assert vorlage_rufen(name="wochenstart")["ablauf"] == text("wochenstart")
    with pytest.raises(ToolError, match="fehlt: thema"):
        vorlage_rufen(name="thema_lernen", lva="Mechanik 1")
    with pytest.raises(ToolError, match="Unbekannte Vorlage"):
        vorlage_rufen(name="raten")

    vorlagen = client.get("/api/ki/vorlagen").json()
    assert [v["name"] for v in vorlagen][:2] == ["thema_lernen", "wochenstart"]
    assert next(v for v in vorlagen if v["name"] == "plan_anpassen") == {
        "name": "plan_anpassen", "titel": "Plan anpassen", "pflicht": ["grund"], "optional": ["woche"]}
    kopie = client.get("/api/ki/vorlage", params={"name": "vorlesung_nachholen", "termin": "Mechanik 14.10."}).json()
    assert kopie["text"] == text("vorlesung_nachholen", termin="Mechanik 14.10.")
    assert client.get("/api/ki/vorlage", params={"name": "plan_anpassen"}).status_code == 422
