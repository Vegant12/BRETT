"""mock-Hevy -> PostgreSQL -> normalized state, in one run (ROADMAP Phase 3 criteria 1-5).

Every other Hevy test in this suite covers one driver. This one covers the composition: a
single `sync_all` against a fully mocked Hevy, then a second `sync_all` that must take the
incremental path, against a real Postgres container.

Mocking rule (conftest, Pitfall 3): RESPONSES use `httpx.Response` (0.x, the type respx
asserts on); EXCEPTIONS use `httpx2` types.

Cleanup is a per-test `finally` rather than a fixture teardown: the container is session-scoped
and shared, so a row that outlives its test changes the result of the next one.
"""

from typing import Any

import httpx  # 0.x -- respx asserts on this type for RESPONSES (conftest, Pitfall 3)
import pytest
import sqlalchemy as sa
from pydantic import SecretStr
from respx import Route, Router
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.models import (
    BodyMeasurement,
    ExerciseMuscle,
    ExerciseMuscleOverride,
    ExerciseTemplate,
    SyncState,
    Workout,
    WorkoutExercise,
    WorkoutSet,
)
from app.db.repositories.sync_state import (
    PROVIDER_HEVY,
    STATUS_IDLE,
    SYNC_RESOURCES,
)
from app.integrations.hevy.client import HevyClient
from app.integrations.hevy.sync import HevySyncService
from tests.conftest import DEFAULT_USER_ID, hevy_fixture

BASE = "https://api.hevyapp.com"
WORKOUTS = f"{BASE}/v1/workouts"
WORKOUT_COUNT = f"{BASE}/v1/workouts/count"
EVENTS = f"{BASE}/v1/workouts/events"
TEMPLATES = f"{BASE}/v1/exercise_templates"
MEASUREMENTS = f"{BASE}/v1/body_measurements"

WORKOUT_A = "11111111-1111-1111-1111-111111111111"
WORKOUT_B = "22222222-2222-2222-2222-222222222222"

BENCH_PRESS = "05293BCA"
LATERAL_RAISE = "D04AC939"

# Distinctive on purpose, so a leak is unambiguous rather than a coincidence.
HEVY_KEY = "hevy-key-end-to-end-must-not-be-logged"

# Every table this composition writes, so "idempotent" can be asserted as a whole rather
# than one table at a time.
TABLES = (
    "workouts",
    "workout_exercises",
    "workout_sets",
    "exercise_templates",
    "exercise_muscles",
    "body_measurements",
)

_SCOPED = (Workout.user_id == DEFAULT_USER_ID, Workout.provider == PROVIDER_HEVY)


async def _no_sleep(_seconds: float) -> None:
    """Collapse tenacity's backoff. The predicate and the attempt count stay real."""


def _client(**kwargs: Any) -> HevyClient:
    return HevyClient(SecretStr(HEVY_KEY), sleep=_no_sleep, **kwargs)


def _maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


def _service(client: HevyClient, maker: async_sessionmaker[AsyncSession]) -> HevySyncService:
    return HevySyncService(client, maker, user_id=DEFAULT_USER_ID)


def _both_workout_pages() -> dict[int, dict[str, Any]]:
    return {1: hevy_fixture("workouts_page1"), 2: hevy_fixture("workouts_page2")}


def _mock_hevy(
    mock: Router,
    *,
    workout_pages: dict[int, dict[str, Any]] | None = None,
    remote_count: int = 2,
) -> dict[str, Route]:
    """Serve every endpoint `sync_all` can reach, repeatably.

    CALLABLE side effects rather than a list of pre-built responses: an `httpx.Response` is a
    one-shot object whose stream is consumed on first use, and every test here runs the whole
    composition at least twice.
    """
    pages = workout_pages if workout_pages is not None else _both_workout_pages()

    def _serve_workouts(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        assert page in pages, f"the sync requested workouts page {page}, which was not mocked"
        return httpx.Response(200, json=pages[page])

    def _serve_count(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"workout_count": remote_count})

    def _serve_events(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=hevy_fixture("workout_events_page1"))

    def _serve_templates(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=hevy_fixture("exercise_templates_page1"))

    def _serve_body(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=hevy_fixture("body_measurements_page1"))

    # `/v1/workouts/count` is registered FIRST: respx resolves routes in registration order,
    # and a `/v1/workouts` route added ahead of it would be the one that answered.
    return {
        "count": mock.get(WORKOUT_COUNT).mock(side_effect=_serve_count),
        "workouts": mock.get(WORKOUTS).mock(side_effect=_serve_workouts),
        "events": mock.get(EVENTS).mock(side_effect=_serve_events),
        "templates": mock.get(TEMPLATES).mock(side_effect=_serve_templates),
        "body": mock.get(MEASUREMENTS).mock(side_effect=_serve_body),
    }


async def _cleanup(maker: async_sessionmaker[AsyncSession]) -> None:
    """Remove every row this module can have committed, pass or fail."""
    async with maker() as session:
        for statement in (
            sa.delete(Workout).where(Workout.user_id == DEFAULT_USER_ID),
            sa.delete(ExerciseMuscle).where(ExerciseMuscle.user_id == DEFAULT_USER_ID),
            sa.delete(ExerciseMuscleOverride).where(
                ExerciseMuscleOverride.user_id == DEFAULT_USER_ID
            ),
            sa.delete(ExerciseTemplate).where(ExerciseTemplate.user_id == DEFAULT_USER_ID),
            sa.delete(BodyMeasurement).where(BodyMeasurement.user_id == DEFAULT_USER_ID),
            sa.delete(SyncState).where(
                SyncState.user_id == DEFAULT_USER_ID, SyncState.provider == PROVIDER_HEVY
            ),
        ):
            await session.execute(statement)
        await session.commit()


async def _counts(maker: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    """Row counts for every table the composition writes, keyed by table name."""
    async with maker() as session:
        values = {
            "workouts": await session.scalar(
                sa.select(sa.func.count()).select_from(Workout).where(*_SCOPED)
            ),
            "workout_exercises": await session.scalar(
                sa.select(sa.func.count())
                .select_from(WorkoutExercise)
                .join(Workout, Workout.id == WorkoutExercise.workout_id)
                .where(*_SCOPED)
            ),
            "workout_sets": await session.scalar(
                sa.select(sa.func.count())
                .select_from(WorkoutSet)
                .join(WorkoutExercise, WorkoutExercise.id == WorkoutSet.workout_exercise_id)
                .join(Workout, Workout.id == WorkoutExercise.workout_id)
                .where(*_SCOPED)
            ),
            "exercise_templates": await session.scalar(
                sa.select(sa.func.count())
                .select_from(ExerciseTemplate)
                .where(ExerciseTemplate.user_id == DEFAULT_USER_ID)
            ),
            "exercise_muscles": await session.scalar(
                sa.select(sa.func.count())
                .select_from(ExerciseMuscle)
                .where(ExerciseMuscle.user_id == DEFAULT_USER_ID)
            ),
            "body_measurements": await session.scalar(
                sa.select(sa.func.count())
                .select_from(BodyMeasurement)
                .where(BodyMeasurement.user_id == DEFAULT_USER_ID)
            ),
        }
    return {table: values[table] or 0 for table in TABLES}


@pytest.mark.integration
async def test_sync_all_on_a_virgin_database_takes_the_full_path(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """ROADMAP criteria 1, 3 and 4 in one call: templates, workouts and body, from nothing.

    `mode="auto"` against a database with no `last_synced_at` anywhere must resolve to the
    FULL workout path -- the events feed pages at 10 and is designed for deltas, so reaching
    for it here would be a history import through the wrong endpoint.
    """
    maker = _maker(engine)
    _mock_hevy(httpx2_mock)
    try:
        async with _client() as client:
            report = await _service(client, maker).sync_all()

        assert report.mode == "full"
        assert report.workouts_full is not None
        assert report.workouts_incremental is None, "a virgin database took the events path"
        assert report.templates is not None
        assert report.body is not None

        counts = await _counts(maker)
        assert counts["workouts"] == 2
        assert counts["workout_sets"] == 4
        assert counts["exercise_templates"] == 4
        assert counts["body_measurements"] == 2
    finally:
        await _cleanup(maker)


@pytest.mark.integration
async def test_status_reports_all_three_resources(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """HEVY-09 / ROADMAP criterion 5, in ONE call rather than three ad-hoc queries.

    Sorted by resource so the output is deterministic; a status report that reordered itself
    between runs would be undiffable.
    """
    maker = _maker(engine)
    _mock_hevy(httpx2_mock)
    try:
        async with _client() as client:
            service = _service(client, maker)
            await service.sync_all()
            statuses = await service.status()

        assert [entry.resource for entry in statuses] == sorted(SYNC_RESOURCES)
        assert all(entry.last_synced_at is not None for entry in statuses)
        assert all(entry.status == STATUS_IDLE for entry in statuses)
        assert all(entry.last_error is None for entry in statuses)
    finally:
        await _cleanup(maker)


@pytest.mark.integration
async def test_second_sync_all_takes_the_incremental_path(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """ROADMAP criterion 2. The switch is `last_synced_at`, and the proof is the wire.

    Asserted on the RECORDED REQUESTS, not only on the report: a service that reported
    `incremental` while still walking `/v1/workouts?page=` would satisfy the dataclass and
    still re-import the whole history on every run.
    """
    maker = _maker(engine)
    _mock_hevy(httpx2_mock)
    try:
        async with _client() as client:
            service = _service(client, maker)
            await service.sync_all()
            before = len(httpx2_mock.calls)
            report = await service.sync_all()

        assert report.mode == "incremental"
        assert report.workouts_incremental is not None
        assert report.workouts_full is None

        second_run = [call.request for call in httpx2_mock.calls[before:]]
        assert second_run, "the second run made no requests at all"
        paged = [
            request
            for request in second_run
            if request.url.path == "/v1/workouts" and "page" in request.url.params
        ]
        assert not paged, "the second run re-walked the full workout pages"
    finally:
        await _cleanup(maker)
