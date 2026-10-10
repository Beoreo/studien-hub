"""Gemeinsame Test-Fixtures: frische In-Memory-Datenbank pro Test."""

import os

os.environ["STUDIENHUB_DB_URL"] = "sqlite://"
os.environ["STUDIENHUB_SCHEDULER"] = "0"
# Tests dürfen nie in den echten Unterlagen-Ordner schreiben
os.environ["STUDIENHUB_UNTERLAGEN"] = __import__("tempfile").mkdtemp(prefix="studienhub-test-")

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, init_db  # noqa: E402

BEISPIELE = Path(__file__).parent / "beispiele"


@pytest.fixture
def session():
    engine = init_db("sqlite://")
    with SessionLocal() as s:
        yield s
    Base.metadata.drop_all(engine)


@pytest.fixture
def client(session):
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def tiss_ics() -> bytes:
    return (BEISPIELE / "tiss.ics").read_bytes()
