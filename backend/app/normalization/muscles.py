"""Canonical muscle taxonomy (NORM-01) and direct/indirect weighting (NORM-03).

Hevy's own ``MuscleGroup`` enum has a single flat ``shoulders`` value. So does the largest
public exercise dataset (``free-exercise-db``, 873 exercises, checked 2026-08-29). There is no
dataset to import the front/side/rear deltoid split from -- it is hand-curated in
``exercise_map.py`` and reviewed like code (D-02).

The stake: a missing split makes "which deltoid head is undertrained" unanswerable, and a WRONG
split is worse than none, because Phase 4 will report confident per-head volume built on it.

The 1.0/0.5 direct/indirect weighting lives here as a DEFAULT, never as a stored column.
NORM-03 and blueprint §18 both require it be configurable at query time; a `weight` column
would freeze one answer into the data.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType


# D-01 (amended 2026-08-29): 19 groups = the hypertrophy split, blueprint
# §18's upper_back, and the abductors/adductors Hevy supplies natively. Changing this enum
# after data exists costs a data migration of exercise_muscles -- it is not a free edit.
class CanonicalMuscleGroup(StrEnum):
    """The project's muscle vocabulary. Provider-neutral by construction."""

    CHEST = "chest"
    LATS = "lats"
    UPPER_BACK = "upper_back"
    TRAPS = "traps"
    LOWER_BACK = "lower_back"
    FRONT_DELTS = "front_delts"
    SIDE_DELTS = "side_delts"
    REAR_DELTS = "rear_delts"
    BICEPS = "biceps"
    TRICEPS = "triceps"
    FOREARMS = "forearms"
    ABS = "abs"
    OBLIQUES = "obliques"
    QUADS = "quads"
    HAMSTRINGS = "hamstrings"
    GLUTES = "glutes"
    CALVES = "calves"
    ABDUCTORS = "abductors"
    ADDUCTORS = "adductors"


class MuscleRole(StrEnum):
    """How hard a muscle works in an exercise. NORM-03 stores the role, never the weight."""

    DIRECT = "direct"
    INDIRECT = "indirect"


# NORM-02 audit trail: 'hevy' = mechanical translation of Hevy's own taxonomy,
# 'curated' = a judgement call authored in exercise_map.py, 'override' = a user correction
# stored in exercise_muscle_overrides.
class MappingSource(StrEnum):
    """Provenance of one muscle assignment."""

    HEVY = "hevy"
    CURATED = "curated"
    OVERRIDE = "override"


# Hevy's live ``MuscleGroup`` enum, all 20 values verbatim from the OpenAPI doc (2026-08-29).
HEVY_MUSCLE_GROUPS: frozenset[str] = frozenset(
    {
        "abdominals",
        "shoulders",
        "biceps",
        "triceps",
        "forearms",
        "quadriceps",
        "hamstrings",
        "calves",
        "glutes",
        "abductors",
        "adductors",
        "lats",
        "upper_back",
        "traps",
        "lower_back",
        "chest",
        "cardio",
        "neck",
        "full_body",
        "other",
    }
)

# The mechanical half of the translation: 13 identities plus one rename. `abdominals` and
# `shoulders` are deliberately absent -- they need a title, not a lookup.
_HEVY_TO_CANONICAL: dict[str, CanonicalMuscleGroup] = {
    "chest": CanonicalMuscleGroup.CHEST,
    "lats": CanonicalMuscleGroup.LATS,
    "upper_back": CanonicalMuscleGroup.UPPER_BACK,
    "traps": CanonicalMuscleGroup.TRAPS,
    "lower_back": CanonicalMuscleGroup.LOWER_BACK,
    "biceps": CanonicalMuscleGroup.BICEPS,
    "triceps": CanonicalMuscleGroup.TRICEPS,
    "forearms": CanonicalMuscleGroup.FOREARMS,
    "hamstrings": CanonicalMuscleGroup.HAMSTRINGS,
    "glutes": CanonicalMuscleGroup.GLUTES,
    "calves": CanonicalMuscleGroup.CALVES,
    "abductors": CanonicalMuscleGroup.ABDUCTORS,
    "adductors": CanonicalMuscleGroup.ADDUCTORS,
    "quadriceps": CanonicalMuscleGroup.QUADS,
}

# The only two of Hevy's 20 values that require human judgement. Resolved by title
# in exercise_map.py; NOT resolvable by a lookup table alone.
HEVY_AMBIGUOUS_GROUPS: frozenset[str] = frozenset({"shoulders", "abdominals"})

# Valid Hevy values that map to no canonical hypertrophy group. Treated as
# unmapped (D-03), NOT fanned out: expanding full_body to all 19 groups would silently
# inflate every per-muscle volume figure in Phase 4.
HEVY_NON_CANONICAL_GROUPS: frozenset[str] = frozenset({"cardio", "neck", "full_body", "other"})


def translate_hevy_muscle_group(value: str) -> CanonicalMuscleGroup | None:
    """Mechanically translate one Hevy muscle-group value.

    Returns ``None`` for the two ambiguous values, for the four non-canonical ones, and
    for any value Hevy invents after this was written. It never raises: D-03 says a
    mapping gap must not block a sync, and an unrecognised enum value is a mapping gap,
    not a data-integrity failure.
    """
    return _HEVY_TO_CANONICAL.get(value)


DEFAULT_ROLE_WEIGHTS: Mapping[MuscleRole, Decimal] = MappingProxyType(
    {
        MuscleRole.DIRECT: Decimal("1.0"),
        MuscleRole.INDIRECT: Decimal("0.5"),
    }
)


def role_weight(role: MuscleRole, weights: Mapping[MuscleRole, Decimal] | None = None) -> Decimal:
    """Weight for a role at QUERY time (NORM-03).

    Phase 4 passes its own mapping to answer "what if indirect counted 0.3?" without a
    migration. Decimal rather than IEEE-754 binary arithmetic: these multiply into tonnage sums.
    """
    return (weights or DEFAULT_ROLE_WEIGHTS)[role]


@dataclass(frozen=True, slots=True)
class MuscleAssignment:
    """One (muscle, role) pair for one exercise, with its provenance."""

    muscle_group: CanonicalMuscleGroup
    role: MuscleRole
    source: MappingSource
