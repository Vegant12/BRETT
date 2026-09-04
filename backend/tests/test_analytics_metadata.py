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
import inspect
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import schemas
from app.analytics.metadata import (
    FRESHNESS_RESOURCES_ACTIVITY,
    FRESHNESS_RESOURCES_ALL,
    FRESHNESS_RESOURCES_APPLE_HEALTH,
    FRESHNESS_RESOURCES_BODY,
    FRESHNESS_RESOURCES_MUSCLE,
    FRESHNESS_RESOURCES_NUTRITION,
    FRESHNESS_RESOURCES_REPORT,
    FRESHNESS_RESOURCES_WORKOUTS,
    INSUFFICIENT_DATA_SESSION_THRESHOLD,
    MEASURED_DAY_FLOORS,
    build_coverage,
    build_freshness,
    build_measurement_coverage,
    earliest_measurement_at,
    earliest_metric_measurement_at,
    is_insufficient,
    is_measurement_insufficient,
)
from app.analytics.schemas import FreshnessMetadata, RecompositionStatus, _AnalyticsModel
from app.core.time import local_range_bounds
from app.db.models.body import BodyMeasurement
from app.db.repositories.sync_state import (
    APPLE_HEALTH_RESOURCES,
    PROVIDER_APPLE_HEALTH,
    PROVIDER_HEVY,
    RESOURCE_ACTIVITY,
    RESOURCE_BODY_MEASUREMENTS,
    RESOURCE_EXERCISE_TEMPLATES,
    RESOURCE_NUTRITION,
    RESOURCE_WORKOUTS,
    SYNC_RESOURCES,
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

# Apple Health's activity sync (D-03). Distinct from BOTH Hevy timestamps above, so a builder
# that ignored the pair's provider and read a Hevy row instead would produce a visibly wrong
# value rather than a coincidentally equal one.
_SYNCED_ACTIVITY_AT = dt.datetime(2026, 8, 30, 7, 31, 52, tzinfo=dt.UTC)

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


# HEALTH-11 / NUTR-05 / D-03: Apple Health's two resources, and the per-provider lookup that
# makes them answerable at all (RESEARCH Pitfall 7).


@pytest.mark.integration
async def test_apple_health_activity_and_nutrition_are_independent(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """D-03 / NUTR-05: nutrition that never synced must report None, not activity's timestamp.

    Only the `activity` row is seeded. That is the shape of the real partial failure D-03 was
    written to expose: both kinds arrive in ONE Health Auto Export POST, but the phone's
    nutrition-logging app can stop writing to HealthKit while step counts keep flowing.
    """
    await golden_workout.user(user_id=ANALYTICS_SECOND_USER_ID)
    await complete_sync(
        session,
        user_id=ANALYTICS_SECOND_USER_ID,
        provider=PROVIDER_APPLE_HEALTH,
        resource=RESOURCE_ACTIVITY,
        last_synced_at=_SYNCED_ACTIVITY_AT,
    )
    await session.flush()

    freshness = await build_freshness(
        session, user_id=ANALYTICS_SECOND_USER_ID, resources=FRESHNESS_RESOURCES_APPLE_HEALTH
    )

    assert freshness.resources == {
        RESOURCE_ACTIVITY: _SYNCED_ACTIVITY_AT,
        RESOURCE_NUTRITION: None,
    }, (
        "D-03/NUTR-05 violated: Apple Health's two resources are not independent. Nutrition was "
        "never synced, so it must report None. Anything else -- activity's timestamp, or a "
        "collapsed combined `apple_health` value -- reports 'fresh' during exactly the partial "
        "failure this split exists to expose, and Claude then coaches off calorie data that "
        f"stopped days ago without ever caveating it. Got: {freshness.resources}"
    )


@pytest.mark.integration
async def test_apple_health_and_hevy_resources_resolve_per_provider(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """HEALTH-11: one call, two providers, each resource reading its OWN provider's row.

    This is the Pitfall 7 regression guard. While `build_freshness` defaulted the provider to
    Hevy, `activity` was looked up under the Hevy provider -- where no row exists -- and came
    back None, so an Apple Health answer would have silently claimed "never synced" forever.
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
        provider=PROVIDER_APPLE_HEALTH,
        resource=RESOURCE_ACTIVITY,
        last_synced_at=_SYNCED_ACTIVITY_AT,
    )
    await session.flush()

    freshness = await build_freshness(
        session,
        user_id=ANALYTICS_SECOND_USER_ID,
        resources=FRESHNESS_RESOURCES_WORKOUTS + FRESHNESS_RESOURCES_ACTIVITY,
    )

    # Guard against a vacuous pass: two equal timestamps would let a single-provider lookup
    # satisfy the assertion below by accident.
    assert _SYNCED_WORKOUTS_AT != _SYNCED_ACTIVITY_AT

    assert freshness.resources == {
        RESOURCE_WORKOUTS: _SYNCED_WORKOUTS_AT,
        RESOURCE_ACTIVITY: _SYNCED_ACTIVITY_AT,
    }, (
        "HEALTH-11 violated (RESEARCH Pitfall 7): a (provider, resource) pair did not read its "
        "OWN provider's bookkeeping row. A single provider applied to every pair reports one "
        "source's freshness as another's -- Hevy's sync time presented as Apple Health's, or a "
        "never-synced None for data that is actually current. Both are plausible-looking numbers "
        f"that are quietly wrong, which is this project's primary failure mode. "
        f"Got: {freshness.resources}"
    )


def test_resource_names_are_unique_across_providers() -> None:
    """The precondition for keying FreshnessMetadata by the BARE resource name.

    No marker and no fixtures: this guards a response-shape invariant, so it must keep running
    when Docker does not.
    """
    assert len(SYNC_RESOURCES | APPLE_HEALTH_RESOURCES) == len(SYNC_RESOURCES) + len(
        APPLE_HEALTH_RESOURCES
    ), (
        "HEALTH-11 violated: a resource name is now used by two providers. "
        "`build_freshness` keys its output dict by the bare resource name, so a shared name "
        "makes one provider's timestamp silently overwrite the other's in every analytics "
        "response. Either rename the resource or switch the key to a composite -- and if you "
        f"switch, every MCP tool response shape changes too. Overlap: "
        f"{sorted(SYNC_RESOURCES & APPLE_HEALTH_RESOURCES)}"
    )


def test_the_report_bundle_is_the_union_of_the_three_it_replaces() -> None:
    """RPT-01/RPT-02: `FRESHNESS_RESOURCES_REPORT` must equal the union of the three existing
    bundles it composes from, exactly -- not by concatenation, by NAMING all five pairs. This
    test is the guard that keeps the two spellings from drifting apart.
    """
    assert set(FRESHNESS_RESOURCES_REPORT) == (
        set(FRESHNESS_RESOURCES_ALL)
        | set(FRESHNESS_RESOURCES_ACTIVITY)
        | set(FRESHNESS_RESOURCES_NUTRITION)
    )
    assert len(FRESHNESS_RESOURCES_REPORT) == 5


def test_build_freshness_has_no_provider_default() -> None:
    """Pitfall 7: a default provider made every Apple Health lookup silently read Hevy's row.

    Structural rather than behavioural, and deliberately markerless -- restoring the default
    would not fail any single-provider test, so only the signature itself can guard it.
    """
    parameters = inspect.signature(build_freshness).parameters

    assert "provider" not in parameters, (
        "HEALTH-11 violated: `build_freshness` accepts a `provider` argument again. A "
        "per-call provider re-creates the bug the pair signature removed -- every resource in "
        "one call resolves against ONE provider, so the first Apple Health resource passed "
        "alongside a Hevy one is answered from the wrong bookkeeping row. The provider belongs "
        f"to the pair, not to the call. Parameters: {sorted(parameters)}"
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


# Phase 5 (05-03): D-15's day-grained coverage floors, and the leak guard widened from one model
# to every analytics return type.

# The 18 return models Phase 5 adds. Named by hand ON PURPOSE, so the dynamic walk below has
# something to be checked AGAINST: a walk that silently found nothing would make every guard in
# this section vacuously true -- the same trap `test_analytics_isolation.py` guards against with
# `test_the_walk_actually_finds_files`.
_PHASE_5_MODELS = frozenset(
    {
        "MeasurementCoverage",
        "ProgressionPoint",
        "ExerciseProgressionResult",
        "ExerciseTrend",
        "ExerciseTrendsResult",
        "PlateauResult",
        "PlateauReport",
        "PersonalRecord",
        "RepsAtWeightRecord",
        "PersonalRecordsResult",
        "ComparisonRate",
        "ComparisonLevel",
        "MuscleGroupComparison",
        "PeriodSummary",
        "PeriodComparisonResult",
        "BodyWeightTrendResult",
        "AggregateProgression",
        "RecompositionResult",
    }
)

# MCP-06 / DQ-01. The first four are `sync_state`'s internals, which `build_freshness`'s own
# comment already forbids; the rest are credential-shaped names that must never become a field on
# something Claude can read. Asserted over the WHOLE package rather than per model, because a
# per-model list is a list somebody forgets to extend.
_FORBIDDEN_FIELD_NAMES = frozenset(
    {
        "last_error",
        "status",
        "cursor_page",
        "cursor_timestamp",
        "api_key",
        "database_url",
        "token",
        "password",
        "dsn",
    }
)

# The ONE deliberate collision, exempted by name and immediately re-pinned by TYPE below.
# `RecompositionResult.status` is blueprint 26's seven-value recomposition classification; the
# forbidden `status` is `sync_state`'s RUN status ("idle"/"running"/"error"). Same word, opposite
# provenance. The exemption is narrow and the annotation assertion is what stops it from later
# being widened into a hole a sync status could travel through.
_FORBIDDEN_NAME_EXEMPTIONS: dict[str, frozenset[str]] = {
    "RecompositionResult": frozenset({"status"}),
}


def _analytics_return_models() -> dict[str, type[_AnalyticsModel]]:
    """Every concrete `_AnalyticsModel` subclass declared in `app.analytics.schemas`.

    Discovered from the module namespace rather than from a hand-maintained list, so a model
    added by a later Phase 5 plan is covered by the guards below the moment it exists, without
    anybody remembering to register it here.
    """
    return {
        name: obj
        for name, obj in vars(schemas).items()
        if isinstance(obj, type) and issubclass(obj, _AnalyticsModel) and obj is not _AnalyticsModel
    }


def test_measured_day_floors_both_sides_of_every_boundary() -> None:
    """D-15: four windows, four INDEPENDENT floors, both sides of each pinned.

    Pinning only the True side would leave `<` and `<=` indistinguishable, so an off-by-one would
    ship green and flag a perfectly well-measured week as untrustworthy -- or, worse, the reverse.

    The floors are per window because a 30-day average can be trustworthy while the 7-day one is
    not. A single shared threshold would make `insufficient_data` mean "the sparsest window was
    sparse", which is not a fact about the average it is attached to.

    The 90-day entry (D-07, BODY-05) follows a DIFFERENT rule from the other three: it gates a
    two-point latest-vs-earliest COMPARISON, not an average, so its floor is the mathematical
    minimum for two distinct points to exist (2), not "a little under half the window".
    """
    assert dict(MEASURED_DAY_FLOORS) == {7: 3, 14: 5, 30: 10, 90: 2}

    assert is_measurement_insufficient(window_days=7, measured_days=2) is True, "7-day floor is 3"
    assert is_measurement_insufficient(window_days=7, measured_days=3) is False, "7-day floor is 3"
    assert is_measurement_insufficient(window_days=14, measured_days=4) is True, "14-day floor is 5"
    assert is_measurement_insufficient(window_days=14, measured_days=5) is False, (
        "14-day floor is 5"
    )
    assert is_measurement_insufficient(window_days=30, measured_days=9) is True, (
        "30-day floor is 10"
    )
    assert is_measurement_insufficient(window_days=30, measured_days=10) is False, (
        "30-day floor is 10"
    )
    assert is_measurement_insufficient(window_days=90, measured_days=1) is True, (
        "90-day floor is 2: one reading has no earliest distinct from its latest"
    )
    assert is_measurement_insufficient(window_days=90, measured_days=2) is False, (
        "90-day floor is 2"
    )

    with pytest.raises(TypeError):
        MEASURED_DAY_FLOORS[7] = 1  # type: ignore[index]


def test_unsupported_measurement_window_raises() -> None:
    """T-05-18: an unchosen window is a caller bug, and the complaint carries no value.

    A permissive default would silently accept a 21-day window whose floor nobody picked and
    report `insufficient_data=False` for it. Raising is the only answer that cannot be misread.
    """
    with pytest.raises(ValueError) as exc:
        is_measurement_insufficient(window_days=21, measured_days=5)

    assert str(exc.value) == "unsupported measurement window length"
    assert not any(ch.isdigit() for ch in str(exc.value)), (
        "error text will be logged; it must carry no value (FOUND-05, ASVS V7)"
    )


def test_build_measurement_coverage_is_synchronous() -> None:
    """The divergence from `build_coverage` is deliberate, so it is pinned rather than assumed."""
    assert not inspect.iscoroutinefunction(build_measurement_coverage), (
        "BODY-01 fetches once and folds five ways; an async builder per window turns one query "
        "into five"
    )

    coverage = build_measurement_coverage(
        window_days=30, measured_days=10, earliest_measurement_at=dt.date(2026, 3, 1)
    )
    assert coverage.window_days == 30
    assert coverage.measured_days_in_window == 10
    assert coverage.insufficient_data is False
    assert coverage.earliest_measurement_at == dt.date(2026, 3, 1)


def test_the_model_walk_covers_every_phase_5_return_model() -> None:
    """A guard on the guards: the two leak tests below iterate whatever this walk returns.

    If the walk were ever wrong -- a moved module, a renamed base class -- it returns nothing and
    both security assertions pass while checking nothing at all. Naming Phase 5's 18 models
    explicitly is what turns that silent pass into a failure.

    The floor rises with the package on purpose, matching `test_analytics_isolation.py`'s
    convention: an exact count would break every time a later plan legitimately adds a model,
    and it would buy nothing -- the walk is over the module namespace, so no model can escape it.
    """
    discovered = set(_analytics_return_models())

    assert _PHASE_5_MODELS <= discovered, (
        f"the walk missed Phase 5 models: {sorted(_PHASE_5_MODELS - discovered)}"
    )
    # 10 pre-existing Phase 4 models plus Phase 5's 18.
    assert len(discovered) >= 28, f"the walk found only {len(discovered)} analytics return models"


def test_no_new_model_declares_a_forbidden_field() -> None:
    """T-05-16, structurally and over the whole package -- and never skippable.

    `extra="forbid"` stops a bookkeeping field being smuggled in at construction time; it happily
    accepts one ADDED to the model. This is the other direction, and it must keep running when
    Docker does not, for the reason this module's docstring gives: a security guarantee that can
    be skipped is a security guarantee that will be.
    """
    for name, model in sorted(_analytics_return_models().items()):
        exempt = _FORBIDDEN_NAME_EXEMPTIONS.get(name, frozenset())
        offenders = (set(model.model_fields) & _FORBIDDEN_FIELD_NAMES) - exempt
        assert not offenders, (
            f"MCP-06: sync internals and credentials must never reach a Claude-readable "
            f"response -- {name} declares {sorted(offenders)}"
        )

    # The exemption is re-pinned by TYPE so it cannot later be widened into a hole a sync run
    # status could travel through under the same field name.
    assert schemas.RecompositionResult.model_fields["status"].annotation is RecompositionStatus, (
        "the `status` exemption is granted to BODY-02's recomposition classification ONLY. A "
        "different type behind that name is sync_state's run status arriving by the back door"
    )


def test_every_new_model_hides_input_in_errors() -> None:
    """T-05-15. Asserted over every subclass, so a future model cannot opt out by omission.

    Phase 5's models carry body weight, the most sensitive number in this project. A model that
    declared its own `model_config` and dropped `hide_input_in_errors` would look completely
    ordinary in review and would only be discovered by finding a weigh-in in a log file.
    """
    models = _analytics_return_models()
    assert models, "the walk found no models -- every assertion below would be vacuous"

    for name, model in sorted(models.items()):
        config = model.model_config
        assert config.get("hide_input_in_errors") is True, (
            f"ASVS V8: a ValidationError would otherwise render a body weight into a log line "
            f"-- {name}"
        )
        assert config.get("frozen") is True, (
            f"a result object a caller can mutate is a result object two callers will disagree "
            f"about -- {name}"
        )
        assert config.get("extra") == "forbid", (
            f"an unexpected field here is a bug in this repo and must fail loudly rather than "
            f"be dropped -- {name}"
        )


# Body-measurement freshness and the all-time earliest weigh-in (BODY-01, BODY-02).

# A third distinct timestamp, so a builder that read one row and reported it three times would be
# unmistakable rather than a coincidence.
_SYNCED_BODY_AT = dt.datetime(2026, 8, 30, 6, 21, 47, tzinfo=dt.UTC)

_FIRST_WEIGH_IN = dt.date(2026, 3, 1)
_LATER_WEIGH_IN = dt.date(2026, 8, 1)
_OTHER_TENANT_WEIGH_IN = dt.date(2025, 1, 1)


@pytest.mark.integration
async def test_body_freshness_reports_the_body_measurements_resource(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """DQ-01 extended to the third sync resource, and to BODY-02's three-way answer.

    `FRESHNESS_RESOURCES_ALL` exists because BODY-02 reads both sides: a stale `exercise_templates`
    sync silently changes every e1RM eligibility decision (D-03 gates on `exercise_type`), which
    changes the progression signal, with no error anywhere. Reporting only the body sync's
    freshness there would hide exactly the staleness that moves the answer.
    """
    await golden_workout.user(user_id=ANALYTICS_SECOND_USER_ID)
    await complete_sync(
        session,
        user_id=ANALYTICS_SECOND_USER_ID,
        provider=PROVIDER_HEVY,
        resource=RESOURCE_BODY_MEASUREMENTS,
        last_synced_at=_SYNCED_BODY_AT,
    )
    await complete_sync(
        session,
        user_id=ANALYTICS_SECOND_USER_ID,
        provider=PROVIDER_HEVY,
        resource=RESOURCE_WORKOUTS,
        last_synced_at=_SYNCED_WORKOUTS_AT,
    )
    await session.flush()

    body = await build_freshness(
        session, user_id=ANALYTICS_SECOND_USER_ID, resources=FRESHNESS_RESOURCES_BODY
    )

    assert body.resources == {RESOURCE_BODY_MEASUREMENTS: _SYNCED_BODY_AT}

    everything = await build_freshness(
        session, user_id=ANALYTICS_SECOND_USER_ID, resources=FRESHNESS_RESOURCES_ALL
    )

    assert set(everything.resources) == {
        RESOURCE_WORKOUTS,
        RESOURCE_EXERCISE_TEMPLATES,
        RESOURCE_BODY_MEASUREMENTS,
    }
    assert everything.resources[RESOURCE_BODY_MEASUREMENTS] == _SYNCED_BODY_AT
    assert everything.resources[RESOURCE_WORKOUTS] == _SYNCED_WORKOUTS_AT
    assert everything.resources[RESOURCE_EXERCISE_TEMPLATES] is None, (
        "a never-synced resource reports None rather than being omitted -- a missing key is "
        "indistinguishable from 'the resource does not exist'"
    )


@pytest.mark.integration
async def test_earliest_measurement_at_is_all_time_and_tenant_scoped(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """The body-weight analogue of `earliest_data_at`, with the same two failure modes.

    All-time rather than window-scoped, because that is what separates "you did not weigh in
    during that window" from "your synced history does not reach back that far". And the second
    user is seeded EARLIER than the first, so a missing `user_id` predicate cannot pass by
    accident -- an unscoped `MIN` would return their date, not this user's.
    """
    await golden_workout.user(user_id=ANALYTICS_SECOND_USER_ID)
    await golden_workout.body_measurement(measured_on=_FIRST_WEIGH_IN, weight_kg=Decimal("66.10"))
    await golden_workout.body_measurement(measured_on=_LATER_WEIGH_IN, weight_kg=Decimal("65.40"))
    await golden_workout.body_measurement(
        measured_on=_OTHER_TENANT_WEIGH_IN,
        weight_kg=Decimal("70.00"),
        user_id=ANALYTICS_SECOND_USER_ID,
    )

    mine = await earliest_measurement_at(session, user_id=DEFAULT_USER_ID)
    theirs = await earliest_measurement_at(session, user_id=ANALYTICS_SECOND_USER_ID)

    # Guard against a vacuous pass: if the fixture wrote nothing, both would be None and equal.
    assert theirs == _OTHER_TENANT_WEIGH_IN
    assert mine == _FIRST_WEIGH_IN, (
        "another user's weigh-in leaked into this user's earliest date (ASVS V4)"
    )


@pytest.mark.integration
async def test_earliest_metric_measurement_at_is_column_scoped_and_tenant_scoped(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """RESEARCH Pitfall 4: the per-metric answer must NOT be the per-row answer.

    The older row carries a weight and no waist; the newer one carries both. An implementation
    that reused `earliest_measurement_at` would return the OLDER date for `waist_cm` -- a
    metric that did not exist on that row -- and the coverage envelope would then claim more
    history for the metric than the metric has. The second user is seeded EARLIER still, so a
    missing `user_id` predicate cannot pass by accident either.
    """
    await golden_workout.user(user_id=ANALYTICS_SECOND_USER_ID)
    await golden_workout.body_measurement(measured_on=_FIRST_WEIGH_IN, weight_kg=Decimal("66.10"))
    await golden_workout.body_measurement(
        measured_on=_LATER_WEIGH_IN, weight_kg=Decimal("65.40"), waist_cm=Decimal("81.00")
    )
    await golden_workout.body_measurement(
        measured_on=_OTHER_TENANT_WEIGH_IN,
        weight_kg=Decimal("70.00"),
        waist_cm=Decimal("95.00"),
        user_id=ANALYTICS_SECOND_USER_ID,
    )

    mine = await earliest_metric_measurement_at(
        session, user_id=DEFAULT_USER_ID, column=BodyMeasurement.waist_cm
    )
    theirs = await earliest_metric_measurement_at(
        session, user_id=ANALYTICS_SECOND_USER_ID, column=BodyMeasurement.waist_cm
    )
    never_recorded = await earliest_metric_measurement_at(
        session, user_id=DEFAULT_USER_ID, column=BodyMeasurement.fat_percent
    )

    assert theirs == _OTHER_TENANT_WEIGH_IN
    assert mine == _LATER_WEIGH_IN, (
        "the weight-only row leaked into waist_cm's earliest date -- this function is column-"
        "scoped, unlike earliest_measurement_at"
    )
    assert await earliest_measurement_at(session, user_id=DEFAULT_USER_ID) == _FIRST_WEIGH_IN, (
        "BODY-01's function must be unchanged: it still answers per-ROW, not per-metric"
    )
    assert never_recorded is None, "a metric with no readings has no earliest date, not a zero"

    assert isinstance(mine, dt.date)
    assert not isinstance(mine, dt.datetime), (
        "`measured_on` is a calendar Date; a datetime here means somebody invented a time of day "
        "for a weigh-in"
    )
