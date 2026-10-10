# Studien-Hub – Konzept

Oct 10, 2026 · @Meister

## Ziel und Ausgangslage

Der Studien-Hub bündelt Termine, Arbeitszeiten und alle Lernunterlagen an einem Ort und macht sie für eine KI dauerhaft abfragbar. Zielgruppe ist ein TU-Wien-Student mit Nebenjob, der sein Studium neben der Arbeit planen muss.

Bestehende Tools reichen nicht aus:

- **Google Kalender:** Ein abonnierter TISS-Feed hat nur eine Farbe. Einzelne LVAs lassen sich nicht einfärben oder markieren.
- **TUWEL:** Unterlagen müssen manuell heruntergeladen und abgelegt werden.
- **Vorlesungsvideos:** Sie werden nicht inhaltlich erfasst und nicht mit den passenden Skript-Kapiteln verknüpft.
- **KI-Chats:** Unterlagen müssen in jeden Chat neu eingefügt werden, und in langen Chats geht Kontext verloren.

## Funktionsumfang

Der Hub hat sieben Funktionsbereiche. Die Spalte „Stufe“ verweist auf die Roadmap weiter unten.

| Bereich | Funktionen | Stufe |
| --- | --- | --- |
| Kalender | Import aller Termine aus TISS (iCal), eigene Farbe pro LVA, Markierungen STEOP / Anwesenheitspflicht / Aufzeichnung, Wochen- und Monatsansicht | 1 |
| Arbeitszeiten | Arbeitstage pro Woche, fixe Zeiten als Serie, flexible Stunden werden automatisch in freie Lücken verteilt, manuelles Verschieben | 1 |
| Filter und Export | Filter nach LVA, Typ (VO/UE), Markierung, Arbeit; Export als iCal, CSV oder PDF, z. B. nur Arbeitszeiten eines Monats | 1 |
| TUWEL-Sync | Automatischer Download aller Kursunterlagen, Ablage pro LVA, Erkennung neuer und geänderter Dateien | 2 |
| Inhaltsverarbeitung | Text aus PDFs und Folien, Transkription von Videos, Gliederung in Kapitel, Zuordnung Video-Abschnitt ↔ Skript-Kapitel, Zusammenfassung pro Kapitel | 3 |
| Wochenübersicht | Jeden Freitag: Termine der Woche, Abgaben und Prüfungen, Zusammenfassung des neuen Stoffs, Lernplan in den freien Zeitfenstern | 4 |
| KI-Assistent | Fragen zu allen Unterlagen, Termine und Lernplan; Zugriff über MCP mit dem eigenen Abo oder optional per API-Key | 4 |

Die Markierungen pro LVA (STEOP, Anwesenheitspflicht, Aufzeichnung) werden einmal pro Semester gesetzt und gelten für alle Termine dieser LVA. Einzelne Termine können abweichen, etwa eine Übung mit Anwesenheitspflicht innerhalb einer sonst freien LVA.

## Architektur

Der Hub läuft als lokales Programm auf deinem Laptop. Eine zentrale Datenbank hält Termine, Unterlagen und Zusammenfassungen; Oberfläche und KI greifen beide darauf zu.

&#91;embedded content: Architektur · 3 Quellen, 3 Kernbausteine, 3 Zugänge\]

Der Sync holt neue Daten, die Verarbeitung macht sie durchsuchbar, und die KI fragt über den MCP-Server nur die passenden Abschnitte ab.

Vorgeschlagener Tech-Stack:

| Baustein | Technik | Grund |
| --- | --- | --- |
| Backend | Python mit FastAPI | Beste Bibliotheken für PDF, Whisper und KI |
| Datenbank | SQLite mit sqlite-vec | Eine Datei, keine Installation, Vektorsuche eingebaut |
| Oberfläche | React mit FullCalendar | Fertige Kalenderansichten mit Drag-and-Drop |
| Transkription | faster-whisper, lokal | Kostenlos, Videos verlassen den Laptop nicht |
| PDF und Folien | PyMuPDF | Schnelle Textextraktion mit Seitenzahlen |
| KI-Anbindung | MCP-Python-SDK | Offizieller Weg, Claude Desktop anzubinden |
| Zeitsteuerung | APScheduler | Täglicher Sync, wöchentliche Übersicht |

## Datenmodell

Alles hängt an der LVA. Termine, Unterlagen und Zusammenfassungen sind immer einer LVA zugeordnet. Arbeitsblöcke sind davon unabhängig.

| Objekt | Wichtigste Felder | Herkunft |
| --- | --- | --- |
| LVA | Nummer, Titel, Semester, Farbe, STEOP, Anwesenheitspflicht, Aufzeichnung, TUWEL-Kurs-ID | TISS + eigene Angaben |
| Termin | LVA, Typ (VO/UE/Prüfung), Start, Ende, Ort, Abweichungen von den LVA-Markierungen | TISS-iCal |
| Arbeitsblock | Start, Ende, fix oder flexibel, Arbeitgeber, Notiz | eigene Eingabe / Verteilungs-Algorithmus |
| Arbeitsregel | Stunden pro Woche, mögliche Tage, frühester Beginn, spätestes Ende, Mindest- und Maximallänge pro Block, Puffer für den Weg | eigene Eingabe |
| Dokument | LVA, Dateiname, Typ (PDF, Folien, Video), TUWEL-Abschnitt, Prüfsumme, Datum | TUWEL-Sync |
| Abschnitt | Dokument, Kapitel, Text, Seiten oder Zeitmarken, Embedding für die Suche | Verarbeitung |
| Zusammenfassung | LVA, Kapitel oder Woche, Text, verknüpfte Abschnitte | KI |
| Lernblock | LVA, Thema, Start, Ende, erledigt | Lernplan |

Die Prüfsumme pro Dokument verhindert doppelte Downloads und erkennt geänderte Dateien. Embeddings sind Zahlenvektoren, mit denen die KI inhaltlich passende Abschnitte findet, auch wenn andere Begriffe verwendet werden.

## Flexible Arbeitszeiten verteilen

Flexible Stunden werden jede Woche automatisch in die freien Lücken gelegt, Pflichttermine haben dabei Vorrang. Der Ablauf:

1. **Sperrzeiten sammeln:** alle Termine mit Anwesenheitspflicht, Prüfungen und fixe Arbeitsblöcke, jeweils mit Puffer für den Weg.
2. **Weiche Termine gewichten:** Vorlesungen ohne Anwesenheitspflicht, die aufgezeichnet werden, dürfen überplant werden. Ohne Aufzeichnung nur, wenn sonst die Stunden nicht reichen.
3. **Lücken finden:** pro erlaubtem Arbeitstag die freien Zeitfenster innerhalb von frühestem Beginn und spätestem Ende.
4. **Lücken bewerten:** lange Blöcke vor kurzen, wenige Wechsel zwischen Uni und Arbeit pro Tag, bevorzugte Tage zuerst.
5. **Stunden verteilen:** die besten Lücken füllen, bis die Wochenstunden erreicht sind; Mindest- und Maximallänge pro Block einhalten.
6. **Vorschlag zeigen:** Die Verteilung erscheint als Vorschlag im Kalender. Du bestätigst oder verschiebst Blöcke per Drag-and-Drop, danach gelten sie als fix.

Wenn die Stunden nicht unterzubringen sind, zeigt der Hub die fehlenden Stunden und welche weichen Termine dafür geopfert werden müssten. Ändert sich ein TISS-Termin, wird nur die betroffene Woche neu vorgeschlagen; bestätigte Blöcke bleiben unverändert.

## Ausbaustufen

Der Hub entsteht in vier Stufen, und jede ist für sich nutzbar. Stufe 1 löst das Kalenderproblem sofort, auch wenn der TUWEL-Zugang noch offen ist.

&#91;embedded content: Roadmap · 4 Stufen, 3 Prüfpunkte\]

Die Raute zwischen zwei Stufen ist der Prüfpunkt: Erst wenn er erfüllt ist, lohnt die nächste Stufe. Parallel zu Stufe 1 klärst du den TUWEL-Zugang (siehe offene Fragen).

## Risiken und offene Fragen

Das größte Risiko ist der TUWEL-Zugang. Alle anderen Punkte sind lösbar, sobald der klar ist.

| Thema | Risiko | Ausweichweg |
| --- | --- | --- |
| TUWEL-Zugang | Unklar, ob die TU persönliche Web-Service-Tokens für Moodle erlaubt | Browser-Erweiterung, die beim Besuch von TUWEL mitsammelt |
| TISS-Daten | STEOP und Anwesenheitspflicht stehen nicht im iCal-Feed; Aufzeichnung steht oft nirgends | Einmalige Eingabe pro LVA, eventuell Auslesen der LVA-Seite |
| Aufzeichnungen | Videos sind urheberrechtlich geschützt und nur für Studierende freigegeben | Nur lokal speichern und verarbeiten, nichts weitergeben |
| Datenschutz | Unterlagen und Arbeitszeiten sind persönlich | Alles lokal; an die KI gehen nur die Abschnitte, die zur Frage passen |
| KI-Kosten | Zusammenfassungen vieler Unterlagen per API kosten Geld | Über MCP mit dem Abo arbeiten; Transkription lokal mit Whisper |
| Wartung | TISS oder TUWEL ändern Formate, der Sync bricht | Sync-Fehler sichtbar melden, Importe klein und austauschbar halten |

Offene Fragen:

- [ ] Erlaubt TUWEL das Erstellen eines persönlichen Tokens (Profil → Sicherheitsschlüssel)?
- [ ] Wo liegen die Vorlesungsaufzeichnungen, in TUWEL oder auf einer eigenen Plattform?
- [ ] Welches Abo nutzt du, und ist Claude Code darin enthalten?
- [ ] Soll der Hub nur auf deinem Laptop laufen oder auch vom Handy erreichbar sein?

## Umsetzung mit Claude Code

Die Planung bleibt in diesem Chat und Dokument, das Programmieren läuft in Claude Code. Claude Code arbeitet direkt in einem Ordner auf deinem Rechner. Es kann Code schreiben, ausführen und testen, und dort laufen später auch der Sync und der MCP-Server.

Einrichtung:

1. Claude Code installieren (Anleitung auf docs.claude.com) und mit deinem Abo anmelden.
2. Einen Projektordner `studien-hub` anlegen und mit Git versionieren.
3. Dieses Konzept als `KONZEPT.md` in den Ordner legen, damit Claude Code es jederzeit lesen kann.
4. Eine Datei `CLAUDE.md` anlegen mit Tech-Stack, Ordnerstruktur und Regeln (z. B. „Kommentare auf Deutsch, Tests für jede Funktion“).

Erste Prompts für Stufe 1, jeweils als eigene Sitzung:

1. „Lies KONZEPT.md. Richte das Projekt mit dem beschriebenen Tech-Stack ein und erstelle das Datenmodell für LVA, Termin, Arbeitsblock und Arbeitsregel.“
2. „Baue einen Import für meinen TISS-iCal-Link, der Termine den LVAs zuordnet und bei erneutem Import nur Änderungen übernimmt.“
3. „Baue die Kalenderansicht mit Farbe pro LVA und Symbolen für STEOP, Anwesenheitspflicht und Aufzeichnung.“
4. „Setze den Verteilungs-Algorithmus für flexible Arbeitszeiten aus KONZEPT.md um, mit Tests für volle und leere Wochen.“
5. „Ergänze Filter und Export als iCal und CSV.“

Nach jeder Sitzung testest du selbst im Browser. Fragen zum Konzept oder zu Entscheidungen kannst du weiterhin hier stellen.
