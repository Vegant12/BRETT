"""PROG-01: the exercise progression series (see also PROG-02 and PROG-03 in this file).

THE load-bearing test is `test_best_set_is_highest_e1rm_not_heaviest`. The wrong answer it
catches is the heaviest-set rule, and the trap is that the obvious fixture cannot see it: a day
containing 60 kg x 10 (e1RM 80.000) and 70 kg x 5 (e1RM 81.667) has its heaviest set and its
highest-estimate set be the SAME set, so both implementations agree. The counterexample is
therefore built the other way round -- 100 kg x 1 (103.333) against 90 kg x 8 (114.000) -- with
the lighter set carrying the higher estimate, which is the only shape that distinguishes them.

Its partner is `test_null_estimate_day_still_returns_a_point`: without it, an implementation that
simply dropped ungated days would pass every value assertion above while deleting 16.8% of real
exercise-sessions (376 of 2,239 on live data) from the series. A deload week, a 5/3/1 wave and a
high-rep accessory day would all read as a training gap.

The `best_set_per_day` tests carry NO integration marker on purpose. D-04's selection rule and
its tie-break are the artefact PROG-02, PROG-03, PROG-04 and CMP-01 all build on, so they must
stay verifiable when Docker is not running -- the same argument `test_analytics_frequency.py`
makes for `sessions_per_week` and `test_analytics_estimates.py` makes for the Epley gates.

Never an approximate-comparison helper anywhere in this file. Reaching for a tolerance here is
the warning sign that a binary floating-point value leaked into an exact-`Decimal` pipeline.

For PROG-02, THE load-bearing test is `test_dead_band_both_sides`. The specific wrong constant it
catches is Decimal("0.005") -- CONTEXT.md's D-18 fraction form pasted into a percent comparison,
which is a band a hundred times too tight and classifies all 28 live exercises as improving or
declining, leaving `stable` unreachable. Its partner is `test_week_offsets_are_not_compressed`:
without it, an implementation that enumerated only the weeks with data would report a stalled
month as continuous progress and every value assertion above would still pass.

For PROG-03, THE load-bearing test is `test_historical_best_is_seeded_from_before_the_lookback`.
The specific wrong number it catches is a streak start that moves when the caller widens the
lookback but the training did not change: seeding the running best from None makes the first
in-window session "improve over nothing", which on live data moved 6 exercises from a correct
full-window plateau to a shorter, later streak.

Its partner is `test_null_estimate_session_neither_extends_nor_breaks`: without it, a deload week
inflates every streak by one session and the verdict flips from "not yet" to "plateaued" for an
exercise that simply changed rep scheme -- 376 of 2,239 live exercise-sessions are in that
category.

All PROG-03 tests freeze the clock: `plateau_duration_days` is measured to NOW, so an unfrozen
test rots within days and the failure looks like an algorithm bug.
"""

import datetime as dt
import uuid
from collections.abc import Sequence
from decimal import Decimal

import pytest
import time_machine
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.estimates import NoEstimateReason
from app.analytics.progression import (
    DEFAULT_PLATEAU_LOOKBACK_WEEKS,
    MIN_TREND_WEEKS,
    PLATEAU_IMPROVEMENT_TOLERANCE,
    PLATEAU_MIN_ELAPSED_DAYS,
    PLATEAU_MIN_QUALIFYING_SESSIONS,
    SessionBest,
    _weekly_slope,
    best_set_per_day,
    classify_trend,
    get_exercise_progression,
    get_exercise_trends,
    get_plateaus,
    scan_plateau,
    weekly_e1rm_points,
)
from app.analytics.rollup import QualifyingSetRow
from app.analytics.schemas import PlateauConfidence, TrendVerdict
from app.db.repositories.sync_state import (
    PROVIDER_HEVY,
    RESOURCE_EXERCISE_TEMPLATES,
    RESOURCE_WORKOUTS,
    complete_sync,
)
from tests.conftest import (
    ANALYTICS_SECOND_USER_ID,
    DEFAULT_USER_ID,
    GoldenBuilder,
    GoldenExercise,
    GoldenSet,
)

# `PROG-*` so these cannot collide with `test_analytics_volume.py`'s `VOL-*`,
# `test_analytics_frequency.py`'s `FREQ-*`, `test_analytics_rollup.py`'s `ROLLUP-*`/`QSR-*`,
# `test_normalization_mapping.py`'s `RESOLVER-*` or the sync suite's `hevy-*`: the container is
# session-scoped and shared.
_BENCH = "PROG-bench"
_PULLUP = "PROG-pullup"
_HIGH_REP = "PROG-highrep"
_UNSYNCED = "PROG-never-synced"
_SHARED = "PROG-shared"
_TREND = "PROG-trend"
_PLATEAU = "PROG-plateau"
_ABANDONED = "PROG-abandoned"

# Three ids whose SORTED order is deliberately not their insertion order, so
# `test_exercises_are_sorted_and_window_is_unsnapped` cannot pass on dict-iteration order.
_TREND_A = "PROG-trend-a"
_TREND_B = "PROG-trend-b"
_TREND_C = "PROG-trend-c"

# Asia/Jakarta is UTC+7, so 02:00Z is 09:00 local on the SAME day -- comfortably inside the local
# day each constant is named for and never at risk of sliding into its neighbour.
_START = dt.date(2026, 8, 3)
_END = dt.date(2026, 8, 30)
_DAY_1 = dt.datetime(2026, 8, 3, 2, 0, tzinfo=dt.UTC)
_DAY_2 = dt.datetime(2026, 8, 10, 2, 0, tzinfo=dt.UTC)
_DAY_3 = dt.datetime(2026, 8, 17, 2, 0, tzinfo=dt.UTC)
_DAY_4 = dt.datetime(2026, 8, 24, 2, 0, tzinfo=dt.UTC)

# Four consecutive Mondays inside `_START`.._END`, which is exactly `MIN_TREND_WEEKS` distinct
# training weeks -- the smallest arrangement D-05 will commit to a verdict on.
_TREND_WEEKS = (_DAY_1, _DAY_2, _DAY_3, _DAY_4)

# Deliberately NOT week-aligned: Wednesday to Tuesday. `_START`/`_END` happen to be a Monday and
# a Sunday, so an implementation that snapped outward to whole weeks would agree with them
# exactly -- this pair is the only shape that can tell the two apart, since snapping widens it to
# Mon 2026-08-03 .. Sun 2026-08-16 and pulls `_DAY_1` into an answer that never asked for it.
_UNALIGNED_START = dt.date(2026, 8, 5)
_UNALIGNED_END = dt.date(2026, 8, 11)

# A window that ENDS before any fixture workout starts, for the empty-series case. Chosen rather
# than "seed nothing" so the test cannot pass vacuously: rows exist, and the window is what
# excludes them.
_EMPTY_START = dt.date(2026, 7, 1)
_EMPTY_END = dt.date(2026, 7, 31)

# The local days those three instants belong to, spelled out rather than derived: deriving them
# with the same timezone arithmetic the code under test uses would make a wrong conversion agree
# with itself.
_LOCAL_DAY_1 = dt.date(2026, 8, 3)
_LOCAL_DAY_2 = dt.date(2026, 8, 10)
_LOCAL_DAY_3 = dt.date(2026, 8, 17)

# 02:00 UTC is 09:00 in Asia/Jakarta -- the UTC day and the local day AGREE here, so the plateau
# tests isolate the streak rule rather than the anchor rule (which 05-06 already pins).
_PLATEAU_NOW = "2026-08-30T02:00:00+00:00"

# The local day `_PLATEAU_NOW` belongs to, and the 12-week lookback start it implies. Both spelled
# out rather than derived: recomputing them with the same arithmetic the code under test uses
# would make an off-by-one agree with itself. `[2026-06-08, 2026-08-30]` inclusive is 84 days,
# which is exactly twelve weeks -- an 85-day span would be twelve weeks plus a day.
_PLATEAU_END = dt.date(2026, 8, 30)
_PLATEAU_START_12W = dt.date(2026, 6, 8)
_PLATEAU_START_24W = dt.date(2026, 3, 16)

# The four weekly sessions every plateau fixture puts INSIDE the 12-week lookback. The streak
# therefore starts on 2026-08-03, which is 27 days before `_PLATEAU_END` -- comfortably past
# D-06's 21-day floor, so these fixtures never sit on the boundary they are not testing.
_PLATEAU_WEEKS = (_DAY_1, _DAY_2, _DAY_3, _DAY_4)
_PLATEAU_DURATION_DAYS = 27

# Strictly before BOTH `_PLATEAU_START_12W` and `_PLATEAU_START_24W`, which is what lets the
# seeding test widen the lookback without pulling a new session into the window. A session between
# the two starts would legitimately lengthen the streak and prove nothing about the seed.
_PRE_LOOKBACK = dt.datetime(2026, 3, 1, 2, 0, tzinfo=dt.UTC)

# A fifth in-window session, five days after the last weekly one, for the cleared-streak case.
_PR_DAY = dt.datetime(2026, 8, 29, 2, 0, tzinfo=dt.UTC)

# Two workout ids on ONE local day. Hand-built rather than random so a failure message names a
# stable value, and distinct so "which workout did the selected set come from" is answerable.
_MORNING_WORKOUT = uuid.UUID("00000000-0000-0000-0000-00000000a001")
_EVENING_WORKOUT = uuid.UUID("00000000-0000-0000-0000-00000000a002")


def _row(
    *,
    weight_kg: Decimal | None,
    reps: int | None,
    set_index: int,
    exercise_type: str | None = "weight_reps",
    local_day: dt.date = _LOCAL_DAY_1,
    workout_id: uuid.UUID = _MORNING_WORKOUT,
    template_external_id: str = _BENCH,
) -> QualifyingSetRow:
    """One hand-built set row, at exactly the grain ``qualifying_set_rows`` returns.

    Hand-built rather than container-sourced because ``best_set_per_day`` is pure: the whole
    reason D-04's fold stops at this grain is that its rules are then testable with no Docker,
    and routing these through Postgres would only re-test the aggregate that
    ``test_analytics_rollup.py`` already covers.
    """
    return QualifyingSetRow(
        workout_id=workout_id,
        local_day=local_day,
        template_external_id=template_external_id,
        title="Bench Press (Barbell)",
        exercise_type=exercise_type,
        set_type="normal",
        set_index=set_index,
        weight_kg=weight_kg,
        reps=reps,
    )


def test_best_set_is_highest_e1rm_not_heaviest() -> None:
    """D-04: the day's headline set is the highest ESTIMATED 1RM, not the heaviest weight.

    Two arrangements, and only the second one is load-bearing. In the first, 70 kg x 5 is both
    the heaviest set and the highest estimate, so a heaviest-weight implementation agrees and the
    assertion proves nothing on its own. The second inverts that relationship deliberately.
    """
    aligned = [
        _row(weight_kg=Decimal("60.000"), reps=10, set_index=0),
        _row(weight_kg=Decimal("70.000"), reps=5, set_index=1),
    ]

    best = best_set_per_day(aligned)[(_BENCH, _LOCAL_DAY_1)]

    assert best.best_weight_kg == Decimal("70.000")
    assert best.best_reps == 5
    assert best.best_e1rm_kg == Decimal("81.667")
    assert best.no_estimate_reason is None

    # The counterexample. 100 x 1 is the heaviest set and estimates at 103.333; 90 x 8 is
    # lighter and estimates at 114.000. The two rules disagree here and nowhere else.
    inverted = [
        _row(weight_kg=Decimal("100.000"), reps=1, set_index=0),
        _row(weight_kg=Decimal("90.000"), reps=8, set_index=1),
    ]

    picked = best_set_per_day(inverted)[(_BENCH, _LOCAL_DAY_1)]

    assert (picked.best_weight_kg, picked.best_reps) == (Decimal("90.000"), 8), (
        "picked the heaviest set (100 kg) instead of the highest estimate (90 kg x 8 = 114.000)"
    )
    assert picked.best_e1rm_kg == Decimal("114.000")


def test_tie_break_prefers_more_reps_then_lower_index() -> None:
    """The tie-break is part of D-04's spec, not an implementation detail.

    Genuine ties happen constantly on machine stacks with fixed increments. Without a stated
    rule the answer depends on row order, which once PROG-03 scans the series as a plateau
    streak is a WRONG answer rather than a flaky one.

    100 kg x 5 and 87.5 kg x 10 both estimate to exactly 116.667 -- an arithmetic tie, not a
    rounding artefact -- so nothing but the reps rule can decide between them.
    """
    equal_estimate = [
        _row(weight_kg=Decimal("100.000"), reps=5, set_index=0),
        _row(weight_kg=Decimal("87.500"), reps=10, set_index=1),
    ]

    more_reps = best_set_per_day(equal_estimate)[(_BENCH, _LOCAL_DAY_1)]

    assert more_reps.best_e1rm_kg == Decimal("116.667")
    assert (more_reps.best_weight_kg, more_reps.best_reps) == (Decimal("87.500"), 10), (
        "at an equal estimate the set with MORE reps wins -- it is the same estimate for more "
        "total work, which is the conservative reading"
    )

    # Equal estimate AND equal reps. The rows differ only in `set_index` and in the workout that
    # carries them, so the LOWER index rule is the only thing that can pick a winner.
    identical = [
        _row(weight_kg=Decimal("60.000"), reps=10, set_index=0, workout_id=_MORNING_WORKOUT),
        _row(weight_kg=Decimal("60.000"), reps=10, set_index=1, workout_id=_EVENING_WORKOUT),
    ]

    lower_index = best_set_per_day(identical)[(_BENCH, _LOCAL_DAY_1)]

    assert lower_index.best_e1rm_kg == Decimal("80.000")
    assert lower_index.workout_id == _MORNING_WORKOUT, (
        "at an equal estimate and equal reps the LOWER set_index wins; the answer fell through "
        "to row order instead"
    )


def test_day_totals_span_all_sets_not_the_best_one() -> None:
    """``sets``/``total_reps``/``volume_kg`` describe the WHOLE day, not the selected set.

    "You did two sets" and "your best set was 70 kg x 5" are different facts, and conflating
    them would report a day's volume as the selected set's volume -- 350 kg instead of 950 kg
    here, a number of the right magnitude in the right units.
    """
    rows = [
        _row(weight_kg=Decimal("60.000"), reps=10, set_index=0),
        _row(weight_kg=Decimal("70.000"), reps=5, set_index=1),
    ]

    best = best_set_per_day(rows)[(_BENCH, _LOCAL_DAY_1)]

    assert best.sets == 2
    assert best.total_reps == 15
    assert best.volume_kg == Decimal("950.000"), (
        "day volume is 60x10 + 70x5 = 950 kg; a figure of 350 means only the selected set was "
        "counted"
    )
    assert best.volume_sets == 2


def test_total_reps_stays_none_when_no_set_reports_reps() -> None:
    """A day of duration-only holds reports ``None`` reps, never a confident ``0``.

    ``COUNT_DURATION_ONLY_SETS`` keeps a timed plank in the hard-set count, so the day exists;
    it just has no rep count to report.
    """
    rows = [
        _row(weight_kg=None, reps=None, set_index=0, exercise_type="duration"),
        _row(weight_kg=None, reps=None, set_index=1, exercise_type="duration"),
    ]

    best = best_set_per_day(rows)[(_BENCH, _LOCAL_DAY_1)]

    assert best.sets == 2
    assert best.total_reps is None, (
        "a confident 0 is a different claim from 'we could not compute this'"
    )
    assert best.volume_sets == 0
    assert best.best_e1rm_kg is None
    assert best.no_estimate_reason is NoEstimateReason.MODALITY


def test_two_workouts_same_local_day_fold_into_one_entry() -> None:
    """One (exercise, local day) is ONE entry, however many workouts contributed to it.

    Training the same lift twice in a day is rare but real, and keying on the workout instead of
    the local day would emit two points for one calendar day -- which PROG-03 would then read as
    two sessions of a plateau streak.
    """
    rows = [
        _row(weight_kg=Decimal("60.000"), reps=10, set_index=0, workout_id=_MORNING_WORKOUT),
        _row(weight_kg=Decimal("70.000"), reps=5, set_index=0, workout_id=_EVENING_WORKOUT),
    ]

    folded = best_set_per_day(rows)

    assert list(folded) == [(_BENCH, _LOCAL_DAY_1)]
    best = folded[(_BENCH, _LOCAL_DAY_1)]
    assert best.sets == 2
    assert best.total_reps == 15
    assert best.workout_id == _EVENING_WORKOUT, (
        "workout_id must identify the workout carrying the SELECTED set, not the first one seen"
    )


# ---------------------------------------------------------------------------
# PROG-02's arithmetic. NO integration marker, for `best_set_per_day`'s reason: the slope, the
# D-18 dead-band and the D-05 gate are business rules, and a business rule that needs Docker to
# be checked is a business rule nobody checks on the commit that breaks it.
# ---------------------------------------------------------------------------

# +1 kg of e1RM per week from a base of 100. Slope exactly 1, so a float leak shows up as a
# trailing-digit mismatch rather than as a plausible-looking number.
_RISING = [
    (0, Decimal("100")),
    (1, Decimal("101")),
    (2, Decimal("102")),
    (3, Decimal("103")),
]

# Mean exactly 100 and slope exactly 0.5000, so `rate_percent_per_week` lands exactly ON D-18's
# +0.5%/week edge. The band is INCLUSIVE there, so this reads as improving.
_AT_BAND = [
    (0, Decimal("99.25")),
    (1, Decimal("99.75")),
    (2, Decimal("100.25")),
    (3, Decimal("100.75")),
]

# Mean exactly 100 and slope exactly 0.4900 -- one hundredth of a percent inside the band.
_INSIDE_BAND = [
    (0, Decimal("99.265")),
    (1, Decimal("99.755")),
    (2, Decimal("100.245")),
    (3, Decimal("100.735")),
]

# The same two series read backwards, so the negative edge is pinned by construction rather than
# by a second hand-computed arrangement that could drift from its mirror.
_AT_BAND_DECLINING = [(x, y) for x, (_, y) in enumerate(reversed(_AT_BAND))]
_INSIDE_BAND_DECLINING = [(x, y) for x, (_, y) in enumerate(reversed(_INSIDE_BAND))]


def _session_best(
    *,
    local_day: dt.date,
    best_e1rm_kg: Decimal | None,
    template_external_id: str = _BENCH,
) -> SessionBest:
    """One folded day at exactly the grain ``best_set_per_day`` returns.

    Hand-built for the same reason ``_row`` is: ``weekly_e1rm_points`` is pure, and routing these
    through Postgres would only re-test the aggregate ``test_analytics_rollup.py`` already covers.
    """
    return SessionBest(
        local_day=local_day,
        template_external_id=template_external_id,
        workout_id=_MORNING_WORKOUT,
        best_e1rm_kg=best_e1rm_kg,
    )


def test_slope_is_exact_decimal() -> None:
    """The OLS slope is closed-form exact ``Decimal``, asserted with ``==`` and no tolerance.

    Four sums and one division, and the denominator depends only on which week offsets are
    present -- an integer for every window -- which is what makes an exact expected value
    assertable at all.
    """
    assert _weekly_slope(_RISING) == Decimal("1.0000"), (
        "a float leaked in -- regr_slope returns double precision even for numeric inputs, and "
        "statistics.linear_regression returns floats"
    )

    assert _weekly_slope([(0, Decimal("100"))]) is None, (
        "one point has no slope; returning zero would read as 'stable' rather than 'unknown'"
    )
    assert _weekly_slope([(2, Decimal("100")), (2, Decimal("110"))]) is None, (
        "every point sharing one week offset makes the denominator zero -- a single week is not "
        "a trend, and it must not raise ZeroDivisionError either"
    )


def test_dead_band_both_sides() -> None:
    """D-18's +-0.5%/week band, pinned at BOTH edges and on BOTH signs.

    THE load-bearing PROG-02 test. The wrong constant it catches is ``Decimal("0.005")`` --
    CONTEXT.md writes D-18 in FRACTION units, and this comparison is in PERCENT units. Pasting
    the fraction here makes the band a hundred times too tight, so every one of the 28 live
    classified exercises reads as improving or declining and ``stable`` becomes unreachable. A
    suite without both edges cannot see that: the improving and declining assertions still pass.

    The edge is INCLUSIVE: exactly +0.5%/week is improving, not stable. An arbitrary choice,
    made once and stated, which is why both sides of it are asserted.
    """
    assert classify_trend(_AT_BAND) == (TrendVerdict.IMPROVING, Decimal("0.50"))
    assert classify_trend(_INSIDE_BAND) == (TrendVerdict.STABLE, Decimal("0.49"))
    assert classify_trend(_AT_BAND_DECLINING) == (TrendVerdict.DECLINING, Decimal("-0.50"))
    assert classify_trend(_INSIDE_BAND_DECLINING) == (TrendVerdict.STABLE, Decimal("-0.49"))


def test_min_weeks_gate_both_sides() -> None:
    """D-05: fewer than four distinct training weeks is ``unclear``, however steep the series.

    Built from ``MIN_TREND_WEEKS`` rather than from a literal 4, so raising the minimum moves
    this test with it instead of leaving it silently asserting the old threshold.
    """
    steep = [(week, Decimal(100 + 20 * week)) for week in range(MIN_TREND_WEEKS)]

    assert classify_trend(steep[:-1]) == (TrendVerdict.UNCLEAR, None), (
        "a +20%/week series still cannot be classified from three weeks -- blueprint 20's "
        "'do not classify progression based on a single workout', scaled to a number"
    )

    verdict, rate = classify_trend(steep)
    assert verdict is TrendVerdict.IMPROVING
    assert rate == Decimal("15.38")


def test_rate_is_scale_invariant() -> None:
    """Doubling every e1RM leaves the rate unchanged, because the normalizer is the window MEAN.

    One band has to be comparable across a 7 kg cable extension and a 160 kg leg press, and the
    mean is what makes it so.
    """
    doubled = [(x, y * Decimal(2)) for x, y in _AT_BAND]

    assert classify_trend(doubled) == (TrendVerdict.IMPROVING, Decimal("0.50")), (
        "normalized by the first point instead of the window mean; the verdict would then depend "
        "on which week the window started in"
    )


def test_week_offsets_are_not_compressed() -> None:
    """A training gap WIDENS the x-axis gap; it is never compressed to consecutive weeks.

    Without this, an implementation that enumerated only the weeks that happen to have data
    would pass every value assertion above while reporting a stalled month as continuous
    progress -- +0.99%/week where the truth is +0.56%/week.
    """
    bests = {
        (_BENCH, local_day): _session_best(local_day=local_day, best_e1rm_kg=e1rm)
        for local_day, e1rm in (
            (dt.date(2026, 8, 3), Decimal("100")),
            (dt.date(2026, 8, 10), Decimal("101")),
            (dt.date(2026, 8, 17), Decimal("102")),
            # Three weeks later, not one: weeks 3 and 4 hold no training at all.
            (dt.date(2026, 9, 7), Decimal("103")),
        )
    }

    points = weekly_e1rm_points(bests, window_start=_START)

    assert [x for x, _ in points[_BENCH]] == [0, 1, 2, 5], (
        "the week offsets were compressed to a dense index over the weeks that had data; the "
        "gap must stay visible on the x-axis"
    )

    gapped = classify_trend(points[_BENCH])
    compressed = classify_trend([(x, y) for x, (_, y) in enumerate(points[_BENCH])])

    assert gapped == (TrendVerdict.IMPROVING, Decimal("0.56"))
    assert compressed == (TrendVerdict.IMPROVING, Decimal("0.99"))
    assert gapped != compressed


def test_weekly_points_take_the_week_maximum_and_skip_nulls() -> None:
    """``y`` is the week's MAXIMUM e1RM, and a null-estimate day contributes no point at all.

    The mean would be dragged down by a deliberately light day, and PROG-02 asks whether the
    CEILING is rising. Both dict orders are checked because a last-wins or first-wins bug agrees
    with the maximum in exactly one of them.
    """
    ascending = {
        (_BENCH, dt.date(2026, 8, 3)): _session_best(
            local_day=dt.date(2026, 8, 3), best_e1rm_kg=Decimal("100")
        ),
        (_BENCH, dt.date(2026, 8, 5)): _session_best(
            local_day=dt.date(2026, 8, 5), best_e1rm_kg=Decimal("110")
        ),
    }
    descending = {
        (_BENCH, dt.date(2026, 8, 3)): _session_best(
            local_day=dt.date(2026, 8, 3), best_e1rm_kg=Decimal("110")
        ),
        (_BENCH, dt.date(2026, 8, 5)): _session_best(
            local_day=dt.date(2026, 8, 5), best_e1rm_kg=Decimal("100")
        ),
    }

    assert weekly_e1rm_points(ascending, window_start=_START)[_BENCH] == [(0, Decimal("110"))]
    assert weekly_e1rm_points(descending, window_start=_START)[_BENCH] == [(0, Decimal("110"))], (
        "the later day overwrote the higher one; two days in one week collapse to the week's "
        "MAXIMUM, not to whichever was folded last"
    )

    # D-07a's skip semantics: an ungated day neither raises nor lowers the ceiling, and it must
    # not manufacture a week offset that would then count toward D-05's four-week minimum.
    with_a_null = dict(ascending)
    with_a_null[(_BENCH, dt.date(2026, 8, 10))] = _session_best(
        local_day=dt.date(2026, 8, 10), best_e1rm_kg=None
    )

    assert weekly_e1rm_points(with_a_null, window_start=_START)[_BENCH] == [(0, Decimal("110"))], (
        "a day with no usable estimate created a week offset; weeks_with_data counts weeks that "
        "produced an ESTIMATE, not weeks trained"
    )


# ---------------------------------------------------------------------------
# PROG-01's public function. Container-backed: the local-day conversion, the tenant-scoped
# template outerjoin and the coverage/freshness envelope have no meaning anywhere else.
# ---------------------------------------------------------------------------

# The two live-observed sync timestamps, 25 minutes apart -- the drift that makes a single
# collapsed `last_synced_at` lossy.
_SYNCED_WORKOUTS_AT = dt.datetime(2026, 8, 30, 5, 43, 18, tzinfo=dt.UTC)
_SYNCED_TEMPLATES_AT = dt.datetime(2026, 8, 30, 6, 8, 4, tzinfo=dt.UTC)


def _bench_exercise(*sets: GoldenSet, template_external_id: str = _BENCH) -> GoldenExercise:
    """One exercise carrying exactly the sets a test names, and no defaults it did not ask for."""
    return GoldenExercise(template_external_id=template_external_id, sets=sets)


@pytest.mark.integration
async def test_progression_series_is_ascending_and_omits_untrained_days(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """One point per TRAINED local day, ascending, and nothing for the 25 days in between.

    The window is 28 days long and holds three workouts. A gap-free day spine would return 28
    points, 25 of them zeros -- which is not the ``volume.py`` case: a zero-training WEEK is
    diagnostically interesting, a non-training DAY is every day, and the signal would be buried.
    """
    await golden_workout.template(external_id=_BENCH, title="Bench Press (Barbell)")
    for start_time, weight in (
        (_DAY_1, Decimal("60.000")),
        (_DAY_2, Decimal("65.000")),
        (_DAY_3, Decimal("70.000")),
    ):
        await golden_workout.workout(
            start_time=start_time,
            exercises=[_bench_exercise(GoldenSet(weight_kg=weight, reps=8))],
        )

    result = await get_exercise_progression(
        session,
        user_id=DEFAULT_USER_ID,
        exercise_template_external_id=_BENCH,
        start_day=_START,
        end_day=_END,
    )

    local_days = [point.local_day for point in result.points]
    assert local_days == [_LOCAL_DAY_1, _LOCAL_DAY_2, _LOCAL_DAY_3], (
        "a gap-free day spine was copied from volume.py; a non-training day is not a "
        "diagnostically interesting zero"
    )
    assert local_days == sorted(local_days)
    assert result.exercise_template_external_id == _BENCH
    assert result.title == "Bench Press (Barbell)"
    assert result.exercise_type == "weight_reps"
    assert result.window_start == _START
    assert result.window_end == _END
    # 60x8 -> 76.000, 65x8 -> 82.333, 70x8 -> 88.667. Ascending in value as well as in date, so
    # a reversed series would be visible here and not only in the day ordering.
    assert [point.estimated_1rm_kg for point in result.points] == [
        Decimal("76.000"),
        Decimal("82.333"),
        Decimal("88.667"),
    ]


@pytest.mark.integration
async def test_window_is_not_snapped_to_whole_weeks(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """D-03: progression follows ``frequency.py``, not ``volume.py`` -- the raw range IS the window.

    Weekly volume widens outward because its buckets must be comparable to one another. A per-day
    series has no such requirement, and snapping would silently return days the caller did not
    ask for -- here, a whole extra training session on 2026-08-03.
    """
    await golden_workout.template(external_id=_BENCH)
    for start_time in (_DAY_1, _DAY_2):
        await golden_workout.workout(
            start_time=start_time,
            exercises=[_bench_exercise(GoldenSet(weight_kg=Decimal("60.000"), reps=8))],
        )

    result = await get_exercise_progression(
        session,
        user_id=DEFAULT_USER_ID,
        exercise_template_external_id=_BENCH,
        start_day=_UNALIGNED_START,
        end_day=_UNALIGNED_END,
    )

    assert (result.window_start, result.window_end) == (_UNALIGNED_START, _UNALIGNED_END), (
        "the window was snapped outward to whole weeks; PROG-01 answers the range it was asked "
        "about"
    )
    assert [point.local_day for point in result.points] == [_LOCAL_DAY_2], (
        "2026-08-03 is outside the requested Wed-to-Tue range and only week snapping could have "
        "pulled it in"
    )


@pytest.mark.integration
async def test_null_estimate_day_still_returns_a_point(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """D-02's rep-range gate removes the ESTIMATE, never the day.

    Dropping ungated days would delete 16.8% of real exercise-sessions (376 of 2,239) from the
    series and make a rep-periodized block read as a training gap. Every other figure the day
    produced is still reportable, and PROG-01 requires a REASON rather than a bare null.
    """
    await golden_workout.template(external_id=_HIGH_REP, title="Cable Fly")
    await golden_workout.workout(
        start_time=_DAY_1,
        exercises=[
            _bench_exercise(
                GoldenSet(weight_kg=Decimal("80.000"), reps=15),
                GoldenSet(weight_kg=Decimal("90.000"), reps=15),
                template_external_id=_HIGH_REP,
            )
        ],
    )

    result = await get_exercise_progression(
        session,
        user_id=DEFAULT_USER_ID,
        exercise_template_external_id=_HIGH_REP,
        start_day=_START,
        end_day=_END,
    )

    assert len(result.points) == 1
    point = result.points[0]
    assert point.estimated_1rm_kg is None
    assert point.no_estimate_reason is NoEstimateReason.REP_RANGE
    # Everything the day actually reported survives the missing estimate.
    assert point.sets == 2
    assert point.total_reps == 30
    assert point.volume_kg == Decimal("2550.000")
    assert point.volume_sets == 2
    assert point.best_weight_kg == Decimal("90.000")
    assert point.best_reps == 15


@pytest.mark.integration
async def test_modality_reason_for_reps_only_day(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """D-03's modality gate, and the ``None``-versus-zero distinction it forces.

    A pull-up day has reps and no weight, so ``volume_kg`` is not computable at all. Reporting
    ``Decimal("0")`` would claim the lifter moved zero kilograms, which is a different and false
    fact -- ``volume_sets`` is what makes the difference visible.
    """
    await golden_workout.template(external_id=_PULLUP, title="Pull Up", exercise_type="reps_only")
    await golden_workout.workout(
        start_time=_DAY_1,
        exercises=[
            _bench_exercise(GoldenSet(reps=12), GoldenSet(reps=10), template_external_id=_PULLUP)
        ],
    )

    result = await get_exercise_progression(
        session,
        user_id=DEFAULT_USER_ID,
        exercise_template_external_id=_PULLUP,
        start_day=_START,
        end_day=_END,
    )

    assert len(result.points) == 1
    point = result.points[0]
    assert point.no_estimate_reason is NoEstimateReason.MODALITY
    assert point.estimated_1rm_kg is None
    assert point.volume_kg is None, (
        "'no set that day had both a weight and reps' is a different fact from 'the day's volume "
        "was zero kilograms'"
    )
    assert point.volume_sets == 0
    assert point.best_weight_kg is None
    assert point.best_reps == 12
    assert point.total_reps == 22
    assert result.exercise_type == "reps_only"


@pytest.mark.integration
async def test_unsynced_template_yields_null_title_and_type_but_still_points(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """A workout may reference a template that is not synced locally, and must still answer.

    ``workout_exercises.exercise_template_external_id`` is a plain string and deliberately not a
    foreign key, so a template deleted upstream or not yet reached by a partial sync must degrade
    to "no title, no modality" rather than block the series. A missing ``exercise_type`` is
    naturally MODALITY under D-03's exact-match gate, never a crash.
    """
    await golden_workout.workout(
        start_time=_DAY_1,
        exercises=[
            _bench_exercise(
                GoldenSet(weight_kg=Decimal("100.000"), reps=5),
                template_external_id=_UNSYNCED,
            )
        ],
    )

    result = await get_exercise_progression(
        session,
        user_id=DEFAULT_USER_ID,
        exercise_template_external_id=_UNSYNCED,
        start_day=_START,
        end_day=_END,
    )

    assert result.title is None
    assert result.exercise_type is None
    assert len(result.points) == 1
    assert result.points[0].no_estimate_reason is NoEstimateReason.MODALITY
    assert result.points[0].best_weight_kg == Decimal("100.000")


@pytest.mark.integration
async def test_second_users_sets_are_invisible(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """ASVS V4 / T-05-22: a single-user suite cannot see a missing tenant predicate.

    Both users are given a template under the SAME external id, because Hevy's built-in template
    ids are GLOBAL. That covers two distinct leaks in one arrangement: the set rows themselves,
    and the outer-joined template whose title and ``exercise_type`` would otherwise be attached
    to this user's answer -- and ``exercise_type`` is the D-03 e1RM gate, so the second leak is a
    correctness bug as well as a disclosure one.
    """
    await golden_workout.user(user_id=ANALYTICS_SECOND_USER_ID)
    await golden_workout.template(external_id=_SHARED, title="Mine")
    await golden_workout.template(
        external_id=_SHARED, title="Theirs", user_id=ANALYTICS_SECOND_USER_ID
    )
    await golden_workout.workout(
        start_time=_DAY_1,
        exercises=[
            _bench_exercise(
                GoldenSet(weight_kg=Decimal("100.000"), reps=5), template_external_id=_SHARED
            )
        ],
    )
    await golden_workout.workout(
        start_time=_DAY_1,
        exercises=[
            _bench_exercise(
                GoldenSet(weight_kg=Decimal("200.000"), reps=5), template_external_id=_SHARED
            )
        ],
        user_id=ANALYTICS_SECOND_USER_ID,
    )

    result = await get_exercise_progression(
        session,
        user_id=DEFAULT_USER_ID,
        exercise_template_external_id=_SHARED,
        start_day=_START,
        end_day=_END,
    )

    assert all(point.best_weight_kg != Decimal("200.000") for point in result.points), (
        "another user's set leaked into this user's progression (ASVS V4)"
    )
    assert result.title == "Mine", (
        "the template outerjoin dropped its own tenant predicate; Hevy's built-in template ids "
        "are global"
    )
    # Guard against a vacuous pass: this user really did train, and the point is theirs.
    assert len(result.points) == 1
    assert result.points[0].best_weight_kg == Decimal("100.000")


@pytest.mark.integration
async def test_empty_window_returns_empty_points_not_an_error(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """No training in the window is an ANSWER, not an exception.

    ``earliest_data_at`` is asserted alongside the empty series because it is what separates
    "you did not train in this window" from "your synced history does not reach back that far" --
    two facts a bare empty list cannot tell apart.
    """
    await golden_workout.template(external_id=_BENCH)
    await golden_workout.workout(
        start_time=_DAY_1,
        exercises=[_bench_exercise(GoldenSet(weight_kg=Decimal("60.000"), reps=8))],
    )

    result = await get_exercise_progression(
        session,
        user_id=DEFAULT_USER_ID,
        exercise_template_external_id=_BENCH,
        start_day=_EMPTY_START,
        end_day=_EMPTY_END,
    )

    assert result.points == []
    assert result.coverage.sessions_in_window == 0
    assert result.coverage.insufficient_data is True
    assert result.coverage.earliest_data_at == _DAY_1
    assert result.title is None
    assert result.exercise_type is None


@pytest.mark.integration
async def test_freshness_names_workouts_and_exercise_templates(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """DQ-01: PROG-01 is only as fresh as the STALER of its two sources.

    Written against the second user because ``sync_state`` rows for the default user are the Hevy
    sync suite's territory and the container is session-scoped and shared.
    """
    await golden_workout.user(user_id=ANALYTICS_SECOND_USER_ID)
    await golden_workout.template(external_id=_BENCH, user_id=ANALYTICS_SECOND_USER_ID)
    await golden_workout.workout(
        start_time=_DAY_1,
        exercises=[_bench_exercise(GoldenSet(weight_kg=Decimal("60.000"), reps=8))],
        user_id=ANALYTICS_SECOND_USER_ID,
    )
    for resource, synced_at in (
        (RESOURCE_WORKOUTS, _SYNCED_WORKOUTS_AT),
        (RESOURCE_EXERCISE_TEMPLATES, _SYNCED_TEMPLATES_AT),
    ):
        await complete_sync(
            session,
            user_id=ANALYTICS_SECOND_USER_ID,
            provider=PROVIDER_HEVY,
            resource=resource,
            last_synced_at=synced_at,
        )

    result = await get_exercise_progression(
        session,
        user_id=ANALYTICS_SECOND_USER_ID,
        exercise_template_external_id=_BENCH,
        start_day=_START,
        end_day=_END,
    )

    assert set(result.freshness.resources) == {RESOURCE_WORKOUTS, RESOURCE_EXERCISE_TEMPLATES}, (
        "exercise_type is the D-03 e1RM gate and comes from the templates table; a stale "
        "template sync silently changes every eligibility decision"
    )
    assert result.freshness.resources == {
        RESOURCE_WORKOUTS: _SYNCED_WORKOUTS_AT,
        RESOURCE_EXERCISE_TEMPLATES: _SYNCED_TEMPLATES_AT,
    }
    # Two genuinely distinct values, not one row read twice.
    assert len(set(result.freshness.resources.values())) == 2


# ---------------------------------------------------------------------------
# PROG-02's public function. Container-backed for the same reason PROG-01's is: the local-day
# conversion, the tenant-scoped template outerjoin and the coverage/freshness envelope have no
# meaning without a database.
# ---------------------------------------------------------------------------


async def _seed_weekly_trend(
    golden_workout: GoldenBuilder,
    *,
    weights: Sequence[Decimal],
    template_external_id: str = _TREND,
    reps: int = 5,
    user_id: uuid.UUID = DEFAULT_USER_ID,
) -> None:
    """One workout per consecutive week, one working set each, at the weights given.

    ``strict=True`` on the zip: a caller passing five weights against four weeks would otherwise
    silently drop one and change the verdict the test is asserting on.
    """
    for start_time, weight in zip(_TREND_WEEKS, weights, strict=True):
        await golden_workout.workout(
            start_time=start_time,
            exercises=[
                _bench_exercise(
                    GoldenSet(weight_kg=weight, reps=reps),
                    template_external_id=template_external_id,
                )
            ],
            user_id=user_id,
        )


@pytest.mark.integration
async def test_improving_verdict_over_four_weeks(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """Four training weeks is the smallest arrangement D-05 will commit to, and it commits.

    100 -> 106 kg x 5 across four weeks is +1.94%/week off a mean e1RM of 120.167 -- comfortably
    outside D-18's +-0.5%/week band, so this cannot pass by landing on a boundary.
    """
    await golden_workout.template(external_id=_TREND, title="Trend Press")
    await _seed_weekly_trend(
        golden_workout,
        weights=[Decimal("100.000"), Decimal("102.000"), Decimal("104.000"), Decimal("106.000")],
    )

    result = await get_exercise_trends(
        session, user_id=DEFAULT_USER_ID, start_day=_START, end_day=_END
    )

    assert len(result.exercises) == 1
    trend = result.exercises[0]
    assert trend.exercise_template_external_id == _TREND
    assert trend.title == "Trend Press"
    assert trend.verdict is TrendVerdict.IMPROVING
    assert trend.weeks_with_data == 4
    assert trend.rate_percent_per_week == Decimal("1.94")


@pytest.mark.integration
async def test_three_training_weeks_is_unclear(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """One week short of D-05's minimum, and the rate is withheld along with the verdict.

    The same series that reads `improving` over four weeks reads `unclear` over three. Reporting
    a rate here would let a caller re-derive a verdict the requirement declined to give.
    """
    await golden_workout.template(external_id=_TREND, title="Trend Press")
    for start_time, weight in zip(
        _TREND_WEEKS[:3],
        (Decimal("100.000"), Decimal("102.000"), Decimal("104.000")),
        strict=True,
    ):
        await golden_workout.workout(
            start_time=start_time,
            exercises=[
                _bench_exercise(GoldenSet(weight_kg=weight, reps=5), template_external_id=_TREND)
            ],
        )

    result = await get_exercise_trends(
        session, user_id=DEFAULT_USER_ID, start_day=_START, end_day=_END
    )

    assert len(result.exercises) == 1
    trend = result.exercises[0]
    assert trend.verdict is TrendVerdict.UNCLEAR, (
        "D-05: committing to a verdict from three weeks is the single-workout failure "
        "blueprint 20 warns about"
    )
    assert trend.rate_percent_per_week is None
    assert trend.weeks_with_data == 3


@pytest.mark.integration
async def test_exercise_with_no_usable_estimate_is_reported_as_unclear(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """Four TRAINING weeks, zero usable estimates -- and the exercise is still reported.

    D-02's rep-range gate removes every estimate, so there is nothing to regress. The exercise
    must not vanish from the response: `weeks_with_data == 0` beside `unclear` is what tells
    Claude "trained but unmeasurable", which a missing row cannot say.
    """
    await golden_workout.template(external_id=_HIGH_REP, title="Cable Fly")
    await _seed_weekly_trend(
        golden_workout,
        weights=[Decimal("80.000")] * 4,
        template_external_id=_HIGH_REP,
        reps=15,
    )

    result = await get_exercise_trends(
        session, user_id=DEFAULT_USER_ID, start_day=_START, end_day=_END
    )

    assert [row.exercise_template_external_id for row in result.exercises] == [_HIGH_REP], (
        "an omitted exercise and a stable one are different facts, and BODY-02's denominator "
        "depends on the distinction"
    )
    trend = result.exercises[0]
    assert trend.weeks_with_data == 0, (
        "weeks_with_data counts weeks that produced an ESTIMATE; reporting 4 training weeks here "
        "would make `unclear` look like a bug"
    )
    assert trend.verdict is TrendVerdict.UNCLEAR
    assert trend.rate_percent_per_week is None


@pytest.mark.integration
async def test_exercises_are_sorted_and_window_is_unsnapped(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """Ascending by external id, and the raw requested range IS the window.

    The templates are written c, a, b so insertion order and sorted order differ -- dict-iteration
    order would pass a `== sorted(ids)` assertion by accident otherwise. The window is the
    Wed-to-Tue `_UNALIGNED_*` pair rather than the week-aligned `_START`/`_END`, because those two
    happen to be a Monday and a Sunday and a snapping implementation would agree with them
    exactly.
    """
    for external_id in (_TREND_C, _TREND_A, _TREND_B):
        await golden_workout.template(external_id=external_id)
    await golden_workout.workout(
        start_time=_DAY_2,
        exercises=[
            _bench_exercise(
                GoldenSet(weight_kg=Decimal("60.000"), reps=8),
                template_external_id=external_id,
            )
            for external_id in (_TREND_C, _TREND_A, _TREND_B)
        ],
    )

    result = await get_exercise_trends(
        session, user_id=DEFAULT_USER_ID, start_day=_UNALIGNED_START, end_day=_UNALIGNED_END
    )

    external_ids = [row.exercise_template_external_id for row in result.exercises]
    assert external_ids == [_TREND_A, _TREND_B, _TREND_C], (
        "the response fell through to dict-iteration order; Phase 6 will diff these between runs"
    )
    assert external_ids == sorted(external_ids)
    assert (result.window_start, result.window_end) == (_UNALIGNED_START, _UNALIGNED_END), (
        "the window was snapped outward to whole weeks; PROG-02 answers the range it was asked "
        "about"
    )


@pytest.mark.integration
async def test_second_users_sets_do_not_change_a_verdict(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """ASVS V4 / T-05-47: a leaked set does not just add a row, it changes the ANSWER.

    Both users train the SAME external id -- Hevy's built-in template ids are global. This user
    is flat at 100 kg for four weeks (`stable`); the other climbs 100 -> 160 kg. A missing tenant
    predicate would fold both series into one exercise and read as `improving`, which is a wrong
    coaching verdict rather than merely an extra row.
    """
    await golden_workout.user(user_id=ANALYTICS_SECOND_USER_ID)
    await golden_workout.template(external_id=_SHARED, title="Mine")
    await golden_workout.template(
        external_id=_SHARED, title="Theirs", user_id=ANALYTICS_SECOND_USER_ID
    )
    await _seed_weekly_trend(
        golden_workout, weights=[Decimal("100.000")] * 4, template_external_id=_SHARED
    )
    await _seed_weekly_trend(
        golden_workout,
        weights=[
            Decimal("100.000"),
            Decimal("120.000"),
            Decimal("140.000"),
            Decimal("160.000"),
        ],
        template_external_id=_SHARED,
        user_id=ANALYTICS_SECOND_USER_ID,
    )

    result = await get_exercise_trends(
        session, user_id=DEFAULT_USER_ID, start_day=_START, end_day=_END
    )

    # Guard against a vacuous pass: this user really did train, and the row is theirs.
    assert len(result.exercises) == 1
    trend = result.exercises[0]
    assert trend.title == "Mine"
    assert trend.verdict is TrendVerdict.STABLE, (
        "another user's sets leaked into this user's trend (ASVS V4)"
    )
    assert trend.rate_percent_per_week == Decimal("0.00")
    assert trend.weeks_with_data == 4


@pytest.mark.integration
async def test_trend_freshness_names_both_resources(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """DQ-01: a stale template sync silently changes every verdict in the response.

    ``exercise_type`` is the D-03 e1RM gate and comes from the templates table, so PROG-02 is only
    as fresh as the STALER of its two sources. Written against the second user because
    ``sync_state`` rows for the default user are the Hevy sync suite's territory and the container
    is session-scoped and shared.
    """
    await golden_workout.user(user_id=ANALYTICS_SECOND_USER_ID)
    await golden_workout.template(external_id=_TREND, user_id=ANALYTICS_SECOND_USER_ID)
    await golden_workout.workout(
        start_time=_DAY_1,
        exercises=[
            _bench_exercise(
                GoldenSet(weight_kg=Decimal("100.000"), reps=5), template_external_id=_TREND
            )
        ],
        user_id=ANALYTICS_SECOND_USER_ID,
    )
    for resource, synced_at in (
        (RESOURCE_WORKOUTS, _SYNCED_WORKOUTS_AT),
        (RESOURCE_EXERCISE_TEMPLATES, _SYNCED_TEMPLATES_AT),
    ):
        await complete_sync(
            session,
            user_id=ANALYTICS_SECOND_USER_ID,
            provider=PROVIDER_HEVY,
            resource=resource,
            last_synced_at=synced_at,
        )

    result = await get_exercise_trends(
        session, user_id=ANALYTICS_SECOND_USER_ID, start_day=_START, end_day=_END
    )

    assert set(result.freshness.resources) == {RESOURCE_WORKOUTS, RESOURCE_EXERCISE_TEMPLATES}
    assert result.freshness.resources == {
        RESOURCE_WORKOUTS: _SYNCED_WORKOUTS_AT,
        RESOURCE_EXERCISE_TEMPLATES: _SYNCED_TEMPLATES_AT,
    }


# ---------------------------------------------------------------------------
# PROG-03's streak scan. NO integration marker, for `best_set_per_day`'s reason: D-06's two
# floors, D-07's tolerance band and D-07a's skip are business rules, and a business rule that
# needs Docker to be checked is a business rule nobody checks on the commit that breaks it.
# ---------------------------------------------------------------------------

# An arbitrary Monday well inside the 12-week lookback these tests never actually resolve --
# `scan_plateau` is pure and takes `as_of` from the caller, so no clock is involved here.
_SCAN_BASE = dt.date(2026, 6, 1)

# The historical ceiling every scan test seeds from, and the two probes either side of D-07's
# band. 100.000 x 1.02 = 102.000 exactly, so 101.500 is inside and 102.500 is outside with no
# rounding anywhere near the boundary.
_SCAN_CEILING = Decimal("100.000")
_INSIDE_TOLERANCE = Decimal("101.500")
_OUTSIDE_TOLERANCE = Decimal("102.500")

# Every flat session sits BELOW the ceiling, so a scan that ignored the seed entirely would still
# have to explain why the first one did not start a fresh streak.
_FLAT = Decimal("99.000")


def _scan_series(*, sessions: int, spacing_days: int, e1rm: Decimal = _FLAT) -> list[SessionBest]:
    """``sessions`` folded days, ``spacing_days`` apart, all at the same estimate.

    Ascending by ``local_day``, because ``scan_plateau`` documents that as a precondition its
    caller (``qualifying_set_rows``' SQL ordering) guarantees.
    """
    return [
        _session_best(
            local_day=_SCAN_BASE + dt.timedelta(days=spacing_days * index), best_e1rm_kg=e1rm
        )
        for index in range(sessions)
    ]


def test_both_d06_floors_are_required() -> None:
    """D-06 needs BOTH four qualifying sessions AND three elapsed weeks, not whichever fires.

    Three arrangements, each failing a different way. A suite carrying only the first would pass
    against a session-count-only implementation and against a calendar-only one alike.
    """
    spanning = scan_plateau(
        _scan_series(sessions=PLATEAU_MIN_QUALIFYING_SESSIONS, spacing_days=7),
        historical_best=_SCAN_CEILING,
        as_of=_SCAN_BASE + dt.timedelta(days=28),
    )

    assert spanning.plateaued is True
    assert spanning.qualifying_sessions == PLATEAU_MIN_QUALIFYING_SESSIONS
    assert spanning.confidence is PlateauConfidence.LOW
    assert spanning.streak_start == _SCAN_BASE

    # Four sessions, thirteen days. The session floor is satisfied and the calendar floor is not.
    cramped = scan_plateau(
        _scan_series(sessions=PLATEAU_MIN_QUALIFYING_SESSIONS, spacing_days=4),
        historical_best=_SCAN_CEILING,
        as_of=_SCAN_BASE + dt.timedelta(days=13),
    )

    assert cramped.qualifying_sessions == PLATEAU_MIN_QUALIFYING_SESSIONS
    assert cramped.plateaued is False, (
        "4 sessions of an exercise trained 3x/week is 9-13 days, inside the day-to-day "
        "fluctuation range blueprint 21 warns against"
    )

    # Three sessions, forty days. The calendar floor is satisfied and the session floor is not.
    thin = scan_plateau(
        _scan_series(sessions=PLATEAU_MIN_QUALIFYING_SESSIONS - 1, spacing_days=20),
        historical_best=_SCAN_CEILING,
        as_of=_SCAN_BASE + dt.timedelta(days=40),
    )

    assert thin.qualifying_sessions == PLATEAU_MIN_QUALIFYING_SESSIONS - 1
    assert thin.plateaued is False, (
        "three sessions spread over forty days clears the calendar floor and still is not four "
        "sessions; D-06 takes whichever demands MORE evidence"
    )
    assert thin.confidence is PlateauConfidence.LOW


def test_tolerance_band_both_sides() -> None:
    """D-07's 2% band, pinned on BOTH sides of the exact boundary.

    100.000 x 1.02 is exactly 102.000, so +1.5% must extend the streak and +2.5% must break it.
    A suite asserting only the breaking side passes against a bare ``>`` on the strict maximum.
    """
    assert PLATEAU_IMPROVEMENT_TOLERANCE == Decimal("0.02")

    inside = scan_plateau(
        [
            _session_best(local_day=_SCAN_BASE, best_e1rm_kg=_FLAT),
            _session_best(
                local_day=_SCAN_BASE + dt.timedelta(days=7), best_e1rm_kg=_INSIDE_TOLERANCE
            ),
        ],
        historical_best=_SCAN_CEILING,
        as_of=_SCAN_BASE + dt.timedelta(days=7),
    )

    assert inside.qualifying_sessions == 2
    assert inside.streak_start == _SCAN_BASE, (
        "a bare > against the strict max flags a lifter bouncing within 1% of their peak as "
        "'no progress'"
    )

    outside = scan_plateau(
        [
            _session_best(local_day=_SCAN_BASE, best_e1rm_kg=_FLAT),
            _session_best(
                local_day=_SCAN_BASE + dt.timedelta(days=7), best_e1rm_kg=_OUTSIDE_TOLERANCE
            ),
        ],
        historical_best=_SCAN_CEILING,
        as_of=_SCAN_BASE + dt.timedelta(days=7),
    )

    assert outside.qualifying_sessions == 1
    assert outside.streak_start == _SCAN_BASE + dt.timedelta(days=7), (
        "the breaking session is the most recent evidence of progress, so the clock restarts FROM "
        "it rather than from the session after it"
    )
    # The running best absorbs the break, so everything after it is measured against the new bar.
    assert outside.historical_best_kg == _OUTSIDE_TOLERANCE


def test_null_estimate_session_neither_extends_nor_breaks() -> None:
    """D-07a: a session with no trusted estimate is SKIPPED entirely.

    Without the skip a deload week inflates every streak by one session and the verdict flips
    from "not yet" to "plateaued" for an exercise that merely changed rep scheme -- 376 of 2,239
    live exercise-sessions (16.8%) have no qualifying set at all.
    """
    series = [
        _session_best(local_day=_SCAN_BASE, best_e1rm_kg=_FLAT),
        _session_best(local_day=_SCAN_BASE + dt.timedelta(days=7), best_e1rm_kg=None),
        _session_best(local_day=_SCAN_BASE + dt.timedelta(days=14), best_e1rm_kg=_FLAT),
        _session_best(local_day=_SCAN_BASE + dt.timedelta(days=21), best_e1rm_kg=_FLAT),
        _session_best(local_day=_SCAN_BASE + dt.timedelta(days=28), best_e1rm_kg=_FLAT),
    ]

    scan = scan_plateau(
        series, historical_best=_SCAN_CEILING, as_of=_SCAN_BASE + dt.timedelta(days=28)
    )

    assert scan.qualifying_sessions == PLATEAU_MIN_QUALIFYING_SESSIONS, (
        "the null-estimate session was counted; five folded days with four usable estimates is a "
        "streak of four"
    )
    assert scan.streak_start == _SCAN_BASE, (
        "the null-estimate session reset the streak; it must neither extend nor break"
    )
    assert scan.plateaued is True


def test_no_history_first_session_starts_rather_than_breaks() -> None:
    """With no seed, the first qualifying session STARTS the streak.

    An improvement over nothing is not an improvement. Treating a ``None`` seed as a zero ceiling
    would make every first in-window session a break, which is precisely the fake window-edge
    break the pre-lookback seed exists to prevent.
    """
    scan = scan_plateau(
        [_session_best(local_day=_SCAN_BASE, best_e1rm_kg=_SCAN_CEILING)],
        historical_best=None,
        as_of=_SCAN_BASE,
    )

    assert scan.qualifying_sessions == 1, "an improvement over nothing is not an improvement"
    assert scan.streak_start == _SCAN_BASE
    assert scan.historical_best_kg == _SCAN_CEILING
    assert scan.plateaued is False


def test_confidence_ladder() -> None:
    """D-07b's ladder, derived from D-06's floor rather than invented: 4-5 low, 6-9 mid, 10+ high.

    The three-session case is the one that matters most: below D-06's floor the verdict is not a
    plateau at all, so a HIGH-confidence non-plateau must be unreachable.
    """
    ladder = {
        3: PlateauConfidence.LOW,
        4: PlateauConfidence.LOW,
        6: PlateauConfidence.MEDIUM,
        10: PlateauConfidence.HIGH,
    }

    for sessions, confidence in ladder.items():
        scan = scan_plateau(
            _scan_series(sessions=sessions, spacing_days=7),
            historical_best=_SCAN_CEILING,
            # Always at least PLATEAU_MIN_ELAPSED_DAYS past the streak start, so the calendar
            # floor never confounds the session-count ladder this test is about.
            as_of=_SCAN_BASE + dt.timedelta(days=7 * sessions + PLATEAU_MIN_ELAPSED_DAYS),
        )

        assert scan.qualifying_sessions == sessions
        assert scan.confidence is confidence, (
            f"{sessions} qualifying sessions must read as {confidence.value}"
        )
        assert scan.plateaued is (sessions >= PLATEAU_MIN_QUALIFYING_SESSIONS)


def test_recent_performance_and_historical_best_are_both_reported() -> None:
    """D-07b: the PAIR of numbers, because a plateau and a DETRAINED exercise look identical alone.

    On the live account Leg Extension's recent performance is 68.2% of its historical best. "No
    new PR" is true both for someone grinding at 99% of their ceiling and for someone who deloaded
    to 68% of it, and only the pair distinguishes them.
    """
    scan = scan_plateau(
        _scan_series(sessions=4, spacing_days=7, e1rm=Decimal("68.000")),
        historical_best=_SCAN_CEILING,
        as_of=_SCAN_BASE + dt.timedelta(days=28),
    )

    assert scan.recent_performance_kg == Decimal("68.000")
    assert scan.historical_best_kg == _SCAN_CEILING
    assert scan.recent_performance_kg is not None
    assert scan.historical_best_kg is not None
    assert scan.recent_performance_kg / scan.historical_best_kg < Decimal("0.85"), (
        "a lifter at 68% of their all-time best is DETRAINED, not plateaued, and only the pair of "
        "numbers makes the two distinguishable"
    )


def test_duration_is_measured_to_as_of_not_the_last_session() -> None:
    """The clock runs to ``as_of``, never to the last session in the streak.

    "You have not PR'd in 40 days" is the useful sentence; "your streak spanned 26 days" is not.
    Four sessions two days apart span six days -- below the calendar floor -- yet twenty days
    later the same streak has been running long enough to count.
    """
    series = _scan_series(sessions=PLATEAU_MIN_QUALIFYING_SESSIONS, spacing_days=2)

    at_the_last_session = scan_plateau(
        series, historical_best=_SCAN_CEILING, as_of=_SCAN_BASE + dt.timedelta(days=6)
    )
    twenty_days_later = scan_plateau(
        series, historical_best=_SCAN_CEILING, as_of=_SCAN_BASE + dt.timedelta(days=26)
    )

    assert at_the_last_session.streak_start == twenty_days_later.streak_start == _SCAN_BASE
    assert at_the_last_session.plateaued is False
    assert twenty_days_later.plateaued is True, (
        "the elapsed span was measured to the last session instead of to as_of; the streak has "
        "not been broken in the twenty days since"
    )


# ---------------------------------------------------------------------------
# PROG-03's public function. Container-backed, and every one of these freezes the clock:
# `get_plateaus` anchors its window on the user's local TODAY, so an unfrozen test rots within
# days and the failure reads as an algorithm bug rather than as a stale fixture.
# ---------------------------------------------------------------------------


async def _seed_plateau_sessions(
    golden_workout: GoldenBuilder,
    *,
    sessions: Sequence[tuple[dt.datetime, Decimal]],
    template_external_id: str = _PLATEAU,
    reps: int = 5,
    user_id: uuid.UUID = DEFAULT_USER_ID,
) -> None:
    """One workout per ``(instant, weight)`` pair, one working set each.

    Five reps throughout, so every set clears D-02's rep gate and the only thing that varies
    between fixtures is the load -- and therefore the estimate the streak is scanned over.
    """
    for start_time, weight in sessions:
        await golden_workout.workout(
            start_time=start_time,
            exercises=[
                _bench_exercise(
                    GoldenSet(weight_kg=weight, reps=reps),
                    template_external_id=template_external_id,
                )
            ],
            user_id=user_id,
        )


def _flat_weeks(weight: str) -> list[tuple[dt.datetime, Decimal]]:
    """The four in-window weekly sessions, all at one load -- the plateau shape itself."""
    return [(week, Decimal(weight)) for week in _PLATEAU_WEEKS]


@pytest.mark.integration
@time_machine.travel(_PLATEAU_NOW, tick=False)
async def test_plateaued_exercise_reports_window_and_threshold(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """PROG-03's requirement text: the window and the threshold come back WITH the result.

    Four weekly sessions at 100 kg x 5 (e1RM 116.667) under a 105 kg x 5 ceiling (122.500) set
    before the lookback. All five echoed fields are asserted, because a verdict whose window and
    tolerance are not on the response is a number Claude cannot qualify.
    """
    await golden_workout.template(external_id=_PLATEAU, title="Plateau Press")
    await _seed_plateau_sessions(
        golden_workout,
        sessions=[(_PRE_LOOKBACK, Decimal("105.000")), *_flat_weeks("100.000")],
    )

    result = await get_plateaus(session, user_id=DEFAULT_USER_ID)

    assert result.lookback_weeks == DEFAULT_PLATEAU_LOOKBACK_WEEKS == 12
    assert (result.lookback_start, result.lookback_end) == (_PLATEAU_START_12W, _PLATEAU_END)
    assert len(result.exercises) == 1

    row = result.exercises[0]
    assert row.exercise_template_external_id == _PLATEAU
    assert row.title == "Plateau Press"
    assert row.plateaued is True
    assert row.qualifying_sessions_in_streak == 4
    assert row.plateau_duration_days == _PLATEAU_DURATION_DAYS
    assert row.confidence is PlateauConfidence.LOW
    assert row.recent_performance_kg == Decimal("116.667")
    assert row.historical_best_kg == Decimal("122.500"), (
        "the pre-lookback 105 kg session is the ceiling this streak has not beaten; a "
        "window-scoped maximum reports 116.667 and makes a detrained exercise look like one "
        "sitting at its peak"
    )
    # The five echoed fields, asserted as literals rather than against the constants they came
    # from -- a wrong constant would otherwise agree with itself.
    assert row.threshold_percent == Decimal("2.00")
    assert row.min_sessions == 4
    assert row.min_elapsed_days == 21
    assert (row.lookback_start, row.lookback_end) == (_PLATEAU_START_12W, _PLATEAU_END)


@pytest.mark.integration
@time_machine.travel(_PLATEAU_NOW, tick=False)
async def test_historical_best_is_seeded_from_before_the_lookback(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """THE load-bearing PROG-03 test: widening the lookback must not move the streak start.

    The in-window loads ESCALATE -- 90, 95, 96, 97 kg, i.e. 105.000, 110.833, 112.000, 113.167 --
    so the second session beats the first by more than 2%. Seeded from the 120 kg session that
    predates BOTH lookbacks (140.000), nothing in the window comes close to breaking and the
    streak runs the full four sessions. Seeded from None, the first session sets the bar at
    105.000 and the second manufactures a break at the window edge, leaving a three-session
    streak twenty days long -- below D-06's calendar floor, so ``plateau_duration_days`` collapses
    to ``None``. A flat fixture cannot tell the two apart.

    The pre-lookback session sits before the 24-week start as well, so widening the window adds
    no new sessions and the two answers must agree exactly.
    """
    await golden_workout.template(external_id=_PLATEAU, title="Plateau Press")
    await _seed_plateau_sessions(
        golden_workout,
        sessions=[
            (_PRE_LOOKBACK, Decimal("120.000")),
            (_DAY_1, Decimal("90.000")),
            (_DAY_2, Decimal("95.000")),
            (_DAY_3, Decimal("96.000")),
            (_DAY_4, Decimal("97.000")),
        ],
    )

    narrow = await get_plateaus(session, user_id=DEFAULT_USER_ID, lookback_weeks=12)
    wide = await get_plateaus(session, user_id=DEFAULT_USER_ID, lookback_weeks=24)

    assert narrow.lookback_start == _PLATEAU_START_12W
    assert wide.lookback_start == _PLATEAU_START_24W
    narrow_row, wide_row = narrow.exercises[0], wide.exercises[0]

    assert narrow_row.plateau_duration_days == _PLATEAU_DURATION_DAYS, (
        "the streak start moved when the lookback widened but the training did not change -- the "
        "running best was seeded from None"
    )
    assert wide_row.plateau_duration_days == narrow_row.plateau_duration_days
    assert wide_row.qualifying_sessions_in_streak == narrow_row.qualifying_sessions_in_streak == 4
    assert wide_row.historical_best_kg == narrow_row.historical_best_kg == Decimal("140.000")
    # 105.000 + 110.833 + 112.000 + 113.167 = 441.000, over four sessions.
    assert narrow_row.recent_performance_kg == Decimal("110.250")


@pytest.mark.integration
@time_machine.travel(_PLATEAU_NOW, tick=False)
async def test_abandoned_exercise_is_not_reported(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """D-19's bound: only templates trained INSIDE the lookback are reported.

    The abandoned template's only session predates the window by nearly six months and it holds
    the account's heaviest load, so an unbounded scan would rank it as the most severe plateau in
    the response.
    """
    await golden_workout.template(external_id=_PLATEAU, title="Plateau Press")
    await golden_workout.template(external_id=_ABANDONED, title="Abandoned Pushdown")
    await _seed_plateau_sessions(golden_workout, sessions=_flat_weeks("100.000"))
    await _seed_plateau_sessions(
        golden_workout,
        sessions=[(_PRE_LOOKBACK, Decimal("140.000"))],
        template_external_id=_ABANDONED,
    )

    result = await get_plateaus(session, user_id=DEFAULT_USER_ID)

    reported = [row.exercise_template_external_id for row in result.exercises]
    assert _ABANDONED not in reported, (
        "unbounded, the scan reports 'plateaued 402 days' for an exercise last trained three "
        "months ago -- literally true and useless as coaching"
    )
    # Guard against a vacuous pass: the in-window template really is reported.
    assert reported == [_PLATEAU]


@pytest.mark.integration
@time_machine.travel(_PLATEAU_NOW, tick=False)
async def test_a_recent_pr_clears_the_plateau(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """A session past the tolerance band restarts the clock FROM itself.

    Four flat sessions at 116.667 set the bar; 103 kg x 5 is 120.167, which clears
    116.667 x 1.02 = 119.000. The streak collapses to that one session, so the exercise is no
    longer plateaued at all.
    """
    await golden_workout.template(external_id=_PLATEAU, title="Plateau Press")
    await _seed_plateau_sessions(
        golden_workout,
        sessions=[*_flat_weeks("100.000"), (_PR_DAY, Decimal("103.000"))],
    )

    result = await get_plateaus(session, user_id=DEFAULT_USER_ID)

    row = result.exercises[0]
    assert row.plateaued is False
    assert row.qualifying_sessions_in_streak == 1, (
        "the PR did not restart the streak; a session above the 2% band is the most recent "
        "evidence of progress and the clock runs from it"
    )
    assert row.plateau_duration_days is None
    assert row.historical_best_kg == Decimal("120.167")
    assert row.recent_performance_kg == Decimal("120.167")


@pytest.mark.integration
@time_machine.travel(_PLATEAU_NOW, tick=False)
async def test_not_plateaued_reports_null_duration(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """``None``, never ``0``: "we did not call this a plateau" is not "it has lasted zero days".

    Two exercises in one response so the invariant is checked on both sides at once, and so the
    stated sort order is pinned by ids whose alphabetical order differs from their insertion
    order.
    """
    await golden_workout.template(external_id=_TREND, title="Two Session Press")
    await golden_workout.template(external_id=_PLATEAU, title="Plateau Press")
    await _seed_plateau_sessions(golden_workout, sessions=_flat_weeks("100.000"))
    await _seed_plateau_sessions(
        golden_workout,
        sessions=[(_DAY_1, Decimal("80.000")), (_DAY_2, Decimal("80.000"))],
        template_external_id=_TREND,
    )

    result = await get_plateaus(session, user_id=DEFAULT_USER_ID)

    reported = [row.exercise_template_external_id for row in result.exercises]
    assert reported == [_PLATEAU, _TREND], (
        "the response fell through to dict-iteration order; Phase 6 will diff these between runs"
    )
    by_id = {row.exercise_template_external_id: row for row in result.exercises}

    assert by_id[_PLATEAU].plateaued is True
    assert by_id[_PLATEAU].plateau_duration_days == _PLATEAU_DURATION_DAYS
    assert by_id[_TREND].plateaued is False
    assert by_id[_TREND].qualifying_sessions_in_streak == 2

    for row in result.exercises:
        assert (row.plateau_duration_days is None) is (not row.plateaued), (
            "a duration of 0 for a non-plateaued exercise reads as 'plateaued since today'"
        )


@pytest.mark.integration
@time_machine.travel(_PLATEAU_NOW, tick=False)
async def test_an_oversized_lookback_is_clamped_rather_than_rejected(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """T-05-66: a lookback past the five-year cap ANSWERS, and reads at most five years.

    400 weeks is a 2,800-day window and ``build_window`` refuses anything above
    ``MAX_ANALYTICS_WINDOW_DAYS``. Without the explicit clamp on the fetch start this call raises
    "requested analytics window exceeds the maximum span" -- a plateau question turned into an
    error by a number the caller was allowed to pass. Clamping loses only history older than five
    years, which cannot be anyone's current ceiling.

    The echoed ``lookback_start`` is deliberately the UNCLAMPED window the caller asked about: the
    clamp bounds what is READ, not what was requested, and a silently narrowed echo would make the
    response claim a window it never evaluated.
    """
    await golden_workout.template(external_id=_PLATEAU, title="Plateau Press")
    await _seed_plateau_sessions(
        golden_workout,
        sessions=[(_PRE_LOOKBACK, Decimal("105.000")), *_flat_weeks("100.000")],
    )

    result = await get_plateaus(session, user_id=DEFAULT_USER_ID, lookback_weeks=400)

    assert result.lookback_weeks == 400
    assert result.lookback_start == dt.date(2018, 12, 31)
    assert result.lookback_end == _PLATEAU_END
    # Every session now falls INSIDE the lookback, so nothing seeds the running best and the
    # 105 kg session starts the streak rather than sitting above it.
    row = result.exercises[0]
    assert row.qualifying_sessions_in_streak == 5
    assert row.historical_best_kg == Decimal("122.500")
    # The clamped fetch still reaches back past every fixture workout, so the coverage count is
    # the whole account rather than a window the clamp silently truncated.
    assert result.coverage.sessions_in_window == 5


@pytest.mark.integration
@time_machine.travel(_PLATEAU_NOW, tick=False)
async def test_lookback_weeks_must_be_positive(session: AsyncSession) -> None:
    """T-05-67 / T-05-68: a caller bug RAISES, and the message carries no value.

    A zero-week window would return an empty ``exercises`` list, which reads as "nothing is
    plateaued" rather than as a bug. The message is asserted digit-free because it will be logged
    (FOUND-05) -- no lookback value, no date, no weight and no user id may reach a log line.
    """
    for weeks in (0, -1):
        with pytest.raises(ValueError) as excinfo:
            await get_plateaus(session, user_id=DEFAULT_USER_ID, lookback_weeks=weeks)

        message = str(excinfo.value)
        assert message == "lookback_weeks must be positive"
        assert not any(char.isdigit() for char in message), (
            "the rejected value was interpolated into a message that will be logged"
        )


@pytest.mark.integration
@time_machine.travel(_PLATEAU_NOW, tick=False)
async def test_second_users_sessions_do_not_break_a_streak(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """ASVS V4 / T-05-69: a leaked set does not add a row here, it CLEARS a plateau.

    Both users train the SAME external id -- Hevy's built-in template ids are global. This user is
    flat at 100 kg for four weeks; the other hits 200 kg x 5 (233.333) on the last of them. A
    missing tenant predicate folds both into one (template, local day) entry, the day's best
    becomes 233.333, and the streak breaks on its final session -- a wrong coaching verdict rather
    than merely an extra row.
    """
    await golden_workout.user(user_id=ANALYTICS_SECOND_USER_ID)
    await golden_workout.template(external_id=_SHARED, title="Mine")
    await golden_workout.template(
        external_id=_SHARED, title="Theirs", user_id=ANALYTICS_SECOND_USER_ID
    )
    await _seed_plateau_sessions(
        golden_workout, sessions=_flat_weeks("100.000"), template_external_id=_SHARED
    )
    await _seed_plateau_sessions(
        golden_workout,
        sessions=[(_DAY_4, Decimal("200.000"))],
        template_external_id=_SHARED,
        user_id=ANALYTICS_SECOND_USER_ID,
    )

    result = await get_plateaus(session, user_id=DEFAULT_USER_ID)

    # Guard against a vacuous pass: this user really did train, and the row is theirs.
    assert len(result.exercises) == 1
    row = result.exercises[0]
    assert row.title == "Mine"
    assert row.plateaued is True, "another user's PR broke this user's streak (ASVS V4)"
    assert row.qualifying_sessions_in_streak == 4
    assert row.historical_best_kg == Decimal("116.667")


@pytest.mark.integration
@time_machine.travel(_PLATEAU_NOW, tick=False)
async def test_plateau_freshness_names_both_resources(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """DQ-01: a stale template sync silently changes every streak in the response.

    ``exercise_type`` is the D-03 e1RM gate and comes from the templates table. Written against
    the second user because ``sync_state`` rows for the default user are the Hevy sync suite's
    territory and the container is session-scoped and shared.
    """
    await golden_workout.user(user_id=ANALYTICS_SECOND_USER_ID)
    await golden_workout.template(external_id=_PLATEAU, user_id=ANALYTICS_SECOND_USER_ID)
    await _seed_plateau_sessions(
        golden_workout,
        sessions=[(_DAY_1, Decimal("100.000"))],
        user_id=ANALYTICS_SECOND_USER_ID,
    )
    for resource, synced_at in (
        (RESOURCE_WORKOUTS, _SYNCED_WORKOUTS_AT),
        (RESOURCE_EXERCISE_TEMPLATES, _SYNCED_TEMPLATES_AT),
    ):
        await complete_sync(
            session,
            user_id=ANALYTICS_SECOND_USER_ID,
            provider=PROVIDER_HEVY,
            resource=resource,
            last_synced_at=synced_at,
        )

    result = await get_plateaus(session, user_id=ANALYTICS_SECOND_USER_ID)

    assert set(result.freshness.resources) == {RESOURCE_WORKOUTS, RESOURCE_EXERCISE_TEMPLATES}
    assert result.freshness.resources == {
        RESOURCE_WORKOUTS: _SYNCED_WORKOUTS_AT,
        RESOURCE_EXERCISE_TEMPLATES: _SYNCED_TEMPLATES_AT,
    }
    assert result.coverage.sessions_in_window == 1
