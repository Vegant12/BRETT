"""NORM-01 / NORM-03 as pure-function assertions (no database required).

The exhaustive test below is the important one: it fails if Hevy adds a muscle-group value
and nobody classifies it. Without it, a new upstream value would silently become "unmapped"
and quietly drain volume out of Phase 4's per-muscle figures with no error anywhere.
"""

from decimal import Decimal
from typing import Any

import pytest

from app.normalization.exercise_map import (
    ABDOMINAL_SPLIT_BY_TITLE,
    DELTOID_SPLIT_BY_TITLE,
    derive_assignments,
    normalize_title,
)
from app.normalization.muscles import (
    DEFAULT_ROLE_WEIGHTS,
    HEVY_AMBIGUOUS_GROUPS,
    HEVY_MUSCLE_GROUPS,
    HEVY_NON_CANONICAL_GROUPS,
    CanonicalMuscleGroup,
    MappingSource,
    MuscleAssignment,
    MuscleRole,
    role_weight,
    translate_hevy_muscle_group,
)

# --------------------------------------------------------------------------
# NORM-01: the canonical list and the total classification of Hevy's enum
# --------------------------------------------------------------------------


def test_canonical_list_is_the_agreed_nineteen() -> None:
    """D-01 (amended). Written out longhand on purpose: adding a group after data exists
    costs a migration of exercise_muscles, so the change must be deliberate."""
    assert {group.value for group in CanonicalMuscleGroup} == {
        "chest",
        "lats",
        "upper_back",
        "traps",
        "lower_back",
        "front_delts",
        "side_delts",
        "rear_delts",
        "biceps",
        "triceps",
        "forearms",
        "abs",
        "obliques",
        "quads",
        "hamstrings",
        "glutes",
        "calves",
        "abductors",
        "adductors",
    }


def test_every_hevy_value_is_classified() -> None:
    """The build breaks if Hevy adds a 21st value and nobody classifies it."""
    assert len(HEVY_MUSCLE_GROUPS) == 20

    for value in HEVY_MUSCLE_GROUPS:
        classifications = [
            translate_hevy_muscle_group(value) is not None,
            value in HEVY_AMBIGUOUS_GROUPS,
            value in HEVY_NON_CANONICAL_GROUPS,
        ]
        assert sum(classifications) == 1, f"{value!r} is classified {sum(classifications)} times"


def test_hevy_classification_sets_are_disjoint() -> None:
    """No Hevy value may sit in two buckets at once."""
    assert HEVY_AMBIGUOUS_GROUPS & HEVY_NON_CANONICAL_GROUPS == frozenset()

    for value in HEVY_AMBIGUOUS_GROUPS | HEVY_NON_CANONICAL_GROUPS:
        assert translate_hevy_muscle_group(value) is None


def test_unknown_hevy_value_is_none_not_an_error() -> None:
    """D-03: a mapping gap degrades to unmapped, it never raises mid-sync."""
    assert translate_hevy_muscle_group("kneecaps") is None
    assert translate_hevy_muscle_group("") is None


# --------------------------------------------------------------------------
# NORM-01: the curated split tables Hevy's flat taxonomy cannot express
# --------------------------------------------------------------------------


def test_deltoid_split_covers_all_three_heads() -> None:
    """A table that only ever yields one head would pass every single-exercise test below."""
    heads = {group for value in DELTOID_SPLIT_BY_TITLE.values() for group in value}
    assert heads == {
        CanonicalMuscleGroup.FRONT_DELTS,
        CanonicalMuscleGroup.SIDE_DELTS,
        CanonicalMuscleGroup.REAR_DELTS,
    }
    assert all(value for value in DELTOID_SPLIT_BY_TITLE.values())


def test_deltoid_keys_are_already_normalized() -> None:
    """Keys are looked up with normalize_title() output. A key like "Face Pull (Cable)"
    would never be hit -- a dead entry that silently drops a curated judgement."""
    for key in DELTOID_SPLIT_BY_TITLE:
        assert normalize_title(key) == key


def test_abdominal_keys_are_already_normalized() -> None:
    for key in ABDOMINAL_SPLIT_BY_TITLE:
        assert normalize_title(key) == key


def _triples(
    assignments: list[MuscleAssignment],
) -> list[tuple[CanonicalMuscleGroup, MuscleRole, MappingSource]]:
    return [(a.muscle_group, a.role, a.source) for a in assignments]


def test_lateral_raise_resolves_to_side_delts() -> None:
    """The NORM-01 headline: Hevy says `shoulders`, we say `side_delts`."""
    result = derive_assignments(
        template_id="D04AC939",
        title="Lateral Raise (Dumbbell)",
        primary_muscle_group="shoulders",
        secondary_muscle_groups=[],
    )
    assert _triples(result) == [
        (CanonicalMuscleGroup.SIDE_DELTS, MuscleRole.DIRECT, MappingSource.CURATED)
    ]


def test_face_pull_resolves_to_rear_delts() -> None:
    result = derive_assignments(
        template_id="A1B2C3D4",
        title="Face Pull (Cable)",
        primary_muscle_group="shoulders",
        secondary_muscle_groups=[],
    )
    assert _triples(result) == [
        (CanonicalMuscleGroup.REAR_DELTS, MuscleRole.DIRECT, MappingSource.CURATED)
    ]


def test_bench_press_secondary_shoulders_becomes_front_delts() -> None:
    """A press's secondary `shoulders` is front-delt work, never side or rear."""
    result = derive_assignments(
        template_id="79D0BB3A",
        title="Bench Press (Barbell)",
        primary_muscle_group="chest",
        secondary_muscle_groups=["triceps", "shoulders"],
    )
    assert _triples(result) == [
        (CanonicalMuscleGroup.CHEST, MuscleRole.DIRECT, MappingSource.HEVY),
        (CanonicalMuscleGroup.TRICEPS, MuscleRole.INDIRECT, MappingSource.HEVY),
        (CanonicalMuscleGroup.FRONT_DELTS, MuscleRole.INDIRECT, MappingSource.CURATED),
    ]

    groups = {a.muscle_group for a in result}
    assert CanonicalMuscleGroup.SIDE_DELTS not in groups
    assert CanonicalMuscleGroup.REAR_DELTS not in groups


def test_unknown_shoulder_exercise_yields_no_delt_guess() -> None:
    """A wrong head is worse than no head: Phase 4 would report it with confidence."""
    assert (
        derive_assignments(
            template_id="ZZZZZZZZ",
            title="Mystery Shoulder Thing",
            primary_muscle_group="shoulders",
            secondary_muscle_groups=[],
        )
        == []
    )


def test_unmapped_template_yields_empty_list() -> None:
    """D-03: a mapping gap returns nothing and never raises, so the sync completes."""
    assert (
        derive_assignments(
            template_id="X",
            title="Sled Push (Custom)",
            primary_muscle_group="full_body",
            secondary_muscle_groups=["other"],
        )
        == []
    )
    assert (
        derive_assignments(
            template_id="X",
            title="",
            primary_muscle_group=None,
            secondary_muscle_groups=[],
        )
        == []
    )


def test_abdominals_default_to_abs_and_twists_to_obliques() -> None:
    """Unlike `shoulders`, `abdominals` has a safe default -- the rectus."""
    crunch = derive_assignments(
        template_id="C1",
        title="Crunch (Machine)",
        primary_muscle_group="abdominals",
        secondary_muscle_groups=[],
    )
    assert _triples(crunch) == [
        (CanonicalMuscleGroup.ABS, MuscleRole.DIRECT, MappingSource.CURATED)
    ]

    twist = derive_assignments(
        template_id="C2",
        title="Russian Twist (Bodyweight)",
        primary_muscle_group="abdominals",
        secondary_muscle_groups=[],
    )
    assert _triples(twist) == [
        (CanonicalMuscleGroup.OBLIQUES, MuscleRole.DIRECT, MappingSource.CURATED)
    ]


def test_direct_beats_indirect_for_the_same_group() -> None:
    """Otherwise the same muscle is counted twice, at two different weights."""
    result = derive_assignments(
        template_id="T1",
        title="Triceps Pushdown (Cable)",
        primary_muscle_group="triceps",
        secondary_muscle_groups=["triceps"],
    )
    assert _triples(result) == [
        (CanonicalMuscleGroup.TRICEPS, MuscleRole.DIRECT, MappingSource.HEVY)
    ]


# --------------------------------------------------------------------------
# NORM-03: direct/indirect weighting is a query-time parameter, not a column
# --------------------------------------------------------------------------


def test_role_weight_defaults_and_override() -> None:
    assert role_weight(MuscleRole.DIRECT) == Decimal("1.0")
    assert role_weight(MuscleRole.INDIRECT) == Decimal("0.5")

    # Phase 4 answers "what if indirect counted 0.3?" without a migration.
    override = {MuscleRole.DIRECT: Decimal("1.0"), MuscleRole.INDIRECT: Decimal("0.3")}
    assert role_weight(MuscleRole.INDIRECT, override) == Decimal("0.3")
    assert role_weight(MuscleRole.DIRECT, override) == Decimal("1.0")


def test_default_role_weights_are_immutable() -> None:
    """No caller can mutate the default weighting process-wide."""
    weights: Any = DEFAULT_ROLE_WEIGHTS
    with pytest.raises(TypeError):
        weights[MuscleRole.DIRECT] = Decimal("9.0")

    assert DEFAULT_ROLE_WEIGHTS[MuscleRole.DIRECT] == Decimal("1.0")
