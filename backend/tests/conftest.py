"""Shared test fixtures.

The central rule: **the test schema is built by ``alembic upgrade head``**, and
by nothing else. FOUND-02 makes migrations the only thing that may create
schema. Letting ``MetaData`` emit the DDL directly would also make the
``downgrade base`` criterion untestable -- there would be nothing for Alembic
to reverse.

Container-backed fixtures are session-scoped; starting Postgres per test would
dominate the runtime. Anything that touches the container must be marked
``@pytest.mark.integration`` so ``-m "not integration"`` stays fast.
"""

import os
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.community.postgres import PostgresContainer

# Alembic's cwd for this project is `backend/`; `alembic.ini` and `migrations/`
# both live there.
BACKEND_DIR = str(Path(__file__).resolve().parents[1])

# Mirrors the constant in migration 0002. Deliberately duplicated rather than
# imported: a migration must not be imported by application or test code, and a
# test asserting against the very value it imports would prove nothing.
DEFAULT_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

# Syntactically valid, never connected to. Unit tests construct `Settings`
# without a container.
_PLACEHOLDER_DB_URL = "postgresql://test:test@localhost:5432/test"


@pytest.fixture(scope="session", autouse=True)
def _default_database_url() -> Iterator[None]:
    """Give non-integration tests a parseable ``DATABASE_URL``.

    ``Settings`` fails fast on a missing ``DATABASE_URL``, so unit tests that
    merely construct settings would otherwise need a container. Tests that care
    about the value override it themselves via ``monkeypatch``.
    """
    preexisting = os.environ.get("DATABASE_URL")
    if not preexisting:
        os.environ["DATABASE_URL"] = _PLACEHOLDER_DB_URL
    yield
    if not preexisting:
        os.environ.pop("DATABASE_URL", None)


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """A running Postgres container, already migrated to head.

    ``driver="asyncpg"`` is required: the default is ``psycopg2``, which is not
    a dependency of this project and would fail at URL construction.
    """
    with PostgresContainer("postgres:18-alpine", driver="asyncpg") as container:
        url = container.get_connection_url()
        # FOUND-02: schema comes from migrations. Run as a subprocess so it uses
        # the same entrypoint production does, rather than an in-process API.
        subprocess.run(  # noqa: S603
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND_DIR,
            env={**os.environ, "DATABASE_URL": url},
            check=True,
            capture_output=True,
            text=True,
        )
        yield url


@pytest.fixture(scope="session")
def alembic(postgres_url: str) -> Callable[..., subprocess.CompletedProcess[str]]:
    """Run an arbitrary alembic command against the test container.

    Deliberately does NOT pass ``check=True``: ``test_no_pending_model_drift``
    asserts on the return code, and a raised ``CalledProcessError`` would hide
    the ``alembic check`` output that explains the drift.
    """

    def _alembic(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603
            [sys.executable, "-m", "alembic", *args],
            cwd=BACKEND_DIR,
            env={**os.environ, "DATABASE_URL": postgres_url},
            capture_output=True,
            text=True,
        )

    return _alembic


@pytest.fixture
def restore_schema(
    alembic: Callable[..., subprocess.CompletedProcess[str]],
) -> Iterator[None]:
    """Guarantee the shared database is back at head after a destructive test.

    ``test_migrations_round_trip`` downgrades the session-scoped container. If
    it fails midway the database is left at ``base`` and every later test in the
    session fails for an unrelated reason, hiding the real failure.
    """
    try:
        yield
    finally:
        alembic("upgrade", "head")


@pytest_asyncio.fixture
async def engine(postgres_url: str) -> AsyncEngine:
    """A per-test engine.

    One engine per fixture scope, never a module-level global: a global binds
    its pool to whichever event loop imported it, and pytest-asyncio gives each
    test a fresh loop.
    """
    engine = create_async_engine(postgres_url)
    try:
        yield engine  # type: ignore[misc]
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncSession:
    """A per-test ORM session bound to the migrated container."""
    maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    async with maker() as db_session:
        yield db_session  # type: ignore[misc]


@pytest.fixture
def client(postgres_url: str) -> Iterator[object]:
    """``TestClient`` for the real app, wired to the test container.

    ``app.main`` is imported lazily -- it reads settings and configures logging
    at import time, so importing it at module scope would run that bootstrap
    before any test had a chance to seed the environment.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    engine = create_async_engine(postgres_url)
    try:
        # `raise_server_exceptions=False` so the D-05 handler's sanitized 500 is
        # what the test observes, instead of the exception propagating.
        with TestClient(app, raise_server_exceptions=False) as test_client:
            # Entering the context ran `lifespan`, which built its own engine
            # from `DATABASE_URL`. Override it AFTER startup -- assigning before
            # would simply be clobbered -- so `/health` probes the container.
            lifespan_engine = app.state.engine
            # `app.state.engine` is the attribute the `/health` route reads.
            app.state.engine = engine
            app.state.sessionmaker = async_sessionmaker(
                engine, expire_on_commit=False, autoflush=False
            )
            try:
                yield test_client
            finally:
                # Hand the lifespan its own engine back so shutdown disposes the
                # one it created, not the fixture's.
                app.state.engine = lifespan_engine
    finally:
        engine.sync_engine.dispose()
