"""Struktur der LVAs: eine LVA je Nummer, Teile für Gruppen, und vorlesungsfreie Zeiten aus TISS.

TISS liefert VO, UE und Übungsgruppen derselben Lehrveranstaltung als eigene Einträge mit eigener
Nummer („104.297 VO Mathematik 1 …“, „104.604 UE Mathematik 1 … - Gruppe 8“). Jede Nummer ist eine eigene
LVA (mit `typ` VO/UE … zur Unterscheidung gleichnamiger LVAs). Teile einer LVA sind ihre Gruppen und
Plenartermine (gleiche Nummer); jeder Teil behält Gruppe, eigene Markierungen und eigenen TUWEL-Kurs.
Frühere Versionen haben VO und UE gleichen Titels zusammengefasst – `lvas_trennen` macht das rückgängig.

Einträge wie „Osterferien, vorlesungsfrei“ oder „Rektorstag“ sind keine LVAs, sondern freie Zeiträume.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .models import (
    STANDARD_FARBEN,
    TYP_ABGABE,
    TYP_PRUEFUNG,
    Dokument,
    FreierZeitraum,
    Lernblock,
    Lva,
    LvaTeil,
    Termin,
    TuwelKurs,
    lies_einstellung,
    setze_einstellung,
)

LVA_NUMMER = re.compile(r"\b(\d{3}\.[0-9A-Z]{3})\b")
FREI = re.compile(
    r"vorlesungsfrei|lehrveranstaltungsfrei|ferien|feiertag|rektorstag|dies academicus|landespatron|"
    r"allerheiligen|allerseelen|empfängnis|himmelfahrt|fronleichnam|pfingst|ostern|weihnacht|neujahr|"
    r"heilige drei könige",
    re.IGNORECASE,
)
GRUPPE = re.compile(r"\s*[-–,:]\s*((?:Gruppe|Gr\.|Group|Kleingruppe|Übungsgruppe)\s*\S.*)$", re.IGNORECASE)
LVA_TYPEN = r"vo|ue|vu|se|pr|lu|ps|ex|ko|ag|pv|sv|uv|vl"

STRUKTUR_VERSION = "3"  # 3: VO und UE wieder getrennt (eine LVA je Nummer)
STRUKTUR_SCHLUESSEL = "lva_struktur"


# --- Erkennen und Zerlegen ------------------------------------------------------------------

def ist_freier_eintrag(titel: str, nummer: str | None = None) -> bool:
    """Ferien, Feiertage, Rektorstag … – nie für Einträge mit LVA-Nummer."""
    return nummer is None and not LVA_NUMMER.search(titel or "") and bool(FREI.search(titel or ""))


def freier_name(titel: str) -> str:
    """„Osterferien, vorlesungsfrei“ -> „Osterferien“."""
    name = re.sub(r"[,;–-]?\s*(lehrveranstaltungs|vorlesungs)frei\b", "", titel or "", flags=re.IGNORECASE)
    return name.strip(" ,;–-") or (titel or "frei").strip()


def zerlege_gruppe(titel: str) -> tuple[str, str | None]:
    """„Mathematik 1 für MB - Gruppe 8“ -> („Mathematik 1 für MB“, „Gruppe 8“)."""
    treffer = GRUPPE.search(titel or "")
    if not treffer:
        return (titel or "").strip(), None
    return titel[: treffer.start()].strip(), re.sub(r"\s+", " ", treffer.group(1)).strip()


def gruppen_schluessel(titel: str) -> str:
    """Vergleichsschlüssel für den Titel einer LVA (ohne Gruppe, Typ, Stunden, Satzzeichen)."""
    basis, _ = zerlege_gruppe(titel)
    text = LVA_NUMMER.sub(" ", basis.casefold())
    text = re.sub(rf"\b({LVA_TYPEN})\b|\(.*?\)", " ", text)
    return re.sub(r"[^0-9a-zäöüß]+", " ", text).strip()


# --- Finden oder Anlegen -------------------------------------------------------------------------

@dataclass
class TeilTreffer:
    lva: Lva
    teil: LvaTeil
    neue_lva: bool = False


def finde_oder_erzeuge_teil(
    session: Session, nummer: str | None, titel: str, lva_typ: str | None, semester: str, cache: dict | None = None
) -> TeilTreffer:
    """Ordnet einen TISS-Eintrag seinem Teil zu; legt LVA und Teil bei Bedarf an."""
    cache = cache if cache is not None else {}
    basis, gruppe = zerlege_gruppe(titel)
    schluessel = gruppen_schluessel(basis) or (nummer or basis)
    cache_schluessel = (nummer, schluessel if not nummer else None, gruppe, semester)
    if cache_schluessel in cache:
        treffer = cache[cache_schluessel]
        _typ_ergaenzen(treffer.teil, lva_typ)
        return TeilTreffer(treffer.lva, treffer.teil, False)

    teil = None
    geschwister: list[LvaTeil] = []
    lva = None
    if nummer:
        # gleiche Nummer = dieselbe LVA (andere Gruppe oder abweichender Titel); andere Nummer = eigene LVA
        geschwister = list(session.scalars(
            select(LvaTeil).join(Lva).where(LvaTeil.nummer == nummer, Lva.semester == semester).order_by(LvaTeil.id)
        ))
        teil = _passender_teil(geschwister, gruppe)
        lva = teil.lva if teil else geschwister[0].lva if geschwister else None
        if lva is None:
            lva = session.scalar(select(Lva).where(Lva.nummer == nummer, Lva.semester == semester))
    else:
        lva = _lva_nach_titel(session, schluessel, lva_typ, semester)
    neue_lva = False
    if lva is None:
        anzahl = session.query(Lva).count()
        lva = Lva(schluessel=nummer or schluessel, nummer=nummer, titel=basis or titel, semester=semester, typ=lva_typ,
                  farbe=STANDARD_FARBEN[anzahl % len(STANDARD_FARBEN)])
        session.add(lva)
        session.flush()
        neue_lva = True
    if lva_typ and not lva.typ:
        lva.typ = lva_typ
    if teil is None:
        teil = next((t for t in lva.teile if t.nummer == nummer and t.gruppe == gruppe), None)
    if teil is None:
        # weitere Gruppe derselben Nummer: Markierungen und TUWEL-Kurs der vorhandenen Gruppe als Vorgabe
        vorlage = geschwister[0] if geschwister else None
        teil = LvaTeil(lva=lva, nummer=nummer, typ=lva_typ or (vorlage.typ if vorlage else None), gruppe=gruppe)
        if vorlage:
            teil.steop, teil.anwesenheitspflicht = vorlage.steop, vorlage.anwesenheitspflicht
            teil.aufzeichnung, teil.tuwel_kurs_id = vorlage.aufzeichnung, vorlage.tuwel_kurs_id
        session.add(teil)
        session.flush()
    if gruppe and not teil.gruppe:
        teil.gruppe = gruppe  # Teil war bisher nur über Termine ohne Gruppenangabe bekannt
    _typ_ergaenzen(teil, lva_typ)
    treffer = TeilTreffer(lva, teil, neue_lva)
    cache[cache_schluessel] = treffer
    return treffer


def _lva_nach_titel(session: Session, schluessel: str, lva_typ: str | None, semester: str) -> Lva | None:
    """Eintrag ohne Nummer (z. B. Kurzform „EP1 VU“): LVA gleichen Titels, bei mehreren die mit passendem Typ."""
    kandidaten = [l for l in session.scalars(select(Lva).where(Lva.semester == semester).order_by(Lva.id))
                  if l.schluessel == schluessel or gruppen_schluessel(l.titel) == schluessel]
    return next((l for l in kandidaten if lva_typ and l.typ == lva_typ), kandidaten[0] if kandidaten else None)


def _passender_teil(geschwister: list[LvaTeil], gruppe: str | None) -> LvaTeil | None:
    """Teil derselben Nummer für einen Termin.

    TISS nennt die Gruppe nicht bei jedem Termin („309.021 UE Mechanik 1 - Gruppe 22“ neben
    „309.021 UE Mechanik 1“ für Plenartermine). Ohne Gruppenangabe gilt daher der vorhandene Teil der
    Nummer, eine Gruppe übernimmt einen noch gruppenlosen Teil; nur eine andere Gruppe ist ein neuer Teil.
    """
    if not geschwister:
        return None
    if gruppe is None:
        return next((t for t in geschwister if t.gruppe is None), geschwister[0])
    gleich = next((t for t in geschwister if t.gruppe == gruppe), None)
    if gleich:
        return gleich
    ohne_gruppe = [t for t in geschwister if t.gruppe is None]
    if ohne_gruppe and not any(t.gruppe for t in geschwister):
        return ohne_gruppe[0]
    return None


def _typ_ergaenzen(teil: LvaTeil, lva_typ: str | None) -> None:
    if lva_typ and not teil.typ:
        teil.typ = lva_typ  # z. B. Teil wurde zuerst über eine Prüfung ohne Typangabe angelegt


def zeitraum_aus_termin(start: datetime, ende: datetime) -> tuple[date, date]:
    """Ganztägige Einträge enden um 0 Uhr des Folgetags; das Ende ist einschließlich."""
    bis = (ende - timedelta(seconds=1)).date() if ende > start else start.date()
    return start.date(), max(bis, start.date())


# --- Einmalige Bereinigung der bestehenden Datenbank -----------------------------------------------

@dataclass
class Bereinigung:
    freie_zeitraeume: list[str] = field(default_factory=list)
    zusammengefasst: list[str] = field(default_factory=list)  # nur noch für alte Berichte
    getrennt: list[str] = field(default_factory=list)
    hinweise: list[str] = field(default_factory=list)
    sicherung: str | None = None


def sicherung_anlegen(datenbank: Path) -> Path:
    """Kopie der SQLite-Datei vor dem Umbau (über die Backup-Schnittstelle, auch bei offener Verbindung)."""
    ziel = datenbank.with_name(f"{datenbank.stem}.vor-lva-umbau-{datetime.now():%Y%m%d-%H%M%S}.db")
    quelle = sqlite3.connect(datenbank)
    try:
        kopie = sqlite3.connect(ziel)
        try:
            quelle.backup(kopie)
        finally:
            kopie.close()
    finally:
        quelle.close()
    return ziel


def _haeufigster_typ(termine: list[Termin]) -> str | None:
    typen = [t.typ for t in termine if t.typ not in (TYP_PRUEFUNG, TYP_ABGABE, "SONSTIGE")]
    return max(set(typen), key=typen.count) if typen else None


def _haeufigste_gruppe(termine: list[Termin]) -> str | None:
    """Gruppe aus den Termintiteln, falls die LVA nach einem Plenartermin ohne Gruppe benannt wurde."""
    gruppen = [g for _, g in (zerlege_gruppe(t.titel) for t in termine) if g]
    return max(set(gruppen), key=gruppen.count) if gruppen else None


def bereinige_datenbank(session: Session) -> Bereinigung:
    """Freie Einträge -> freie Zeiträume; Teile anlegen; Teile derselben LVA zusammenfassen.

    Markierungen wandern auf die Teile, Abweichungen einzelner Termine bleiben unberührt.
    Unterlagen, Lernblöcke und TUWEL-Zuordnungen hängen danach an der gemeinsamen LVA.
    """
    bericht = Bereinigung()

    # 1. Ferien, Feiertage, Rektorstag … sind keine LVAs
    for lva in list(session.scalars(select(Lva))):
        if not ist_freier_eintrag(lva.titel, lva.nummer):
            continue
        abhaengig = (
            session.scalar(select(Dokument.id).where(Dokument.lva_id == lva.id).limit(1))
            or session.scalar(select(Lernblock.id).where(Lernblock.lva_id == lva.id).limit(1))
            or session.scalar(select(TuwelKurs.id).where(TuwelKurs.lva_id == lva.id).limit(1))
        )
        if abhaengig:
            bericht.hinweise.append(f"„{lva.titel}“ sieht frei aus, hat aber Unterlagen oder Lernblöcke – bleibt LVA")
            continue
        for termin in lva.termine:
            von, bis = zeitraum_aus_termin(termin.start, termin.ende)
            if termin.tiss_uid and session.scalar(select(FreierZeitraum).where(FreierZeitraum.tiss_uid == termin.tiss_uid)):
                continue
            session.add(FreierZeitraum(tiss_uid=termin.tiss_uid, bezeichnung=freier_name(lva.titel), von=von, bis=bis))
        bericht.freie_zeitraeume.append(f"{freier_name(lva.titel)} ({lva.semester})")
        session.delete(lva)
    session.flush()

    # 2. Jede bisherige LVA bekommt ihren Teil; die Markierungen ziehen dorthin um
    for lva in session.scalars(select(Lva)):
        if lva.teile:
            continue
        basis, gruppe = zerlege_gruppe(lva.titel)
        gruppe = gruppe or _haeufigste_gruppe(lva.termine)
        teil = LvaTeil(
            lva=lva, nummer=lva.nummer, typ=_haeufigster_typ(lva.termine), gruppe=gruppe,
            steop=lva.steop, anwesenheitspflicht=lva.anwesenheitspflicht, aufzeichnung=lva.aufzeichnung,
            tuwel_kurs_id=lva.tuwel_kurs_id,
        )
        session.add(teil)
        session.flush()
        session.execute(update(Termin).where(Termin.lva_id == lva.id).values(teil_id=teil.id))
        lva.titel = basis or lva.titel  # Schlüssel erst nach dem Zusammenfassen setzen (eindeutig je Semester)
        lva.tuwel_kurs_id = None  # gilt jetzt pro Teil
    session.flush()

    # 3. Früher zusammengefasste LVAs (VO + UE gleichen Titels) wieder trennen: eine LVA je Nummer
    lvas_trennen(session, bericht)

    # 4. Typ und Schlüssel (Nummer, sonst Titel) – so findet der nächste TISS-Import dieselbe LVA wieder
    for lva in session.scalars(select(Lva)):
        if not lva.typ:
            lva.typ = next((t.typ for t in lva.teile if t.typ), None)
        lva.nummer = lva.nummer or next((t.nummer for t in lva.teile if t.nummer), None)
        lva.schluessel = lva.nummer or gruppen_schluessel(lva.titel) or lva.schluessel
    setze_einstellung(session, STRUKTUR_SCHLUESSEL, STRUKTUR_VERSION)
    session.commit()
    return bericht


def _freie_farbe(session: Session, semester: str) -> str:
    belegt = {l.farbe.lower() for l in session.scalars(select(Lva).where(Lva.semester == semester))}
    return next((f for f in STANDARD_FARBEN if f.lower() not in belegt), STANDARD_FARBEN[len(belegt) % len(STANDARD_FARBEN)])


def lvas_trennen(session: Session, bericht: Bereinigung | None = None) -> list[str]:
    """Jede weitere Nummer einer LVA wird eine eigene LVA: Teile, Termine, TUWEL-Kurse und deren Unterlagen ziehen
    mit. ECTS bleiben bei der Haupt-LVA (VO/VU), die neue bekommt Ziel, Regler, Lernwerte und „besuchen“ als Vorgabe.
    Eine gespeicherte STEOP-Variante enthält danach auch die neue LVA."""
    from .lva_auswahl import VARIANTE_SCHLUESSEL

    getrennt = []
    roh = lies_einstellung(session, VARIANTE_SCHLUESSEL)
    variante = json.loads(roh) if roh else None
    for lva in list(session.scalars(select(Lva).order_by(Lva.id))):
        nummern = list(dict.fromkeys(t.nummer for t in lva.teile if t.nummer))
        if len(nummern) < 2:
            continue
        haupt = next((t.nummer for t in lva.teile if t.nummer and t.typ in ("VO", "VU")),
                     lva.nummer if lva.nummer in nummern else nummern[0])
        for nummer in [n for n in nummern if n != haupt]:
            teile = [t for t in lva.teile if t.nummer == nummer]
            kurse = {t.tuwel_kurs_id for t in teile if t.tuwel_kurs_id}
            neu = Lva(
                schluessel=nummer, nummer=nummer, titel=lva.titel, semester=lva.semester, typ=teile[0].typ,
                farbe=_freie_farbe(session, lva.semester), steop=any(t.steop for t in teile),
                anwesenheitspflicht=any(t.anwesenheitspflicht for t in teile), aufzeichnung=any(t.aufzeichnung for t in teile),
                ziel=lva.ziel, bedarf_faktor=lva.bedarf_faktor, lernparameter=lva.lernparameter, besuchen=lva.besuchen,
            )
            session.add(neu)
            session.flush()
            teil_ids = [t.id for t in teile]
            session.execute(update(LvaTeil).where(LvaTeil.id.in_(teil_ids)).values(lva_id=neu.id))
            session.execute(update(Termin).where(Termin.teil_id.in_(teil_ids)).values(lva_id=neu.id))
            if kurse:
                session.execute(update(TuwelKurs).where(TuwelKurs.id.in_(kurse)).values(lva_id=neu.id))
                session.execute(update(Dokument).where(Dokument.lva_id == lva.id, Dokument.tuwel_kurs_id.in_(kurse))
                                .values(lva_id=neu.id))
            if variante and lva.id in variante.get("ids", []):
                variante["ids"].append(neu.id)
            getrennt.append(f"{lva.titel} ({lva.semester}): {neu.typ or ''} {nummer}".replace("  ", " "))
        lva.nummer, lva.schluessel = haupt, haupt
        lva.typ = next((t.typ for t in lva.teile if t.nummer == haupt and t.typ), lva.typ)
        session.flush()
        session.expire(lva)
    if variante and getrennt:
        setze_einstellung(session, VARIANTE_SCHLUESSEL, json.dumps(variante))
    if bericht is not None:
        bericht.getrennt.extend(getrennt)
        if getrennt:
            bericht.hinweise.append("Getrennte LVAs: ECTS der neuen LVAs bitte im Reiter „LVAs“ eintragen.")
    session.flush()
    return getrennt


def braucht_bereinigung(session: Session) -> bool:
    return lies_einstellung(session, STRUKTUR_SCHLUESSEL) != STRUKTUR_VERSION


def beim_start_bereinigen(session_fabrik, url: str) -> Bereinigung | None:
    """Einmalige Bereinigung beim Start; legt vorher eine Sicherungskopie der Datenbankdatei an."""
    import logging

    with session_fabrik() as session:
        if not braucht_bereinigung(session):
            return None
        hat_daten = session.scalar(select(Lva.id).limit(1)) is not None
        sicherung = None
        datei = url.removeprefix("sqlite:///") if url.startswith("sqlite:///") else None
        if hat_daten and datei and datei != ":memory:":
            sicherung = sicherung_anlegen(Path(datei))
        bericht = bereinige_datenbank(session)
        bericht.sicherung = str(sicherung) if sicherung else None
        if hat_daten:
            setze_einstellung(session, "lva_struktur_bericht", json.dumps({
                "zeit": datetime.now().isoformat(timespec="seconds"),
                "freie_zeitraeume": bericht.freie_zeitraeume,
                "zusammengefasst": bericht.zusammengefasst,
                "getrennt": bericht.getrennt,
                "hinweise": bericht.hinweise,
                "sicherung": bericht.sicherung,
            }, ensure_ascii=False))
            session.commit()
            logging.getLogger("studienhub").warning(
                "LVA-Struktur bereinigt: %d freie Zeiträume, %d LVAs getrennt, Sicherung: %s",
                len(bericht.freie_zeitraeume), len(bericht.getrennt), bericht.sicherung,
            )
        return bericht
