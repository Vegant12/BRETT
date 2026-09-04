"""PROG-04: personal records at SET grain (D-08, D-09).

THE load-bearing test is `test_rep_pr_is_not_capped_by_the_e1rm_rep_gate`. The specific wrong
number it catches is 12: an implementation that reuses D-02's rep gate for the rep PR reports the
best set at 12 reps and silently hides every set above it -- on live data that is 320 sets at
exactly 20 reps and 879 at 15. D-02 gates the ESTIMATE, never the observation.

Its partner is `test_dropset_sets_a_record_and_warmup_does_not`: without it, an implementation
that filtered to `set_type == 'normal'` would still pass every value assertion above while
dropping 823 live dropset sets -- 12% of all hard sets -- from every record.

No tolerance-based comparison appears below -- not `approx`, not rounding. Every expected figure
is an exact `Decimal` computed by hand, and a tolerance would quietly accept the integer-division
e1RM defect (`estimates.py`'s first warning), whose wrong answer is the bare weight lifted: a
number of the right magnitude, in the right units, that every downstream `>` still works on.
"""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.records import get_personal_records, get_recent_records
from app.analytics.schemas import (
    PersonalRecord,
    PersonalRecordsResult,
    PersonalRecordType,
    RecentRecord,
    RecentRecordsResult,
)
from app.db.repositories.sync_state import (
    RESOURCE_EXERCISE_TEMPLATES,
    RESOURCE_WORKOUTS,
)
from tests.conftest import (
    ANALYTICS_SECOND_USER_ID,
    DEFAULT_USER_ID,
    GoldenBuilder,
    GoldenExercise,
    GoldenSet,
)

# `PR-*` so these cannot collide with `test_analytics_frequency.py`'s `FREQ-*`,
# `test_analytics_volume.py`'s `VOL-*`, `test_analytics_rollup.py`'s `ROLLUP-*` or
# `test_normalization_mapping.py`'s `RESOLVER-*`: the container is session-scoped and shared.
_BENCH = "PR-bench"
_PULLUP = "PR-pullup"
_SHARED = "PR-shared"

# A whole calendar month, deliberately NOT a multiple of 7 and deliberately not starting on a
# Monday: `window_start`/`window_end` are asserted back verbatim in
# `test_records_and_freshness_shape`, which is what proves no week snapping happened.
_START = dt.date(2026, 8, 1)
_END = dt.date(2026, 8, 31)

# Jakarta is UTC+7, so 02:00Z is 09:00 local on the same day -- comfortably inside the local day
# each constant is named for, and never at risk of sliding into its neighbour.
_EARLY = dt.datetime(2026, 8, 3, 2, 0, tzinfo=dt.UTC)  # local 2026-08-03
_LATE = dt.datetime(2026, 8, 17, 2, 0, tzinfo=dt.UTC)  # local 2026-08-17
_EARLY_DAY = dt.date(2026, 8, 3)
_LATE_DAY = dt.date(2026, 8, 17)

# The hand-computed fixture every value assertion in this module is derived from:
#
#   100.000 x 3   -> e1RM 110.000, volume   300.000
#    80.000 x 12  -> e1RM 112.000, volume   960.000   <- the estimated-1RM record
#    40.000 x 22  -> e1RM   none  (D-02),   volume 880.000   <- the rep record
#                                   session volume 2140.000 over 3 sets
#
# The 22-rep set is the whole point of the arrangement: it holds the rep PR while being
# INELIGIBLE for the estimate, so the two rules cannot be satisfied by one gate.
_MIXED_SETS = (
    GoldenSet(weight_kg=Decimal("100.000"), reps=3),
    GoldenSet(weight_kg=Decimal("80.000"), reps=12),
    GoldenSet(weight_kg=Decimal("40.000"), reps=22),
)


def _by_type(result: PersonalRecordsResult) -> dict[PersonalRecordType, PersonalRecord]:
    """Index the records by type so ABSENCE is assertable with `not in`.

    PROG-04's absent-not-zero rule is only testable against a mapping: `next(r for r in ...)`
    raises `StopIteration` on a missing type, which reads as an error rather than as the fact
    under test.
    """
    return {record.record_type: record for record in result.records}


async def _records(session: AsyncSession, template_external_id: str) -> PersonalRecordsResult:
    """The default user's records for one exercise over the whole fixture month."""
    return await get_personal_records(
        session,
        user_id=DEFAULT_USER_ID,
        exercise_template_external_id=template_external_id,
        start_day=_START,
        end_day=_END,
    )


@pytest.mark.integration
async def test_all_five_record_types_are_detected(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """One workout, three sets, and every PROG-04 figure pinned to an exact Decimal.

    The four scalar records and the per-weight list are asserted from the SAME fixture on
    purpose: they are five different questions about one set of rows, and an implementation that
    computed any one of them from a pre-collapsed per-day value would disagree with the others
    here rather than in some later phase.
    """
    await golden_workout.template(external_id=_BENCH)
    await golden_workout.workout(
        start_time=_EARLY,
        exercises=[GoldenExercise(template_external_id=_BENCH, sets=_MIXED_SETS)],
    )

    result = await _records(session, _BENCH)
    records = _by_type(result)

    assert records[PersonalRecordType.MAX_WEIGHT].value == Decimal("100.000")
    assert records[PersonalRecordType.MAX_WEIGHT].reps == 3
    assert records[PersonalRecordType.MAX_REPS].value == Decimal(22)
    assert records[PersonalRecordType.MAX_REPS].weight_kg == Decimal("40.000")
    assert records[PersonalRecordType.ESTIMATED_1RM].value == Decimal("112.000"), (
        "expected 80 x 12 = 112.000; got 110.000, which is the 3-rep set -- the 22-rep set must "
        "fail D-02, not win it"
    )
    assert records[PersonalRecordType.SESSION_VOLUME].value == Decimal("2140.000")
    assert records[PersonalRecordType.SESSION_VOLUME].volume_sets == 3
    assert records[PersonalRecordType.SESSION_VOLUME].achieved_on == _EARLY_DAY

    assert [row.weight_kg for row in result.reps_at_weight] == [
        Decimal("100.000"),
        Decimal("80.000"),
        Decimal("40.000"),
    ]


@pytest.mark.integration
async def test_rep_pr_is_not_capped_by_the_e1rm_rep_gate(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """THE load-bearing test. The wrong number it catches is 12.

    D-02's trusted rep range exists so an Epley estimate is not extrapolated past the point
    fatigue stops being proportional to load. Reusing it as a filter on the rep PR reports the
    12-rep set as the rep record and silently hides 320 live sets at exactly 20 reps and 879 at
    15 -- and the rep PR is precisely the record that lives above the cap.
    """
    await golden_workout.template(external_id=_BENCH)
    await golden_workout.workout(
        start_time=_EARLY,
        exercises=[GoldenExercise(template_external_id=_BENCH, sets=_MIXED_SETS)],
    )

    result = await _records(session, _BENCH)
    rep_pr = _by_type(result)[PersonalRecordType.MAX_REPS]

    assert rep_pr.reps == 22, (
        "the rep PR was capped at D-02's trusted rep range. That gate bounds the ESTIMATE, never "
        "the observation -- reporting 12 here hides every set above it, which on live data is "
        "320 sets at 20 reps and 879 at 15"
    )
    assert rep_pr.value == Decimal(22)
    # The per-weight list must not be capped either: 22 reps at 40 kg is a real row.
    assert max(row.reps for row in result.reps_at_weight) == 22


@pytest.mark.integration
async def test_dropset_sets_a_record_and_warmup_does_not(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """D-08: only `warmup` is excluded. `dropset` and `failure` set records like any other set.

    The 200 kg warm-up is heavier than everything else in the fixture, so an implementation that
    lost the warm-up exclusion fails loudly here. The dropset is the partner half: filtering to
    `normal` instead would report no record at all in the first phase, and it would drop 823 live
    sets -- 12% of all hard sets -- from every record in production.

    The second phase adds a `failure` set, which the provider has never actually sent. It is
    declared in `workout.py` and therefore WILL arrive one day, and an allow-list would start
    discarding it silently on that day.
    """
    await golden_workout.template(external_id=_BENCH)
    await golden_workout.workout(
        start_time=_EARLY,
        exercises=[
            GoldenExercise(
                template_external_id=_BENCH,
                sets=(
                    GoldenSet(set_type="warmup", weight_kg=Decimal("200.000"), reps=1),
                    GoldenSet(set_type="dropset", weight_kg=Decimal("110.000"), reps=5),
                ),
            )
        ],
    )

    dropset_only = await _records(session, _BENCH)

    assert dropset_only.records, (
        "no record at all: the dropset was filtered out. D-08 makes `dropset` eligible for every "
        "record type -- an allow-list of `normal` drops 823 live sets"
    )
    assert _by_type(dropset_only)[PersonalRecordType.MAX_WEIGHT].value == Decimal("110.000")
    assert all(record.value != Decimal("200.000") for record in dropset_only.records), (
        "a 200 kg warm-up set a record. Warm-ups are excluded once, in SQL, and must never reach "
        "the record scan at all"
    )
    assert all(row.weight_kg != Decimal("200.000") for row in dropset_only.reps_at_weight)

    await golden_workout.workout(
        start_time=_LATE,
        exercises=[
            GoldenExercise(
                template_external_id=_BENCH,
                sets=(GoldenSet(set_type="failure", weight_kg=Decimal("115.000"), reps=5),),
            )
        ],
    )

    with_failure = await _records(session, _BENCH)

    assert _by_type(with_failure)[PersonalRecordType.MAX_WEIGHT].value == Decimal("115.000"), (
        "a `failure` set did not set the max-weight record. A to-failure set is a real, hard "
        "effort -- D-08 makes it eligible for every record type"
    )
    assert _by_type(with_failure)[PersonalRecordType.MAX_WEIGHT].achieved_on == _LATE_DAY


@pytest.mark.integration
async def test_tie_records_the_earliest_date(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """D-09: the identical set performed twice reports the FIRST date, not the most recent.

    Both dates are in the window and both sets are identical, so the value assertions pass under
    either rule -- only the date distinguishes them. That is exactly why the wrong rule survives
    review: "you hit 100 kg on the 17th" reads as ordinary history.
    """
    await golden_workout.template(external_id=_BENCH)
    repeated = (GoldenSet(weight_kg=Decimal("100.000"), reps=3),)
    for start_time in (_EARLY, _LATE):
        await golden_workout.workout(
            start_time=start_time,
            exercises=[GoldenExercise(template_external_id=_BENCH, sets=repeated)],
        )

    result = await _records(session, _BENCH)
    records = _by_type(result)

    assert records[PersonalRecordType.MAX_WEIGHT].value == Decimal("100.000")
    assert records[PersonalRecordType.MAX_WEIGHT].achieved_on == _EARLY_DAY, (
        "D-09: 'when did I first hit this', not 'when did I most recently reconfirm it'"
    )
    assert records[PersonalRecordType.MAX_REPS].achieved_on == _EARLY_DAY
    assert records[PersonalRecordType.ESTIMATED_1RM].achieved_on == _EARLY_DAY

    # The same rule, at the per-weight grain: a second copy of the tie-break is how these two
    # would eventually disagree about the same set.
    assert len(result.reps_at_weight) == 1
    assert result.reps_at_weight[0].achieved_on == _EARLY_DAY


@pytest.mark.integration
async def test_reps_at_weight_is_one_row_per_distinct_weight(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """One row per WEIGHT, carrying the best rep count at it -- not one row per set.

    The three 80 kg sets are written 8 / 12 / 10, so neither "keep the first" nor "keep the last"
    produces 12. The list is descending by weight because a coach reads the heaviest first.
    """
    await golden_workout.template(external_id=_BENCH)
    await golden_workout.workout(
        start_time=_EARLY,
        exercises=[
            GoldenExercise(
                template_external_id=_BENCH,
                sets=(
                    GoldenSet(weight_kg=Decimal("80.000"), reps=8),
                    GoldenSet(weight_kg=Decimal("80.000"), reps=12),
                    GoldenSet(weight_kg=Decimal("80.000"), reps=10),
                    GoldenSet(weight_kg=Decimal("100.000"), reps=3),
                ),
            )
        ],
    )

    result = await _records(session, _BENCH)

    assert len(result.reps_at_weight) == 2, (
        "reps_at_weight emitted one row per SET rather than per distinct weight"
    )
    by_weight = {row.weight_kg: row.reps for row in result.reps_at_weight}
    assert by_weight[Decimal("80.000")] == 12
    assert by_weight[Decimal("100.000")] == 3
    weights = [row.weight_kg for row in result.reps_at_weight]
    assert weights == sorted(weights, reverse=True)
    assert weights == [Decimal("100.000"), Decimal("80.000")]


@pytest.mark.integration
async def test_reps_only_exercise_omits_weight_based_records(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """An absent record type is ABSENT. A pull-up has no max weight, and zero is not the answer.

    `reps_only` fails D-03's exact-match modality gate, so the estimate is ineligible too. Three
    of the four record types therefore have no eligible set, and the fourth -- the rep PR -- is
    the only honest thing this exercise can report.
    """
    await golden_workout.template(external_id=_PULLUP, exercise_type="reps_only")
    await golden_workout.workout(
        start_time=_EARLY,
        exercises=[
            GoldenExercise(
                template_external_id=_PULLUP,
                sets=(GoldenSet(reps=15), GoldenSet(reps=20)),
            )
        ],
    )

    result = await _records(session, _PULLUP)
    records = _by_type(result)

    assert records[PersonalRecordType.MAX_REPS].value == Decimal(20)
    assert records[PersonalRecordType.MAX_REPS].weight_kg is None
    for absent in (
        PersonalRecordType.MAX_WEIGHT,
        PersonalRecordType.ESTIMATED_1RM,
        PersonalRecordType.SESSION_VOLUME,
    ):
        assert absent not in records, (
            f"an absent record type must not be reported as a zero-value record: {absent.value}"
        )
    assert result.reps_at_weight == []


@pytest.mark.integration
async def test_session_volume_is_per_workout_not_per_window(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """The volume record is one EXERCISE-SESSION, never the window's total.

    Summed across the window this fixture reads 1600.000, which is a plausible number for a
    plausible-sounding question -- and it answers "how much did I move this month", not "what was
    my best session". The two workouts are deliberately different sizes so the two readings
    cannot coincide.
    """
    await golden_workout.template(external_id=_BENCH)
    await golden_workout.workout(
        start_time=_EARLY,
        exercises=[
            GoldenExercise(
                template_external_id=_BENCH,
                sets=(
                    GoldenSet(weight_kg=Decimal("100.000"), reps=5),
                    GoldenSet(weight_kg=Decimal("100.000"), reps=5),
                ),
            )
        ],
    )
    await golden_workout.workout(
        start_time=_LATE,
        exercises=[
            GoldenExercise(
                template_external_id=_BENCH,
                sets=(GoldenSet(weight_kg=Decimal("100.000"), reps=6),),
            )
        ],
    )

    volume = _by_type(await _records(session, _BENCH))[PersonalRecordType.SESSION_VOLUME]

    assert volume.value == Decimal("1000.000"), (
        "session volume was summed across the whole window instead of per exercise-session"
    )
    assert volume.achieved_on == _EARLY_DAY
    assert volume.volume_sets == 2


@pytest.mark.integration
async def test_second_users_sets_are_invisible(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """ASVS V4: a single-user suite cannot see a missing tenant predicate.

    Both users get a template under the SAME external id, because Hevy's built-in template ids
    are GLOBAL -- an unscoped join attaches the other user's `exercise_type` to this user's set,
    which changes the D-03 estimate gate as well as leaking a title.
    """
    await golden_workout.user(user_id=ANALYTICS_SECOND_USER_ID)
    await golden_workout.template(external_id=_SHARED, title="Mine")
    await golden_workout.template(
        external_id=_SHARED, title="Theirs", user_id=ANALYTICS_SECOND_USER_ID
    )
    await golden_workout.workout(
        start_time=_EARLY,
        exercises=[
            GoldenExercise(
                template_external_id=_SHARED,
                sets=(GoldenSet(weight_kg=Decimal("100.000"), reps=5),),
            )
        ],
    )
    await golden_workout.workout(
        start_time=_LATE,
        exercises=[
            GoldenExercise(
                template_external_id=_SHARED,
                sets=(GoldenSet(weight_kg=Decimal("300.000"), reps=5),),
            )
        ],
        user_id=ANALYTICS_SECOND_USER_ID,
    )

    result = await _records(session, _SHARED)

    # Guard against a vacuous pass: if the fixture wrote nothing, every assertion below holds
    # while proving nothing at all.
    assert result.records
    assert result.title == "Mine"
    assert all(record.value != Decimal("300.000") for record in result.records), (
        "another user's set leaked into this user's records (ASVS V4)"
    )
    assert all(row.weight_kg != Decimal("300.000") for row in result.reps_at_weight)
    assert _by_type(result)[PersonalRecordType.MAX_WEIGHT].value == Decimal("100.000")


@pytest.mark.integration
async def test_records_and_freshness_shape(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """The envelope: stated ordering, the raw window echoed back, and DQ-01's two resources.

    `window_start`/`window_end` are the assertion that no week snapping happened. 2026-08-01 is a
    Saturday and 2026-08-31 a Monday, so a snapped window would report 2026-07-27 / 2026-09-06 --
    a range the caller never asked about, over which "when did I first hit this" is a different
    question.

    Freshness names BOTH resources because `exercise_type` is the D-03 gate for the estimated-1RM
    record and it comes from the templates table: a stale template sync silently changes which
    sets are eligible for that record, with no error anywhere in the stack.
    """
    await golden_workout.template(external_id=_BENCH, title="Bench Press (Barbell)")
    await golden_workout.workout(
        start_time=_EARLY,
        exercises=[GoldenExercise(template_external_id=_BENCH, sets=_MIXED_SETS)],
    )

    result = await _records(session, _BENCH)

    record_types = [record.record_type.value for record in result.records]
    assert record_types == sorted(record_types)
    assert record_types == ["estimated_1rm", "max_reps", "max_weight", "session_volume"]
    assert result.exercise_template_external_id == _BENCH
    assert result.title == "Bench Press (Barbell)"
    assert (result.window_start, result.window_end) == (_START, _END), (
        "the window was snapped to whole weeks. A record is a point in time and has no bucket to "
        "be comparable with, so PROG-04 echoes the raw requested range back"
    )
    assert set(result.freshness.resources) == {RESOURCE_WORKOUTS, RESOURCE_EXERCISE_TEMPLATES}
    assert result.coverage.sessions_in_window == 1
    assert result.coverage.insufficient_data is True


# ---------------------------------------------------------------------------
# get_recent_records: the cross-exercise scan (PROG-04, asked cross-exercise).
#
# THE load-bearing test here is `test_a_window_leader_that_does_not_beat_history_is_not_a_record`
# -- it is the exact behaviour separating this function from `get_personal_records`, and a future
# refactor that collapses the two is most likely to break it silently, since every value
# assertion elsewhere would still pass.
# ---------------------------------------------------------------------------

_RR_BENCH = "RR-bench"
_RR_SQUAT = "RR-squat"
_RR_PULLUP = "RR-pullup"
_RR_SHARED = "RR-shared"

# A whole calendar month again, for the same reason `_START`/`_END` are: the window echoed back
# unsnapped is itself an assertion.
_RR_START = dt.date(2026, 8, 1)
_RR_END = dt.date(2026, 8, 31)

# Strictly BEFORE `_RR_START` -- the pre-window history a record must beat.
_RR_PRIOR = dt.datetime(2026, 7, 15, 2, 0, tzinfo=dt.UTC)  # local 2026-07-15
_RR_PRIOR_DAY = dt.date(2026, 7, 15)

# Two in-window instants, so ordering (latest-first) is assertable.
_RR_EARLY = dt.datetime(2026, 8, 3, 2, 0, tzinfo=dt.UTC)  # local 2026-08-03
_RR_LATE = dt.datetime(2026, 8, 20, 2, 0, tzinfo=dt.UTC)  # local 2026-08-20
_RR_EARLY_DAY = dt.date(2026, 8, 3)
_RR_LATE_DAY = dt.date(2026, 8, 20)


def _by_template_and_type(
    result: RecentRecordsResult,
) -> dict[tuple[str, PersonalRecordType], RecentRecord]:
    """Index by (exercise, record type) -- the grain a cross-exercise scan reports at."""
    return {
        (record.exercise_template_external_id, record.record.record_type): record
        for record in result.records
    }


async def _recent(
    session: AsyncSession, start_day: dt.date = _RR_START, end_day: dt.date = _RR_END
) -> RecentRecordsResult:
    """The default user's cross-exercise recent-records scan over the fixture month."""
    return await get_recent_records(
        session, user_id=DEFAULT_USER_ID, start_day=start_day, end_day=end_day
    )


@pytest.mark.integration
async def test_max_weight_record_beats_pre_window_history(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """The in-window heaviest set (100 kg) beats the pre-window heaviest (95 kg): one
    `MAX_WEIGHT` record, with `previous_value` naming the incumbent it beat.
    """
    await golden_workout.template(external_id=_RR_BENCH)
    await golden_workout.workout(
        start_time=_RR_PRIOR,
        exercises=[
            GoldenExercise(
                template_external_id=_RR_BENCH,
                sets=(GoldenSet(weight_kg=Decimal("95.000"), reps=5),),
            )
        ],
    )
    await golden_workout.workout(
        start_time=_RR_EARLY,
        exercises=[
            GoldenExercise(
                template_external_id=_RR_BENCH,
                sets=(GoldenSet(weight_kg=Decimal("100.000"), reps=3),),
            )
        ],
    )

    record = _by_template_and_type(await _recent(session))[
        (_RR_BENCH, PersonalRecordType.MAX_WEIGHT)
    ]

    assert record.record.value == Decimal("100.000")
    assert record.record.achieved_on == _RR_EARLY_DAY
    assert record.previous_value == Decimal("95.000")


@pytest.mark.integration
async def test_a_window_leader_that_does_not_beat_history_is_not_a_record(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """THE load-bearing test. 90 kg in-window against a 95 kg pre-window best yields NO
    `MAX_WEIGHT` record here -- exactly the case where `get_personal_records(start_day=...,
    end_day=...)` WOULD return 90 kg, because that function only ever looks inside its own
    window. A future refactor that collapses this function into a loop over that one would pass
    every OTHER assertion in this file and fail silently only here.
    """
    await golden_workout.template(external_id=_RR_BENCH)
    await golden_workout.workout(
        start_time=_RR_PRIOR,
        exercises=[
            GoldenExercise(
                template_external_id=_RR_BENCH,
                sets=(GoldenSet(weight_kg=Decimal("95.000"), reps=5),),
            )
        ],
    )
    await golden_workout.workout(
        start_time=_RR_EARLY,
        exercises=[
            GoldenExercise(
                template_external_id=_RR_BENCH,
                sets=(GoldenSet(weight_kg=Decimal("90.000"), reps=5),),
            )
        ],
    )

    by_template = _by_template_and_type(await _recent(session))

    assert (_RR_BENCH, PersonalRecordType.MAX_WEIGHT) not in by_template, (
        "a window leader that never beat history was reported as a record -- this is exactly "
        "the behaviour that separates get_recent_records from get_personal_records"
    )


@pytest.mark.integration
async def test_an_exercise_trained_first_time_in_window_has_no_previous_value(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """No pre-window history at all: the record still fires, with `previous_value is None` --
    a real and different fact from "beat a small number", never collapsed to zero.
    """
    await golden_workout.template(external_id=_RR_SQUAT)
    await golden_workout.workout(
        start_time=_RR_EARLY,
        exercises=[
            GoldenExercise(
                template_external_id=_RR_SQUAT,
                sets=(GoldenSet(weight_kg=Decimal("60.000"), reps=5),),
            )
        ],
    )

    record = _by_template_and_type(await _recent(session))[
        (_RR_SQUAT, PersonalRecordType.MAX_WEIGHT)
    ]

    assert record.record.value == Decimal("60.000")
    assert record.previous_value is None


@pytest.mark.integration
async def test_rep_pr_above_twelve_reps_is_reported(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """D-02's rep cap gates the ESTIMATE, never the observation -- a 20-rep set sets a rep PR
    here exactly as it does in `get_personal_records`.
    """
    await golden_workout.template(external_id=_RR_BENCH)
    await golden_workout.workout(
        start_time=_RR_EARLY,
        exercises=[
            GoldenExercise(
                template_external_id=_RR_BENCH,
                sets=(GoldenSet(weight_kg=Decimal("40.000"), reps=20),),
            )
        ],
    )

    record = _by_template_and_type(await _recent(session))[(_RR_BENCH, PersonalRecordType.MAX_REPS)]

    assert record.record.value == Decimal(20)
    assert record.previous_value is None


@pytest.mark.integration
async def test_session_volume_is_never_per_window(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """A 1,500 kg pre-window session beats two SEPARATE 1,000 kg in-window sessions -- even
    though their WINDOW total (2,000 kg) exceeds it. Summing across the window instead of
    scoping to one exercise-session would report a record that never actually happened in any
    single session.
    """
    await golden_workout.template(external_id=_RR_BENCH)
    await golden_workout.workout(
        start_time=_RR_PRIOR,
        exercises=[
            GoldenExercise(
                template_external_id=_RR_BENCH,
                sets=(GoldenSet(weight_kg=Decimal("100.000"), reps=15),),
            )
        ],
    )
    await golden_workout.workout(
        start_time=_RR_EARLY,
        exercises=[
            GoldenExercise(
                template_external_id=_RR_BENCH,
                sets=(GoldenSet(weight_kg=Decimal("100.000"), reps=10),),
            )
        ],
    )
    await golden_workout.workout(
        start_time=_RR_LATE,
        exercises=[
            GoldenExercise(
                template_external_id=_RR_BENCH,
                sets=(GoldenSet(weight_kg=Decimal("100.000"), reps=10),),
            )
        ],
    )

    by_template = _by_template_and_type(await _recent(session))

    assert (_RR_BENCH, PersonalRecordType.SESSION_VOLUME) not in by_template, (
        "session volume was compared against the WINDOW's total instead of per exercise-session"
    )


@pytest.mark.integration
async def test_bodyweight_exercise_yields_no_weight_or_volume_record(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """A `reps_only` exercise has no `weight_kg` at all: no `MAX_WEIGHT`, no `SESSION_VOLUME`,
    and no crash -- only the rep PR is a fact this exercise can report.
    """
    await golden_workout.template(external_id=_RR_PULLUP, exercise_type="reps_only")
    await golden_workout.workout(
        start_time=_RR_EARLY,
        exercises=[GoldenExercise(template_external_id=_RR_PULLUP, sets=(GoldenSet(reps=15),))],
    )

    by_template = _by_template_and_type(await _recent(session))

    assert (_RR_PULLUP, PersonalRecordType.MAX_WEIGHT) not in by_template
    assert (_RR_PULLUP, PersonalRecordType.SESSION_VOLUME) not in by_template
    assert by_template[(_RR_PULLUP, PersonalRecordType.MAX_REPS)].record.value == Decimal(15)


@pytest.mark.integration
async def test_a_tie_with_history_is_not_a_new_record(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """D-09: a value achieved LATER that merely EQUALS the incumbent is not a new record -- the
    earlier date already owns the tie-break, so the later occurrence must lose.
    """
    await golden_workout.template(external_id=_RR_BENCH)
    await golden_workout.workout(
        start_time=_RR_PRIOR,
        exercises=[
            GoldenExercise(
                template_external_id=_RR_BENCH,
                sets=(GoldenSet(weight_kg=Decimal("100.000"), reps=5),),
            )
        ],
    )
    await golden_workout.workout(
        start_time=_RR_EARLY,
        exercises=[
            GoldenExercise(
                template_external_id=_RR_BENCH,
                sets=(GoldenSet(weight_kg=Decimal("100.000"), reps=5),),
            )
        ],
    )

    by_template = _by_template_and_type(await _recent(session))

    assert (_RR_BENCH, PersonalRecordType.MAX_WEIGHT) not in by_template, (
        "an in-window set that merely equalled (never beat) the pre-window incumbent was "
        "reported as a new record"
    )


@pytest.mark.integration
async def test_records_are_sorted_newest_first(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """Three different exercises, three different first-ever days: the most recent leads."""
    await golden_workout.template(external_id=_RR_BENCH)
    await golden_workout.template(external_id=_RR_SQUAT)
    await golden_workout.template(external_id=_RR_PULLUP, exercise_type="reps_only")

    await golden_workout.workout(
        start_time=dt.datetime(2026, 8, 5, 2, 0, tzinfo=dt.UTC),
        exercises=[
            GoldenExercise(
                template_external_id=_RR_BENCH,
                sets=(GoldenSet(weight_kg=Decimal("60.000"), reps=5),),
            )
        ],
    )
    await golden_workout.workout(
        start_time=dt.datetime(2026, 8, 15, 2, 0, tzinfo=dt.UTC),
        exercises=[
            GoldenExercise(
                template_external_id=_RR_SQUAT,
                sets=(GoldenSet(weight_kg=Decimal("80.000"), reps=5),),
            )
        ],
    )
    await golden_workout.workout(
        start_time=dt.datetime(2026, 8, 25, 2, 0, tzinfo=dt.UTC),
        exercises=[GoldenExercise(template_external_id=_RR_PULLUP, sets=(GoldenSet(reps=10),))],
    )

    result = await _recent(session)

    assert result.records[0].record.achieved_on == dt.date(2026, 8, 25)
    assert result.records[0].exercise_template_external_id == _RR_PULLUP
    achieved_on_values = [record.record.achieved_on for record in result.records]
    assert achieved_on_values == sorted(achieved_on_values, reverse=True)


@pytest.mark.integration
async def test_second_users_sets_are_invisible_to_recent_records(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """ASVS V4: `template_external_ids=None` widens the EXERCISE scope, never the tenant scope,
    because the tenant predicate inside `qualifying_set_rows` is unconditional and leads it.
    """
    await golden_workout.user(user_id=ANALYTICS_SECOND_USER_ID)
    await golden_workout.template(external_id=_RR_SHARED, title="Mine")
    await golden_workout.template(
        external_id=_RR_SHARED, title="Theirs", user_id=ANALYTICS_SECOND_USER_ID
    )
    await golden_workout.workout(
        start_time=_RR_EARLY,
        exercises=[
            GoldenExercise(
                template_external_id=_RR_SHARED,
                sets=(GoldenSet(weight_kg=Decimal("100.000"), reps=5),),
            )
        ],
    )
    await golden_workout.workout(
        start_time=_RR_LATE,
        exercises=[
            GoldenExercise(
                template_external_id=_RR_SHARED,
                sets=(GoldenSet(weight_kg=Decimal("300.000"), reps=5),),
            )
        ],
        user_id=ANALYTICS_SECOND_USER_ID,
    )

    result = await _recent(session)

    # Guard against a vacuous pass: if the fixture wrote nothing, every assertion below holds
    # while proving nothing at all.
    assert result.records
    assert all(record.record.value != Decimal("300.000") for record in result.records), (
        "another user's set leaked into this user's cross-exercise scan (ASVS V4)"
    )
    record = _by_template_and_type(result)[(_RR_SHARED, PersonalRecordType.MAX_WEIGHT)]
    assert record.title == "Mine"
    assert record.record.value == Decimal("100.000")


@pytest.mark.integration
async def test_recent_records_envelope_shape(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """The window is echoed back unsnapped, and freshness names the same two resources
    `get_personal_records` does, for the same reason: `exercise_type` gates e1RM eligibility and
    comes from the templates table.
    """
    await golden_workout.template(external_id=_RR_BENCH)
    await golden_workout.workout(
        start_time=_RR_EARLY,
        exercises=[
            GoldenExercise(
                template_external_id=_RR_BENCH,
                sets=(GoldenSet(weight_kg=Decimal("100.000"), reps=5),),
            )
        ],
    )

    result = await _recent(session)

    assert (result.window_start, result.window_end) == (_RR_START, _RR_END), (
        "the window was snapped. A record is a point in time and has no bucket to be comparable "
        "with, so this echoes the raw requested range back exactly as PROG-04 does"
    )
    assert set(result.freshness.resources) == {RESOURCE_WORKOUTS, RESOURCE_EXERCISE_TEMPLATES}
