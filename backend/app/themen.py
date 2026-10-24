"""Themen je LVA, Wissensstand und Lernereignisse (Stufe 4) – DB-Seite zu wissensstand.py.

Themen kommen aus der Kapitelstruktur der Skripte (oberste Ebene der Gliederung). Gibt es kein Skript mit
Gliederung, dienen die Foliensätze als Themen. Eigene Themen (manuell) bleiben beim erneuten Ableiten
erhalten, ebenso der Wissensstand. Jedes Thema ist mit seinen Abschnitten verknüpft: über das Kapitel und
über die Suche nach dem Thementitel.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .embedding import Embedder
from .lernaufwand import pruefungen, pruefungstermine
from .models import Abschnitt, Dokument, Lernereignis, Lva, Notiz, Pruefungsstoff, Termin, Thema, Wissensstand
from .pruefungsstoff import zeitabschnitte
from .suche import suchen
from .wissensstand import STUFEN, faellig, naechste_wiederholung, neue_stufe


def umlaute_reparieren(text: str) -> str:
    """„GÃ¼termarkt“ -> „Gütermarkt“ (UTF-8, das als Latin-1 gelesen wurde – kommt in Dateinamen vor)."""
    if "Ã" not in text and "Â" not in text:
        return text
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def titel_aus_kapitel(kapitel: str) -> str:
    """„2 Statik starrer Körper“ -> „Statik starrer Körper“."""
    kapitel = umlaute_reparieren(kapitel)
    return re.sub(r"^\s*(kapitel\s+)?\d+(\.\d+)*\.?\s*[:\-–]?\s*", "", kapitel, flags=re.I).strip() or kapitel.strip()


def _kapitel_der_skripte(session: Session, lva_id: int) -> list[str]:
    """Kapitel (oberste Ebene) des Skripts mit der reichsten Gliederung, in Reihenfolge."""
    zeilen = session.execute(
        select(Abschnitt.dokument_id, Abschnitt.kapitel, Abschnitt.reihenfolge, Dokument.lernart)
        .join(Dokument, Dokument.id == Abschnitt.dokument_id)
        .where(Abschnitt.lva_id == lva_id, Abschnitt.kapitel.is_not(None), Abschnitt.offiziell.is_(True))
        .order_by(Abschnitt.dokument_id, Abschnitt.reihenfolge)
    ).all()
    je_dokument: dict[int, list[str]] = {}
    lernart: dict[int, str | None] = {}
    for dok_id, kapitel, _, art in zeilen:
        liste = je_dokument.setdefault(dok_id, [])
        if kapitel not in liste:
            liste.append(kapitel)
        lernart[dok_id] = art
    if not je_dokument:
        return []
    # Skripte vor Folien, dann die meisten Kapitel
    beste = max(je_dokument, key=lambda d: (lernart[d] == "skript", len(je_dokument[d])))
    return je_dokument[beste] if len(je_dokument[beste]) >= 2 else []


def themen_ableiten(session: Session, lva: Lva, embedder: Embedder | None = None) -> list[Thema]:
    """Legt fehlende Themen aus der Kapitelstruktur an; vorhandene (auch eigene) bleiben unverändert."""
    kapitel = _kapitel_der_skripte(session, lva.id)
    if not kapitel:  # kein Skript mit Gliederung: Foliensätze als Themen
        kapitel = [d.dateiname.rsplit(".", 1)[0] for d in session.scalars(
            select(Dokument).where(Dokument.lva_id == lva.id, Dokument.lernart == "folien", Dokument.quelle != "mbcloud")
            .order_by(Dokument.erschienen_am.nulls_last(), Dokument.dateiname))]
    vorhanden = {t.kapitel or t.titel for t in session.scalars(select(Thema).where(Thema.lva_id == lva.id))}
    reihenfolge = (session.scalar(select(func.max(Thema.reihenfolge)).where(Thema.lva_id == lva.id)) or 0)
    neue = []
    for k in kapitel:
        if k in vorhanden:
            continue
        reihenfolge += 1
        thema = Thema(lva_id=lva.id, titel=titel_aus_kapitel(k)[:300], kapitel=k[:300], reihenfolge=reihenfolge, quelle="auto")
        session.add(thema)
        neue.append(thema)
    session.flush()
    for thema in session.scalars(select(Thema).where(Thema.lva_id == lva.id)):
        abschnitte_verknuepfen(session, thema, embedder)
    session.commit()
    return neue


def abschnitte_verknuepfen(session: Session, thema: Thema, embedder: Embedder | None, anzahl: int = 8) -> None:
    """Abschnitte des gleichnamigen Kapitels plus die besten Suchtreffer zum Thementitel."""
    gefunden = []
    if thema.kapitel:
        gefunden += list(session.scalars(select(Abschnitt).where(Abschnitt.lva_id == thema.lva_id, Abschnitt.kapitel == thema.kapitel)))
    gefunden += [t.abschnitt for t in suchen(session, thema.titel, thema.lva_id, anzahl, embedder)]
    thema.abschnitte = list({a.id: a for a in gefunden}.values())


def _stand(session: Session, thema: Thema) -> Wissensstand:
    stand = session.get(Wissensstand, thema.id)
    if stand is None:
        stand = Wissensstand(thema_id=thema.id, stufe=0)
        session.add(stand)
        session.flush()
    return stand


def naechste_pruefung(session: Session, lva_id: int, heute: date) -> date | None:
    zeitpunkte = pruefungen(session, session.get(Lva, lva_id))
    return next((z.date() for z in zeitpunkte if z.date() >= heute), None)


def ereignis_eintragen(session: Session, thema: Thema, art: str, ergebnis: float | None = None, notiz: str | None = None,
                       quelle: str = "hub", heute: date | None = None, stufe: int | None = None) -> Lernereignis:
    """Protokolliert ein Lernereignis und passt Stufe und nächste Wiederholung an.

    Selbsteinschätzung setzt die Stufe direkt (`stufe`), alle anderen Arten leiten sie aus `ergebnis` (0–1) ab.
    """
    heute = heute or date.today()
    stand = _stand(session, thema)
    vorher = stand.stufe
    if stufe is not None:
        stand.stufe = max(0, min(int(stufe), 4))
    elif ergebnis is not None:
        stand.stufe = neue_stufe(stand.stufe, ergebnis)
    stand.letzte_uebung = heute
    stand.naechste_wiederholung = naechste_wiederholung(stand.stufe, heute, naechste_pruefung(session, thema.lva_id, heute))
    ereignis = Lernereignis(lva_id=thema.lva_id, thema_id=thema.id, art=art, ergebnis=ergebnis, notiz=notiz, quelle=quelle,
                            stufe_vorher=vorher, stufe_nachher=stand.stufe,
                            zeitpunkt=datetime.combine(heute, datetime.now().time()))
    session.add(ereignis)
    session.commit()
    return ereignis


# --- Prüfungsstoff: Themen je Prüfung ------------------------------------------------------------------

def hat_lernstand(session: Session, thema: Thema) -> bool:
    stand = session.get(Wissensstand, thema.id)
    return bool(stand and stand.stufe) or session.scalar(
        select(Lernereignis.id).where(Lernereignis.thema_id == thema.id).limit(1)) is not None


def stoff_uebernehmen(session: Session, lva: Lva, pruefung_am: date, titel: list[str],
                      embedder: Embedder | None = None) -> dict[str, int]:
    """Die Themen der Prüfung sind danach genau `titel`: vorhandene gleichen Namens werden zugeordnet (Lernstand
    bleibt), fehlende angelegt. Themen, die nicht mehr im Stoff stehen, verlieren die Zuordnung; aus dem Stoff
    entstandene ohne Lernstand und ohne andere Prüfung verschwinden."""
    tag = pruefung_am.isoformat()
    themen = list(session.scalars(select(Thema).where(Thema.lva_id == lva.id).order_by(Thema.reihenfolge, Thema.id)))
    nach_titel = {t.titel.casefold(): t for t in themen}
    reihenfolge = max((t.reihenfolge for t in themen), default=0)
    ergebnis = {"neu": 0, "zugeordnet": 0, "entfernt": 0}
    gewuenscht: list[Thema] = []
    for name in titel:
        thema = nach_titel.get(name.casefold())
        if thema is None:
            reihenfolge += 1
            thema = Thema(lva_id=lva.id, titel=name[:300], kapitel=name[:300], reihenfolge=reihenfolge, quelle="stoff",
                          pruefungen=[tag])
            session.add(thema)
            nach_titel[name.casefold()] = thema
            ergebnis["neu"] += 1
        elif tag not in (thema.pruefungen or []):
            thema.pruefungen = sorted([*(thema.pruefungen or []), tag])  # neue Liste, damit die Änderung gespeichert wird
            ergebnis["zugeordnet"] += 1
        if thema not in gewuenscht:
            gewuenscht.append(thema)
    for thema in themen:
        if thema in gewuenscht or tag not in (thema.pruefungen or []):
            continue
        rest = [p for p in thema.pruefungen if p != tag]
        if not rest and thema.quelle == "stoff" and not hat_lernstand(session, thema):
            session.delete(thema)
        else:
            thema.pruefungen = rest  # leer = keiner Prüfung mehr zugeordnet (nicht „alle“)
        ergebnis["entfernt"] += 1
    session.flush()
    for thema in gewuenscht:
        abschnitte_verknuepfen(session, thema, embedder)
    session.commit()
    return ergebnis


def themen_der_pruefung(themen: list[dict], tag: date) -> list[dict]:
    """Themen eines Zeitabschnitts: die dieser Prüfung zugeordneten; gibt es keine, die allgemeinen (ohne Zuordnung)."""
    zugeordnet = [t for t in themen if tag.isoformat() in (t["pruefungen"] or [])]
    return zugeordnet or [t for t in themen if t["pruefungen"] is None]


def zeitstrahl_out(session: Session, lva: Lva, themen: list[dict], heute: date) -> list[dict]:
    """Je Prüfung der LVA ein Zeitabschnitt mit seinen Themen, Fortschritt und hochgeladenem Stoff."""
    termine = pruefungstermine(session, lva)
    if not termine:
        return []
    erster = session.scalar(select(func.min(Termin.start)).where(Termin.lva_id == lva.id))
    beginn = erster.date() if erster else heute
    stoff = list(session.scalars(select(Pruefungsstoff).where(Pruefungsstoff.lva_id == lva.id)
                                 .order_by(Pruefungsstoff.hochgeladen_am.desc())))
    quelle = {z.date(): (z, q) for z, q in termine}
    ergebnis = []
    for a in zeitabschnitte(beginn, list(quelle), heute):
        eigene = themen_der_pruefung(themen, a.bis)
        zeitpunkt, herkunft = quelle[a.bis]
        ergebnis.append({
            "datum": a.bis, "zeitpunkt": zeitpunkt, "quelle": herkunft, "von": a.von, "zeit_anteil": a.zeit_anteil,
            "vorbei": a.vorbei, "themen": [t["id"] for t in eigene],
            "fortschritt": round(sum(t["stufe"] for t in eigene) / (4 * len(eigene)), 2) if eigene else 0,
            "stoff": [{"id": s.id, "dateiname": s.dateiname, "themen": s.themen, "hochgeladen_am": s.hochgeladen_am}
                      for s in stoff if s.pruefung_am == a.bis],
        })
    return ergebnis


def thema_out(session: Session, thema: Thema, heute: date) -> dict:
    stand = session.get(Wissensstand, thema.id)
    stufe = stand.stufe if stand else 0
    return {
        "id": thema.id, "lva_id": thema.lva_id, "titel": thema.titel, "reihenfolge": thema.reihenfolge,
        "quelle": thema.quelle, "kapitel": thema.kapitel, "stufe": stufe, "stufe_name": STUFEN[stufe],
        "letzte_uebung": stand.letzte_uebung if stand else None,
        "naechste_wiederholung": stand.naechste_wiederholung if stand else None,
        "faellig": faellig(stand.naechste_wiederholung if stand else None, heute),
        "abschnitte": len(thema.abschnitte),
        "pruefungen": thema.pruefungen,  # None = gilt für alle Prüfungen
    }


def uebersicht(session: Session, lva_id: int | None = None, heute: date | None = None,
               lva_ids: set[int] | None = None) -> list[dict]:
    """Je LVA: Themen mit Stufe, fällige Wiederholungen, Tage bis zur Prüfung, Verteilung der Stufen und der
    Zeitstrahl (Abschnitte bis zu jeder Prüfung). `lva_ids` begrenzt auf diese LVAs (auch ohne Themen)."""
    heute = heute or date.today()
    abfrage = select(Lva)
    if lva_id is not None:
        abfrage = abfrage.where(Lva.id == lva_id)
    elif lva_ids is not None:
        abfrage = abfrage.where(Lva.id.in_(lva_ids))
    ergebnis = []
    for lva in session.scalars(abfrage.order_by(Lva.semester.desc(), Lva.titel, Lva.typ)):
        themen = [thema_out(session, t, heute) for t in session.scalars(
            select(Thema).where(Thema.lva_id == lva.id).order_by(Thema.reihenfolge, Thema.id))]
        if lva_id is None and lva_ids is None and not themen:
            continue
        pruefung = naechste_pruefung(session, lva.id, heute)
        verteilung = Counter(t["stufe"] for t in themen)
        ergebnis.append({
            "lva_id": lva.id, "lva": lva.anzeigename, "farbe": lva.farbe, "semester": lva.semester,
            "pruefung": pruefung, "tage_bis_pruefung": (pruefung - heute).days if pruefung else None,
            "themen": themen, "faellig": [t for t in themen if t["faellig"]],
            "verteilung": {s: verteilung.get(s, 0) for s in STUFEN},
            "fortschritt": round(sum(t["stufe"] for t in themen) / (4 * len(themen)), 2) if themen else 0,
            "zeitstrahl": zeitstrahl_out(session, lva, themen, heute),
            "notizen": [{"id": n.id, "text": n.text, "erstellt_am": n.erstellt_am, "quelle": n.quelle} for n in session.scalars(
                select(Notiz).where(Notiz.lva_id == lva.id).order_by(Notiz.erstellt_am.desc()).limit(5))],
        })
    return ergebnis


def faellige_wiederholungen(session: Session, lva_id: int | None = None, heute: date | None = None) -> list[dict]:
    heute = heute or date.today()
    abfrage = select(Thema).join(Wissensstand).where(Wissensstand.naechste_wiederholung <= heute)
    if lva_id is not None:
        abfrage = abfrage.where(Thema.lva_id == lva_id)
    return [thema_out(session, t, heute) | {"lva": t.lva.anzeigename}
            for t in session.scalars(abfrage.order_by(Wissensstand.naechste_wiederholung, Thema.reihenfolge))]
