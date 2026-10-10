"""Datenbankanbindung: Engine, Sessions und deklarative Basis."""

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import DATENBANK_URL


class Base(DeclarativeBase):
    pass


SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False)
_engine: Engine | None = None


def erstelle_engine(url: str) -> Engine:
    """Erzeugt eine SQLite-Engine mit aktivierten Fremdschlüsseln."""
    optionen: dict = {"connect_args": {"check_same_thread": False}}
    if url in ("sqlite://", "sqlite:///:memory:"):
        # In-Memory-Datenbank (Tests): eine gemeinsame Verbindung für alle Sessions
        optionen["poolclass"] = StaticPool
    elif url.startswith("sqlite:///"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, **optionen)

    @event.listens_for(engine, "connect")
    def _fremdschluessel_an(dbapi_verbindung, _):
        dbapi_verbindung.execute("PRAGMA foreign_keys=ON")

    return engine


def init_db(url: str = DATENBANK_URL) -> Engine:
    """Verbindet die Session-Fabrik mit der Datenbank und legt fehlende Tabellen an."""
    global _engine
    from . import models  # noqa: F401  – registriert die Tabellen

    _engine = erstelle_engine(url)
    SessionLocal.configure(bind=_engine)
    Base.metadata.create_all(_engine)
    return _engine


def get_session() -> Iterator[Session]:
    """FastAPI-Abhängigkeit: eine Session pro Anfrage."""
    with SessionLocal() as session:
        yield session
