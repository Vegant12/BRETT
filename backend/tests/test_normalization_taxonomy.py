"""NORM-01 / NORM-03 as pure-function assertions (no database required).

The exhaustive test below is the important one: it fails if Hevy adds a muscle-group value
and nobody classifies it. Without it, a new upstream value would silently become "unmapped"
and quietly drain volume out of Phase 4's per-muscle figures with no error anywhere.
"""

from decimal import Decimal
from typing import Any

import pytest

from app.normalization.muscles import (
    DEFAULT_ROLE_WEIGHTS,
    HEVY_AMBIGUOUS_GROUPS,
    HEVY_MUSCLE_GROUPS,
    HEVY_NON_CANONICAL_GROUPS,
    CanonicalMuscleGroup,
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
