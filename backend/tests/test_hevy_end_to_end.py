"""mock-Hevy -> PostgreSQL -> normalized state, in one run (ROADMAP Phase 3 criteria 1-5).

Every other Hevy test in this suite covers one driver. This one covers the composition: a
single `sync_all` against a fully mocked Hevy, then a second `sync_all` that must take the
incremental path, against a real Postgres container.

Mocking rule (conftest, Pitfall 3): RESPONSES use `httpx.Response` (0.x, the type respx
asserts on); EXCEPTIONS use `httpx2` types.

Cleanup is a per-test `finally` rather than a fixture teardown: the container is session-scoped
and shared, so a row that outlives its test changes the result of the next one.
"""

import io
import json
import logging
from typing import Any

import httpx  # 0.x -- respx asserts on this type for RESPONSES (conftest, Pitfall 3)
import pytest
import sqlalchemy as sa
import structlog
from pydantic import SecretStr
from respx import Route, Router
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config import Settings
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
    RESOURCE_BODY_MEASUREMENTS,
    RESOURCE_EXERCISE_TEMPLATES,
    RESOURCE_WORKOUTS,
    STATUS_ERROR,
    STATUS_IDLE,
    SYNC_RESOURCES,
    get_sync_state,
)
from app.integrations.hevy.client import HevyClient
from app.integrations.hevy.errors import HevyServerError
from app.integrations.hevy.sync import HevySyncService
from app.logging import configure_logging
from app.normalization.resolver import effective_muscles
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

# Never connected to. `configure_logging` needs a `Settings`, and `Settings` needs a URL.
DB_URL = "postgresql://u:pw@localhost:5432/db"

# One workout title and two body-composition values, exactly as the fixtures carry them.
# `test_no_health_data_reaches_the_log_stream` asserts none of the three survives into a line.
HEALTH_DATA_IN_FIXTURES = ("Push Day", "80.5", "18.5")

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
    """Serve every endpoint the FULL path reaches, repeatably.

    The events feed is deliberately NOT registered here: respx asserts every registered route
    was called, so a run that legitimately never goes incremental would fail on teardown for
    a route it was right not to touch. `_mock_events` is opted into by the tests that drain.

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

    def _serve_templates(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=hevy_fixture("exercise_templates_page1"))

    def _serve_body(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=hevy_fixture("body_measurements_page1"))

    # `/v1/workouts/count` is registered FIRST: respx resolves routes in registration order,
    # and a `/v1/workouts` route added ahead of it would be the one that answered.
    return {
        "count": mock.get(WORKOUT_COUNT).mock(side_effect=_serve_count),
        "workouts": mock.get(WORKOUTS).mock(side_effect=_serve_workouts),
        "templates": mock.get(TEMPLATES).mock(side_effect=_serve_templates),
        "body": mock.get(MEASUREMENTS).mock(side_effect=_serve_body),
    }


def _mock_events(mock: Router) -> Route:
    """Serve `/v1/workouts/events` with the canned edit-and-delete feed."""

    def _serve_events(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=hevy_fixture("workout_events_page1"))

    return mock.get(EVENTS).mock(side_effect=_serve_events)


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


async def _state(maker: async_sessionmaker[AsyncSession], resource: str) -> SyncState | None:
    async with maker() as session:
        return await get_sync_state(
            session, user_id=DEFAULT_USER_ID, provider=PROVIDER_HEVY, resource=resource
        )


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
async def test_sync_all_populates_the_canonical_mapping(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """NORM-01 proven through the FULL stack rather than in isolation.

    `test_hevy_templates.py` already asserts the deltoid split against the template driver.
    This asserts it against the composition and through the override resolver -- the path
    Phase 4 will actually take -- because a mapping that is written correctly and then
    resolved incorrectly is indistinguishable from no mapping at all.
    """
    maker = _maker(engine)
    _mock_hevy(httpx2_mock)
    try:
        async with _client() as client:
            await _service(client, maker).sync_all()

        async with maker() as session:
            lateral = await effective_muscles(
                session, user_id=DEFAULT_USER_ID, template_external_id=LATERAL_RAISE
            )
            bench = await effective_muscles(
                session, user_id=DEFAULT_USER_ID, template_external_id=BENCH_PRESS
            )

        # Hevy says `shoulders`; a lateral raise is frontal-plane abduction, so the SIDE head
        # is the one that works and it is the only one reported.
        assert [
            (muscle.muscle_group.value, muscle.role.value, muscle.source.value)
            for muscle in lateral
        ] == [("side_delts", "direct", "curated")]

        # The same flat `shoulders` bucket, as a SECONDARY on a press, is front-delt work.
        assert ("front_delts", "indirect") in [
            (muscle.muscle_group.value, muscle.role.value) for muscle in bench
        ]
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
    _mock_events(httpx2_mock)
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


@pytest.mark.integration
async def test_incremental_run_applies_the_edit_and_the_deletion(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """HEVY-02 and HEVY-04 through the composition, with the other two resources as controls.

    The controls are the point: an incremental workout run must not disturb templates or body
    measurements, and asserting their counts are unchanged is the only way to notice if the
    event path ever started deleting outside its own resource.
    """
    maker = _maker(engine)
    _mock_hevy(httpx2_mock)
    _mock_events(httpx2_mock)
    try:
        async with _client() as client:
            service = _service(client, maker)
            await service.sync_all()
            after_full = await _counts(maker)
            await service.sync_all()

        async with maker() as session:
            rows = (
                await session.execute(
                    sa.select(Workout.external_id, Workout.title).where(*_SCOPED)
                )
            ).all()

        assert [(row.external_id, row.title) for row in rows] == [
            (WORKOUT_A, "Push Day (edited)")
        ], "the edit was not applied, or the deletion did not remove workout B"

        after_incremental = await _counts(maker)
        assert after_incremental["exercise_templates"] == after_full["exercise_templates"]
        assert after_incremental["exercise_muscles"] == after_full["exercise_muscles"]
        assert after_incremental["body_measurements"] == after_full["body_measurements"]
    finally:
        await _cleanup(maker)


@pytest.mark.integration
async def test_full_sync_is_idempotent_end_to_end(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """HEVY-03 across every table at once, with `mode="full"` forced on both runs.

    Each driver has its own idempotency test. This one exists because the failure it catches
    is a composition failure: two drivers that are individually idempotent can still
    accumulate if one re-creates rows the other counts.
    """
    maker = _maker(engine)
    _mock_hevy(httpx2_mock)
    try:
        async with _client() as client:
            service = _service(client, maker)
            await service.sync_all(mode="full")
            first = await _counts(maker)
            await service.sync_all(mode="full")
            second = await _counts(maker)

        assert first == second, f"a second full sync changed the row counts: {first} -> {second}"
        # Guards against the trivial pass where both runs wrote nothing at all.
        assert all(first[table] > 0 for table in TABLES), f"the first full sync wrote {first}"
    finally:
        await _cleanup(maker)


@pytest.mark.integration
async def test_a_failing_resource_does_not_roll_back_a_completed_one(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """HEVY-08 at the composition level, and the reason `sync_all` has no exception handling.

    Templates are synced first and succeed; workouts then fail permanently. The templates'
    `last_synced_at` must survive -- a service that caught the workout failure and reported a
    green run would be claiming freshness for a resource that never ran, and one that rolled
    back would throw away a page of work that was already committed.

    The body route is deliberately not registered: it must never be reached.
    """
    maker = _maker(engine)
    httpx2_mock.get(TEMPLATES).mock(
        side_effect=lambda _request: httpx.Response(
            200, json=hevy_fixture("exercise_templates_page1")
        )
    )
    httpx2_mock.get(WORKOUT_COUNT).mock(
        side_effect=lambda _request: httpx.Response(200, json={"workout_count": 2})
    )
    httpx2_mock.get(WORKOUTS).mock(side_effect=lambda _request: httpx.Response(500))
    try:
        async with _client(max_attempts=2) as client:
            with pytest.raises(HevyServerError):
                await _service(client, maker).sync_all()

        counts = await _counts(maker)
        assert counts["exercise_templates"] == 4, "the completed resource was rolled back"
        assert counts["workouts"] == 0
        assert counts["body_measurements"] == 0, "the sync continued past a hard failure"

        templates = await _state(maker, RESOURCE_EXERCISE_TEMPLATES)
        assert templates is not None
        assert templates.status == STATUS_IDLE
        assert templates.last_synced_at is not None, "HEVY-08: a completed resource stays fresh"

        workouts = await _state(maker, RESOURCE_WORKOUTS)
        assert workouts is not None
        assert workouts.status == STATUS_ERROR
        assert workouts.last_synced_at is None

        # The resource that never started has no row at all, which `status()` reports as
        # `never` rather than omitting.
        assert await _state(maker, RESOURCE_BODY_MEASUREMENTS) is None
    finally:
        await _cleanup(maker)


@pytest.mark.integration
async def test_no_health_data_reaches_the_log_stream(
    engine: AsyncEngine, httpx2_mock: Router, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Blueprint 44 and ASVS V8: sync lifecycle logs carry counts, pages and dates. They must
    never carry a workout title or a body-composition value."""
    maker = _maker(engine)
    _mock_hevy(httpx2_mock)
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("HEVY_API_KEY", HEVY_KEY)
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    try:
        # The real pipeline, rendered into a buffer -- NOT `structlog.testing`, which clears
        # the configured processor chain for its duration and would leave this test green
        # over a redaction layer that never ran (test_secret_redaction.py's Pitfall 6).
        configure_logging(Settings(_env_file=None))
        buffer = io.StringIO()
        handler = root.handlers[0]
        assert isinstance(handler, logging.StreamHandler)
        handler.setStream(buffer)

        async with _client() as client:
            await _service(client, maker).sync_all()

        out = buffer.getvalue()
    finally:
        root.handlers, root.level = saved_handlers, saved_level
        structlog.reset_defaults()
        await _cleanup(maker)

    entries = [json.loads(line) for line in out.splitlines() if line.strip()]
    # Without this the test would pass trivially on an empty buffer, which is exactly what a
    # mis-wired capture produces.
    assert any(entry["event"] == "hevy_sync_all_completed" for entry in entries)

    # `timestamp` is dropped before the scan: its microsecond field is an unconstrained
    # six-digit number that will eventually contain one of these strings by chance, and a
    # suite that goes red once a fortnight teaches people to re-run it rather than read it.
    scanned = json.dumps([
        {key: value for key, value in entry.items() if key != "timestamp"} for entry in entries
    ])
    for value in HEALTH_DATA_IN_FIXTURES:
        assert value not in scanned, f"T-03-46 violated: {value!r} reached the log stream"
    assert HEVY_KEY not in scanned, "FOUND-05 violated: the api-key reached the log stream"
