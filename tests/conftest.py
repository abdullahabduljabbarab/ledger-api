import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.database as database_module
from app.database import get_db
from app.main import app
from app.models import Base

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://ledger:ledger@localhost:5432/ledger_test",
)

engine = create_engine(TEST_DATABASE_URL)
TestSession = sessionmaker(bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(engine)
    original_session_local = database_module.SessionLocal
    database_module.SessionLocal = TestSession
    yield
    database_module.SessionLocal = original_session_local
    Base.metadata.drop_all(engine)


@pytest.fixture
def db():
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db):
    def override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
