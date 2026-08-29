"""HEVY-02 / HEVY-04. The highest-risk logic in the phase, and the tests are the counterexample.

The naive implementation -- advance `since` while paging -- applies a handful of events,
silently drops the rest, and reports success. `test_drain_keeps_since_frozen_across_pages` and
`test_multiply_updated_workout_keeps_the_newest_payload` are the two assertions that would fail
if anyone reintroduces it.
"""

import datetime as dt
from collections.abc import Mapping
from copy import deepcopy
from decimal import Decimal
from typing import Any

import httpx  # 0.x -- respx asserts on this type for RESPONSES (conftest, Pitfall 3)
import pytest
import sqlalchemy as sa
from pydantic import SecretStr
from respx import Route, Router
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.time import utc_now
from app.db.models import SyncState, Workout, WorkoutExercise, WorkoutSet
from app.db.repositories.sync_state import (
    PROVIDER_HEVY,
    RESOURCE_WORKOUTS,
    complete_sync,
    ensure_sync_state,
    get_sync_state,
)
from app.db.session import make_sessionmaker
from app.integrations.hevy.client import HevyClient
from app.integrations.hevy.errors import HevyResponseError, HevyServerError
from app.integrations.hevy.events import drain_events, sync_workout_events
from app.integrations.hevy.schemas import (
    HevyDeletedWorkoutEvent,
    HevyUpdatedWorkoutEvent,
    PaginatedWorkoutEvents,
    event_timestamp,
)
from app.integrations.hevy.workouts import sync_workouts
from tests.conftest import DEFAULT_USER_ID, hevy_fixture

PROVIDER = "hevy"

BASE = "https://api.hevyapp.com"
EVENTS = f"{BASE}/v1/workouts/events"
WORKOUTS = f"{BASE}/v1/workouts"
WORKOUT_COUNT = f"{BASE}/v1/workouts/count"

# The two ids the shipped fixtures use, so a drain test and a full-sync test talk about the
# same workouts.
WORKOUT_A = "11111111-1111-1111-1111-111111111111"
WORKOUT_B = "22222222-2222-2222-2222-222222222222"

# Arbitrary but FIXED. `since` is the value under test in `test_drain_keeps_since_frozen_...`,
# so it must not be derived from the clock.
SINCE = dt.datetime(2026, 8, 1, tzinfo=dt.UTC)
SINCE_WIRE = "2026-08-01T00:00:00Z"

# The newest event in `workout_events_page1.json` is the DELETE, not the last item in feed
# order -- which is exactly why the cursor is a max() and not `events[-1]`.
FIXTURE_MAX_TIMESTAMP = dt.datetime(2026, 8, 5, 10, 0, tzinfo=dt.UTC)

# A pre-existing checkpoint, older than every event in the fixtures, so "the cursor moved" and
# "the cursor stayed" are distinguishable outcomes.
BASELINE_CURSOR = dt.datetime(2026, 8, 2, tzinfo=dt.UTC)


# --- fixtures and mocks ----------------------------------------------------


async def _no_sleep(_seconds: float) -> None:
    """Collapse tenacity's backoff to nothing; the retry predicate stays real."""


def _client() -> HevyClient:
    """The real client with the real retry policy, over a mocked socket."""
    return HevyClient(SecretStr("test-key"), max_attempts=2, sleep=_no_sleep)


def _updated(workout_id: str, updated_at: str, *, title: str = "Session") -> dict[str, Any]:
    """An `updated` event carrying a FULL workout snapshot, as Hevy sends it."""
    workout: dict[str, Any] = deepcopy(hevy_fixture("workouts_page1")["workouts"][0])
    workout["id"] = workout_id
    workout["title"] = title
    workout["updated_at"] = updated_at
    return {"type": "updated", "workout": workout}


def _deleted(workout_id: str, deleted_at: str) -> dict[str, Any]:
    return {"type": "deleted", "id": workout_id, "deleted_at": deleted_at}


def _events_page(page: int, page_count: int, events: list[dict[str, Any]]) -> dict[str, Any]:
    return {"page": page, "page_count": page_count, "events": events}


def _three_pages() -> Mapping[int, dict[str, Any]]:
    """Six events across three pages, in Hevy's NEWEST-FIRST order.

    Pages 2 and 3 hold the older events -- precisely the ones a drain that advanced `since`
    after page 1 would re-window itself out of and never see.
    """
    return {
        1: _events_page(
            1,
            3,
            [
                _deleted("w-a", "2026-08-09T00:00:00Z"),
                _updated("w-b", "2026-08-08T00:00:00Z"),
            ],
        ),
        2: _events_page(
            2,
            3,
            [
                _updated("w-c", "2026-08-07T00:00:00Z"),
                _deleted("w-d", "2026-08-06T00:00:00Z"),
            ],
        ),
        3: _events_page(
            3,
            3,
            [
                _updated("w-e", "2026-08-05T00:00:00Z"),
                _deleted("w-f", "2026-08-04T00:00:00Z"),
            ],
        ),
    }


def _mock_events(mock: Router, payloads: Mapping[int, dict[str, Any]]) -> Route:
    """Serve `/v1/workouts/events` by requested page.

    A CALLABLE side_effect rather than a list of responses: a pre-built `httpx.Response` is a
    one-shot object whose stream is consumed on first use, and several tests drain twice.
    """

    def _serve(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        assert page in payloads, f"the drain requested page {page}, which was not mocked"
        return httpx.Response(200, json=payloads[page])

    return mock.get(EVENTS).mock(side_effect=_serve)


def _mock_workout_pages(
    mock: Router, payloads: Mapping[int, dict[str, Any]], *, remote_count: int
) -> Route:
    """Serve the FULL-sync endpoints, so an incremental test can start from real rows.

    An incremental sync that has never had a full sync in front of it is not a scenario worth
    asserting on -- `sync_workout_events` refuses it outright (T-03-41).
    """

    def _count(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"workout_count": remote_count})

    def _serve(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        assert page in payloads, f"the sync requested page {page}, which was not mocked"
        return httpx.Response(200, json=payloads[page])

    mock.get(WORKOUT_COUNT).mock(side_effect=_count)
    return mock.get(WORKOUTS).mock(side_effect=_serve)


def _one_workout_page(index: int = 0) -> dict[str, Any]:
    """`page_count: 1` around a single fixture workout, so the full sync stops after it."""
    workout: dict[str, Any] = deepcopy(hevy_fixture("workouts_page1")["workouts"][index])
    return {"page": 1, "page_count": 1, "workouts": [workout]}


def _both_workout_pages() -> Mapping[int, dict[str, Any]]:
    return {1: hevy_fixture("workouts_page1"), 2: hevy_fixture("workouts_page2")}


# --- database helpers ------------------------------------------------------

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


def _sets_of(external_id: str, *, exercise_index: int) -> sa.Select[Any]:
    """Every set row belonging to ONE exercise of one Hevy workout."""
    return (
        sa.select(WorkoutSet.weight_kg)
        .join(WorkoutExercise, WorkoutExercise.id == WorkoutSet.workout_exercise_id)
        .join(Workout, Workout.id == WorkoutExercise.workout_id)
        .where(
            *_SCOPED,
            Workout.external_id == external_id,
            WorkoutExercise.exercise_index == exercise_index,
        )
        .order_by(WorkoutSet.set_index)
    )


async def _seed_baseline(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    cursor_timestamp: dt.datetime | None = None,
    last_synced_at: dt.datetime | None = None,
) -> None:
    """Stand in for a completed full sync.

    `sync_workout_events` refuses to drain without a baseline, so every incremental test needs
    one -- either from a real `sync_workouts` run or, where the full sync is not what is under
    test, from here.
    """
    async with sessionmaker() as session:
        await ensure_sync_state(
            session,
            user_id=DEFAULT_USER_ID,
            provider=PROVIDER_HEVY,
            resource=RESOURCE_WORKOUTS,
        )
        await complete_sync(
            session,
            user_id=DEFAULT_USER_ID,
            provider=PROVIDER_HEVY,
            resource=RESOURCE_WORKOUTS,
            last_synced_at=last_synced_at or utc_now(),
            cursor_timestamp=cursor_timestamp,
        )
        await session.commit()


async def _state(sessionmaker: async_sessionmaker[AsyncSession]) -> SyncState:
    async with sessionmaker() as session:
        state = await get_sync_state(
            session,
            user_id=DEFAULT_USER_ID,
            provider=PROVIDER_HEVY,
            resource=RESOURCE_WORKOUTS,
        )
    assert state is not None, "the sync never created its bookkeeping row"
    return state


async def _cleanup(engine: AsyncEngine) -> None:
    """Remove everything this module's tests can have committed.

    The container is session-scoped and shared, and `test_migrations` asserts `count(*) == 1`
    on `users` -- a leaked row breaks a later test for a reason that has nothing to do with
    that test. A `finally` is strictly stronger than a compensating delete because it also
    survives a mid-test assertion failure.
    """
    async with engine.begin() as conn:
        await conn.execute(sa.delete(Workout).where(*_SCOPED))
        await conn.execute(
            sa.delete(SyncState).where(
                SyncState.user_id == DEFAULT_USER_ID, SyncState.provider == PROVIDER
            )
        )


# --- the drain -------------------------------------------------------------


async def test_drain_collects_every_page_before_returning(httpx2_mock: Router) -> None:
    """Rule 2. Nothing may be applied until every page is in hand."""
    route = _mock_events(httpx2_mock, _three_pages())

    async with _client() as client:
        drain = await drain_events(client, since=SINCE)

    assert route.call_count == 3
    assert drain.pages_fetched == 3
    assert len(drain.events) == 6


async def test_drain_keeps_since_frozen_across_pages(httpx2_mock: Router) -> None:
    """Pitfall 1. Advancing the cursor mid-drain re-windows the query and permanently loses
    every page not yet fetched. It fails with no error anywhere, which is why this is a test
    and not a comment."""
    route = _mock_events(httpx2_mock, _three_pages())

    async with _client() as client:
        await drain_events(client, since=SINCE)

    sent = [call.request.url.params["since"] for call in route.calls]
    assert len(sent) == 3
    assert set(sent) == {SINCE_WIRE}, f"`since` moved during the drain: {sent}"


async def test_drain_returns_events_oldest_first(httpx2_mock: Router) -> None:
    """Rule 3. The feed arrives newest-first; the drain must hand back the reverse."""
    _mock_events(httpx2_mock, {1: hevy_fixture("workout_events_page1")})

    async with _client() as client:
        drain = await drain_events(client, since=SINCE)

    stamps = [event_timestamp(event) for event in drain.events]
    assert stamps == sorted(stamps), "events were not sorted oldest-first"
    assert stamps[-1] == FIXTURE_MAX_TIMESTAMP


async def test_drain_cursor_is_the_max_event_timestamp(httpx2_mock: Router) -> None:
    """The cursor is a max(), never `events[-1]`.

    In this fixture the newest event is the DELETE at index 0, so a drain that took the last
    item in feed order would checkpoint an hour and a day too early.
    """
    _mock_events(httpx2_mock, {1: hevy_fixture("workout_events_page1")})

    async with _client() as client:
        drain = await drain_events(client, since=SINCE)

    assert drain.cursor == FIXTURE_MAX_TIMESTAMP


async def test_drain_of_an_empty_feed_returns_the_baseline(httpx2_mock: Router) -> None:
    """Nothing changed upstream, so the cursor must stay exactly where it was.

    A drain that returned `utc_now()` here would silently skip anything logged in Hevy
    between the last event and this call.
    """
    _mock_events(httpx2_mock, {1: _events_page(1, 1, [])})

    async with _client() as client:
        drain = await drain_events(client, since=SINCE)

    assert drain.events == ()
    assert drain.pages_fetched == 1
    assert drain.cursor == SINCE


def test_event_timestamp_reads_the_variant_specific_field() -> None:
    """The two variants carry their timestamp in DIFFERENT fields.

    Sorting on `.workout.updated_at` alone would raise on every delete; sorting on
    `.deleted_at` alone would raise on every update.
    """
    payload = PaginatedWorkoutEvents.model_validate(hevy_fixture("workout_events_page1"))
    deleted, updated = payload.events

    assert isinstance(deleted, HevyDeletedWorkoutEvent)
    assert isinstance(updated, HevyUpdatedWorkoutEvent)
    assert event_timestamp(deleted) == deleted.deleted_at
    assert event_timestamp(updated) == updated.workout.updated_at
    assert event_timestamp(updated) == dt.datetime(2026, 8, 4, 9, 0, tzinfo=dt.UTC)


async def test_drain_rejects_a_naive_since() -> None:
    """FOUND-04 as a guard, not a convention.

    A naive `since` has no defined instant, so sending it would reinterpret the checkpoint in
    whatever offset the process happens to run in -- seven hours of workouts, in Jakarta.

    No HTTP fixture on purpose: the guard must fire before the socket is touched.
    """
    async with _client() as client:
        with pytest.raises(ValueError, match="naive datetime rejected"):
            await drain_events(client, since=dt.datetime(2026, 8, 1))  # noqa: DTZ001


async def test_unknown_event_type_fails_validation(httpx2_mock: Router) -> None:
    """A permissive union would drop an unknown event silently, which is data loss that looks
    exactly like a successful sync."""
    _mock_events(
        httpx2_mock,
        {1: _events_page(1, 1, [{"type": "archived", "id": "x"}])},
    )

    async with _client() as client:
        with pytest.raises(HevyResponseError):
            await drain_events(client, since=SINCE)


# --- applying the drain ----------------------------------------------------


@pytest.mark.integration
async def test_updated_event_replaces_the_workout(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """An `updated` event carries a FULL snapshot, so it REPLACES rather than merges.

    The set count shrinking from three to two is the assertion that matters: a merge would
    leave the old 100 kg working set behind and inflate every tonnage figure Phase 4 computes.
    """
    _mock_workout_pages(httpx2_mock, {1: _one_workout_page()}, remote_count=1)
    _mock_events(httpx2_mock, {1: hevy_fixture("workout_events_page1")})
    sessionmaker = make_sessionmaker(engine)
    try:
        async with _client() as client:
            await sync_workouts(client, sessionmaker, user_id=DEFAULT_USER_ID)
        assert await _counts(engine) == (1, 2, 3)

        async with _client() as client:
            result = await sync_workout_events(client, sessionmaker, user_id=DEFAULT_USER_ID)

        assert result.workouts_updated == 1
        # Workout B was never synced in this test, so its delete is a counted no-op.
        assert result.deletes_not_found == 1

        async with engine.connect() as conn:
            title = await conn.scalar(
                sa.select(Workout.title).where(*_SCOPED, Workout.external_id == WORKOUT_A)
            )
            bench = (await conn.scalars(_sets_of(WORKOUT_A, exercise_index=0))).all()

        assert title == "Push Day (edited)"
        assert list(bench) == [Decimal("105.000")]
    finally:
        await _cleanup(engine)


@pytest.mark.integration
async def test_deleted_event_removes_workout_and_children_leaving_siblings(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """HEVY-04. The delete takes its own children by cascade and nothing else.

    `delete_workout` filters on user_id AND provider AND external_id, so an upstream event can
    only remove the one workout it names for the one user being synced (T-03-38).
    """
    _mock_workout_pages(httpx2_mock, _both_workout_pages(), remote_count=2)
    _mock_events(httpx2_mock, {1: hevy_fixture("workout_events_page1")})
    sessionmaker = make_sessionmaker(engine)
    try:
        async with _client() as client:
            await sync_workouts(client, sessionmaker, user_id=DEFAULT_USER_ID)
        assert await _counts(engine) == (2, 3, 4)

        async with _client() as client:
            result = await sync_workout_events(client, sessionmaker, user_id=DEFAULT_USER_ID)

        assert result.workouts_deleted == 1
        assert result.deletes_not_found == 0

        # Workout A survives, rewritten to the event's two-exercise/one-set-each snapshot.
        # Workout B, its exercise and its set are all gone.
        assert await _counts(engine) == (1, 2, 2)
        async with engine.connect() as conn:
            survivors = (await conn.scalars(sa.select(Workout.external_id).where(*_SCOPED))).all()
        assert list(survivors) == [WORKOUT_A]
    finally:
        await _cleanup(engine)


@pytest.mark.integration
async def test_delete_event_for_unknown_workout_is_a_noop(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """The feed can report a deletion for a workout created and deleted between two syncs.

    Raising here would fail an entire drain over a workout that never existed locally, and
    would leave `status='error'` behind on a run that did nothing wrong.
    """
    _mock_events(
        httpx2_mock,
        {1: _events_page(1, 1, [_deleted("never-synced", "2026-08-07T00:00:00Z")])},
    )
    sessionmaker = make_sessionmaker(engine)
    try:
        await _seed_baseline(sessionmaker)

        async with _client() as client:
            result = await sync_workout_events(client, sessionmaker, user_id=DEFAULT_USER_ID)

        assert result.deletes_not_found == 1
        assert result.workouts_deleted == 0
        assert (await _state(sessionmaker)).status == "idle"
    finally:
        await _cleanup(engine)


@pytest.mark.integration
async def test_multiply_updated_workout_keeps_the_newest_payload(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """Each updated event carries a FULL snapshot. Applied in arrival
    order the OLDER snapshot lands last and wins."""
    _mock_events(
        httpx2_mock,
        {
            1: _events_page(
                1,
                1,
                [
                    # Hevy's order: newest at index 0.
                    _updated(WORKOUT_A, "2026-08-06T12:00:00Z", title="final"),
                    _updated(WORKOUT_A, "2026-08-05T12:00:00Z", title="stale"),
                ],
            )
        },
    )
    sessionmaker = make_sessionmaker(engine)
    try:
        await _seed_baseline(sessionmaker)

        async with _client() as client:
            result = await sync_workout_events(client, sessionmaker, user_id=DEFAULT_USER_ID)

        assert result.workouts_updated == 2
        async with engine.connect() as conn:
            title = await conn.scalar(
                sa.select(Workout.title).where(*_SCOPED, Workout.external_id == WORKOUT_A)
            )
        assert title == "final", "events were applied newest-first and the stale snapshot won"
    finally:
        await _cleanup(engine)


@pytest.mark.integration
async def test_cursor_advances_once_after_the_drain(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """The checkpoint is the maximum event timestamp across the WHOLE drain, written once.

    A cursor advanced per page would checkpoint page 1's newest event over pages 2..N that had
    not been applied yet.
    """
    _mock_events(httpx2_mock, {1: hevy_fixture("workout_events_page1")})
    sessionmaker = make_sessionmaker(engine)
    try:
        await _seed_baseline(sessionmaker, cursor_timestamp=BASELINE_CURSOR)

        async with _client() as client:
            await sync_workout_events(client, sessionmaker, user_id=DEFAULT_USER_ID)

        state = await _state(sessionmaker)
        assert state.cursor_timestamp == FIXTURE_MAX_TIMESTAMP
        assert state.status == "idle"
    finally:
        await _cleanup(engine)


@pytest.mark.integration
async def test_cursor_does_not_advance_when_the_drain_fails(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """T-03-39. A failed drain must leave the checkpoint exactly where it was.

    Re-reading the same window next run is free -- every apply is idempotent. Skipping it is
    unrecoverable, because Hevy will never mention those events again.
    """

    def _serve(request: httpx.Request) -> httpx.Response:
        if int(request.url.params["page"]) == 1:
            return httpx.Response(
                200,
                json=_events_page(1, 2, [_updated(WORKOUT_A, "2026-08-06T12:00:00Z")]),
            )
        return httpx.Response(500)

    httpx2_mock.get(EVENTS).mock(side_effect=_serve)
    sessionmaker = make_sessionmaker(engine)
    try:
        await _seed_baseline(sessionmaker, cursor_timestamp=BASELINE_CURSOR)

        async with _client() as client:
            with pytest.raises(HevyServerError):
                await sync_workout_events(client, sessionmaker, user_id=DEFAULT_USER_ID)

        state = await _state(sessionmaker)
        assert state.cursor_timestamp == BASELINE_CURSOR, "a failed drain moved the cursor"
        assert state.status == "error"
        # Page 1's event must not have been applied either -- nothing is written until the
        # whole drain is in hand.
        assert await _counts(engine) == (0, 0, 0)
    finally:
        await _cleanup(engine)


@pytest.mark.integration
async def test_event_sync_skips_without_a_baseline(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """T-03-41. With no baseline there is no window to be incremental FROM.

    Draining from the epoch would be a full history import through an endpoint that pages at
    10 and is designed for deltas. No routes are registered here on purpose: any request at
    all would fail as unmocked, on top of the recorded-call assertion.
    """
    sessionmaker = make_sessionmaker(engine)
    try:
        async with sessionmaker() as session:
            await ensure_sync_state(
                session,
                user_id=DEFAULT_USER_ID,
                provider=PROVIDER_HEVY,
                resource=RESOURCE_WORKOUTS,
            )
            await session.commit()

        async with _client() as client:
            result = await sync_workout_events(client, sessionmaker, user_id=DEFAULT_USER_ID)

        assert result.skipped_reason
        assert result.pages_fetched == 0
        assert len(httpx2_mock.calls) == 0, "the skip path still hit the network"
    finally:
        await _cleanup(engine)


@pytest.mark.integration
async def test_since_includes_the_overlap_margin(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """The drain deliberately re-reads the five minutes before the checkpoint.

    Asserted numerically, not as `cursor - EVENT_CURSOR_OVERLAP`: recomputing the expected
    value from the constant under test would pass even if the subtraction were dropped.
    Hevy's `since` filter and our clock are not the same clock, and an event landing in the
    same second as the previous cursor could otherwise fall outside the next window.
    """
    route = _mock_events(httpx2_mock, {1: _events_page(1, 1, [])})
    sessionmaker = make_sessionmaker(engine)
    try:
        await _seed_baseline(sessionmaker, cursor_timestamp=FIXTURE_MAX_TIMESTAMP)

        async with _client() as client:
            await sync_workout_events(client, sessionmaker, user_id=DEFAULT_USER_ID)

        assert route.call_count == 1
        assert route.calls[0].request.url.params["since"] == "2026-08-05T09:55:00Z"
    finally:
        await _cleanup(engine)


@pytest.mark.integration
async def test_full_then_incremental_round_trip(
    engine: AsyncEngine, httpx2_mock: Router
) -> None:
    """ROADMAP success criteria 1 and 2, in one assertion.

    A full history import followed by an incremental drain leaves exactly the state Hevy is
    in: the edited workout holding its NEW payload, and the deleted workout gone along with
    every row that hung off it.
    """
    _mock_workout_pages(httpx2_mock, _both_workout_pages(), remote_count=2)
    _mock_events(httpx2_mock, {1: hevy_fixture("workout_events_page1")})
    sessionmaker = make_sessionmaker(engine)
    try:
        async with _client() as client:
            await sync_workouts(client, sessionmaker, user_id=DEFAULT_USER_ID)

        async with _client() as client:
            result = await sync_workout_events(client, sessionmaker, user_id=DEFAULT_USER_ID)

        assert result.events_applied == 2
        assert result.workouts_updated == 1
        assert result.workouts_deleted == 1

        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    sa.select(Workout.external_id, Workout.title).where(*_SCOPED)
                )
            ).all()
            bench = (await conn.scalars(_sets_of(WORKOUT_A, exercise_index=0))).all()

        assert [(row.external_id, row.title) for row in rows] == [
            (WORKOUT_A, "Push Day (edited)")
        ]
        assert list(bench) == [Decimal("105.000")]

        state = await _state(sessionmaker)
        assert state.cursor_timestamp == FIXTURE_MAX_TIMESTAMP
        assert state.last_synced_at is not None
        assert state.status == "idle"
        assert state.last_error is None
    finally:
        await _cleanup(engine)
