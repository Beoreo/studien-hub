"""Prüfungstermine: Übersicht je LVA, eigene Termine, angemeldeten Termin wählen, Import von der Browser-Erweiterung."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..lva_auswahl import lade_auswahl
from ..models import PRUEFUNG_MANUELL, TYP_PRUEFUNG, Lva, Pruefungstermin, Termin, setze_einstellung
from ..planung_service import auswahl_geaendert, lade_regel
from ..pruefungen import (
    UNLESBAR_SCHLUESSEL,
    AbgleichErgebnis,
    abgleichen,
    abruf_liste,
    angemeldet_setzen,
    anmeldestatus,
    feed_pruefungstage,
    ist_angemeldet,
    loeschen,
    sync_status,
    sync_status_speichern,
    termine_der_lva,
)
from ..schemas import (
    AngemeldetWahl,
    PruefungenImport,
    PruefungenLvaOut,
    PruefungenOut,
    PruefungsterminAenderung,
    PruefungsterminNeu,
    PruefungsterminOut,
)
from .tuwel import pruefe_schluessel

router = APIRouter(prefix="/api/pruefungen", tags=["Prüfungen"])

FELDER = ("id", "lva_id", "quelle", "titel", "start", "ende", "ort", "anmeldung_von", "anmeldung_bis", "abmeldung_bis",
          "tiss_angemeldet", "bearbeitet", "notiz")


def termin_out(t: Pruefungstermin, feed_tage: set, jetzt: datetime) -> PruefungsterminOut:
    return PruefungsterminOut(
        **{f: getattr(t, f) for f in FELDER},
        angemeldet=ist_angemeldet(t, feed_tage),
        angemeldet_automatisch=t.angemeldet is None,
        anmeldestatus=anmeldestatus(t.anmeldung_von, t.anmeldung_bis, jetzt),
    )


def lva_out(session: Session, lva: Lva, jetzt: datetime | None = None) -> PruefungenLvaOut:
    jetzt = jetzt or datetime.now()
    feed = feed_pruefungstage(session, lva.id)
    termine = [termin_out(t, feed, jetzt) for t in termine_der_lva(session, lva.id)]
    # Auswahl „Angemeldet“: Termine aus TISS/TUWEL vor eigenen Zusatzterminen (z. B. Zwischentests)
    angemeldet = [t for t in termine if t.angemeldet and t.quelle != PRUEFUNG_MANUELL] or [t for t in termine if t.angemeldet]
    # zuerst der nächste angemeldete Termin, sonst der letzte (vorbei)
    gewaehlt = next((t for t in angemeldet if t.start >= jetzt.replace(hour=0, minute=0, second=0, microsecond=0)),
                    angemeldet[-1] if angemeldet else None)
    tage = {t.start.date() for t in termine}
    ohne_termin = [s for s in session.scalars(
        select(Termin.start).where(Termin.lva_id == lva.id, Termin.typ == TYP_PRUEFUNG).order_by(Termin.start)
    ) if s.date() not in tage]
    regel = lade_regel(session)
    return PruefungenLvaOut(lva_id=lva.id, titel=lva.titel, kurzname=lva.kurzname, typ=lva.typ, farbe=lva.farbe,
                            lernwochen=lva.lernwochen,
                            lernwochen_standard=regel.lernphase_wochen if regel and regel.lernphase_wochen is not None else 2,
                            angemeldet_id=gewaehlt.id if gewaehlt else None, feed_pruefungen=ohne_termin,
                            termine=termine)


def _termin(session: Session, termin_id: int) -> Pruefungstermin:
    termin = session.get(Pruefungstermin, termin_id)
    if termin is None or termin.ausgeblendet:
        raise HTTPException(404, "Prüfungstermin nicht gefunden")
    return termin


def _geaendert(session: Session) -> None:
    """Angemeldete Prüfungen bestimmen den Lernbedarf: Wochen mit Vorschlägen neu planen."""
    session.commit()
    auswahl_geaendert(session)


@router.get("", response_model=PruefungenOut)
def uebersicht(session: Session = Depends(get_session)):
    """Besuchte LVAs des laufenden Semesters mit allen bekannten Prüfungsterminen, dazu der Stand der Importe."""
    auswahl = lade_auswahl(session)
    lvas = [l for l in session.scalars(select(Lva).where(Lva.semester == auswahl.semester).order_by(Lva.titel))
            if auswahl.besucht(l)] if auswahl.semester else []
    jetzt = datetime.now()
    return PruefungenOut(lvas=[lva_out(session, l, jetzt) for l in lvas], sync=sync_status(session))


@router.post("", response_model=PruefungsterminOut, status_code=201)
def anlegen(daten: PruefungsterminNeu, session: Session = Depends(get_session)):
    """Eigener Termin (z. B. Zwischentest, Termin, den weder TISS noch TUWEL kennt)."""
    if session.get(Lva, daten.lva_id) is None:
        raise HTTPException(404, "LVA nicht gefunden")
    termin = Pruefungstermin(quelle=PRUEFUNG_MANUELL, **daten.model_dump())
    session.add(termin)
    _geaendert(session)
    return termin_out(termin, feed_pruefungstage(session, termin.lva_id), datetime.now())


@router.patch("/{termin_id}", response_model=PruefungsterminOut)
def aendern(termin_id: int, daten: PruefungsterminAenderung, session: Session = Depends(get_session)):
    termin = _termin(session, termin_id)
    werte = daten.model_dump(exclude_unset=True)
    if "titel" in werte and werte["titel"] is None:
        del werte["titel"]
    if "start" in werte and werte["start"] is None:
        raise HTTPException(422, "Beginn fehlt")
    zeiten_alt = (termin.start, termin.ende)
    for feld, wert in werte.items():
        setattr(termin, feld, wert)
    if termin.ende is not None and termin.ende <= termin.start:
        session.rollback()
        raise HTTPException(422, "Ende muss nach dem Beginn liegen")
    if termin.quelle != PRUEFUNG_MANUELL and (termin.start, termin.ende) != zeiten_alt:
        termin.bearbeitet = True  # der nächste Import überschreibt die eigenen Zeiten nicht
    _geaendert(session)
    return termin_out(termin, feed_pruefungstage(session, termin.lva_id), datetime.now())


@router.delete("/{termin_id}", status_code=204)
def entfernen(termin_id: int, session: Session = Depends(get_session)):
    """Eigene Termine werden gelöscht, importierte ausgeblendet (der Import holt sie nicht zurück)."""
    loeschen(session, _termin(session, termin_id))
    _geaendert(session)
    return Response(status_code=204)


@router.put("/lva/{lva_id}/angemeldet", response_model=PruefungenLvaOut)
def angemeldet_waehlen(lva_id: int, daten: AngemeldetWahl, session: Session = Depends(get_session)):
    """Auswahl „Angemeldet“: genau ein Termin der LVA, keiner oder wieder automatisch (nach TISS)."""
    lva = session.get(Lva, lva_id)
    if lva is None:
        raise HTTPException(404, "LVA nicht gefunden")
    try:
        angemeldet_setzen(session, lva, daten.termin_id, daten.automatisch)
    except ValueError as fehler:
        raise HTTPException(422, str(fehler)) from fehler
    _geaendert(session)
    return lva_out(session, lva)


# --- Browser-Erweiterung -----------------------------------------------------------------------------

@router.get("/abruf", dependencies=[Depends(pruefe_schluessel)])
def abruf(session: Session = Depends(get_session)):
    """Welche TISS-Prüfungslisten und TUWEL-Kurse die Erweiterung lesen soll."""
    return {"lvas": abruf_liste(session)}


@router.post("/sync", dependencies=[Depends(pruefe_schluessel)])
def sync(daten: PruefungenImport, session: Session = Depends(get_session)):
    """Termine einer Quelle (TISS-Prüfungslisten oder TUWEL-Kalender) übernehmen."""
    gesamt = AbgleichErgebnis(fehler=list(daten.fehler))
    termine = 0
    for eintrag in daten.lvas:
        if session.get(Lva, eintrag.lva_id) is None:
            gesamt.fehler.append(f"LVA {eintrag.lva_id} ist dem Hub nicht bekannt")
            continue
        e = abgleichen(session, daten.quelle, eintrag.lva_id, [t.model_dump() for t in eintrag.termine], eintrag.vollstaendig)
        gesamt.neu, gesamt.geaendert = gesamt.neu + e.neu, gesamt.geaendert + e.geaendert
        gesamt.entfernt, gesamt.unveraendert = gesamt.entfernt + e.entfernt, gesamt.unveraendert + e.unveraendert
        termine += len(eintrag.termine)
    if daten.unlesbar_html:
        setze_einstellung(session, UNLESBAR_SCHLUESSEL, daten.unlesbar_html)
    sync_status_speichern(session, daten.quelle, gesamt, len(daten.lvas), termine)
    session.commit()
    neu_geplant = auswahl_geaendert(session) if gesamt.etwas_geaendert else []
    return {"neu": gesamt.neu, "geaendert": gesamt.geaendert, "entfernt": gesamt.entfernt,
            "unveraendert": gesamt.unveraendert, "fehler": gesamt.fehler, "neu_geplante_wochen": neu_geplant}
