"""Einstiegspunkt des Studien-Hubs: FastAPI-App mit Scheduler und Oberfläche."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import FRONTEND_DIST, SCHEDULER_AKTIV, SYNC_UHRZEIT
from .db import init_db
from .routers import arbeit, kalender, lvas, termine, tiss


def _starte_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler(timezone="Europe/Vienna")
    scheduler.add_job(tiss.taeglicher_sync, "cron", hour=SYNC_UHRZEIT, id="tiss-sync", replace_existing=True)
    scheduler.start()
    return scheduler


@asynccontextmanager
async def lebenszyklus(app: FastAPI):
    init_db()
    scheduler = _starte_scheduler() if SCHEDULER_AKTIV else None
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title="Studien-Hub", version="0.1.0", lifespan=lebenszyklus)
for modul in (lvas, termine, arbeit, tiss, kalender):
    app.include_router(modul.router)


@app.get("/api/status", tags=["System"])
def status():
    return {"ok": True}


# Gebaute Oberfläche (frontend/dist) direkt mit ausliefern, falls vorhanden
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="oberflaeche")
