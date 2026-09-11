"""PHYS-09's ordinal diff and PHYS-10's volume cross-reference (`app/analytics/physique.py`).

The seven pure-diff tests below take NO container by construction: `get_physique_diff` is
synchronous and takes already-fetched `PhysiqueObservationRecord` instances, built here with the
`_record` helper rather than through a database round trip. The eight cross-reference/latest-diff
tests DO need a container, because `get_muscle_group_volume` needs real `date_trunc` and window
functions -- `test_analytics_isolation.py`'s own reason SQLite is banned in this repo.
"""

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.physique import (
    get_latest_physique_diff,
    get_physique_diff,
    get_physique_volume_cross_reference,
)
from app.analytics.recomposition import RECOMP_LOOKBACK_WEEKS
from app.analytics.schemas import PhysiqueDiffVerdict
from app.db.models.physique import PHYSIQUE_MIN_ELAPSED_DAYS, PhysiqueRatingLevel, PoseState
from app.db.repositories.physique import (
    PhysiqueObservationRecord,
    RatingEntry,
    create_observation,
)
from app.normalization.muscles import CanonicalMuscleGroup, MuscleRole
from tests.conftest import DEFAULT_USER_ID, GoldenBuilder, GoldenExercise, GoldenSet

_NOT_VISIBLE_REASON = "Not visible in this fixture's photo set."

# A Monday, so `get_muscle_group_volume`'s week-snapping does not widen the fixture's own window
# unexpectedly. `RECOMP_LOOKBACK_WEEKS` (12) back from here is 2026-03-17 -- `_TRAIN_DAY` sits
# comfortably inside that span.
_OBSERVED_ON = dt.date(2026, 6, 8)
_TRAIN_DAY = dt.datetime(2026, 5, 4, 2, 0, tzinfo=dt.UTC)


def _rating_entry(group: CanonicalMuscleGroup, level: PhysiqueRatingLevel | None) -> RatingEntry:
    """One `RatingEntry`, level XOR reason -- the same invariant `create_observation` enforces."""
    if level is not None:
        return RatingEntry(muscle_group=group, rating_level=level)
    return RatingEntry(muscle_group=group, not_assessable_reason=_NOT_VISIBLE_REASON)


def _rating_entries(
    levels: dict[CanonicalMuscleGroup, PhysiqueRatingLevel | None] | None = None,
    *,
    default: PhysiqueRatingLevel | None = PhysiqueRatingLevel.DEVELOPED,
) -> list[RatingEntry]:
    """All 19 canonical groups at `default`, overridden per group by `levels`."""
    resolved = levels or {}
    return [_rating_entry(group, resolved.get(group, default)) for group in CanonicalMuscleGroup]


def _record(
    *,
    observed_on: dt.date,
    levels: dict[CanonicalMuscleGroup, PhysiqueRatingLevel | None] | None = None,
    default: PhysiqueRatingLevel | None = PhysiqueRatingLevel.DEVELOPED,
) -> PhysiqueObservationRecord:
    """All 19 ratings at `default`, overridden per group by `levels`.

    `default=None` writes every group as `Not Assessable` with a placeholder reason, mirroring
    `GoldenBuilder.physique_observation`'s own default so the two fixtures agree about what an
    unrated group looks like. Built directly as a dataclass -- no database round trip -- because
    `get_physique_diff` is pure and synchronous.
    """
    return PhysiqueObservationRecord(
        id=uuid.uuid4(),
        observed_on=observed_on,
        leanness_notes=None,
        conditioning_notes=None,
        symmetry_notes=None,
        photo_angles_present=(),
        pose_state=PoseState.RELAXED,
        conditions_note=None,
        superseded_at=None,
        superseded_reason=None,
        superseded_by_id=None,
        created_at=dt.datetime.now(dt.UTC),
        ratings=tuple(_rating_entries(levels, default=default)),
    )


async def _train_group(
    golden_workout: GoldenBuilder,
    *,
    group: CanonicalMuscleGroup,
    template_id: str,
    sets: int,
    start_time: dt.datetime = _TRAIN_DAY,
) -> None:
    """One DIRECT-only template for `group`, trained `sets` times on `start_time`.

    DIRECT-only and a single muscle group per template keeps each set's contribution to
    `weighted_sets` an exact `Decimal("1")` at the resolver's default weights, so the fixture's
    arithmetic is auditable by inspection.
    """
    await golden_workout.template(external_id=template_id, muscles=[(group, MuscleRole.DIRECT)])
    await golden_workout.workout(
        start_time=start_time,
        exercises=[
            GoldenExercise(
                template_external_id=template_id,
                sets=[GoldenSet(weight_kg=Decimal("40"), reps=8) for _ in range(sets)],
            )
        ],
    )


# ---------------------------------------------------------------------------
# PHYS-09: get_physique_diff -- pure, synchronous, no container.
# ---------------------------------------------------------------------------


def test_two_identical_observations_are_all_unchanged() -> None:
    earlier = _record(observed_on=dt.date(2026, 1, 1))
    later = _record(observed_on=dt.date(2026, 2, 1))

    result = get_physique_diff(earlier=earlier, later=later)

    assert len(result.muscle_groups) == 19
    assert all(row.verdict is PhysiqueDiffVerdict.UNCHANGED for row in result.muscle_groups)
    assert all(row.level_delta == 0 for row in result.muscle_groups)


def test_a_two_level_rise_is_improved() -> None:
    group = CanonicalMuscleGroup.CHEST
    earlier = _record(observed_on=dt.date(2026, 1, 1), levels={group: PhysiqueRatingLevel.MINIMAL})
    later = _record(observed_on=dt.date(2026, 2, 1), levels={group: PhysiqueRatingLevel.DEVELOPED})

    result = get_physique_diff(earlier=earlier, later=later)

    row = next(r for r in result.muscle_groups if r.muscle_group is group)
    assert row.verdict is PhysiqueDiffVerdict.IMPROVED
    assert row.level_delta == 2


def test_a_two_level_fall_is_regressed() -> None:
    group = CanonicalMuscleGroup.CHEST
    earlier = _record(observed_on=dt.date(2026, 1, 1), levels={group: PhysiqueRatingLevel.STANDOUT})
    later = _record(observed_on=dt.date(2026, 2, 1), levels={group: PhysiqueRatingLevel.DEVELOPED})

    result = get_physique_diff(earlier=earlier, later=later)

    row = next(r for r in result.muscle_groups if r.muscle_group is group)
    assert row.verdict is PhysiqueDiffVerdict.REGRESSED
    assert row.level_delta == -2


def test_a_one_level_move_is_unchanged_because_it_is_the_noise_floor() -> None:
    group = CanonicalMuscleGroup.CHEST
    earlier = _record(observed_on=dt.date(2026, 1, 1), levels={group: PhysiqueRatingLevel.MINIMAL})
    later = _record(observed_on=dt.date(2026, 2, 1), levels={group: PhysiqueRatingLevel.EMERGING})

    result = get_physique_diff(earlier=earlier, later=later)

    row = next(r for r in result.muscle_groups if r.muscle_group is group)
    assert row.verdict is PhysiqueDiffVerdict.UNCHANGED
    assert row.level_delta == 1


def test_not_assessable_on_either_side_is_not_comparable() -> None:
    group = CanonicalMuscleGroup.ABDUCTORS

    earlier_missing = _record(observed_on=dt.date(2026, 1, 1), levels={group: None})
    later_present = _record(observed_on=dt.date(2026, 2, 1))
    result_a = get_physique_diff(earlier=earlier_missing, later=later_present)
    row_a = next(r for r in result_a.muscle_groups if r.muscle_group is group)
    assert row_a.verdict is PhysiqueDiffVerdict.NOT_COMPARABLE
    assert row_a.level_delta is None

    earlier_present = _record(observed_on=dt.date(2026, 1, 1))
    later_missing = _record(observed_on=dt.date(2026, 2, 1), levels={group: None})
    result_b = get_physique_diff(earlier=earlier_present, later=later_missing)
    row_b = next(r for r in result_b.muscle_groups if r.muscle_group is group)
    assert row_b.verdict is PhysiqueDiffVerdict.NOT_COMPARABLE
    assert row_b.level_delta is None


def test_the_diff_returns_all_nineteen_groups_sorted_by_value() -> None:
    earlier = _record(observed_on=dt.date(2026, 1, 1))
    later = _record(observed_on=dt.date(2026, 2, 1))

    result = get_physique_diff(earlier=earlier, later=later)

    assert len(result.muscle_groups) == 19
    assert [row.muscle_group.value for row in result.muscle_groups] == sorted(
        group.value for group in CanonicalMuscleGroup
    )


def test_the_diff_is_byte_identical_across_repeated_runs() -> None:
    earlier = _record(
        observed_on=dt.date(2026, 1, 1),
        levels={CanonicalMuscleGroup.CHEST: PhysiqueRatingLevel.MINIMAL},
    )
    later = _record(
        observed_on=dt.date(2026, 2, 1),
        levels={CanonicalMuscleGroup.CHEST: PhysiqueRatingLevel.STANDOUT},
    )

    first = get_physique_diff(earlier=earlier, later=later).model_dump_json()
    second = get_physique_diff(earlier=earlier, later=later).model_dump_json()

    assert first == second


def test_the_diff_reports_the_elapsed_interval_and_the_unenforced_floor() -> None:
    earlier = _record(observed_on=dt.date(2026, 1, 1))
    later = _record(observed_on=dt.date(2026, 1, 9))  # 8 days later -- inside the 30-day floor

    result = get_physique_diff(earlier=earlier, later=later)

    assert result.elapsed_days == 8
    assert result.min_elapsed_days == PHYSIQUE_MIN_ELAPSED_DAYS
    # Not refused: the floor is surfaced, never enforced (PHYS-F01 deferred).
    assert len(result.muscle_groups) == 19


# ---------------------------------------------------------------------------
# get_latest_physique_diff -- needs a container (reads through the repository).
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_get_latest_physique_diff_returns_none_with_fewer_than_two_observations(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    assert await get_latest_physique_diff(session, user_id=DEFAULT_USER_ID) is None

    await golden_workout.physique_observation(observed_on=dt.date(2026, 1, 1))

    assert await get_latest_physique_diff(session, user_id=DEFAULT_USER_ID) is None


@pytest.mark.integration
async def test_get_latest_physique_diff_ignores_a_superseded_observation(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    del golden_workout  # session-only fixture use, kept for the rollback safety net

    oldest = await create_observation(
        session,
        user_id=DEFAULT_USER_ID,
        observed_on=dt.date(2026, 1, 1),
        ratings=_rating_entries(),
        pose_state=PoseState.RELAXED,
    )
    middle = await create_observation(
        session,
        user_id=DEFAULT_USER_ID,
        observed_on=dt.date(2026, 2, 1),
        ratings=_rating_entries(),
        pose_state=PoseState.RELAXED,
    )
    newest = await create_observation(
        session,
        user_id=DEFAULT_USER_ID,
        observed_on=dt.date(2026, 3, 1),
        ratings=_rating_entries(),
        pose_state=PoseState.RELAXED,
        supersedes_observation_id=middle.id,
        superseded_reason="corrected after re-review",
    )

    result = await get_latest_physique_diff(session, user_id=DEFAULT_USER_ID)

    assert result is not None
    assert result.earlier_observed_on == oldest.observed_on
    assert result.later_observed_on == newest.observed_on


# ---------------------------------------------------------------------------
# PHYS-10: get_physique_volume_cross_reference -- needs a container
# (get_muscle_group_volume needs real date_trunc/window functions).
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_the_cross_reference_returns_none_when_no_observation_exists(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    del golden_workout

    result = await get_physique_volume_cross_reference(session, user_id=DEFAULT_USER_ID)

    assert result is None


@pytest.mark.integration
async def test_the_cross_reference_reuses_the_recomposition_lookback(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    await golden_workout.physique_observation(observed_on=_OBSERVED_ON)

    result = await get_physique_volume_cross_reference(session, user_id=DEFAULT_USER_ID)

    assert result is not None
    assert result.lookback_weeks == RECOMP_LOOKBACK_WEEKS


@pytest.mark.integration
async def test_a_not_assessable_group_is_never_flagged_even_at_zero_volume(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """D-03: nobody is trained (every group totals `Decimal("0")`) and nobody is rated (every
    group defaults to `Not Assessable`), so the join must find nothing -- including
    `abductors`, which is `Not Assessable` in ordinary use (PHYS-02) and has zero volume here.
    """
    await golden_workout.physique_observation(observed_on=_OBSERVED_ON)

    result = await get_physique_volume_cross_reference(session, user_id=DEFAULT_USER_ID)

    assert result is not None
    assert result.flagged == []
    assert CanonicalMuscleGroup.ABDUCTORS not in {flag.muscle_group for flag in result.flagged}


@pytest.mark.integration
async def test_the_cross_reference_flags_a_group_that_is_both_underdeveloped_and_undertrained(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """CHEST is trained; every other group (including GLUTES and BICEPS) totals zero. GLUTES is
    rated Minimal and gets flagged. BICEPS is equally undertrained but rated Standout, and the
    rating disqualifies it -- proving the join is an AND, not a volume-only filter.
    """
    await _train_group(
        golden_workout, group=CanonicalMuscleGroup.CHEST, template_id="PHYS-CHEST", sets=5
    )
    await golden_workout.physique_observation(
        observed_on=_OBSERVED_ON,
        ratings=[
            (CanonicalMuscleGroup.GLUTES, PhysiqueRatingLevel.MINIMAL.value, None),
            (CanonicalMuscleGroup.BICEPS, PhysiqueRatingLevel.STANDOUT.value, None),
        ],
    )

    result = await get_physique_volume_cross_reference(session, user_id=DEFAULT_USER_ID)

    assert result is not None
    assert result.undertrained_threshold_weighted_sets == Decimal("0")
    assert len(result.flagged) == 1
    flag = result.flagged[0]
    assert flag.muscle_group is CanonicalMuscleGroup.GLUTES
    assert flag.rating_level is PhysiqueRatingLevel.MINIMAL
    assert flag.weighted_sets == Decimal("0")


@pytest.mark.integration
async def test_the_cross_reference_does_not_flag_a_well_trained_underdeveloped_group(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """Fourteen groups (including CHEST) are trained equally; five stay untrained. CHEST is
    rated Minimal but sits well outside the bottom-5 quartile, so it must not be flagged even
    though its rating alone would qualify it as underdeveloped.
    """
    untrained = {
        CanonicalMuscleGroup.ABDUCTORS,
        CanonicalMuscleGroup.ADDUCTORS,
        CanonicalMuscleGroup.CALVES,
        CanonicalMuscleGroup.FOREARMS,
        CanonicalMuscleGroup.OBLIQUES,
    }
    trained = [group for group in CanonicalMuscleGroup if group not in untrained]
    assert len(trained) == 14
    for index, group in enumerate(trained):
        await _train_group(
            golden_workout, group=group, template_id=f"PHYS-WELL-{index:02d}", sets=3
        )
    await golden_workout.physique_observation(
        observed_on=_OBSERVED_ON,
        ratings=[(CanonicalMuscleGroup.CHEST, PhysiqueRatingLevel.MINIMAL.value, None)],
    )

    result = await get_physique_volume_cross_reference(session, user_id=DEFAULT_USER_ID)

    assert result is not None
    assert result.undertrained_threshold_weighted_sets == Decimal("0")
    assert CanonicalMuscleGroup.CHEST not in {flag.muscle_group for flag in result.flagged}


@pytest.mark.integration
async def test_the_cross_reference_does_not_flag_a_high_volume_group_rated_minimal(
    session: AsyncSession, golden_workout: GoldenBuilder
) -> None:
    """CHEST is the single highest-volume group of all 19 (everything else totals zero) and is
    rated Minimal. It is unambiguously not in the bottom quartile, so it must not be flagged.
    """
    await _train_group(
        golden_workout, group=CanonicalMuscleGroup.CHEST, template_id="PHYS-HIGH", sets=10
    )
    await golden_workout.physique_observation(
        observed_on=_OBSERVED_ON,
        ratings=[(CanonicalMuscleGroup.CHEST, PhysiqueRatingLevel.MINIMAL.value, None)],
    )

    result = await get_physique_volume_cross_reference(session, user_id=DEFAULT_USER_ID)

    assert result is not None
    assert CanonicalMuscleGroup.CHEST not in {flag.muscle_group for flag in result.flagged}
