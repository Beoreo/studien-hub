# Studien-Hub – Hinweise für Claude Code

Das fachliche Konzept steht in `KONZEPT.md`. Vor größeren Änderungen dort nachlesen.
Aktueller Stand: **Stufe 1** (Kalender, Arbeitszeiten, Filter und Export) ist umgesetzt, **Stufe 2**
(TUWEL-Sync) läuft über eine Browser-Erweiterung, weil TUWEL Webservice-Tokens nach < 1 min verwirft.
**Stufe 3** (Text, Abschnitte, Embeddings, Suche, Transkripte) und **Stufe 4** (Themen, Wissensstand,
MCP-Server für Claude Desktop) sind im Minimum umgesetzt (KONZEPT.md „Inhaltsverarbeitung und KI“).

## Tech-Stack

| Baustein | Technik |
| --- | --- |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 |
| Datenbank | SQLite (eine Datei unter `daten/studienhub.db`) mit sqlite-vec (Vektoren) und FTS5 (Volltext) |
| Oberfläche | React 18 + Vite + FullCalendar 6 |
| iCal | `icalendar` (Import und Export) |
| PDF-Export | `fpdf2` |
| Zeitsteuerung | APScheduler (täglicher TISS-Import) |
| Inhalte | PyMuPDF (Text, Gliederung), fastembed (lokales Embedding-Modell, ONNX), faster-whisper (Transkripte) |
| KI | MCP-Python-SDK 2.x (`mcp.server.mcpserver.MCPServer`, stdio) für Claude Desktop |
| Betrieb | keyring (Windows-Anmeldeinformationsverwaltung), pystray (Infobereich), PyInstaller (onedir), Inno Setup 6 |

## Ordnerstruktur

```
studien-hub/
  KONZEPT.md            Fachkonzept
  CLAUDE.md             diese Datei
  ANLEITUNG.md          Installation, Update, Fehlerbehebung (für den Alltagsbetrieb)
  VERSION               einzige Stelle der Versionsnummer (Backend, Setup, Erweiterung im Paket)
  start.ps1             startet Backend und Frontend im Entwicklungsmodus
  build.ps1             erzeugt dist\StudienHub-Setup-<Version>.exe (Frontend, Tests, PyInstaller, Inno Setup)
  installer/            studienhub.iss (Inno Setup), sandbox-starten.ps1 + sandbox-test.ps1 (Installationstest)
  daten/                SQLite-Datenbank des Entwicklungsmodus (nicht in Git)
  build/, dist/         Zwischenstände und Setup-Datei (nicht in Git)
  backend/
    requirements.txt    requirements-build.txt (PyInstaller), studienhub.spec, studienhub_start.py (exe)
    app/
      main.py           FastAPI-App, CORS, Scheduler, Auslieferung des gebauten Frontends
      config.py         Betriebsart (Entwicklung/Produktion), Pfade, Zeitzone, Version, Zugangsdaten-Zugriff
      desktop.py        StudienHub.exe: Infobereich, Einzelinstanz, --mcp, --eintragen/--austragen/--daten-loeschen
      geheimnisse.py    Zugangsdaten über keyring; einmalige Übernahme aus einer .env
      jobs.py           geplante Läufe (Zeitplan, Protokoll je Job, Nachholen verpasster täglicher Läufe)
      sicherung.py      tägliche Sicherung (SQLite-Backup-API), 14 behalten, Wiederherstellen im laufenden Betrieb
      protokoll.py      Logs mit Rotation, letzte Warnungen/Fehler für die Status-Seite
      autostart.py      HKCU\...\Run (nur als exe)
      einrichtung.py    Einrichtungsassistent: Datenübernahme aus dem Entwicklungsordner, Modelle laden, Token
      db.py             Engine, Session, Base
      models.py         Datenmodell (LVA, Termin, Arbeitsblock, Arbeitsregel, Einstellung)
      schemas.py        Pydantic-Schemas der API
      tiss_import.py    Parsen und Abgleich des TISS-iCal-Feeds
      planung.py        Verteilungs-Algorithmus (reine Logik, ohne DB)
      lernbedarf.py     Lernbedarf je LVA und Woche aus den ECTS (reine Logik): Lernphase, Nachholen
      lernplanung.py    Lernblöcke planen (reine Logik): Zeit nach Wochenbedarf, Stoff auf die Blöcke verteilen
      lernaufwand.py    DB-Seite des Lernbedarfs: Prüfungen, Präsenz, gelernte Zeit, Stoffmenge je Unterlage
      pruefungen.py     Prüfungstermine je LVA: Abgleich mit TISS/TUWEL, Anmeldung, Abruf-Liste für die Erweiterung
      feiertage.py      gesetzliche Feiertage AT (Paket holidays) und freie Tage der Arbeitsregel
      planung_service.py  DB-Anbindung des Algorithmus
      lva_auswahl.py    welche LVAs besucht werden (STEOP-Status, Variante)
      steop_kriterien.py  STEOP-Kriterienbaum aus TISS bewerten, Variante wählen (reine Logik)
      filter.py         gemeinsame Filterlogik für Kalender und Export
      export.py         iCal-, CSV- und PDF-Export
      tuwel_sync.py     TUWEL-Sync auf Hub-Seite: Kurs->LVA, Prüfsummen, Ablage unter daten/unterlagen
      tuwel_client.py   Moodle-REST mit Token (derzeit ungenutzt: Tokens leben bei TUWEL < 1 min)
      extraktion.py     Text aus PDF/Folien/Word lesen, Gliederung erkennen, Abschnitte bilden (ohne DB)
      embedding.py      lokales Embedding-Modell (fastembed); HashEmbedder für Tests
      suche.py          Abschnitte speichern (sqlite-vec + FTS5), hybride Suche
      verarbeitung.py   Hintergrundjobs: Unterlagen verarbeiten, Videos transkribieren (faster-whisper)
      wissensstand.py   Stufen und Wiederholungsabstände (reine Logik)
      themen.py         Themen aus der Kapitelstruktur, Lernereignisse, Übersicht
      mcp_server.py     MCP-Server für Claude Desktop (stdio, 20 Werkzeuge, 6 Prompt-Vorlagen, Server-Anweisungen)
      mcp_vorlagen.py   Texte der Prompt-Vorlagen (auch für den Wochenbericht)
      wochenbericht.py  Wochenbericht aus den neuen TUWEL-Unterlagen der Woche (ohne Claude), Sonntagslauf
      pruefungsstoff.py Themen aus hochgeladenem Prüfungsstoff, Zeitabschnitte bis zu den Prüfungen (reine Logik)
      ki_einrichtung.py Eintrag in claude_desktop_config.json mit Sicherung
      mbcloud.py        MB Cloud (reine Logik): Einteilung, Datum/Jahr, Zuordnung, Lösung↔Prüfung, WebDAV-Antwort
      mbcloud_client.py WebDAV mit App-Passwort, Pause je Anfrage, Nextcloud-Login-Flow v2
      mbcloud_sync.py   Index (nur geänderte Ordner per ETag), Zuordnung, Downloads mit SHA-256-Duplikaterkennung
      routers/          API-Endpunkte unter /api/...
    tests/              pytest
  frontend/
    src/design.css      Design-Variablen und Komponenten-Klassen (Farben, Schrift, Abstände, Radien)
    src/ui.jsx          einheitliche Bausteine (Button, Feld, Karte, Tabelle, Badge, Hinweis, Dialog, …) und Icons
    src/styles.css      App-Rahmen und Kalender
    src/components/     Seiten (eigenes CSS je Seite nur bei Bedarf, daneben)
    scripts/screenshots.mjs  Screenshots aller Reiter bei 1440 und 390 px (Design-Prüfung)
  browser-erweiterung/  TUWEL- und TISS-STEOP-Sync (Manifest V3, Chrome/Edge/Firefox), liest mit der Browser-Sitzung
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
- **Zugangsdaten nie in Dateien:** nur über `geheimnisse.py` (keyring, Dienst „StudienHub“). Tests setzen
  `STUDIENHUB_GEHEIMNISSE=speicher` und `STUDIENHUB_DATEN` auf einen Temp-Ordner (conftest) – nie die echte Verwaltung
  oder den echten Datenordner berühren.

## Betrieb (installierte Version)

- Zwei Betriebsarten (`config.PRODUKTION`): Entwicklung mit Daten in `daten/`; Produktion (`sys.frozen`) mit Programm in
  `%LOCALAPPDATA%\Programs\StudienHub` und Daten in `%LOCALAPPDATA%\StudienHub` (Logs, Sicherungen, Modelle darunter).
  Beide nutzen Port 8000 (nur 127.0.0.1) und dieselben Zugangsdaten – nie gleichzeitig laufen lassen.
- CORS nur für `chrome-extension://<ERWEITERUNG_ID>` (fester `key` im Manifest, ID in `config.ERWEITERUNG_ID`) und
  `moz-extension://`. Die Erweiterung holt den Schlüssel selbst (`/api/tuwel/einrichtung`) und vergisst ihn bei 401.
- Neue geplante Läufe in `jobs.standard_jobs` eintragen (nicht direkt im Scheduler), damit Status-Seite, Symbol im
  Infobereich und Nachholen sie kennen. Täglich + `nachholen=True` = beim Start nachholen, wenn verpasst.
- „Jetzt synchronisieren“: TISS und MB Cloud sofort; für TUWEL setzt der Hub `tuwel_sync_angefordert`, die Erweiterung
  fragt alle 2 min (`/api/tuwel/sync/anforderung`).
- Neue Pakete mit DLLs, Daten- oder Modelldateien bzw. dynamischen Importen in `studienhub.spec` (`collect_all`)
  aufnehmen und die gebaute exe testen (`build.ps1`, dann `installer\sandbox-starten.ps1`).
- Version nur in `VERSION` ändern; ein Update ist eine neue Setup-Datei (gleiche AppId in `installer/studienhub.iss`).
- PowerShell-Skripte (`*.ps1`) als **UTF-8 mit BOM** speichern: Windows PowerShell 5.1 liest sie sonst als ANSI, und
  ein „–“ oder „““ wird zum Anführungszeichen, das die Zeile zerbricht.

## Design-Regeln (Oberfläche)

- **Nur Variablen aus `src/design.css`** – keine Hex-Farben, Grautöne oder freien px-Abstände in Komponenten/CSS.
  Farben: Primär `--primaer` (#006598) für den Hauptbutton, aktive Reiter, Links, Fokus, Auswahl; Text `--text`
  (#320E3B); neutrale Töne nur als Deckkraft-Ableitungen von `--text` (`--text-leise`, `--flaeche`, `--rand` …);
  `--bestaetigen` (#2C6E49) für Übernehmen/Bestätigen/Speichern; `--verwerfen` (#DF2935) für Verwerfen/Löschen/Fehler/
  Konflikte (Text auf Rot-Tönung: `--verwerfen-dunkel`). Neue Farbkombinationen auf WCAG AA prüfen (Text ≥ 4,5:1, UI ≥ 3:1).
- Eine Schrift, drei Größen (`--groesse-klein` 13, `--groesse` 15, `--groesse-gross` 20 px), Abstände im 8-px-Raster
  (`--a1` … `--a6`, `--a0` = 4 px nur innerhalb von Komponenten), ein Radius `--radius`.
- **Nur Bausteine aus `src/ui.jsx`**: Button (primaer | bestaetigen | verwerfen | umriss; reines Abbrechen = umriss),
  IconButton, Feld/Eingabe/Auswahl/Kontrolle, Karte, Tabelle, Badge, Hinweis, Dialog/Rueckfrage, Seitenleiste, Menue,
  LeererZustand, SeitenKopf. Fehlt einer, dort ergänzen statt in einer Seite nachbauen. Kein `window.confirm`.
- **Pro Ansicht genau ein Hauptbutton** in Primärfarbe; weitere Aktionen zurückhaltend (umriss, Icon, `Menue`).
- **Höchstens ein Hinweisbereich** je Ansicht: `Hinweis` mit einer Zeile Zusammenfassung (wichtigste Zahlen),
  Details aufklappbar. Erklärtexte auf einen Satz, Selteneres in aufklappbare Karten.
- **Icons nur über `<Icon name>`** (lucide-react, eine Größe/Strichstärke), keine Emojis oder Sonderzeichen. Feste
  Zuordnung in `ICONS` (STEOP star, Anwesenheit user-check, Aufzeichnung video, Prüfung graduation-cap, Abgabe
  file-check, Arbeit briefcase, Lernen book-open, frei calendar-off, TUWEL school, MB Cloud cloud, KI sparkles,
  Warnung triangle-alert). Icon ohne Text braucht `label` (Tooltip + aria-label). Neue Symbole in die zentrale
  Legende (`components/Legende.jsx`), keine Legenden in einzelnen Ansichten.
- Kalender: Einträge hell neutral mit LVA-Farbe als 4-px-Streifen; Arbeit flächig neutral, Lernen mit Buch-Symbol,
  Vorschläge gestrichelt; im Eintrag nur Kurztitel (`kurzTitel`: eigener Kurzname, sonst gekürzt), Zeit, Symbole –
  Details in der Seitenleiste. LVA-Farben aus der Palette `--lva-1 … 10` (Backend: `STANDARD_FARBEN`).
- Jede Änderung an der Oberfläche bei 1440 und 390 px prüfen: `node scripts/screenshots.mjs <url> <ordner> [reiter]`
  meldet horizontalen Überlauf; keine Überlappungen, abgeschnittenen Texte oder zu dichten Stellen.

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

# MCP-Server wie Claude Desktop testen (alle Werkzeuge, gegen eine Kopie der Datenbank)
cd backend; .\.venv\Scripts\python scripts\mcp_test.py --frage "Freikörperbild"

# Tests der Browser-Erweiterung
cd browser-erweiterung; npm test

# Frontend bauen – danach liefert das Backend die Oberfläche selbst unter http://127.0.0.1:8000 aus
cd frontend; npm run build

# Setup-Datei bauen (dist\StudienHub-Setup-<Version>.exe) und in der Windows Sandbox testen
.\build.ps1
.\installer\sandbox-starten.ps1

# Design-Prüfung: Screenshots aller Reiter (1440 und 390 px); Vite gegen ein anderes Backend: STUDIENHUB_API, VITE_PORT
cd frontend; node scripts/screenshots.mjs http://localhost:5173 ..\screenshots
```

## Fachliche Kernpunkte

- Eine `Lva` je LVA-Nummer: VO und UE gleichen Titels sind eigene LVAs, unterschieden über `Lva.typ`
  (`anzeigename` = Kurzname oder „Titel Typ“; Oberfläche: `lvaName`/`kurzTitel` mit Typ). `LvaTeil`e sind nur die
  Gruppen/Plenartermine derselben Nummer (`lva_struktur.py`); Markierungen und TUWEL-Kurs je Teil. Ältere, zusammen-
  gefasste LVAs trennt `lvas_trennen` beim Start (STRUKTUR_VERSION 3, mit Sicherungskopie; STEOP-Variante wird ergänzt).
  STEOP-Blätter ohne Nummer werden mit Typ zugeordnet (Schlüssel `titel:<typ>:<titel>`).
  Ein Termin kann Markierungen über `*_abweichung` überschreiben (`None` = Wert des Teils gilt). TISS-Termine
  derselben Nummer ohne Gruppenangabe (Plenartermine) gehören zum Teil ihrer Nummer.
- Ferien, Feiertage, Rektorstag, „vorlesungsfrei“ aus TISS sind keine LVAs, sondern `FreierZeitraum` und sperren
  Arbeit und Lernen wie Feiertage. Die einmalige Bereinigung alter Datenbanken läuft beim Start (mit Sicherungskopie).
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
- Erscheinungsdatum (`Dokument.erschienen_am` + `erschienen_quelle`): Dateien zuerst TUWEL-Zeit der Aktivität aus
  `core_course_get_updates_since` (nur wenn die Aktivität genau eine Datei hat), sonst `Last-Modified`;
  LectureTube-Aufzeichnungen das Aufnahmedatum; andere Video-Links die TUWEL-Zeit der Einstellungen.
  Fehlende Daten fordert der Hub mit `datum_fehlt` an, die Erweiterung holt nur den Kopf (HEAD) und
  schickt sie als `nachtrag` – das ändert keinen Status. „Neu seit letztem Sync“ = Status neu/geaendert.
- Wochenvorschlag (`planung_service.schlage_woche_vor`, KONZEPT.md „Wochenplanung“): Pflichttermine → Arbeit
  (Wochenstunden sind Pflicht, bestätigte Lernblöcke sind `belegte_zeiten`) → Lernen bis zum Wochenbedarf → Freizeit.
  Reicht die Zeit nicht, wird Lernzeit gekürzt (zuerst LVAs ohne Lernphase), nie Arbeit; gemeldet in `rueckstaende`.
- Lernbedarf (`lernbedarf.py`): (ECTS × 25 h − Präsenz) × `Arbeitsregel.ects_faktor` (0,7) × Ziel (`Lva.ziel`:
  bestehen 0,6 / normal 0,8 / gut 1,0) × `Lva.bedarf_faktor`. Lernblöcke nur in den Lernfenstern vor Prüfungen:
  Prüfungswoche plus `Lva.lernwochen` Wochen davor (None = `Arbeitsregel.lernphase_wochen`), frühestens ab dem ersten
  Termin; ohne Prüfung kein Lernbedarf. Rückstand nur innerhalb des Fensters (`gelernt_je_woche`); Priorität beim
  Kürzen = Wochen bis zur Prüfung. Gelernt = `tatsaechliche_minuten` oder geplant.
- Eigene Termine im Kalender: zu einer LVA = `Termin` mit `quelle="manuell"` (TISS-Import lässt sie stehen, nur sie
  sind verschieb-/löschbar), ohne LVA = `PersoenlicherTermin` (Planung: wie Pflichttermin). Änderungen planen die
  Woche neu (`rest_neu_planen`).
- Wochenbericht (`wochenbericht.py`): ohne Claude, aus den TUWEL-Unterlagen, die in der Woche erschienen sind oder neu
  gefasst wurden; sonntags (Standard an) bzw. Montag nachgeholt, auf Knopfdruck sofort.
- Wissensstand: Zeitstrahl je besuchter LVA mit einem Abschnitt bis zu jeder Prüfung (`themen.zeitstrahl_out`).
  Prüfungsstoff hochladen (`POST /api/wissen/stoff`, `pruefungsstoff.themen_aus_text`: Gliederung, Folientitel oder
  Zeilen) setzt die Themen der Prüfung (`Thema.pruefungen`, ISO-Tage; None = alle Prüfungen, [] = keine); Lernstand
  bleibt, Stoff-Themen ohne Lernstand verschwinden beim Ersetzen.
  Prüfungen (`lernaufwand.pruefungstermine`): Feed-Termine vom Typ PRUEFUNG plus die angemeldeten `Pruefungstermin`e
  (ein Termin am Tag einer Feed-Prüfung zählt nicht doppelt); ohne Anmeldung der nächste angebotene als „vorschlag“.
  `Lva.eigene_pruefungen` und `pruefung_am` sind veraltet (beim Start in `Pruefungstermin` umgezogen).
- Prüfungstermine (`pruefungen.py`, Reiter „Prüfungen“): Der TISS-Feed kennt nur angemeldete Prüfungen. Die Erweiterung
  (`pruefungen.js`) liest daher nach jedem Lauf (höchstens alle 12 h, auf Knopfdruck immer) die TISS-Prüfungslisten
  (`examDateList.xhtml`, Nummern und Semester aus `GET /api/pruefungen/abruf`) und den TUWEL-Kalender
  (`core_calendar_get_calendar_monthly_view`) und schickt sie an `POST /api/pruefungen/sync` (Schlüssel nötig); eine
  geöffnete Prüfungsliste meldet `tiss-inhalt.js` (unvollständig: nichts wird gelöscht). Abgleich über `quelle` +
  `extern_id`; fehlende Termine fallen nur bei vollständiger Liste weg, nie selbst bearbeitete (`bearbeitet`) oder
  angemeldete (die Anmeldung wandert auf einen neuen Termin am selben Tag). Gelöschte importierte Termine bleiben
  `ausgeblendet`. `angemeldet` None = automatisch (TISS meldet die Anmeldung oder Feed-Prüfung am selben Tag); die
  Auswahl je LVA setzt genau einen Termin. TUWEL-Termine am Tag eines TISS-Termins werden nicht angezeigt.
  Kalender: angemeldete Termine (`art` pruefung) und Anmeldestarts (`art` anmeldung, ganztägig; mit gewähltem Termin nur
  dessen Start). Zeitstrahl-Maßstab: `frontend/src/zeitstrahl.js` (Wurzel der Tage, Mindestabstand; `npm test`).
- Unterlagen bestimmen nur den Stoff eines Lernblocks (`stoff_zuteilen`, `Lernblock.zuteilung` = Stoffmenge je
  Dokument): Gewicht nach Seiten/Dauer, Werte in `Lva.lernparameter`, `Dokument.lern_minuten` überschreibt (0 = nicht
  lernen). Offener Stoff (jedes Alter) verteilt sich auf die Wochen bis zur Lernphase.
- STEOP-Status aus TISS: die Erweiterung liest die Seite „STEOP Status“ (`tiss-inhalt.js` beim Öffnen, danach
  bei jedem Lauf über die gemerkte Adresse mit der TISS-Sitzung), wertet sie in `tiss.js` aus (Symbole über die Legende)
  und schickt sie an `POST /api/tiss/steop` (Schlüssel nötig). Unsicherer Status (None) ändert nichts.
- Kursauswahl (`lva_auswahl.py`, `lade_auswahl` → `Auswahl`): vor Abschluss der STEOP (Einstellung `steop_abgeschlossen`)
  gilt eine Variante des neuesten Semesters. STEOP-Teil: aus dem Kriterienbaum der TISS-Detailansicht („P4: 9 ECTS aus:“
  → „1 aus:“/„Alle aus:“ → LVAs; `tiss.js: kriterienLesen`) wählt `steop_kriterien.variante_waehlen` die LVAs, die
  möglichst viele P-Kriterien mit möglichst wenig ECTS erfüllen („Alle aus“-LVAs immer); ohne Kriterien alle STEOP-LVAs
  (LVA oder Teil `steop`, oder Nummer aus TISS). Jede Textzeile unter einem Kriterium ist eine LVA; ohne Nummer wird sie
  über den Titel zugeordnet (`steop_kriterien.zuordnen`, Typ/Semester ignoriert, wortweise). Ein zugeklapptes P-Kriterium
  (Hintergrundabruf) behält die zuletzt gesehenen LVAs; die Roh-HTML der Detailansicht liegt in `steop_tiss_html`
  (letzte mit LVAs) und `steop_tiss_html_letzt`. Semester = laufendes nach Datum (`semester_am`), nicht das höchste.
  Dazu Nicht-STEOP-LVAs bis zu den erlaubten ECTS (`auffuellen`;
  `steop_erlaubte_ects`, sonst TISS). Ungespeichert wird sie bei jedem Lesen erzeugt; bearbeitet steht sie in
  `steop_variante` (`PUT /api/lvas/steop/variante/{id}`, neu: `POST /api/lvas/steop/variante`).
  `Lva.besuchen` gilt nur nach Abschluss: True/False blendet manuell ein/aus, None = besucht.
  Ausgeblendete LVAs: im Kalender ausgegraut (`ausgeblendet`), nicht im Export, keine Sperren, kein Lernbedarf.
  Änderungen rufen `auswahl_geaendert` (Lernvorschläge weg, Wochen mit Vorschlägen neu planen).
- `POST /api/arbeit/vorschlaege-loeschen` löscht alle unbestätigten Arbeitsvorschläge aller Wochen.
- Arbeitsplaner: zwei Blöcke eines Tages dürfen direkt aneinander liegen (`_anschluss`), Leerlauf zwischen Arbeits-
  blöcken ohne Uni/Lernen kostet (`FAKTOR_LEERLAUF`). Bei Änderungen am Algorithmus `planung_service.PLANER_VERSION`
  erhöhen: Start und TISS-Import planen offene Vorschläge neu, wenn Version oder Kursauswahl abweichen.
- MB Cloud (KONZEPT.md „MB Cloud“): inoffiziell, Zugang nur in der `.env` (`MBCLOUD_URL`, `MBCLOUD_BENUTZER`,
  `MBCLOUD_APP_PASSWORT`, per Login-Flow eingetragen). Index in `MbCloudOrdner`/`MbCloudDatei`, Downloads als
  `Dokument` mit `quelle="mbcloud"`, `kategorie`, `jahr` (tuwel_cm_id 0, schluessel `mbcloud:<pfad>`). MB-Cloud-
  Dokumente zählen nicht zum Stoff; in der Lernphase füllt `offene_altpruefungen` Lernblöcke (eine pro Block).
  Schonend: nie parallel, `MBCLOUD_PAUSE_SEKUNDEN` zwischen Anfragen; Tests nur gegen nachgebauten WebDAV-Server.
- Stufe 3: Abschnitte (`Abschnitt`) mit Herkunft; Vektoren in `abschnitt_vec` (vec0, rowid = id), Volltext in
  `abschnitt_fts` – beide beim Löschen mitpflegen (`suche.abschnitte_loeschen`). Verarbeitung/Transkription laufen nur,
  wenn auf „KI verbinden“ eingeschaltet (Einstellungen `ki_verarbeitung_aktiv`, `ki_transkription_aktiv`); erst dann
  wird ein Modell geladen. Tests nutzen `HashEmbedder` (`setze_standard_embedder`), nie das echte Modell.
- MCP-Server: Eingabefehler als `ToolError` melden (andere Ausnahmen gelten in MCP 2.x als Absturz). Er setzt
  `STUDIENHUB_OFFLINE=1`; nichts auf stdout ausgeben. Lernblöcke von Claude: `Lernblock.quelle="ki"`, Status vorschlag,
  bleiben beim Neuplanen stehen und zählen als belegt. `scripts/mcp_test.py` prüft alle Werkzeuge über stdio.
- Verschieben, Löschen, Fixieren eines Blocks plant den Rest der Woche neu (`rest_neu_planen`, nur wenn die Woche
  Vorschläge hat). Gelöschte Vorschläge landen in `VerworfenerVorschlag` und werden dort nicht wieder vorgeschlagen.
- Eine in der LVA gespeicherte `tuwel_kurs_id` gilt nur bei passendem Semester; bei Zuordnungswechsel
  ziehen die Unterlagen samt Dateien um (`setze_kurs_lva`).
- Geheimnisse nur in `.env` (ignoriert); `.env.example` bleibt leer (Test + pre-commit-Hook prüfen das).
- Neue Spalten in bestehenden Tabellen in `db.NACHTRAEGLICHE_SPALTEN` eintragen (einfache Migration).
- Ein erneuter TISS-Import übernimmt nur Änderungen (Abgleich über die iCal-UID) und plant nur die
  betroffenen Wochen neu.
