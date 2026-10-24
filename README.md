# Studien-Hub

Ein lokaler Studienplaner für Studierende der TU Wien. Er sammelt Termine aus TISS, Unterlagen und Aufzeichnungen aus
TUWEL und Altprüfungen aus der MB Cloud an einem Ort. Daraus plant er Arbeitszeit und Lernblöcke rund um deine
Prüfungen. Alles läuft auf deinem eigenen Rechner; deine Daten verlassen ihn nicht.

> Inoffizielles Projekt – nicht von der TU Wien oder der Fachschaft. Die Anbindung an TISS, TUWEL und die MB Cloud nutzt
> deine eigene Anmeldung im Browser und kann brechen, wenn sich diese Seiten ändern.

## Funktionen

- **Kalender** mit allen TISS-Terminen (iCal-Feed), Feiertagen und vorlesungsfreien Zeiten, eigenen Terminen zu einer
  LVA und persönlichen Terminen. Filter und Export als iCal, CSV oder PDF.
- **Prüfungen:** Termine samt Anmeldefristen aus den TISS-Prüfungslisten und dem TUWEL-Kalender. Je LVA wählst du den
  angemeldeten Termin; der Anmeldebeginn erscheint im Kalender. Ein Zeitstrahl passt seinen Maßstab an die Abstände an.
- **Wochenplanung:** verteilt deine Arbeitsstunden auf die freien Zeiten der Woche und legt Lernblöcke in die Wochen
  vor deinen Prüfungen. Die Lernzeit kommt aus den ECTS; wie viele Wochen vorher du lernst, stellst du je LVA ein.
- **TUWEL-Sync** über eine Browser-Erweiterung (Edge, Chrome, Firefox): lädt Unterlagen und LectureTube-Aufzeichnungen
  je LVA und erkennt neue und geänderte Dateien.
- **Wochenbericht:** was in TUWEL in der Woche dazugekommen ist, je LVA mit geschätztem Stoff.
- **Wissensstand:** je Kurs ein Zeitstrahl bis zu den Prüfungen mit Fortschritt und Themen. Lädst du den Prüfungsstoff
  hoch (Stoffliste, Skript oder Folien), entstehen daraus die Themen dieser Prüfung.
- **STEOP:** liest deinen STEOP-Status aus TISS und wählt eine Kursvariante.
- **Optional mit KI:** Volltext- und semantische Suche in deinen Unterlagen, Transkripte von Aufzeichnungen und ein
  MCP-Server für Claude Desktop. Die Modelle laufen lokal.

## Installation (Windows)

Setup-Datei `StudienHub-Setup-<Version>.exe` ausführen – ohne Adminrechte. Ein Assistent führt durch TISS-Link,
Browser-Erweiterung und MB Cloud. Alle Schritte stehen in der [Anleitung](ANLEITUNG.md).

Die Setup-Datei baust du selbst aus dem Quellcode (siehe unten).

## Entwicklung

Voraussetzungen: Python 3.12, Node.js, für die Setup-Datei zusätzlich Inno Setup 6.

```powershell
# Backend einrichten
cd backend; py -3.12 -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt

# Backend und Oberfläche im Entwicklungsmodus starten (http://localhost:5173)
cd ..\frontend; npm install; npm run dev

# Tests
cd ..\backend; .\.venv\Scripts\python -m pytest
cd ..\browser-erweiterung; npm test
cd ..\frontend; npm test

# Setup-Datei bauen (dist\StudienHub-Setup-<Version>.exe)
cd ..; .\build.ps1
```

| Teil | Technik |
| --- | --- |
| Backend | Python, FastAPI, SQLAlchemy, SQLite (mit sqlite-vec und FTS5) |
| Oberfläche | React, Vite, FullCalendar |
| Browser-Erweiterung | Manifest V3, ohne Abhängigkeiten |
| Paket | PyInstaller, Inno Setup |

Aufbau und fachliche Regeln stehen in [KONZEPT.md](KONZEPT.md) und [CLAUDE.md](CLAUDE.md).

## Datenschutz

- Der Hub ist nur auf `127.0.0.1` erreichbar.
- Zugangsdaten liegen in der Windows-Anmeldeinformationsverwaltung, nicht in Dateien.
- Abgerufen werden nur deine eigenen Daten aus TISS, TUWEL und der MB Cloud.
- Die KI-Funktionen sind ausgeschaltet, bis du sie einschaltest.

## Lizenz

[MIT](LICENSE)
