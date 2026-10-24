"""Einstiegspunkt des Studien-Hubs: FastAPI-App mit Scheduler und Oberfläche.

Entwicklung: `uvicorn app.main:app` (start.ps1, npm run dev). Produktion: StudienHub.exe (desktop.py) startet dieselbe
App in einem Thread, dazu das Symbol im Infobereich.
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import jobs, protokoll
from .config import ERWEITERUNG_ID, FRONTEND_DIST, PRODUKTION, SCHEDULER_AKTIV, SYNC_UHRZEIT, VERSION, alte_env_uebernehmen
from .db import init_db, ist_initialisiert
from .routers import (
    arbeit,
    kalender,
    ki,
    lernen,
    lvas,
    mbcloud,
    planung,
    pruefungen,
    system,
    termine,
    tiss,
    tuwel,
    wissen,
    wochenbericht,
)

log = logging.getLogger("studienhub")


def _starte_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler

    from .wochenbericht import beim_start_nachholen

    scheduler = BackgroundScheduler(timezone="Europe/Vienna")
    jobs.JOBS.update({j.id: j for j in jobs.standard_jobs(SYNC_UHRZEIT)})
    jobs.planen(scheduler)
    scheduler.start()
    beim_start_nachholen()  # Rechner war Sonntagabend aus: Sonntag später oder Montag nachholen
    jobs.nachholen()  # TISS, MB Cloud, Sicherung: verpasste tägliche Läufe jetzt
    return scheduler


def _planung_aktualisieren() -> None:
    """Beim Start: Vorschläge, die mit einer älteren Planer-Version oder anderer Kursauswahl entstanden, neu planen."""
    from .db import SessionLocal
    from .planung_service import planung_aktuell_halten

    try:
        with SessionLocal() as session:
            wochen = planung_aktuell_halten(session)
        if wochen:
            log.warning("Vorschläge neu geplant: %s", ", ".join(map(str, wochen)))
    except Exception:  # der Start darf daran nicht scheitern; Fehler sichtbar im Log
        log.exception("Vorschläge konnten beim Start nicht neu geplant werden")


@asynccontextmanager
async def lebenszyklus(app: FastAPI):
    protokoll.einrichten(datei=SCHEDULER_AKTIV)  # Tests (ohne Scheduler) schreiben keine Logdatei
    log.info("Studien-Hub %s startet (%s)", VERSION, "Produktion" if PRODUKTION else "Entwicklung")
    if SCHEDULER_AKTIV:
        try:
            alte_env_uebernehmen()
        except Exception:  # Zugangsdaten bleiben dann in der .env; Hinweis im Log
            log.exception("Zugangsdaten aus der .env konnten nicht übernommen werden")
    if not ist_initialisiert():
        init_db()
    _planung_aktualisieren()
    app.state.scheduler = _starte_scheduler() if SCHEDULER_AKTIV else None
    yield
    if app.state.scheduler:
        app.state.scheduler.shutdown(wait=False)


app = FastAPI(title="Studien-Hub", version=VERSION, lifespan=lebenszyklus)
# Aus dem Browser darf nur die Erweiterung den Hub aufrufen (feste ID aus dem `key` im Manifest; Firefox vergibt
# je Installation eine eigene moz-extension-Adresse). Die Oberfläche selbst kommt vom gleichen Ursprung.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=rf"^(chrome-extension://{ERWEITERUNG_ID}|moz-extension://[0-9a-f-]+)$",
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-Studienhub-Schluessel"],
)
for modul in (lvas, termine, arbeit, lernen, planung, pruefungen, tiss, tuwel, mbcloud, wissen, ki, wochenbericht, kalender,
              system):
    app.include_router(modul.router)


# Neuester Änderungszeitpunkt des Backend-Codes beim Laden; npm run dev erkennt daran veraltete Prozesse
CODE_STAND = max((p.stat().st_mtime for p in Path(__file__).parent.rglob("*.py")), default=0)


@app.get("/api/status", tags=["System"])
def status():
    return {"ok": True, "app": "studien-hub", "version": VERSION, "pid": os.getpid(), "code_stand": CODE_STAND}


# Gebaute Oberfläche (frontend/dist bzw. im Paket) direkt mit ausliefern, falls vorhanden
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="oberflaeche")
