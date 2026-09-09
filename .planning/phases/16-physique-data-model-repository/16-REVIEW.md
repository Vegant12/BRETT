---
phase: 16-physique-data-model-repository
reviewed: 2026-09-09T00:00:00Z
depth: standard
files_reviewed: 10
files_reviewed_list:
  - backend/app/db/models/__init__.py
  - backend/app/db/models/physique.py
  - backend/app/db/repositories/physique.py
  - backend/migrations/versions/0007_physique_observations.py
  - backend/tests/conftest.py
  - backend/tests/test_db_models.py
  - backend/tests/test_db_physique.py
  - backend/tests/test_deploy_script_preflight.py
  - backend/tests/test_migration_preflight.py
  - scripts/verify-restore.sql
findings:
  critical: 0
  warning: 2
  info: 3
  total: 5
status: issues_found
---

# Phase 16: Code Review Report

**Reviewed:** 2026-09-09T00:00:00Z
**Depth:** standard
**Files Reviewed:** 10
**Status:** issues_found

## Summary

Reviewed the PHYS-01..PHYS-05 data model, migration, and repository added in Phase 16, plus the
supporting test/fixture/deploy-script changes that ride along with it. The schema design is
careful and well-reasoned: the "String + named CHECK, never a native enum" rule is applied
consistently and tested at both the `Base.metadata` layer and the live-schema layer, the
D-07/D-08 "exactly 19 rows, level XOR reason" invariant is enforced by both a Python
pre-validation pass and database constraints, tenant scoping follows the ASVS V4 convention used
elsewhere in the repo, and the `superseded_by_id` self-reference correctly uses `SET NULL`
instead of the CASCADE every other FK in the schema uses. No SQL injection, hardcoded secrets, or
other security issues were found; `scripts/verify-restore.sql` was updated correctly for the two
new tables.

Two issues are worth fixing before this ships further: the repository's read path can silently
under-report an observation's ratings instead of failing loudly if a row is ever missing (which
the module's own docstrings say should never happen but doesn't defend against), and the write
path validates the length of only one of five free-text/array fields before issuing any SQL,
which is inconsistent with the stated rationale for that one validation. Neither is currently
reachable given the write path always inserts a complete, well-formed row, but both are latent
correctness risks for the Phase 17 work that will build on this module (supersede writes, edits).

## Warnings

### WR-01: `_read_observation` silently drops missing rating rows instead of failing loudly

**File:** `backend/app/db/repositories/physique.py:229-237`
**Issue:** `PhysiqueObservationRecord.ratings`'s own docstring (lines 67-71) states the tuple is
"always length 19, ordered by `CanonicalMuscleGroup` declaration order, so a caller can zip it
against the enum without sorting." The read path does not enforce that: it filters out any group
that fails to appear in `by_group` (`if group.value in by_group`) rather than raising when a
row is unexpectedly missing.

Today the write path (`_validate_rating_coverage`) guarantees all 19 rows exist at write time, so
this is unreachable in the current code. But `physique_ratings` rows have no protection against
being deleted independently of their parent by a future migration, a manual `DELETE`, or a Phase
17 write bug — and when that happens this function will return a *shorter, silently
misaligned* tuple instead of raising, defeating the exact "zip against the enum" guarantee the
docstring promises to callers (index `i` would no longer correspond to `CanonicalMuscleGroup`
member `i`). A caller that trusts the documented invariant would get quietly wrong data instead
of an exception naming the corrupted observation.

**Fix:**
```python
missing = [group for group in CanonicalMuscleGroup if group.value not in by_group]
if missing:
    raise RuntimeError(
        f"physique_observation {observation_id} is missing rating rows for: "
        f"{sorted(group.value for group in missing)}"
    )

entries = tuple(
    RatingEntry(
        muscle_group=group,
        rating_level=_rating_level(by_group[group.value].rating_level),
        not_assessable_reason=by_group[group.value].not_assessable_reason,
    )
    for group in CanonicalMuscleGroup
)
```

### WR-02: Only `not_assessable_reason` is length-validated before any SQL; four other fields are not

**File:** `backend/app/db/repositories/physique.py:122-167`
**Issue:** The module comment at lines 47-49 explains why `not_assessable_reason` is
length-checked in Python: "refused here rather than left for asyncpg to truncate mid-transaction,
aborting the session on a write that started clean." The exact same risk applies to
`leanness_notes` (cap 500), `conditioning_notes` (cap 500), `symmetry_notes` (cap 500), and
`conditions_note` (cap 200) — all accepted as unchecked `str | None` parameters at lines 142-145
— and to `photo_angles_present`, which is accepted as a bare `Sequence[str]` (line 141) with no
check against the `PhotoAngle` vocabulary before the insert at lines 155-167. An overlong note or
a caller-supplied angle string that isn't `front`/`back`/`side` will not fail with a clear
`ValueError` the way an overlong `not_assessable_reason` does — it will reach the database and
raise a `DBAPIError`/`IntegrityError` on the header insert, aborting the session for a write path
that documents itself as validating problems "before any statement is issued" (line 149-151).
This is an inconsistency in the module's own stated design principle, not just a style nit: a
caller integrating against this module (Phase 17) will reasonably expect the same clean-`ValueError`
behavior for every field, based on the precedent set by `not_assessable_reason`.

**Fix:** Add the same style of pre-check for the other free-text fields and validate
`photo_angles_present` against `PhotoAngle`, e.g.:
```python
_FIELD_MAX_LENGTHS = {
    "leanness_notes": 500,
    "conditioning_notes": 500,
    "symmetry_notes": 500,
    "conditions_note": 200,
}

def _validate_field_lengths(**fields: str | None) -> None:
    for name, value in fields.items():
        if value is not None and len(value) > _FIELD_MAX_LENGTHS[name]:
            raise ValueError(f"{name} exceeds {_FIELD_MAX_LENGTHS[name]} characters")

def _validate_photo_angles(angles: Sequence[str]) -> None:
    allowed = {angle.value for angle in PhotoAngle}
    bad = sorted(set(angles) - allowed)
    if bad:
        raise ValueError(f"photo_angles_present contains unsupported angle(s): {bad}")
```
called at the top of `create_observation`, alongside `_validate_rating_coverage`.

## Info

### IN-01: `photo_angles_present` is typed `Sequence[str]` rather than `Sequence[PhotoAngle]`

**File:** `backend/app/db/repositories/physique.py:141`
**Issue:** `pose_state` is accepted as the typed `PoseState` enum, giving static type-checking at
call sites, but the sibling `photo_angles_present` parameter accepts any `str`, losing the same
protection `PhotoAngle` (defined in `app/db/models/physique.py:90-100`) exists to provide.
**Fix:** `photo_angles_present: Sequence[PhotoAngle] = ()`, converting to `.value` at the insert
site (`[angle.value for angle in photo_angles_present]`), consistent with how `pose_state.value`
is handled.

### IN-02: The `<@` containment CHECK does not reject duplicate angle values

**File:** `backend/app/db/models/physique.py:155-158`, `backend/migrations/versions/0007_physique_observations.py:84-87`
**Issue:** `photo_angles_present <@ ARRAY['front','back','side']::varchar(16)[]` accepts
`['front','front']` since containment doesn't consider multiplicity. Not currently exploitable
(nothing reads angle counts), but worth a note since IN-01's fix would be a natural place to also
reject duplicates.
**Fix:** If desired, add a Python-side check (`len(set(angles)) == len(angles)`) alongside IN-01's
vocabulary check; not worth a DDL change for a cosmetic array-payload field.

### IN-03: No guard against a self-referential `superseded_by_id` loop

**File:** `backend/app/db/models/physique.py:138-142`, `backend/migrations/versions/0007_physique_observations.py:96-101`
**Issue:** `superseded_by_id` self-references `physique_observations.id` with no CHECK or
application guard preventing `id == superseded_by_id`. Nothing in Phase 16 writes this column
(D-01/PHYS-08 is Phase 17's), so this is purely a forward-looking note for whoever implements the
supersede write path.
**Fix:** When Phase 17 adds the write logic, consider `CheckConstraint("id != superseded_by_id", ...)`
or an application-level check in the write function, whichever fits that phase's design better.

---

_Reviewed: 2026-09-09T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
