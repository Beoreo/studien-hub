"""Prüfungstermine je LVA: Import aus TISS (Prüfungsliste) und TUWEL (Kurskalender), eigene Termine, Anmeldung.

Der TISS-iCal-Feed enthält nur Prüfungen, zu denen man schon angemeldet ist. Die Browser-Erweiterung liest deshalb
zusätzlich die Prüfungslisten (alle angebotenen Termine mit Anmeldefrist) und den TUWEL-Kalender. Je LVA gilt ein
Termin als angemeldet, wenn man ihn selbst gewählt hat – sonst automatisch, wenn TISS es meldet oder der Feed am
selben Tag eine Prüfung hat. Für den Lernbedarf zählen die angemeldeten Termine (lernaufwand.pruefungstermine).
"""

import json
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .lva_auswahl import lade_auswahl, lva_nummern
from .models import (
    PRUEFUNG_MANUELL,
    PRUEFUNG_TISS,
    PRUEFUNG_TUWEL,
    TYP_PRUEFUNG,
    Lva,
    Pruefungstermin,
    Termin,
    TuwelKurs,
    lies_einstellung,
    setze_einstellung,
)

QUELLEN = (PRUEFUNG_TISS, PRUEFUNG_TUWEL)
SYNC_SCHLUESSEL = "pruefungen_sync_{quelle}"  # letzter Lauf je Quelle (JSON) für die Oberfläche
UNLESBAR_SCHLUESSEL = "pruefungen_tiss_unlesbar"  # Rohfassung einer Seite, aus der nichts gelesen wurde
# Zeiten, die der Import nur bei nicht selbst bearbeiteten Terminen überschreibt
ZEITFELDER = ("start", "ende")
FELDER = ("titel", "ort", "anmeldung_von", "anmeldung_bis", "abmeldung_bis")


# --- reine Logik ---------------------------------------------------------------------------------

def anmeldestatus(von: datetime | None, bis: datetime | None, jetzt: datetime) -> str | None:
    """„bald“ vor Beginn der Anmeldung, „offen“ während, „vorbei“ danach; None ohne bekannte Frist."""
    if von is None and bis is None:
        return None
    if von is not None and jetzt < von:
        return "bald"
    if bis is not None and jetzt > bis:
        return "vorbei"
    return "offen"


def naechstes_semester(semester: str) -> str:
    """2026W → 2027S, 2027S → 2027W."""
    jahr, art = int(semester[:4]), semester[4:]
    return f"{jahr + 1}S" if art == "W" else f"{jahr}W"


def ist_angemeldet(termin: Pruefungstermin, feed_tage: set[date]) -> bool:
    if termin.angemeldet is not None:
        return termin.angemeldet
    return termin.tiss_angemeldet or termin.start.date() in feed_tage


# --- Lesen -----------------------------------------------------------------------------------------

def feed_pruefungstage(session: Session, lva_id: int) -> set[date]:
    """Tage mit einer Prüfung aus dem TISS-Feed (dort stehen nur angemeldete Prüfungen)."""
    starts = session.scalars(select(Termin.start).where(Termin.lva_id == lva_id, Termin.typ == TYP_PRUEFUNG))
    return {s.date() for s in starts}


def termine_der_lva(session: Session, lva_id: int) -> list[Pruefungstermin]:
    """Sichtbare Termine, sortiert. Ein TUWEL-Termin am Tag eines TISS-Termins ist derselbe und fällt weg."""
    termine = list(session.scalars(
        select(Pruefungstermin)
        .where(Pruefungstermin.lva_id == lva_id, Pruefungstermin.ausgeblendet.is_(False))
        .order_by(Pruefungstermin.start, Pruefungstermin.id)
    ))
    tiss_tage = {t.start.date() for t in termine if t.quelle == PRUEFUNG_TISS}
    return [t for t in termine if not (t.quelle == PRUEFUNG_TUWEL and t.start.date() in tiss_tage)]


def angemeldete_termine(session: Session, lva_id: int) -> list[Pruefungstermin]:
    feed = feed_pruefungstage(session, lva_id)
    return [t for t in termine_der_lva(session, lva_id) if ist_angemeldet(t, feed)]


# --- Ändern ----------------------------------------------------------------------------------------

def angemeldet_setzen(session: Session, lva: Lva, termin_id: int | None, automatisch: bool = False) -> None:
    """Auswahl „Angemeldet“: genau dieser Termin (oder keiner); alle anderen der LVA gelten als nicht angemeldet.
    `automatisch` hebt die eigene Wahl auf: dann zählt wieder, was TISS meldet."""
    termine = list(session.scalars(select(Pruefungstermin).where(Pruefungstermin.lva_id == lva.id)))
    if termin_id is not None and termin_id not in {t.id for t in termine}:
        raise ValueError("Termin gehört nicht zu dieser LVA")
    for t in termine:
        t.angemeldet = None if automatisch else t.id == termin_id


def loeschen(session: Session, termin: Pruefungstermin) -> None:
    """Eigene Termine verschwinden; importierte werden nur ausgeblendet, damit der nächste Import sie nicht zurückholt."""
    if termin.quelle == PRUEFUNG_MANUELL:
        session.delete(termin)
    else:
        termin.ausgeblendet = True
        termin.angemeldet = False


# --- Import von der Browser-Erweiterung ----------------------------------------------------------

@dataclass
class AbgleichErgebnis:
    neu: int = 0
    geaendert: int = 0
    entfernt: int = 0
    unveraendert: int = 0
    fehler: list[str] = field(default_factory=list)

    @property
    def etwas_geaendert(self) -> bool:
        return bool(self.neu or self.geaendert or self.entfernt)


def _uebernehmen(termin: Pruefungstermin, daten: dict) -> bool:
    felder = FELDER + (() if termin.bearbeitet else ZEITFELDER)
    geaendert = False
    for feld in felder:
        if feld in daten and getattr(termin, feld) != daten[feld]:
            setattr(termin, feld, daten[feld])
            geaendert = True
    angemeldet = bool(daten.get("angemeldet"))
    if termin.tiss_angemeldet != angemeldet:
        termin.tiss_angemeldet = angemeldet
        geaendert = True
    return geaendert


def abgleichen(session: Session, quelle: str, lva_id: int, termine: list[dict], vollstaendig: bool = True,
               jetzt: datetime | None = None) -> AbgleichErgebnis:
    """Termine einer LVA aus einer Quelle übernehmen (Schlüssel: `extern_id`). Ist die Liste vollständig, fallen
    nicht mehr gemeldete Termine weg – außer selbst bearbeitete und angemeldete; eine Anmeldung wandert auf einen
    neuen Termin am selben Tag (TISS hat die Uhrzeit geändert)."""
    jetzt = jetzt or datetime.now()
    ergebnis = AbgleichErgebnis()
    vorhanden = {t.extern_id: t for t in session.scalars(
        select(Pruefungstermin).where(Pruefungstermin.quelle == quelle, Pruefungstermin.lva_id == lva_id))}
    gesehen: dict[str, Pruefungstermin] = {}
    for daten in termine:
        extern_id = daten["extern_id"]
        if extern_id in gesehen:
            continue
        termin = vorhanden.get(extern_id)
        if termin is None:
            # dieselbe Kennung kann in einer anderen LVA stecken (z. B. nach Zusammenlegen): dorthin nicht doppelt
            termin = session.scalar(select(Pruefungstermin).where(
                Pruefungstermin.quelle == quelle, Pruefungstermin.extern_id == extern_id))
        if termin is None:
            termin = Pruefungstermin(lva_id=lva_id, quelle=quelle, extern_id=extern_id, start=daten["start"])
            session.add(termin)
            _uebernehmen(termin, daten)
            ergebnis.neu += 1
        elif _uebernehmen(termin, daten):
            ergebnis.geaendert += 1
        else:
            ergebnis.unveraendert += 1
        termin.zuletzt_gesehen = jetzt
        gesehen[extern_id] = termin

    if vollstaendig:
        for extern_id, termin in vorhanden.items():
            if extern_id in gesehen or termin.bearbeitet:
                continue
            if termin.angemeldet:
                nachfolger = next((n for n in gesehen.values() if n.start.date() == termin.start.date()), None)
                if nachfolger is None:
                    continue  # angemeldet und ohne Ersatz: lieber behalten als die Anmeldung verlieren
                nachfolger.angemeldet = True
            session.delete(termin)
            ergebnis.entfernt += 1
    session.flush()
    return ergebnis


def sync_status_speichern(session: Session, quelle: str, ergebnis: AbgleichErgebnis, lvas: int, termine: int,
                          jetzt: datetime | None = None) -> None:
    setze_einstellung(session, SYNC_SCHLUESSEL.format(quelle=quelle), json.dumps({
        "zeit": (jetzt or datetime.now()).isoformat(timespec="seconds"), "lvas": lvas, "termine": termine,
        "neu": ergebnis.neu, "geaendert": ergebnis.geaendert, "entfernt": ergebnis.entfernt, "fehler": ergebnis.fehler,
    }))


def sync_status(session: Session) -> dict[str, dict | None]:
    status = {}
    for quelle in QUELLEN:
        roh = lies_einstellung(session, SYNC_SCHLUESSEL.format(quelle=quelle))
        status[quelle] = json.loads(roh) if roh else None
    return status


def tuwel_kurse_der_lva(session: Session, lva: Lva) -> set[int]:
    kurse = {k for k in [lva.tuwel_kurs_id, *(t.tuwel_kurs_id for t in lva.teile)] if k}
    kurse |= set(session.scalars(select(TuwelKurs.id).where(TuwelKurs.lva_id == lva.id)))
    return kurse


def abruf_liste(session: Session) -> list[dict]:
    """Was die Erweiterung holen soll: je besuchter LVA des laufenden Semesters die LVA-Nummern (TISS-Prüfungsliste,
    dieses und nächstes Semester – Prüfungen liegen oft danach) und die TUWEL-Kurse."""
    auswahl = lade_auswahl(session)
    if auswahl.semester is None:
        return []
    liste = []
    for lva in session.scalars(select(Lva).where(Lva.semester == auswahl.semester).order_by(Lva.titel)):
        if not auswahl.besucht(lva):
            continue
        # VO/VU zuerst: dort hängen die Prüfungen; Übungsgruppen haben meist keine Prüfungsliste
        teile = sorted(lva.teile, key=lambda t: (t.typ not in ("VO", "VU"), t.id))
        nummern = list(dict.fromkeys(n for n in [*(t.nummer for t in teile), *sorted(lva_nummern(lva))] if n))
        liste.append({
            "lva_id": lva.id, "name": lva.anzeigename, "nummern": nummern,
            "semester": [lva.semester, naechstes_semester(lva.semester)],
            "tuwel_kurse": sorted(tuwel_kurse_der_lva(session, lva)),
        })
    return liste
