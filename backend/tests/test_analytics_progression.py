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
"""

import datetime as dt
import uuid
from decimal import Decimal

from app.analytics.estimates import NoEstimateReason
from app.analytics.progression import best_set_per_day
from app.analytics.rollup import QualifyingSetRow

# `PROG-*` so these cannot collide with `test_analytics_volume.py`'s `VOL-*`,
# `test_analytics_frequency.py`'s `FREQ-*`, `test_analytics_rollup.py`'s `ROLLUP-*`/`QSR-*`,
# `test_normalization_mapping.py`'s `RESOLVER-*` or the sync suite's `hevy-*`: the container is
# session-scoped and shared.
_BENCH = "PROG-bench"
_PULLUP = "PROG-pullup"
_HIGH_REP = "PROG-highrep"
_UNSYNCED = "PROG-never-synced"
_SHARED = "PROG-shared"

# Asia/Jakarta is UTC+7, so 02:00Z is 09:00 local on the SAME day -- comfortably inside the local
# day each constant is named for and never at risk of sliding into its neighbour.
_START = dt.date(2026, 8, 3)
_END = dt.date(2026, 8, 30)
_DAY_1 = dt.datetime(2026, 8, 3, 2, 0, tzinfo=dt.UTC)
_DAY_2 = dt.datetime(2026, 8, 10, 2, 0, tzinfo=dt.UTC)
_DAY_3 = dt.datetime(2026, 8, 17, 2, 0, tzinfo=dt.UTC)

# The local days those three instants belong to, spelled out rather than derived: deriving them
# with the same timezone arithmetic the code under test uses would make a wrong conversion agree
# with itself.
_LOCAL_DAY_1 = dt.date(2026, 8, 3)
_LOCAL_DAY_2 = dt.date(2026, 8, 10)
_LOCAL_DAY_3 = dt.date(2026, 8, 17)

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
