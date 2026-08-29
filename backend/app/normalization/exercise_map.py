"""Curated exercise -> canonical muscle overlay (D-02, NORM-01).

Authored and reviewed LIKE CODE, not re-derived from Hevy's template metadata on every sync.
Hevy may recategorise an exercise at any time -- its own API docs warn the structure may
change without notice -- and a silent recategorisation would rewrite months of per-muscle
history. What Hevy tells us seeds the mapping; this file owns it.

Absence from these tables is a SUPPORTED STATE, not an error (D-03). An exercise with no
resolvable canonical group still syncs in full -- workout, exercise and sets all persist -- and
is simply excluded from per-muscle analytics until someone curates it. Sync must never fail on
a mapping gap.

Scope of the human judgement required, from RESEARCH: of Hevy's 20 muscle-group values, 14 are
a mechanical rename, 4 are non-canonical, and exactly TWO -- `shoulders` and `abdominals` --
need a person. Everything below exists to resolve those two.
"""

import re
from collections.abc import Iterator, Mapping, Sequence
from types import MappingProxyType

from app.normalization.muscles import (
    CanonicalMuscleGroup,
    MappingSource,
    MuscleAssignment,
    MuscleRole,
    translate_hevy_muscle_group,
)

_PARENTHETICAL = re.compile(r"\s*\([^)]*\)\s*$")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_title(title: str) -> str:
    """Reduce a Hevy exercise title to a stable lookup key.

    Hevy titles carry the equipment in a trailing parenthetical -- "Lateral Raise
    (Dumbbell)", "Lateral Raise (Cable)", "Lateral Raise (Machine)". The deltoid head
    is the same in all three, so the parenthetical is dropped and one curated entry
    covers every equipment variant.
    """
    stripped = _PARENTHETICAL.sub("", title)
    return _NON_ALNUM.sub(" ", stripped.casefold()).strip()


_F = CanonicalMuscleGroup.FRONT_DELTS
_S = CanonicalMuscleGroup.SIDE_DELTS
_R = CanonicalMuscleGroup.REAR_DELTS

# NORM-01. Keys are normalize_title() output.
# Values are the deltoid head(s) Hevy's flat 'shoulders' expands to for that movement; the
# role (direct/indirect) is inherited from whether Hevy listed it as primary or secondary.
DELTOID_SPLIT_BY_TITLE: Mapping[str, tuple[CanonicalMuscleGroup, ...]] = MappingProxyType(
    {
        # Vertical pressing: front head does the work, side head assists heavily enough
        # to count as part of the movement rather than a separate exercise.
        "overhead press": (_F, _S),
        "seated overhead press": (_F, _S),
        "shoulder press": (_F, _S),
        "seated shoulder press": (_F, _S),
        "military press": (_F, _S),
        "push press": (_F, _S),
        "arnold press": (_F, _S),
        "landmine press": (_F,),
        "z press": (_F, _S),
        "single arm overhead press": (_F, _S),
        # Front raises: isolation, front head only.
        "front raise": (_F,),
        "plate front raise": (_F,),
        # Abduction in the scapular/frontal plane: side head.
        "lateral raise": (_S,),
        "seated lateral raise": (_S,),
        "leaning lateral raise": (_S,),
        "egyptian lateral raise": (_S,),
        "cable lateral raise": (_S,),
        "machine lateral raise": (_S,),
        "lu raise": (_S,),
        "y raise": (_S,),
        "upright row": (_S,),
        # Horizontal abduction / external rotation: rear head.
        "face pull": (_R,),
        "reverse fly": (_R,),
        "rear delt fly": (_R,),
        "rear delt reverse fly": (_R,),
        "bent over reverse fly": (_R,),
        "bent over rear delt raise": (_R,),
        "bent over low pulley side lateral": (_R,),
        "reverse pec deck": (_R,),
        "rear delt row": (_R,),
        "prone incline reverse fly": (_R,),
        "cable rear delt fly": (_R,),
    }
)

# A `shoulders` SECONDARY on an unlisted exercise is almost always a press: the front
# head is the one that receives indirect work in horizontal and vertical pressing, and
# side/rear heads essentially never appear as the secondary of a press. Guessing front
# here recovers real indirect pressing volume that would otherwise be discarded; the
# inverse guess (dropping it) would understate front-delt work on every push day.
SECONDARY_SHOULDERS_DEFAULT: tuple[CanonicalMuscleGroup, ...] = (CanonicalMuscleGroup.FRONT_DELTS,)

_ABS = CanonicalMuscleGroup.ABS
_OBLIQUES = CanonicalMuscleGroup.OBLIQUES

# NORM-01. Keys are normalize_title() output. Rotation, lateral flexion and anti-rotation
# are the oblique movements; everything else falls through to ABDOMINAL_DEFAULT.
ABDOMINAL_SPLIT_BY_TITLE: Mapping[str, tuple[CanonicalMuscleGroup, ...]] = MappingProxyType(
    {
        "russian twist": (_OBLIQUES,),
        "cable woodchop": (_OBLIQUES,),
        "woodchopper": (_OBLIQUES,),
        "side plank": (_OBLIQUES,),
        "side bend": (_OBLIQUES,),
        "oblique crunch": (_OBLIQUES,),
        "pallof press": (_OBLIQUES,),
        "landmine twist": (_OBLIQUES,),
        "windmill": (_OBLIQUES,),
        "standing side bend": (_OBLIQUES,),
        "bicycle crunch": (_ABS, _OBLIQUES),
        "hanging oblique knee raise": (_ABS, _OBLIQUES),
    }
)

# Unlike `shoulders`, `abdominals` has a safe default: nearly every ab movement trains
# the rectus. Obliques are the refinement, listed above.
ABDOMINAL_DEFAULT: tuple[CanonicalMuscleGroup, ...] = (CanonicalMuscleGroup.ABS,)

# D-02's authoritative layer: keyed by Hevy exercise_template_id, this REPLACES everything
# derived below for that template. Empty until the first real template sync produces the
# ids (plan 03-11); the title tables above carry v1. Populating it is a code change,
# reviewed like any other.
CURATED_BY_TEMPLATE_ID: Mapping[str, tuple[tuple[CanonicalMuscleGroup, MuscleRole], ...]] = (
    MappingProxyType({})
)


def _expand(
    hevy_value: str, role: MuscleRole, key: str
) -> Iterator[tuple[CanonicalMuscleGroup, MappingSource]]:
    """Expand one (Hevy value, role) pair into zero or more canonical groups.

    Yields nothing rather than raising when the value cannot be resolved -- that is the
    D-03 unmapped path, and it is reached on every sync by cardio and custom exercises.
    """
    if hevy_value == "shoulders":
        heads = DELTOID_SPLIT_BY_TITLE.get(key)
        if heads is None:
            # A DIRECT `shoulders` on an unlisted title is the case where guessing is
            # actively harmful: Phase 4 would report per-head volume for a head that may
            # never have been trained. Leave it unmapped until someone curates the title.
            if role is MuscleRole.DIRECT:
                return
            heads = SECONDARY_SHOULDERS_DEFAULT
        for head in heads:
            yield head, MappingSource.CURATED
        return

    if hevy_value == "abdominals":
        for group in ABDOMINAL_SPLIT_BY_TITLE.get(key, ABDOMINAL_DEFAULT):
            yield group, MappingSource.CURATED
        return

    translated = translate_hevy_muscle_group(hevy_value)
    if translated is not None:
        yield translated, MappingSource.HEVY


def derive_assignments(
    *,
    template_id: str,
    title: str,
    primary_muscle_group: str | None,
    secondary_muscle_groups: Sequence[str],
) -> list[MuscleAssignment]:
    """Resolve one Hevy exercise template to canonical (muscle, role, source) triples.

    Order of authority:
      1. CURATED_BY_TEMPLATE_ID -- replaces everything, source='curated'
      2. the title split tables for `shoulders` / `abdominals` -- source='curated'
      3. the mechanical Hevy translation -- source='hevy'
      4. nothing (D-03 unmapped) -- NEVER an exception

    Direct beats indirect: if a group is reachable both ways, it appears once as direct.
    """
    curated = CURATED_BY_TEMPLATE_ID.get(template_id)
    if curated is not None:
        return [MuscleAssignment(group, role, MappingSource.CURATED) for group, role in curated]

    pairs: list[tuple[str, MuscleRole]] = []
    if primary_muscle_group is not None:
        pairs.append((primary_muscle_group, MuscleRole.DIRECT))
    pairs.extend((value, MuscleRole.INDIRECT) for value in secondary_muscle_groups)

    key = normalize_title(title)

    # Directs are processed first, so keeping the FIRST occurrence per group makes
    # direct win over indirect without a second pass or a priority comparison.
    resolved: dict[CanonicalMuscleGroup, MuscleAssignment] = {}
    for hevy_value, role in pairs:
        for group, source in _expand(hevy_value, role, key):
            if group not in resolved:
                resolved[group] = MuscleAssignment(group, role, source)

    return list(resolved.values())
