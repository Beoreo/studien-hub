# Studien-Hub – Hinweise für Claude Code

Das fachliche Konzept steht in `KONZEPT.md`. Vor größeren Änderungen dort nachlesen.
Aktueller Stand: **Stufe 1** (Kalender, Arbeitszeiten, Filter und Export) ist umgesetzt.

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
      routers/          API-Endpunkte unter /api/...
    tests/              pytest
  frontend/
    src/                React-Komponenten
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
- Neue Spalten in bestehenden Tabellen in `db.NACHTRAEGLICHE_SPALTEN` eintragen (einfache Migration).
- Ein erneuter TISS-Import übernimmt nur Änderungen (Abgleich über die iCal-UID) und plant nur die
  betroffenen Wochen neu.
