"""MB Cloud: Index aktuell halten, Ordner zuordnen, ausgewählte Dateien herunterladen (DB-Seite zu mbcloud.py).

Ablauf eines Laufs:
1. Liste der LVA-Ordner unter `MBCLOUD_WURZEL` lesen (eine Anfrage) und jedem Ordner eine LVA zuordnen –
   sicher über die Nummer, sonst als Vorschlag. Bestätigte und abgelehnte Zuordnungen bleiben unangetastet.
2. Nur zugeordnete Ordner (sicher oder bestätigt) werden gelesen, und nur, wenn sich ihr ETag geändert hat;
   innerhalb steigt der Lauf nur in Unterordner mit geändertem ETag ab. Index = Pfad, Name, Größe, Datum, ETag.
3. Einteilung, Datum/Jahr und Verknüpfung Altprüfung–Lösung je Ordner.
4. Downloads: automatisch Altprüfungen, Lösungen und Formelsammlungen der letzten 5 Jahre für besuchte LVAs,
   eine Datei nach der anderen. Gleicher Inhalt (SHA-256) wie eine vorhandene Unterlage – auch aus TUWEL – wird
   nicht doppelt abgelegt.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path, PurePosixPath

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import MBCLOUD_WURZEL, UNTERLAGEN_ORDNER
from .lva_auswahl import besuchte_lva_ids
from .mbcloud import (
    KATEGORIE_NAMEN,
    IndexEintrag,
    LvaKandidat,
    automatisch_laden,
    datum_erkennen,
    kategorie_erkennen,
    loesungen_verknuepfen,
    ordner_zuordnen,
)
from .mbcloud_client import MbCloud
from .models import (
    DOK_NEU,
    MB_ABGELEHNT,
    MB_AUTO,
    MB_BESTAETIGT,
    MB_VORSCHLAG,
    Dokument,
    Lva,
    MbCloudDatei,
    MbCloudOrdner,
    setze_einstellung,
)
from .tiss_import import semester_von
from .tuwel_sync import lva_ordner, sicherer_name

QUELLE = "mbcloud"
DATEITYPEN = {".pdf": "pdf", ".ppt": "folien", ".pptx": "folien", ".odp": "folien", ".doc": "dokument",
              ".docx": "dokument", ".odt": "dokument"}


@dataclass
class Bericht:
    ordner: int = 0
    zugeordnet: int = 0
    vorschlaege: int = 0
    gelesen: list[str] = field(default_factory=list)
    neue_dateien: int = 0
    geaenderte_dateien: int = 0
    entfernte_dateien: int = 0
    heruntergeladen: int = 0
    duplikate: int = 0
    anfragen: int = 0
    fehler: list[str] = field(default_factory=list)


# --- Zuordnung --------------------------------------------------------------------------------------

def kandidaten(session: Session, heute: date | None = None) -> list[LvaKandidat]:
    """LVAs in Vorrang-Reihenfolge: besuchte zuerst, dann aktuelles Semester, dann neuere Semester."""
    heute = heute or date.today()
    aktuell = semester_von(datetime.combine(heute, datetime.min.time()))
    besucht = besuchte_lva_ids(session)
    lvas = sorted(session.scalars(select(Lva)),
                  key=lambda l: (l.id not in besucht, l.semester != aktuell, [-ord(c) for c in l.semester], l.id))
    return [
        LvaKandidat(l.id, l.titel, frozenset(filter(None, [l.nummer, *(t.nummer for t in l.teile)])), l.kurzname)
        for l in lvas
    ]


def zuordnen(session: Session, ordner: MbCloudOrdner, liste: list[LvaKandidat]) -> None:
    """Automatische Zuordnung; von Hand bestätigte oder abgelehnte Ordner bleiben, wie sie sind."""
    if ordner.zuordnung in (MB_BESTAETIGT, MB_ABGELEHNT):
        return
    z = ordner_zuordnen(ordner.name, liste)
    ordner.lva_id, ordner.aehnlichkeit = z.lva_id, z.aehnlichkeit
    ordner.zuordnung = None if z.lva_id is None else MB_AUTO if z.sicher else MB_VORSCHLAG


def wird_gelesen(ordner: MbCloudOrdner) -> bool:
    return ordner.lva_id is not None and ordner.zuordnung in (MB_AUTO, MB_BESTAETIGT)


# --- Index ------------------------------------------------------------------------------------------

def _einteilen(datei: MbCloudDatei, ordner_pfad: str) -> None:
    unterordner = list(PurePosixPath(datei.eltern_pfad).relative_to(ordner_pfad).parts) if datei.eltern_pfad != ordner_pfad else []
    einteilung = kategorie_erkennen(datei.name, unterordner)
    datum, jahr = datum_erkennen(datei.name, unterordner)
    datei.kategorie, datei.gedankenprotokoll, datei.datum = einteilung.kategorie, einteilung.gedankenprotokoll, datum
    datei.jahr_geschaetzt = jahr is None and datei.geaendert is not None
    datei.jahr = jahr if jahr is not None else (datei.geaendert.year if datei.geaendert else None)


def _ordner_lesen(session: Session, cloud: MbCloud, ordner: MbCloudOrdner, pfad: str, bericht: Bericht) -> None:
    """Liest einen (Unter-)Ordner; steigt nur in Unterordner mit geändertem ETag ab."""
    eintraege = cloud.liste(pfad)[1:]  # der erste Eintrag ist der Ordner selbst
    vorhanden = {d.pfad: d for d in session.scalars(select(MbCloudDatei).where(MbCloudDatei.eltern_pfad == pfad))}
    jetzt = datetime.now()
    for e in eintraege:
        datei = vorhanden.pop(e.pfad, None)
        alter_etag = datei.etag if datei else None
        if datei is None:
            datei = MbCloudDatei(ordner_id=ordner.id, pfad=e.pfad, eltern_pfad=pfad, name=e.name, ist_ordner=e.ist_ordner)
            session.add(datei)
            if not e.ist_ordner:
                bericht.neue_dateien += 1
        elif alter_etag != e.etag and not e.ist_ordner:
            bericht.geaenderte_dateien += 1
            if datei.dokument_id and not datei.duplikat:
                datei.dokument_id = None  # neue Fassung: beim nächsten Download neu holen
        datei.groesse, datei.geaendert, datei.zuletzt_gesehen = e.groesse, e.geaendert, jetzt
        if e.ist_ordner:
            if alter_etag != e.etag:
                session.flush()
                _ordner_lesen(session, cloud, ordner, e.pfad, bericht)
        else:
            _einteilen(datei, ordner.pfad)
        datei.etag = e.etag
    for weg in vorhanden.values():  # nicht mehr in der Cloud: samt Unterordner-Inhalt aus dem Index
        if weg.ist_ordner:
            bericht.entfernte_dateien += len(session.scalars(select(MbCloudDatei.id).where(
                MbCloudDatei.pfad.startswith(weg.pfad + "/"), MbCloudDatei.ist_ordner.is_(False))).all())
        else:
            bericht.entfernte_dateien += 1
        session.execute(delete(MbCloudDatei).where(MbCloudDatei.pfad.startswith(weg.pfad + "/")))
        session.delete(weg)
    session.flush()


def loesungen_neu_verknuepfen(session: Session, ordner: MbCloudOrdner) -> None:
    dateien = list(session.scalars(select(MbCloudDatei).where(MbCloudDatei.ordner_id == ordner.id, MbCloudDatei.ist_ordner.is_(False))))
    paare = loesungen_verknuepfen([IndexEintrag(d.id, d.name, d.eltern_pfad, d.kategorie, d.datum, d.jahr) for d in dateien])
    for d in dateien:
        d.loesung_zu_id = paare.get(d.id)


def index_aktualisieren(session: Session, cloud: MbCloud, heute: date | None = None) -> Bericht:
    bericht = Bericht()
    liste = kandidaten(session, heute)
    vorhanden = {o.pfad: o for o in session.scalars(select(MbCloudOrdner))}
    jetzt = datetime.now()
    for e in cloud.liste(MBCLOUD_WURZEL)[1:]:
        if not e.ist_ordner:
            continue
        ordner = vorhanden.pop(e.pfad, None) or MbCloudOrdner(pfad=e.pfad, name=e.name)
        session.add(ordner)
        ordner.name, ordner.etag, ordner.groesse, ordner.zuletzt_gesehen = e.name, e.etag, e.groesse, jetzt
        zuordnen(session, ordner, liste)
        bericht.ordner += 1
    for weg in vorhanden.values():
        session.delete(weg)
    session.flush()

    for ordner in session.scalars(select(MbCloudOrdner).order_by(MbCloudOrdner.name)):
        bericht.zugeordnet += wird_gelesen(ordner)
        bericht.vorschlaege += ordner.zuordnung == MB_VORSCHLAG
        if wird_gelesen(ordner) and ordner.etag != ordner.gelesen_etag:
            _ordner_lesen(session, cloud, ordner, ordner.pfad, bericht)
            loesungen_neu_verknuepfen(session, ordner)
            ordner.gelesen_etag = ordner.etag
            bericht.gelesen.append(ordner.name)
            session.commit()  # Fortschritt sichern: ein Abbruch kostet nur den aktuellen Ordner
    session.commit()
    bericht.anfragen = cloud.anfragen
    return bericht


# --- Downloads ---------------------------------------------------------------------------------------

def _zielpfad(session: Session, lva: Lva, datei: MbCloudDatei) -> Path:
    ordner = lva_ordner(lva) / "MB Cloud" / sicherer_name(KATEGORIE_NAMEN.get(datei.kategorie or "", "Sonstiges"), 40)
    pfad = ordner / sicherer_name(datei.name)
    if session.scalar(select(Dokument.id).where(Dokument.pfad == pfad.as_posix())):
        stamm, punkt, endung = pfad.name.rpartition(".")
        pfad = pfad.with_name(f"{stamm} ({datei.id}).{endung}" if punkt else f"{pfad.name} ({datei.id})")
    return pfad


def herunterladen(session: Session, cloud: MbCloud, datei: MbCloudDatei) -> str:
    """Lädt eine Datei; Ergebnis „neu“ oder „duplikat“ (gleicher Inhalt schon im Hub, z. B. aus TUWEL)."""
    ordner = datei.ordner
    lva = session.get(Lva, ordner.lva_id) if ordner.lva_id else None
    if lva is None:
        raise ValueError("Ordner ist keiner LVA zugeordnet")
    relativ = _zielpfad(session, lva, datei)
    ziel = UNTERLAGEN_ORDNER / relativ
    ziel.parent.mkdir(parents=True, exist_ok=True)
    pruefer, groesse = hashlib.sha256(), 0
    fd, temp = tempfile.mkstemp(dir=ziel.parent, prefix=".download.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as aus, cloud.herunterladen(datei.pfad) as bloecke:
            for block in bloecke:
                pruefer.update(block)
                groesse += len(block)
                aus.write(block)
        summe = pruefer.hexdigest()
        gleich = session.scalar(select(Dokument).where(Dokument.pruefsumme == summe))
        if gleich is not None:
            Path(temp).unlink()
            datei.dokument_id, datei.duplikat = gleich.id, True
            session.commit()
            return "duplikat"
        os.replace(temp, ziel)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise

    jetzt = datetime.now()
    doc = Dokument(
        lva_id=lva.id, tuwel_kurs_id=0, tuwel_cm_id=0, schluessel=f"{QUELLE}:{datei.pfad}"[:1000],
        abschnitt="MB Cloud", aktivitaet=KATEGORIE_NAMEN.get(datei.kategorie or "", "Sonstiges"), dateiname=datei.name,
        typ=DATEITYPEN.get(Path(datei.name).suffix.lower(), "sonstiges"), ist_link=False,
        quelle_url=f"{cloud.url}/index.php/apps/files/files?dir=/{PurePosixPath(datei.eltern_pfad).as_posix()}",
        pfad=relativ.as_posix(), pruefsumme=summe, groesse=groesse, status=DOK_NEU, quelle=QUELLE,
        kategorie=datei.kategorie, jahr=datei.jahr,
        erschienen_am=datetime.combine(datei.datum, datetime.min.time()) if datei.datum else datei.geaendert,
        erschienen_quelle="mbcloud", erstellt_am=jetzt, geaendert_am=jetzt, zuletzt_gesehen=jetzt,
    )
    # gleiche Datei schon einmal geladen (ältere Fassung): Eintrag weiterverwenden
    alt = session.scalar(select(Dokument).where(Dokument.tuwel_cm_id == 0, Dokument.schluessel == doc.schluessel))
    if alt is not None:
        for feld in ("pfad", "pruefsumme", "groesse", "kategorie", "jahr", "erschienen_am", "geaendert_am"):
            setattr(alt, feld, getattr(doc, feld))
        doc = alt
    else:
        session.add(doc)
    session.flush()
    datei.dokument_id, datei.duplikat = doc.id, False
    session.commit()
    return "neu"


def automatische_downloads(session: Session, cloud: MbCloud, heute: date | None = None,
                           hoechstens: int | None = None) -> tuple[int, int, list[str]]:
    """Altprüfungen, Lösungen, Formelsammlungen der letzten 5 Jahre für besuchte LVAs – eine nach der anderen."""
    heute = heute or date.today()
    besucht = besuchte_lva_ids(session)
    offen = [
        d for d in session.scalars(
            select(MbCloudDatei).join(MbCloudOrdner).where(
                MbCloudDatei.ist_ordner.is_(False), MbCloudDatei.dokument_id.is_(None),
                MbCloudOrdner.lva_id.in_(besucht), MbCloudOrdner.zuordnung.in_([MB_AUTO, MB_BESTAETIGT]),
            ).order_by(MbCloudDatei.jahr.desc(), MbCloudDatei.pfad)
        )
        if automatisch_laden(d.kategorie, d.jahr, heute)
    ]
    neu = duplikate = 0
    fehler = []
    for datei in offen[:hoechstens]:
        try:
            if herunterladen(session, cloud, datei) == "neu":
                neu += 1
            else:
                duplikate += 1
        except Exception as f:  # einzelne Datei: melden und weitermachen
            session.rollback()
            fehler.append(f"{datei.name}: {f}")
    return neu, duplikate, fehler


def lauf(session: Session, cloud: MbCloud, heute: date | None = None) -> Bericht:
    """Index aktualisieren und automatische Downloads; Ergebnis und Fehler landen in den Einstellungen."""
    import json

    bericht = Bericht()
    try:
        bericht = index_aktualisieren(session, cloud, heute)
        bericht.heruntergeladen, bericht.duplikate, bericht.fehler = automatische_downloads(session, cloud, heute)
        bericht.anfragen = cloud.anfragen
        setze_einstellung(session, "mbcloud_letzter_fehler", None)
    except Exception as f:
        session.rollback()
        bericht.fehler.append(str(f))
        setze_einstellung(session, "mbcloud_letzter_fehler", str(f))
    setze_einstellung(session, "mbcloud_letzter_lauf", datetime.now().isoformat(timespec="seconds"))
    setze_einstellung(session, "mbcloud_bericht", json.dumps(bericht.__dict__, ensure_ascii=False))
    session.commit()
    return bericht
