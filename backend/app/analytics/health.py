"""Rolling activity and nutrition averages (HEALTH-12, NUTR-04, D-05, D-06).

The first module in ``backend/app/analytics/`` to read ``health_daily_metrics``.

**Copies ``bodyweight.py``'s shape, NOT ``body_measurements.py``'s (D-05/D-06).** Activity and
intake are recorded daily from the phone, unlike a tape measure -- a rolling 7-, 14- and
30-day average with independent per-window floors is the right design here, the same way it is
for body weight, and the latest-vs-90-days-ago comparison BODY-05 needed for sparsely-tracked
circumference columns would be the wrong shape for data that actually arrives every day.

**No interpolation and no carry-forward**, inheriting ``bodyweight.py`` D-13's reason in spirit:
a missed logging day is not a zero-calorie day, and filling it would hide exactly the sparsity
Claude needs to see.

**Each window has its own floor AND each metric has its own floor.** ``bodyweight.py`` tracks
one value, so per-window independence was enough; here there are 5 and 7 values whose logging
cadences differ (real production, 2026-09-03: ``sodium`` absent on a day the other five macros
were present). This is 13-RESEARCH.md Pitfall 2.

**Rows are SUMMED across ``source_name``.** The natural key
``(user, source, metric, source_name, local_day)`` deliberately permits two rows for one
metric-day, and real production has them -- 2026-08-23, ``Foodvisor`` and ``Built With Science``
both wrote ``DietaryEnergyConsumed``. All twelve registry metrics declare ``aggregation="sum"``,
so summing is the registry-sanctioned fold; picking one row would silently report a fraction of
the day.

**No ``source_name != 'Hevy'`` predicate belongs here.** HEALTH-08's exclusion happens at INGEST
(``integrations/health_auto_export/normalize.py::is_hevy_sourced`` drops the datapoint before it
is written) and the Phase 9 backfill reuses that same normalizer, so this table holds no
Hevy-originated rows. Adding a read-side filter would be redundant AND would risk dropping the
``Gymverse``/``Zing`` rows ``.planning/STATE.md`` records as deliberately ingested.

Read-only, like everything else under ``app/analytics/``: nothing here writes, and the CALLER
owns the transaction. The session is positional and everything else keyword-only, matching
``app/db/repositories/``.
"""

import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.metadata import (
    FRESHNESS_RESOURCES_ACTIVITY,
    FRESHNESS_RESOURCES_NUTRITION,
    build_freshness,
    build_measurement_coverage,
)
from app.analytics.rollup import resolve_window
from app.analytics.schemas import (
    ACTIVITY_METRIC_UNITS,
    NUTRITION_METRIC_UNITS,
    ActivityMetric,
    ActivityPeriodSummary,
    ActivityTrendResult,
    FreshnessMetadata,
    MetricPeriodSummary,
    MetricTrend,
    MetricWindowAverage,
    NutritionMetric,
    NutritionPeriodSummary,
    NutritionTrendResult,
)
from app.core.time import local_day, utc_now
from app.db.models.health import HealthDailyMetric
from app.db.repositories.sync_state import PROVIDER_APPLE_HEALTH

_VALUE_QUANTUM = Decimal("0.001")
_PERCENT_QUANTUM = Decimal("0.01")

# The 30-day window is the widest HEALTH-12/NUTR-04 need; [anchor-29, anchor] is 30 calendar
# days inclusive. `bodyweight.py`'s "one fetch, folded N ways" rule at this module's grain.
_FETCH_SPAN_DAYS = 29

# D-06 decision, from `docs/health-auto-export-setup.md` section 11 ("Nutrition and activity
# coverage measurement (Phase 13, D-06)"), 2026-09-04: nutrition trend analytics reuse
# `MEASURED_DAY_FLOORS` (the existing 3-of-7, 5-of-14, 10-of-30 floors) unchanged, per Phase
# 13's D-06 research gap, which this measurement attempt could not close live -- treat any
# resulting `insufficient_data` response as correct, not broken, until a future re-measurement
# replaces this comment. (Rephrased here from the doc's own digit-slash-digit shorthand for
# these same three floors, to avoid tripping the Epley-divisor guard in
# `test_analytics_isolation.py`, which reads a slash immediately followed by thirty as that
# pattern; the decision content is unchanged.)
# `period_measured_day_floor` below GENERALIZES those same three floors (D-15) to an arbitrary
# report-period length rather than competing with them.
PERIOD_FLOOR_FRACTION = Decimal("0.33")
PERIOD_FLOOR_MIN_DAYS = 2


def period_measured_day_floor(days_in_period: int) -> int:
    """The minimum measured-day count a report PERIOD needs before its total is believable.

    GENERALIZES ``MEASURED_DAY_FLOORS`` rather than competing with it: ``ceil(0.33 * n)``
    reproduces D-15's three published floors exactly -- 7->3, 14->5, 30->10 -- which is what
    makes a computed floor for an arbitrary report period defensible instead of invented. The
    ``min(..., days_in_period)`` clamp exists because a 1-day period cannot satisfy a floor of 2
    and would otherwise report ``insufficient_data`` for a period whose only day was fully
    logged.

    ``is_measurement_insufficient`` is deliberately NOT reused here: it raises on an unsupported
    window length by design, and relaxing that to serve this path would weaken the guard for
    ``bodyweight.py`` too.
    """
    if days_in_period < 1:
        raise ValueError("period length must be at least one day")
    scaled = int(
        (Decimal(days_in_period) * PERIOD_FLOOR_FRACTION).to_integral_value(
            rounding=ROUND_CEILING
        )
    )
    return min(max(PERIOD_FLOOR_MIN_DAYS, scaled), days_in_period)


@dataclass(frozen=True, slots=True)
class HealthMetricRow:
    """One ``health_daily_metrics`` row, narrowed to the three columns this module folds."""

    metric: str
    local_day: dt.date
    value: Decimal


async def _metric_rows(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    metrics: Sequence[str],
    start_day: dt.date,
    end_day: dt.date,
) -> list[HealthMetricRow]:
    """Every row for the given metrics in an INCLUSIVE local-day range, ordered deterministically.

    ONE query for all metrics of a kind, folded N ways by ``_fold_by_metric_day`` -- not one
    query per metric. ``user_id`` leads the WHERE clause (T-04-02, ASVS V4) and is keyword-only
    with no default. ``metrics`` is a BOUND ``IN`` list built from a closed ``StrEnum``, never an
    interpolated string (ASVS V5, Ruff S608).
    """
    result = await session.execute(
        select(HealthDailyMetric.metric, HealthDailyMetric.local_day, HealthDailyMetric.value)
        .where(
            HealthDailyMetric.user_id == user_id,
            HealthDailyMetric.source == PROVIDER_APPLE_HEALTH,
            HealthDailyMetric.metric.in_(metrics),
            HealthDailyMetric.local_day >= start_day,
            HealthDailyMetric.local_day <= end_day,
        )
        .order_by(HealthDailyMetric.metric, HealthDailyMetric.local_day)
    )
    return [
        HealthMetricRow(metric=row.metric, local_day=row.local_day, value=row.value)
        for row in result.all()
    ]


def _fold_by_metric_day(rows: Sequence[HealthMetricRow]) -> dict[str, dict[dt.date, Decimal]]:
    """One value per (metric, local_day), summed across ``source_name``.

    Real production has multi-source days: 2026-08-23, ``Foodvisor`` and ``Built With Science``
    both wrote ``dietary_energy`` for the same day, and all twelve registry metrics declare
    ``aggregation="sum"`` -- so summing is the registry-sanctioned fold, and picking one row
    would silently report a fraction of the day.
    """
    by_metric: dict[str, dict[dt.date, Decimal]] = {}
    for row in rows:
        by_day = by_metric.setdefault(row.metric, {})
        by_day[row.local_day] = by_day.get(row.local_day, Decimal(0)) + row.value
    return by_metric


def _window_average(
    by_day: Mapping[dt.date, Decimal], *, end_day: dt.date, window_days: int
) -> tuple[Decimal | None, int]:
    """Mean over the measured days inside the INCLUSIVE window ``[end_day - (n-1), end_day]``.

    Copied from ``bodyweight.py`` verbatim except for the quantum. Returns ``(None, 0)`` for an
    empty window, never a zero average -- a zero would read as "you took zero steps".
    """
    start_day = end_day - dt.timedelta(days=window_days - 1)
    values = [value for day, value in by_day.items() if start_day <= day <= end_day]
    if not values:
        return None, 0
    total = sum(values, Decimal(0))
    return (total / Decimal(len(values))).quantize(_VALUE_QUANTUM), len(values)


def _window_total(
    by_day: Mapping[dt.date, Decimal], *, end_day: dt.date, window_days: int
) -> Decimal | None:
    """Sum over the measured days in the same inclusive window as ``_window_average``.

    ``None`` on an empty window, never a zero -- for the same reason ``_window_average`` never
    returns a zero average.
    """
    start_day = end_day - dt.timedelta(days=window_days - 1)
    values = [value for day, value in by_day.items() if start_day <= day <= end_day]
    if not values:
        return None
    return sum(values, Decimal(0)).quantize(_VALUE_QUANTUM)


async def _earliest_day_per_metric(
    session: AsyncSession, *, user_id: uuid.UUID, metrics: Sequence[str]
) -> dict[str, dt.date]:
    """The earliest logged day of EACH metric, independently -- the per-metric sibling of
    ``metadata.earliest_measurement_at``.

    A per-metric ``earliest`` is what separates "you did not log this in the window" from "your
    history does not reach back that far", and a table-wide MIN would report a 2022 date for a
    metric first recorded in 2026. ONE query, grouped by metric -- not one query per metric.
    """
    result = await session.execute(
        select(HealthDailyMetric.metric, func.min(HealthDailyMetric.local_day))
        .where(
            HealthDailyMetric.user_id == user_id,
            HealthDailyMetric.source == PROVIDER_APPLE_HEALTH,
            HealthDailyMetric.metric.in_(metrics),
        )
        .group_by(HealthDailyMetric.metric)
    )
    return {metric: earliest for metric, earliest in result.all()}


async def _trend_for(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    metric_values: Sequence[str],
    units: Mapping[str, str],
    freshness_resources: Sequence[tuple[str, str]],
) -> tuple[dt.date, list[MetricTrend], FreshnessMetadata]:
    """The shared HEALTH-12/NUTR-04 fold: one fetch, folded per metric per window.

    Anchor-day probe idiom verbatim from ``bodyweight.py``. ONE ``_metric_rows`` call over
    ``[anchor - _FETCH_SPAN_DAYS, anchor]``, folded per metric per window (7, 14, 30), each with
    its OWN ``build_measurement_coverage`` floor.
    """
    probe_day = local_day(utc_now(), "UTC")
    tz = (
        await resolve_window(
            session,
            user_id=user_id,
            start_day=probe_day,
            end_day=probe_day,
            snap_to_weeks=False,
        )
    ).tz
    anchor = local_day(utc_now(), tz)

    rows = await _metric_rows(
        session,
        user_id=user_id,
        metrics=metric_values,
        start_day=anchor - dt.timedelta(days=_FETCH_SPAN_DAYS),
        end_day=anchor,
    )
    by_metric = _fold_by_metric_day(rows)
    earliest = await _earliest_day_per_metric(session, user_id=user_id, metrics=metric_values)

    metric_trends: list[MetricTrend] = []
    for metric in metric_values:
        by_day = by_metric.get(metric, {})

        windows: list[MetricWindowAverage] = []
        window_avgs: dict[int, Decimal | None] = {}
        window_insufficient: dict[int, bool] = {}
        for window_days in (7, 14, 30):
            avg, measured_days = _window_average(by_day, end_day=anchor, window_days=window_days)
            total = _window_total(by_day, end_day=anchor, window_days=window_days)
            coverage = build_measurement_coverage(
                window_days=window_days,
                measured_days=measured_days,
                earliest_measurement_at=earliest.get(metric),
            )
            window_avgs[window_days] = None if coverage.insufficient_data else avg
            window_insufficient[window_days] = coverage.insufficient_data
            windows.append(
                MetricWindowAverage(
                    window_days=window_days,
                    average=None if coverage.insufficient_data else avg,
                    total=None if coverage.insufficient_data else total,
                    coverage=coverage,
                )
            )

        change_percent: Decimal | None = None
        avg_7 = window_avgs[7]
        avg_30 = window_avgs[30]
        if (
            avg_7 is not None
            and avg_30 is not None
            and not window_insufficient[7]
            and not window_insufficient[30]
            and avg_30 != 0
        ):
            change_percent = (Decimal(100) * (avg_7 - avg_30) / avg_30).quantize(
                _PERCENT_QUANTUM
            )

        latest_measured_on: dt.date | None = None
        latest_value: Decimal | None = None
        if by_day:
            latest_measured_on = max(by_day)
            latest_value = by_day[latest_measured_on]

        metric_trends.append(
            MetricTrend(
                metric=metric,
                unit=units[metric],
                windows=windows,
                change_percent_7d_vs_30d=change_percent,
                latest_measured_on=latest_measured_on,
                latest_value=latest_value,
            )
        )

    freshness = await build_freshness(session, user_id=user_id, resources=freshness_resources)
    return anchor, metric_trends, freshness


async def _period_for(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    metric_values: Sequence[str],
    units: Mapping[str, str],
    start_day: dt.date,
    end_day: dt.date,
) -> list[MetricPeriodSummary]:
    """The shared RPT-01/RPT-02 fold: one fetch over an explicit closed period, folded per metric.

    Mirrors ``_trend_for``'s shape but with a COMPUTED floor (``period_measured_day_floor``)
    instead of a looked-up one, since a report period is not one of ``MEASURED_DAY_FLOORS``'s
    four supported window lengths.
    """
    if end_day < start_day:
        raise ValueError("end_day precedes start_day")

    days_in_period = (end_day - start_day).days + 1
    floor_days = period_measured_day_floor(days_in_period)

    rows = await _metric_rows(
        session, user_id=user_id, metrics=metric_values, start_day=start_day, end_day=end_day
    )
    by_metric = _fold_by_metric_day(rows)

    summaries: list[MetricPeriodSummary] = []
    for metric in metric_values:
        by_day = by_metric.get(metric, {})
        measured_days = len(by_day)
        insufficient_data = measured_days < floor_days
        total: Decimal | None = None
        daily_average: Decimal | None = None
        if by_day:
            total = sum(by_day.values(), Decimal(0)).quantize(_VALUE_QUANTUM)
            daily_average = (total / Decimal(measured_days)).quantize(_VALUE_QUANTUM)
        summaries.append(
            MetricPeriodSummary(
                metric=metric,
                unit=units[metric],
                daily_average=None if insufficient_data else daily_average,
                total=None if insufficient_data else total,
                measured_days=measured_days,
                days_in_period=days_in_period,
                floor_days=floor_days,
                insufficient_data=insufficient_data,
            )
        )
    return summaries


async def get_activity_trend(session: AsyncSession, *, user_id: uuid.UUID) -> ActivityTrendResult:
    """HEALTH-12: 7-, 14- and 30-day rolling activity averages, independent per window/metric.

    Takes no date range on purpose. "How active have I been" is always anchored on today, and a
    caller-supplied end date would let a stale anchor produce a confident-looking figure from a
    window that has since been superseded.

    Activity data is recomposition CONTEXT, never a classifier input. Nothing in
    ``recomposition.py`` reads this module, and nothing should.

    ``user_id`` is keyword-only with no default (ASVS V4). The caller owns the transaction;
    nothing here writes.
    """
    metric_values = [m.value for m in ActivityMetric]
    units = {m.value: unit for m, unit in ACTIVITY_METRIC_UNITS.items()}
    anchor, metrics, freshness = await _trend_for(
        session,
        user_id=user_id,
        metric_values=metric_values,
        units=units,
        freshness_resources=FRESHNESS_RESOURCES_ACTIVITY,
    )
    return ActivityTrendResult(anchor_day=anchor, metrics=metrics, freshness=freshness)


async def get_nutrition_trend(
    session: AsyncSession, *, user_id: uuid.UUID
) -> NutritionTrendResult:
    """NUTR-04: 7-, 14- and 30-day rolling nutrition averages, independent per window/metric.

    Takes no date range for the same reason ``get_activity_trend`` does not -- "how's my
    nutrition been" is always anchored on today.

    Returns all seven values always (D-08 -- no metric selector, ever). Per 13-RESEARCH.md
    Pitfall 2 each metric carries its OWN coverage, never one shared flag: real production data
    shows the macros are not perfectly co-logged.

    ``user_id`` is keyword-only with no default (ASVS V4). The caller owns the transaction;
    nothing here writes.
    """
    metric_values = [m.value for m in NutritionMetric]
    units = {m.value: unit for m, unit in NUTRITION_METRIC_UNITS.items()}
    anchor, metrics, freshness = await _trend_for(
        session,
        user_id=user_id,
        metric_values=metric_values,
        units=units,
        freshness_resources=FRESHNESS_RESOURCES_NUTRITION,
    )
    return NutritionTrendResult(anchor_day=anchor, metrics=metrics, freshness=freshness)


async def get_activity_period_summary(
    session: AsyncSession, *, user_id: uuid.UUID, start_day: dt.date, end_day: dt.date
) -> ActivityPeriodSummary:
    """RPT-01/RPT-02's activity section, over the REPORT's own explicit closed period.

    Sharing the report's window rather than an independent rolling one is deliberate -- a report
    whose training figures cover Monday-to-today and whose activity figures cover the trailing
    thirty days would have two sections visibly disagreeing about what "this week" means.
    ``get_activity_trend`` is where the rolling view lives.

    ``user_id`` is keyword-only with no default (ASVS V4). The caller owns the transaction;
    nothing here writes.
    """
    metric_values = [m.value for m in ActivityMetric]
    units = {m.value: unit for m, unit in ACTIVITY_METRIC_UNITS.items()}
    metrics = await _period_for(
        session,
        user_id=user_id,
        metric_values=metric_values,
        units=units,
        start_day=start_day,
        end_day=end_day,
    )
    return ActivityPeriodSummary(
        window_start=start_day,
        window_end=end_day,
        days_in_period=(end_day - start_day).days + 1,
        metrics=metrics,
    )


async def get_nutrition_period_summary(
    session: AsyncSession, *, user_id: uuid.UUID, start_day: dt.date, end_day: dt.date
) -> NutritionPeriodSummary:
    """RPT-01/RPT-02's nutrition section, over the REPORT's own explicit closed period.

    Same period-sharing rule as ``get_activity_period_summary`` -- sharing the report's window
    rather than an independent rolling one, so the report cannot visibly disagree with itself
    about what "this week" means.

    ``user_id`` is keyword-only with no default (ASVS V4). The caller owns the transaction;
    nothing here writes.
    """
    metric_values = [m.value for m in NutritionMetric]
    units = {m.value: unit for m, unit in NUTRITION_METRIC_UNITS.items()}
    metrics = await _period_for(
        session,
        user_id=user_id,
        metric_values=metric_values,
        units=units,
        start_day=start_day,
        end_day=end_day,
    )
    return NutritionPeriodSummary(
        window_start=start_day,
        window_end=end_day,
        days_in_period=(end_day - start_day).days + 1,
        metrics=metrics,
    )
