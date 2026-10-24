"""MCP-Server des Studien-Hubs für Claude Desktop (Stufe 4) – offizielles Python-SDK, lokal über stdio.

Start: `python -m app.mcp_server` (aus dem Ordner backend). Der Server
- liest Unterlagen nur aus der Datenbank (Abschnitte); er schreibt keine Dateien,
- greift nicht ins Netz (Embedding-Modell nur aus dem lokalen Speicher, `STUDIENHUB_OFFLINE=1`),
- schreibt nur Lernereignisse, Wissensstand, Notizen und Lernblock-*Vorschläge* (die du im Hub bestätigst).
Alle Ausgaben gehen an stderr – stdout gehört dem MCP-Protokoll.
"""

from __future__ import annotations

import os
import re
import sys
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta

os.environ.setdefault("STUDIENHUB_OFFLINE", "1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("STUDIENHUB_SCHEDULER", "0")

from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402
from sqlalchemy import select  # noqa: E402

from .db import SessionLocal, init_db, ist_initialisiert  # noqa: E402
from .lva_auswahl import besuchte_lva_ids  # noqa: E402
from .models import (  # noqa: E402
    LERN_VORSCHLAG,
    Abschnitt,
    Arbeitsblock,
    Lernblock,
    Lva,
    MbCloudDatei,
    MbCloudOrdner,
    Notiz,
    Termin,
    Thema,
)
from .wissensstand import ARTEN, STUFEN  # noqa: E402

ANWEISUNGEN = """Studien-Hub: Unterlagen, Termine, Lernplan und Wissensstand eines TU-Wien-Studenten (Maschinenbau/WIMB).
Diese Regeln gelten immer:
1. Antworte aus den Unterlagen des Studenten (`suche_unterlagen`, `lies_abschnitt`, `lies_dokument`) und nenne
   immer die Quelle: Datei und Seite – bei Aufzeichnungen Video und Zeitmarke.
2. Offizielle Unterlagen (TUWEL, LectureTube) haben Vorrang. Inhalte aus der MB Cloud sind inoffiziell
   (Studierende, oft Gedankenprotokolle) – kennzeichne sie immer als „inoffiziell, MB Cloud, <Jahr>“.
3. Steht etwas nicht in den Unterlagen, sag das ausdrücklich. Allgemeinwissen nur als solches kennzeichnen.
4. Frag zu Beginn den Wissensstand ab (`wissensstand`) und passe Tiefe und Tempo der Erklärung daran an.
5. Trag nach jeder Übung (Quiz, Kontrollfragen, Altprüfung) ein Lernereignis ein (`lernereignis_eintragen`,
   Ergebnis als Anteil 0–1).
6. Bei benoteten Abgaben (Hausübungen, Abgaben, Tests) nur Hinweise und Denkanstöße geben, keine fertigen
   Lösungen oder Endergebnisse.
7. Lernblöcke nur vorschlagen (`lernblock_vorschlagen`, `wochenplan_vorschlagen`) – der Student bestätigt im Hub.
Vorlagen für typische Abläufe: thema_lernen, wochenstart, wiederholung, pruefung_simulieren, vorlesung_nachholen,
plan_anpassen. Nennt der Student eine davon (auch umschrieben, z. B. „Wochenstart“ oder „Prüfung simulieren für
Mathe“), hol den Ablauf mit dem Werkzeug `vorlage` und folge ihm Schritt für Schritt.
"""

server = MCPServer(name="studien-hub", instructions=ANWEISUNGEN, version="1.0")


@contextmanager
def sitzung():
    if not ist_initialisiert():
        init_db()
    with SessionLocal() as session:
        yield session


def _embedder():
    from .embedding import standard_embedder

    return standard_embedder()


def lva_finden(session, angabe: str | int | None) -> Lva | None:
    """LVA über ID, LVA-Nummer, Kurzname oder Teil des Titels (besuchte LVAs zuerst)."""
    if angabe in (None, ""):
        return None
    text = str(angabe).strip()
    if text.isdigit() and (lva := session.get(Lva, int(text))):
        return lva
    besucht = besuchte_lva_ids(session)
    lvas = sorted(session.scalars(select(Lva)), key=lambda l: (l.id not in besucht, l.semester), reverse=False)
    klein = text.casefold()
    for pruefen in (
        lambda l: l.nummer == text or any(t.nummer == text for t in l.teile),
        lambda l: (l.kurzname or "").casefold() == klein,
        lambda l: l.titel.casefold() == klein,
        lambda l: klein in l.titel.casefold() or klein in (l.kurzname or "").casefold(),
    ):
        treffer = [l for l in lvas if pruefen(l)]
        if treffer:
            return treffer[0]
    raise ToolError(f"Keine LVA gefunden für „{angabe}“ – `liste_lvas` zeigt alle.")


def thema_finden(session, angabe: str | int, lva: Lva | None = None) -> Thema:
    text = str(angabe).strip()
    if text.isdigit() and (thema := session.get(Thema, int(text))):
        return thema
    abfrage = select(Thema)
    if lva is not None:
        abfrage = abfrage.where(Thema.lva_id == lva.id)
    themen = list(session.scalars(abfrage))
    klein = text.casefold()
    treffer = [t for t in themen if t.titel.casefold() == klein] or [t for t in themen if klein in t.titel.casefold()]
    if not treffer:
        raise ToolError(f"Kein Thema „{angabe}“ – `wissensstand` zeigt die Themen je LVA.")
    if len(treffer) > 1 and lva is None:
        raise ToolError(f"„{angabe}“ ist mehrdeutig – bitte die LVA angeben oder die Themen-ID verwenden.")
    return treffer[0]


def _datum(text: str | None, standard: date) -> date:
    return date.fromisoformat(text[:10]) if text else standard


# --- Lesen ----------------------------------------------------------------------------------------------

@server.tool()
def suche_unterlagen(frage: str, lva: str | None = None, anzahl: int = 8, nur_offiziell: bool = False) -> list[dict]:
    """Semantische Suche in allen Unterlagen (Skripte, Folien, Transkripte, MB Cloud).

    Liefert Abschnitte mit Quelle (tuwel/lecturetube/mbcloud), offiziell ja/nein, Jahr, Kapitel und Fundstelle
    (Seite oder Zeitmarke). `lva`: Name, Kurzname oder LVA-Nummer, optional.
    """
    from .suche import suchen

    with sitzung() as session:
        gefunden = lva_finden(session, lva)
        treffer = suchen(session, frage, gefunden.id if gefunden else None, max(1, min(anzahl, 25)), _embedder(), nur_offiziell)
        return [t.als_dict() for t in treffer]


@server.tool()
def lies_abschnitt(abschnitt_id: int, umgebung: int = 1) -> dict:
    """Vollständiger Text eines Abschnitts samt `umgebung` Nachbarabschnitten davor und danach."""
    with sitzung() as session:
        a = session.get(Abschnitt, abschnitt_id)
        if a is None:
            raise ToolError(f"Abschnitt {abschnitt_id} gibt es nicht.")
        nachbarn = list(session.scalars(select(Abschnitt).where(
            Abschnitt.dokument_id == a.dokument_id,
            Abschnitt.reihenfolge.between(a.reihenfolge - umgebung, a.reihenfolge + umgebung),
        ).order_by(Abschnitt.reihenfolge)))
        return {
            "abschnitt_id": a.id, "dokument": a.dokument.dateiname, "lva": a.lva.anzeigename,
            "quelle": a.quelle, "offiziell": a.offiziell, "jahr": a.jahr, "kapitel": a.unterkapitel or a.kapitel,
            "fundstelle": a.fundstelle,
            "text": "\n\n".join((f"[{n.fundstelle}] " if n.fundstelle else "") + n.text for n in nachbarn),
        }


@server.tool()
def liste_lvas(nur_besuchte: bool = True) -> list[dict]:
    """LVAs mit Semester, ECTS, Teilen (VO/UE/Gruppe), STEOP und ob sie dieses Semester besucht werden."""
    from .lernaufwand import pruefungen

    with sitzung() as session:
        besucht = besuchte_lva_ids(session)
        ergebnis = []
        for l in session.scalars(select(Lva).order_by(Lva.semester.desc(), Lva.titel)):
            if nur_besuchte and l.id not in besucht:
                continue
            zeitpunkte = pruefungen(session, l)
            ergebnis.append({
                "id": l.id, "titel": l.titel, "kurzname": l.kurzname, "semester": l.semester, "ects": l.ects,
                "besucht": l.id in besucht, "teile": [f"{t.bezeichnung} {t.nummer or ''}".strip() for t in l.teile],
                "pruefungen": [z.isoformat() for z in zeitpunkte],
            })
        return ergebnis


@server.tool()
def termine(von: str | None = None, bis: str | None = None, lva: str | None = None) -> list[dict]:
    """Uni-Termine im Zeitraum (ISO-Datum, Standard: heute bis in 7 Tagen) mit Markierungen."""
    with sitzung() as session:
        start = datetime.combine(_datum(von, date.today()), time())
        ende = datetime.combine(_datum(bis, start.date() + timedelta(days=7)), time()) + timedelta(days=1)
        abfrage = select(Termin).where(Termin.start < ende, Termin.ende > start).order_by(Termin.start)
        if gefunden := lva_finden(session, lva):
            abfrage = abfrage.where(Termin.lva_id == gefunden.id)
        besucht = besuchte_lva_ids(session)
        return [{
            "termin_id": t.id, "lva_id": t.lva_id,
            "start": t.start.isoformat(), "ende": t.ende.isoformat(), "titel": t.anzeigename, "typ": t.typ, "ort": t.ort,
            "anwesenheitspflicht": t.hat_anwesenheitspflicht, "aufzeichnung": t.wird_aufgezeichnet,
            "besucht": t.lva_id in besucht,
        } for t in session.scalars(abfrage)]


@server.tool()
def wochenplan(woche: str | None = None) -> dict:
    """Woche (beliebiger Tag, ISO; Standard: diese Woche): Stunden Uni/Arbeit/Lernen/Freizeit, Arbeits- und
    Lernblöcke, Lernstand je LVA und nächste Prüfungen."""
    from .planung_service import wochenuebersicht

    with sitzung() as session:
        tag = _datum(woche, date.today())
        u = wochenuebersicht(session, tag)
        von = datetime.combine(u["woche"], time())
        bis = von + timedelta(days=7)
        u["arbeit"] = [{"start": b.start.isoformat(), "ende": b.ende.isoformat(), "status": b.status}
                       for b in session.scalars(select(Arbeitsblock).where(Arbeitsblock.start >= von, Arbeitsblock.start < bis).order_by(Arbeitsblock.start))]
        u["lernen"] = [{"id": b.id, "start": b.start.isoformat(), "ende": b.ende.isoformat(), "lva": b.lva.anzeigename,
                        "thema": b.thema, "status": b.status, "von_claude": b.quelle == "ki", "erledigt": b.erledigt,
                        "tatsaechliche_minuten": b.tatsaechliche_minuten}
                       for b in session.scalars(select(Lernblock).where(Lernblock.start >= von, Lernblock.start < bis).order_by(Lernblock.start))]
        return _json(u)


@server.tool()
def pruefungen() -> list[dict]:
    """Kommende Prüfungen aller besuchten LVAs mit Tagen bis dahin (TISS oder selbst eingetragen)."""
    from .lernaufwand import pruefungstermine

    with sitzung() as session:
        heute = date.today()
        ergebnis = []
        for lva in session.scalars(select(Lva).where(Lva.id.in_(besuchte_lva_ids(session)))):
            for z, quelle in pruefungstermine(session, lva):
                if z.date() >= heute:
                    ergebnis.append({"lva": lva.anzeigename, "lva_id": lva.id, "zeitpunkt": z.isoformat(),
                                     "tage": (z.date() - heute).days, "quelle": quelle})
        return sorted(ergebnis, key=lambda p: p["zeitpunkt"])


@server.tool()
def wissensstand(lva: str | None = None) -> list[dict]:
    """Themen je LVA mit Stufe (0 neu … 4 prüfungsfest), letzter Übung, nächster Wiederholung und Tagen bis zur Prüfung."""
    from .themen import uebersicht

    with sitzung() as session:
        gefunden = lva_finden(session, lva)
        return _json(uebersicht(session, gefunden.id if gefunden else None))


@server.tool()
def faellige_wiederholungen(lva: str | None = None) -> list[dict]:
    """Themen, deren Wiederholung heute oder früher fällig ist."""
    from .themen import faellige_wiederholungen as faellige

    with sitzung() as session:
        gefunden = lva_finden(session, lva)
        return _json(faellige(session, gefunden.id if gefunden else None))


@server.tool()
def altpruefungen(lva: str) -> list[dict]:
    """Altprüfungen und Lösungen einer LVA aus der MB Cloud (inoffiziell), neueste zuerst – mit Datum/Jahr,
    Gedankenprotokoll ja/nein, verknüpfter Lösung und ob schon bearbeitet (Punkte, Zeit)."""
    with sitzung() as session:
        gefunden = lva_finden(session, lva)
        dateien = list(session.scalars(select(MbCloudDatei).join(MbCloudOrdner).where(
            MbCloudOrdner.lva_id == gefunden.id, MbCloudDatei.kategorie.in_(["altpruefung", "loesung"]),
        ).order_by(MbCloudDatei.datum.desc().nulls_last(), MbCloudDatei.jahr.desc().nulls_last())))
        loesung_fuer = {d.loesung_zu_id: d for d in dateien if d.loesung_zu_id}
        ergebnis = []
        for d in dateien:
            if d.kategorie != "altpruefung":
                continue
            doc, loesung = d.dokument, loesung_fuer.get(d.id)
            ergebnis.append({
                "name": d.name, "datum": d.datum.isoformat() if d.datum else None, "jahr": d.jahr,
                "gedankenprotokoll": d.gedankenprotokoll, "dokument_id": d.dokument_id, "inoffiziell": True,
                "loesung": loesung.name if loesung else None,
                "loesung_dokument_id": loesung.dokument_id if loesung else None,
                "bearbeitet": bool(doc and doc.bearbeitet_am), "punkte": doc.punkte if doc else None,
                "punkte_max": doc.punkte_max if doc else None, "minuten": doc.bearbeitet_minuten if doc else None,
                "abschnitte": list(session.scalars(select(Abschnitt.id).where(Abschnitt.dokument_id == d.dokument_id)))
                if d.dokument_id else [],
            })
        return ergebnis


# --- Schreiben ---------------------------------------------------------------------------------------

@server.tool()
def lernereignis_eintragen(thema: str, art: str, ergebnis: float | None = None, lva: str | None = None,
                           notiz: str | None = None) -> dict:
    """Lernereignis protokollieren: `art` = quiz | altpruefung | selbsteinschaetzung | lernblock, `ergebnis` 0–1
    (Anteil richtig/Punkte). Passt Stufe und nächste Wiederholung an. `thema`: Titel oder ID."""
    from .themen import ereignis_eintragen, thema_out

    if art not in ARTEN:
        raise ToolError(f"Art muss eine von {', '.join(ARTEN)} sein.")
    if ergebnis is not None and not 0 <= ergebnis <= 1:
        raise ToolError("Ergebnis als Anteil zwischen 0 und 1 angeben (z. B. 0.7 für 70 %).")
    with sitzung() as session:
        t = thema_finden(session, thema, lva_finden(session, lva))
        e = ereignis_eintragen(session, t, art, ergebnis, notiz, quelle="ki")
        return _json({"ereignis_id": e.id, "stufe_vorher": e.stufe_vorher, "stufe_nachher": e.stufe_nachher,
                      "thema": thema_out(session, t, date.today())})


@server.tool()
def wissensstand_setzen(thema: str, stufe: int, lva: str | None = None, notiz: str | None = None) -> dict:
    """Stufe eines Themas direkt setzen (0 neu, 1 gesehen, 2 mit Hilfe, 3 sicher, 4 prüfungsfest) –
    wird als Selbsteinschätzung protokolliert."""
    from .themen import ereignis_eintragen, thema_out

    if stufe not in STUFEN:
        raise ToolError("Stufe muss zwischen 0 und 4 liegen.")
    with sitzung() as session:
        t = thema_finden(session, thema, lva_finden(session, lva))
        ereignis_eintragen(session, t, "selbsteinschaetzung", None, notiz, quelle="ki", stufe=stufe)
        return _json(thema_out(session, t, date.today()))


@server.tool()
def notiz_speichern(text: str, lva: str | None = None, thema: str | None = None) -> dict:
    """Notiz zu einer LVA oder einem Thema speichern (erscheint im Hub beim Wissensstand)."""
    with sitzung() as session:
        gefunden = lva_finden(session, lva)
        t = thema_finden(session, thema, gefunden) if thema else None
        notiz = Notiz(lva_id=(gefunden.id if gefunden else (t.lva_id if t else None)), thema_id=t.id if t else None,
                      text=text, quelle="ki")
        session.add(notiz)
        session.commit()
        return {"notiz_id": notiz.id, "lva_id": notiz.lva_id, "thema_id": notiz.thema_id}


@server.tool()
def lernblock_vorschlagen(lva: str, start: str, ende: str, thema: str | None = None) -> dict:
    """Lernblock vorschlagen (ISO-Zeitpunkte, z. B. 2026-10-14T16:00). Es entsteht nur ein Vorschlag, den der
    Student im Hub bestätigt; Überschneidungen mit Terminen und Arbeit werden gemeldet."""
    with sitzung() as session:
        gefunden = lva_finden(session, lva)
        if gefunden is None:
            raise ToolError("Bitte eine LVA angeben.")
        anfang, schluss = datetime.fromisoformat(start), datetime.fromisoformat(ende)
        if schluss <= anfang:
            raise ToolError("Ende muss nach dem Beginn liegen.")
        if schluss - anfang > timedelta(hours=6):
            raise ToolError("Ein Lernblock darf höchstens 6 Stunden lang sein.")
        besucht = besuchte_lva_ids(session)
        konflikte = [f"Termin {t.anzeigename} {t.start:%H:%M}–{t.ende:%H:%M}" for t in session.scalars(
            select(Termin).where(Termin.start < schluss, Termin.ende > anfang)) if t.lva_id in besucht and t.typ != "ABGABE"]
        konflikte += [f"Arbeit {b.start:%H:%M}–{b.ende:%H:%M}" for b in session.scalars(
            select(Arbeitsblock).where(Arbeitsblock.start < schluss, Arbeitsblock.ende > anfang))]
        konflikte += [f"Lernblock {b.start:%H:%M}–{b.ende:%H:%M}" for b in session.scalars(
            select(Lernblock).where(Lernblock.start < schluss, Lernblock.ende > anfang))]
        block = Lernblock(lva_id=gefunden.id, start=anfang, ende=schluss, status=LERN_VORSCHLAG, quelle="ki",
                          thema=(thema or "Vorschlag von Claude")[:500], notiz="Von Claude vorgeschlagen")
        session.add(block)
        session.commit()
        return {"lernblock_id": block.id, "status": "vorschlag – im Hub bestätigen", "konflikte": konflikte}


@server.tool()
def rueckblick(woche: str | None = None) -> dict:
    """Rückblick auf eine Woche (Standard: die vergangene): Lernblöcke erledigt/offen, Lernereignisse mit Ergebnis,
    bearbeitete Altprüfungen, geleistete Arbeitsstunden."""
    from .models import Dokument, Lernereignis

    with sitzung() as session:
        tag = _datum(woche, date.today() - timedelta(days=7))
        von = datetime.combine(tag - timedelta(days=tag.weekday()), time())
        bis = von + timedelta(days=7)
        bloecke = list(session.scalars(select(Lernblock).where(Lernblock.start >= von, Lernblock.start < bis).order_by(Lernblock.start)))
        arbeit = list(session.scalars(select(Arbeitsblock).where(Arbeitsblock.start >= von, Arbeitsblock.start < bis)))
        ereignisse = list(session.scalars(select(Lernereignis).where(Lernereignis.zeitpunkt >= von, Lernereignis.zeitpunkt < bis)
                                          .order_by(Lernereignis.zeitpunkt)))
        altpruefungen = list(session.scalars(select(Dokument).where(Dokument.bearbeitet_am >= von, Dokument.bearbeitet_am < bis)))
        return {
            "woche": von.date().isoformat(),
            "lernbloecke": [{"start": b.start.isoformat(), "lva": b.lva.anzeigename, "thema": b.thema,
                             "geplant_minuten": b.geplante_minuten, "erledigt": b.erledigt,
                             "tatsaechliche_minuten": b.tatsaechliche_minuten, "status": b.status} for b in bloecke],
            "erledigt": sum(b.erledigt for b in bloecke), "offen": sum(not b.erledigt for b in bloecke),
            "lernminuten": sum(b.tatsaechliche_minuten if b.tatsaechliche_minuten is not None else (b.geplante_minuten if b.erledigt else 0) for b in bloecke),
            "arbeitsstunden": round(sum((b.ende - b.start).total_seconds() for b in arbeit if b.status == "bestaetigt") / 3600, 1),
            "lernereignisse": [{"zeitpunkt": e.zeitpunkt.isoformat(), "thema": e.thema.titel if e.thema else None, "art": e.art,
                                "ergebnis": e.ergebnis, "stufe": f"{e.stufe_vorher} → {e.stufe_nachher}"} for e in ereignisse],
            "altpruefungen": [{"datei": d.dateiname, "lva": d.lva.anzeigename, "punkte": d.punkte,
                               "punkte_max": d.punkte_max, "minuten": d.bearbeitet_minuten} for d in altpruefungen],
        }


@server.tool()
def neue_unterlagen(tage: int = 7, lva: str | None = None) -> list[dict]:
    """Unterlagen, die in den letzten `tage` Tagen erschienen sind (neuer Stoff) – offiziell und MB Cloud."""
    from .models import Dokument

    with sitzung() as session:
        seit = datetime.now() - timedelta(days=max(1, min(tage, 60)))
        abfrage = select(Dokument).where(Dokument.erschienen_am >= seit).order_by(Dokument.erschienen_am.desc())
        if gefunden := lva_finden(session, lva):
            abfrage = abfrage.where(Dokument.lva_id == gefunden.id)
        besucht = besuchte_lva_ids(session)
        return [{
            "dokument_id": d.id, "datei": d.dateiname, "lva": d.lva.anzeigename, "erschienen": d.erschienen_am.isoformat(),
            "art": "Aufzeichnung" if d.ist_link else (d.lernart or d.typ), "quelle": d.quelle or "tuwel",
            "offiziell": d.quelle != "mbcloud", "kategorie": d.kategorie, "jahr": d.jahr, "seiten": d.seiten,
            "text_lesbar": d.text_status == "fertig" or d.transkript_status == "fertig",
        } for d in session.scalars(abfrage) if d.lva_id in besucht]


@server.tool()
def lies_dokument(dokument_id: int, max_zeichen: int = 30000) -> dict:
    """Ganze Unterlage als Text mit Fundstellen (z. B. eine Altprüfung samt Lösung). Lange Dokumente werden gekürzt."""
    from .models import Dokument

    with sitzung() as session:
        doc = session.get(Dokument, dokument_id)
        if doc is None:
            raise ToolError(f"Unterlage {dokument_id} gibt es nicht.")
        abschnitte = list(session.scalars(select(Abschnitt).where(Abschnitt.dokument_id == doc.id).order_by(Abschnitt.reihenfolge)))
        text, gekuerzt = "", False
        for a in abschnitte:
            teil = (f"[{a.fundstelle}] " if a.fundstelle else "") + a.text + "\n\n"
            if len(text) + len(teil) > max(2000, min(max_zeichen, 100000)):
                gekuerzt = True
                break
            text += teil
        return {
            "dokument_id": doc.id, "datei": doc.dateiname, "lva": doc.lva.anzeigename,
            "quelle": doc.quelle or "tuwel", "offiziell": doc.quelle != "mbcloud", "kategorie": doc.kategorie, "jahr": doc.jahr,
            "text": text.strip() or None, "gekuerzt": gekuerzt,
            "hinweis": None if abschnitte else "Kein lesbarer Text – Scan ohne Texterkennung oder noch nicht verarbeitet.",
        }


def _termin_finden(session, angabe: str) -> Termin:
    """Termin über ID oder „<LVA> <Datum>“ (z. B. „Mechanik 14.10.“ oder „Mathe 2026-10-14“)."""
    text = angabe.strip()
    if text.isdigit() and (termin := session.get(Termin, int(text))):
        return termin
    datum = None
    if m := re.search(r"(\d{4})-(\d{2})-(\d{2})", text):
        datum = date(int(m[1]), int(m[2]), int(m[3]))
    elif m := re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})?", text):
        jahr = int(m[3]) + (2000 if m[3] and len(m[3]) == 2 else 0) if m[3] else date.today().year
        datum = date(jahr, int(m[2]), int(m[1]))
        if not m[3] and datum > date.today() + timedelta(days=30):
            datum = datum.replace(year=datum.year - 1)
    rest = re.sub(r"\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.(\d{2,4})?", " ", text).strip(" ,-")
    lva = lva_finden(session, rest) if rest else None
    abfrage = select(Termin).where(Termin.typ.in_(["VO", "VU", "UE", "SONSTIGE"])).order_by(Termin.start.desc())
    if lva:
        abfrage = abfrage.where(Termin.lva_id == lva.id)
    if datum:
        abfrage = abfrage.where(Termin.start >= datetime.combine(datum, time()), Termin.start < datetime.combine(datum + timedelta(days=1), time()))
    else:
        abfrage = abfrage.where(Termin.start <= datetime.now())
    termin = session.scalars(abfrage.limit(1)).first()
    if termin is None:
        raise ToolError(f"Kein Termin gefunden für „{angabe}“ – `termine` zeigt Termine mit termin_id.")
    return termin


@server.tool()
def aufzeichnung_zu_termin(termin: str, max_zeichen: int = 30000) -> dict:
    """Aufzeichnung (LectureTube) zu einem Vorlesungstermin samt Transkript mit Zeitmarken.
    `termin`: termin_id oder „<LVA> <Datum>“, z. B. „Mechanik 14.10.“."""
    from .models import Dokument

    with sitzung() as session:
        t = _termin_finden(session, termin)
        tag = t.start.date()
        videos = list(session.scalars(select(Dokument).where(Dokument.lva_id == t.lva_id, Dokument.ist_link.is_(True))))
        passend = sorted(
            (v for v in videos if (v.aufnahme_am or (v.erschienen_am.date() if v.erschienen_am else None)) is not None),
            key=lambda v: abs(((v.aufnahme_am or v.erschienen_am.date()) - tag).days),
        )
        video = passend[0] if passend and abs(((passend[0].aufnahme_am or passend[0].erschienen_am.date()) - tag).days) <= 3 else None
        ergebnis = {"termin_id": t.id, "termin": t.anzeigename, "start": t.start.isoformat(), "lva_id": t.lva_id,
                    "lva": t.lva.anzeigename, "aufzeichnung": None, "transkript": None}
        if video is None:
            ergebnis["hinweis"] = "Keine Aufzeichnung zu diesem Termin gefunden (±3 Tage)."
            return ergebnis
        abschnitte = list(session.scalars(select(Abschnitt).where(Abschnitt.dokument_id == video.id).order_by(Abschnitt.reihenfolge)))
        text = ""
        for a in abschnitte:
            teil = f"[{a.fundstelle}] {a.text}\n"
            if len(text) + len(teil) > max_zeichen:
                break
            text += teil
        ergebnis.update(aufzeichnung={"dokument_id": video.id, "titel": video.dateiname, "url": video.quelle_url,
                                      "aufnahme_am": (video.aufnahme_am or tag).isoformat(), "dauer_sekunden": video.dauer_sekunden},
                        transkript=text.strip() or None)
        if not abschnitte:
            ergebnis["hinweis"] = ("Noch kein Transkript – Transkription auf „KI verbinden“ einschalten."
                                   if video.transkript_status is None else f"Transkript fehlgeschlagen: {video.transkript_fehler}")
        return ergebnis


@server.tool()
def altpruefung_bearbeitet(dokument_id: int, minuten: int | None = None, punkte: float | None = None,
                           punkte_max: float | None = None) -> dict:
    """Altprüfung als bearbeitet markieren (Zeitbedarf, erreichte und maximale Punkte); sie wird dann nicht mehr eingeplant."""
    from .models import Dokument

    with sitzung() as session:
        doc = session.get(Dokument, dokument_id)
        if doc is None or doc.kategorie != "altpruefung":
            raise ToolError(f"{dokument_id} ist keine Altprüfung – `altpruefungen` zeigt die dokument_id.")
        if punkte is not None and punkte_max is not None and punkte > punkte_max:
            raise ToolError("Mehr Punkte als möglich.")
        doc.bearbeitet_am, doc.bearbeitet_minuten, doc.punkte, doc.punkte_max = datetime.now(), minuten, punkte, punkte_max
        session.commit()
        return {"dokument_id": doc.id, "datei": doc.dateiname, "punkte": punkte, "punkte_max": punkte_max, "minuten": minuten}


@server.tool()
def wochenplan_vorschlagen(woche: str | None = None, grund: str | None = None) -> dict:
    """Lässt den Hub eine Woche nach seinen Planungsregeln neu vorschlagen (Pflichttermine, dann Arbeit, dann Lernen).
    Bestätigte Blöcke bleiben; es entstehen nur Vorschläge, die der Student im Hub bestätigt."""
    from .planung_service import KeineRegelFehler, schlage_woche_vor

    with sitzung() as session:
        tag = _datum(woche, date.today())
        try:
            v = schlage_woche_vor(session, tag)
        except KeineRegelFehler as fehler:
            raise ToolError(str(fehler)) from fehler
        return _json({
            "woche": v["woche"], "grund": grund, "arbeit_stunden": v["verplant_stunden"], "arbeit_fehlend": v["fehlende_stunden"],
            "lern_stunden": v["lern_stunden"],
            "lernbloecke": [{"start": b.start.isoformat(), "ende": b.ende.isoformat(), "lva": b.lva.anzeigename,
                             "thema": b.thema} for b in v["lernbloecke"]],
            "arbeitsbloecke": [{"start": b.start.isoformat(), "ende": b.ende.isoformat()} for b in v["bloecke"]],
            "konflikte": v["konflikte"], "hinweise": v["hinweise"], "begruendungen": v["begruendungen"],
        })


# --- Prompt-Vorlagen (in Claude Desktop über „+“ → studien-hub) ---------------------------------------

from . import mcp_vorlagen  # noqa: E402


@server.tool()
def vorlage(name: str, lva: str | None = None, thema: str | None = None, termin: str | None = None,
            grund: str | None = None, woche: str | None = None, minuten: str | None = None) -> dict:
    """Ablauf einer Lernvorlage holen, wenn der Student eine nennt (z. B. „Starte thema_lernen für Mechanik 1,
    Thema Reibung“) – danach Schritt für Schritt danach vorgehen. Vorlagen: thema_lernen (lva, thema), wochenstart,
    wiederholung (lva optional), pruefung_simulieren (lva, minuten optional), vorlesung_nachholen (termin),
    plan_anpassen (grund, woche optional). Funktioniert auch, wo der Client Prompt-Vorlagen nicht anzeigt."""
    werte = {"lva": lva, "thema": thema, "termin": termin, "grund": grund, "woche": woche, "minuten": minuten}
    try:
        return {"vorlage": name, "ablauf": mcp_vorlagen.vorlage_text(name.strip().lower().replace(" ", "_"), werte)}
    except ValueError as fehler:
        raise ToolError(str(fehler)) from fehler


@server.prompt(title="Thema lernen", description="Erklärung in kleinen Schritten mit Verständnisfragen, 3 Kontrollfragen, Wissensstand aktualisieren")
def thema_lernen(lva: str, thema: str) -> str:
    return mcp_vorlagen.thema_lernen(lva, thema)


@server.prompt(title="Wochenstart", description="Rückblick, neuer Stoff, Prüfungen, fällige Wiederholungen – 3 Prioritäten und Lernblock-Vorschläge")
def wochenstart() -> str:
    return mcp_vorlagen.wochenstart_text()


@server.prompt(title="Wiederholung", description="Quiz zu allen fälligen Themen, Abstände nach Spaced Repetition anpassen")
def wiederholung(lva: str | None = None) -> str:
    return mcp_vorlagen.wiederholung(lva)


@server.prompt(title="Prüfung simulieren", description="Noch nicht gerechnete Altprüfung mit Zeitlimit, Bewertung, Fehleranalyse pro Thema")
def pruefung_simulieren(lva: str, minuten: str = "90") -> str:
    return mcp_vorlagen.pruefung_simulieren(lva, int(minuten) if str(minuten).strip().isdigit() else 90)


@server.prompt(title="Vorlesung nachholen", description="Zusammenfassung der Aufzeichnung mit Skript-Verweisen und 3 Kontrollfragen")
def vorlesung_nachholen(termin: str) -> str:
    return mcp_vorlagen.vorlesung_nachholen(termin)


@server.prompt(title="Plan anpassen", description="Neuer Wochenplan als Vorschläge nach den Planungsregeln des Hubs")
def plan_anpassen(grund: str, woche: str | None = None) -> str:
    return mcp_vorlagen.plan_anpassen(grund, woche)


def _json(wert):
    """Datumswerte für die Ausgabe in Text umwandeln."""
    if isinstance(wert, dict):
        return {k: _json(v) for k, v in wert.items()}
    if isinstance(wert, list):
        return [_json(v) for v in wert]
    if isinstance(wert, (date, datetime)):
        return wert.isoformat()
    return wert


def main() -> None:
    import logging

    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    server.run("stdio")


if __name__ == "__main__":
    main()
