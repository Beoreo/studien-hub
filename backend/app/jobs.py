"""Geplante Läufe: Zeitplan, Protokoll (letzter Start/Ende/Fehler je Job) und Nachholen verpasster Läufe.

Tägliche Jobs mit `nachholen` laufen beim Start sofort, wenn ihr letzter planmäßiger Zeitpunkt seit dem letzten Lauf
verstrichen ist (Laptop war aus). Der Stand je Job steht in der Einstellung `job:<id>` (JSON), damit die Status-Seite
und das Symbol im Infobereich ihn zeigen können.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Callable

from .db import SessionLocal
from .models import lies_einstellung, setze_einstellung

log = logging.getLogger("studienhub.jobs")


@dataclass(frozen=True)
class Job:
    id: str
    name: str
    funktion: Callable[[], object]
    taeglich: time | None = None  # Uhrzeit des täglichen Laufs
    intervall_minuten: int | None = None
    woechentlich: tuple[str, int] | None = None  # (Wochentag „sun“, Stunde) – Nachholen regelt der Job selbst
    nachholen: bool = False


def _tiss():
    from .routers.tiss import taeglicher_sync

    taeglicher_sync()


def _mbcloud():
    from .routers.mbcloud import taeglicher_lauf

    taeglicher_lauf()


def _sicherung():
    from .sicherung import taegliche_sicherung

    taegliche_sicherung()


def _verarbeitung():
    from .verarbeitung import verarbeitungs_lauf

    verarbeitungs_lauf()


def _transkription():
    from .verarbeitung import transkriptions_lauf

    transkriptions_lauf()


def _wochenbericht():
    from .wochenbericht import sonntagslauf

    sonntagslauf()


def _wochenbericht_stunde() -> int:
    from .wochenbericht import STUNDE

    return STUNDE


def standard_jobs(sync_stunde: int = 6) -> list[Job]:
    return [
        Job("tiss-sync", "TISS-Import", _tiss, taeglich=time(sync_stunde), nachholen=True),
        # MB Cloud nach dem TISS-Import (neue LVAs sind dann schon da); nur wenn verbunden
        Job("mbcloud", "MB Cloud", _mbcloud, taeglich=time(sync_stunde, 30), nachholen=True),
        Job("sicherung", "Sicherung der Datenbank", _sicherung, taeglich=time(12), nachholen=True),
        # Stufe 3: Unterlagen lesen/einbetten, Videos transkribieren – nur wenn auf „KI verbinden“ eingeschaltet
        Job("verarbeitung", "Unterlagen aufbereiten", _verarbeitung, intervall_minuten=15),
        Job("transkription", "Videos transkribieren", _transkription, intervall_minuten=10),
        Job("wochenbericht", "Wochenbericht", _wochenbericht, woechentlich=("sun", _wochenbericht_stunde())),
    ]


JOBS: dict[str, Job] = {j.id: j for j in standard_jobs()}
_laufend: set[str] = set()
_sperre = threading.Lock()


def _schluessel(job_id: str) -> str:
    return f"job:{job_id}"


def stand(job_id: str) -> dict:
    with SessionLocal() as session:
        roh = lies_einstellung(session, _schluessel(job_id))
    return json.loads(roh) if roh else {}


def _merken(job_id: str, **werte) -> None:
    with SessionLocal() as session:
        roh = lies_einstellung(session, _schluessel(job_id))
        daten = {**(json.loads(roh) if roh else {}), **werte}
        setze_einstellung(session, _schluessel(job_id), json.dumps(daten, ensure_ascii=False))
        session.commit()


def ausfuehren(job_id: str) -> bool:
    """Führt einen Job aus und protokolliert ihn. False, wenn er gerade schon läuft."""
    job = JOBS[job_id]
    with _sperre:
        if job_id in _laufend:
            return False
        _laufend.add(job_id)
    start = datetime.now()
    try:
        _merken(job_id, letzter_start=start.isoformat(timespec="seconds"))
        job.funktion()
        _merken(job_id, letztes_ende=datetime.now().isoformat(timespec="seconds"), fehler=None)
    except Exception as fehler:  # ein Job darf die anderen nie mitreißen; Fehler sichtbar in Status und Log
        log.exception("Job „%s“ fehlgeschlagen", job.name)
        _merken(job_id, letztes_ende=datetime.now().isoformat(timespec="seconds"),
                fehler={"zeit": datetime.now().isoformat(timespec="seconds"), "meldung": str(fehler)[:500]})
    finally:
        with _sperre:
            _laufend.discard(job_id)
    return True


def im_hintergrund(job_id: str) -> None:
    threading.Thread(target=ausfuehren, args=(job_id,), name=f"job-{job_id}", daemon=True).start()


def laeuft(job_id: str) -> bool:
    return job_id in _laufend


def letzter_planzeitpunkt(job: Job, jetzt: datetime) -> datetime | None:
    """Wann der tägliche Job zuletzt hätte laufen sollen (heute, falls die Uhrzeit schon vorbei ist, sonst gestern)."""
    if job.taeglich is None:
        return None
    heute = datetime.combine(jetzt.date(), job.taeglich)
    return heute if jetzt >= heute else heute - timedelta(days=1)


def verpasst(job: Job, jetzt: datetime, letzter_start: datetime | None) -> bool:
    soll = letzter_planzeitpunkt(job, jetzt)
    return job.nachholen and soll is not None and (letzter_start is None or letzter_start < soll)


def nachholen(jetzt: datetime | None = None, starten: Callable[[str], None] = im_hintergrund) -> list[str]:
    """Startet alle verpassten täglichen Läufe (der Reihe nach in einem Hintergrund-Thread je Job)."""
    jetzt = jetzt or datetime.now()
    faellig = []
    for job in JOBS.values():
        start = stand(job.id).get("letzter_start")
        if verpasst(job, jetzt, datetime.fromisoformat(start) if start else None):
            faellig.append(job.id)
    for job_id in faellig:
        log.info("Verpassten Lauf nachholen: %s", JOBS[job_id].name)
        starten(job_id)
    return faellig


def planen(scheduler) -> None:
    """Alle Jobs im APScheduler eintragen; verpasste Zeitpunkte holt `nachholen` nach, nicht der Scheduler."""
    for job in JOBS.values():
        if job.taeglich:
            ausloeser = {"trigger": "cron", "hour": job.taeglich.hour, "minute": job.taeglich.minute}
        elif job.intervall_minuten:
            ausloeser = {"trigger": "interval", "minutes": job.intervall_minuten}
        else:
            tag, stunde = job.woechentlich
            ausloeser = {"trigger": "cron", "day_of_week": tag, "hour": stunde}
        scheduler.add_job(ausfuehren, args=[job.id], id=job.id, replace_existing=True, max_instances=1,
                          coalesce=True, misfire_grace_time=600, **ausloeser)


def uebersicht(scheduler=None) -> list[dict]:
    """Für die Status-Seite: je Job Name, läuft gerade, letzter Lauf, Fehler, nächster geplanter Lauf."""
    ergebnis = []
    for job in JOBS.values():
        geplant = scheduler.get_job(job.id) if scheduler else None
        naechster = geplant.next_run_time if geplant else None
        bisher = stand(job.id)
        ergebnis.append({
            "id": job.id,
            "name": job.name,
            "laeuft": laeuft(job.id),
            "letzter_start": bisher.get("letzter_start"),
            "letztes_ende": bisher.get("letztes_ende"),
            "fehler": bisher.get("fehler"),
            "naechster_lauf": naechster.replace(tzinfo=None).isoformat(timespec="seconds") if naechster else None,
        })
    return ergebnis
