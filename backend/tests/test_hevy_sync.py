"""HEVY-01 / HEVY-03 / HEVY-09 against a real Postgres container.

SQLite would prove nothing here: ON CONFLICT, ON DELETE CASCADE and TIMESTAMPTZ are exactly
what these assertions are about.

Only the HTTP transport is mocked. The pagination loop, the upsert, the child replacement and
the checkpoint writes are all real.

The sync path commits by design, so every test cleans up in a `finally`. The container is
session-scoped and shared, and `test_migrations` asserts `count(*) == 1` on `users` -- a leaked
row breaks a later test for a reason that has nothing to do with that test.
"""

import io
import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
from typing import Any

import httpx  # 0.x -- respx asserts on this type for RESPONSES (conftest, Pitfall 3)
import pytest
import sqlalchemy as sa
import structlog
from pydantic import SecretStr
from respx import Route, Router
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from app.db.models import SyncState, Workout, WorkoutExercise, WorkoutSet
from app.db.repositories.sync_state import (
    PROVIDER_HEVY,
    RESOURCE_WORKOUTS,
    get_sync_state,
)
from app.db.session import make_sessionmaker
from app.integrations.hevy.client import HevyClient
from app.integrations.hevy.schemas import HevyWorkout, PaginatedWorkouts
from app.integrations.hevy.workouts import (
    delete_workout,
    persist_workout_page,
    sync_workouts,
    upsert_workout,
)
from app.logging import configure_logging
from tests.conftest import DEFAULT_USER_ID, hevy_fixture

PROVIDER = "hevy"

BASE = "https://api.hevyapp.com"
WORKOUTS = f"{BASE}/v1/workouts"
WORKOUT_COUNT = f"{BASE}/v1/workouts/count"

# Overflows `Numeric(7, 3)` (precision 7, scale 3 -- four integer digits at most), so the
# INSERT fails inside PostgreSQL rather than inside a mock somebody wrote.
OVERFLOW_WEIGHT = 99999999


async def _no_sleep(_seconds: float) -> None:
    """Collapse tenacity's backoff to nothing.

    The retry PREDICATE and the attempt count stay entirely real; only the 1-3 real seconds
    each failure test would otherwise spend waiting are removed.
    """


def _client() -> HevyClient:
    """The real client with the real retry policy, over a mocked socket."""
    return HevyClient(SecretStr("test-key"), max_attempts=2, sleep=_no_sleep)


def _mock_pages(mock: Router, payloads: Mapping[int, dict[str, Any]], *, remote_count: int) -> Route:
    """Serve `/v1/workouts` by requested page, plus `/v1/workouts/count`.

    A CALLABLE side_effect rather than a list of responses: the idempotency test walks the same
    pages three times, and a pre-built `httpx.Response` is a one-shot object whose stream is
    consumed on first use.
    """

    def _count(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"workout_count": remote_count})

    def _serve(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        assert page in payloads, f"the sync requested page {page}, which was not mocked"
        return httpx.Response(200, json=payloads[page])

    mock.get(WORKOUT_COUNT).mock(side_effect=_count)
    return mock.get(WORKOUTS).mock(side_effect=_serve)


@contextmanager
def _rendered_logs(monkeypatch: pytest.MonkeyPatch) -> Iterator[io.StringIO]:
    """Capture what the REAL logging pipeline writes, redaction layers included.

    Not `structlog.testing.capture_logs`: that helper replaces the configured processor chain
    for its duration, so both redaction layers would be absent and a leak could not be observed
    (test_secret_redaction.py, Pitfall 6). Mirrors `test_hevy_client.py`.
    """
    monkeypatch.setenv("ENVIRONMENT", "production")
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    try:
        configure_logging(Settings(_env_file=None))
        buffer = io.StringIO()
        handler = root.handlers[0]
        assert isinstance(handler, logging.StreamHandler)
        handler.setStream(buffer)
        yield buffer
    finally:
        root.handlers, root.level = saved_handlers, saved_level
        structlog.reset_defaults()


def _workouts(name: str) -> list[HevyWorkout]:
    return PaginatedWorkouts.model_validate(hevy_fixture(name)).workouts


def _workout(name: str, index: int = 0) -> HevyWorkout:
    return _workouts(name)[index]


def _raw_workout(name: str, index: int = 0) -> dict[str, Any]:
    payload: dict[str, Any] = deepcopy(hevy_fixture(name)["workouts"][index])
    return payload


async def _counts(engine: AsyncEngine) -> tuple[int, int, int]:
    """`(workouts, workout_exercises, workout_sets)` reachable from this user's Hevy rows."""
    scoped = (Workout.user_id == DEFAULT_USER_ID, Workout.provider == PROVIDER)
    async with engine.connect() as conn:
        workouts = await conn.scalar(
            sa.select(sa.func.count()).select_from(Workout).where(*scoped)
        )
        exercises = await conn.scalar(
            sa.select(sa.func.count())
            .select_from(WorkoutExercise)
            .join(Workout, Workout.id == WorkoutExercise.workout_id)
            .where(*scoped)
        )
        sets = await conn.scalar(
            sa.select(sa.func.count())
            .select_from(WorkoutSet)
            .join(WorkoutExercise, WorkoutExercise.id == WorkoutSet.workout_exercise_id)
            .join(Workout, Workout.id == WorkoutExercise.workout_id)
            .where(*scoped)
        )
    return (workouts or 0, exercises or 0, sets or 0)


async def _cleanup(engine: AsyncEngine) -> None:
    """Remove everything this module's tests can have committed.

    The workout delete takes its exercises and sets with it by FK cascade, which is the same
    mechanism `delete_workout` relies on -- so a cleanup that leaked children would also be
    evidence the cascade is wrong.
    """
    async with engine.begin() as conn:
        await conn.execute(
            sa.delete(Workout).where(
                Workout.user_id == DEFAULT_USER_ID, Workout.provider == PROVIDER
            )
        )
        await conn.execute(
            sa.delete(SyncState).where(
                SyncState.user_id == DEFAULT_USER_ID, SyncState.provider == PROVIDER
            )
        )


@pytest.mark.integration
async def test_upsert_is_idempotent_across_three_runs(engine: AsyncEngine) -> None:
    """HEVY-03: three writes of the same payload leave one workout, two exercises, three sets.

    Three rather than two, deliberately. Two runs would pass even if the second silently
    replaced the row wholesale; the third catches a delete-then-insert that only works once.
    """
    sessionmaker = make_sessionmaker(engine)
    workout = _workout("workouts_page1")
    try:
        observed = []
        for _ in range(3):
            async with sessionmaker() as session:
                await upsert_workout(session, user_id=DEFAULT_USER_ID, workout=workout)
                await session.commit()
            observed.append(await _counts(engine))

        assert observed == [(1, 2, 3)] * 3
    finally:
        await _cleanup(engine)


@pytest.mark.integration
async def test_upsert_replaces_children_when_a_set_is_removed(engine: AsyncEngine) -> None:
    """An edited workout with FEWER sets must shrink, not accumulate.

    This is the whole reason children are delete-and-reinserted rather than upserted on
    `(workout_id, index)`. A per-child upsert leaves the surplus row behind, and every volume
    and tonnage figure Phase 4 computes from it is inflated forever -- silently, because the
    workout still looks correct in every other respect.
    """
    sessionmaker = make_sessionmaker(engine)
    raw = _raw_workout("workouts_page1")
    edited = deepcopy(raw)
    # Drop the `index: 1` working set from Bench Press, leaving only the warmup.
    edited["exercises"][0]["sets"] = [edited["exercises"][0]["sets"][0]]

    try:
        async with sessionmaker() as session:
            await upsert_workout(
                session, user_id=DEFAULT_USER_ID, workout=HevyWorkout.model_validate(raw)
            )
            await session.commit()
        assert await _counts(engine) == (1, 2, 3)

        async with sessionmaker() as session:
            await upsert_workout(
                session, user_id=DEFAULT_USER_ID, workout=HevyWorkout.model_validate(edited)
            )
            await session.commit()

        assert await _counts(engine) == (1, 2, 2)
        async with engine.connect() as conn:
            surviving = await conn.scalar(
                sa.select(sa.func.count())
                .select_from(WorkoutSet)
                .where(WorkoutSet.set_index == 1)
            )
        assert surviving == 0, "an orphan set survived the shrink and will inflate Phase 4 volume"
    finally:
        await _cleanup(engine)


@pytest.mark.integration
async def test_delete_workout_cascades_and_leaves_siblings(engine: AsyncEngine) -> None:
    """HEVY-04: deleting one workout takes its own children and nothing else."""
    sessionmaker = make_sessionmaker(engine)
    first = _workout("workouts_page1")
    second = _workout("workouts_page2")
    try:
        async with sessionmaker() as session:
            await persist_workout_page(session, user_id=DEFAULT_USER_ID, workouts=[first, second])
            await session.commit()
        assert await _counts(engine) == (2, 3, 4)

        async with sessionmaker() as session:
            removed = await delete_workout(
                session, user_id=DEFAULT_USER_ID, external_id=first.id
            )
            await session.commit()

        assert removed is True
        # Exactly page 2's workout, its one exercise and its one set are left standing.
        assert await _counts(engine) == (1, 1, 1)
        async with engine.connect() as conn:
            survivor = await conn.scalar(
                sa.select(Workout.external_id).where(Workout.user_id == DEFAULT_USER_ID)
            )
        assert survivor == second.id
    finally:
        await _cleanup(engine)


@pytest.mark.integration
async def test_delete_unknown_workout_is_a_noop(engine: AsyncEngine) -> None:
    """A deletion for a workout we never stored is information, not an error.

    The events feed can report a deletion for a workout created and deleted between two of our
    syncs. Raising here would fail a drain over a workout that never existed locally.
    """
    sessionmaker = make_sessionmaker(engine)
    try:
        async with sessionmaker() as session:
            removed = await delete_workout(
                session, user_id=DEFAULT_USER_ID, external_id="never-synced"
            )
            await session.commit()
        assert removed is False
    finally:
        await _cleanup(engine)


@pytest.mark.integration
async def test_malformed_workout_is_skipped_and_the_page_commits(engine: AsyncEngine) -> None:
    """Pitfall 11: without a SAVEPOINT, one bad row poisons every statement after it.

    The failure is real -- a weight that genuinely overflows `Numeric(7, 3)` -- so this asserts
    against PostgreSQL's actual transaction-abort semantics rather than against a Python
    exception someone invented.
    """
    sessionmaker = make_sessionmaker(engine)
    bad_raw = _raw_workout("workouts_page1")
    bad_raw["id"] = "bad-workout-0001"
    bad_raw["exercises"][0]["sets"][0]["weight_kg"] = OVERFLOW_WEIGHT
    bad = HevyWorkout.model_validate(bad_raw)
    good = _workout("workouts_page2")

    try:
        async with sessionmaker() as session:
            result = await persist_workout_page(
                session, user_id=DEFAULT_USER_ID, workouts=[bad, good]
            )
            await session.commit()

        assert result.skipped == (bad.id,)
        assert result.upserted == 1
        # The good workout that came AFTER the failure is what proves the savepoint: without
        # one, its INSERT dies with "current transaction is aborted".
        assert await _counts(engine) == (1, 1, 1)
    finally:
        await _cleanup(engine)


@pytest.mark.integration
async def test_full_sync_paginates_across_two_pages(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """HEVY-01: the driver walks every page, not just the first.

    Hevy caps `pageSize` at 10, so "did it follow `page_count`?" is the difference between a
    full history and the ten most recent sessions.
    """
    _mock_pages(
        httpx2_mock,
        {1: hevy_fixture("workouts_page1"), 2: hevy_fixture("workouts_page2")},
        remote_count=2,
    )
    sessionmaker = make_sessionmaker(engine)
    try:
        async with _client() as client:
            result = await sync_workouts(client, sessionmaker, user_id=DEFAULT_USER_ID)

        assert result.pages_fetched == 2
        assert result.workouts_upserted == 2
        assert await _counts(engine) == (2, 3, 4)
    finally:
        await _cleanup(engine)


@pytest.mark.integration
async def test_last_synced_at_is_set_and_status_is_idle(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """HEVY-09: freshness is what tells Claude the data may be stale.

    `cursor_page is None` is the other half: a completed full sync has no page to resume from,
    and leaving one behind would make the NEXT run skip everything before it.
    """
    _mock_pages(
        httpx2_mock,
        {1: hevy_fixture("workouts_page1"), 2: hevy_fixture("workouts_page2")},
        remote_count=2,
    )
    sessionmaker = make_sessionmaker(engine)
    try:
        async with _client() as client:
            await sync_workouts(client, sessionmaker, user_id=DEFAULT_USER_ID)

        async with sessionmaker() as session:
            state = await get_sync_state(
                session,
                user_id=DEFAULT_USER_ID,
                provider=PROVIDER_HEVY,
                resource=RESOURCE_WORKOUTS,
            )
        assert state is not None
        assert state.status == "idle"
        assert state.last_synced_at is not None
        assert state.cursor_page is None
        assert state.last_error is None
    finally:
        await _cleanup(engine)


@pytest.mark.integration
async def test_count_mismatch_logs_but_does_not_raise(
    engine: AsyncEngine, httpx2_mock: Router, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-09: a reconciliation gap is information, not a failure.

    Raising here would mark a perfectly good sync as an error and, worse, leave the cursor
    behind for a "resume" that has nothing to resume. The log line is the deliverable.
    """
    _mock_pages(
        httpx2_mock,
        {1: hevy_fixture("workouts_page1"), 2: hevy_fixture("workouts_page2")},
        remote_count=99,
    )
    sessionmaker = make_sessionmaker(engine)
    try:
        with _rendered_logs(monkeypatch) as buffer:
            async with _client() as client:
                result = await sync_workouts(client, sessionmaker, user_id=DEFAULT_USER_ID)
            rendered = buffer.getvalue()

        assert result.local_count == 2
        assert result.remote_count == 99
        assert "hevy_workout_count_mismatch" in rendered

        async with sessionmaker() as session:
            state = await get_sync_state(
                session,
                user_id=DEFAULT_USER_ID,
                provider=PROVIDER_HEVY,
                resource=RESOURCE_WORKOUTS,
            )
        assert state is not None
        assert state.status == "idle"
    finally:
        await _cleanup(engine)
