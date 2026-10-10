"""Datenbankanbindung: Engine, Sessions und deklarative Basis."""

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
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
    _fehlende_spalten_ergaenzen(_engine)
    return _engine


# Spalten, die nach der ersten Version dazugekommen sind: (Tabelle, Spalte, SQL-Definition)
NACHTRAEGLICHE_SPALTEN = [
    ("arbeitsregel", "freie_tage", "JSON DEFAULT '[]'"),
    ("arbeitsregel", "max_tag_stunden", "FLOAT DEFAULT 9"),
    ("arbeitsregel", "lernfenster_minuten", "INTEGER DEFAULT 120"),
    ("arbeitsregel", "voller_unitag_stunden", "FLOAT DEFAULT 6"),
    ("arbeitsregel", "min_freie_tage", "INTEGER DEFAULT 1"),
    ("arbeitsregel", "gewichte", "JSON"),
    ("dokument", "episode_id", "VARCHAR(100)"),
    ("dokument", "aufnahme_am", "DATE"),
    ("dokument", "dauer_sekunden", "INTEGER"),
    ("dokument", "medien_url", "TEXT"),
    ("dokument", "erschienen_am", "DATETIME"),
    ("dokument", "erschienen_quelle", "VARCHAR(20)"),
    ("dokument", "seiten", "INTEGER"),
    ("dokument", "lernart", "VARCHAR(12)"),
    ("dokument", "lern_minuten", "INTEGER"),
    ("lva", "ects", "FLOAT"),
    ("lva", "lernparameter", "JSON"),
    ("arbeitsregel", "lern_min_block_minuten", "INTEGER DEFAULT 45"),
    ("arbeitsregel", "lern_max_block_minuten", "INTEGER DEFAULT 120"),
    ("arbeitsregel", "lern_tage", "JSON DEFAULT '[0, 1, 2, 3, 4, 5]'"),
    ("arbeitsregel", "ects_warnschwelle", "FLOAT DEFAULT 0.5"),
]


def _fehlende_spalten_ergaenzen(engine: Engine) -> None:
    """Minimale Migration: ergänzt neue Spalten in bestehenden SQLite-Datenbanken."""
    pruefer = inspect(engine)
    with engine.begin() as verbindung:
        for tabelle, spalte, definition in NACHTRAEGLICHE_SPALTEN:
            vorhanden = {s["name"] for s in pruefer.get_columns(tabelle)}
            if spalte not in vorhanden:
                verbindung.execute(text(f"ALTER TABLE {tabelle} ADD COLUMN {spalte} {definition}"))


def ist_initialisiert() -> bool:
    """True, wenn bereits eine Datenbank verbunden ist (z. B. die In-Memory-Datenbank der Tests)."""
    return _engine is not None


def get_session() -> Iterator[Session]:
    """FastAPI-Abhängigkeit: eine Session pro Anfrage."""
    with SessionLocal() as session:
        yield session
