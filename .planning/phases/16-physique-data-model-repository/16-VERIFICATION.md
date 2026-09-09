---
phase: 16-physique-data-model-repository
verified: 2026-09-09T05:29:55Z
status: passed
score: 5/5 must-haves verified
overrides_applied: 0
---

# Phase 16: Physique Data Model & Repository Verification Report

**Phase Goal:** A physique observation's full shape — ratings, notes, confounder metadata,
not-assessable handling — persists correctly and reads back out cleanly, with no MCP surface yet.
**Verified:** 2026-09-09T05:29:55Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A `PhysiqueObservation` header row plus one `PhysiqueRating` child row per rated `(observation, muscle_group)` can be inserted and read back through `backend/app/db/repositories/physique.py`, keyed on `CanonicalMuscleGroup` with no new taxonomy | ✓ VERIFIED | `create_observation`/`get_latest_observation` implemented in `backend/app/db/repositories/physique.py`; `test_create_observation_round_trips_all_nineteen_ratings` passes live against Postgres — 19 rows round-trip in `CanonicalMuscleGroup` order |
| 2 | Ratings persist as a `String`-backed `StrEnum` guarded by a named `CHECK` constraint — never a native PostgreSQL `ENUM` — verified by `test_migrations_round_trip` passing unchanged | ✓ VERIFIED | `PhysiqueRatingLevel`/`PoseState` are `String`+`CheckConstraint` in both the model and migration 0007; `grep -ci "sa.Enum\|postgresql.ENUM"` returns 0 in both files; `test_migrations_round_trip` and `test_no_pending_model_drift` pass; `test_migration_declares_no_native_enum_type` queries `pg_type` directly and finds none |
| 3 | `Not Assessable` is representable per muscle group with a short reason rather than a forced numeric guess; `abductors`/`adductors` can be recorded this way without special-casing | ✓ VERIFIED | `ck_physique_ratings_rating_xor_not_assessable` DB constraint + `_validate_rating_coverage`'s XOR check; `test_abductors_and_adductors_take_the_not_assessable_path_without_special_casing` proves both groups take the identical code path and greps the repository source for the literal absence of "abductor"/"adductor" |
| 4 | Each observation stores three independently-capped free-text note fields plus confounder metadata (photo angles, pose state, conditions note) as fields separate from the ratings | ✓ VERIFIED | `leanness_notes`/`conditioning_notes`/`symmetry_notes` (500 each), `conditions_note` (200), `photo_angles_present` (ARRAY + `<@` CHECK), `pose_state` (CHECK) all present on `PhysiqueObservation`, independent of `PhysiqueRating` rows; `test_confounder_metadata` and `test_note_field_caps` prove round-trip and independence live against Postgres |
| 5 | Migration `0007` (next after `0006`) applies cleanly and round-trips (up/down) without orphaning a `pg_type` | ✓ VERIFIED | `backend/migrations/versions/0007_physique_observations.py` exists, `down_revision = "0006"`; `test_migrations.py -m integration` (3 tests, includes round-trip and drift check) passes |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/app/db/models/physique.py` | `PhysiqueObservation`/`PhysiqueRating` models, locked constants, StrEnums | ✓ VERIFIED | 221 lines; exact column set matches plan (14/7 columns); all four CHECK constraints resolve to plan-specified names; zero `relationship()`, zero native ENUM |
| `backend/app/db/models/__init__.py` | Registry entry for migrations/env.py | ✓ VERIFIED | `from app.db.models.physique import PhysiqueObservation, PhysiqueRating` present, both names in `__all__` |
| `backend/tests/test_db_models.py` | Fast-suite shape guards | ✓ VERIFIED | 7 `test_physique_*` functions present (plan named 6 in one acceptance line but specified 7 in the action block — documented deviation, not a gap; all 7 pass) |
| `backend/migrations/versions/0007_physique_observations.py` | Hand-written DDL for both tables | ✓ VERIFIED | 174 lines; 2 `create_table`, 4 `CheckConstraint`, 1 `ondelete="SET NULL"`, 2 `drop_table`; matches models byte-for-byte per `alembic check` |
| `backend/tests/test_db_physique.py` | Schema shape + CHECK negative-path + repository round-trip tests | ✓ VERIFIED | 723 lines, 14 tests total (6 schema-layer from Plan 02 + 8 repository-layer from Plan 03); all pass live |
| `backend/tests/conftest.py` | Purge entries + `GoldenBuilder.physique_observation` | ✓ VERIFIED | `physique_ratings` appears before `physique_observations` in `_MCP_PURGE_TABLES` (FK-child-first); `physique_observation` builder method present |
| `backend/app/db/repositories/physique.py` | `create_observation`/`get_latest_observation`, sole writer | ✓ VERIFIED | 284 lines; exports `RatingEntry`, `PhysiqueObservationRecord`, `create_observation`, `get_latest_observation`; zero `session.commit()`, zero `relationship()`/`selectinload` |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `backend/app/db/models/__init__.py` | `backend/app/db/models/physique.py` | model registry import | ✓ WIRED | Import present, both models in `Base.metadata` (14 total tables) |
| `backend/app/db/models/physique.py` | `backend/app/normalization/muscles.py` | `CanonicalMuscleGroup` reused for taxonomy | ✓ WIRED (deliberate deviation) | Model does NOT import `CanonicalMuscleGroup` (would be unused/F401) — validation happens in the repository layer instead, matching `ExerciseMuscle`'s precedent; the repository (`backend/app/db/repositories/physique.py`) does import and use it for the 19-row completeness check |
| `backend/migrations/versions/0007_physique_observations.py` | `backend/app/db/models/physique.py` | byte-matching DDL, `alembic check` | ✓ WIRED | `test_no_pending_model_drift` passes — zero drift |
| `backend/tests/conftest.py` | `physique_ratings`/`physique_observations` | `_MCP_PURGE_TABLES` | ✓ WIRED | Verified FK-child-first ordering |
| `backend/app/db/repositories/physique.py` | `backend/app/db/models/physique.py` | insert/select | ✓ WIRED | Direct imports and use in `create_observation`/`_read_observation` |
| `backend/app/db/repositories/physique.py` | `backend/app/normalization/muscles.py` | `CanonicalMuscleGroup` drives completeness check | ✓ WIRED | `for group in CanonicalMuscleGroup` used in both write and read paths |
| `backend/tests/test_db_physique.py` | `backend/app/db/repositories/physique.py` | round-trip assertions | ✓ WIRED | Imports `create_observation`, `get_latest_observation`, `RatingEntry`, `PhysiqueObservationRecord` and exercises them live |

Note on the second key link: the PLAN's key_links description ("CanonicalMuscleGroup reused as
the muscle vocabulary... pattern: `from app\.normalization\.muscles import CanonicalMuscleGroup`")
does not literally match `physique.py` (the model), which deliberately omits this import per its
own code comment (avoiding an unused-import lint failure). The connection is real but lives one
layer up, in the repository module Plan 03 built. This is a wiring-location deviation, not a
missing link — the taxonomy is genuinely reused with no new enum, and the repository's grep-count
acceptance criteria (`for group in CanonicalMuscleGroup` at least 2) are satisfied.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Fast suite green | `uv run pytest -m "not integration" -q` | 670 passed | ✓ PASS |
| Full suite green (incl. integration) | `uv run pytest -q` | 1130 passed | ✓ PASS |
| Physique integration tests | `uv run pytest backend/tests/test_db_physique.py -m integration -q` | 14 passed | ✓ PASS |
| Migration round-trip + drift check | `uv run pytest backend/tests/test_migrations.py -m integration -q` | 3 passed | ✓ PASS |
| MCP isolation unchanged (no MCP surface added) | `uv run pytest backend/tests/test_mcp_isolation.py backend/tests/test_mcp_tool_schemas.py -q` | 21 passed | ✓ PASS |
| Lint clean | `uv run ruff check` (all phase-16 files) | All checks passed | ✓ PASS |
| Type-check clean | `uv run mypy backend/app/db/models/physique.py backend/app/db/repositories/physique.py` | Success: no issues found | ✓ PASS |
| No native ENUM anywhere | `grep -ci "sa.Enum\|postgresql.ENUM"` on model + migration | 0 matches both files | ✓ PASS |
| `_WRITE_ALLOWLIST` untouched | `grep -n "_WRITE_ALLOWLIST ="` in `test_mcp_isolation.py` | `frozenset({"program_switch.py"})` | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|--------------|--------|----------|
| PHYS-01 | 16-01, 16-02, 16-03 | Five-level ordinal scale, verbatim-travelling anchor constant, level 5 self-relative | ✓ SATISFIED | `PHYSIQUE_RATING_LEVELS`/`PHYSIQUE_RATING_ANCHORS` byte-identical to spike; `test_physique_rating_levels_are_the_five_spike_confirmed_values`, `test_physique_rating_anchors_travel_verbatim` pass |
| PHYS-02 | 16-01, 16-02, 16-03 | `Not Assessable` as first-class value with reason; abductors/adductors no special-casing | ✓ SATISFIED | `ck_physique_ratings_rating_xor_not_assessable` + `_validate_rating_coverage`; `test_not_assessable_xor_rating`, `test_abductors_and_adductors_take_the_not_assessable_path_without_special_casing` pass |
| PHYS-03 | 16-01, 16-02, 16-03 | Header + child row shape keyed on `CanonicalMuscleGroup`; `String`+CHECK never native ENUM | ✓ SATISFIED | Both models/migration confirmed; `test_migration_declares_no_native_enum_type`, `test_no_pending_model_drift` pass |
| PHYS-04 | 16-01, 16-02 | Three separately-capped qualitative note fields, no numeric body-fat estimate | ✓ SATISFIED | `leanness_notes`/`conditioning_notes`/`symmetry_notes` at 500 chars each, `String` type (no numeric column); `test_note_field_caps`, `test_physique_note_field_caps_are_not_transposed` pass |
| PHYS-05 | 16-01, 16-02 | Confounder metadata independent of ratings: photo angles, pose state, conditions note | ✓ SATISFIED | `photo_angles_present`/`pose_state`/`conditions_note` columns on the header, structurally separate from `PhysiqueRating` rows; `test_confounder_metadata` proves independence live |

No orphaned requirements: REQUIREMENTS.md maps only PHYS-01 through PHYS-05 to Phase 16, and all five appear in at least one plan's `requirements` frontmatter.

### Anti-Patterns Found

None. No `TODO`/`FIXME`/`PLACEHOLDER` comments, no stub returns, no hardcoded empty data paths in any of the phase's created/modified files. Both summary files' "Known Stubs: None" claims were independently verified by grep.

### Human Verification Required

None. All behaviors in this phase are database-schema and repository-layer facts, fully provable by automated tests (unit + integration against real PostgreSQL). No UI, no visual, no external service, no MCP surface exists yet to require human judgment.

### Gaps Summary

No gaps. All five ROADMAP success criteria verified against live code and a real Postgres
database (not mocked). Full test suite (1130 tests) green, including 14 new physique-specific
integration tests exercising every CHECK constraint's negative path, the 19-row completeness
invariant, tenant scoping, and the abductors/adductors no-special-casing claim as a grep-provable
fact rather than an assertion. The MCP write-allowlist guard confirms no MCP surface was
introduced, matching the phase goal's explicit "with no MCP surface yet" clause. Two minor,
explicitly-documented deviations in the summaries (docstring rewording to avoid self-tripping
acceptance-criteria greps, and a 6-vs-7 test-count acceptance-criteria mismatch resolved in favor
of full behavioral coverage) do not affect goal achievement — both are honestly disclosed and
verified harmless.

---

_Verified: 2026-09-09T05:29:55Z_
_Verifier: Claude (gsd-verifier)_
