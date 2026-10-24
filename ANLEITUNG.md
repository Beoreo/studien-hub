# Studien-Hub – Installation, Update und Fehlerbehebung

## Installieren

1. `StudienHub-Setup-<Version>.exe` starten. Adminrechte sind nicht nötig.
2. Optionen wählen:
   - **Beim Anmelden an Windows starten** – der Hub läuft dann im Hintergrund (Symbol im Infobereich).
   - **In Claude Desktop eintragen** – KI-Anbindung; die bisherige Konfiguration wird vorher gesichert.
3. Am Ende öffnet sich der Hub im Browser mit dem **Einrichtungsassistenten**:
   - **Bisherige Daten übernehmen** – nur, wenn es einen Entwicklungsordner gibt. Übernimmt Datenbank, Unterlagen,
     Modelle und die Zugangsdaten aus der dortigen `.env`.
   - **TISS-Kalender** – iCal-Link aus TISS einfügen.
   - **TUWEL-Token** – optional.
   - **MB Cloud** – verbinden; die Anmeldung öffnet sich im Browser.
   - **Browser-Erweiterung in Edge laden** – Schritt-für-Schritt-Anleitung mit „Ordner öffnen“. Die Erweiterung holt
     sich den Schlüssel selbst.
   - **KI verbinden** – danach Claude Desktop ganz beenden und neu starten.
   - **Modelle herunterladen** – Suche ca. 240 MB, Transkription ca. 480 MB; danach offline.

   Jeder Schritt lässt sich überspringen und später unter **Status → Einrichtung öffnen** nachholen.

Wo was liegt:

| Was | Ort |
|---|---|
| Programm | `%LOCALAPPDATA%\Programs\StudienHub` |
| Browser-Erweiterung | `%LOCALAPPDATA%\Programs\StudienHub\browser-erweiterung` (ID immer `jdjohgkcmmpkpgflffjffeaojfmiahcj`) |
| Daten (Datenbank, Unterlagen, Modelle) | `%LOCALAPPDATA%\StudienHub` |
| Sicherungen (täglich, 14 bleiben) | `%LOCALAPPDATA%\StudienHub\sicherungen` |
| Logs | `%LOCALAPPDATA%\StudienHub\logs` |
| Zugangsdaten | Windows-Anmeldeinformationsverwaltung → Windows-Anmeldeinformationen → Einträge mit „StudienHub“ |

Der Hub ist nur auf diesem Rechner unter `http://127.0.0.1:8000` erreichbar.

## Im Alltag

- **Symbol im Infobereich:** Doppelklick öffnet den Hub. Das Menü hat „Jetzt synchronisieren“, „Status“ und „Beenden“.
  Ein **rotes Symbol** heißt: Bei einem Sync oder Lauf ist ein Fehler aufgetreten – Details unter „Status“.
- **Jetzt synchronisieren:** TISS und MB Cloud laufen sofort. TUWEL holt die Browser-Erweiterung in den nächsten
  2 Minuten, sofern der Browser offen ist.
- **War der Laptop zur geplanten Zeit aus** (TISS 6:00, MB Cloud 6:30, Sicherung 12:00), wird der Lauf beim nächsten
  Start nachgeholt.
- **Sicherung zurückspielen:** Status → Sicherungen → „Wiederherstellen“. Der aktuelle Stand wird vorher selbst
  gesichert.
- **Autostart** ein- oder ausschalten: Status → System.

## Update

Neue `StudienHub-Setup-<Version>.exe` einfach über die alte installieren. Ein laufender Hub wird dabei beendet; Daten,
Einstellungen und Zugangsdaten bleiben erhalten. Edge lädt die aktualisierte Erweiterung beim nächsten Browserstart
(oder sofort über `edge://extensions` → „Neu laden“).

### Update auf 1.1.0

1. Läuft der Entwicklungsmodus (`npm run dev`), ihn zuerst beenden.
2. `StudienHub-Setup-1.1.0.exe` über die alte Version installieren.
3. In `edge://extensions` die Studien-Hub-Erweiterung **neu laden**. Sie braucht jetzt zusätzlich die Berechtigung
   „Cookies“ (für die Prüfungslisten aus TISS). War zum Testen eine Erweiterung aus dem Quellordner geladen, diese
   entfernen und die aus `%LOCALAPPDATA%\Programs\StudienHub\browser-erweiterung` laden.
4. Beim ersten Start trennt der Hub VO und UE derselben Lehrveranstaltung in eigene LVAs (vorher entsteht automatisch
   eine Sicherungskopie der Datenbank). Danach einmal:
   - Reiter **LVAs**: ECTS der neuen UE-LVAs eintragen – ohne ECTS gibt es für sie keine Lernzeit.
   - Im Popup der Erweiterung **„Jetzt synchronisieren“** – holt die Prüfungstermine aus TISS und TUWEL.
   - Reiter **Prüfungen**: je LVA den angemeldeten Termin wählen und „Lernen ab … Wochen“ einstellen. Lernblöcke gibt
     es nur noch in diesen Wochen vor einer Prüfung.

Neu in 1.1.0: Reiter „Prüfungen“ (Termine aus TISS/TUWEL, Anmeldestart im Kalender, Zeitstrahl), eigene und
persönliche Termine im Kalender (Zeitraum aufziehen), Wochenbericht aus den TUWEL-Daten statt über Claude,
Zeitstrahl je Kurs im Wissensstand mit Upload des Prüfungsstoffs.

## Deinstallieren

Windows-Einstellungen → Apps → „Studien-Hub“ → Deinstallieren. Die Frage „Sollen auch deine Daten gelöscht werden?“
mit **Nein** beantworten, um Datenbank, Unterlagen und Zugangsdaten zu behalten – eine spätere Installation macht dort
weiter. Autostart und der Eintrag in Claude Desktop werden in beiden Fällen entfernt.

## Fehlerbehebung

| Problem | Lösung |
|---|---|
| „Der Studien-Hub konnte nicht starten. Ist Port 8000 belegt?“ | Meist läuft der Entwicklungsmodus (`start.ps1`, `npm run dev`). Diesen beenden. Beide nutzen Port 8000 und können nicht gleichzeitig laufen. |
| Doppelklick auf das Programm öffnet nur den Browser | Der Hub läuft schon (Symbol im Infobereich, ggf. unter „^“ ausgeblendet). Es darf nur ein Exemplar laufen. |
| Symbol ist rot | Status-Seite öffnen: Die Tabelle „Quellen“ und „Letzte Warnungen und Fehler“ zeigen die Ursache. Ausführlich steht sie im Log (Status → Logs). |
| TUWEL: „Noch kein erfolgreicher Sync“ | Erweiterung in Edge geladen und aktiviert? In TUWEL eingeloggt? TUWEL einmal öffnen – das startet einen Lauf. |
| Erweiterung meldet „Schlüssel passte nicht“ | Nichts tun: Der nächste Lauf holt den aktuellen Schlüssel selbst (z. B. nach einer Neuinstallation). |
| Edge zeigt „Erweiterungen im Entwicklermodus deaktivieren?“ | „Abbrechen“ bzw. Hinweis schließen. Entpackte Erweiterungen sind erlaubt; Edge erinnert nur daran. |
| Claude Desktop findet die Werkzeuge nicht | Claude Desktop ganz beenden (auch im Infobereich) und neu starten. Unter „KI verbinden“ prüfen, ob der Eintrag „aktuell“ ist, sonst neu eintragen. |
| Suche findet nichts / Transkription läuft nicht | Unter „KI verbinden“ die Schalter einschalten und im Assistenten die Modelle herunterladen. |
| Falscher Stand nach einem Fehler | Status → Sicherungen → passende Sicherung wiederherstellen. |
| Zugangsdaten ändern oder löschen | Im Hub neu eintragen (TUWEL-Token im Assistenten, MB Cloud „Neu verbinden“) oder in der Windows-Anmeldeinformationsverwaltung die „StudienHub“-Einträge löschen. |

## Für die Entwicklung

- Der Entwicklungsmodus (`start.ps1` bzw. `npm run dev`) bleibt unverändert und nutzt eigene Daten in
  `studien-hub/daten`. Zugangsdaten teilt er sich mit der installierten Version (Anmeldeinformationsverwaltung).
- Setup-Datei bauen: `.\build.ps1` (mit Tests) oder `.\build.ps1 -OhneTests`. Ergebnis:
  `dist\StudienHub-Setup-<Version>.exe`. Die Version steht nur in der Datei `VERSION`.
- `build.ps1` prüft nach dem Paketieren die wichtigsten Importe direkt in der fertigen exe
  (`StudienHub.exe --import-pruefen <module>`).
- Installationstest auf einem frischen Windows-Benutzer, zwei Wege:
  - **Windows Sandbox** (braucht eingeschaltete Virtualisierung im BIOS): `.\installer\sandbox-starten.ps1`. Ergebnis in
    `build\sandbox-ergebnis\ergebnis.txt`.
  - **Testkonto** (geht immer):
    1. `.\installer\testkonto-einrichten.ps1` ausführen (UAC-Rückfrage). Es zeigt das Kennwort an.
    2. *Benutzer wechseln* zu „StudienHubTest“.
    3. `C:\StudienHubTest\TEST-STARTEN.cmd` starten.
    4. Im Testkonto abmelden, wieder anmelden und `NACH-ANMELDUNG.cmd` starten. Das prüft den echten Autostart.
    5. Zurück im eigenen Konto `.\installer\testkonto-entfernen.ps1` ausführen.

    Ergebnis in `C:\StudienHubTest\ergebnis\ergebnis.txt`. Das Skript verweigert den Start in jedem anderen Konto.
