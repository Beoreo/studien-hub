# Studien-Hub – Hinweise für Claude Code

Das fachliche Konzept steht in `KONZEPT.md`. Vor größeren Änderungen dort nachlesen.
Aktueller Stand: **Stufe 1** (Kalender, Arbeitszeiten, Filter und Export) ist umgesetzt, **Stufe 2**
(TUWEL-Sync) läuft über eine Browser-Erweiterung, weil TUWEL Webservice-Tokens nach < 1 min verwirft.

## Tech-Stack

| Baustein | Technik |
| --- | --- |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 |
| Datenbank | SQLite (eine Datei unter `daten/studienhub.db`); ab Stufe 3 zusätzlich sqlite-vec |
| Oberfläche | React 18 + Vite + FullCalendar 6 |
| iCal | `icalendar` (Import und Export) |
| PDF-Export | `fpdf2` |
| Zeitsteuerung | APScheduler (täglicher TISS-Import) |
| Später | PyMuPDF (Stufe 3), faster-whisper (Stufe 3), MCP-Python-SDK (Stufe 4) |

## Ordnerstruktur

```
studien-hub/
  KONZEPT.md            Fachkonzept
  CLAUDE.md             diese Datei
  start.ps1             startet Backend und Frontend im Entwicklungsmodus
  daten/                SQLite-Datenbank (nicht in Git)
  backend/
    requirements.txt
    app/
      main.py           FastAPI-App, Scheduler, Auslieferung des gebauten Frontends
      config.py         Pfade, Zeitzone, Umgebungsvariablen
      db.py             Engine, Session, Base
      models.py         Datenmodell (LVA, Termin, Arbeitsblock, Arbeitsregel, Einstellung)
      schemas.py        Pydantic-Schemas der API
      tiss_import.py    Parsen und Abgleich des TISS-iCal-Feeds
      planung.py        Verteilungs-Algorithmus (reine Logik, ohne DB)
      feiertage.py      gesetzliche Feiertage AT (Paket holidays) und freie Tage der Arbeitsregel
      planung_service.py  DB-Anbindung des Algorithmus
      filter.py         gemeinsame Filterlogik für Kalender und Export
      export.py         iCal-, CSV- und PDF-Export
      tuwel_sync.py     TUWEL-Sync auf Hub-Seite: Kurs->LVA, Prüfsummen, Ablage unter daten/unterlagen
      tuwel_client.py   Moodle-REST mit Token (derzeit ungenutzt: Tokens leben bei TUWEL < 1 min)
      routers/          API-Endpunkte unter /api/...
    tests/              pytest
  frontend/
    src/                React-Komponenten
  browser-erweiterung/  TUWEL-Sync (Manifest V3, Chrome/Edge/Firefox), liest TUWEL mit der Browser-Sitzung
    lib.js tuwel.js hub.js sync.js   testbare Logik; background.js/popup.* nur Browser-Anbindung
    tests/              node --test
```

## Regeln

- Kommentare, Docstrings, Bezeichner der Fachdomäne und Oberflächentexte auf **Deutsch**.
- **Tests für jede Funktion**: neue Logik bekommt pytest-Tests in `backend/tests/`.
- Zeiten werden als *naive* lokale Zeit (Europe/Vienna) gespeichert. Eingehende Zeiten mit Zeitzone
  werden beim Import nach Europe/Vienna umgerechnet.
- Algorithmen ohne Datenbankzugriff halten (siehe `planung.py`), DB-Zugriff in Service-Modulen.
- Importe klein und austauschbar halten; Sync-Fehler sichtbar melden statt still zu schlucken.
- Alles bleibt lokal. Keine Daten an externe Dienste außer dem Abruf des eigenen TISS-Feeds.

## Befehle

```powershell
# Backend einrichten (einmalig)
cd backend; py -3.12 -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt

# Tests
cd backend; .\.venv\Scripts\python -m pytest

# Backend starten (http://127.0.0.1:8000, API-Doku unter /docs)
cd backend; .\.venv\Scripts\python -m uvicorn app.main:app --reload

# Entwicklung: startet Backend (Port 8000, falls nicht schon laufend) und Vite (http://localhost:5173)
cd frontend; npm install; npm run dev
# nur Vite, ohne Backend
cd frontend; npm run dev:frontend

# Tests der Browser-Erweiterung
cd browser-erweiterung; npm test

# Frontend bauen – danach liefert das Backend die Oberfläche selbst unter http://127.0.0.1:8000 aus
cd frontend; npm run build
```

## Fachliche Kernpunkte

- Markierungen (STEOP, Anwesenheitspflicht, Aufzeichnung) hängen an der LVA; ein Termin kann sie
  über `*_abweichung` überschreiben (`None` = LVA-Wert gilt).
- Arbeitsblöcke: `art` = `fix` | `flexibel`, `status` = `vorschlag` | `bestaetigt`.
  Verschobene oder bestätigte Vorschläge sind `bestaetigt` und werden nicht mehr neu geplant.
- `Arbeitsregel.stunden_pro_woche` ist die Gesamtstundenzahl; bestätigte Blöcke der Woche werden
  abgezogen, der Rest wird verteilt.
- An gesetzlichen Feiertagen (holidays, Land AT) und an den `freie_tage` der Arbeitsregel
  (einzelne Tage, Zeiträume, optional jährlich) wird keine Arbeitszeit vorgeschlagen. Beides
  erscheint im Kalender als ganztägiger grauer Eintrag.
- Die Verteilung (`planung.py`) sucht die beste Woche nach Punktzahl, nicht die früheste: Tagespläne
  je Tag, dynamische Programmierung über die Woche. Harte Regeln: Tagesgrenze Uni+Arbeit
  (`max_tag_stunden`), Lernfenster nach Vorlesungen sowie vor und am Vortag von Prüfungen/Abgaben,
  kein Block am Abend nach vollem Unitag. Gewichtet (0–10): gleichmaessig, buendeln, lernzeit,
  erholung, zerstueckelung. Der Vorschlag liefert `begruendungen`; offene Vorschläge lassen sich
  verwerfen (`POST /api/arbeit/verwerfen`).
- Termine mit „Abgabe/Deadline“ im Titel bekommen den Typ `ABGABE` (Frist, kein Anwesenheitstermin).
- TUWEL-Sync: Die Erweiterung meldet Kurse (`/api/tuwel/sync/kurse`), Inhalte je Kurs (`/sync/inhalt`, der Hub
  antwortet mit den URLs, die er braucht) und lädt nur diese hoch (`/sync/datei`). Schreibende Sync-Endpunkte
  verlangen den Kopf `X-Studienhub-Schluessel`. Neue Datei-Revision in TUWEL = neue URL; bei geändertem Inhalt
  bleibt die alte Datei als „name (alt JJJJ-MM-TT).ext“ erhalten. Videos nur als Link (`Dokument.ist_link`).
- LectureTube = TUWEL-Plugin `mod_opencast`: TUWEL holt die Episoden serverseitig von Opencast und rendert
  sie in die Seite (Serie: `li.episode` bzw. Tabelle, Episode: `window.episode`). Kein LTI, kein direkter
  Opencast-Zugriff, daher keine zusätzlichen Host-Berechtigungen. Jede Episode ist ein `Dokument` mit
  `episode_id` (Schlüssel `opencast:<id>`), `aufnahme_am`, `dauer_sekunden`, `medien_url`; Episodenseiten
  werden nur für neue Aufzeichnungen ohne Dauer geöffnet.
- Eine in der LVA gespeicherte `tuwel_kurs_id` gilt nur bei passendem Semester; bei Zuordnungswechsel
  ziehen die Unterlagen samt Dateien um (`setze_kurs_lva`).
- Geheimnisse nur in `.env` (ignoriert); `.env.example` bleibt leer (Test + pre-commit-Hook prüfen das).
- Neue Spalten in bestehenden Tabellen in `db.NACHTRAEGLICHE_SPALTEN` eintragen (einfache Migration).
- Ein erneuter TISS-Import übernimmt nur Änderungen (Abgleich über die iCal-UID) und plant nur die
  betroffenen Wochen neu.
