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
        # Added from the live template inventory (plan 03-12). A CUSTOM template in this
        # account, filed by its author under `shoulders`, and never once logged in 327
        # workouts. "Press up" reads as either a bodyweight overhead press or (British
        # usage) a push-up; the front head is the one head both readings agree on, so it is
        # the only head assigned. Revisit if it is ever actually performed.
        "press up": (_F,),
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
        # Added from the live template inventory (plan 03-12). This one is not
        # hypothetical: it is the single most-performed unmapped exercise in this account
        # (35 logged sets across the Cable and Dumbbell variants), and one normalised key
        # covers both because `normalize_title` drops the equipment parenthetical.
        "single arm lateral raise": (_S,),
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

_M = CanonicalMuscleGroup


def _curate(
    *,
    direct: tuple[CanonicalMuscleGroup, ...],
    indirect: tuple[CanonicalMuscleGroup, ...] = (),
) -> tuple[tuple[CanonicalMuscleGroup, MuscleRole], ...]:
    """Spell one curated entry as prime movers plus assistors.

    The stored shape is still a flat tuple of ``(group, role)`` pairs -- this only stops
    ``MuscleRole.DIRECT`` from being retyped thirty times, which is precisely the kind of
    repetition where a stray ``INDIRECT`` hides in plain sight during review.
    """
    return tuple((group, MuscleRole.DIRECT) for group in direct) + tuple(
        (group, MuscleRole.INDIRECT) for group in indirect
    )


# D-02's authoritative layer: keyed by Hevy exercise_template_id, this REPLACES everything
# derived below for that template. Populating it is a code change, reviewed like any other.
#
# Every entry below is a `full_body` template from the live inventory (plan 03-11). Hevy's
# `full_body` is not a muscle, so the mechanical translation yields nothing -- yet a barbell
# clean plainly trains quads, glutes, hamstrings and traps, and permanently scoring it as
# zero volume would be wrong rather than merely incomplete.
#
# THE LINE between an entry here and an entry in DELIBERATELY_UNMAPPED below is whether the
# movement is LOADED RESISTANCE WORK WITH AN ECCENTRIC. A thruster lowers the bar under
# control and counts; a ball slam and a sled push have no eccentric at all and do not.
# Burpees, crawls, running drills and yoga are conditioning or mobility, not hypertrophy
# stimulus for an identifiable prime mover.
#
# NONE of these thirty templates appears in this account's 327 synced workouts. They are
# curated so that the first time one IS performed it lands in per-muscle volume, instead of
# silently contributing nothing until somebody notices months later.
CURATED_BY_TEMPLATE_ID: Mapping[str, tuple[tuple[CanonicalMuscleGroup, MuscleRole], ...]] = (
    MappingProxyType(
        {
            # -- Olympic pulls and their derivatives. Triple extension: the posterior chain
            # drives the bar and the traps finish it. The arms are connectors, not movers.
            # "Clean (Barbell)"
            "ABB00838": _curate(
                direct=(_M.QUADS, _M.GLUTES, _M.HAMSTRINGS, _M.TRAPS),
                indirect=(_M.LOWER_BACK, _M.UPPER_BACK, _M.FOREARMS),
            ),
            # "Clean Pull (Barbell)" -- the pull without the catch, so no front-rack squat.
            "652FEA39": _curate(
                direct=(_M.HAMSTRINGS, _M.GLUTES, _M.TRAPS),
                indirect=(_M.QUADS, _M.LOWER_BACK, _M.UPPER_BACK, _M.FOREARMS),
            ),
            # "Clean and Jerk (Barbell)"
            "9E09CEC3": _curate(
                direct=(_M.QUADS, _M.GLUTES, _M.HAMSTRINGS, _M.TRAPS, _M.FRONT_DELTS),
                indirect=(_M.SIDE_DELTS, _M.TRICEPS, _M.LOWER_BACK, _M.UPPER_BACK),
            ),
            # "Clean and Press (Barbell)"
            "D3095577": _curate(
                direct=(_M.QUADS, _M.GLUTES, _M.HAMSTRINGS, _M.TRAPS, _M.FRONT_DELTS),
                indirect=(_M.SIDE_DELTS, _M.TRICEPS, _M.LOWER_BACK, _M.UPPER_BACK),
            ),
            # "Deadlift High Pull (Barbell)" -- hinge into an upright row, so the upper back
            # and traps take the top half rather than the delts.
            "FA5D0DE1": _curate(
                direct=(_M.HAMSTRINGS, _M.GLUTES, _M.TRAPS, _M.UPPER_BACK),
                indirect=(_M.QUADS, _M.LOWER_BACK, _M.SIDE_DELTS, _M.FOREARMS),
            ),
            # "Dumbbell Snatch"
            "F3717B0E": _curate(
                direct=(_M.HAMSTRINGS, _M.GLUTES, _M.TRAPS, _M.FRONT_DELTS),
                indirect=(_M.QUADS, _M.SIDE_DELTS, _M.LOWER_BACK, _M.FOREARMS),
            ),
            # "Hang Clean (Barbell)" -- from the hang, so less knee drive than a full clean.
            "BD4E7E53": _curate(
                direct=(_M.HAMSTRINGS, _M.GLUTES, _M.TRAPS),
                indirect=(_M.QUADS, _M.UPPER_BACK, _M.LOWER_BACK, _M.FOREARMS),
            ),
            # "Hang Snatch (Barbell)"
            "F4E77594": _curate(
                direct=(_M.HAMSTRINGS, _M.GLUTES, _M.TRAPS, _M.FRONT_DELTS),
                indirect=(_M.QUADS, _M.UPPER_BACK, _M.SIDE_DELTS, _M.FOREARMS),
            ),
            # "Jump Shrug (Barbell)" -- a shrug that happens to leave the floor. The traps
            # are the only muscle taking meaningful working volume.
            "BA3DE542": _curate(
                direct=(_M.TRAPS,),
                indirect=(_M.QUADS, _M.GLUTES, _M.HAMSTRINGS, _M.CALVES, _M.FOREARMS),
            ),
            # "Power Clean (Barbell)"
            "C628D768": _curate(
                direct=(_M.QUADS, _M.GLUTES, _M.HAMSTRINGS, _M.TRAPS),
                indirect=(_M.LOWER_BACK, _M.UPPER_BACK, _M.FOREARMS),
            ),
            # "Power Snatch (Barbell)"
            "E22F9358": _curate(
                direct=(_M.QUADS, _M.GLUTES, _M.HAMSTRINGS, _M.TRAPS, _M.FRONT_DELTS),
                indirect=(_M.SIDE_DELTS, _M.UPPER_BACK, _M.LOWER_BACK, _M.FOREARMS),
            ),
            # "Snatch (Barbell)"
            "FB09C938": _curate(
                direct=(_M.QUADS, _M.GLUTES, _M.HAMSTRINGS, _M.TRAPS, _M.FRONT_DELTS),
                indirect=(_M.SIDE_DELTS, _M.UPPER_BACK, _M.LOWER_BACK, _M.FOREARMS),
            ),
            # -- Overhead and jerk work. The overhead lockout is the limiting element, so
            # the shoulder is direct even where the legs supply the drive.
            # "Split Jerk (Barbell)"
            "E764B907": _curate(
                direct=(_M.FRONT_DELTS, _M.TRICEPS, _M.QUADS, _M.GLUTES),
                indirect=(_M.SIDE_DELTS, _M.TRAPS, _M.ABS),
            ),
            # "Press Under (Barbell)" -- a snatch/jerk drill: press yourself under the bar.
            # Catalogued as full_body, but the work is an overhead press against bodyweight.
            "84A77566": _curate(
                direct=(_M.FRONT_DELTS, _M.TRICEPS),
                indirect=(_M.SIDE_DELTS, _M.TRAPS, _M.QUADS),
            ),
            # "Overhead Squat (Barbell)" -- the delts hold the bar, they do not move it, so
            # the squat is direct and the shoulder is not.
            "2CFED196": _curate(
                direct=(_M.QUADS, _M.GLUTES),
                indirect=(
                    _M.HAMSTRINGS,
                    _M.FRONT_DELTS,
                    _M.SIDE_DELTS,
                    _M.UPPER_BACK,
                    _M.ABS,
                ),
            ),
            # "Thruster (Barbell)" -- front squat into a push press: two prime movers, one rep.
            "90E506D5": _curate(
                direct=(_M.QUADS, _M.GLUTES, _M.FRONT_DELTS),
                indirect=(_M.TRICEPS, _M.SIDE_DELTS, _M.ABS),
            ),
            # "Thruster (Kettlebell)"
            "10313AFD": _curate(
                direct=(_M.QUADS, _M.GLUTES, _M.FRONT_DELTS),
                indirect=(_M.TRICEPS, _M.SIDE_DELTS, _M.ABS),
            ),
            # "Wall Ball" -- the same squat-to-press as a thruster with a lighter implement.
            # Kept (unlike the ball slam below) because the catch loads a real eccentric.
            "A1F47ACC": _curate(
                direct=(_M.QUADS, _M.GLUTES, _M.FRONT_DELTS),
                indirect=(_M.TRICEPS, _M.SIDE_DELTS, _M.ABS),
            ),
            # "Landmine Squat and Press (Barbell)"
            "983274DD": _curate(
                direct=(_M.QUADS, _M.GLUTES, _M.FRONT_DELTS),
                indirect=(_M.TRICEPS, _M.SIDE_DELTS, _M.ABS),
            ),
            # -- Kettlebell hinge and get-up work.
            # "Kettlebell Swing" -- a hip hinge, NOT a squat and NOT a front raise. The bell
            # travelling to shoulder height is momentum, so the delts are incidental.
            "F8A0FCCA": _curate(
                direct=(_M.GLUTES, _M.HAMSTRINGS),
                indirect=(_M.LOWER_BACK, _M.ABS, _M.FOREARMS, _M.FRONT_DELTS),
            ),
            # "Kettlebell Clean"
            "F99C211D": _curate(
                direct=(_M.HAMSTRINGS, _M.GLUTES, _M.TRAPS),
                indirect=(_M.FRONT_DELTS, _M.LOWER_BACK, _M.FOREARMS),
            ),
            # "Kettlebell Snatch"
            "89304423": _curate(
                direct=(_M.HAMSTRINGS, _M.GLUTES, _M.TRAPS, _M.FRONT_DELTS),
                indirect=(_M.SIDE_DELTS, _M.LOWER_BACK, _M.FOREARMS),
            ),
            # "Kettlebell Turkish Get Up" -- genuinely whole-body, but the load only ever
            # rests on an overhead shoulder and a braced trunk; the legs reposition it.
            "5F8903BF": _curate(
                direct=(_M.FRONT_DELTS, _M.ABS, _M.OBLIQUES),
                indirect=(_M.SIDE_DELTS, _M.TRICEPS, _M.GLUTES, _M.QUADS),
            ),
            # -- Loaded carries. The grip and the shoulder girdle hold the weight; the legs
            # only transport it, which is why they are indirect on a walk and not a squat.
            # "Farmers Walk"
            "50C613D0": _curate(
                direct=(_M.FOREARMS, _M.TRAPS),
                indirect=(_M.ABS, _M.OBLIQUES, _M.GLUTES, _M.UPPER_BACK),
            ),
            # "Suitcase Carry (Dumbbell)" -- one-sided, so the obliques resist lateral
            # flexion the whole way. That anti-flexion work is the point of the exercise.
            "7593855D": _curate(
                direct=(_M.FOREARMS, _M.OBLIQUES),
                indirect=(_M.TRAPS, _M.ABS, _M.GLUTES),
            ),
            # -- Bodyweight strength holds. Isometric, but loaded to failure like any set.
            # "Front Lever Hold" -- straight-arm lat work against an anti-extension brace.
            "0E608350": _curate(
                direct=(_M.LATS, _M.ABS),
                indirect=(_M.UPPER_BACK, _M.OBLIQUES),
            ),
            # "Front Lever Raise"
            "30F03BF0": _curate(
                direct=(_M.LATS, _M.ABS),
                indirect=(_M.UPPER_BACK, _M.OBLIQUES),
            ),
            # "Handstand Hold" -- overhead support, so front and side heads both hold it.
            "BE3615CF": _curate(
                direct=(_M.FRONT_DELTS, _M.SIDE_DELTS),
                indirect=(_M.TRICEPS, _M.TRAPS, _M.ABS),
            ),
            # "Muscle Up" -- a pull-up and a dip in one rep, which is why chest and triceps
            # are direct here and on no other pulling movement.
            "9F9C164B": _curate(
                direct=(_M.LATS, _M.BICEPS, _M.TRICEPS, _M.CHEST),
                indirect=(_M.UPPER_BACK, _M.FRONT_DELTS, _M.ABS, _M.FOREARMS),
            ),
            # -- Machine combination movement.
            # "Squat Row" -- compositional name: a squat and a row, both loaded.
            "A8814C06": _curate(
                direct=(_M.QUADS, _M.GLUTES, _M.UPPER_BACK, _M.LATS),
                indirect=(_M.BICEPS, _M.FOREARMS),
            ),
        }
    )
)

# Templates that resolve to NOTHING on purpose (D-03, RESEARCH Open Question 5). Recorded
# explicitly so that "unmapped" splits cleanly into "not curated yet" (a gap to close) and
# "correctly excluded" (the end state). Phase 4 excludes both from per-muscle volume; only
# this set is expected to still be listed by `mapping-gaps`.
#
# `full_body` is NOT fanned out to all 19 groups: that would silently inflate every
# per-muscle volume figure in Phase 4 with work that trained no specific muscle.
#
# Three reasons appear here, and only these three:
#   * cardio / conditioning -- no discrete prime mover, or no eccentric to create one
#     (sled work and ball slams are concentric-only by construction)
#   * mobility, warm-up or class work -- not a resistance set at all
#   * `neck` -- a real Hevy muscle group that D-01's amended 19-group canonical list
#     deliberately excludes, so there is nothing to map it TO
DELIBERATELY_UNMAPPED: Mapping[str, str] = MappingProxyType(
    {
        # --- cardio (24). Hevy's own `cardio` primary group; no discrete muscle applies.
        "5E0DDACE": "Aerobics -- cardio class, no discrete prime mover",
        "43573BB8": "Air Bike -- cardio machine",
        "084A67CA": "Battle Ropes -- metabolic conditioning, no meaningful eccentric load",
        "A0D8FA1B": "Boxing -- cardio/skill work",
        "E23F1F2B": "Climbing -- cardio/skill work, load varies with route not with sets",
        "D8F7F851": "Cycling -- cardio machine",
        "3303376C": "Elliptical Trainer -- cardio machine",
        "023947AB": "HIIT -- a session format, not an exercise",
        "1C34A172": "Hiking -- cardio",
        "040BA2E3": "Jump Rope -- cardio",
        "7FD2EC3E": "Recumbent Bike -- cardio machine",
        "0222DB42": "Rowing Machine -- cardio machine",
        "AC1BB830": "Running -- cardio",
        "24A809EF": "Skating -- cardio",
        "5D99A2FA": "Ski Erg -- cardio machine",
        "84325755": "Skiing -- cardio",
        "911A58D3": "Snowboarding -- cardio",
        "213AB238": "Spinning -- cardio class",
        "9283BABA": "Sprints -- cardio",
        "4377A52B": "Stair Machine (Floors) -- cardio machine",
        "4377A52C": "Stair Machine (Steps) -- cardio machine",
        "B60A678F": "Swimming -- cardio",
        "243710DE": "Treadmill -- cardio machine",
        "33EDD7DB": "Walking -- cardio",
        # --- full_body conditioning and mobility (15).
        "F51D9080": "Ball Slams -- explosive conditioning; the ball is released, so no eccentric",
        "B3B1D947": "Bear Crawl -- locomotion conditioning",
        "BB792A36": "Burpee -- bodyweight conditioning",
        "115CC72C": "Burpee Broad Jumps -- bodyweight conditioning",
        "86B00DDE": "Burpee Over the Bar -- bodyweight conditioning",
        "7DA843A3": "Downward Dog -- mobility/yoga position",
        "C9CCB878": "High Knee Skips -- running drill",
        "150E076B": "High Knees -- running drill",
        "991833C2": "Jumping Jack -- conditioning/warm-up",
        "F49E31D6": "Mountain Climber -- conditioning",
        "EC2510CD": "Pilates -- class format, not a loaded set",
        "7D1BD41D": "Sled Pull -- concentric-only; drag direction changes the prime mover",
        "7757171F": "Sled Push -- concentric-only conditioning, no eccentric to accumulate",
        "79EF4E4F": "Warm Up -- a placeholder entry, not an exercise",
        "8C9D2928": "Yoga -- class format, not a loaded set",
        # --- neck (4). Outside the canonical 19 by D-01, so unmappable BY DESIGN.
        "22FEDCA4": "Lying Neck Curls -- `neck` is outside D-01's canonical 19 groups",
        "31B8DA0F": "Lying Neck Curls (Weighted) -- `neck` is outside D-01's canonical 19 groups",
        "0910BD28": "Lying Neck Extension -- `neck` is outside D-01's canonical 19 groups",
        "D6A73CF2": (
            "Lying Neck Extension (Weighted) -- `neck` is outside D-01's canonical 19 groups"
        ),
        # --- other (1).
        "527DA061": "Stretching -- mobility work, no resistance",
    }
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
