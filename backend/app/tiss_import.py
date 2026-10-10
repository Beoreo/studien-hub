"""Import des persönlichen TISS-Kalenders (iCal).

Der Feed enthält pro Termin ein VEVENT. Die LVA wird aus SUMMARY/DESCRIPTION erkannt
(z. B. „185.A91 VU Einführung in die Programmierung 1“). Ein erneuter Import gleicht über die
iCal-UID ab und übernimmt nur Änderungen; eigene Abweichungen am Termin bleiben erhalten.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

import httpx
from icalendar import Calendar
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import ZEITZONE
from .models import (
    STANDARD_FARBEN,
    TYP_PRUEFUNG,
    TYP_SONSTIGE,
    TYP_UE,
    TYP_VO,
    TYP_VU,
    Lva,
    Termin,
)
from .planung import wochenbeginn

LVA_NUMMER = re.compile(r"\b(\d{3}\.[0-9A-Z]{3})\b")
LVA_TYP = re.compile(r"\b(VO|UE|VU|SE|PR|LU|PS|EX|KO|AG|PV|SV|UV|VL)\b")
PRUEFUNG = re.compile(r"prüfung|pruefung|\bexam|klausur|\btest\b|\btermin zur leistungsfeststellung", re.IGNORECASE)
TYP_ABBILDUNG = {"VO": TYP_VO, "UE": TYP_UE, "VU": TYP_VU, "VL": TYP_VO}


@dataclass
class TissTermin:
    uid: str
    lva_nummer: str | None
    lva_titel: str
    typ: str
    start: datetime
    ende: datetime
    ort: str | None
    beschreibung: str | None
    zusammenfassung: str


@dataclass
class ImportErgebnis:
    neu: int = 0
    geaendert: int = 0
    geloescht: int = 0
    unveraendert: int = 0
    neue_lvas: list[str] = field(default_factory=list)
    betroffene_wochen: set[date] = field(default_factory=set)
    neu_geplante_wochen: list[date] = field(default_factory=list)


def zu_lokaler_zeit(wert: date | datetime) -> datetime:
    """Wandelt iCal-Zeiten in naive Wiener Lokalzeit um."""
    if not isinstance(wert, datetime):
        return datetime.combine(wert, time())
    if wert.tzinfo is not None:
        return wert.astimezone(ZEITZONE).replace(tzinfo=None)
    return wert


def semester_von(zeitpunkt: datetime) -> str:
    """Wintersemester Oktober–Februar (z. B. „2026W“), sonst Sommersemester („2026S“)."""
    if zeitpunkt.month >= 10:
        return f"{zeitpunkt.year}W"
    if zeitpunkt.month <= 2:
        return f"{zeitpunkt.year - 1}W"
    return f"{zeitpunkt.year}S"


def _kategorien(komponente) -> list[str]:
    roh = komponente.get("CATEGORIES")
    if roh is None:
        return []
    eintraege = roh if isinstance(roh, list) else [roh]
    texte: list[str] = []
    for eintrag in eintraege:
        if hasattr(eintrag, "cats"):
            texte += [str(c) for c in eintrag.cats]
        else:
            texte.append(str(eintrag))
    return texte


def zerlege_zusammenfassung(zusammenfassung: str, beschreibung: str = "") -> tuple[str | None, str, str | None]:
    """Liefert (LVA-Nummer, LVA-Titel, LVA-Typ-Kürzel) aus dem SUMMARY-Text."""
    nummer_treffer = LVA_NUMMER.search(zusammenfassung) or LVA_NUMMER.search(beschreibung)
    nummer = nummer_treffer.group(1) if nummer_treffer else None
    rest = LVA_NUMMER.sub("", zusammenfassung).strip()
    typ_treffer = LVA_TYP.search(rest)
    typ = typ_treffer.group(1) if typ_treffer else None
    if typ_treffer:
        vorne, hinten = rest[: typ_treffer.start()].strip(), rest[typ_treffer.end():].strip()
        titel = hinten or vorne  # „185.A91 VU Titel“ oder Kurzform „EP1 VU“
    else:
        titel = rest
    titel = titel.strip(" -–:,") or (beschreibung.splitlines()[0].strip() if beschreibung else "") or zusammenfassung
    return nummer, titel, typ


def parse_ical(daten: bytes | str) -> list[TissTermin]:
    """Liest alle Termine aus einem iCal-Feed."""
    kalender = Calendar.from_ical(daten)
    termine: list[TissTermin] = []
    gesehene_uids: set[str] = set()
    for komponente in kalender.walk("VEVENT"):
        if "DTSTART" not in komponente:
            continue
        zusammenfassung = str(komponente.get("SUMMARY", "")).strip()
        beschreibung = str(komponente.get("DESCRIPTION", "")).strip()
        start = zu_lokaler_zeit(komponente.decoded("DTSTART"))
        if "DTEND" in komponente:
            ende = zu_lokaler_zeit(komponente.decoded("DTEND"))
        elif "DURATION" in komponente:
            ende = start + komponente.decoded("DURATION")
        else:
            ende = start + timedelta(hours=1)

        nummer, titel, typ_kuerzel = zerlege_zusammenfassung(zusammenfassung, beschreibung)
        kategorien = " ".join(_kategorien(komponente)).upper()
        if "EXAM" in kategorien or PRUEFUNG.search(zusammenfassung):
            typ = TYP_PRUEFUNG
            titel = PRUEFUNG.sub("", titel).strip(" -–:,") or titel
        else:
            typ = TYP_ABBILDUNG.get(typ_kuerzel or "", TYP_SONSTIGE)

        uid = str(komponente.get("UID", "")).strip()
        if not uid:
            uid = "ohne-uid-" + hashlib.sha1(f"{zusammenfassung}|{start.isoformat()}".encode()).hexdigest()
        if uid in gesehene_uids:
            uid = f"{uid}#{start.isoformat()}"  # wiederholte UID (z. B. Serien) eindeutig machen
        gesehene_uids.add(uid)

        termine.append(
            TissTermin(
                uid=uid,
                lva_nummer=nummer,
                lva_titel=titel,
                typ=typ,
                start=start,
                ende=ende,
                ort=str(komponente.get("LOCATION", "")).strip() or None,
                beschreibung=beschreibung or None,
                zusammenfassung=zusammenfassung,
            )
        )
    return termine


def _finde_oder_erzeuge_lva(session: Session, termin: TissTermin, cache: dict, ergebnis: ImportErgebnis) -> Lva:
    semester = semester_von(termin.start)
    schluessel = termin.lva_nummer or termin.lva_titel
    if (schluessel, semester) in cache:
        return cache[(schluessel, semester)]
    lva = session.scalar(select(Lva).where(Lva.schluessel == schluessel, Lva.semester == semester))
    if lva is None:
        anzahl = session.query(Lva).count()
        lva = Lva(
            schluessel=schluessel,
            nummer=termin.lva_nummer,
            titel=termin.lva_titel,
            semester=semester,
            farbe=STANDARD_FARBEN[anzahl % len(STANDARD_FARBEN)],
        )
        session.add(lva)
        session.flush()
        ergebnis.neue_lvas.append(f"{termin.lva_nummer or ''} {termin.lva_titel}".strip())
    elif (
        lva.nummer
        and termin.typ != TYP_PRUEFUNG
        and len(termin.lva_titel) > len(lva.titel)
    ):
        lva.titel = termin.lva_titel  # längeren (vollständigeren) Titel bevorzugen
    cache[(schluessel, semester)] = lva
    return lva


def importiere_termine(session: Session, tiss_termine: list[TissTermin]) -> ImportErgebnis:
    """Gleicht die Termine aus dem Feed mit der Datenbank ab (nur Änderungen werden übernommen)."""
    ergebnis = ImportErgebnis()
    bestehend = {t.tiss_uid: t for t in session.scalars(select(Termin).where(Termin.quelle == "tiss"))}
    lva_cache: dict = {}
    jetzt = datetime.now()

    for neu in tiss_termine:
        lva = _finde_oder_erzeuge_lva(session, neu, lva_cache, ergebnis)
        werte = {
            "lva_id": lva.id,
            "typ": neu.typ,
            "titel": neu.zusammenfassung,
            "start": neu.start,
            "ende": neu.ende,
            "ort": neu.ort,
            "beschreibung": neu.beschreibung,
        }
        alt = bestehend.pop(neu.uid, None)
        if alt is None:
            session.add(Termin(tiss_uid=neu.uid, quelle="tiss", geaendert_am=jetzt, **werte))
            ergebnis.neu += 1
            ergebnis.betroffene_wochen.add(wochenbeginn(neu.start.date()))
        elif any(getattr(alt, k) != v for k, v in werte.items()):
            ergebnis.betroffene_wochen.add(wochenbeginn(alt.start.date()))
            ergebnis.betroffene_wochen.add(wochenbeginn(neu.start.date()))
            for k, v in werte.items():
                setattr(alt, k, v)
            alt.geaendert_am = jetzt
            ergebnis.geaendert += 1
        else:
            ergebnis.unveraendert += 1

    # Termine, die nicht mehr im Feed stehen, löschen – aber nur im Zeitraum, den der Feed abdeckt
    if tiss_termine:
        frueheste = min(t.start for t in tiss_termine)
        for verschwunden in bestehend.values():
            if verschwunden.start >= frueheste:
                ergebnis.betroffene_wochen.add(wochenbeginn(verschwunden.start.date()))
                session.delete(verschwunden)
                ergebnis.geloescht += 1

    session.commit()
    return ergebnis


def lade_feed(url: str) -> bytes:
    """Lädt den iCal-Feed; webcal:// wird als https:// abgerufen."""
    if url.startswith("webcal://"):
        url = "https://" + url.removeprefix("webcal://")
    antwort = httpx.get(url, timeout=30, follow_redirects=True)
    antwort.raise_for_status()
    return antwort.content


def importiere_ical(session: Session, daten: bytes | str, neu_planen: bool = True) -> ImportErgebnis:
    """Parst den Feed, gleicht ab und plant betroffene zukünftige Wochen neu."""
    ergebnis = importiere_termine(session, parse_ical(daten))
    if neu_planen:
        from .planung_service import plane_wochen_neu

        ergebnis.neu_geplante_wochen = plane_wochen_neu(session, ergebnis.betroffene_wochen)
    return ergebnis
