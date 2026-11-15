"""Shared pytest fixtures: an isolated SQLite database and a TestClient."""

from __future__ import annotations

import os

# Configuration must be in place before the application package is imported.
os.environ["ENVIRONMENT"] = "test"
os.environ["SECRET_KEY"] = "test-secret-key-that-is-long-enough-for-hs256"
os.environ["IP_HASH_PEPPER"] = "test-pepper"
os.environ["BASE_URL"] = "http://testserver"
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["REDIS_URL"] = ""
os.environ["RATE_LIMIT_CREATE_PER_MINUTE"] = "1000"
os.environ["RATE_LIMIT_AUTH_PER_MINUTE"] = "1000"
os.environ["CACHE_TTL_SECONDS"] = "300"
os.environ["TRUSTED_PROXY"] = "false"

import warnings
from collections.abc import Iterator

warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient`.*")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.cache import link_cache  # noqa: E402
from app.core.database import Base, get_db  # noqa: E402
from app.core.rate_limit import limiter  # noqa: E402
from app.main import app  # noqa: E402

USER_PASSWORD = "quiet-forest-42"


@pytest.fixture(autouse=True)
def _clean_runtime_state() -> Iterator[None]:
    """Keep the in-process cache and rate limiter clean between tests."""
    link_cache.clear()
    limiter.reset()
    yield
    link_cache.clear()
    limiter.reset()


@pytest.fixture()
def engine() -> Iterator[Engine]:
    """Create a throwaway in-memory database with the full schema."""
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(test_engine)
    yield test_engine
    Base.metadata.drop_all(test_engine)
    test_engine.dispose()


@pytest.fixture()
def session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a session factory bound to the throwaway database."""
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Yield a direct database session for assertions and setup."""
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def client(session_factory: sessionmaker[Session]) -> Iterator[TestClient]:
    """Return a TestClient wired to the throwaway database."""

    def override_get_db() -> Iterator[Session]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, base_url="http://testserver") as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def registered_user(client: TestClient) -> dict:
    """Register a primary account and return the auth payload."""
    response = client.post(
        "/api/auth/register",
        json={"email": "user@example.com", "password": USER_PASSWORD},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture()
def auth(registered_user: dict) -> dict[str, str]:
    """Return an Authorization header for the primary account."""
    return {"Authorization": f"Bearer {registered_user['access_token']}"}


@pytest.fixture()
def other_auth(client: TestClient) -> dict[str, str]:
    """Register a second account and return its Authorization header."""
    response = client.post(
        "/api/auth/register",
        json={"email": "stranger@example.com", "password": USER_PASSWORD},
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture()
def make_link(client: TestClient):
    """Return a factory that creates links through the API."""

    def factory(headers: dict[str, str] | None = None, **overrides) -> dict:
        payload = {"url": "https://example.com/landing/page?utm_source=tests"}
        payload.update(overrides)
        response = client.post("/api/links", json=payload, headers=headers or {})
        return response

    return factory
