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

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.estimates import NoEstimateReason
from app.analytics.progression import best_set_per_day, get_exercise_progression
from app.analytics.rollup import QualifyingSetRow
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

# Asia/Jakarta is UTC+7, so 02:00Z is 09:00 local on the SAME day -- comfortably inside the local
# day each constant is named for and never at risk of sliding into its neighbour.
_START = dt.date(2026, 8, 3)
_END = dt.date(2026, 8, 30)
_DAY_1 = dt.datetime(2026, 8, 3, 2, 0, tzinfo=dt.UTC)
_DAY_2 = dt.datetime(2026, 8, 10, 2, 0, tzinfo=dt.UTC)
_DAY_3 = dt.datetime(2026, 8, 17, 2, 0, tzinfo=dt.UTC)

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
