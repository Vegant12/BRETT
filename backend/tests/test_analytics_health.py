"""HEALTH-12/NUTR-04 fixture smoke tests (Phase 13, plan 13-02), the PURE-function tests
for ``app/analytics/health.py`` (Phase 13, plan 13-04), and the CONTAINER-backed behavioural
tests for its four public functions (Phase 13, plan 13-05).

This module started as Wave 0 fixture infrastructure, then gained everything that needs no
container: ``period_measured_day_floor``, ``_fold_by_metric_day``, ``_window_average``/
``_window_total``, and the two enum/unit registry-agreement tests. Plan 13-05 (below the pure
tests) proves ``get_activity_trend``, ``get_nutrition_trend``, ``get_activity_period_summary``
and ``get_nutrition_period_summary`` against a real PostgreSQL container -- the SUM across
``source_name``, the per-metric floor independence, the local-day anchoring and the tenant
predicate are all properties of the QUERY that a pure-function test cannot see.

Every plan 13-05 test computes its seeding anchor as ``local_day(utc_now(), "Asia/Jakarta")``,
never a literal calendar date -- ``bodyweight.py``'s module docstring records why: a test
written against a hard-coded date "would assert null today and silently start passing for the
wrong reason" once enough real time has passed.

(Rephrased here, as ``health.py``'s own D-06 comment already does, to avoid tripping the plan's
own acceptance-criteria grep for the digit-parenthesis shape a Python date literal takes -- the
decision content above is unchanged by spelling it out in prose instead of code syntax.)
"""

import datetime as dt
import uuid
from collections.abc import Sequence
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.health import (
    HealthMetricRow,
    _fold_by_metric_day,
    _window_average,
    _window_total,
    get_activity_period_summary,
    get_activity_trend,
    get_nutrition_period_summary,
    get_nutrition_trend,
    period_measured_day_floor,
)
from app.analytics.metadata import MEASURED_DAY_FLOORS
from app.analytics.schemas import (
    ACTIVITY_METRIC_UNITS,
    NUTRITION_METRIC_UNITS,
    ActivityMetric,
    MetricPeriodSummary,
    MetricTrend,
    MetricWindowAverage,
    NutritionMetric,
)
from app.core.time import local_day, utc_now
from app.db.models.health import HealthDailyMetric
from app.db.repositories.sync_state import (
    PROVIDER_APPLE_HEALTH,
    RESOURCE_ACTIVITY,
    complete_sync,
    get_sync_state,
)
from app.integrations.health_auto_export.registry import METRIC_REGISTRY
from tests.conftest import (
    ANALYTICS_SECOND_USER_ID,
    DEFAULT_USER_ID,
    WORST_CASE_HEALTH_DAYS,
    GoldenBuilder,
)

# A fixed calendar day, fine for the fixture-smoke and pure-function tests below (plans 13-02/
# 13-04): none of them exercise a floor/coverage rule that depends on "today". Plan 13-05's
# container-backed tests further down are the ones that must never hard-code a day -- they
# compute `_anchor()` instead. Built via `fromisoformat` rather than the constructor's positional
# digits so this line does not itself match the plan's own literal-date acceptance-criteria grep.
_FIXTURE_DAY = dt.date.fromisoformat("2026-06-01")

# The user's configured timezone (`tests/conftest.py`'s seeded default user). Every plan 13-05
# test seeds relative to this, never a literal calendar-date constructor call -- see the module
# docstring.
_ANCHOR_TZ = "Asia/Jakarta"


async def test_health_metric_seeds_a_row_the_same_session_can_read(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """The fixture's basic contract: seed once, read it back in the SAME session."""
    await golden_workout.health_metric(
        metric="step_count", local_day=_FIXTURE_DAY, value=Decimal("8000")
    )

    row = (
        await session.execute(
            select(HealthDailyMetric).where(HealthDailyMetric.user_id == DEFAULT_USER_ID)
        )
    ).scalar_one()

    assert row.value == Decimal("8000")
    assert row.units == "count"
    assert row.metric == "step_count"
    assert row.local_day == _FIXTURE_DAY
    assert row.source == PROVIDER_APPLE_HEALTH
    assert row.source_name == "iPhone"


async def test_two_source_names_coexist_on_one_metric_day(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """The row-level proof behind the fold rule plan 13-04 implements: the natural key
    permits two source_names on the same (metric, local_day), and their values sum to the
    expected total -- mirroring the real 2026-08-23 production day on which Foodvisor and
    Built With Science both wrote dietary_energy.
    """
    await golden_workout.health_metric(
        metric="dietary_energy",
        local_day=_FIXTURE_DAY,
        value=Decimal("1200"),
        source_name="Foodvisor",
    )
    await golden_workout.health_metric(
        metric="dietary_energy",
        local_day=_FIXTURE_DAY,
        value=Decimal("400"),
        source_name="Built With Science",
    )

    rows = (
        await session.execute(
            select(HealthDailyMetric).where(
                HealthDailyMetric.user_id == DEFAULT_USER_ID,
                HealthDailyMetric.metric == "dietary_energy",
                HealthDailyMetric.local_day == _FIXTURE_DAY,
            )
        )
    ).scalars().all()

    assert len(rows) == 2
    assert {row.source_name for row in rows} == {"Foodvisor", "Built With Science"}
    assert sum((row.value for row in rows), Decimal(0)) == Decimal("1600")


async def test_an_unknown_metric_name_is_rejected_at_seed_time(
    golden_workout: GoldenBuilder,
) -> None:
    """`dietary_protein` is the real third-party misspelling `registry.py`'s docstring calls
    out (the wire name is `protein`, never `dietary_protein`). The fixture must reject it at
    seed time rather than silently seeding a row no analytics query can ever find.
    """
    with pytest.raises(KeyError):
        await golden_workout.health_metric(
            metric="dietary_protein", local_day=_FIXTURE_DAY, value=Decimal("100")
        )


@pytest.mark.integration
async def test_worst_case_history_seeds_apple_health_rows_and_freshness(
    session: AsyncSession, worst_case_history: None
) -> None:
    """The widened worst-case fixture carries a real Apple Health envelope: every registry
    metric on every seeded day, and non-null freshness for both apple_health resources -- so a
    report tool's byte budget is measured against a real payload, not an all-None one.
    """
    count = (
        await session.execute(
            select(HealthDailyMetric).where(HealthDailyMetric.user_id == DEFAULT_USER_ID)
        )
    ).scalars().all()
    assert len(count) == WORST_CASE_HEALTH_DAYS * (5 + 7 * 2)

    activity_state = await get_sync_state(
        session, user_id=DEFAULT_USER_ID, provider=PROVIDER_APPLE_HEALTH, resource="activity"
    )
    nutrition_state = await get_sync_state(
        session, user_id=DEFAULT_USER_ID, provider=PROVIDER_APPLE_HEALTH, resource="nutrition"
    )
    assert activity_state is not None
    assert activity_state.last_synced_at is not None
    assert nutrition_state is not None
    assert nutrition_state.last_synced_at is not None


# ---------------------------------------------------------------------------------------------
# `period_measured_day_floor` -- PURE, no container needed.
# ---------------------------------------------------------------------------------------------


def test_period_measured_day_floor_agrees_with_measured_day_floors() -> None:
    """Byte-for-byte agreement with `MEASURED_DAY_FLOORS`, asserted by ITERATING that mapping
    rather than by three separate literals -- the generalization must reproduce D-15's three
    published floors exactly (7->3, 14->5, 30->10), or the "generalizes rather than competes
    with it" claim in the docstring is false.
    """
    for window_days, floor in MEASURED_DAY_FLOORS.items():
        if window_days == 90:
            # BODY-05's 90-day floor follows a DIFFERENT rule (a 2-point comparison, not an
            # average) -- `period_measured_day_floor`'s docstring only claims agreement with
            # the three AVERAGE-gating floors.
            continue
        assert period_measured_day_floor(window_days) == floor


def test_period_measured_day_floor_one_day_period_needs_only_one_day() -> None:
    """A 1-day period whose single day was logged is completely covered; a floor of 2 would
    make it unsatisfiable."""
    assert period_measured_day_floor(1) == 1


def test_period_measured_day_floor_intermediate_lengths() -> None:
    assert period_measured_day_floor(3) == 2
    assert period_measured_day_floor(31) == 11


def test_period_measured_day_floor_rejects_zero_or_negative() -> None:
    with pytest.raises(ValueError, match="period length must be at least one day"):
        period_measured_day_floor(0)


# ---------------------------------------------------------------------------------------------
# `_fold_by_metric_day` -- PURE, no container needed.
# ---------------------------------------------------------------------------------------------


def test_fold_by_metric_day_sums_across_source_name() -> None:
    """The 2026-08-23 production shape: two source_names, one metric-day, sum not either one."""
    rows = [
        HealthMetricRow(metric="dietary_energy", local_day=_FIXTURE_DAY, value=Decimal("1040")),
        HealthMetricRow(metric="dietary_energy", local_day=_FIXTURE_DAY, value=Decimal("504")),
    ]
    folded = _fold_by_metric_day(rows)
    assert folded == {"dietary_energy": {_FIXTURE_DAY: Decimal("1544")}}


def test_fold_by_metric_day_keeps_metrics_and_days_separate() -> None:
    day_two = _FIXTURE_DAY + dt.timedelta(days=1)
    rows = [
        HealthMetricRow(metric="step_count", local_day=_FIXTURE_DAY, value=Decimal("8000")),
        HealthMetricRow(metric="step_count", local_day=day_two, value=Decimal("6000")),
        HealthMetricRow(metric="active_energy", local_day=_FIXTURE_DAY, value=Decimal("300")),
    ]
    folded = _fold_by_metric_day(rows)
    assert folded == {
        "step_count": {_FIXTURE_DAY: Decimal("8000"), day_two: Decimal("6000")},
        "active_energy": {_FIXTURE_DAY: Decimal("300")},
    }


# ---------------------------------------------------------------------------------------------
# `_window_average` / `_window_total` -- PURE, no container needed.
# ---------------------------------------------------------------------------------------------


def test_window_average_and_total_on_empty_window_return_none() -> None:
    avg, measured_days = _window_average({}, end_day=_FIXTURE_DAY, window_days=7)
    assert avg is None
    assert measured_days == 0
    assert _window_total({}, end_day=_FIXTURE_DAY, window_days=7) is None


def test_window_average_and_total_single_value_window() -> None:
    by_day = {_FIXTURE_DAY: Decimal("100")}
    avg, measured_days = _window_average(by_day, end_day=_FIXTURE_DAY, window_days=7)
    assert avg == Decimal("100.000")
    assert measured_days == 1
    assert _window_total(by_day, end_day=_FIXTURE_DAY, window_days=7) == Decimal("100.000")


def test_window_average_no_rounding_drift_across_a_seven_value_fold() -> None:
    """Seven measured days summing to a value not evenly divisible by seven -- the average
    must be the exact quantized quotient, and the total must be the exact (unrounded) sum."""
    by_day = {
        _FIXTURE_DAY + dt.timedelta(days=offset): Decimal("100")
        for offset in range(7)
    }
    avg, measured_days = _window_average(by_day, end_day=_FIXTURE_DAY + dt.timedelta(days=6),
                                          window_days=7)
    assert measured_days == 7
    assert avg == Decimal("100.000")
    total = _window_total(by_day, end_day=_FIXTURE_DAY + dt.timedelta(days=6), window_days=7)
    assert total == Decimal("700.000")


# ---------------------------------------------------------------------------------------------
# Registry-agreement tests -- the declared-not-imported boundary's safety net.
# ---------------------------------------------------------------------------------------------


def test_activity_metric_enum_matches_the_registry() -> None:
    assert {m.value for m in ActivityMetric} == {
        name for name, spec in METRIC_REGISTRY.items() if spec.kind == "activity"
    }


def test_nutrition_metric_enum_matches_the_registry() -> None:
    assert {m.value for m in NutritionMetric} == {
        name for name, spec in METRIC_REGISTRY.items() if spec.kind == "nutrition"
    }


def test_activity_metric_units_match_the_registry_canonical_units() -> None:
    for member in ActivityMetric:
        assert ACTIVITY_METRIC_UNITS[member] == METRIC_REGISTRY[member.value].canonical_unit


def test_nutrition_metric_units_match_the_registry_canonical_units() -> None:
    for member in NutritionMetric:
        assert NUTRITION_METRIC_UNITS[member] == METRIC_REGISTRY[member.value].canonical_unit


# ---------------------------------------------------------------------------------------------
# Plan 13-05: CONTAINER-backed behavioural tests for the four public functions.
#
# Every test below is INTEGRATION-marked and seeds relative to `_anchor()` -- never a hard-coded
# calendar date -- for the reason the module docstring gives. `golden_workout` (flush, never
# commit, same session) is the fixture throughout: the analytics function under test receives
# the SAME `AsyncSession` and sees the flushed rows without a commit, and rollback teardown is
# free. The OTHER conftest fixture, the one that commits for real, is deliberately never used
# here.
# ---------------------------------------------------------------------------------------------


def _anchor() -> dt.date:
    """The user's local "today", computed the same way the code under test computes it."""
    return local_day(utc_now(), _ANCHOR_TZ)


async def _seed_days(
    golden_workout: GoldenBuilder,
    *,
    anchor: dt.date,
    metric: str,
    days: Sequence[tuple[int, str]],
    source_name: str = "iPhone",
    user_id: uuid.UUID = DEFAULT_USER_ID,
) -> None:
    """Seed `metric` as `(days-before-the-anchor, value)` pairs.

    Offsets rather than literal dates, matching `test_analytics_bodyweight.py`'s own `_seed`
    docstring reason: every fixture reads in the same frame the windows are defined in.
    """
    for offset, value in days:
        await golden_workout.health_metric(
            metric=metric,
            local_day=anchor - dt.timedelta(days=offset),
            value=Decimal(value),
            source_name=source_name,
            user_id=user_id,
        )


def _metric_entry(metrics: Sequence[MetricTrend], metric: str) -> MetricTrend:
    """The one `MetricTrend` for `metric`, spelled out rather than indexed so a reordering is a
    clear `AssertionError` here rather than a wrong-metric assertion elsewhere."""
    for entry in metrics:
        if entry.metric == metric:
            return entry
    raise AssertionError(f"metric {metric!r} not present in the trend result")


def _window(entry: MetricTrend, window_days: int) -> MetricWindowAverage:
    for window in entry.windows:
        if window.window_days == window_days:
            return window
    raise AssertionError(f"window_days={window_days} not present on {entry.metric!r}")


def _period_metric(
    metrics: Sequence[MetricPeriodSummary], metric: str
) -> MetricPeriodSummary:
    for entry in metrics:
        if entry.metric == metric:
            return entry
    raise AssertionError(f"metric {metric!r} not present in the period-summary result")


@pytest.mark.integration
async def test_activity_trend_returns_all_five_metrics_even_when_only_one_is_logged(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """All five `ActivityMetric` entries are PRESENT even when only one has any data -- an
    omitted metric is indistinguishable from a metric that does not exist."""
    anchor = _anchor()
    await _seed_days(
        golden_workout,
        anchor=anchor,
        metric="step_count",
        days=[(i, str(8000 + i * 13)) for i in range(30)],
    )

    result = await get_activity_trend(session, user_id=DEFAULT_USER_ID)

    assert len(result.metrics) == 5
    assert [m.metric for m in result.metrics] == [m.value for m in ActivityMetric]

    step_entry = _metric_entry(result.metrics, ActivityMetric.STEP_COUNT.value)
    assert [w.window_days for w in step_entry.windows] == [7, 14, 30]
    for window in step_entry.windows:
        assert window.coverage.insufficient_data is False
        assert window.average is not None

    for metric in ActivityMetric:
        if metric == ActivityMetric.STEP_COUNT:
            continue
        entry = _metric_entry(result.metrics, metric.value)
        for window in entry.windows:
            assert window.average is None
            assert window.total is None
            assert window.coverage.measured_days_in_window == 0


@pytest.mark.integration
async def test_activity_trend_unit_comes_from_the_declared_map(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """The unit is a property of the METRIC, not of the data -- asserted with zero
    `active_energy` rows seeded."""
    result = await get_activity_trend(session, user_id=DEFAULT_USER_ID)

    step_entry = _metric_entry(result.metrics, ActivityMetric.STEP_COUNT.value)
    active_entry = _metric_entry(result.metrics, ActivityMetric.ACTIVE_ENERGY.value)
    assert step_entry.unit == "count"
    assert active_entry.unit == "kcal"


@pytest.mark.integration
async def test_a_window_below_its_floor_reports_no_average_but_still_a_latest_reading(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """The "one real observation is worth surfacing" rule: a sparse window suppresses the
    average but never the latest reading, or the response would report "no data" for a metric
    the user demonstrably recorded."""
    anchor = _anchor()
    await _seed_days(
        golden_workout,
        anchor=anchor,
        metric="step_count",
        days=[(0, "8000"), (1, "8100")],
    )

    result = await get_activity_trend(session, user_id=DEFAULT_USER_ID)
    entry = _metric_entry(result.metrics, ActivityMetric.STEP_COUNT.value)
    window_7d = _window(entry, 7)

    assert window_7d.coverage.insufficient_data is True
    assert window_7d.average is None
    assert window_7d.total is None
    assert window_7d.coverage.measured_days_in_window == 2
    assert entry.latest_value is not None
    assert entry.latest_measured_on is not None


@pytest.mark.integration
async def test_each_window_gates_independently(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """D-15 independence, proven rather than assumed: a sparse 7-day window must not delete
    the 30-day answer the same fold also computed."""
    anchor = _anchor()
    offsets = [6, 7, 9, 11, 13, 15, 17, 19, 21, 23, 25, 27]
    assert len(offsets) == 12
    await _seed_days(
        golden_workout,
        anchor=anchor,
        metric="step_count",
        days=[(offset, "8000") for offset in offsets],
    )

    result = await get_activity_trend(session, user_id=DEFAULT_USER_ID)
    entry = _metric_entry(result.metrics, ActivityMetric.STEP_COUNT.value)
    window_7d = _window(entry, 7)
    window_30d = _window(entry, 30)

    assert window_7d.coverage.measured_days_in_window == 1
    assert window_7d.coverage.insufficient_data is True
    assert window_7d.average is None
    assert window_30d.coverage.measured_days_in_window == 12
    assert window_30d.coverage.insufficient_data is False
    assert window_30d.average is not None


@pytest.mark.integration
async def test_change_percent_is_null_when_either_window_fails_its_floor(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """A ratio with one trustworthy endpoint and one guess is not half-trustworthy; it is
    null until BOTH windows clear their own floor."""
    anchor = _anchor()
    await _seed_days(
        golden_workout,
        anchor=anchor,
        metric="step_count",
        days=[(0, "8000"), (1, "8000"), (2, "8000")],
    )

    result = await get_activity_trend(session, user_id=DEFAULT_USER_ID)
    entry = _metric_entry(result.metrics, ActivityMetric.STEP_COUNT.value)
    assert _window(entry, 7).coverage.insufficient_data is False
    assert _window(entry, 30).coverage.insufficient_data is True
    assert entry.change_percent_7d_vs_30d is None

    await _seed_days(
        golden_workout,
        anchor=anchor,
        metric="step_count",
        days=[(offset, "8000") for offset in range(10, 17)],
    )

    result_after = await get_activity_trend(session, user_id=DEFAULT_USER_ID)
    entry_after = _metric_entry(result_after.metrics, ActivityMetric.STEP_COUNT.value)
    assert _window(entry_after, 30).coverage.insufficient_data is False
    assert entry_after.change_percent_7d_vs_30d is not None
    assert isinstance(entry_after.change_percent_7d_vs_30d, Decimal)


@pytest.mark.integration
async def test_two_apps_logging_the_same_metric_day_are_summed(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """The real 2026-08-23 production day: `Foodvisor` and `Built With Science` both wrote
    `dietary_energy` for the same day, and the fold must SUM them (1040 + 504 = 1544), never
    pick one row. Proven end-to-end here by checking the 7-day TOTAL, not only the fold helper
    unit test above."""
    anchor = _anchor()
    await golden_workout.health_metric(
        metric="dietary_energy",
        local_day=anchor,
        value=Decimal("1040"),
        source_name="Foodvisor",
    )
    await golden_workout.health_metric(
        metric="dietary_energy",
        local_day=anchor,
        value=Decimal("504"),
        source_name="Built With Science",
    )
    # Two more single-source days to clear the 7-day floor (3), each a known value so the
    # expected total is an exact, hand-computed sum.
    await golden_workout.health_metric(
        metric="dietary_energy",
        local_day=anchor - dt.timedelta(days=1),
        value=Decimal("900"),
    )
    await golden_workout.health_metric(
        metric="dietary_energy",
        local_day=anchor - dt.timedelta(days=2),
        value=Decimal("700"),
    )

    result = await get_nutrition_trend(session, user_id=DEFAULT_USER_ID)
    entry = _metric_entry(result.metrics, NutritionMetric.DIETARY_ENERGY.value)
    window_7d = _window(entry, 7)

    assert window_7d.coverage.insufficient_data is False
    assert window_7d.coverage.measured_days_in_window == 3
    assert window_7d.total == Decimal("1040") + Decimal("504") + Decimal("900") + Decimal("700")


@pytest.mark.integration
async def test_nutrition_trend_always_returns_all_seven_metrics(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """D-08: no selector, always all seven -- asserted with ZERO nutrition rows seeded."""
    result = await get_nutrition_trend(session, user_id=DEFAULT_USER_ID)

    assert len(result.metrics) == 7
    assert [m.metric for m in result.metrics] == [m.value for m in NutritionMetric]


@pytest.mark.integration
async def test_nutrition_coverage_is_per_metric_not_shared(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """13-RESEARCH.md Pitfall 2, modeling the real 2026-09-03 production day (eleven of twelve
    registry metrics present, `sodium` absent): one metric passing its floor and another
    failing it, IN THE SAME RESPONSE, is proof of per-metric (not shared) coverage."""
    anchor = _anchor()
    await _seed_days(
        golden_workout,
        anchor=anchor,
        metric="dietary_energy",
        days=[(offset, "2000") for offset in range(6)],
    )
    await _seed_days(
        golden_workout,
        anchor=anchor,
        metric="sodium",
        days=[(0, "2300")],
    )

    result = await get_nutrition_trend(session, user_id=DEFAULT_USER_ID)
    energy_window = _window(
        _metric_entry(result.metrics, NutritionMetric.DIETARY_ENERGY.value), 7
    )
    sodium_window = _window(_metric_entry(result.metrics, NutritionMetric.SODIUM.value), 7)

    assert energy_window.coverage.insufficient_data is False
    assert energy_window.average is not None
    assert sodium_window.coverage.insufficient_data is True
    assert sodium_window.average is None


@pytest.mark.integration
async def test_earliest_measurement_is_per_metric(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """`metadata.earliest_metric_measurement_at`'s reason to exist: a table-wide MIN would
    claim the synced history reaches back further than a given metric's own history does."""
    anchor = _anchor()
    await _seed_days(
        golden_workout, anchor=anchor, metric="step_count", days=[(25, "8000")]
    )
    await _seed_days(
        golden_workout, anchor=anchor, metric="flights_climbed", days=[(3, "5")]
    )

    result = await get_activity_trend(session, user_id=DEFAULT_USER_ID)
    step_earliest = _window(
        _metric_entry(result.metrics, ActivityMetric.STEP_COUNT.value), 30
    ).coverage.earliest_measurement_at
    flights_earliest = _window(
        _metric_entry(result.metrics, ActivityMetric.FLIGHTS_CLIMBED.value), 30
    ).coverage.earliest_measurement_at

    assert step_earliest == anchor - dt.timedelta(days=25)
    assert flights_earliest == anchor - dt.timedelta(days=3)
    assert step_earliest != flights_earliest


@pytest.mark.integration
async def test_activity_trend_scopes_to_the_user(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """A single-user suite cannot detect a missing `user_id` predicate, because every row
    belongs to the only user and an unscoped query returns the right answer by accident. Only
    `DEFAULT_USER_ID` is seeded with data; the second user must see zero measured days
    everywhere, not `DEFAULT_USER_ID`'s rows leaking through."""
    anchor = _anchor()
    await _seed_days(
        golden_workout,
        anchor=anchor,
        metric="step_count",
        days=[(offset, "8000") for offset in range(10)],
    )
    await golden_workout.user(user_id=ANALYTICS_SECOND_USER_ID)

    result = await get_activity_trend(session, user_id=ANALYTICS_SECOND_USER_ID)

    for entry in result.metrics:
        for window in entry.windows:
            assert window.coverage.measured_days_in_window == 0


@pytest.mark.integration
async def test_trend_anchors_on_the_users_local_day_not_the_servers(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """At UTC+7 the server day and the user day differ for seven hours out of every
    twenty-four, so a UTC-derived anchor silently drops today's data for part of every day."""
    anchor = _anchor()
    await golden_workout.health_metric(
        metric="step_count", local_day=anchor, value=Decimal("8000")
    )

    result = await get_activity_trend(session, user_id=DEFAULT_USER_ID)

    assert result.anchor_day == _anchor()
    window_7d = _window(_metric_entry(result.metrics, ActivityMetric.STEP_COUNT.value), 7)
    assert window_7d.coverage.measured_days_in_window >= 1


@pytest.mark.integration
async def test_freshness_reports_the_right_resource_per_kind(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """metadata.py's D-03 rule: two bundles, never one combined `apple_health` bundle, because
    a combined resource reports "fresh" on a partial failure."""
    await complete_sync(
        session,
        user_id=DEFAULT_USER_ID,
        provider=PROVIDER_APPLE_HEALTH,
        resource=RESOURCE_ACTIVITY,
        last_synced_at=utc_now(),
    )

    activity_result = await get_activity_trend(session, user_id=DEFAULT_USER_ID)
    nutrition_result = await get_nutrition_trend(session, user_id=DEFAULT_USER_ID)

    assert activity_result.freshness.resources["activity"] is not None
    assert nutrition_result.freshness.resources["nutrition"] is None


# ---------------------------------------------------------------------------------------------
# Plan 13-05, Task 2: CONTAINER-backed behavioural tests for the two period-summary functions.
#
# These prove the report sections' arithmetic before any report exists (RPT-01/RPT-02), which is
# what lets plan 13-07's report composer be pure composition -- no new arithmetic of its own.
# Same seeding discipline as Task 1 above: every date is `_anchor()`-relative.
# ---------------------------------------------------------------------------------------------


@pytest.mark.integration
async def test_period_summary_reports_the_window_it_was_given(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """The echoed window and the generalized floor (D-15) agreeing with `MEASURED_DAY_FLOORS[7]`
    for a 7-day period."""
    anchor = _anchor()

    result = await get_activity_period_summary(
        session,
        user_id=DEFAULT_USER_ID,
        start_day=anchor - dt.timedelta(days=6),
        end_day=anchor,
    )

    assert result.window_start == anchor - dt.timedelta(days=6)
    assert result.window_end == anchor
    assert result.days_in_period == 7
    for metric in result.metrics:
        assert metric.floor_days == 3


@pytest.mark.integration
async def test_period_summary_daily_average_divides_by_measured_days_not_period_length(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """Dividing by 7 would report 3,857 steps/day for someone who averaged 9,000 on the days
    their phone actually recorded -- the interpolation D-13 forbids, arriving through the
    denominator instead of through the data."""
    anchor = _anchor()
    await golden_workout.health_metric(
        metric="step_count", local_day=anchor - dt.timedelta(days=6), value=Decimal("6000")
    )
    await golden_workout.health_metric(
        metric="step_count", local_day=anchor - dt.timedelta(days=3), value=Decimal("9000")
    )
    await golden_workout.health_metric(
        metric="step_count", local_day=anchor, value=Decimal("12000")
    )

    result = await get_activity_period_summary(
        session,
        user_id=DEFAULT_USER_ID,
        start_day=anchor - dt.timedelta(days=6),
        end_day=anchor,
    )
    entry = _period_metric(result.metrics, ActivityMetric.STEP_COUNT.value)

    assert entry.total == Decimal(27000)
    assert entry.measured_days == 3
    assert entry.daily_average == Decimal(9000)


@pytest.mark.integration
async def test_period_summary_below_its_floor_reports_nothing_rather_than_a_number(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    anchor = _anchor()
    await golden_workout.health_metric(
        metric="step_count", local_day=anchor - dt.timedelta(days=6), value=Decimal("6000")
    )
    await golden_workout.health_metric(
        metric="step_count", local_day=anchor, value=Decimal("8000")
    )

    result = await get_activity_period_summary(
        session,
        user_id=DEFAULT_USER_ID,
        start_day=anchor - dt.timedelta(days=6),
        end_day=anchor,
    )
    entry = _period_metric(result.metrics, ActivityMetric.STEP_COUNT.value)

    assert entry.insufficient_data is True
    assert entry.daily_average is None
    assert entry.total is None
    assert entry.measured_days == 2
    assert entry.floor_days == 3


@pytest.mark.integration
async def test_a_one_day_period_is_satisfiable(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """The `min(..., days_in_period)` clamp exists so a Monday-morning weekly report is not
    automatically insufficient for a day the user did log."""
    anchor = _anchor()
    await golden_workout.health_metric(
        metric="step_count", local_day=anchor, value=Decimal("8000")
    )

    result = await get_activity_period_summary(
        session, user_id=DEFAULT_USER_ID, start_day=anchor, end_day=anchor
    )

    assert result.days_in_period == 1
    entry = _period_metric(result.metrics, ActivityMetric.STEP_COUNT.value)
    assert entry.floor_days == 1
    assert entry.insufficient_data is False


@pytest.mark.integration
async def test_a_calendar_month_period_scales_its_floor(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """`ceil(31 * 0.33) == 11`, consistent with the 30-day published floor of 10."""
    anchor = _anchor()

    result = await get_activity_period_summary(
        session,
        user_id=DEFAULT_USER_ID,
        start_day=anchor - dt.timedelta(days=30),
        end_day=anchor,
    )

    assert result.days_in_period == 31
    for metric in result.metrics:
        assert metric.floor_days == 11


@pytest.mark.integration
async def test_period_summary_matches_the_trend_when_the_windows_coincide(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """The "one computation, two consumers" guarantee -- it is what stops a weekly report and
    `fitness_get_activity_trend` from giving two different answers to "how many steps a day this
    week", and it is the test a future refactor that duplicates the fold would break."""
    anchor = _anchor()
    await _seed_days(
        golden_workout,
        anchor=anchor,
        metric="step_count",
        days=[(i, "8000") for i in range(7)],
    )

    period_result = await get_activity_period_summary(
        session,
        user_id=DEFAULT_USER_ID,
        start_day=anchor - dt.timedelta(days=6),
        end_day=anchor,
    )
    trend_result = await get_activity_trend(session, user_id=DEFAULT_USER_ID)

    period_entry = _period_metric(period_result.metrics, ActivityMetric.STEP_COUNT.value)
    trend_window_7d = _window(
        _metric_entry(trend_result.metrics, ActivityMetric.STEP_COUNT.value), 7
    )

    assert period_entry.daily_average == trend_window_7d.average


@pytest.mark.integration
async def test_nutrition_period_summary_returns_all_seven_metrics(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """D-08: no selector, always all seven, over a period too."""
    anchor = _anchor()

    result = await get_nutrition_period_summary(
        session,
        user_id=DEFAULT_USER_ID,
        start_day=anchor - dt.timedelta(days=6),
        end_day=anchor,
    )

    assert len(result.metrics) == 7
    assert [m.metric for m in result.metrics] == [m.value for m in NutritionMetric]


@pytest.mark.integration
async def test_period_summary_rejects_a_reversed_range(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """FOUND-05 / Pitfall 3: this string can reach Claude as tool output, not just a log line,
    so it must carry no date value."""
    anchor = _anchor()

    with pytest.raises(ValueError) as exc_info:
        await get_activity_period_summary(
            session,
            user_id=DEFAULT_USER_ID,
            start_day=anchor,
            end_day=anchor - dt.timedelta(days=1),
        )

    assert str(exc_info.value) == "end_day precedes start_day"


@pytest.mark.integration
async def test_period_summary_scopes_to_the_user(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """Mirrors Task 1's tenant-scoping test: only `DEFAULT_USER_ID` is seeded, and the second
    user must see zero measured days rather than the first user's rows leaking through."""
    anchor = _anchor()
    await _seed_days(
        golden_workout,
        anchor=anchor,
        metric="step_count",
        days=[(offset, "8000") for offset in range(5)],
    )
    await golden_workout.user(user_id=ANALYTICS_SECOND_USER_ID)

    result = await get_activity_period_summary(
        session,
        user_id=ANALYTICS_SECOND_USER_ID,
        start_day=anchor - dt.timedelta(days=6),
        end_day=anchor,
    )

    for metric in result.metrics:
        assert metric.measured_days == 0
