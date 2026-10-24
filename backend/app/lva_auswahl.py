"""Welche LVAs dieses Semester besucht werden – nach dem STEOP-Status.

Der STEOP-Status kommt aus TISS (Seite „STEOP Status“, gelesen von der Browser-Erweiterung) oder wird
im Reiter „LVAs“ von Hand gesetzt. Eine LVA gilt als STEOP-LVA, wenn sie selbst oder einer ihrer Teile als
STEOP markiert ist oder TISS ihre Nummer in den offenen STEOP-Kriterien nennt.

Solange die STEOP offen ist, müssen nicht alle STEOP-LVAs sofort gemacht werden. TISS nennt die Kriterien als Baum
(„P4: 9 ECTS aus:“ → „1 aus:“, „Alle aus:“ …); daraus wird eine Variante gewählt, die die Kriterien mit möglichst
wenig ECTS erfüllt (`steop_kriterien.variante_waehlen`). Ohne Kriterien aus TISS gehören alle STEOP-LVAs dazu.
Dazu kommen Nicht-STEOP-LVAs bis zu den erlaubten Non-STEOP-ECTS (aus TISS oder von Hand). Es gilt immer genau eine
**Variante** (Menge von LVA-IDs des laufenden Semesters):
- ungespeichert wird sie bei jedem Lesen neu erzeugt (folgt also neuen LVAs, Markierungen und TISS-Ständen),
- sobald sie bearbeitet wird, ist sie gespeichert (`steop_variante`) und bleibt so, bis sie neu erzeugt wird
  oder die erlaubten ECTS sich ändern.

Nach Abschluss der STEOP werden alle LVAs besucht. `Lva.besuchen` überschreibt das je LVA: True = manuell
eingeblendet, False = manuell ausgeblendet, None = automatisch. Ausgeblendete LVAs erscheinen nicht im Kalender
und Export, ihre Termine sperren keine Arbeitszeit und sie bekommen keine Lernzeit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import steop_kriterien
from .models import Lva, lies_einstellung, setze_einstellung

STEOP_SCHLUESSEL = "steop_abgeschlossen"
TISS_SCHLUESSEL = "steop_tiss"  # letzter Stand aus TISS (JSON)
TISS_HTML_SCHLUESSEL = "steop_tiss_html"  # Rohfassung der Detailansicht (nur zur Prüfung)
QUELLE_SCHLUESSEL = "steop_quelle"  # tiss | manuell
ERLAUBTE_ECTS_SCHLUESSEL = "steop_erlaubte_ects"  # von Hand; leer = Wert aus TISS
VARIANTE_SCHLUESSEL = "steop_variante"  # bearbeitete Variante (JSON: semester, ids)


def steop_abgeschlossen(session: Session) -> bool:
    return lies_einstellung(session, STEOP_SCHLUESSEL) == "ja"


def setze_steop_abgeschlossen(session: Session, abgeschlossen: bool, quelle: str = "manuell") -> None:
    setze_einstellung(session, STEOP_SCHLUESSEL, "ja" if abgeschlossen else "nein")
    setze_einstellung(session, QUELLE_SCHLUESSEL, quelle)


def tiss_stand(session: Session) -> dict | None:
    roh = lies_einstellung(session, TISS_SCHLUESSEL)
    return json.loads(roh) if roh else None


def kriterien_zusammenfuehren(neu: list[dict], alt: list[dict]) -> list[dict]:
    """Ein zugeklapptes P-Kriterium (ohne LVAs, z. B. beim Abruf im Hintergrund) behält die zuletzt gesehenen LVAs."""
    if not neu:
        return alt
    alte = {k.get("name"): k for k in alt if k.get("name")}
    return [
        k if steop_kriterien.hat_lvas(k) or not steop_kriterien.hat_lvas(alte.get(k.get("name"), {}))
        else {**k, "kinder": alte[k["name"]]["kinder"]}
        for k in neu
    ]


def steop_aus_tiss_speichern(session: Session, daten: dict) -> bool:
    """Speichert den Stand aus TISS. Nur ein sicher erkannter Status (nicht None) ändert die Auswahl."""
    daten = dict(daten)
    detail_html = daten.pop("detail_html", None)
    if detail_html:  # Rohfassung zur Prüfung des Aufbaus – die letzte und die letzte mit LVAs
        setze_einstellung(session, TISS_HTML_SCHLUESSEL + "_letzt", detail_html)
        if any(steop_kriterien.hat_lvas(k) for k in daten.get("kriterien") or []):
            setze_einstellung(session, TISS_HTML_SCHLUESSEL, detail_html)
    stand = {**daten, "zeit": datetime.now().isoformat(timespec="seconds")}
    alt = tiss_stand(session)
    if alt and stand.get("abgeschlossen") is False:
        # Detailansicht nicht aufgeklappt: die zuletzt gesehenen STEOP-LVAs und Kriterien behalten
        if not stand.get("steop_nummern") and alt.get("steop_nummern"):
            stand["steop_nummern"] = alt["steop_nummern"]
        if alt.get("kriterien"):
            if not stand.get("kriterien"):
                stand["verknuepfung"] = alt.get("verknuepfung", "AND")
            stand["kriterien"] = kriterien_zusammenfuehren(stand.get("kriterien") or [], alt["kriterien"])
    setze_einstellung(session, TISS_SCHLUESSEL, json.dumps(stand, ensure_ascii=False))
    if daten.get("abgeschlossen") is None:
        return False
    setze_steop_abgeschlossen(session, bool(daten["abgeschlossen"]), quelle="tiss")
    return True


def tiss_kriterien(session: Session) -> tuple[list[dict], str]:
    """Kriterienbaum der offenen STEOP aus TISS und die Verknüpfung der obersten Ebene (AND | OR)."""
    stand = tiss_stand(session)
    if not stand or stand.get("abgeschlossen"):
        return [], "AND"
    return stand.get("kriterien") or [], stand.get("verknuepfung") or "AND"


def tiss_steop_nummern(session: Session) -> frozenset[str]:
    stand = tiss_stand(session)
    if not stand or stand.get("abgeschlossen"):
        return frozenset()
    return frozenset(stand.get("steop_nummern") or []) | steop_kriterien.nummern(stand.get("kriterien") or [])


def lva_nummern(lva: Lva) -> set[str]:
    return {n for n in [lva.nummer, *(t.nummer for t in lva.teile)] if n}


def ist_steop_lva(lva: Lva, tiss_nummern: frozenset[str] = frozenset()) -> bool:
    if lva.steop or any(t.steop for t in lva.teile):
        return True
    return bool(lva_nummern(lva) & tiss_nummern)


# --- Einstellungen der Variante -------------------------------------------------------------------

def erlaubte_ects(session: Session) -> tuple[float | None, str | None]:
    """Erlaubte Non-STEOP-ECTS und woher sie kommen (manuell | tiss | None)."""
    roh = lies_einstellung(session, ERLAUBTE_ECTS_SCHLUESSEL)
    if roh:
        return float(roh), "manuell"
    tiss = tiss_stand(session)
    if tiss and tiss.get("erlaubte_ects") is not None:
        return float(tiss["erlaubte_ects"]), "tiss"
    return None, None


def setze_erlaubte_ects(session: Session, wert: float | None) -> None:
    """Erlaubte ECTS von Hand (None = aus TISS); eine bearbeitete Variante wird verworfen."""
    setze_einstellung(session, ERLAUBTE_ECTS_SCHLUESSEL, None if wert is None else str(float(wert)))
    variante_verwerfen(session)


# --- Variante: reine Logik ------------------------------------------------------------------------

@dataclass(frozen=True)
class Kandidat:
    id: int
    titel: str
    ects: float | None
    ist_steop: bool


def auffuellen(kandidaten: list[Kandidat], erlaubte_ects: float | None) -> set[int]:
    """Nicht-STEOP-LVAs, die das erlaubte ECTS-Budget möglichst voll ausschöpfen (meiste ECTS zuerst; bei
    Gleichstand die zuerst gefundene Auswahl). LVAs ohne ECTS-Angabe bleiben draußen (Budget nicht prüfbar)."""
    budget = round((erlaubte_ects or 0) * 10)  # Zehntel-ECTS
    andere = sorted((k for k in kandidaten if not k.ist_steop and k.ects), key=lambda k: (-k.ects, k.titel, k.id))
    beste: dict[int, tuple[int, ...]] = {0: ()}
    for k in andere:
        gewicht = round(k.ects * 10)
        for summe, auswahl in sorted(beste.items(), reverse=True):
            neu = summe + gewicht
            if neu <= budget and neu not in beste:
                beste[neu] = auswahl + (k.id,)
    return set(beste[max(beste)])


# --- Variante: Datenbank --------------------------------------------------------------------------

def semester_am(tag: date) -> str:
    """TU-Semester eines Tages: Wintersemester ab August (Vorbereitung) bis Februar, sonst Sommersemester."""
    if tag.month >= 8:
        return f"{tag.year}W"
    if tag.month <= 2:
        return f"{tag.year - 1}W"
    return f"{tag.year}S"


def aktuelles_semester(session: Session, heute: date | None = None) -> str | None:
    """Das laufende Semester, wenn es LVAs hat; sonst das nächste mit LVAs, sonst das letzte."""
    vorhanden = sorted(s for s in session.scalars(select(Lva.semester).distinct()) if s)
    if not vorhanden:
        return None
    jetzt = semester_am(heute or date.today())
    return next((s for s in vorhanden if s >= jetzt), vorhanden[-1])


def gespeicherte_variante(session: Session, semester: str | None) -> set[int] | None:
    roh = lies_einstellung(session, VARIANTE_SCHLUESSEL)
    if not roh:
        return None
    daten = json.loads(roh)
    return set(daten["ids"]) if daten.get("semester") == semester else None


def variante_verwerfen(session: Session) -> None:
    setze_einstellung(session, VARIANTE_SCHLUESSEL, None)


def _speichern(session: Session, semester: str | None, ids: set[int]) -> None:
    setze_einstellung(session, VARIANTE_SCHLUESSEL, json.dumps({"semester": semester, "ids": sorted(ids)}))


_WAHL_CACHE: dict[str, set[int]] = {}  # gleiche Kriterien + gleiches Angebot = gleiche Wahl (wird oft gelesen)


def _steop_wahl(kriterien: list[dict], verknuepfung: str, angebot: dict[int, set[str]],
                ects: dict[int, float | None]) -> set[int]:
    schluessel = json.dumps([kriterien, verknuepfung, sorted((i, sorted(n)) for i, n in angebot.items()),
                             sorted(ects.items())], sort_keys=True)
    if schluessel not in _WAHL_CACHE:
        if len(_WAHL_CACHE) > 64:
            _WAHL_CACHE.clear()
        _WAHL_CACHE[schluessel] = steop_kriterien.variante_waehlen(kriterien, verknuepfung, angebot, ects)
    return set(_WAHL_CACHE[schluessel])


@dataclass
class Auswahl:
    """Alles, was zur Entscheidung „wird besucht“ nötig ist – einmal geladen, für viele LVAs."""

    fertig: bool
    nummern: frozenset[str] = frozenset()
    semester: str | None = None
    variante: set[int] = field(default_factory=set)
    bearbeitet: bool = False
    kriterien: list[dict] = field(default_factory=list)
    verknuepfung: str = "AND"
    angebot: dict[int, set[str]] = field(default_factory=dict)  # LVA-ID -> Blatt-Schlüssel, laufendes Semester
    ects: dict[int, float | None] = field(default_factory=dict)
    steop_ids: set[int] = field(default_factory=set)  # über den Titel einem Kriterium zugeordnet

    def ist_steop(self, lva: Lva) -> bool:
        return lva.id in self.steop_ids or ist_steop_lva(lva, self.nummern)

    def besucht(self, lva: Lva) -> bool:
        if self.fertig:
            return True if lva.besuchen is None else lva.besuchen
        return lva.id in self.variante


def lade_auswahl(session: Session) -> Auswahl:
    fertig, nummern, semester = steop_abgeschlossen(session), tiss_steop_nummern(session), aktuelles_semester(session)
    if fertig:
        return Auswahl(fertig=True, nummern=nummern, semester=semester)
    kriterien, verknuepfung = tiss_kriterien(session)
    lvas = session.scalars(select(Lva).where(Lva.semester == semester)).all()
    angebot = steop_kriterien.zuordnen(kriterien, [(l.id, l.titel, lva_nummern(l), l.typ) for l in lvas])
    blatt_schluessel = {steop_kriterien.schluessel(b) for b in steop_kriterien.blaetter(kriterien)}
    auswahl = Auswahl(False, nummern, semester, kriterien=kriterien, verknuepfung=verknuepfung, angebot=angebot,
                      ects={l.id: l.ects for l in lvas},
                      steop_ids={i for i, s in angebot.items() if s & blatt_schluessel})
    gespeichert = gespeicherte_variante(session, semester)
    if gespeichert is not None:
        auswahl.variante, auswahl.bearbeitet = gespeichert, True
        return auswahl
    kandidaten = [Kandidat(l.id, l.titel, l.ects, auswahl.ist_steop(l)) for l in lvas]
    if kriterien:
        steop = _steop_wahl(kriterien, verknuepfung, angebot, auswahl.ects)
    else:  # ohne Kriterien aus TISS: alle STEOP-LVAs
        steop = {k.id for k in kandidaten if k.ist_steop}
    auswahl.variante = steop | auffuellen(kandidaten, erlaubte_ects(session)[0])
    return auswahl


def variante_aendern(session: Session, lva_id: int, enthalten: bool) -> None:
    """Eine LVA in die Variante aufnehmen oder herausnehmen; die Variante gilt danach als bearbeitet."""
    auswahl = lade_auswahl(session)
    ids = set(auswahl.variante)
    if enthalten:
        ids.add(lva_id)
    else:
        ids.discard(lva_id)
    _speichern(session, auswahl.semester, ids)


def besuchte_lva_ids(session: Session) -> set[int]:
    auswahl = lade_auswahl(session)
    return {lva.id for lva in session.scalars(select(Lva)) if auswahl.besucht(lva)}


def ausgeblendete_lva_ids(session: Session) -> set[int]:
    return {lva.id for lva in session.scalars(select(Lva))} - besuchte_lva_ids(session)
