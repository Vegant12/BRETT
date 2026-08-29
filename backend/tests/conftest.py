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

import json
import os
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

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

# Phase 2: `app.main` imports `app.mcp.server`, which calls `get_settings()` and
# `streamable_http_app()` at IMPORT time. These values must already be in the
# environment when the `client` fixture performs its lazy `from app.main import
# app`, which is why the seeding fixture below is session-scoped and autouse.
#
# `testserver` is `TestClient`'s default `base_url` host. Omit it from the
# allowlist and every MCP request in the suite returns `421 Invalid Host header`
# instead of the status the test is asserting on (RESEARCH Pitfall 2).
_TEST_MCP_ENV = {
    "MCP_AUTH_SECRET": "test-mcp-secret-not-a-real-credential",
    "MCP_AUTH_MODE": "static",
    "MCP_ALLOWED_HOSTS": "testserver,localhost,127.0.0.1",
    "MCP_RESOURCE_URL": "http://testserver/mcp",
    "MCP_ISSUER_URL": "https://example.authkit.app",
}

# Applied at MODULE scope, not from the fixture below, and that is load-bearing.
# `test_secret_redaction.py` does `from app.main import app` at ITS module scope,
# which runs during pytest's COLLECTION phase -- and collection finishes before
# any session-scoped fixture is entered. `app.main` imports `app.mcp.server`,
# which calls `build_token_verifier()` and `streamable_http_app()` at import, so
# whichever module imports it first freezes the verifier's secret and the Host
# allowlist for the entire session. Seed too late and the run dies at collection
# with `RuntimeError: MCP_AUTH_SECRET is required to start the MCP server`; seed
# only *some* of these and it dies more quietly, with every MCP request
# returning `421 Invalid Host header` because `testserver` never made it into
# `MCP_ALLOWED_HOSTS`. pytest imports a conftest before collecting the test
# modules beside it, so this is the earliest available hook.
#
# `setdefault`, never assignment: a developer's real environment still wins,
# matching `_default_database_url`'s intent.
_PREEXISTING_MCP_ENV = {key: os.environ.get(key) for key in _TEST_MCP_ENV}
for _key, _value in _TEST_MCP_ENV.items():
    os.environ.setdefault(_key, _value)


HEVY_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "hevy"


def hevy_fixture(name: str) -> dict[str, Any]:
    """Load a canned Hevy response.

    These files are transcribed from Hevy's LIVE OpenAPI document, not from
    `BRETT blueprint.md` -- the blueprint is wrong about `rir`, `weight_unit`, and
    about exercises/sets having ids. Regenerating them by hand from the blueprint
    would reintroduce exactly the schema drift this phase exists to eliminate.
    """
    payload: dict[str, Any] = json.loads(
        (HEVY_FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8")
    )
    return payload


# ---------------------------------------------------------------------------
# Mocking Hevy: `pytest-httpx2` is a thin adapter over `respx`, and respx asserts
# internally that a mocked response is an `httpx` (0.x) `Response`. The client under
# test is `httpx2`. The rule, verified the hard way:
#
#     RESPONSES use httpx.Response   (the 0.x package, dev-only, pulled in by respx)
#     EXCEPTIONS use httpx2 types    (httpx2.ConnectError, httpx2.ReadTimeout, ...)
#
# Passing `httpx2.Response(429)` into `side_effect` fails with a bare
# `AssertionError: assert isinstance(resolved.response, httpx.Response)` from inside
# respx/router.py, with nothing pointing at the type as the cause.
# ---------------------------------------------------------------------------


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


@pytest.fixture(scope="session", autouse=True)
def _default_mcp_env() -> Iterator[None]:
    """Undo the module-scope MCP seeding when the session ends.

    Only the teardown half lives here. The seeding itself has to happen at
    import time (see the block beside `_TEST_MCP_ENV`), because a fixture --
    even a session-scoped autouse one -- runs strictly after collection, and
    collection is when `app.mcp.server` is first imported and frozen.

    Mirrors `_default_database_url` on the way out: anything a developer's real
    environment already supplied is left exactly as found. `test_config.py`
    clears all of these per-test via its own `_clean_env`, so seeding does not
    weaken the assertions on default values there.
    """
    yield
    for key, was_preexisting in _PREEXISTING_MCP_ENV.items():
        if was_preexisting is None:
            os.environ.pop(key, None)


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

    The lazy import is doubly load-bearing from Phase 2 on: ``app.main`` imports
    ``app.mcp.server``, which builds the MCP ASGI app at import time from these
    settings. ``_default_mcp_env`` is session-scoped and autouse, so it has
    already run by the time this line executes.
    """
    from fastapi.testclient import TestClient

    from app.main import app
    from app.mcp.server import mcp

    # `StreamableHTTPSessionManager.run()` refuses a second call on the same
    # instance ("can only be called once per instance. Create a new instance if
    # you need to run again."), and the manager is built exactly once by
    # `streamable_http_app()` at import time. Production honours that invariant
    # for free -- one process, one lifespan -- but this fixture starts and stops
    # the same in-process app once per test, so from the SECOND client-using
    # test onward `lifespan` would raise before a single assertion ran.
    #
    # Clearing the one-shot flag is a TEST-ONLY concession, and it is a complete
    # reset: `run()`'s own `finally` already restores `_task_group`,
    # `_lifespan_state`, `_server_instances` and `_session_owners`, leaving this
    # flag as the only state standing between the manager and a clean restart.
    # Do NOT instead make `app/main.py` tolerate a repeat `run()` -- inside one
    # process that really is a bug, and it should keep crashing.
    mcp.session_manager._has_started = False

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
