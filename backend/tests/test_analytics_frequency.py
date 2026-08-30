"""Training frequency: distinct-workout session counts and the exact per-week rate (VOL-03).

The rule under test is not the intuitive one. A per-muscle session count is DISTINCT WORKOUTS,
never a total taken over the exercises that hit that muscle. One workout containing three
hamstring exercises is ONE hamstring session, and adding the per-template counts together
instead inflated real training weeks by a factor: hamstrings 2 -> 8 (4.0x), biceps 2 -> 7,
glutes 2 -> 6, with 14 of 16 trained muscle groups affected. Every inflated figure still reads
as plausible history, which is why this needs a test rather than a reviewer.

`test_per_muscle_sessions_dedup_within_one_workout` is the load-bearing one: it would fail the
moment the counts are summed rather than de-duplicated. Its partner,
`test_per_muscle_sessions_count_separate_workouts_separately`, is what stops the naive fix of
"just always return 1" -- alone, either test is satisfiable by a wrong implementation, and
together they pin both directions.

The `sessions_per_week` arithmetic tests carry NO integration marker on purpose. The rate
formula is the piece Phase 5's CMP-01 will reuse, and it must stay verifiable when Docker is
not running -- the same argument `test_normalization_mapping.py` makes for its `apply_weights`
tests.
"""

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.frequency import get_training_frequency, sessions_per_week
from app.analytics.metadata import INSUFFICIENT_DATA_SESSION_THRESHOLD
from app.db.repositories.sync_state import (
    PROVIDER_HEVY,
    RESOURCE_EXERCISE_TEMPLATES,
    RESOURCE_WORKOUTS,
    complete_sync,
)
from app.normalization.muscles import CanonicalMuscleGroup, MuscleRole
from tests.conftest import (
    ANALYTICS_SECOND_USER_ID,
    DEFAULT_USER_ID,
    GoldenBuilder,
    GoldenExercise,
    GoldenSet,
)

# `FREQ-*` so these cannot collide with `test_analytics_volume.py`'s `VOL-*`,
# `test_analytics_rollup.py`'s `ROLLUP-*`, or `test_normalization_mapping.py`'s `RESOLVER-*`:
# the container is session-scoped and shared.
_RDL = "FREQ-RDL"
_CURL_HAM = "FREQ-HAMCURL"
_GOODMORNING = "FREQ-GOODMORNING"
_UNSYNCED = "FREQ-NEVER-SYNCED"

# A 7-day window (Mon 2026-08-24 .. Sun 2026-08-30) for the dedup tests, and a deliberately
# NON-multiple-of-7 10-day window for the rate test -- D-03 says the range is arbitrary, and a
# 7-day-only test would pass against an implementation that divided by whole weeks.
_WEEK_START = dt.date(2026, 8, 24)
_WEEK_END = dt.date(2026, 8, 30)
_TEN_DAY_START = dt.date(2026, 8, 20)
_TEN_DAY_END = dt.date(2026, 8, 29)

# Jakarta is UTC+7, so 02:00Z is 09:00 local on the same day -- comfortably inside the local day
# each constant is named for, and never at risk of sliding into its neighbour.
_MONDAY = dt.datetime(2026, 8, 24, 2, 0, tzinfo=dt.UTC)
_WEDNESDAY = dt.datetime(2026, 8, 26, 2, 0, tzinfo=dt.UTC)
_FRIDAY = dt.datetime(2026, 8, 28, 2, 0, tzinfo=dt.UTC)

# Three identical working sets. The magnitudes are irrelevant to frequency -- it counts
# workouts, never sets -- but a non-warmup set has to exist or the aggregate emits no row
# for the exercise at all.
_WORKING_SETS = (GoldenSet(weight_kg=Decimal("100.000"), reps=8),) * 3

_HAMSTRING_TEMPLATES = (_RDL, _CURL_HAM, _GOODMORNING)


async def _seed_hamstring_templates(golden_workout: GoldenBuilder) -> None:
    """Three DISTINCT templates that all map to the same muscle.

    That shape is the whole point: three templates, one muscle. If the templates mapped to
    three different muscles the de-duplication bug would be invisible, because each muscle
    would legitimately have exactly one session.
    """
    for template_id in _HAMSTRING_TEMPLATES:
        await golden_workout.template(
            external_id=template_id,
            muscles=[(CanonicalMuscleGroup.HAMSTRINGS, MuscleRole.DIRECT)],
        )


def _working_exercise(template_id: str) -> GoldenExercise:
    """One exercise on the given template, carrying three identical working sets.

    Deliberately muscle-agnostic: the same shape is used for the hamstring fixtures, the chest
    one and the ordering fixture, so a test arrangement differs only in its MAPPING and never in
    its set contents.
    """
    return GoldenExercise(template_external_id=template_id, sets=_WORKING_SETS)


def test_sessions_per_week_arithmetic_is_exact() -> None:
    """10 days is exactly 10/7 weeks, and the rate is quantized before anyone sees it.

    `Decimal` and never binary floating point: two arithmetically identical rates have to
    compare equal, and `0.68` is what a coach reads where the raw quotient is
    `0.6774193548387097`.
    """
    assert sessions_per_week(3, 10) == Decimal("2.10")
    assert sessions_per_week(2, 7) == Decimal("2.00")
    assert sessions_per_week(1, 10) == Decimal("0.70")
    assert sessions_per_week(3, 31) == Decimal("0.68")
    assert sessions_per_week(0, 7) == Decimal("0.00")


def test_sessions_per_week_rejects_a_zero_day_window() -> None:
    """A zero-day window is a caller bug, not a zero rate.

    T-04-05: the message is a fixed literal and carries no date, no count and no user id,
    because it is going to be logged.
    """
    with pytest.raises(ValueError, match="window length must be positive"):
        sessions_per_week(1, 0)


@pytest.mark.integration
async def test_per_muscle_sessions_dedup_within_one_workout(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """THE load-bearing test: three hamstring exercises in one workout is ONE session.

    This is the defect RESEARCH measured as the most dangerous in the phase. Summing the
    per-template session counts produces 3 here, and 8-against-a-true-2 on real data, and the
    inflated number reads as ordinary training history rather than as arithmetic.
    """
    await _seed_hamstring_templates(golden_workout)
    await golden_workout.workout(
        start_time=_MONDAY,
        exercises=[_working_exercise(template_id) for template_id in _HAMSTRING_TEMPLATES],
    )

    result = await get_training_frequency(
        session, user_id=DEFAULT_USER_ID, start_day=_WEEK_START, end_day=_WEEK_END
    )

    hamstrings = [
        row for row in result.muscle_groups if row.muscle_group is CanonicalMuscleGroup.HAMSTRINGS
    ]
    assert len(hamstrings) == 1
    assert hamstrings[0].sessions == 1, (
        "per-muscle sessions were SUMMED instead of de-duplicated. One workout containing three "
        "hamstring exercises is ONE hamstring session -- summing inflated hamstrings 2 -> 8 "
        "(4.0x) and 14 of 16 muscle groups on real data"
    )
    assert hamstrings[0].sessions_per_week == Decimal("1.00")
    assert hamstrings[0].insufficient_data is True
    # Guard against a vacuous pass: three exercises really were written.
    assert len(result.exercises) == 3


@pytest.mark.integration
async def test_per_muscle_sessions_count_separate_workouts_separately(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """The partner assertion, and the reason both tests exist.

    Without it, "always return 1" passes the de-duplication test above while destroying every
    frequency figure in the other direction. The same three exercises, spread across three
    workouts, are three hamstring sessions.
    """
    await _seed_hamstring_templates(golden_workout)
    for start_time, template_id in zip(
        (_MONDAY, _WEDNESDAY, _FRIDAY), _HAMSTRING_TEMPLATES, strict=True
    ):
        await golden_workout.workout(
            start_time=start_time, exercises=[_working_exercise(template_id)]
        )

    result = await get_training_frequency(
        session, user_id=DEFAULT_USER_ID, start_day=_WEEK_START, end_day=_WEEK_END
    )

    hamstrings = [
        row for row in result.muscle_groups if row.muscle_group is CanonicalMuscleGroup.HAMSTRINGS
    ]
    assert len(hamstrings) == 1
    assert hamstrings[0].sessions == 3
    assert hamstrings[0].sessions_per_week == Decimal("3.00")
    assert hamstrings[0].insufficient_data is False


@pytest.mark.integration
async def test_sessions_per_week_over_an_arbitrary_range(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """D-03: 3 sessions over 10 days is 2.1 per week -- not 3, and not 1.

    The window is deliberately not a multiple of 7. That is the only shape that catches an
    implementation which divided by whole weeks, or which widened the requested range outward
    to a week boundary the way weekly volume does.
    """
    await _seed_hamstring_templates(golden_workout)
    for start_time, template_id in zip(
        (_MONDAY, _WEDNESDAY, _FRIDAY), _HAMSTRING_TEMPLATES, strict=True
    ):
        await golden_workout.workout(
            start_time=start_time, exercises=[_working_exercise(template_id)]
        )

    result = await get_training_frequency(
        session, user_id=DEFAULT_USER_ID, start_day=_TEN_DAY_START, end_day=_TEN_DAY_END
    )

    assert result.coverage.sessions_in_window == 3
    assert result.sessions_per_week == Decimal("2.10")


@pytest.mark.integration
async def test_per_exercise_frequency_is_reported_alongside_per_muscle(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """Every distinct template trained in the window gets its own row, with its title.

    Per-exercise frequency is not derivable from the per-muscle rows -- three templates hitting
    one muscle collapse to a single muscle row by design -- so both grains are reported.
    """
    titles = {
        _RDL: "Romanian Deadlift (Barbell)",
        _CURL_HAM: "Seated Leg Curl (Machine)",
        _GOODMORNING: "Good Morning (Barbell)",
    }
    for template_id, title in titles.items():
        await golden_workout.template(
            external_id=template_id,
            title=title,
            muscles=[(CanonicalMuscleGroup.HAMSTRINGS, MuscleRole.DIRECT)],
        )
    await golden_workout.workout(
        start_time=_MONDAY,
        exercises=[_working_exercise(template_id) for template_id in _HAMSTRING_TEMPLATES],
    )

    result = await get_training_frequency(
        session, user_id=DEFAULT_USER_ID, start_day=_WEEK_START, end_day=_WEEK_END
    )

    assert [row.exercise_template_external_id for row in result.exercises] == sorted(titles)
    assert all(row.sessions == 1 for row in result.exercises)
    assert {row.exercise_template_external_id: row.title for row in result.exercises} == titles


@pytest.mark.integration
async def test_per_exercise_title_is_none_for_an_unsynced_template(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """An unsynced template degrades to "no title, no muscles" -- it never raises.

    `workout_exercises.exercise_template_external_id` is a plain string and deliberately not a
    foreign key, so a template the user deleted upstream, or one a partial sync has not reached
    yet, must not block a frequency answer for everything else in the window.
    """
    await golden_workout.workout(
        start_time=_MONDAY,
        exercises=[GoldenExercise(template_external_id=_UNSYNCED, sets=_WORKING_SETS)],
    )

    result = await get_training_frequency(
        session, user_id=DEFAULT_USER_ID, start_day=_WEEK_START, end_day=_WEEK_END
    )

    assert len(result.exercises) == 1
    assert result.exercises[0].exercise_template_external_id == _UNSYNCED
    assert result.exercises[0].title is None
    assert result.exercises[0].sessions == 1
    assert result.muscle_groups == [], (
        "an unmapped template contributed to a muscle group. With no mapping there is no muscle "
        "to attribute the sets to, and inventing one would be a fabricated number"
    )


# DQ-01 / DQ-02 / U-03: the envelope, per-row confidence, and scoping

_CHEST_TEMPLATE = "FREQ-BENCH"
# The two live-observed sync timestamps, 25 minutes apart -- the drift that makes a single
# collapsed last_synced_at lossy.
_SYNCED_WORKOUTS_AT = dt.datetime(2026, 8, 30, 5, 43, 18, tzinfo=dt.UTC)
_SYNCED_TEMPLATES_AT = dt.datetime(2026, 8, 30, 6, 8, 4, tzinfo=dt.UTC)


@pytest.mark.integration
async def test_frequency_carries_freshness_for_workouts_and_exercise_templates(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """DQ-01: a per-muscle answer is only as fresh as the STALER of its two sources.

    The muscle map comes from `exercise_templates`, so a stale template sync silently changes
    every per-muscle number in this response with no error anywhere in the stack. Collapsing the
    two into one `last_synced_at` would report the newer for both, which is precisely the
    staleness Claude needs in order to caveat an answer instead of asserting it.

    Written against the second user because `sync_state` rows for the default user are the Hevy
    sync suite's territory, and the container is session-scoped and shared.
    """
    await golden_workout.user(user_id=ANALYTICS_SECOND_USER_ID)
    await golden_workout.template(
        external_id=_RDL,
        muscles=[(CanonicalMuscleGroup.HAMSTRINGS, MuscleRole.DIRECT)],
        user_id=ANALYTICS_SECOND_USER_ID,
    )
    await golden_workout.workout(
        start_time=_MONDAY,
        exercises=[_working_exercise(_RDL)],
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
    await session.flush()

    result = await get_training_frequency(
        session, user_id=ANALYTICS_SECOND_USER_ID, start_day=_WEEK_START, end_day=_WEEK_END
    )

    assert result.freshness.resources == {
        RESOURCE_WORKOUTS: _SYNCED_WORKOUTS_AT,
        RESOURCE_EXERCISE_TEMPLATES: _SYNCED_TEMPLATES_AT,
    }
    # Two genuinely distinct values, not one row read twice.
    assert len(set(result.freshness.resources.values())) == 2


@pytest.mark.integration
async def test_frequency_carries_the_d06_coverage_block(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """DQ-02 / D-06 on both sides of the threshold, from one fixture arrangement.

    The second query is the point: the same window re-read after a second workout has to flip
    `insufficient_data`, so `<` and `<=` are distinguishable and an off-by-one in the comparison
    cannot ship green.

    `earliest_data_at` is asserted here as well because it is what separates "you did not train
    in this window" from "your synced history does not reach back that far" -- two facts a bare
    zero cannot tell apart.
    """
    await _seed_hamstring_templates(golden_workout)
    await golden_workout.workout(start_time=_MONDAY, exercises=[_working_exercise(_RDL)])

    first = await get_training_frequency(
        session, user_id=DEFAULT_USER_ID, start_day=_WEEK_START, end_day=_WEEK_END
    )

    assert first.coverage.sessions_in_window == 1
    assert first.coverage.insufficient_data is True
    assert first.coverage.earliest_data_at == _MONDAY

    await golden_workout.workout(start_time=_WEDNESDAY, exercises=[_working_exercise(_RDL)])

    second = await get_training_frequency(
        session, user_id=DEFAULT_USER_ID, start_day=_WEEK_START, end_day=_WEEK_END
    )

    assert second.coverage.sessions_in_window == 2
    assert second.coverage.insufficient_data is False
    assert second.coverage.earliest_data_at == _MONDAY


@pytest.mark.integration
async def test_per_muscle_insufficient_data_uses_the_shared_threshold(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """U-03: per-row confidence is ADDITIVE to the response-level flag, not a replacement.

    "Plenty of chest data but only one rear-delt session" is the case a single response-level
    flag cannot express at all. Here the window holds two sessions -- so the response is not
    insufficient -- while chest was trained once and is. Both facts are true simultaneously, and
    only a per-row count can carry them.
    """
    await golden_workout.template(
        external_id=_CHEST_TEMPLATE,
        muscles=[(CanonicalMuscleGroup.CHEST, MuscleRole.DIRECT)],
    )
    await golden_workout.template(
        external_id=_RDL,
        muscles=[(CanonicalMuscleGroup.HAMSTRINGS, MuscleRole.DIRECT)],
    )
    await golden_workout.workout(
        start_time=_MONDAY,
        exercises=[_working_exercise(_RDL), _working_exercise(_CHEST_TEMPLATE)],
    )
    await golden_workout.workout(start_time=_WEDNESDAY, exercises=[_working_exercise(_RDL)])

    result = await get_training_frequency(
        session, user_id=DEFAULT_USER_ID, start_day=_WEEK_START, end_day=_WEEK_END
    )

    chest = next(
        row for row in result.muscle_groups if row.muscle_group is CanonicalMuscleGroup.CHEST
    )
    hams = next(
        row for row in result.muscle_groups if row.muscle_group is CanonicalMuscleGroup.HAMSTRINGS
    )
    # Written against the shared constant, never the literal 2: revisiting D-05 later must be a
    # one-line change that does not silently invalidate this into asserting a dead threshold.
    assert (chest.sessions, chest.insufficient_data) == (
        INSUFFICIENT_DATA_SESSION_THRESHOLD - 1,
        True,
    )
    assert (hams.sessions, hams.insufficient_data) == (INSUFFICIENT_DATA_SESSION_THRESHOLD, False)
    assert result.coverage.insufficient_data is False, (
        "U-03: the response-level D-06 flag is about the WINDOW, not about any one muscle. "
        "Two sessions happened, so the response is not insufficient -- but chest still is"
    )


@pytest.mark.integration
async def test_frequency_results_are_deterministically_ordered(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """Both lists are sorted by a stated key, never by dict-iteration order.

    The fixtures are written in an order that is NOT the sorted order, in both dimensions: the
    templates are inserted RDL / bench / good-morning but sort bench-first, and the muscles are
    reached hamstrings-first but sort chest-first. An implementation that happened to preserve
    insertion order would pass a fixture arranged any other way.

    Phase 6 will diff these responses between runs, and a flaky ordering is a flaky test.
    """
    for template_id, muscle_group in (
        (_RDL, CanonicalMuscleGroup.HAMSTRINGS),
        (_CHEST_TEMPLATE, CanonicalMuscleGroup.CHEST),
        (_GOODMORNING, CanonicalMuscleGroup.GLUTES),
    ):
        await golden_workout.template(
            external_id=template_id, muscles=[(muscle_group, MuscleRole.DIRECT)]
        )
    await golden_workout.workout(
        start_time=_MONDAY,
        exercises=[
            _working_exercise(template_id)
            for template_id in (_RDL, _CHEST_TEMPLATE, _GOODMORNING)
        ],
    )

    result = await get_training_frequency(
        session, user_id=DEFAULT_USER_ID, start_day=_WEEK_START, end_day=_WEEK_END
    )

    muscle_values = [row.muscle_group.value for row in result.muscle_groups]
    exercise_ids = [row.exercise_template_external_id for row in result.exercises]
    assert muscle_values == sorted(muscle_values)
    assert muscle_values == ["chest", "glutes", "hamstrings"]
    assert exercise_ids == sorted(exercise_ids)
    assert exercise_ids == [_CHEST_TEMPLATE, _GOODMORNING, _RDL]


@pytest.mark.integration
async def test_frequency_is_scoped_to_one_user(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """T-04-02: three workouts for one user and one for the other, in the same window.

    A single-user suite cannot see a missing tenant predicate -- every row belongs to the only
    user, so an unscoped query is right by accident. Both users are given a template under the
    SAME external id with different titles, because Hevy's built-in template ids are global: an
    unscoped title lookup would attach the other user's exercise name to this user's row.
    """
    await golden_workout.user(user_id=ANALYTICS_SECOND_USER_ID)
    await golden_workout.template(
        external_id=_RDL,
        title="Mine",
        muscles=[(CanonicalMuscleGroup.HAMSTRINGS, MuscleRole.DIRECT)],
    )
    await golden_workout.template(
        external_id=_RDL,
        title="Theirs",
        muscles=[(CanonicalMuscleGroup.HAMSTRINGS, MuscleRole.DIRECT)],
        user_id=ANALYTICS_SECOND_USER_ID,
    )
    for start_time in (_MONDAY, _WEDNESDAY, _FRIDAY):
        await golden_workout.workout(
            start_time=start_time,
            exercises=[_working_exercise(_RDL)],
            user_id=ANALYTICS_SECOND_USER_ID,
        )
    await golden_workout.workout(start_time=_MONDAY, exercises=[_working_exercise(_RDL)])

    mine = await get_training_frequency(
        session, user_id=DEFAULT_USER_ID, start_day=_WEEK_START, end_day=_WEEK_END
    )
    theirs = await get_training_frequency(
        session, user_id=ANALYTICS_SECOND_USER_ID, start_day=_WEEK_START, end_day=_WEEK_END
    )

    # Guard against a vacuous pass: if the fixture wrote nothing, both would be zero and equal.
    assert theirs.coverage.sessions_in_window == 3
    assert theirs.sessions_per_week == Decimal("3.00")
    assert mine.coverage.sessions_in_window == 1, (
        "ASVS V4 violated: training frequency included another user's workouts"
    )
    assert mine.sessions_per_week == Decimal("1.00")
    assert [row.title for row in mine.exercises] == ["Mine"]
    assert [row.sessions for row in mine.muscle_groups] == [1]
