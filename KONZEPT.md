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
| MB Cloud | Inoffizielle Unterlagen der Fachschaft (Altprüfungen, Lösungen, Ausarbeitungen): Index, Zuordnung, gezielte Downloads, Altprüfungen in der Lernphase | 2 |
| Inhaltsverarbeitung | Text aus PDFs, Folien und Word mit Seitenzahlen, Gliederung in Kapitel, Transkription von Videos mit Zeitmarken, Abschnitte mit Embeddings, semantische Suche | 3 |
| Wochenübersicht | Jeden Freitag: Termine der Woche, Abgaben und Prüfungen, Zusammenfassung des neuen Stoffs, Lernplan in den freien Zeitfenstern | 4 |
| KI-Assistent | Claude Desktop (eigenes Abo) über einen lokalen MCP-Server: Fragen zu allen Unterlagen mit Fundstelle, Termine, Lernplan, Quiz mit Protokoll, Lernblock-Vorschläge | 4 |
| Wissensstand | Themen je LVA aus der Kapitelstruktur, Stufe 0–4 je Thema, verteilte Wiederholung, Protokoll aller Lernereignisse | 4 |

Die Markierungen pro LVA (STEOP, Anwesenheitspflicht, Aufzeichnung) werden einmal pro Semester gesetzt und gelten für alle Termine dieser LVA. Einzelne Termine können abweichen, etwa eine Übung mit Anwesenheitspflicht innerhalb einer sonst freien LVA.

## Architektur

Der Hub läuft als lokales Programm auf deinem Laptop. Eine zentrale Datenbank hält Termine, Unterlagen und Zusammenfassungen; Oberfläche und KI greifen beide darauf zu.

&#91;embedded content: Architektur · 3 Quellen, 3 Kernbausteine, 3 Zugänge\]

Der Sync holt neue Daten, die Verarbeitung macht sie durchsuchbar, und die KI fragt über den MCP-Server nur die passenden Abschnitte ab.

Vorgeschlagener Tech-Stack:

| Baustein | Technik | Grund |
| --- | --- | --- |
| Backend | Python mit FastAPI | Beste Bibliotheken für PDF, Whisper und KI |
| Datenbank | SQLite mit sqlite-vec und FTS5 | Eine Datei, keine Installation, Vektor- und Volltextsuche eingebaut |
| Embeddings | fastembed (ONNX) mit paraphrase-multilingual-MiniLM-L12-v2 | Lokal, ohne PyTorch, versteht Deutsch, 384 Dimensionen |
| Oberfläche | React mit FullCalendar | Fertige Kalenderansichten mit Drag-and-Drop |
| Transkription | faster-whisper, lokal | Kostenlos, Videos verlassen den Laptop nicht |
| PDF und Folien | PyMuPDF | Schnelle Textextraktion mit Seitenzahlen |
| KI-Anbindung | MCP-Python-SDK | Offizieller Weg, Claude Desktop anzubinden |
| Zeitsteuerung | APScheduler | Täglicher Sync, wöchentliche Übersicht |

## Datenmodell

Alles hängt an der LVA. Termine, Unterlagen und Zusammenfassungen sind immer einer LVA zugeordnet. Arbeitsblöcke sind davon unabhängig.

| Objekt | Wichtigste Felder | Herkunft |
| --- | --- | --- |
| LVA | Titel, Semester, Farbe, ECTS, eigenes Prüfungsdatum, Ziel (bestehen/normal/gute Note), Regler für den Wochenbedarf | TISS + eigene Angaben |
| LVA-Teil | LVA, Nummer, Typ (VO/UE), Gruppe, STEOP, Anwesenheitspflicht, Aufzeichnung, TUWEL-Kurs-ID | TISS + eigene Angaben |
| Termin | LVA, Teil, Typ (VO/UE/Prüfung/Abgabe), Start, Ende, Ort, Abweichungen von den Markierungen des Teils | TISS-iCal |
| Freier Zeitraum | Bezeichnung, von, bis (Ferien, Feiertage, Rektorstag) | TISS-iCal |
| Arbeitsblock | Start, Ende, fix oder flexibel, Arbeitgeber, Notiz | eigene Eingabe / Verteilungs-Algorithmus |
| Arbeitsregel | Stunden pro Woche (Pflicht), mögliche Tage, frühester Beginn, spätestes Ende, Mindest- und Maximallänge pro Block, Puffer für den Weg, Tagesgrenze, Lerntage, ECTS-Faktor, Lernphase in Wochen | eigene Eingabe |
| Dokument | LVA, Dateiname, Typ (PDF, Folien, Video), Abschnitt, Prüfsumme, Datum, Quelle (TUWEL oder MB Cloud), Kategorie, Jahr; bei Altprüfungen erledigt, Zeitbedarf, Punkte | TUWEL-Sync, MB Cloud |
| MB-Cloud-Ordner | Pfad, Name, ETag, zugeordnete LVA, Art der Zuordnung (sicher, Vorschlag, bestätigt, abgelehnt) | MB Cloud |
| MB-Cloud-Datei | Pfad, Name, Größe, Datum, ETag, Kategorie, Prüfungsdatum/Jahr, Gedankenprotokoll, Lösung zu, heruntergeladen als, Duplikat | MB Cloud (nur Index) |
| Abschnitt | Dokument, LVA, Quelle (TUWEL, LectureTube, MB Cloud), offiziell oder inoffiziell, Jahr, Kapitel, Seite oder Zeitmarke, Text, Embedding | Verarbeitung |
| Thema | LVA, Titel, Reihenfolge, Herkunft (Kapitel oder eigenes), verknüpfte Abschnitte | Verarbeitung + eigene Angaben |
| Wissensstand | Thema, Stufe 0–4, letzte Übung, nächste Wiederholung | Lernereignisse |
| Lernereignis | LVA, Thema, Art (Quiz, Altprüfung, Selbsteinschätzung, Lernblock), Zeitpunkt, Ergebnis, Stufe vorher/nachher, Quelle (Hub oder Claude) | Hub, KI |
| Notiz | LVA, Thema, Text, Quelle | Hub, KI |
| Zusammenfassung | LVA, Kapitel oder Woche, Text, verknüpfte Abschnitte | KI |
| Lernblock | LVA, Thema, Start, Ende, Vorschlag oder fixiert, behandelter Stoff je Unterlage, erledigt, tatsächlich gelernte Minuten | Lernplan |

Die Prüfsumme pro Dokument verhindert doppelte Downloads und erkennt geänderte Dateien. Embeddings sind Zahlenvektoren, mit denen die KI inhaltlich passende Abschnitte findet, auch wenn andere Begriffe verwendet werden.

## Wochenplanung: Pflicht, Arbeit, Lernen, Freizeit

Ziel der Planung ist das Minimum, das das Studium machbar hält, nicht das Maximum. Jede Woche wird in dieser Reihenfolge gefüllt:

1. **Pflichttermine und Prüfungen** sind gesetzt (mit Puffer für den Weg). Feiertage und vorlesungsfreie Zeiten aus TISS sperren Arbeit und Lernen.
2. **Arbeit:** Die Wochenstunden sind Pflicht und werden zuerst verteilt (Ablauf im nächsten Abschnitt).
3. **Lernen** bis zum Wochenbedarf jeder LVA, in die Lücken, die Termine und Arbeit lassen.
4. **Der Rest ist Freizeit.**

### Welche LVAs dieses Semester besucht werden

Grundlage ist der STEOP-Status aus TISS (Seite „STEOP Status“). Die Browser-Erweiterung liest ihn mit deiner TISS-Anmeldung, sobald du die Seite einmal öffnest, und danach bei jedem Lauf; von Hand lässt er sich im Reiter „LVAs“ überschreiben, bis TISS den nächsten Stand liefert. Eine LVA ist STEOP-LVA, wenn sie oder einer ihrer Teile als STEOP markiert ist oder TISS ihre Nummer in den offenen STEOP-Kriterien nennt. Die STEOP-LVAs müssen nicht alle im ersten Semester gemacht werden: Die „Detailansicht offener STEOPs“ nennt die Kriterien als Baum, z. B. „P4: 9 ECTS aus:“ mit „1 aus:“, „1 aus:“ und „Alle aus:“ darunter; die P-Kriterien sind mit AND (oder OR) verbunden. Weil sich die Kriterien auf mehrere Arten erfüllen lassen, gilt solange die STEOP offen ist immer genau eine **Variante**: Der Hub wählt die LVAs dieses Semesters, die möglichst viele P-Kriterien erfüllen und dafür möglichst wenig ECTS brauchen; LVAs unter „Alle aus“ sind immer dabei, in TISS schon erledigte zählen mit. Ist ein Kriterium mit den LVAs dieses Semesters nicht erfüllbar (z. B. LVA nur im Sommer), meldet der Hub das. Ohne Kriterien aus TISS gehören alle STEOP-LVAs zur Variante. Dazu kommen Nicht-STEOP-LVAs bis zu den erlaubten Non-STEOP-ECTS (aus TISS, von Hand überschreibbar), die das Budget möglichst voll ausschöpfen; LVAs ohne ECTS-Angabe bleiben draußen. Du bearbeitest die Variante, indem du LVAs an- oder abhakst (in der LVA-Tabelle oder direkt im Kriterienbaum); ab dann bleibt sie so, bis du „Neue Variante erzeugen“ wählst oder die erlaubten ECTS änderst. Erfüllt die bearbeitete Variante ein mögliches Kriterium nicht mehr oder überschreitet sie das ECTS-Budget, erscheint eine Warnung. Nach Abschluss der STEOP werden alle LVAs besucht. Nicht gewählte LVAs sind ausgeblendet: Sie stehen ausgegraut im Semesterplan (Reiter „LVAs“) und im Kalender, fehlen im Export, ihre Termine sperren keine Arbeitszeit, und sie bekommen keine Lernzeit. Nach Abschluss lässt sich jede LVA manuell ausblenden oder wieder einblenden; „automatisch“ heißt dann besucht. Nach einer Änderung werden die Wochen, die schon Vorschläge haben, neu geplant.

Alle Arbeitszeit-Vorschläge aller Wochen lassen sich auf einmal löschen; bestätigte und fixe Blöcke bleiben.

### Lernbedarf aus den ECTS

Die Lernzeit einer LVA kommt aus den ECTS, nicht aus den Seiten der Unterlagen:

> Lernbedarf im Semester = (ECTS × 25 h − Präsenzstunden) × ECTS-Faktor × Ziel × Regler

| Größe | Bedeutung | Standard |
| --- | --- | --- |
| Präsenzstunden | Summe aller Termine der LVA ohne Prüfungen und Abgaben | aus TISS |
| ECTS-Faktor | ECTS-Werte sind meist zu hoch angesetzt; gilt für alle LVAs (Reiter „Arbeitszeiten“) | 0,7 |
| Ziel | je LVA: „bestehen“ 0,6, „normal“ 0,8, „gute Note“ 1,0 | normal |
| Regler | je LVA, 0–200 % (Reiter „LVAs“) | 100 % |

Der Bedarf verteilt sich über die Wochen vom ersten Termin bis zur (letzten) Prüfung. Die Wochen der **Lernphase** vor jeder Prüfung (Standard 2, einstellbar) zählen dreifach, Wochen mit gesperrten Lerntagen anteilig weniger. Ohne Prüfung endet die Verteilung mit dem letzten Termin, ohne Lernphase. Ohne ECTS bekommt eine LVA keine Lernzeit, die Wochenplanung weist darauf hin.

**Nachholen:** Was in früheren Wochen nicht gelernt wurde, verteilt sich auf die verbleibenden Wochen bis zur Prüfung; ein Vorsprung senkt den Bedarf. Als gelernt zählt die nach einem Block eingetragene tatsächliche Zeit, sonst die geplante. Gezählt wird ab der ersten Woche mit Lernblöcken für die LVA – Wochen vor der Nutzung des Hubs erzeugen keinen Rückstand.

**Unterlagen bestimmen nur den Stoff:** Welche Unterlagen ein Lernblock behandelt, ergibt sich aus dem offenen Stoff (älteste zuerst). Jede Unterlage wird dafür gewichtet (Folien und Skripte nach Seiten, Videos nach Dauer, Übungsblätter fest), damit ein langes Skript mehr Blöcke bekommt als ein kurzer Foliensatz; die Lernzeit ändert das nicht. Bereits vorhandener Stoff – etwa beim ersten Sync mitten im Semester – wird über die Wochen bis zur Lernphase verteilt, nicht in eine Woche gepackt. In der Lernphase ist der ganze offene Stoff dran, danach heißt der Block „Prüfungsvorbereitung“.

### Prüfungen

Prüfungstermine kommen aus dem TISS-Feed. Fehlt dort einer, trägst du das Datum pro LVA im Reiter „LVAs“ ein; ein TISS-Termin hat Vorrang. Prüfungen sind im Kalender deutlich hervorgehoben (🎓, roter Rahmen), selbst eingetragene erscheinen als ganztägiger Eintrag. Die Wochenübersicht zeigt die nächsten Prüfungen als Countdown. In der Prüfungswoche liegen Lernblöcke der LVA nur vor der Prüfung.

### Lernblöcke verteilen

Pro Lernblock wird jede freie Lücke bewertet: gleichmäßige Tageslast, höchstens ein Block derselben LVA pro Tag, möglichst vor der nächsten Übung oder Abgabe. Harte Regeln: erlaubte Lerntage und Uhrzeiten, Tagesgrenze Uni + Arbeit + Lernen, Mindest- und Maximallänge eines Blocks.

**Konflikte:** Reicht die Zeit nicht, bekommen zuerst die LVAs in der Lernphase ihre Blöcke, die übrigen reihum. Gekürzt wird also zuerst die Lernzeit von LVAs ohne nahe Prüfung – nie die Arbeit. Die Wochenplanung zeigt je LVA, wie viel sie diese Woche hinter den Plan fällt, den gesamten Rückstand und wie viel sie bis zur Prüfung pro Woche nachholen müsste.

### Bearbeiten und Wochenübersicht

Du kannst Blöcke verschieben, löschen und fixieren. Verschobene und fixierte Blöcke bleiben, wie sie sind; ein gelöschter Vorschlag wird in dieser Woche nicht wieder an dieselbe Stelle gelegt. Danach plant der Hub nur den Rest der Woche neu (nur wenn die Woche schon Vorschläge hat). „Vorschläge verwerfen“ setzt die Woche zurück.

Pro Woche zeigt ein Balken die Stunden für Uni, Arbeit, Lernen und Freizeit (wache Zeit: 16 h pro Tag), darunter der Countdown der nächsten Prüfungen und der Lernstand je LVA (Soll, geplant, Rückstand).

## Flexible Arbeitszeiten verteilen

Flexible Stunden werden jede Woche automatisch in die freien Lücken gelegt, Pflichttermine haben dabei Vorrang. Die Wochenstunden sind Pflicht: Reichen sie nicht, werden zuerst weiche Regeln gelockert (Lernfenster nach Vorlesungen, nicht aufgezeichnete Vorlesungen, zuletzt der Lernschutz vor Prüfungen und Abgaben). Der Ablauf:

1. **Sperrzeiten sammeln:** alle Termine mit Anwesenheitspflicht, Prüfungen und fixe Arbeitsblöcke, jeweils mit Puffer für den Weg.
2. **Weiche Termine gewichten:** Vorlesungen ohne Anwesenheitspflicht, die aufgezeichnet werden, dürfen überplant werden. Ohne Aufzeichnung nur, wenn sonst die Stunden nicht reichen.
3. **Lücken finden:** pro erlaubtem Arbeitstag die freien Zeitfenster innerhalb von frühestem Beginn und spätestem Ende.
4. **Lücken bewerten:** lange Blöcke vor kurzen, wenige Wechsel zwischen Uni und Arbeit pro Tag, bevorzugte Tage zuerst, kein Leerlauf zwischen zwei Arbeitsblöcken (zwei Blöcke eines Tages liegen am Stück, nur mit Pause).
5. **Stunden verteilen:** die besten Lücken füllen, bis die Wochenstunden erreicht sind; Mindest- und Maximallänge pro Block einhalten.
6. **Vorschlag zeigen:** Die Verteilung erscheint als Vorschlag im Kalender. Du bestätigst oder verschiebst Blöcke per Drag-and-Drop, danach gelten sie als fix.

Wenn die Stunden auch so nicht unterzubringen sind, zeigt der Hub die fehlenden Stunden und welche weichen Termine dafür geopfert werden müssten. Ändert sich ein TISS-Termin, wird nur die betroffene Woche neu vorgeschlagen; bestätigte Blöcke bleiben unverändert.

## MB Cloud der Fachschaft (inoffizielle Quelle)

Die MB Cloud der Fachschaft Maschinenbau (https://mbcloud.at) ist eine Nextcloud mit Unterlagen von Studierenden. Aufbau: Team-Ordner `MB_VT_WIMB`, darin ein Ordner pro LVA („Mechanik 1 VO 309.019“), darin Unterordner wie „Prüfungsunterlagen“, „Theoriefragen“, „Zusammenfassungen“. Neuere Dateien heißen z. B. `2025-10-09-Gedankenprotokoll-<Titel>-<Nummer>.pdf`. Hochladen geht nur über die Upload-Funktion; Regeln zum Lesen gibt es keine. Der Hub liest nur, lädt schonend und behält die Dateien lokal.

- **Zugang:** Anmeldung über den Nextcloud-Login-Flow: Der Hub öffnet die MB Cloud im Browser, man meldet sich mit dem TU Login an und erlaubt den Zugriff. Der Hub bekommt ein eigenes App-Passwort (in der MB Cloud widerrufbar) und speichert Adresse, Benutzer und App-Passwort nur in der `.env`.
- **Index statt Download:** Täglich (nach dem TISS-Import) liest der Hub per WebDAV nur das Verzeichnis – Pfad, Name, Größe, Datum, ETag. Zuerst die Liste der LVA-Ordner (eine Anfrage), dann nur zugeordnete Ordner und darin nur Unterordner, deren ETag sich geändert hat. Eine Anfrage nach der anderen mit Pause dazwischen.
- **Zuordnung:** Sicher über die LVA-Nummer im Ordnernamen (VO und UE haben eigene Ordner, landen aber bei derselben LVA). Ohne Nummer vergleicht der Hub den Titel unscharf (verschiedene Zahlen wie „Mechanik 1/2“ schließen aus); ähnliche Titel erscheinen im Reiter „MB Cloud“ zur Bestätigung. Bestätigen, Umhängen und Ablehnen gelten für alle künftigen Dateien im Ordner.
- **Einteilung:** Aus Datei- und Ordnername: Altprüfung (auch Theoriefragen; Gedankenprotokolle sind als nicht original gekennzeichnet), Lösung, Ausarbeitung, Mitschrift, Formelsammlung, Sonstiges. Prüfungsdatum oder Jahr aus dem Namen (2025-10-09, 09.10.2025, WS2024, SS 23, Juni 2019, 2021), sonst geschätzt aus dem Änderungsdatum. Lösungen werden mit der Altprüfung desselben Datums bzw. desselben Namens verknüpft.
- **Downloads:** Automatisch nur Altprüfungen, Lösungen und Formelsammlungen der letzten 5 Jahre für besuchte LVAs, alles andere per Klick. Ablage unter `<Semester>/<LVA>/MB Cloud/<Kategorie>/`. Gleicher Inhalt (SHA-256) wie eine vorhandene Unterlage, auch aus TUWEL, wird nicht doppelt abgelegt.
- **Kennzeichnung:** Jede Unterlage trägt Quelle, Kategorie und Jahr, ist in der Unterlagenliste gestrichelt orange markiert („MB Cloud · Altprüfung · 2025“) und nach Quelle filterbar.
- **Planung:** Der Lernbedarf bleibt unverändert; MB-Cloud-Dateien zählen nicht zum Stoff. In der Lernphase vor einer Prüfung bekommt jeder Lernblock der LVA eine konkrete Altprüfung, neueste zuerst, eine pro Block. Eine Altprüfung lässt sich als erledigt markieren (Zeitbedarf, erreichte Punkte) – im Reiter „MB Cloud“ oder im Lernblock; erledigte plant der Hub nicht mehr ein.
- **Für Stufe 4:** Quelle, Kategorie und Jahr stehen am Dokument, damit die KI offizielle Unterlagen bevorzugen und MB-Cloud-Inhalte als inoffiziell (mit Jahr) zitieren kann.

## Inhaltsverarbeitung und KI (Stufe 3 und 4)

### Unterlagen aufbereiten (Stufe 3)

Eingeschaltet wird die Verarbeitung auf der Seite „KI verbinden“; beim ersten Mal lädt der Hub das Sprachmodell (≈ 220 MB, für Transkripte zusätzlich ≈ 460 MB) nach `daten/modelle`, danach läuft alles offline im Hintergrund.

- **Text:** PDFs (PyMuPDF) Seite für Seite, PowerPoint/Impress je Folie, Word nach Absätzen. Die Gliederung kommt aus dem Inhaltsverzeichnis der PDF, sonst aus nummerierten Überschriften, die größer oder fett gesetzt sind als der Fließtext (Aufzählungen wie „3. Schritt“ zählen nicht).
- **Abschnitte:** höchstens 1500 Zeichen, nie über eine Kapitelgrenze; kurze Folien werden zusammengelegt. Jeder Abschnitt trägt LVA, Quelle (TUWEL, LectureTube, MB Cloud), offiziell/inoffiziell, Jahr, Kapitel (oberste Ebene und voller Pfad) und Seite(n) bzw. Zeitmarken.
- **Embeddings:** lokales Modell `paraphrase-multilingual-MiniLM-L12-v2` (fastembed, ONNX), gespeichert in sqlite-vec; dazu ein Volltextindex (FTS5).
- **Suche:** Vektor- und Volltexttreffer werden zusammengeführt (Reciprocal Rank Fusion); offizielle Unterlagen bekommen einen kleinen Vorsprung. Ohne Modell bleibt der Volltext.
- **Transkripte:** faster-whisper (CPU, int8) arbeitet die Aufzeichnungen nach und nach ab, ein Video je Lauf. Die Audiodaten kommen von der direkten Videoadresse, die der TUWEL-Sync speichert; abgelaufene Adressen werden gemeldet und nach dem nächsten Sync erneut versucht. Abschnitte von etwa 90 Sekunden mit Zeitmarke.
- Neue oder geänderte Unterlagen (Prüfsumme) werden alle 15 Minuten verarbeitet; Fehler stehen am Dokument und auf „KI verbinden“.

### Themen und Wissensstand (Stufe 4)

- **Themen** je LVA aus der obersten Gliederungsebene des Skripts mit der reichsten Gliederung; ohne gegliedertes Skript dienen die Foliensätze als Themen. Im Reiter „Wissensstand“ lassen sich Themen anlegen, umbenennen, verschieben und löschen; eigene Themen und der Wissensstand bleiben beim erneuten Ableiten erhalten. Jedes Thema ist mit seinen Abschnitten verknüpft (gleiches Kapitel und Suche nach dem Titel).
- **Stufen:** 0 neu · 1 gesehen · 2 mit Hilfe lösbar · 3 sicher · 4 prüfungsfest. Ein Ergebnis ab 80 % hebt die Stufe, 50–80 % hält sie (mindestens 1), darunter senkt es sie; Selbsteinschätzung setzt sie direkt.
- **Wiederholung:** nächste Wiederholung nach 1, 2, 4, 9 oder 21 Tagen je Stufe, spätestens am Tag vor der Prüfung.
- **Protokoll:** jedes Lernereignis (Quiz, Altprüfung, Selbsteinschätzung, Lernblock) mit Datum, Ergebnis, Stufe vorher und nachher und Quelle (Hub oder Claude).
- **Reiter „Wissensstand“:** je LVA die Themen als farbige Kacheln (Farbe = Stufe), Verteilung der Stufen, Tage bis zur Prüfung, fällige Wiederholungen oben, Notizen von Claude.

### MCP-Server für Claude Desktop (Stufe 4)

Claude Desktop startet den Server selbst (`python -m app.mcp_server`, offizielles MCP-Python-SDK, stdio). Er liest nur aus der Datenbank, schreibt keine Dateien und greift nicht ins Netz (Modell nur aus `daten/modelle`).

| Werkzeug | Zweck |
| --- | --- |
| suche_unterlagen (Frage, LVA optional) | Abschnitte mit Quelle, offiziell/inoffiziell, Jahr, Kapitel, Fundstelle |
| lies_abschnitt | vollständiger Abschnitt samt Nachbarn |
| liste_lvas, termine (Zeitraum), wochenplan, pruefungen | Stammdaten, Termine, Wochenplan mit Stunden, Prüfungen |
| wissensstand (LVA optional), faellige_wiederholungen | Themen, Stufen, Wiederholungen, Tage bis zur Prüfung |
| altpruefungen (LVA) | Altprüfungen aus der MB Cloud mit Lösung und Bearbeitungsstand |
| lernereignis_eintragen (Thema, Art, Ergebnis), wissensstand_setzen | Ergebnisse protokollieren, Stufe setzen |
| notiz_speichern | Notiz zu LVA oder Thema |
| lernblock_vorschlagen | legt nur einen Vorschlag an; bleibt beim Neuplanen stehen, bis du ihn im Kalender bestätigst oder löschst |
| wochenplan_vorschlagen (Woche, Grund) | lässt den Hub die Woche nach seinen Regeln neu vorschlagen |
| rueckblick (Woche), neue_unterlagen (Tage) | erledigte/offene Lernblöcke, Ergebnisse, Arbeitsstunden; neuer Stoff |
| lies_dokument, aufzeichnung_zu_termin | ganze Unterlage (z. B. Altprüfung und Lösung); Aufzeichnung samt Transkript zu einem Termin |
| altpruefung_bearbeitet | Altprüfung mit Zeit und Punkten als erledigt markieren |

**Server-Anweisungen (gelten immer):** aus den Unterlagen antworten und immer die Quelle nennen (Datei und Seite bzw. Video und Zeitmarke); offizielle Unterlagen vor inoffiziellen, MB-Cloud-Inhalte als „inoffiziell, MB Cloud, Jahr“; sagen, wenn etwas nicht in den Unterlagen steht; zu Beginn den Wissensstand abfragen und die Erklärung anpassen; nach jeder Übung ein Lernereignis eintragen; bei benoteten Abgaben nur Hinweise, keine fertigen Lösungen; Lernblöcke nur vorschlagen.

**Prompt-Vorlagen** – nicht jede Version von Claude Desktop zeigt MCP-Vorlagen im Menü an. Deshalb gibt es drei Wege: im Chat in eigenen Worten nennen („Starte thema_lernen für Mechanik 1, Thema Reibung“), dann holt Claude den Ablauf über das Werkzeug `vorlage`; im Menü „+“ → „Slash-Befehle“ bzw. „/“, falls die Version sie anzeigt; oder auf „KI verbinden“ den fertigen Text erzeugen und kopieren.

| Vorlage | Felder | Ablauf |
| --- | --- | --- |
| thema_lernen | LVA, Thema | Wissensstand abfragen, Erklärung in kleinen Schritten mit Verständnisfragen, 3 Kontrollfragen, Lernereignis |
| wochenstart | – | Rückblick, neuer Stoff, Prüfungen, fällige Wiederholungen → 3 Prioritäten, Lernblock-Vorschläge |
| wiederholung | LVA (optional) | Quiz zu allen fälligen Themen, je Thema ein Lernereignis (passt die Abstände an) |
| pruefung_simulieren | LVA, Minuten (Standard 90) | neueste nicht gerechnete Altprüfung mit Zeitlimit, Bewertung anhand der Lösung, Fehleranalyse pro Thema, Altprüfung und Lernereignisse eintragen |
| vorlesung_nachholen | Termin („Mechanik 14.10.“ oder ID) | Zusammenfassung der Aufzeichnung mit Zeitmarken, verknüpft mit dem Skript, 3 Kontrollfragen |
| plan_anpassen | Grund, Woche (optional) | Woche nach den Planungsregeln neu vorschlagen, Änderungen zusammenfassen |

### Automatische Wochenübersicht

Jeden Sonntag um 19 Uhr (einschaltbar im Reiter „Wochenbericht“) startet der Hub Claude Code im Kopflos-Modus: `claude -p` mit dem eigenen Abo, derselben MCP-Konfiguration wie Claude Desktop und der Vorlage „wochenstart“ für die kommende Woche. Geprüft am 11.10.2026: Anmeldung über claude.ai (Abo), der Lauf nutzt die Hub-Werkzeuge und legt Vorschläge an (≈ 2 Minuten, 14 Schritte). Ein API-Key ist daher nicht nötig.

- Erlaubt sind nur die lesenden Hub-Werkzeuge und `lernblock_vorschlagen`; von den eingebauten Werkzeugen bleibt nur ToolSearch (lädt die MCP-Werkzeuge nach) – keine Dateien, keine Befehle, kein Web.
- Der Bericht (Markdown: Rückblick, neuer Stoff, Prüfungen und Wiederholungen, Prioritäten, vorgeschlagene Lernblöcke) erscheint als Seite im Reiter „Wochenbericht“, die Lernblöcke als „Vorschlag von Claude“ im Kalender.
- Je Lauf zeigt der Hub Dauer, Schritte und die Kosten laut Claude Code; mit Abo-Anmeldung ist das ein Rechenwert ohne Verrechnung, der Lauf zählt aber zum Kontingent.
- War der Rechner am Sonntagabend aus, wird der Lauf beim nächsten Start (Sonntag später oder Montag) nachgeholt. Fehler – auch ein Bericht ohne die geforderten Abschnitte – stehen sichtbar beim Bericht.

**Einrichtung:** Die Seite „KI verbinden“ trägt den Server in `claude_desktop_config.json` ein (Windows: `%APPDATA%\Claude`, auch die Store-Version; macOS: `~/Library/Application Support/Claude`), legt vorher eine Sicherung an und lässt andere Einträge unverändert. Danach Claude Desktop ganz beenden (Infobereich → Beenden) und neu starten. `backend/scripts/mcp_test.py` startet den Server wie Claude Desktop und ruft jedes Werkzeug gegen eine Kopie der Datenbank auf.

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
