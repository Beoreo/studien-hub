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
EMBEDDING_DIM = 384  # paraphrase-multilingual-MiniLM-L12-v2 (embedding.py)
VEKTORSUCHE = {"verfuegbar": False}  # sqlite-vec geladen?


def _sqlite_vec_laden(dbapi_verbindung) -> bool:
    """Lädt die sqlite-vec-Erweiterung; ohne sie arbeitet die Suche nur mit dem Volltext (FTS5)."""
    try:
        import sqlite_vec

        dbapi_verbindung.enable_load_extension(True)
        sqlite_vec.load(dbapi_verbindung)
        dbapi_verbindung.enable_load_extension(False)
        return True
    except Exception:
        return False


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
        # Hub und MCP-Server (eigener Prozess) teilen die Datei: kurz warten statt „database is locked“
        dbapi_verbindung.execute("PRAGMA busy_timeout=10000")
        if url not in ("sqlite://", "sqlite:///:memory:"):
            # WAL: Lesen (Oberfläche, MCP-Server) wird nie durch einen laufenden Schreibvorgang blockiert
            try:
                dbapi_verbindung.execute("PRAGMA journal_mode=WAL")
            except Exception:  # z. B. gerade von einem anderen Prozess exklusiv gesperrt – beim nächsten Mal
                pass
        VEKTORSUCHE["verfuegbar"] = _sqlite_vec_laden(dbapi_verbindung)

    return engine


def verbindungen_erneuern() -> None:
    """Nach dem Zurückspielen einer Sicherung: offene Verbindungen verwerfen, damit alle den neuen Stand lesen."""
    # In-Memory-Datenbank (Tests): die einzige Verbindung ist die Datenbank – nicht schließen
    if _engine is not None and _engine.url.database not in (None, "", ":memory:"):
        _engine.dispose()


def init_db(url: str = DATENBANK_URL) -> Engine:
    """Verbindet die Session-Fabrik mit der Datenbank und legt fehlende Tabellen an."""
    global _engine
    from . import models  # noqa: F401  – registriert die Tabellen

    _engine = erstelle_engine(url)
    SessionLocal.configure(bind=_engine)
    Base.metadata.create_all(_engine)
    _fehlende_spalten_ergaenzen(_engine)
    suchindex_anlegen(_engine)
    # Einmalig: Ferien-Einträge zu freien Zeiten, VO/UE/Gruppen unter einer LVA (mit Sicherungskopie)
    from .lva_struktur import beim_start_bereinigen

    beim_start_bereinigen(SessionLocal, url)
    farben_umstellen(_engine)
    pruefungen_uebernehmen(_engine)
    eigene_pruefungen_umziehen(_engine)
    return _engine


def eigene_pruefungen_umziehen(engine: Engine) -> int:
    """Früher selbst eingetragene Prüfungstage (Liste lva.eigene_pruefungen) werden eigene, angemeldete
    Prüfungstermine (9 Uhr, ohne Ende = ganztägig). Mehrfach aufrufbar."""
    with engine.begin() as verbindung:
        anzahl = verbindung.execute(text(
            "INSERT INTO pruefungstermin (lva_id, quelle, titel, start, tiss_angemeldet, angemeldet, bearbeitet, "
            "ausgeblendet, zuletzt_gesehen) "
            "SELECT DISTINCT lva.id, 'manuell', 'Prüfung', j.value || ' 09:00:00.000000', 0, 1, 0, 0, CURRENT_TIMESTAMP "
            "FROM lva, json_each(lva.eigene_pruefungen) AS j "
            "WHERE lva.eigene_pruefungen IS NOT NULL AND json_valid(lva.eigene_pruefungen)"
        )).rowcount
        verbindung.execute(text("UPDATE lva SET eigene_pruefungen = NULL WHERE eigene_pruefungen IS NOT NULL"))
    return anzahl


def pruefungen_uebernehmen(engine: Engine) -> int:
    """Früher gab es je LVA nur ein eigenes Prüfungsdatum (pruefung_am): in die Liste eigene_pruefungen übernehmen.
    Mehrfach aufrufbar."""
    with engine.begin() as verbindung:
        return verbindung.execute(text(
            "UPDATE lva SET eigene_pruefungen = json_array(pruefung_am), pruefung_am = NULL "
            "WHERE pruefung_am IS NOT NULL AND (eigene_pruefungen IS NULL OR json_array_length(eigene_pruefungen) = 0)"
        )).rowcount


def farben_umstellen(engine: Engine) -> int:
    """LVAs mit einer früheren Standardfarbe bekommen die Farbe an gleicher Stelle der neuen Palette.
    Selbst gewählte Farben bleiben; mehrfach aufrufbar."""
    from .models import ALTE_STANDARD_FARBEN, STANDARD_FARBEN

    geaendert = 0
    with engine.begin() as verbindung:
        for alt, neu in zip(ALTE_STANDARD_FARBEN, STANDARD_FARBEN):
            geaendert += verbindung.execute(
                text("UPDATE lva SET farbe = :neu WHERE lower(farbe) = :alt"), {"neu": neu, "alt": alt}
            ).rowcount
    return geaendert


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
    ("termin", "teil_id", "INTEGER REFERENCES lva_teil(id) ON DELETE SET NULL"),
    ("lva", "ects", "FLOAT"),
    ("lva", "lernparameter", "JSON"),
    ("arbeitsregel", "lern_min_block_minuten", "INTEGER DEFAULT 45"),
    ("arbeitsregel", "lern_max_block_minuten", "INTEGER DEFAULT 120"),
    ("arbeitsregel", "lern_tage", "JSON DEFAULT '[0, 1, 2, 3, 4, 5]'"),
    ("arbeitsregel", "ects_faktor", "FLOAT DEFAULT 0.7"),
    ("arbeitsregel", "lernphase_wochen", "INTEGER DEFAULT 2"),
    ("lva", "pruefung_am", "DATE"),  # veraltet, nur für pruefungen_uebernehmen
    ("lva", "eigene_pruefungen", "JSON"),
    ("lva", "ziel", "VARCHAR(10) DEFAULT 'normal'"),
    ("lva", "bedarf_faktor", "FLOAT DEFAULT 1.0"),
    ("lva", "besuchen", "BOOLEAN"),
    ("dokument", "quelle", "VARCHAR(10) DEFAULT 'tuwel'"),
    ("dokument", "kategorie", "VARCHAR(20)"),
    ("dokument", "jahr", "INTEGER"),
    ("dokument", "bearbeitet_am", "DATETIME"),
    ("dokument", "bearbeitet_minuten", "INTEGER"),
    ("dokument", "punkte", "FLOAT"),
    ("dokument", "punkte_max", "FLOAT"),
    ("dokument", "text_status", "VARCHAR(10)"),
    ("dokument", "text_pruefsumme", "VARCHAR(64)"),
    ("dokument", "text_fehler", "TEXT"),
    ("dokument", "transkript_status", "VARCHAR(10)"),
    ("dokument", "transkript_fehler", "TEXT"),
    ("lernblock", "quelle", "VARCHAR(10) DEFAULT 'hub'"),
    ("lva", "typ", "VARCHAR(12)"),
    ("lva", "lernwochen", "INTEGER"),
    ("wochenbericht", "neue_unterlagen", "INTEGER"),
    ("thema", "pruefungen", "JSON"),
]


def suchindex_anlegen(engine: Engine) -> None:
    """Volltext (FTS5) und Vektoren (sqlite-vec) zu den Abschnitten; rowid = abschnitt.id."""
    with engine.begin() as verbindung:
        verbindung.execute(text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS abschnitt_fts USING fts5(text, kapitel, tokenize='unicode61 remove_diacritics 2')"
        ))
        if VEKTORSUCHE["verfuegbar"]:
            verbindung.execute(text(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS abschnitt_vec USING vec0(embedding float[{EMBEDDING_DIM}] distance_metric=cosine)"
            ))


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
