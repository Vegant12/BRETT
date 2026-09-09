---
phase: 16-physique-data-model-repository
plan: 01
subsystem: db-models
tags: [sqlalchemy, physique, check-constraint, schema]
dependency-graph:
  requires: []
  provides:
    - PhysiqueObservation SQLAlchemy model
    - PhysiqueRating SQLAlchemy model
    - PHYSIQUE_RATING_LEVELS / PHYSIQUE_RATING_ANCHORS / PHYSIQUE_MIN_ELAPSED_DAYS / PHYSIQUE_DIFF_MIN_LEVEL_DELTA constants
    - PhysiqueRatingLevel / PoseState / PhotoAngle StrEnums
  affects:
    - backend/app/db/models/__init__.py (model registry)
    - backend/tests/test_db_models.py (fast-suite metadata guards)
    - scripts/verify-restore.sql (restore-drill digest coverage)
tech-stack:
  added: []
  patterns:
    - "String + named CHECK constraint for bounded vocabularies, never native PostgreSQL ENUM (first use of CheckConstraint in this codebase)"
key-files:
  created:
    - backend/app/db/models/physique.py
  modified:
    - backend/app/db/models/__init__.py
    - backend/tests/test_db_models.py
    - scripts/verify-restore.sql
decisions:
  - "Reworded the module docstring's 'No relationship() is declared' prose to 'No ORM relationship mapping is declared' to avoid the docstring itself tripping the acceptance criterion's literal grep -c 'relationship(' == 0 check"
  - "Kept all 7 physique-prefixed test functions specified verbatim in the plan's action block, even though one acceptance-criteria line said 'exactly 6' -- the action section's own code enumerates 7 distinct behaviors (levels, anchors, note caps, observed_on date type, CHECK names, unique key, supersede FK ondelete) and removing any one would drop required coverage"
metrics:
  duration: 25 min
  completed: 2026-09-09
---

# Phase 16 Plan 01: Physique Data Model Summary

SQLAlchemy models for `physique_observations` (header) and `physique_ratings` (child, one row
per `(observation, muscle_group)`), with the Phase 15 spike's rating constants copied verbatim
and every bounded vocabulary column backed by `String` + a named `CHECK` constraint rather than
a native PostgreSQL `ENUM`.

## What Was Built

- **`backend/app/db/models/physique.py`** (new): `PhysiqueObservation` and `PhysiqueRating`
  models, `PhysiqueRatingLevel`/`PoseState`/`PhotoAngle` `StrEnum`s, and the four Phase 15
  constants (`PHYSIQUE_RATING_LEVELS`, `PHYSIQUE_RATING_ANCHORS`, `PHYSIQUE_MIN_ELAPSED_DAYS`,
  `PHYSIQUE_DIFF_MIN_LEVEL_DELTA`).
- **`backend/app/db/models/__init__.py`**: registered both new models so
  `migrations/env.py`'s autogenerate/`alembic check` sees them.
- **`backend/tests/test_db_models.py`**: extended the exact-equality table-set guard to 14
  tables, extended the no-relationships and tenant-scoping guards, and added 7 new
  `physique`-selectable unit tests.
- **`scripts/verify-restore.sql`** (deviation, see below): added digest arms for the two new
  tables so the restore-drill coverage guard stays green.

## Final Column List

**`physique_observations`** (14 columns): `id`, `user_id`, `observed_on`, `leanness_notes`,
`conditioning_notes`, `symmetry_notes`, `photo_angles_present`, `pose_state`, `conditions_note`,
`superseded_at`, `superseded_reason`, `superseded_by_id`, `created_at`, `updated_at`.

**`physique_ratings`** (7 columns): `id`, `observation_id`, `muscle_group`, `rating_level`,
`not_assessable_reason`, `created_at`, `updated_at`.

Both match the plan's success-criteria column lists exactly. No column was added, dropped, or
renamed relative to the plan's `<action>` specification.

## Resolved CHECK Constraint Names

- `ck_physique_observations_valid_pose_state`
- `ck_physique_observations_valid_photo_angles`
- `ck_physique_ratings_valid_rating_level`
- `ck_physique_ratings_rating_xor_not_assessable`

All four verified live via the plan's automated verification script and pinned by
`test_physique_vocabularies_are_check_constrained_not_native_enums`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Docstring wording tripped its own acceptance-criteria grep**
- **Found during:** Task 1 verification
- **Issue:** The module docstring's prose "No `relationship()` is declared anywhere on either
  model" literally contained the substring `relationship(`, which the acceptance criterion
  `grep -c "relationship(" backend/app/db/models/physique.py` returns 0` checks for. The
  docstring text and the code-shape guard were in direct conflict.
- **Fix:** Reworded to "No ORM `relationship` mapping is declared anywhere on either model" —
  identical meaning, no literal `relationship(` substring.
- **Files modified:** `backend/app/db/models/physique.py`
- **Commit:** `3566cbc`

**2. [Rule 3 - Blocking issue] `verify-restore.sql` drift guard failed on the new tables**
- **Found during:** Task 2's full fast-suite run
- **Issue:** `test_verify_restore_sql.py::test_the_digest_query_covers_every_mapped_table`
  asserts every table in `Base.metadata` appears exactly once as a `FROM` target in
  `scripts/verify-restore.sql`. Adding `physique_observations`/`physique_ratings` to
  `Base.metadata` (this plan's own change) made that assertion fail — a pre-existing guard
  directly triggered by this plan's schema addition, not a pre-existing unrelated failure.
- **Fix:** Added matching `UNION ALL` arms for both new tables, in the same
  `md5(string_agg(md5(x::text), ',' ORDER BY x.id))` shape as every existing arm.
- **Files modified:** `scripts/verify-restore.sql`
- **Commit:** `7859eb4`

### Acceptance-Criteria Discrepancy (documented, not auto-fixed)

Task 2's acceptance criteria include `grep -c "def test_physique_" ... returns exactly 6`, but
the same task's `<action>` section explicitly specifies 7 distinct test functions (each with
full code to copy verbatim), covering 7 distinct behaviors named in the task's own `<behavior>`
list. All 7 were implemented as specified; `pytest -k physique` collects 7 (satisfies the plan's
separate "at least 6" verification-step wording). Flagging this loudly per the plan's own output
instructions, since it is the kind of literal-count mismatch that instruction says to call out.

No other deviation. Migration `0007` (Plan 02) can byte-match every column/type/constraint
declared here without reinterpretation.

## Known Stubs

None. No hardcoded empty values, placeholder text, or unwired data paths — this plan is schema
only, with no read/write surface yet (Phase 17).

## Verification Evidence

- `uv run pytest -m "not integration" -q` → 659 passed, 11 skipped, 446 deselected
- `uv run pytest backend/tests/test_db_models.py -k physique -q` → 7 passed
- `uv run pytest backend/tests/test_db_models.py -k credential -q` → 1 passed
- `uv run ruff check backend/app/db/models/physique.py backend/app/db/models/__init__.py backend/tests/test_db_models.py` → All checks passed
- `uv run mypy backend/app/db/models/physique.py` → Success: no issues found
- `grep -ri "sa.Enum\|postgresql.ENUM" backend/app/db/models/physique.py` → no matches

## Self-Check: PASSED

- FOUND: `backend/app/db/models/physique.py`
- FOUND: `backend/app/db/models/__init__.py` (modified)
- FOUND: `backend/tests/test_db_models.py` (modified)
- FOUND: `scripts/verify-restore.sql` (modified)
- FOUND commit `3566cbc` (feat(16-01): create PhysiqueObservation/PhysiqueRating models)
- FOUND commit `7859eb4` (feat(16-01): register physique models and extend fast-suite guards)
