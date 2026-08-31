"""Rolling body-weight averages and rate of change (BODY-01, D-13 through D-17).

The first module in ``backend/app/`` to read ``body_measurements`` for analysis, and the first to
window on a calendar ``Date`` column rather than on a timestamp. ``rollup.py``'s timezone
apparatus therefore applies to exactly one thing here -- choosing the anchor DAY -- and to none of
the row comparisons: ``measured_on`` is already a local calendar date, and converting it would be
inventing a time of day that was never measured.

**No interpolation and no carry-forward (D-13).** Every average is over the days that actually
have a weigh-in. Filling the gaps would bias the number on an assumption -- linear? last known
value? -- that is not a measurement, and it would hide exactly the sparsity Claude needs to see.
On live data there is a real 52-day gap between 2026-06-15 and 2026-08-06; interpolation would
fabricate that into a smooth line.

**Each window has its OWN floor, and they are independent (D-15).** 7-day needs 3 measured days,
14-day needs 5, 30-day needs 10. A 30-day average can be trustworthy while the 7-day one is not,
and vice versa -- the same additive relationship ``MuscleGroupVolume``'s per-muscle flag has with
the response-level one, not a replacement for it.

**The reported rate is SMOOTHED over four weeks (D-16), never a single week.** Blueprint 25's own
worked example compares this week's 7-day average against last week's. Water, sodium, carbohydrate
and glycogen swings alone move a 65-80 kg person's week-over-week number by several hundred grams:
on live data the raw single-week delta is +0.475 kg, which on 65.65 kg is +0.72%/week -- nearly
THREE TIMES BODY-02's lean-bulk threshold, from noise. The raw delta is still surfaced as
``latest_week_delta_kg`` (D-17) because it is useful context, and it is never what BODY-02
classifies against.

**`insufficient_data` is the expected answer on today's live data, and that is correct.** The
D-16 anchor window needs a 7-day average from four weeks ago, and on 2026-08-30 that window holds
zero weigh-ins. Every test in this module uses synthetic fixtures under a frozen clock: a test
written against live data would assert null today and silently start passing for the wrong reason
around 2026-09-06.

Read-only, like everything else under ``app/analytics/``: nothing here writes, and the CALLER
owns the transaction. The session is positional and everything else keyword-only, matching
``app/db/repositories/``.
"""

import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.metadata import (
    FRESHNESS_RESOURCES_BODY,
    build_freshness,
    build_measurement_coverage,
    earliest_measurement_at,
    is_measurement_insufficient,
)
from app.analytics.rollup import resolve_window
from app.analytics.schemas import BodyWeightTrendResult
from app.core.time import local_day, utc_now
from app.db.models.body import BodyMeasurement

# D-16: four weeks, matching D-05's "minimum meaningful window" so the phase carries ONE concept
# and not two.
TREND_ANCHOR_WEEKS = 4

# Every window BODY-01 needs lives inside [anchor - 34, anchor]:
#   current 7d   = [anchor-6,  anchor]
#   prior 7d     = [anchor-13, anchor-7]    <- D-17's raw week-over-week delta
#   current 14d  = [anchor-13, anchor]
#   current 30d  = [anchor-29, anchor]
#   D-16 anchor  = [anchor-34, anchor-28]   <- the widest reach back
# 35 days, <=35 rows. ONE fetch, folded five ways. Five queries would be five round trips for no
# new information -- `volume.py`'s "one aggregate, folded once" rule at a different grain.
_FETCH_SPAN_DAYS = 34

# D-14: a manual entry is a deliberate correction of that day's number, so it wins.
MANUAL_SOURCE = "manual"

# Three decimals, not two. `body_measurements.weight_kg` is Numeric(6, 2), but the AVERAGE of N
# two-decimal readings genuinely carries more precision, and rounding it to 0.01 before the rate
# calculation would push up to 10 g of drift into a figure BODY-02 compares against a
# +/-0.10%/week band that is itself only ~65 g/week at this user's bodyweight.
_WEIGHT_QUANTUM = Decimal("0.001")
_PERCENT_QUANTUM = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class BodyMeasurementRow:
    """One weigh-in. Frozen: nothing folds INTO it, unlike ``SessionBest``.

    ``source`` is carried solely for D-14's tie-break and never surfaces in a return type.
    """

    measured_on: dt.date
    source: str
    weight_kg: Decimal | None


async def _weight_rows(
    session: AsyncSession, *, user_id: uuid.UUID, start_day: dt.date, end_day: dt.date
) -> list[BodyMeasurementRow]:
    """Every weigh-in in an INCLUSIVE local-date range, ordered deterministically.

    ``measured_on`` is compared directly against two ``dt.date`` bounds, INCLUSIVE on both ends.
    No timezone conversion of any kind: the column is already a calendar day. Threading
    ``utc_start``/``utc_end`` through here by analogy with the workout aggregates would be a
    category error and would shift the boundary days by seven hours.

    ``user_id`` is keyword-only with no default: ASVS V4 -- the schema is multi-user-ready, so an
    unscoped read is a cross-tenant disclosure a single-user suite cannot see.

    Ordered ``(measured_on, source)`` so ``'hevy'`` precedes ``'manual'`` alphabetically and the
    D-14 tie-break below is order-INDEPENDENT rather than order-dependent by luck.
    """
    result = await session.execute(
        select(BodyMeasurement.measured_on, BodyMeasurement.source, BodyMeasurement.weight_kg)
        .where(
            # T-04-02: the tenant predicate leads.
            BodyMeasurement.user_id == user_id,
            BodyMeasurement.measured_on >= start_day,
            BodyMeasurement.measured_on <= end_day,
        )
        .order_by(BodyMeasurement.measured_on, BodyMeasurement.source)
    )
    return [
        BodyMeasurementRow(measured_on=row.measured_on, source=row.source, weight_kg=row.weight_kg)
        for row in result.all()
    ]


def _dedupe_by_day(rows: Sequence[BodyMeasurementRow]) -> dict[dt.date, Decimal]:
    """D-14: one weight per measured day, preferring ``'manual'`` over ``'hevy'``.

    In Python rather than a SQL de-duplicating window clause because it is a BUSINESS RULE, and
    business rules live in pure Python here so they are testable with no container. The whole
    population is at most 35 rows, so there is nothing to optimise.

    Moot today -- zero ``'manual'`` rows exist -- and locked now so it cannot silently become a
    double-count the day manual entry ships. The natural key ``(user_id, source, measured_on)``
    explicitly permits two rows for one day, so "average them" and "count the day twice" are both
    reachable failure modes that produce plausible numbers.

    Rows with no weight are dropped: a weigh-in row that recorded only a waist measurement is not
    a body-weight data point, and counting it toward a coverage floor would make sparse data read
    as sufficient.
    """
    by_day: dict[dt.date, Decimal] = {}
    seen_manual: set[dt.date] = set()
    for row in rows:
        if row.weight_kg is None:
            continue
        if row.measured_on in seen_manual:
            continue
        by_day[row.measured_on] = row.weight_kg
        if row.source == MANUAL_SOURCE:
            seen_manual.add(row.measured_on)
    return by_day


def _window_average(
    by_day: Mapping[dt.date, Decimal], *, end_day: dt.date, window_days: int
) -> tuple[Decimal | None, int]:
    """Mean over the measured days inside the INCLUSIVE window ``[end_day - (n-1), end_day]``.

    Returns the average AND the measured-day count. The count is returned rather than the flag
    because this fold does not decide sufficiency -- D-15's floors do, in ``metadata.py``, in one
    place, for every window.

    Returns ``(None, 0)`` for an empty window rather than raising: an empty window is a real and
    common answer, and a zero average would read as a bodyweight of zero.
    """
    start_day = end_day - dt.timedelta(days=window_days - 1)
    values = [weight for day, weight in by_day.items() if start_day <= day <= end_day]
    if not values:
        return None, 0
    total = sum(values, Decimal(0))
    return (total / Decimal(len(values))).quantize(_WEIGHT_QUANTUM), len(values)


async def get_body_weight_trend(
    session: AsyncSession, *, user_id: uuid.UUID
) -> BodyWeightTrendResult:
    """BODY-01: 7-, 14- and 30-day rolling averages, plus the D-16 smoothed weekly rate.

    Takes no date range on purpose. "What is my weight trend" is always anchored on today; a
    caller-supplied end date would let a stale anchor produce a confident-looking rate from a
    window that has since been superseded, and BODY-02 has no use for a historical anchor.

    ``user_id`` is keyword-only with no default (ASVS V4). The caller owns the transaction;
    nothing here writes.
    """
    # `resolve_window` is the ONLY sanctioned reader of `users.timezone` (rollup.py:134-152), but
    # the anchor day cannot be known until the timezone is. Resolve a throwaway one-day window
    # first purely to obtain `tz`, then build the real 35-day window from the LOCAL anchor. The
    # throwaway window is never queried against.
    #
    # A server-local calendar-day call would be wrong twice over: Ruff's DTZ ruleset bans it
    # repo-wide, and it returns the SERVER's calendar day. At UTC+7 the server day and the user
    # day differ for seven hours out of every twenty-four.
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

    # ONE fetch covering every window, folded five ways. See `_FETCH_SPAN_DAYS`.
    rows = await _weight_rows(
        session,
        user_id=user_id,
        start_day=anchor - dt.timedelta(days=_FETCH_SPAN_DAYS),
        end_day=anchor,
    )
    by_day = _dedupe_by_day(rows)
    earliest = await earliest_measurement_at(session, user_id=user_id)

    avg_7, days_7 = _window_average(by_day, end_day=anchor, window_days=7)
    avg_14, days_14 = _window_average(by_day, end_day=anchor, window_days=14)
    avg_30, days_30 = _window_average(by_day, end_day=anchor, window_days=30)
    # D-17's prior week: [anchor-13, anchor-7]. Its own window, its own floor.
    avg_prior, days_prior = _window_average(
        by_day, end_day=anchor - dt.timedelta(days=7), window_days=7
    )
    # D-16's anchor: a 7-day average ending four weeks before today, i.e. [anchor-34, anchor-28].
    avg_anchor, days_anchor = _window_average(
        by_day, end_day=anchor - dt.timedelta(days=7 * TREND_ANCHOR_WEEKS), window_days=7
    )

    coverage_7 = build_measurement_coverage(
        window_days=7, measured_days=days_7, earliest_measurement_at=earliest
    )
    coverage_14 = build_measurement_coverage(
        window_days=14, measured_days=days_14, earliest_measurement_at=earliest
    )
    coverage_30 = build_measurement_coverage(
        window_days=30, measured_days=days_30, earliest_measurement_at=earliest
    )
    coverage_anchor = build_measurement_coverage(
        window_days=7, measured_days=days_anchor, earliest_measurement_at=earliest
    )

    rate_kg: Decimal | None = None
    rate_percent: Decimal | None = None
    # D-16 says so explicitly: the smoothed rate is null if EITHER window fails its floor. A rate
    # computed from one trustworthy endpoint and one guess is not half-trustworthy, it is wrong.
    if (
        avg_7 is not None
        and avg_anchor is not None
        and not coverage_7.insufficient_data
        and not coverage_anchor.insufficient_data
    ):
        rate_kg = ((avg_7 - avg_anchor) / Decimal(TREND_ANCHOR_WEEKS)).quantize(_WEIGHT_QUANTUM)
        if avg_7 != 0:
            # D-10's basis is PERCENT OF BODYWEIGHT per week, and the denominator is the CURRENT
            # 7-day average -- not the anchor and not the mean of the two. "Percent of bodyweight"
            # naturally means percent of PRESENT bodyweight, it is the figure the user would
            # compute by hand, and while gaining it is the more conservative choice: a larger
            # denominator yields a smaller percentage, so D-11's strict +0.25%/week threshold is
            # never tripped by the arithmetic alone. Both windows already passed D-15, so the
            # denominator is never a low-confidence number when the rate exists at all.
            rate_percent = (Decimal(100) * rate_kg / avg_7).quantize(_PERCENT_QUANTUM)

    latest_week_delta: Decimal | None = None
    # D-17 has its OWN independent gate. It is surfaced even when the smoothed rate is null --
    # that is exactly the live-data case today -- and it is NEVER what BODY-02 classifies against.
    if (
        avg_7 is not None
        and avg_prior is not None
        and not coverage_7.insufficient_data
        and not is_measurement_insufficient(window_days=7, measured_days=days_prior)
    ):
        latest_week_delta = (avg_7 - avg_prior).quantize(_WEIGHT_QUANTUM)

    return BodyWeightTrendResult(
        anchor_day=anchor,
        # None when the window fails its own floor -- the average exists arithmetically, but
        # reporting it would present a two-weigh-in mean as a trend anchor.
        average_7d_kg=None if coverage_7.insufficient_data else avg_7,
        average_14d_kg=None if coverage_14.insufficient_data else avg_14,
        average_30d_kg=None if coverage_30.insufficient_data else avg_30,
        coverage_7d=coverage_7,
        coverage_14d=coverage_14,
        coverage_30d=coverage_30,
        trend_anchor_coverage=coverage_anchor,
        trend_rate_kg_per_week=rate_kg,
        trend_rate_percent_per_week=rate_percent,
        latest_week_delta_kg=latest_week_delta,
        freshness=await build_freshness(
            session, user_id=user_id, resources=FRESHNESS_RESOURCES_BODY
        ),
    )
