"""HEVY-01 / HEVY-03 / HEVY-09 against a real Postgres container.

SQLite would prove nothing here: ON CONFLICT, ON DELETE CASCADE and TIMESTAMPTZ are exactly
what these assertions are about.

Only the HTTP transport is mocked. The pagination loop, the upsert, the child replacement and
the checkpoint writes are all real.

The sync path commits by design, so every test cleans up in a `finally`. The container is
session-scoped and shared, and `test_migrations` asserts `count(*) == 1` on `users` -- a leaked
row breaks a later test for a reason that has nothing to do with that test, and a `finally` is
strictly stronger than a compensating delete because it also survives a mid-test assertion
failure.
"""

import io
import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
from decimal import Decimal
from typing import Any

import httpx  # 0.x -- respx asserts on this type for RESPONSES (conftest, Pitfall 3)
import pytest
import sqlalchemy as sa
import structlog
from pydantic import SecretStr
from respx import Route, Router
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from app.db.models import (
    ExerciseTemplate,
    SyncState,
    Workout,
    WorkoutExercise,
    WorkoutSet,
)
from app.db.repositories.sync_state import (
    PROVIDER_HEVY,
    RESOURCE_WORKOUTS,
    get_sync_state,
)
from app.db.session import make_sessionmaker
from app.integrations.hevy.client import HevyClient
from app.integrations.hevy.workouts import delete_workout, sync_workouts
from app.logging import configure_logging
from tests.conftest import DEFAULT_USER_ID, hevy_fixture

PROVIDER = "hevy"

BASE = "https://api.hevyapp.com"
WORKOUTS = f"{BASE}/v1/workouts"
WORKOUT_COUNT = f"{BASE}/v1/workouts/count"

PAGE_1_WORKOUT = "11111111-1111-1111-1111-111111111111"
PAGE_2_WORKOUT = "22222222-2222-2222-2222-222222222222"

# A full-UUID template id, i.e. one of Hevy's CUSTOM templates -- the case D-03 is about,
# because a custom template can be deleted upstream and never appear in a template sync.
UNMAPPED_TEMPLATE_ID = "b459cba5-cd6d-463c-abd6-54f8eafcadcb"


# --- fixtures and mocks ----------------------------------------------------


async def _no_sleep(_seconds: float) -> None:
    """Collapse tenacity's backoff to nothing.

    The retry PREDICATE and the attempt count stay entirely real; only the pause between
    attempts is removed, so a failure test costs milliseconds instead of seconds.
    """


def _client() -> HevyClient:
    """The real client with the real retry policy, over a mocked socket."""
    return HevyClient(SecretStr("test-key"), max_attempts=2, sleep=_no_sleep)


def _raw_workout(name: str, index: int = 0) -> dict[str, Any]:
    payload: dict[str, Any] = deepcopy(hevy_fixture(name)["workouts"][index])
    return payload


def _one_page(workout: dict[str, Any]) -> dict[str, Any]:
    """A `page_count: 1` envelope, so the driver stops after the workout under test."""
    return {"page": 1, "page_count": 1, "workouts": [workout]}


def _both_pages() -> Mapping[int, dict[str, Any]]:
    return {1: hevy_fixture("workouts_page1"), 2: hevy_fixture("workouts_page2")}


def _mock_pages(
    mock: Router, payloads: Mapping[int, dict[str, Any]], *, remote_count: int
) -> Route:
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


# --- database readers ------------------------------------------------------

_SCOPED = (Workout.user_id == DEFAULT_USER_ID, Workout.provider == PROVIDER)


async def _counts(engine: AsyncEngine) -> tuple[int, int, int]:
    """`(workouts, workout_exercises, workout_sets)` reachable from this user's Hevy rows."""
    async with engine.connect() as conn:
        workouts = await conn.scalar(
            sa.select(sa.func.count()).select_from(Workout).where(*_SCOPED)
        )
        exercises = await conn.scalar(
            sa.select(sa.func.count())
            .select_from(WorkoutExercise)
            .join(Workout, Workout.id == WorkoutExercise.workout_id)
            .where(*_SCOPED)
        )
        sets = await conn.scalar(
            sa.select(sa.func.count())
            .select_from(WorkoutSet)
            .join(WorkoutExercise, WorkoutExercise.id == WorkoutSet.workout_exercise_id)
            .join(Workout, Workout.id == WorkoutExercise.workout_id)
            .where(*_SCOPED)
        )
    return (workouts or 0, exercises or 0, sets or 0)


def _sets_of(external_id: str) -> sa.Select[Any]:
    """Every set row belonging to one Hevy workout, as a reusable subquery-free select."""
    return (
        sa.select(WorkoutSet)
        .join(WorkoutExercise, WorkoutExercise.id == WorkoutSet.workout_exercise_id)
        .join(Workout, Workout.id == WorkoutExercise.workout_id)
        .where(*_SCOPED, Workout.external_id == external_id)
    )


async def _cleanup(engine: AsyncEngine) -> None:
    """Remove everything this module's tests can have committed.

    The workout delete takes its exercises and sets with it by FK cascade, which is the same
    mechanism `delete_workout` relies on -- so a cleanup that leaked children would also be
    evidence the cascade is wrong.
    """
    async with engine.begin() as conn:
        await conn.execute(sa.delete(Workout).where(*_SCOPED))
        await conn.execute(
            sa.delete(SyncState).where(
                SyncState.user_id == DEFAULT_USER_ID, SyncState.provider == PROVIDER
            )
        )


# --- tests -----------------------------------------------------------------


@pytest.mark.integration
async def test_full_sync_paginates_across_two_pages(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """HEVY-01: the driver walks every page, not just the first.

    Hevy caps `pageSize` at 10, so "did it follow `page_count`?" is the difference between a
    full training history and the ten most recent sessions.
    """
    _mock_pages(httpx2_mock, _both_pages(), remote_count=2)
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
async def test_sync_is_idempotent_across_three_runs(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """HEVY-03: running the sync three times leaves the row counts unchanged.

    Three rather than two, deliberately. Two runs would pass even if the second silently
    replaced everything wholesale; the third catches a delete-then-insert that only works once.
    """
    _mock_pages(httpx2_mock, _both_pages(), remote_count=2)
    sessionmaker = make_sessionmaker(engine)
    try:
        observed = []
        for _ in range(3):
            async with _client() as client:
                await sync_workouts(client, sessionmaker, user_id=DEFAULT_USER_ID)
            observed.append(await _counts(engine))

        assert observed == [(2, 3, 4)] * 3
    finally:
        await _cleanup(engine)


@pytest.mark.integration
async def test_edited_workout_with_fewer_sets_shrinks(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """An edited workout with FEWER sets must shrink, not accumulate.

    This is the whole reason children are delete-and-reinserted rather than upserted on
    `(workout_id, index)`. A per-child upsert leaves the surplus row behind, and every volume,
    tonnage and PR figure Phase 4 computes from it is inflated forever -- silently, because the
    workout still looks correct in every other respect.
    """
    original = _raw_workout("workouts_page1")
    edited = deepcopy(original)
    # Drop the `index: 1` working set from Bench Press, leaving only the warmup.
    edited["exercises"][0]["sets"] = [edited["exercises"][0]["sets"][0]]

    pages: dict[int, dict[str, Any]] = {1: _one_page(original)}
    _mock_pages(httpx2_mock, pages, remote_count=1)
    sessionmaker = make_sessionmaker(engine)
    try:
        async with _client() as client:
            await sync_workouts(client, sessionmaker, user_id=DEFAULT_USER_ID)
        assert await _counts(engine) == (1, 2, 3)

        pages[1] = _one_page(edited)
        async with _client() as client:
            await sync_workouts(client, sessionmaker, user_id=DEFAULT_USER_ID)

        assert await _counts(engine) == (1, 2, 2)
        async with engine.connect() as conn:
            indexes = (await conn.scalars(_sets_of(PAGE_1_WORKOUT).with_only_columns(
                WorkoutSet.set_index
            ))).all()
        assert 1 not in indexes, "an orphan set survived and will inflate Phase 4 volume"
    finally:
        await _cleanup(engine)


@pytest.mark.integration
async def test_warmup_set_type_is_stored_verbatim(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """VOL-01 excludes exactly the string 'warmup'.

    Coercing Hevy's four set types into an `is_warmup` boolean here would look harmless and
    would break Phase 4's volume filter *and* Phase 5's dropset/failure handling silently.
    """
    _mock_pages(httpx2_mock, _both_pages(), remote_count=2)
    sessionmaker = make_sessionmaker(engine)
    try:
        async with _client() as client:
            await sync_workouts(client, sessionmaker, user_id=DEFAULT_USER_ID)

        async with engine.connect() as conn:
            types = (await conn.scalars(_sets_of(PAGE_1_WORKOUT).with_only_columns(
                WorkoutSet.set_type
            ))).all()
        assert sorted(types) == ["normal", "normal", "warmup"]
    finally:
        await _cleanup(engine)


@pytest.mark.integration
async def test_rpe_and_decimal_weight_round_trip_exactly(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """`Numeric`, never `Float`.

    Phase 4 sums thousands of these into tonnage, and `0.1 + 0.2 != 0.3` in binary floating
    point. Asserted as `Decimal` values read back OUT of PostgreSQL, not as the parsed wire
    values, because the round trip is where a Float column would lose them.
    """
    _mock_pages(httpx2_mock, _both_pages(), remote_count=2)
    sessionmaker = make_sessionmaker(engine)
    try:
        async with _client() as client:
            await sync_workouts(client, sessionmaker, user_id=DEFAULT_USER_ID)

        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    _sets_of(PAGE_1_WORKOUT)
                    .with_only_columns(WorkoutSet.weight_kg, WorkoutSet.rpe)
                    .where(WorkoutSet.set_index == 1)
                )
            ).one()

        assert row.weight_kg == Decimal("100.000")
        assert row.rpe == Decimal("9.5")
        assert isinstance(row.rpe, Decimal), "a Float column would return 9.499999999999998"
    finally:
        await _cleanup(engine)


@pytest.mark.integration
async def test_workout_metadata_is_preserved(engine: AsyncEngine, httpx2_mock: Router) -> None:
    """Blueprint 8: do not throw away useful source metadata.

    `supersets_id == 0` is the sharp case -- zero is a real superset group, so any code that
    tested it for truthiness would drop it and no other assertion here would notice.
    """
    _mock_pages(httpx2_mock, _both_pages(), remote_count=2)
    sessionmaker = make_sessionmaker(engine)
    try:
        async with _client() as client:
            await sync_workouts(client, sessionmaker, user_id=DEFAULT_USER_ID)

        async with engine.connect() as conn:
            workout = (
                await conn.execute(
                    sa.select(Workout.routine_external_id, Workout.description).where(
                        *_SCOPED, Workout.external_id == PAGE_1_WORKOUT
                    )
                )
            ).one()
            exercises = (
                await conn.execute(
                    sa.select(
                        WorkoutExercise.exercise_index,
                        WorkoutExercise.notes,
                        WorkoutExercise.supersets_id,
                    )
                    .join(Workout, Workout.id == WorkoutExercise.workout_id)
                    .where(*_SCOPED, Workout.external_id == PAGE_1_WORKOUT)
                    .order_by(WorkoutExercise.exercise_index)
                )
            ).all()

        assert workout.routine_external_id == "aaaaaaaa-0000-0000-0000-000000000001"
        assert workout.description == "Felt strong."
        assert exercises[0].notes == "Paused reps."
        assert exercises[0].supersets_id is None
        assert exercises[1].supersets_id == 0, "superset group 0 was dropped as falsy"
    finally:
        await _cleanup(engine)


@pytest.mark.integration
async def test_unmapped_template_workout_still_persists(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """D-03: a workout whose exercise template is unknown locally must still sync.

    `workout_exercises.exercise_template_external_id` is a plain string and NOT a foreign key
    for exactly this reason. A hard FK would make the sync fail on a custom template the user
    deleted upstream -- losing real training history over a missing lookup row.
    """
    unmapped = _raw_workout("workouts_page1")
    unmapped["exercises"] = [unmapped["exercises"][0]]
    unmapped["exercises"][0]["exercise_template_id"] = UNMAPPED_TEMPLATE_ID
    _mock_pages(httpx2_mock, {1: _one_page(unmapped)}, remote_count=1)
    sessionmaker = make_sessionmaker(engine)
    try:
        async with _client() as client:
            result = await sync_workouts(client, sessionmaker, user_id=DEFAULT_USER_ID)

        async with engine.connect() as conn:
            templates = await conn.scalar(
                sa.select(sa.func.count())
                .select_from(ExerciseTemplate)
                .where(ExerciseTemplate.external_id == UNMAPPED_TEMPLATE_ID)
            )
            stored = await conn.scalar(
                sa.select(WorkoutExercise.exercise_template_external_id)
                .join(Workout, Workout.id == WorkoutExercise.workout_id)
                .where(*_SCOPED, Workout.external_id == PAGE_1_WORKOUT)
            )

        assert templates == 0, "the template exists locally, so this proves nothing"
        assert stored == UNMAPPED_TEMPLATE_ID
        assert result.skipped == ()
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
    _mock_pages(httpx2_mock, _both_pages(), remote_count=2)
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

    Raising here would mark a perfectly good sync as an error and, worse, leave a cursor behind
    for a "resume" that has nothing to resume. The log line is the deliverable.
    """
    _mock_pages(httpx2_mock, _both_pages(), remote_count=99)
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


@pytest.mark.integration
async def test_delete_workout_cascades_and_leaves_siblings(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """HEVY-04: deleting one workout takes its own children and nothing else."""
    _mock_pages(httpx2_mock, _both_pages(), remote_count=2)
    sessionmaker = make_sessionmaker(engine)
    try:
        async with _client() as client:
            await sync_workouts(client, sessionmaker, user_id=DEFAULT_USER_ID)
        assert await _counts(engine) == (2, 3, 4)

        async with sessionmaker() as session:
            removed = await delete_workout(
                session, user_id=DEFAULT_USER_ID, external_id=PAGE_1_WORKOUT
            )
            await session.commit()

        assert removed is True
        # Exactly page 2's workout, its one exercise and its one set are left standing.
        assert await _counts(engine) == (1, 1, 1)
        async with engine.connect() as conn:
            survivor = await conn.scalar(sa.select(Workout.external_id).where(*_SCOPED))
        assert survivor == PAGE_2_WORKOUT
    finally:
        await _cleanup(engine)


@pytest.mark.integration
async def test_delete_unknown_workout_is_a_noop(engine: AsyncEngine) -> None:
    """A deletion for a workout we never stored is information, not an error.

    The events feed can report a deletion for a workout created and deleted between two of our
    syncs. Raising here would fail a whole drain over a workout that never existed locally.

    No HTTP fixture: this path never reaches the network, and requesting one would only assert
    that respx saw no traffic.
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
