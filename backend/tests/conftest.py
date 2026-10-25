import importlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app import main, worker

seed_module = importlib.import_module("app.seed")


@pytest.fixture
def database(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    test_session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(main, "Session", test_session)
    monkeypatch.setattr(worker, "Session", test_session)
    monkeypatch.setattr(seed_module, "Session", test_session)
    monkeypatch.setattr(seed_module, "engine", engine)
    yield test_session
    engine.dispose()


@pytest.fixture
def client(database):
    with TestClient(main.app) as test_client:
        yield test_client
