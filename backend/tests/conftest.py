"""Shared test fixtures.

The central rule: **the test schema is built by ``alembic upgrade head``**, and
by nothing else. FOUND-02 makes migrations the only thing that may create
schema. Letting ``MetaData`` emit the DDL directly would also make the
``downgrade base`` criterion untestable -- there would be nothing for Alembic
to reverse.

Container-backed fixtures are session-scoped; starting Postgres per test would
dominate the runtime. Anything that touches the container must be marked
``@pytest.mark.integration`` so ``-m "not integration"`` stays fast.

Phase 4 adds ``golden_workout``, a builder for synthetic workouts, templates,
muscle mappings, overrides and extra users with exact hand-computable contents.
It obeys the never-commit rule in the strongest available form: every write is
``flush``ed, never committed, and the fixture ``rollback``s in a ``finally`` so
the shared container is untouched whether the test passes or fails. A
compensating ``DELETE`` would be weaker -- it would not run if an assertion
raised mid-test, and it could not undo rows another connection had already
observed. ``test_analytics_fixtures.py`` is the builder's self-test and proves
both halves: the rows are visible through the builder's own session, and
invisible to a second connection.
"""

import datetime as dt
import json
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.community.postgres import PostgresContainer

from app.db.models.exercise import ExerciseMuscle, ExerciseTemplate
from app.db.models.user import User
from app.db.models.workout import Workout, WorkoutExercise, WorkoutSet
from app.normalization.muscles import CanonicalMuscleGroup, MappingSource, MuscleRole
from app.normalization.resolver import set_override

# Alembic's cwd for this project is `backend/`; `alembic.ini` and `migrations/`
# both live there.
BACKEND_DIR = str(Path(__file__).resolve().parents[1])

# Mirrors the constant in migration 0002. Deliberately duplicated rather than
# imported: a migration must not be imported by application or test code, and a
# test asserting against the very value it imports would prove nothing.
DEFAULT_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

# A second user, for the ASVS V4 cross-tenant scoping tests. Distinct from
# `test_normalization_mapping.py`'s SECOND_USER_ID: the container is
# session-scoped and shared, and two modules reusing one id would let one
# module's cleanup delete the other's fixtures.
ANALYTICS_SECOND_USER_ID = uuid.UUID("00000000-0000-0000-0000-0000000004e2")

# Fixture ids for this phase are prefixed so they cannot collide with the
# `RESOLVER-*` ids `test_normalization_mapping.py` writes or the `hevy-*` ids
# the sync tests write.
ANALYTICS_ID_PREFIX = "ANALYTICS"

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


# ---------------------------------------------------------------------------
# Phase 4: golden analytics fixtures.
#
# Every Phase 4 calculation is verified against synthetic workouts whose answer
# was computed by hand. That only works if the workout the test *describes* and
# the rows the database *holds* are the same thing, which is what
# `test_analytics_fixtures.py` exists to prove.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GoldenSet:
    """One synthetic set. Every field maps 1:1 to a ``workout_sets`` column.

    Defaults are all-None on purpose: a ``duration`` set is
    ``GoldenSet(duration_seconds=60)`` and a ``reps_only`` set is
    ``GoldenSet(reps=12)``, so a fixture cannot accidentally acquire a weight
    the modality does not have.

    ``weight_kg`` is a ``Decimal``, never a ``float``: these sum into tonnage,
    and binary floating point would make two arithmetically identical weekly
    totals compare unequal.
    """

    set_type: str = "normal"
    weight_kg: Decimal | None = None
    reps: int | None = None
    distance_meters: Decimal | None = None
    duration_seconds: int | None = None
    rpe: Decimal | None = None


@dataclass(frozen=True, slots=True)
class GoldenExercise:
    """One synthetic exercise within a workout."""

    template_external_id: str
    sets: Sequence[GoldenSet] = ()
    supersets_id: int | None = None
    title: str = "Fixture Exercise"


class GoldenBuilder:
    """Builds synthetic analytics fixtures with exact, hand-computable contents.

    Writes with explicit Core statements, mirroring
    ``app/integrations/hevy/workouts.py``, and FLUSHES rather than commits. The
    analytics function under test receives the SAME ``AsyncSession``, so it sees
    the flushed rows inside the open transaction -- which is why every analytics
    function takes ``session: AsyncSession`` and not an ``async_sessionmaker``.
    A function that opened its own session would run in a different transaction
    and see none of this.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._workout_seq = 0

    async def user(self, *, user_id: uuid.UUID, timezone: str = "Asia/Jakarta") -> uuid.UUID:
        """Add a second (third, ...) user, so cross-tenant scoping is testable.

        A single-user suite cannot detect a missing ``user_id`` predicate: every
        row belongs to the only user, so an unscoped query returns the right
        answer by accident.
        """
        if user_id == DEFAULT_USER_ID:
            raise ValueError(
                "the seeded default user already exists: migration 0002 inserts it, and a "
                "second insert would violate the primary key"
            )
        await self._session.execute(insert(User).values(id=user_id, timezone=timezone))
        await self._session.flush()
        return user_id

    async def template(
        self,
        *,
        external_id: str,
        exercise_type: str = "weight_reps",
        title: str | None = None,
        muscles: Sequence[tuple[CanonicalMuscleGroup, MuscleRole]] = (),
        user_id: uuid.UUID = DEFAULT_USER_ID,
    ) -> str:
        """One ``exercise_templates`` row plus its canonical ``exercise_muscles`` base set.

        The enum's ``.value`` is stored, never the enum object: both columns are
        ``String``, and the resolver converts back on read.
        """
        await self._session.execute(
            insert(ExerciseTemplate).values(
                id=uuid.uuid4(),
                user_id=user_id,
                provider="hevy",
                external_id=external_id,
                title=title or external_id,
                exercise_type=exercise_type,
                # The RAW Hevy strings stay empty: this builder writes the
                # CANONICAL mapping directly, because the resolver is what Phase
                # 4 reads and translating Hevy's taxonomy here would test the
                # translation twice and the resolver not at all.
                primary_muscle_group=None,
                secondary_muscle_groups=[],
                equipment_category=None,
                is_custom=False,
            )
        )
        if muscles:
            await self._session.execute(
                insert(ExerciseMuscle),
                [
                    {
                        "id": uuid.uuid4(),
                        "user_id": user_id,
                        "exercise_template_external_id": external_id,
                        "muscle_group": muscle_group.value,
                        "role": role.value,
                        "source": MappingSource.CURATED.value,
                    }
                    for muscle_group, role in muscles
                ],
            )
        await self._session.flush()
        return external_id

    async def override(
        self,
        *,
        external_id: str,
        muscles: Sequence[tuple[CanonicalMuscleGroup, MuscleRole]],
        user_id: uuid.UUID = DEFAULT_USER_ID,
    ) -> int:
        """Replace a template's mapping, via the resolver's own writer.

        Delegates to ``app.normalization.resolver.set_override`` rather than
        inserting ``exercise_muscle_overrides`` rows by hand. The
        delete-then-insert replacement semantics must have exactly one
        implementation; a second copy here is how the fixture and the resolver
        would eventually disagree, and the fixture would then be certifying the
        wrong answer.
        """
        written = await set_override(
            self._session,
            user_id=user_id,
            template_external_id=external_id,
            assignments=list(muscles),
            note="analytics fixture",
        )
        await self._session.flush()
        return written

    async def workout(
        self,
        *,
        start_time: dt.datetime,
        exercises: Sequence[GoldenExercise],
        user_id: uuid.UUID = DEFAULT_USER_ID,
        title: str = "Fixture Workout",
        external_id: str | None = None,
        duration_minutes: int = 60,
    ) -> uuid.UUID:
        """One workout and its whole exercise/set tree. Returns the workout id."""
        if start_time.tzinfo is None:
            # Mirrors `app/core/time.py::_require_aware` (FOUND-04). A naive
            # instant would silently mis-bucket every week-boundary fixture, and
            # a fixture that lies about which week it is in makes the golden
            # answer wrong rather than the test red.
            raise ValueError("naive start_time rejected: fixtures must be timezone-aware UTC")

        self._workout_seq += 1
        workout_id = uuid.uuid4()
        resolved_external_id = external_id or f"{ANALYTICS_ID_PREFIX}-W{self._workout_seq:03d}"

        await self._session.execute(
            insert(Workout).values(
                id=workout_id,
                user_id=user_id,
                provider="hevy",
                external_id=resolved_external_id,
                title=title,
                description=None,
                routine_external_id=None,
                start_time=start_time,
                end_time=start_time + dt.timedelta(minutes=duration_minutes),
                provider_created_at=start_time,
                provider_updated_at=start_time,
            )
        )

        for exercise_index, exercise in enumerate(exercises):
            exercise_id = uuid.uuid4()
            await self._session.execute(
                insert(WorkoutExercise).values(
                    id=exercise_id,
                    workout_id=workout_id,
                    exercise_index=exercise_index,
                    title=exercise.title,
                    notes=None,
                    exercise_template_external_id=exercise.template_external_id,
                    # `0` is a real superset group, so this is passed through
                    # verbatim and never tested for truthiness.
                    supersets_id=exercise.supersets_id,
                )
            )
            if exercise.sets:
                # executemany, matching the sync path: `workout_sets` is by far
                # the highest-cardinality table these fixtures write.
                await self._session.execute(
                    insert(WorkoutSet),
                    [
                        {
                            "id": uuid.uuid4(),
                            "workout_exercise_id": exercise_id,
                            "set_index": set_index,
                            "set_type": golden_set.set_type,
                            "weight_kg": golden_set.weight_kg,
                            "reps": golden_set.reps,
                            "distance_meters": golden_set.distance_meters,
                            "duration_seconds": golden_set.duration_seconds,
                            "rpe": golden_set.rpe,
                            "custom_metric": None,
                        }
                        for set_index, golden_set in enumerate(exercise.sets)
                    ],
                )

        await self._session.flush()
        return workout_id


@pytest_asyncio.fixture
async def golden_workout(session: AsyncSession) -> AsyncIterator[GoldenBuilder]:
    """A builder whose every write is rolled back, pass or fail.

    Rollback rather than a compensating DELETE for two reasons, both verified in
    this suite: it survives an assertion failure mid-test, and
    ``test_migrations.py`` asserts ``count(*) == 1`` on ``users`` from a SEPARATE
    connection, which cannot see uncommitted rows at all.
    """
    try:
        yield GoldenBuilder(session)
    finally:
        await session.rollback()


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
