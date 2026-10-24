"""MB Cloud der Fachschaft Maschinenbau (mbcloud.at, Nextcloud) – reine Logik ohne Netz und Datenbank.

Aufbau der Cloud: `MB_VT_WIMB/<Titel> <Typ> <Nummer>/<Unterordner>/<Datei>`, z. B.
`MB_VT_WIMB/Mechanik 1 VO 309.019/Prüfungsunterlagen/2025-10-09-Gedankenprotokoll-Mechanik 1-309.019.pdf`.

- `kategorie_erkennen`: Altprüfung, Lösung, Ausarbeitung, Mitschrift, Formelsammlung, Sonstiges – aus Datei-
  und Ordnernamen (der Dateiname hat Vorrang). Gedankenprotokolle sind Altprüfungen, aber keine Originalangabe.
- `datum_erkennen`: Prüfungsdatum oder Jahr aus dem Namen (2025-10-09, 09.10.2025, WS2024, SS 23, 2021 …).
- `ordner_zuordnen`: LVA-Ordner zu einer LVA – sicher über die LVA-Nummer, sonst unscharf über den Titel.
- `loesungen_verknuepfen`: Lösung zur Altprüfung desselben Datums bzw. desselben Namens.
- `automatisch_laden`: Altprüfungen, Lösungen und Formelsammlungen der letzten 5 Jahre.
- `propfind_lesen`: WebDAV-Antwort (PROPFIND, Tiefe 1) in Einträge umwandeln.
"""

from __future__ import annotations

import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from urllib.parse import unquote

ALTPRUEFUNG = "altpruefung"
LOESUNG = "loesung"
AUSARBEITUNG = "ausarbeitung"
MITSCHRIFT = "mitschrift"
FORMELSAMMLUNG = "formelsammlung"
SONSTIGES = "sonstiges"
KATEGORIEN = [ALTPRUEFUNG, LOESUNG, AUSARBEITUNG, MITSCHRIFT, FORMELSAMMLUNG, SONSTIGES]
KATEGORIE_NAMEN = {
    ALTPRUEFUNG: "Altprüfung", LOESUNG: "Lösung", AUSARBEITUNG: "Ausarbeitung", MITSCHRIFT: "Mitschrift",
    FORMELSAMMLUNG: "Formelsammlung", SONSTIGES: "Sonstiges",
}
AUTOMATISCH = {ALTPRUEFUNG, LOESUNG, FORMELSAMMLUNG}
AUTOMATISCH_JAHRE = 5

LVA_NUMMER = re.compile(r"\b(\d{3}\.[0-9A-Z]{3})\b")
LVA_TYP = re.compile(r"\b(VO|UE|VU|SE|PR|LU|PS|EX|KO|AG|PV|SV|UV|VL)\b")

# Dateiname: genau, deshalb vor dem Ordner geprüft. Reihenfolge zählt (Lösung vor Prüfung).
_DATEI_REGELN = [
    (re.compile(r"l(ö|oe|o)sung|solution|musterl|loesg|lsg\b", re.I), LOESUNG),
    (re.compile(r"formel(sammlung|blatt|zettel|übersicht|uebersicht)|formulary|formelsammlung", re.I), FORMELSAMMLUNG),
    (re.compile(r"ged(a|ä|ae)n(k|ch)(en|tnis)?s?protokoll|gedaechtnisprotokoll", re.I), ALTPRUEFUNG),
    (re.compile(r"pr(ü|ue|u)fung|klausur|\bexam|\btest\b|teilpr|angabe|kolloquium|\bklau?sur", re.I), ALTPRUEFUNG),
    (re.compile(r"mitschrift|vorlesungsnotizen|notizen|lecture.?notes", re.I), MITSCHRIFT),
    (re.compile(r"zusammenfassung|ausarbeitung|summary|lernunterlage|lernzettel|spickzettel", re.I), AUSARBEITUNG),
]
# Ordnernamen (vom tiefsten zum obersten Unterordner)
_ORDNER_REGELN = [
    (re.compile(r"l(ö|oe)sung", re.I), LOESUNG),
    (re.compile(r"formel", re.I), FORMELSAMMLUNG),
    (re.compile(r"pr(ü|ue)fung|klausur|theoriefragen|altpr|tests?\b|gedankenprotokoll", re.I), ALTPRUEFUNG),
    (re.compile(r"mitschrift", re.I), MITSCHRIFT),
    (re.compile(r"zusammenfassung|ausarbeitung", re.I), AUSARBEITUNG),
]
GEDANKENPROTOKOLL = re.compile(r"ged(a|ä|ae)n(k|ch)(en|tnis)?s?protokoll|gedaechtnisprotokoll", re.I)


@dataclass(frozen=True)
class Einteilung:
    kategorie: str
    gedankenprotokoll: bool = False


def kategorie_erkennen(name: str, ordner: list[str] | tuple[str, ...] = ()) -> Einteilung:
    """Kategorie aus Dateiname, sonst aus den Unterordnern (tiefster zuerst)."""
    stamm = name.rsplit(".", 1)[0] if "." in name else name
    protokoll = bool(GEDANKENPROTOKOLL.search(stamm)) or any(GEDANKENPROTOKOLL.search(o) for o in ordner)
    for muster, kategorie in _DATEI_REGELN:
        if muster.search(stamm):
            return Einteilung(kategorie, protokoll and kategorie == ALTPRUEFUNG)
    for teil in reversed(list(ordner)):
        for muster, kategorie in _ORDNER_REGELN:
            if muster.search(teil):
                return Einteilung(kategorie, protokoll and kategorie == ALTPRUEFUNG)
    return Einteilung(SONSTIGES)


# --- Datum und Jahr -----------------------------------------------------------------------------

_ISO = re.compile(r"(?<!\d)(20\d{2}|19\d{2})[-_. ]?(0[1-9]|1[0-2])[-_. ]?(0[1-9]|[12]\d|3[01])(?!\d)")
_DEUTSCH = re.compile(r"(?<![\d.])(0?[1-9]|[12]\d|3[01])[._-](0?[1-9]|1[0-2])[._-](20\d{2}|19\d{2}|\d{2})(?![\d])")
_SEMESTER = re.compile(r"\b(WS|SS|WiSe|SoSe|W|S)[ _-]?(20\d{2}|\d{2})(?:[/_-](?:20)?\d{2})?\b", re.I)
_JAHR = re.compile(r"(?<![\d.])(20[0-4]\d|199\d)(?![\d.]\d)")
_MONATE = {
    "jänner": 1, "jaenner": 1, "januar": 1, "jan": 1, "februar": 2, "feb": 2, "märz": 3, "maerz": 3, "mär": 3,
    "april": 4, "apr": 4, "mai": 5, "juni": 6, "jun": 6, "juli": 7, "jul": 7, "august": 8, "aug": 8,
    "september": 9, "sept": 9, "sep": 9, "oktober": 10, "okt": 10, "november": 11, "nov": 11,
    "dezember": 12, "dez": 12,
}
_MONAT_JAHR = re.compile(r"\b(" + "|".join(sorted(_MONATE, key=len, reverse=True)) + r")\.?[ _-]?(20\d{2})\b", re.I)


def _gueltig(jahr: int, monat: int, tag: int) -> date | None:
    try:
        return date(jahr, monat, tag) if 1990 <= jahr <= 2100 else None
    except ValueError:
        return None


def datum_erkennen(name: str, ordner: list[str] | tuple[str, ...] = ()) -> tuple[date | None, int | None]:
    """(Prüfungsdatum, Jahr) aus Dateiname, sonst aus den Unterordnern. LVA-Nummern (311.093) zählen nicht."""
    for text in [name, *reversed(list(ordner))]:
        text = LVA_NUMMER.sub(" ", text)
        if m := _ISO.search(text):
            if d := _gueltig(int(m[1]), int(m[2]), int(m[3])):
                return d, d.year
        if m := _DEUTSCH.search(text):
            jahr = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
            if d := _gueltig(jahr, int(m[2]), int(m[1])):
                return d, d.year
        if m := _MONAT_JAHR.search(text):
            return None, int(m[2])
        if m := _SEMESTER.search(text):
            jahr = int(m[2]) + (2000 if len(m[2]) == 2 else 0)
            if 1990 <= jahr <= 2100:
                return None, jahr
        if m := _JAHR.search(text):
            return None, int(m[1])
    return None, None


# --- Zuordnung zu LVAs ----------------------------------------------------------------------------

@dataclass(frozen=True)
class LvaKandidat:
    """Was die Zuordnung über eine LVA wissen muss. Reihenfolge der Liste = Vorrang (besuchte, aktuelles Semester)."""

    lva_id: int
    titel: str
    nummern: frozenset[str] = frozenset()
    kurzname: str | None = None


@dataclass(frozen=True)
class Zuordnung:
    lva_id: int | None
    aehnlichkeit: float
    sicher: bool


def _normal(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = LVA_NUMMER.sub(" ", text)
    text = re.sub(r"\b(vo|ue|vu|se|pr|lu|ps|ex|ko|ag|pv|sv|uv|vl|rechenubung|ubung|vorlesung)\b", " ", text)
    text = re.sub(r"\bf(u|ue)r\b|\bund\b|\bder\b|\bdie\b|\bdes\b|\bin\b|&", " ", text)
    return re.sub(r"[^0-9a-z]+", " ", text).strip()


def ordner_titel(name: str) -> tuple[str, str | None, str | None]:
    """„Mechanik 1 VO 309.019“ -> („Mechanik 1“, „VO“, „309.019“)."""
    nummer = (LVA_NUMMER.search(name) or [None, None])[1]
    rest = LVA_NUMMER.sub(" ", name)
    typ = (LVA_TYP.search(rest) or [None, None])[1]
    titel = re.sub(r"\s+", " ", LVA_TYP.sub(" ", rest)).strip(" -_")
    return titel, typ, nummer


def titel_aehnlichkeit(a: str, b: str) -> float:
    """0–1; verschiedene Zahlen im Titel (Mechanik 1 / Mechanik 2) schließen eine Übereinstimmung aus."""
    na, nb = _normal(a), _normal(b)
    if not na or not nb:
        return 0.0
    zahlen_a, zahlen_b = set(re.findall(r"\d+", na)), set(re.findall(r"\d+", nb))
    if (zahlen_a or zahlen_b) and zahlen_a != zahlen_b:
        return 0.0
    if na == nb:
        return 1.0
    worte_a, worte_b = set(na.split()), set(nb.split())
    jaccard = len(worte_a & worte_b) / len(worte_a | worte_b)
    return round(max(SequenceMatcher(None, na, nb).ratio(), jaccard), 3)


SICHER_AB = 1.0  # nur identische Titel gelten ohne Nummer als sicher
VORSCHLAG_AB = 0.6


def ordner_zuordnen(name: str, kandidaten: list[LvaKandidat]) -> Zuordnung:
    """Sicher über die LVA-Nummer; sonst Titelvergleich – ähnliche Titel nur als Vorschlag zur Bestätigung."""
    titel, _, nummer = ordner_titel(name)
    if nummer:
        for k in kandidaten:
            if nummer in k.nummern:
                return Zuordnung(k.lva_id, 1.0, True)
    bester = Zuordnung(None, 0.0, False)
    for k in kandidaten:
        wert = max(titel_aehnlichkeit(titel, k.titel), titel_aehnlichkeit(titel, k.kurzname or ""))
        if wert > bester.aehnlichkeit:
            bester = Zuordnung(k.lva_id, wert, False)
    # eine fremde LVA-Nummer im Ordnernamen widerspricht: höchstens Vorschlag (gleichnamige LVA eines anderen Studiums)
    if bester.aehnlichkeit >= SICHER_AB and not nummer:
        return Zuordnung(bester.lva_id, bester.aehnlichkeit, True)
    if bester.aehnlichkeit >= VORSCHLAG_AB:
        return bester
    return Zuordnung(None, bester.aehnlichkeit, False)


# --- Lösung zur Altprüfung ------------------------------------------------------------------------

@dataclass(frozen=True)
class IndexEintrag:
    """Minimalform für Verknüpfung und Download-Regel."""

    schluessel: int
    name: str
    eltern: str
    kategorie: str
    datum: date | None = None
    jahr: int | None = None


_OHNE_LOESUNG = re.compile(r"musterl(ö|oe)sung(en)?|l(ö|oe)sung(en)?|solution|loesg|lsg|mit|inkl", re.I)


def _stamm(name: str) -> str:
    stamm = name.rsplit(".", 1)[0]
    return re.sub(r"[^0-9a-z]+", " ", _OHNE_LOESUNG.sub(" ", _normal(stamm))).strip()


def loesungen_verknuepfen(eintraege: list[IndexEintrag]) -> dict[int, int]:
    """Lösung -> Altprüfung: zuerst gleiches Datum, sonst gleicher Name ohne „Lösung“, sonst gleiches Jahr im selben Ordner."""
    pruefungen = [e for e in eintraege if e.kategorie == ALTPRUEFUNG]
    paare: dict[int, int] = {}
    for l in (e for e in eintraege if e.kategorie == LOESUNG):
        treffer = None
        if l.datum:
            treffer = next((p for p in pruefungen if p.datum == l.datum), None)
        if treffer is None:
            stamm = _stamm(l.name)
            treffer = next((p for p in pruefungen if stamm and _stamm(p.name) == stamm), None)
        if treffer is None and l.jahr:
            gleich = [p for p in pruefungen if p.eltern == l.eltern and p.jahr == l.jahr and not p.datum]
            treffer = gleich[0] if len(gleich) == 1 else None
        if treffer is not None:
            paare[l.schluessel] = treffer.schluessel
    return paare


def automatisch_laden(kategorie: str | None, jahr: int | None, heute: date) -> bool:
    """Standard: Altprüfungen, Lösungen und Formelsammlungen der letzten 5 Jahre; alles andere per Klick."""
    return kategorie in AUTOMATISCH and jahr is not None and jahr >= heute.year - AUTOMATISCH_JAHRE


# --- WebDAV ----------------------------------------------------------------------------------------

@dataclass(frozen=True)
class DavEintrag:
    pfad: str  # relativ zum Benutzerordner, ohne führenden und abschließenden Schrägstrich
    name: str
    ist_ordner: bool
    groesse: int | None
    geaendert: datetime | None
    etag: str | None


NS = {"d": "DAV:", "oc": "http://owncloud.org/ns"}
PROPFIND_KOERPER = (
    '<?xml version="1.0"?><d:propfind xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns"><d:prop>'
    "<d:getlastmodified/><d:getcontentlength/><d:getetag/><d:resourcetype/><oc:size/>"
    "</d:prop></d:propfind>"
)


def propfind_lesen(xml: str | bytes, wurzel_href: str) -> list[DavEintrag]:
    """Liest eine PROPFIND-Antwort. `wurzel_href` z. B. „/remote.php/dav/files/abc123/“."""
    wurzel = unquote(wurzel_href).rstrip("/") + "/"
    eintraege = []
    for antwort in ET.fromstring(xml).findall("d:response", NS):
        href = unquote(antwort.findtext("d:href", "", NS))
        pfad = href.split(wurzel, 1)[1] if wurzel in href else href
        pfad = pfad.strip("/")
        prop = None
        for propstat in antwort.findall("d:propstat", NS):
            if "200" in (propstat.findtext("d:status", "", NS) or ""):
                prop = propstat.find("d:prop", NS)
        if prop is None:
            continue
        ist_ordner = prop.find("d:resourcetype/d:collection", NS) is not None
        groesse = prop.findtext("oc:size", None, NS) if ist_ordner else prop.findtext("d:getcontentlength", None, NS)
        geaendert = prop.findtext("d:getlastmodified", None, NS)
        try:
            zeit = parsedate_to_datetime(geaendert).astimezone().replace(tzinfo=None) if geaendert else None
        except (TypeError, ValueError):
            zeit = None
        etag = (prop.findtext("d:getetag", None, NS) or "").strip('"') or None
        eintraege.append(DavEintrag(pfad, pfad.rsplit("/", 1)[-1], ist_ordner,
                                    int(groesse) if groesse and groesse.isdigit() else None, zeit, etag))
    return eintraege
