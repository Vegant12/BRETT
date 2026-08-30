"""Guards on the curated data itself (D-02: curation is code, so it gets tests).

These are cheap invariants that catch the realistic mistakes: a key that will never be hit
because it was not normalised, a curated entry that resolves to nothing, and an id that
appears both as "curated" and as "deliberately excluded".
"""

from app.normalization.exercise_map import (
    ABDOMINAL_SPLIT_BY_TITLE,
    CURATED_BY_TEMPLATE_ID,
    DELIBERATELY_UNMAPPED,
    DELTOID_SPLIT_BY_TITLE,
    derive_assignments,
    normalize_title,
)
from app.normalization.muscles import CanonicalMuscleGroup, MuscleRole


def test_curated_template_ids_resolve_to_something() -> None:
    """A curated entry that resolves to nothing is worse than no entry: it silently replaces
    whatever the mechanical translation would have produced."""
    for template_id in CURATED_BY_TEMPLATE_ID:
        assignments = derive_assignments(
            template_id=template_id,
            title="",
            primary_muscle_group=None,
            secondary_muscle_groups=[],
        )
        assert assignments, f"{template_id!r} is curated but resolves to no muscle at all"


def test_curated_and_deliberately_unmapped_are_disjoint() -> None:
    """T-03-56. An id cannot be both "we decided what this trains" and "this trains nothing".

    The contradiction is not theoretical: curating a template and forgetting to delete its
    exclusion entry would leave `mapping-gaps` reporting it as correctly excluded forever,
    while Phase 4 happily counted its volume.
    """
    overlap = set(CURATED_BY_TEMPLATE_ID) & set(DELIBERATELY_UNMAPPED)

    assert overlap == set(), f"template ids classified twice: {sorted(overlap)}"


def test_deliberately_unmapped_entries_carry_a_reason() -> None:
    """A bare 8-character hex id is unreadable a year later.

    `--` separates the title from the reason, so both halves are present by construction.
    """
    for template_id, reason in DELIBERATELY_UNMAPPED.items():
        assert isinstance(reason, str)
        assert reason.strip(), f"{template_id!r} is excluded with an empty reason"
        assert "--" in reason, (
            f"{template_id!r} must be documented as '<title> -- <reason>', got {reason!r}"
        )


def test_curated_roles_are_valid_members() -> None:
    """Values are written by hand, so a typo'd string would otherwise reach the database.

    `exercise_muscles.muscle_group` has no enum constraint -- `resolver._muscle_group` raises
    on a bad value at READ time, which is one whole sync too late.
    """
    for template_id, pairs in CURATED_BY_TEMPLATE_ID.items():
        assert pairs, f"{template_id!r} is curated with an empty assignment set"
        for group, role in pairs:
            assert isinstance(group, CanonicalMuscleGroup), f"{template_id!r}: {group!r}"
            assert isinstance(role, MuscleRole), f"{template_id!r}: {role!r}"


def test_no_curated_entry_duplicates_a_muscle_group() -> None:
    """The same group twice in one entry is counted twice, at two different weights.

    `derive_assignments` deduplicates the DERIVED path but returns a curated entry verbatim,
    so this is the only thing standing between a copy-paste slip and doubled volume.
    """
    for template_id, pairs in CURATED_BY_TEMPLATE_ID.items():
        groups = [group for group, _ in pairs]
        assert len(groups) == len(set(groups)), (
            f"{template_id!r} lists a muscle group more than once: {sorted(groups)}"
        )


def test_deltoid_and_abdominal_keys_stay_normalized() -> None:
    """Re-asserted here because curation adds keys BY HAND, from titles seen in a live sync.

    A key like "Single Arm Lateral Raise (Cable)" is never looked up -- the lookup uses
    `normalize_title` output -- so it is a curated judgement that silently does nothing.
    """
    for table in (DELTOID_SPLIT_BY_TITLE, ABDOMINAL_SPLIT_BY_TITLE):
        for key in table:
            assert normalize_title(key) == key, f"{key!r} will never be looked up"


def test_deltoid_table_still_covers_all_three_heads() -> None:
    """Curation must not collapse the split NORM-01 exists to provide."""
    heads = {group for value in DELTOID_SPLIT_BY_TITLE.values() for group in value}

    assert heads == {
        CanonicalMuscleGroup.FRONT_DELTS,
        CanonicalMuscleGroup.SIDE_DELTS,
        CanonicalMuscleGroup.REAR_DELTS,
    }


def test_title_tables_have_no_duplicate_keys_after_normalisation() -> None:
    """Two raw titles that normalise to the same key would silently shadow each other.

    A dict cannot hold a duplicate, so the collision is invisible in the source: the second
    entry simply overwrites the first and one curated judgement disappears. Re-normalising
    every key and counting is the only way to see it. The empty-string check catches the
    other end of the same mistake -- a key of "(Dumbbell)" normalises to "" and would then
    match every untitled exercise.
    """
    for table in (DELTOID_SPLIT_BY_TITLE, ABDOMINAL_SPLIT_BY_TITLE):
        renormalised = [normalize_title(key) for key in table]

        assert len(set(renormalised)) == len(renormalised)
        assert "" not in renormalised
