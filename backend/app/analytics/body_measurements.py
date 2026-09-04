"""BODY-05: latest-vs-earliest circumference/composition comparison over a fixed 90-day window.

**Deliberately NOT ``bodyweight.py``'s rolling-average shape (D-05/D-06).** On live production
data 13 of the 16 in-scope columns have never been recorded once, and ``waist_cm`` -- the
best-covered of them -- holds exactly 2 readings in the trailing 90 days. A 3/5/10 measured-day
floor built for a metric weighed in daily would answer ``insufficient_data`` to essentially every
real call this tool will ever receive; a two-point latest-vs-earliest comparison over a wider
window is what actually matches how someone spot-checks a tape measure.

**``insufficient_data`` and ``is_stale`` are INDEPENDENT signals (D-08), never one flag.** All four
combinations are reachable: two readings four months apart are comparable AND stale; one fresh
reading is stale=False AND insufficient. Collapsing them into one flag would make "we cannot
compare" and "this is old news" the same sentence, and only one of those is a reason to distrust
the number.

**There is no quantization here.** The source columns are ``Numeric(6, 2)``/``Numeric(5, 2)``, so
a ``Decimal`` subtraction of two already-precise values is exact -- ``bodyweight.py``'s
``_WEIGHT_QUANTUM`` exists to correct drift introduced by AVERAGING N readings, and this function
never averages.

**There is no source-precedence tie-break.** D-03 leaves ``bodyweight.py``'s "manual wins over
hevy" rule dormant here: only ``'hevy'`` ever writes ``body_measurements`` under this scope, so the
same-day conflict that rule resolves cannot occur on real data. Same-day rows are folded by a
deterministic ``ORDER BY (measured_on, source)`` instead, which is the only property that matters
when the tie itself is unreachable.

Read-only, like everything else under ``app/analytics/``: nothing here writes, and the CALLER owns
the transaction. The session is positional and everything else keyword-only, matching
``app/db/repositories/``.
"""

import datetime as dt
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.analytics.metadata import (
    FRESHNESS_RESOURCES_BODY,
    build_freshness,
    build_measurement_coverage,
    earliest_metric_measurement_at,
)
from app.analytics.rollup import resolve_window
from app.analytics.schemas import BodyMeasurementMetric, BodyMeasurementTrendResult
from app.core.time import local_day, utc_now
from app.db.models.body import BodyMeasurement

# D-06. Wide enough to usually catch two readings of an occasionally-tracked metric -- live
# `waist_cm` has a 14-day median gap and a 119-day worst case -- while still reading as a recent
# trend rather than an all-time comparison. INCLUSIVE on both ends: [anchor - 89, anchor] is 90
# calendar days, not 91.
WINDOW_DAYS = 90

# D-08. [ASSUMED], and echoed on every response as `stale_after_days` rather than hidden here,
# precisely because no external authority governs "how old is too old" for a tape measure. Set at
# roughly 2x the observed 14-day median gap between real `waist_cm` readings, so a metric tracked
# at its historical cadence does not spuriously flag while one that has gone quiet for a third of
# the window does. A one-constant change if the user disagrees.
STALE_AFTER_DAYS = 30


@dataclass(frozen=True, slots=True)
class MetricReading:
    """One non-null reading of one metric. Frozen: nothing folds into it."""

    measured_on: dt.date
    source: str
    value: Decimal


def fold_by_day(readings: Sequence[MetricReading]) -> dict[dt.date, Decimal]:
    """One value per measured day.

    No precedence rule, deliberately (D-03). ``bodyweight.py`` prefers ``'manual'`` over ``'hevy'``
    because BODY-01 has a manual-correction path; BODY-05 does not and will not under this phase's
    scope, so every row here is ``source='hevy'`` and the conflict this would resolve cannot occur
    on real data. The caller orders by ``(measured_on, source)``, so the surviving value for a day
    is the alphabetically-last source -- DETERMINISTIC rather than arbitrary, which is the only
    property that matters when the tie cannot happen.
    """
    return {reading.measured_on: reading.value for reading in readings}


def staleness(latest_measured_on: dt.date | None, *, anchor: dt.date) -> tuple[bool, int | None]:
    """D-08: how old the newest reading is, computed INDEPENDENTLY of the coverage floor.

    Returns ``(is_stale, days_since_latest_reading)``. With no reading in the window there is no
    "latest" to be stale, so the answer is ``(False, None)`` -- NOT ``(True, None)``. "We have
    nothing" is ``coverage.insufficient_data``'s sentence to say, and saying it twice in two fields
    would make a metric that was never measured indistinguishable from one that was abandoned.

    A single reading in the window still gets a real age. It failed the floor for a COMPARISON,
    which says nothing about whether the observation itself is recent.
    """
    if latest_measured_on is None:
        return False, None
    elapsed = (anchor - latest_measured_on).days
    return elapsed > STALE_AFTER_DAYS, elapsed


async def _metric_readings(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    column: InstrumentedAttribute[Decimal | None],
    start_day: dt.date,
    end_day: dt.date,
) -> list[MetricReading]:
    """Every non-null reading of one metric in an INCLUSIVE local-date range.

    ``column.is_not(None)`` is in the WHERE clause rather than filtered in Python because a NULL
    is not a reading of zero -- Hevy writes all 17 columns on every sync and leaves the untracked
    ones NULL, so without this predicate ``measured_days_in_window`` would count every sync date
    and the floor would clear for a metric that was never measured.

    ``measured_on`` is a calendar Date compared against two ``dt.date`` bounds with no timezone
    conversion of any kind. Threading UTC instants through here by analogy with the workout
    aggregates would be a category error and would shift the boundary days by seven hours.

    Ordered ``(measured_on, source)`` so ``fold_by_day``'s same-day resolution is
    order-INDEPENDENT rather than order-dependent by luck.
    """
    result = await session.execute(
        select(BodyMeasurement.measured_on, BodyMeasurement.source, column)
        .where(
            # T-11-02 / ASVS V4: the tenant predicate leads.
            BodyMeasurement.user_id == user_id,
            column.is_not(None),
            BodyMeasurement.measured_on >= start_day,
            BodyMeasurement.measured_on <= end_day,
        )
        .order_by(BodyMeasurement.measured_on, BodyMeasurement.source)
    )
    return [MetricReading(measured_on=row[0], source=row[1], value=row[2]) for row in result.all()]


async def get_body_measurement_trend(
    session: AsyncSession, *, user_id: uuid.UUID, metric: BodyMeasurementMetric
) -> BodyMeasurementTrendResult:
    """BODY-05: one metric's latest reading against its earliest inside a fixed 90-day window.

    Takes no date range, for the same reason ``get_body_weight_trend`` does not: "how has my
    waist changed" is always a question about now, and a caller-supplied anchor would let a stale
    window produce a confident-looking delta that has since been superseded.

    ``metric`` is a ``BodyMeasurementMetric``, never a string. ``getattr`` on a closed 16-member
    enum whose values are asserted equal to the ORM's own column names is the entire validation
    story (D-09) -- the MCP layer's schema rejects an unknown name before this function is
    reached, and a hand-written membership check here would be a second copy of the same list,
    free to drift from the first.

    ``user_id`` is keyword-only with no default (ASVS V4). The caller owns the transaction;
    nothing here writes.
    """
    column: InstrumentedAttribute[Decimal | None] = getattr(BodyMeasurement, metric.value)

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

    readings = await _metric_readings(
        session,
        user_id=user_id,
        column=column,
        start_day=anchor - dt.timedelta(days=WINDOW_DAYS - 1),
        end_day=anchor,
    )
    by_day = fold_by_day(readings)
    days = sorted(by_day)

    coverage = build_measurement_coverage(
        window_days=WINDOW_DAYS,
        measured_days=len(by_day),
        earliest_measurement_at=await earliest_metric_measurement_at(
            session, user_id=user_id, column=column
        ),
    )

    latest_day = days[-1] if days else None
    is_stale, days_since = staleness(latest_day, anchor=anchor)

    # The earliest endpoint and the delta exist ONLY above the floor. With one reading, "earliest"
    # IS "latest" and the delta is a guaranteed zero -- which reads as "your waist has not
    # changed" rather than "you measured it once", the single most misleading thing this function
    # could return.
    earliest_day = days[0] if not coverage.insufficient_data else None
    latest_value = by_day[latest_day] if latest_day is not None else None
    earliest_value = by_day[earliest_day] if earliest_day is not None else None
    delta = (
        latest_value - earliest_value
        if latest_value is not None and earliest_value is not None
        else None
    )

    return BodyMeasurementTrendResult(
        metric=metric,
        window_days=WINDOW_DAYS,
        anchor_day=anchor,
        coverage=coverage,
        # Populated whenever ANY reading exists, floor notwithstanding: a single reading is a real
        # observation, and suppressing it would report "no data" for a metric the user
        # demonstrably measured.
        latest_value=latest_value,
        latest_measured_on=latest_day,
        earliest_value=earliest_value,
        earliest_measured_on=earliest_day,
        # No `.quantize(...)`. Both operands are already 2-decimal `Numeric` values, so the
        # difference is exact -- `bodyweight.py`'s `_WEIGHT_QUANTUM` exists because it AVERAGES,
        # and this never does.
        delta_value=delta,
        is_stale=is_stale,
        days_since_latest_reading=days_since,
        stale_after_days=STALE_AFTER_DAYS,
        freshness=await build_freshness(
            session, user_id=user_id, resources=FRESHNESS_RESOURCES_BODY
        ),
    )
