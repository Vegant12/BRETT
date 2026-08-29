"""HEVY-02 / HEVY-04. The highest-risk logic in the phase, and the tests are the counterexample.

The naive implementation -- advance `since` while paging -- applies a handful of events,
silently drops the rest, and reports success. `test_drain_keeps_since_frozen_across_pages` and
`test_multiply_updated_workout_keeps_the_newest_payload` are the two assertions that would fail
if anyone reintroduces it.
"""

import datetime as dt
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

import httpx  # 0.x -- respx asserts on this type for RESPONSES (conftest, Pitfall 3)
import pytest
from pydantic import SecretStr
from respx import Route, Router

from app.integrations.hevy.client import HevyClient
from app.integrations.hevy.errors import HevyResponseError
from app.integrations.hevy.events import drain_events
from app.integrations.hevy.schemas import (
    HevyDeletedWorkoutEvent,
    HevyUpdatedWorkoutEvent,
    PaginatedWorkoutEvents,
    event_timestamp,
)
from tests.conftest import hevy_fixture

BASE = "https://api.hevyapp.com"
EVENTS = f"{BASE}/v1/workouts/events"

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
