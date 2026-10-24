"""Prompt-Vorlagen des MCP-Servers (in Claude Desktop über „+“ → studien-hub auswählbar).

Reine Textbausteine ohne Datenbank: Jede Vorlage beschreibt den Ablauf und nennt die Werkzeuge, die Claude dafür
aufruft. Der Wochenbericht (wochenbericht.py) entsteht ohne Claude aus den TUWEL-Daten.
"""

from __future__ import annotations

from datetime import date, timedelta


def _woche_text(woche: date | None) -> str:
    if woche is None:
        return "diese Woche"
    montag = woche - timedelta(days=woche.weekday())
    return f"die Woche vom {montag:%d.%m.} bis {montag + timedelta(days=6):%d.%m.%Y}"


def thema_lernen(lva: str, thema: str) -> str:
    return f"""Ich möchte das Thema „{thema}“ in der LVA {lva} lernen.

Ablauf:
1. Ruf `wissensstand` für „{lva}“ auf: Stufe, letzte Übung und Tage bis zur Prüfung für „{thema}“. Ist das Thema
   neu (Stufe 0) oder unbekannt, frag mich kurz, was ich schon weiß.
2. Such mit `suche_unterlagen` (lva: „{lva}“) die passenden Abschnitte und lies die wichtigsten mit `lies_abschnitt`.
3. Erklär das Thema in kleinen Schritten – je Schritt ein Gedanke, mit Quelle (Datei und Seite bzw. Video und
   Zeitmarke). Pass Tiefe und Tempo an meine Stufe an.
4. Nach jedem Schritt eine kurze Verständnisfrage. Warte auf meine Antwort, bevor du weitermachst, und kläre
   Missverständnisse sofort.
5. Zum Schluss 3 Kontrollfragen mit steigender Schwierigkeit; werte meine Antworten aus.
6. Trag das Ergebnis mit `lernereignis_eintragen` ein (thema: „{thema}“, lva: „{lva}“, art: quiz, ergebnis: Anteil
   richtig beantworteter Kontrollfragen) und nenne mir die neue Stufe und die nächste Wiederholung."""


def wochenstart_text(woche: date | None = None, automatisch: bool = False) -> str:
    zeitraum = _woche_text(woche)
    text = f"""Wochenstart für {zeitraum}.

Sammle zuerst:
1. `rueckblick`{f' (woche: „{(woche - timedelta(days=7)).isoformat()}“)' if woche else ''} für die vergangene Woche: erledigte und offene Lernblöcke, eingetragene Ergebnisse
   (Lernereignisse, bearbeitete Altprüfungen), geleistete Arbeitsstunden.
2. `neue_unterlagen` der letzten 7 Tage (neuer Stoff je LVA).
3. `pruefungen` (mit Tagen bis dahin) und `faellige_wiederholungen`.
4. `wochenplan`{f' (woche: „{woche.isoformat()}“)' if woche else ''} – Termine, Arbeit, schon geplante Lernblöcke, Lernstand.

Daraus:
- Kurzer Rückblick: was lief, was blieb offen (mit Zahlen).
- Neuer Stoff je LVA, nächste Prüfungen mit Countdown, fällige Wiederholungen.
- Genau 3 Prioritäten für die Woche, jeweils mit Begründung (Prüfungsnähe, Rückstand, Wissensstand).
- Lernblöcke für diese Prioritäten mit `lernblock_vorschlagen` anlegen – nur in freien Zeiten laut `wochenplan`,
  ohne Überschneidung mit Terminen, Arbeit oder vorhandenen Lernblöcken, je 45–120 Minuten. Liste sie danach auf
  (Tag, Uhrzeit, LVA, Inhalt). Sie sind nur Vorschläge; ich bestätige sie im Hub."""
    if automatisch:
        text += """

Dies ist ein automatischer Lauf ohne Rückfragen: Stell keine Fragen, triff vernünftige Annahmen und nenne sie.
Antworte ausschließlich mit dem fertigen Bericht in Markdown mit diesen Überschriften:
## Rückblick
## Neuer Stoff
## Prüfungen und Wiederholungen
## Prioritäten
## Vorgeschlagene Lernblöcke
Nenne bei Aussagen aus Unterlagen die Quelle; MB-Cloud-Inhalte als „inoffiziell, MB Cloud, Jahr“."""
    return text


def wiederholung(lva: str | None = None) -> str:
    bereich = f"in {lva}" if lva else "aller LVAs"
    return f"""Wiederholung der fälligen Themen {bereich}.

1. Ruf `faellige_wiederholungen`{f' (lva: „{lva}“)' if lva else ''} auf. Ist nichts fällig, sag das und schlag die drei
   schwächsten Themen aus `wissensstand` vor.
2. Für jedes fällige Thema 2–3 Fragen, die du aus meinen Unterlagen ableitest (`suche_unterlagen`) – eine nach der
   anderen. Warte jeweils auf meine Antwort und gib eine kurze Rückmeldung mit Quelle.
3. Nach jedem Thema `lernereignis_eintragen` (art: quiz, ergebnis: Anteil richtig). Das passt Stufe und Abstand
   nach Spaced Repetition an: ab 80 % eine Stufe hinauf und längerer Abstand, unter 50 % eine Stufe hinunter.
4. Zum Schluss eine Tabelle: Thema | Ergebnis | Stufe alt → neu | nächste Wiederholung."""


def pruefung_simulieren(lva: str, minuten: int = 90) -> str:
    return f"""Prüfungssimulation für {lva}, Zeitlimit {minuten} Minuten.

1. `altpruefungen` (lva: „{lva}“): Nimm die neueste noch nicht bearbeitete Altprüfung (bearbeitet = false), die
   lesbaren Text hat (abschnitte nicht leer). Originalangaben vor Gedankenprotokollen. Sag mir, welche du nimmst –
   sie ist inoffiziell (MB Cloud, Jahr). Gibt es keine, sag das.
2. Lies sie mit `lies_dokument` und gib mir alle Aufgaben vollständig, aber ohne Lösung. Nenne Start- und Endzeit
   ({minuten} Minuten ab jetzt). Während der Zeit keine Hilfen, nur Verständnisfragen zur Angabe beantworten.
3. Wenn ich abgebe oder die Zeit um ist: Bewerte anhand der Lösung (`loesung_dokument_id` → `lies_dokument`). Gibt
   es keine Lösung, bewerte mit den offiziellen Unterlagen und sag das. Punkte je Aufgabe und gesamt.
4. Fehleranalyse pro Thema (Themen aus `wissensstand`), jeweils mit Fundstellen zum Nacharbeiten.
5. `altpruefung_bearbeitet` (dokument_id, Minuten, Punkte, maximale Punkte) und für jedes betroffene Thema
   `lernereignis_eintragen` (art: altpruefung, ergebnis: Anteil der Punkte in diesem Thema)."""


def vorlesung_nachholen(termin: str) -> str:
    return f"""Ich habe die Vorlesung „{termin}“ verpasst und will sie nachholen.

1. `aufzeichnung_zu_termin` (termin: „{termin}“) findet den Termin und die passende Aufzeichnung samt Transkript.
   Gibt es keine Aufzeichnung oder kein Transkript, sag das und nimm stattdessen die Folien und Skriptteile, die
   in dieser Woche erschienen sind (`neue_unterlagen`).
2. Fasse die Vorlesung in Abschnitten zusammen, jeweils mit Zeitmarke (Video und Minute).
3. Verknüpfe jeden Abschnitt mit dem passenden Skript-Abschnitt (`suche_unterlagen` in dieser LVA: Datei und Seite).
4. Stell mir 3 Kontrollfragen, werte meine Antworten aus und trag `lernereignis_eintragen` für das passende Thema ein."""


VORLAGEN = {
    "thema_lernen": ("Thema lernen", ["lva", "thema"], []),
    "wochenstart": ("Wochenstart", [], []),
    "wiederholung": ("Wiederholung", [], ["lva"]),
    "pruefung_simulieren": ("Prüfung simulieren", ["lva"], ["minuten"]),
    "vorlesung_nachholen": ("Vorlesung nachholen", ["termin"], []),
    "plan_anpassen": ("Plan anpassen", ["grund"], ["woche"]),
}


def vorlage_text(name: str, werte: dict[str, str | None]) -> str:
    """Text einer Vorlage mit Werten; fehlende Pflichtfelder lösen ValueError aus."""
    if name not in VORLAGEN:
        raise ValueError(f"Unbekannte Vorlage „{name}“ – vorhanden: {', '.join(VORLAGEN)}.")
    _, pflicht, frei = VORLAGEN[name]
    fehlend = [f for f in pflicht if not (werte.get(f) or "").strip()]
    if fehlend:
        raise ValueError(f"Für „{name}“ fehlt: {', '.join(fehlend)}.")
    argumente = {f: werte[f].strip() for f in pflicht} | {f: (werte.get(f) or "").strip() or None for f in frei}
    if name == "wochenstart":
        return wochenstart_text()
    if name == "pruefung_simulieren":
        minuten = argumente.pop("minuten")
        return pruefung_simulieren(argumente["lva"], int(minuten) if minuten and minuten.isdigit() else 90)
    return globals()[name](**argumente)


def plan_anpassen(grund: str, woche: str | None = None) -> str:
    return f"""Mein Wochenplan muss angepasst werden. Grund: {grund}

1. `wochenplan`{f' (woche: „{woche}“)' if woche else ''}: Termine, Arbeit, Lernblöcke, Lernstand und Prüfungen.
2. Betrifft der Grund feste Zeiten (Krankheit, zusätzlicher Termin, Ausfall), frag nach den genauen Tagen und
   Uhrzeiten, bevor du planst.
3. Es gelten die Planungsregeln des Hubs: Pflichttermine zuerst, dann Arbeit (die Wochenstunden sind Pflicht und
   werden nie gekürzt), dann Lernen bis zum Wochenbedarf; reicht die Zeit nicht, wird zuerst Lernzeit von LVAs ohne
   nahe Prüfung gekürzt.
4. Lass den Hub die Woche mit `wochenplan_vorschlagen` neu vorschlagen (bestätigte Blöcke bleiben unverändert) und
   ergänze bei Bedarf einzelne Lernblöcke mit `lernblock_vorschlagen`.
5. Fasse die Änderungen zusammen (was neu, was entfällt, welche LVA hinter den Plan fällt) und erinnere mich, die
   Vorschläge im Hub zu bestätigen."""
