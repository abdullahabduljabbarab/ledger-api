import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.database as database_module
from app.auth import Role, TokenData, create_access_token
from app.database import get_db
from app.main import app
from app.models import Base

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql://ledger:ledger@localhost:5432/ledger_test",
)

engine = create_engine(TEST_DATABASE_URL)
TestSession = sessionmaker(bind=engine)


def _auth_header(role: Role = Role.admin) -> dict:
    token = create_access_token(TokenData(username="test", role=role))
    return {"Authorization": f"Bearer {token}"}


class AuthenticatedTestClient:
    def __init__(self, inner: TestClient, headers: dict):
        self._inner = inner
        self._headers = headers

    def get(self, url, **kwargs):
        kwargs.setdefault("headers", {}).update(self._headers)
        return self._inner.get(url, **kwargs)

    def post(self, url, **kwargs):
        kwargs.setdefault("headers", {}).update(self._headers)
        return self._inner.post(url, **kwargs)

    def put(self, url, **kwargs):
        kwargs.setdefault("headers", {}).update(self._headers)
        return self._inner.put(url, **kwargs)

    def delete(self, url, **kwargs):
        kwargs.setdefault("headers", {}).update(self._headers)
        return self._inner.delete(url, **kwargs)

    def patch(self, url, **kwargs):
        kwargs.setdefault("headers", {}).update(self._headers)
        return self._inner.patch(url, **kwargs)


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
        yield AuthenticatedTestClient(c, _auth_header(Role.admin))
    app.dependency_overrides.clear()


@pytest.fixture
def raw_client(db):
    def override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
