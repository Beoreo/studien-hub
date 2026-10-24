"""Wochenbericht aus den TUWEL-Daten: was in einer Woche an Unterlagen und Aufzeichnungen dazugekommen ist.

Kein Claude, keine Netzwerkzugriffe – der Bericht entsteht sofort aus dem, was der TUWEL-Sync gespeichert hat:
je besuchter LVA die neuen und geänderten Unterlagen (mit geschätzter Stoffmenge, siehe lernaufwand.py), neue
Aufzeichnungen, LVAs ohne Neues und die Prüfungen der nächsten Wochen. Eingeschaltet erstellt der Hub ihn jeden
Sonntag für die laufende Woche; war der Rechner aus, holt er den Bericht der Vorwoche am Montag nach.
Ergebnis: Markdown in `Wochenbericht.text`.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .lernaufwand import erscheinungszeit, pruefungstermine, stoff_minuten
from .models import DOK_GEAENDERT, Dokument, Lva, Wochenbericht, lies_einstellung, setze_einstellung

log = logging.getLogger("studienhub")
AKTIV = "wochenbericht_aktiv"
STUNDE = int(os.environ.get("STUDIENHUB_WOCHENBERICHT_STUNDE", "19"))  # Sonntag, 19 Uhr
PRUEFUNGEN_VORAUS = timedelta(weeks=3)
WOCHENTAGE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


# --- reine Logik --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class NeueUnterlage:
    lva: str
    dateiname: str
    abschnitt: str
    video: bool
    geaendert: bool  # schon bekannt, neue Fassung in dieser Woche
    seiten: int | None = None
    dauer_sekunden: int | None = None
    stoff_minuten: int = 0


def montag(tag: date) -> date:
    return tag - timedelta(days=tag.weekday())


def berichtswoche(jetzt: datetime) -> date:
    """Montag der Woche, über die berichtet wird: die laufende (der Sonntagslauf schließt sie ab)."""
    return montag(jetzt.date())


def _stunden(minuten: int) -> str:
    return f"{minuten / 60:.1f}".replace(".", ",") + " h"


def _umfang(u: NeueUnterlage) -> str:
    if u.video:
        if not u.dauer_sekunden:
            return "Video"
        m = round(u.dauer_sekunden / 60)
        return f"Video, {m // 60}:{m % 60:02} h" if m >= 60 else f"Video, {m} min"
    return f"{u.seiten} Seiten" if u.seiten else "–"


def _zelle(text: str) -> str:
    return (text or "").replace("|", "/").strip() or "–"


def bericht_text(woche: date, unterlagen: list[NeueUnterlage], ohne_neues: list[str],
                 pruefungen: list[tuple[str, datetime]]) -> str:
    """Markdown-Bericht einer Woche (Montag `woche`) aus den neuen Unterlagen."""
    sonntag = woche + timedelta(days=6)
    neu = [u for u in unterlagen if not u.geaendert]
    geaendert = [u for u in unterlagen if u.geaendert]
    videos = [u for u in neu if u.video]
    stoff = sum(u.stoff_minuten for u in unterlagen)
    lvas = sorted({u.lva for u in unterlagen})

    zeilen = [f"## Woche vom {woche:%d.%m.} bis {sonntag:%d.%m.%Y}", "", "## Überblick", ""]
    if unterlagen:
        zeilen += [
            f"- **{len(neu) - len(videos)}** neue Unterlagen, **{len(videos)}** neue Aufzeichnungen, "
            f"**{len(geaendert)}** geändert – in {len(lvas)} {'LVA' if len(lvas) == 1 else 'LVAs'}",
            f"- geschätzter neuer Stoff: **{_stunden(stoff)}**",
        ]
    else:
        zeilen.append("- In dieser Woche ist in TUWEL nichts Neues dazugekommen.")

    for lva in lvas:
        eintraege = sorted((u for u in unterlagen if u.lva == lva), key=lambda u: (u.geaendert, u.video, u.abschnitt, u.dateiname))
        summe = sum(u.stoff_minuten for u in eintraege)
        zeilen += ["", f"### {lva} ({_stunden(summe)} Stoff)", "", "| Unterlage | Abschnitt | Umfang | Stoff |", "| --- | --- | --- | --- |"]
        for u in eintraege:
            name = f"{_zelle(u.dateiname)}{' *(geändert)*' if u.geaendert else ''}"
            zeilen.append(f"| {name} | {_zelle(u.abschnitt)} | {_umfang(u)} | {u.stoff_minuten} min |")

    if ohne_neues:
        zeilen += ["", "## Ohne Neues", "", *[f"- {name}" for name in sorted(ohne_neues)]]
    if pruefungen:
        zeilen += ["", "## Prüfungen in den nächsten Wochen", ""]
        zeilen += [f"- **{name}**: {WOCHENTAGE[z.weekday()]} {z:%d.%m.%Y %H:%M}"
                   for name, z in sorted(pruefungen, key=lambda p: p[1])]
    return "\n".join(zeilen)


# --- Datenbank ------------------------------------------------------------------------------------------

def neue_unterlagen(session: Session, woche: date, lvas: list[Lva]) -> list[NeueUnterlage]:
    """TUWEL-Unterlagen der LVAs, die in der Woche erschienen sind oder eine neue Fassung bekommen haben."""
    von = datetime.combine(montag(woche), time())
    bis = von + timedelta(days=7)
    namen = {l.id: l.anzeigename for l in lvas}
    ergebnis = []
    for doc in session.scalars(select(Dokument).where(Dokument.lva_id.in_(namen), Dokument.quelle == "tuwel")):
        neu = von <= erscheinungszeit(doc) < bis
        geaendert = not neu and doc.status == DOK_GEAENDERT and von <= doc.geaendert_am < bis
        if not (neu or geaendert):
            continue
        ergebnis.append(NeueUnterlage(
            lva=namen[doc.lva_id], dateiname=doc.dateiname, abschnitt=doc.abschnitt or doc.aktivitaet, video=doc.ist_link,
            geaendert=geaendert, seiten=doc.seiten, dauer_sekunden=doc.dauer_sekunden, stoff_minuten=stoff_minuten(doc, doc.lva),
        ))
    session.flush()  # stoff_minuten bestimmt Seiten und Art einmalig
    return ergebnis


def bericht_erstellen(session: Session, woche: date | None = None, anlass: str = "manuell",
                      jetzt: datetime | None = None) -> Wochenbericht:
    """Erstellt (oder ersetzt) den Bericht der Woche; Fehler stehen im Bericht."""
    from .lva_auswahl import besuchte_lva_ids

    jetzt = jetzt or datetime.now()
    woche = montag(woche or berichtswoche(jetzt))
    for alt in session.scalars(select(Wochenbericht).where(Wochenbericht.woche == woche)):
        session.delete(alt)
    bericht = Wochenbericht(woche=woche, status="laeuft", anlass=anlass, erstellt_am=jetzt, vorschlaege=0)
    session.add(bericht)
    try:
        lvas = list(session.scalars(select(Lva).where(Lva.id.in_(besuchte_lva_ids(session))).order_by(Lva.titel)))
        unterlagen = neue_unterlagen(session, woche, lvas)
        mit_neuem = {u.lva for u in unterlagen}
        # nur LVAs mit TUWEL-Kurs können Neues haben
        ohne = [l.anzeigename for l in lvas if l.anzeigename not in mit_neuem
                and session.scalar(select(Dokument.id).where(Dokument.lva_id == l.id).limit(1)) is not None]
        grenze = datetime.combine(woche + timedelta(days=7), time()) + PRUEFUNGEN_VORAUS
        anstehend = [(l.anzeigename, z) for l in lvas for z, _ in pruefungstermine(session, l)
                     if datetime.combine(woche, time()) <= z < grenze]
        bericht.text = bericht_text(woche, unterlagen, ohne, anstehend)
        bericht.neue_unterlagen = len(unterlagen)
        bericht.status = "ok"
    except Exception as fehler:  # sichtbar melden statt still schlucken
        log.exception("Wochenbericht fehlgeschlagen")
        bericht.status, bericht.fehler = "fehler", str(fehler)[:2000]
    session.commit()
    return bericht


def ist_aktiv(session: Session) -> bool:
    """Standard: eingeschaltet (der Bericht kostet nichts und braucht kein Netz)."""
    return lies_einstellung(session, AKTIV) != "nein"


def setze_aktiv(session: Session, aktiv: bool) -> None:
    setze_einstellung(session, AKTIV, "ja" if aktiv else "nein")
    session.commit()


def nachholen_woche(session: Session, jetzt: datetime) -> date | None:
    """War der Rechner am Sonntagabend aus? Sonntag später: diese Woche; Montag: die Vorwoche."""
    if not ist_aktiv(session):
        return None
    tag = jetzt.weekday()
    if tag == 6 and jetzt.hour >= STUNDE:
        woche = montag(jetzt.date())
    elif tag == 0:
        woche = montag(jetzt.date()) - timedelta(days=7)
    else:
        return None
    vorhanden = session.scalar(select(Wochenbericht.id).where(Wochenbericht.woche == woche, Wochenbericht.status == "ok").limit(1))
    return None if vorhanden else woche


def sonntagslauf() -> None:
    """Scheduler: Sonntag, 19 Uhr – nur wenn eingeschaltet."""
    from .db import SessionLocal

    with SessionLocal() as session:
        if ist_aktiv(session):
            bericht_erstellen(session, anlass="zeitplan")


def beim_start_nachholen() -> None:
    from .db import SessionLocal

    with SessionLocal() as session:
        woche = nachholen_woche(session, datetime.now())
        if woche:
            bericht_erstellen(session, woche, anlass="nachgeholt")
