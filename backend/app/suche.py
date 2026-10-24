"""Semantische Suche über alle Abschnitte (Stufe 3): Vektoren (sqlite-vec) und Volltext (FTS5) kombiniert.

Beide Listen werden per Reciprocal Rank Fusion zusammengeführt; offizielle Unterlagen bekommen einen kleinen
Vorsprung vor inoffiziellen (MB Cloud). Ohne sqlite-vec oder ohne Modell bleibt der Volltext.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from .db import VEKTORSUCHE
from .embedding import Embedder
from .extraktion import AbschnittRoh
from .models import Abschnitt, Dokument

RRF_K = 60
BONUS_OFFIZIELL = 0.15  # Anteil eines Rangplatzes 1: offizielle Unterlagen leicht bevorzugt


# --- Schreiben -----------------------------------------------------------------------------------------

def abschnitte_loeschen(session: Session, dokument_id: int) -> None:
    ids = list(session.scalars(select(Abschnitt.id).where(Abschnitt.dokument_id == dokument_id)))
    if not ids:
        return
    liste = ",".join(map(str, ids))
    session.execute(text(f"DELETE FROM abschnitt_fts WHERE rowid IN ({liste})"))
    if VEKTORSUCHE["verfuegbar"]:
        session.execute(text(f"DELETE FROM abschnitt_vec WHERE rowid IN ({liste})"))
    session.execute(delete(Abschnitt).where(Abschnitt.id.in_(ids)))


def abschnitte_speichern(session: Session, doc: Dokument, rohe: list[AbschnittRoh], quelle: str,
                         embedder: Embedder | None) -> list[Abschnitt]:
    """Ersetzt die Abschnitte einer Unterlage; Herkunft (LVA, Quelle, offiziell, Jahr) kommt vom Dokument.

    Die Embeddings werden *vor* dem ersten Schreibzugriff berechnet (das dauert bei großen Skripten Sekunden bis
    Minuten) – so hält die Unterlage die Datenbank nur für das eigentliche Schreiben gesperrt.
    """
    vektoren = []
    if embedder is not None and VEKTORSUCHE["verfuegbar"] and rohe:
        vektoren = embedder.einbetten([_einbettungstext(r.unterkapitel, doc.dateiname, r.text) for r in rohe])
    abschnitte_loeschen(session, doc.id)
    jahr = doc.jahr or (doc.erschienen_am.year if doc.erschienen_am else None)
    neue = [
        Abschnitt(dokument_id=doc.id, lva_id=doc.lva_id, reihenfolge=i, quelle=quelle, offiziell=quelle != "mbcloud",
                  jahr=jahr, kapitel=(r.kapitel or "")[:300] or None, unterkapitel=(r.unterkapitel or "")[:500] or None,
                  seite_von=r.seite_von, seite_bis=r.seite_bis, zeit_von=r.zeit_von, zeit_bis=r.zeit_bis, text=r.text)
        for i, r in enumerate(rohe)
    ]
    session.add_all(neue)
    session.flush()
    for a in neue:
        session.execute(text("INSERT INTO abschnitt_fts(rowid, text, kapitel) VALUES (:id, :t, :k)"),
                        {"id": a.id, "t": a.text, "k": a.unterkapitel or ""})
    for a, v in zip(neue, vektoren):
        session.execute(text("INSERT INTO abschnitt_vec(rowid, embedding) VALUES (:id, :v)"),
                        {"id": a.id, "v": json.dumps(v)})
    return neue


def _einbettungstext(unterkapitel: str | None, dateiname: str, inhalt: str) -> str:
    """Kapitel und Dateiname geben dem Abschnitt Zusammenhang."""
    kopf = " – ".join(filter(None, [unterkapitel, dateiname]))
    return f"{kopf}\n{inhalt}"[:2000]


# --- Suchen ------------------------------------------------------------------------------------------

@dataclass
class Treffer:
    abschnitt: Abschnitt
    punkte: float
    vektor_rang: int | None = None
    volltext_rang: int | None = None

    def als_dict(self, kurz: bool = True) -> dict:
        a = self.abschnitt
        return {
            "abschnitt_id": a.id, "lva_id": a.lva_id, "lva": a.lva.anzeigename,
            "dokument": a.dokument.dateiname, "dokument_id": a.dokument_id, "quelle": a.quelle,
            "offiziell": a.offiziell, "jahr": a.jahr, "kapitel": a.unterkapitel or a.kapitel,
            "fundstelle": a.fundstelle, "seite_von": a.seite_von, "seite_bis": a.seite_bis,
            "zeit_von": a.zeit_von, "zeit_bis": a.zeit_bis, "kategorie": a.dokument.kategorie,
            "text": (a.text[:600] + " …") if kurz and len(a.text) > 600 else a.text,
            "punkte": round(self.punkte, 4),
        }


def _fts_anfrage(frage: str) -> str | None:
    """Freitext in eine tolerante FTS5-Anfrage: Wörter mit Präfix, ODER-verknüpft."""
    woerter = [w for w in re.findall(r"\w+", frage.casefold()) if len(w) > 2]
    return " OR ".join(f'"{w}"*' for w in woerter[:12]) or None


def suchen(session: Session, frage: str, lva_id: int | None = None, anzahl: int = 8,
           embedder: Embedder | None = None, nur_offiziell: bool = False) -> list[Treffer]:
    kandidaten = max(anzahl * 6, 40)
    raenge_vektor: dict[int, int] = {}
    raenge_text: dict[int, int] = {}

    if embedder is not None and VEKTORSUCHE["verfuegbar"]:
        try:
            v = embedder.einbetten([frage])[0]
            zeilen = session.execute(
                text("SELECT rowid FROM abschnitt_vec WHERE embedding MATCH :v AND k = :k ORDER BY distance"),
                {"v": json.dumps(v), "k": kandidaten * (4 if lva_id else 1)},
            ).all()
            raenge_vektor = {z[0]: i for i, z in enumerate(zeilen)}
        except Exception:  # z. B. Modell nicht vorhanden (offline): Volltext genügt
            raenge_vektor = {}
    anfrage = _fts_anfrage(frage)
    if anfrage:
        zeilen = session.execute(
            text("SELECT rowid FROM abschnitt_fts WHERE abschnitt_fts MATCH :q ORDER BY rank LIMIT :k"),
            {"q": anfrage, "k": kandidaten * (4 if lva_id else 1)},
        ).all()
        raenge_text = {z[0]: i for i, z in enumerate(zeilen)}

    ids = set(raenge_vektor) | set(raenge_text)
    if not ids:
        return []
    abfrage = select(Abschnitt).where(Abschnitt.id.in_(ids))
    if lva_id is not None:
        abfrage = abfrage.where(Abschnitt.lva_id == lva_id)
    if nur_offiziell:
        abfrage = abfrage.where(Abschnitt.offiziell.is_(True))
    treffer = []
    for a in session.scalars(abfrage):
        rv, rt = raenge_vektor.get(a.id), raenge_text.get(a.id)
        punkte = sum(1 / (RRF_K + r + 1) for r in (rv, rt) if r is not None)
        if a.offiziell:
            punkte += BONUS_OFFIZIELL / (RRF_K + 1)
        treffer.append(Treffer(a, punkte, rv, rt))
    return sorted(treffer, key=lambda t: -t.punkte)[:anzahl]
