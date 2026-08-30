"""Freshness and coverage, the envelope every analytics response carries (DQ-01, DQ-02).

The integration tests run against the real Postgres container because the two things under
test have no meaning outside PostgreSQL: `sync_state`'s writers go through
`INSERT ... ON CONFLICT DO UPDATE`, and the coverage count is a `TIMESTAMPTZ` half-open range
predicate whose boundary behaviour is exactly what a SQLite stand-in would get subtly wrong.

The structural test that pins `FreshnessMetadata`'s field set deliberately carries NO
integration marker. "No credential, error text or internal cursor reaches Claude" is a security
guarantee, and a security guarantee must never become skippable because Docker is not running
-- the same argument `test_sync_state.py` makes for keeping its `format_sync_error` tests in
the fast suite. The D-05 boundary test below is markerless for the cheaper reason that it
touches no database at all.

Every container-backed test takes `golden_workout` even when it only writes `sync_state` rows,
because that fixture owns the `finally: await session.rollback()` which keeps the shared
session-scoped container clean whether the test passes or fails.
"""

import datetime as dt
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.metadata import (
    FRESHNESS_RESOURCES_MUSCLE,
    INSUFFICIENT_DATA_SESSION_THRESHOLD,
    build_coverage,
    build_freshness,
    is_insufficient,
)
from app.analytics.schemas import FreshnessMetadata
from app.core.time import local_range_bounds
from app.db.repositories.sync_state import (
    PROVIDER_HEVY,
    RESOURCE_EXERCISE_TEMPLATES,
    RESOURCE_WORKOUTS,
    complete_sync,
    get_sync_state,
    record_sync_error,
)
from tests.conftest import (
    ANALYTICS_SECOND_USER_ID,
    DEFAULT_USER_ID,
    GoldenBuilder,
    GoldenExercise,
    GoldenSet,
)

# `ANALYTICS_SECOND_USER_ID` and not DEFAULT_USER_ID: the container is session-scoped and
# shared, and DEFAULT_USER_ID's `sync_state` rows are written and asserted on by the Hevy sync
# tests. A distinct user id means these rows cannot collide with theirs.
#
# The two timestamps are 25 minutes apart because that is the drift observed on the live
# database between the workouts sync and the exercise_templates sync.
_SYNCED_WORKOUTS_AT = dt.datetime(2026, 8, 30, 5, 43, 18, tzinfo=dt.UTC)
_SYNCED_TEMPLATES_AT = dt.datetime(2026, 8, 30, 6, 8, 4, tzinfo=dt.UTC)

# Distinctive on purpose, so a leak is unambiguous rather than a coincidence.
_LEAK_SENTINEL = "zz-analytics-leak-canary-9f3a"


class _SentinelFailure(Exception):
    """An exception that OPTS IN to storing detail, the way the Hevy client does.

    A plain `RuntimeError(_LEAK_SENTINEL)` would not do: `format_sync_error` stores the class
    name alone unless the exception curates a `safe_message`, so the sentinel would never reach
    the column and the leak test would pass without ever having anything to leak.
    """

    safe_message = _LEAK_SENTINEL


@pytest.mark.integration
async def test_freshness_reports_each_resource_independently(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """DQ-01: one `last_synced_at` per resource, because they genuinely drift apart.

    A single collapsed `last_synced_at` would report the NEWER of the two for both. The muscle
    map comes from `exercise_templates`, so a stale template sync silently changes every
    per-muscle number -- and 25 minutes of drift is exactly the staleness Claude must be able
    to see in order to caveat the answer instead of asserting it.
    """
    await golden_workout.user(user_id=ANALYTICS_SECOND_USER_ID)
    await complete_sync(
        session,
        user_id=ANALYTICS_SECOND_USER_ID,
        provider=PROVIDER_HEVY,
        resource=RESOURCE_WORKOUTS,
        last_synced_at=_SYNCED_WORKOUTS_AT,
    )
    await complete_sync(
        session,
        user_id=ANALYTICS_SECOND_USER_ID,
        provider=PROVIDER_HEVY,
        resource=RESOURCE_EXERCISE_TEMPLATES,
        last_synced_at=_SYNCED_TEMPLATES_AT,
    )
    await session.flush()

    freshness = await build_freshness(
        session, user_id=ANALYTICS_SECOND_USER_ID, resources=FRESHNESS_RESOURCES_MUSCLE
    )

    assert freshness.resources == {
        RESOURCE_WORKOUTS: _SYNCED_WORKOUTS_AT,
        RESOURCE_EXERCISE_TEMPLATES: _SYNCED_TEMPLATES_AT,
    }
    # Two genuinely distinct values, not one row read twice.
    assert len(set(freshness.resources.values())) == 2


@pytest.mark.integration
async def test_freshness_reports_none_for_a_never_synced_resource(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """A never-synced resource reports `None`; it is NOT omitted from the map.

    "Never synced" is a legitimate answer to "when was this last synced". Dropping the key
    instead would make it indistinguishable from "the resource does not exist", which is the
    one reading that should send Claude looking for a bug rather than for a stale sync.
    """
    await golden_workout.user(user_id=ANALYTICS_SECOND_USER_ID)

    freshness = await build_freshness(
        session, user_id=ANALYTICS_SECOND_USER_ID, resources=FRESHNESS_RESOURCES_MUSCLE
    )

    assert set(freshness.resources) == {RESOURCE_WORKOUTS, RESOURCE_EXERCISE_TEMPLATES}
    assert all(value is None for value in freshness.resources.values())


def test_freshness_model_cannot_carry_sync_state_internals() -> None:
    """T-04-03, structurally rather than behaviourally -- and never skippable.

    `extra="forbid"` on the analytics base model means a future refactor cannot quietly widen
    `FreshnessMetadata` to carry the bookkeeping row's error text, run status or resume
    cursors. Asserting the field set as well as the rejection catches the other direction: a
    field ADDED to the model, which `extra="forbid"` would happily accept.

    No marker and no fixtures: this is the MCP-06 guarantee, and it must keep running when
    Docker does not.
    """
    assert set(FreshnessMetadata.model_fields) == {"resources"}

    with pytest.raises(ValidationError):
        FreshnessMetadata(resources={}, last_error=_LEAK_SENTINEL)  # type: ignore[call-arg]


@pytest.mark.integration
async def test_freshness_never_leaks_last_error(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """MCP-06 end to end: a real stored error never reaches the serialized response.

    The structural test above proves the model cannot DECLARE the field. This one proves the
    builder does not smuggle it in some other way -- it seeds a distinctive sentinel through
    the production writer and then scans the actual JSON Phase 6 would hand to Claude.
    """
    await golden_workout.user(user_id=ANALYTICS_SECOND_USER_ID)
    await record_sync_error(
        session,
        user_id=ANALYTICS_SECOND_USER_ID,
        provider=PROVIDER_HEVY,
        resource=RESOURCE_WORKOUTS,
        exc=_SentinelFailure(),
    )
    await session.flush()

    state = await get_sync_state(
        session,
        user_id=ANALYTICS_SECOND_USER_ID,
        provider=PROVIDER_HEVY,
        resource=RESOURCE_WORKOUTS,
    )
    assert state is not None and state.last_error is not None
    assert _LEAK_SENTINEL in state.last_error, (
        "the sentinel never reached sync_state -- test is vacuous"
    )

    payload = (
        await build_freshness(
            session, user_id=ANALYTICS_SECOND_USER_ID, resources=FRESHNESS_RESOURCES_MUSCLE
        )
    ).model_dump_json()

    assert _LEAK_SENTINEL not in payload, (
        f"MCP-06 violated: {_LEAK_SENTINEL!r} reached an analytics return model. "
        f"sync_state's stored error text is bounded by format_sync_error precisely so it "
        f"does not travel"
    )


# DQ-02: coverage, the D-05 threshold, and cross-tenant scoping

# Monday-anchored so the fixtures read the same way the weekly-volume plans' do. Jakarta is
# UTC+7, so 02:00Z is 09:00 local on the same day -- comfortably inside the local Monday.
_WEEK_START = dt.date(2026, 8, 24)
_WEEK_END = dt.date(2026, 8, 30)
_MONDAY = dt.datetime(2026, 8, 24, 2, 0, tzinfo=dt.UTC)
_WEDNESDAY = dt.datetime(2026, 8, 26, 2, 0, tzinfo=dt.UTC)
_LONG_AGO = dt.datetime(2026, 4, 6, 2, 0, tzinfo=dt.UTC)
_TEMPLATE = "ANALYTICS-META-BENCH"

_TIMEZONE = "Asia/Jakarta"


def _bench(*sets: GoldenSet) -> GoldenExercise:
    """One weighted exercise on the shared fixture template."""
    return GoldenExercise(template_external_id=_TEMPLATE, sets=sets)


_ONE_WORKING_SET = (GoldenSet(weight_kg=Decimal("60.000"), reps=10),)


@pytest.mark.integration
async def test_insufficient_data_is_true_at_one_session(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """D-05's whole point: one session cannot support a per-week rate.

    Reporting a single workout without the flag is how sparse data gets read as a confident
    result -- the number is arithmetically correct and the conclusion drawn from it is not.
    """
    utc_start, utc_end = local_range_bounds(_WEEK_START, _WEEK_END, _TIMEZONE)
    await golden_workout.template(external_id=_TEMPLATE)
    await golden_workout.workout(start_time=_MONDAY, exercises=[_bench(*_ONE_WORKING_SET)])

    coverage = await build_coverage(
        session, user_id=DEFAULT_USER_ID, utc_start=utc_start, utc_end=utc_end
    )

    assert coverage.sessions_in_window == 1
    assert coverage.insufficient_data is True


@pytest.mark.integration
async def test_insufficient_data_is_false_at_two_sessions(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """The other side of the same boundary, and the reason both tests exist.

    Pinning only the True case would leave `<=` and `<` indistinguishable, so an off-by-one in
    the comparison operator would ship green and flag every two-session week as untrustworthy.
    """
    utc_start, utc_end = local_range_bounds(_WEEK_START, _WEEK_END, _TIMEZONE)
    await golden_workout.template(external_id=_TEMPLATE)
    await golden_workout.workout(start_time=_MONDAY, exercises=[_bench(*_ONE_WORKING_SET)])
    await golden_workout.workout(start_time=_WEDNESDAY, exercises=[_bench(*_ONE_WORKING_SET)])

    coverage = await build_coverage(
        session, user_id=DEFAULT_USER_ID, utc_start=utc_start, utc_end=utc_end
    )

    assert coverage.sessions_in_window == 2
    assert coverage.insufficient_data is False


@pytest.mark.integration
async def test_insufficient_data_is_true_with_no_sessions(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """An empty window is the zero case, and it is still insufficient rather than "fine"."""
    utc_start, utc_end = local_range_bounds(_WEEK_START, _WEEK_END, _TIMEZONE)
    await golden_workout.user(user_id=ANALYTICS_SECOND_USER_ID)

    coverage = await build_coverage(
        session, user_id=ANALYTICS_SECOND_USER_ID, utc_start=utc_start, utc_end=utc_end
    )

    assert coverage.sessions_in_window == 0
    assert coverage.insufficient_data is True


def test_is_insufficient_boundary_is_the_shared_constant() -> None:
    """The flip point is the CONSTANT, not the literal 2.

    Written this way so revisiting D-05 later is a one-line change that does not silently
    invalidate this test into asserting a threshold the code no longer uses.
    """
    assert INSUFFICIENT_DATA_SESSION_THRESHOLD == 2
    assert is_insufficient(INSUFFICIENT_DATA_SESSION_THRESHOLD - 1) is True
    assert is_insufficient(INSUFFICIENT_DATA_SESSION_THRESHOLD) is False


@pytest.mark.integration
async def test_earliest_data_at_is_the_oldest_workout_across_all_time(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """The two assertions together are the point: the count is windowed, the floor is not.

    `earliest_data_at` is deliberately NOT window-scoped, because that is what separates "you
    did not train that week" from "your synced history does not reach back that far". Scoping
    it would collapse both into the same pair of zeroes.
    """
    utc_start, utc_end = local_range_bounds(_WEEK_START, _WEEK_END, _TIMEZONE)
    await golden_workout.template(external_id=_TEMPLATE)
    await golden_workout.workout(start_time=_LONG_AGO, exercises=[_bench(*_ONE_WORKING_SET)])
    await golden_workout.workout(start_time=_MONDAY, exercises=[_bench(*_ONE_WORKING_SET)])

    coverage = await build_coverage(
        session, user_id=DEFAULT_USER_ID, utc_start=utc_start, utc_end=utc_end
    )

    assert coverage.sessions_in_window == 1
    assert coverage.earliest_data_at == _LONG_AGO


@pytest.mark.integration
async def test_earliest_data_at_is_none_without_any_workouts(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """No history at all reports `None`, not the window start masquerading as a floor.

    The default user is given a workout months before the window on purpose. Without it this
    test passes against an empty table no matter what predicate `earliest_workout_at` uses,
    and the all-time lookup is the one place where forgetting `user_id` is easiest to miss --
    the window bounds would not save it.
    """
    utc_start, utc_end = local_range_bounds(_WEEK_START, _WEEK_END, _TIMEZONE)
    await golden_workout.user(user_id=ANALYTICS_SECOND_USER_ID)
    await golden_workout.template(external_id=_TEMPLATE)
    await golden_workout.workout(start_time=_LONG_AGO, exercises=[_bench(*_ONE_WORKING_SET)])

    coverage = await build_coverage(
        session, user_id=ANALYTICS_SECOND_USER_ID, utc_start=utc_start, utc_end=utc_end
    )

    assert coverage.earliest_data_at is None, (
        "T-04-02: earliest_data_at reported another user's history as this user's floor. "
        "The all-time lookup needs its own user_id predicate -- the window bounds do not "
        "constrain it"
    )


@pytest.mark.integration
async def test_coverage_does_not_count_another_users_workouts(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """T-04-02: a single-user suite cannot see a missing `user_id` predicate.

    With one user every row belongs to them, so an unscoped count returns the right answer by
    accident. Three workouts for a second user in the same window is the smallest arrangement
    where the unscoped and scoped answers differ, and differ by more than one.
    """
    utc_start, utc_end = local_range_bounds(_WEEK_START, _WEEK_END, _TIMEZONE)
    await golden_workout.user(user_id=ANALYTICS_SECOND_USER_ID)
    await golden_workout.template(external_id=_TEMPLATE)
    await golden_workout.template(external_id=_TEMPLATE, user_id=ANALYTICS_SECOND_USER_ID)

    for start_time in (_MONDAY, _WEDNESDAY, _MONDAY + dt.timedelta(days=3)):
        await golden_workout.workout(
            start_time=start_time,
            exercises=[_bench(*_ONE_WORKING_SET)],
            user_id=ANALYTICS_SECOND_USER_ID,
        )
    await golden_workout.workout(start_time=_MONDAY, exercises=[_bench(*_ONE_WORKING_SET)])

    mine = await build_coverage(
        session, user_id=DEFAULT_USER_ID, utc_start=utc_start, utc_end=utc_end
    )
    theirs = await build_coverage(
        session, user_id=ANALYTICS_SECOND_USER_ID, utc_start=utc_start, utc_end=utc_end
    )

    # Guard against a vacuous pass: if the fixture wrote nothing, both would be 0 and equal.
    assert theirs.sessions_in_window == 3
    assert mine.sessions_in_window == 1, (
        "ASVS V4 violated: the coverage count includes another user's workouts. The schema is "
        "multi-user-ready, so a missing user_id predicate is a cross-tenant disclosure"
    )
    assert mine.insufficient_data is True
    assert theirs.insufficient_data is False
