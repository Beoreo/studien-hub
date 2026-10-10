"""TUWEL-Sync auf Seite des Hubs (Stufe 2).

Die Browser-Erweiterung liest TUWEL mit der Sitzung des eingeloggten Browsers und meldet:
1. die Kursliste       -> Kurse werden den LVAs zugeordnet (`kurse_registrieren`)
2. die Inhalte je Kurs -> der Hub sagt, welche Dateien neu sind (`inhalt_abgleichen`)
3. die angeforderten Dateien -> Prüfsumme, Ablage pro LVA, Erkennung von Änderungen (`datei_speichern`)

Videos werden nur als Link-Eintrag gespeichert, ohne Download (Verarbeitung folgt in Stufe 3).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import UNTERLAGEN_ORDNER
from .models import (
    DOK_GEAENDERT,
    DOK_NEU,
    DOK_UNVERAENDERT,
    ZUORDNUNG_AUS,
    ZUORDNUNG_AUTO,
    Dokument,
    Lva,
    TuwelKurs,
    lies_einstellung,
    setze_einstellung,
)
from .tiss_import import LVA_NUMMER

# Einstellungs-Schlüssel
SCHLUESSEL_ERWEITERUNG = "erweiterung_schluessel"
LETZTER_LAUF = "tuwel_letzter_lauf"
LETZTER_ERFOLG = "tuwel_letzter_erfolg"
LETZTER_FEHLER = "tuwel_letzter_fehler"
LETZTES_ERGEBNIS = "tuwel_letztes_ergebnis"
WARNUNG_NACH = timedelta(hours=36)  # ohne erfolgreichen Lauf -> Hinweis in der Oberfläche

DATEI_TYPEN = {
    "pdf": "pdf",
    "ppt": "folien", "pptx": "folien", "odp": "folien", "key": "folien",
    "doc": "dokument", "docx": "dokument", "odt": "dokument", "txt": "dokument", "md": "dokument",
    "tex": "dokument", "rtf": "dokument",
}
SEMESTER_MUSTER = [
    re.compile(r"\b(20\d\d)\s*([WS])(?:S|E)?\b", re.IGNORECASE),  # 2026W, 2026WS, 2026 S
    re.compile(r"\b([WS])(?:S|E|oSe|iSe)?\s*(20\d\d)\b", re.IGNORECASE),  # WS 2026, SS2026, WiSe 2026
]
VERBOTEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVIERT = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


# --- Schlüssel für die Erweiterung ------------------------------------------------

def erweiterungs_schluessel(session: Session, neu: bool = False) -> str:
    """Gemeinsamer Schlüssel zwischen Hub und Erweiterung; wird beim ersten Abruf erzeugt."""
    schluessel = lies_einstellung(session, SCHLUESSEL_ERWEITERUNG)
    if neu or not schluessel:
        schluessel = secrets.token_urlsafe(24)
        setze_einstellung(session, SCHLUESSEL_ERWEITERUNG, schluessel)
        session.commit()
    return schluessel


# --- Zuordnung Kurs -> LVA -----------------------------------------------------------

def semester_aus_text(text: str) -> str | None:
    """Erkennt Semesterangaben wie „2026W“, „WS 2026/27“ oder „SS2026“."""
    treffer = SEMESTER_MUSTER[0].search(text)
    if treffer:
        return f"{treffer.group(1)}{treffer.group(2).upper()}"
    treffer = SEMESTER_MUSTER[1].search(text)
    if treffer:
        return f"{treffer.group(2)}{treffer.group(1).upper()}"
    return None


def _normalisiert(text: str) -> str:
    text = LVA_NUMMER.sub(" ", text.casefold())
    text = re.sub(r"\b(vo|ue|vu|se|pr|lu|ps|ex)\b|\(.*?\)|20\d\d\s*[ws]?\b|[ws]s\s*20\d\d", " ", text)
    return re.sub(r"[^0-9a-zäöüß]+", " ", text).strip()


def ordne_kurs_zu(session: Session, kurs: TuwelKurs) -> Lva | None:
    """Findet die LVA zu einem TUWEL-Kurs. Manuelle Zuordnungen bleiben unangetastet."""
    if kurs.zuordnung != ZUORDNUNG_AUTO:
        return kurs.lva

    # In der LVA-Liste von Hand eingetragene TUWEL-Kurs-ID hat Vorrang
    lva = session.scalar(select(Lva).where(Lva.tuwel_kurs_id == kurs.id))
    if lva:
        return lva

    text = " ".join(filter(None, [kurs.kurzname, kurs.name, kurs.idnumber]))
    semester = semester_aus_text(text)
    nummern = LVA_NUMMER.findall(text)
    kandidaten: list[Lva] = []
    if nummern:
        kandidaten = list(session.scalars(select(Lva).where(Lva.nummer.in_(nummern))))
    else:
        titel = _normalisiert(kurs.name or kurs.kurzname)
        if titel:
            kandidaten = [l for l in session.scalars(select(Lva)) if _normalisiert(l.titel) == titel]
    if semester:
        kandidaten = [l for l in kandidaten if l.semester == semester]
    if not kandidaten:
        return None
    # Bei mehreren Treffern: zuerst die Reihenfolge der Nummern im Kursnamen, dann das neueste Semester
    kandidaten.sort(key=lambda l: (nummern.index(l.nummer) if l.nummer in nummern else 99, _semester_rang(l.semester)))
    return kandidaten[0]


def _semester_rang(semester: str) -> int:
    """Kleiner = neuer, für die Sortierung."""
    try:
        return -(int(semester[:4]) * 2 + (1 if semester[4:].upper() == "W" else 0))
    except ValueError:
        return 0


def kurse_registrieren(session: Session, kurse: list[dict]) -> list[TuwelKurs]:
    """Speichert die gemeldeten Kurse und ordnet sie zu; liefert sie in gemeldeter Reihenfolge."""
    jetzt = datetime.now()
    ergebnis = []
    for daten in kurse:
        kurs = session.get(TuwelKurs, int(daten["id"])) or TuwelKurs(id=int(daten["id"]))
        kurs.kurzname = daten.get("kurzname") or ""
        kurs.name = daten.get("name") or ""
        kurs.idnumber = daten.get("idnumber") or None
        kurs.zuletzt_gesehen = jetzt
        session.add(kurs)
        session.flush()
        lva = ordne_kurs_zu(session, kurs)
        if kurs.zuordnung == ZUORDNUNG_AUTO:
            kurs.lva = lva
            if lva is not None and lva.tuwel_kurs_id is None:
                lva.tuwel_kurs_id = kurs.id
        ergebnis.append(kurs)
    setze_einstellung(session, LETZTER_LAUF, jetzt.isoformat(timespec="seconds"))
    session.commit()
    return ergebnis


def soll_synchronisiert_werden(kurs: TuwelKurs) -> bool:
    return kurs.lva_id is not None and kurs.zuordnung != ZUORDNUNG_AUS


# --- Abgleich der Inhalte ------------------------------------------------------------

@dataclass
class Eintrag:
    cm_id: int
    url: str
    art: str = "datei"  # "datei" oder "video"
    abschnitt: str = ""
    aktivitaet: str = ""
    dateiname: str = ""
    unterordner: str = ""

    @property
    def schluessel(self) -> str:
        if self.art == "video":
            return self.url
        return f"{self.unterordner}/{self.dateiname}" if self.unterordner else self.dateiname


def dateityp(dateiname: str) -> str:
    endung = dateiname.rsplit(".", 1)[-1].lower() if "." in dateiname else ""
    return DATEI_TYPEN.get(endung, "sonstiges")


def inhalt_abgleichen(session: Session, kurs: TuwelKurs, eintraege: list[Eintrag]) -> dict:
    """Trägt Videos als Links ein und liefert die URLs der Dateien, die heruntergeladen werden müssen."""
    if not soll_synchronisiert_werden(kurs):
        raise ValueError(f"Kurs {kurs.id} ist keiner LVA zugeordnet")
    jetzt = datetime.now()
    herunterladen: list[str] = []
    unveraendert = videos_neu = 0
    for e in eintraege:
        doc = session.scalar(select(Dokument).where(Dokument.tuwel_cm_id == e.cm_id, Dokument.schluessel == e.schluessel))
        if e.art == "video":
            if doc is None:
                doc = Dokument(
                    lva_id=kurs.lva_id, tuwel_kurs_id=kurs.id, tuwel_cm_id=e.cm_id, schluessel=e.schluessel,
                    dateiname=e.aktivitaet or e.url, typ="video", ist_link=True, quelle_url=e.url, status=DOK_NEU,
                )
                session.add(doc)
                videos_neu += 1
            else:
                doc.status = DOK_UNVERAENDERT
            doc.abschnitt, doc.aktivitaet, doc.zuletzt_gesehen = e.abschnitt, e.aktivitaet, jetzt
            continue

        # Gleiche URL wie beim letzten Mal und Datei vorhanden: TUWEL ändert die URL bei jeder neuen Version
        if doc is not None and doc.quelle_url == e.url and doc.pfad and (UNTERLAGEN_ORDNER / doc.pfad).exists():
            doc.status = DOK_UNVERAENDERT
            doc.zuletzt_gesehen = jetzt
            unveraendert += 1
        elif e.url not in herunterladen:
            herunterladen.append(e.url)
    session.commit()
    return {"herunterladen": herunterladen, "unveraendert": unveraendert, "videos_neu": videos_neu}


# --- Ablage der Dateien ---------------------------------------------------------------

def sicherer_name(name: str, max_laenge: int = 100) -> str:
    """Macht einen Datei- oder Ordnernamen unter Windows gültig."""
    name = VERBOTEN.sub("_", name).strip().rstrip(". ") or "_"
    if name.split(".")[0].upper() in RESERVIERT:
        name = "_" + name
    if len(name) > max_laenge:
        stamm, punkt, endung = name.rpartition(".")
        if punkt and len(endung) <= 10:
            name = stamm[: max_laenge - len(endung) - 1].rstrip(". ") + "." + endung
        else:
            name = name[:max_laenge].rstrip(". ")
    return name


def lva_ordner(lva: Lva) -> Path:
    return Path(sicherer_name(lva.semester, 20)) / sicherer_name(lva.kurzname or lva.titel, 80)


def zielpfad(session: Session, lva: Lva, e: Eintrag, doc: Dokument | None) -> Path:
    """Relativer Ablagepfad: Semester/LVA/Abschnitt/Unterordner/Datei; bei Namensgleichheit mit Zusatz."""
    teile = [lva_ordner(lva)]
    if e.abschnitt:
        teile.append(Path(sicherer_name(e.abschnitt, 60)))
    for teil in filter(None, e.unterordner.split("/")):
        teile.append(Path(sicherer_name(teil, 60)))
    pfad = Path(*teile) / sicherer_name(e.dateiname)
    belegt = session.scalar(select(Dokument).where(Dokument.pfad == pfad.as_posix()))
    if belegt is not None and (doc is None or belegt.id != doc.id):
        stamm, punkt, endung = pfad.name.rpartition(".")
        neuer_name = f"{stamm} ({e.cm_id}).{endung}" if punkt else f"{pfad.name} ({e.cm_id})"
        pfad = pfad.with_name(neuer_name)
    return pfad


def datei_speichern(session: Session, kurs: TuwelKurs, e: Eintrag, inhalt: BinaryIO) -> dict:
    """Speichert eine heruntergeladene Datei mit SHA-256. Geänderte Dateien behalten die alte Version."""
    if not soll_synchronisiert_werden(kurs):
        raise ValueError(f"Kurs {kurs.id} ist keiner LVA zugeordnet")
    lva = kurs.lva
    doc = session.scalar(select(Dokument).where(Dokument.tuwel_cm_id == e.cm_id, Dokument.schluessel == e.schluessel))
    relativ = Path(doc.pfad) if doc and doc.pfad else zielpfad(session, lva, e, doc)
    ziel = UNTERLAGEN_ORDNER / relativ
    ziel.parent.mkdir(parents=True, exist_ok=True)

    # In eine temporäre Datei schreiben und dabei die Prüfsumme bilden
    pruefer = hashlib.sha256()
    groesse = 0
    fd, temp = tempfile.mkstemp(dir=ziel.parent, prefix=".download.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as aus:
            while block := inhalt.read(1024 * 1024):
                pruefer.update(block)
                groesse += len(block)
                aus.write(block)
        summe = pruefer.hexdigest()
        jetzt = datetime.now()

        if doc is not None and doc.pruefsumme == summe and ziel.exists():
            Path(temp).unlink()
            status = DOK_UNVERAENDERT
        else:
            if doc is not None and ziel.exists():
                # alte Version aufheben: „name (alt 2026-10-10).pdf“
                stamm, punkt, endung = ziel.name.rpartition(".")
                alt = f"{stamm} (alt {date.today().isoformat()}).{endung}" if punkt else f"{ziel.name} (alt {date.today()})"
                os.replace(ziel, ziel.with_name(alt))
            os.replace(temp, ziel)
            status = DOK_NEU if doc is None else DOK_GEAENDERT
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise

    if doc is None:
        doc = Dokument(
            lva_id=lva.id, tuwel_kurs_id=kurs.id, tuwel_cm_id=e.cm_id, schluessel=e.schluessel,
            dateiname=e.dateiname, typ=dateityp(e.dateiname), ist_link=False, erstellt_am=jetzt,
        )
        session.add(doc)
    doc.lva_id = lva.id
    doc.abschnitt, doc.aktivitaet = e.abschnitt, e.aktivitaet
    doc.quelle_url, doc.pfad = e.url, relativ.as_posix()
    doc.pruefsumme, doc.groesse, doc.status = summe, groesse, status
    doc.zuletzt_gesehen = jetzt
    if status != DOK_UNVERAENDERT:
        doc.geaendert_am = jetzt
    session.commit()
    return {"status": status, "id": doc.id, "pfad": doc.pfad}


# --- Abschluss und Status -------------------------------------------------------------

def sync_beenden(session: Session, statistik: dict) -> None:
    jetzt = datetime.now().isoformat(timespec="seconds")
    setze_einstellung(session, LETZTES_ERGEBNIS, json.dumps({**statistik, "zeit": jetzt}, ensure_ascii=False))
    fehler = statistik.get("fehler") or []
    setze_einstellung(session, LETZTER_ERFOLG, jetzt)
    setze_einstellung(session, LETZTER_FEHLER, json.dumps({"zeit": jetzt, "meldung": "; ".join(fehler)}, ensure_ascii=False) if fehler else None)
    session.commit()


def fehler_melden(session: Session, meldung: str, art: str = "fehler") -> None:
    jetzt = datetime.now().isoformat(timespec="seconds")
    setze_einstellung(session, LETZTER_LAUF, jetzt)
    setze_einstellung(session, LETZTER_FEHLER, json.dumps({"zeit": jetzt, "meldung": meldung, "art": art}, ensure_ascii=False))
    session.commit()


def status(session: Session, jetzt: datetime | None = None) -> dict:
    jetzt = jetzt or datetime.now()
    erfolg = lies_einstellung(session, LETZTER_ERFOLG)
    fehler = lies_einstellung(session, LETZTER_FEHLER)
    ergebnis = lies_einstellung(session, LETZTES_ERGEBNIS)
    warnung = None
    if erfolg is None:
        warnung = "Noch kein erfolgreicher TUWEL-Sync. Ist die Browser-Erweiterung eingerichtet?"
    elif jetzt - datetime.fromisoformat(erfolg) > WARNUNG_NACH:
        warnung = (f"Seit {datetime.fromisoformat(erfolg):%d.%m. %H:%M} kein erfolgreicher TUWEL-Sync – "
                   "Browser öffnen und in TUWEL einloggen.")
    kurse = list(session.scalars(select(TuwelKurs)))
    dokumente = list(session.scalars(select(Dokument)))
    return {
        "letzter_lauf": lies_einstellung(session, LETZTER_LAUF),
        "letzter_erfolg": erfolg,
        "letzter_fehler": json.loads(fehler) if fehler else None,
        "letztes_ergebnis": json.loads(ergebnis) if ergebnis else None,
        "warnung": warnung,
        "kurse": len(kurse),
        "kurse_ohne_lva": sum(1 for k in kurse if k.lva_id is None and k.zuordnung != ZUORDNUNG_AUS),
        "dateien": sum(1 for d in dokumente if not d.ist_link),
        "videos": sum(1 for d in dokumente if d.ist_link),
    }
