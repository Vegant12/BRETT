---
phase: 16-physique-data-model-repository
plan: 03
subsystem: database
tags: [sqlalchemy, postgresql, physique, repository, asyncio]

# Dependency graph
requires:
  - phase: 16-physique-data-model-repository (plan 01/02)
    provides: physique_observations/physique_ratings schema, migration 0007, GoldenBuilder.physique_observation fixture
provides:
  - "backend/app/db/repositories/physique.py: RatingEntry, PhysiqueObservationRecord, create_observation, get_latest_observation"
  - "backend/tests/test_db_physique.py: repository round-trip, completeness-validation and tenant-scoping tests"
affects: [17-physique-analytics-mcp-tools, 18-monthly-report-physique-integration]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Repository never commits; caller owns the transaction (matches programs.py)"
    - "Frozen dataclass composite read-row (RatingEntry/PhysiqueObservationRecord), no relationship()/selectinload -- two explicit queries assembled in Python (matches workouts.py)"
    - "Validate-before-INSERT: _validate_rating_coverage raises ValueError before any statement is issued, so an invalid write leaves zero rows rather than a half-written observation"

key-files:
  created:
    - backend/app/db/repositories/physique.py
  modified:
    - backend/tests/test_db_physique.py

key-decisions:
  - "Reworded two docstring passages the plan specified verbatim, because their literal wording would have failed the plan's own acceptance checks: (1) the module docstring originally said 'No `relationship()` and no `selectinload`', which itself contains the two substrings a later grep guard requires to be absent; reworded to 'No ORM relationship mapping and no eager-loading helper are used anywhere in this module'. (2) the module docstring originally named `abductors`/`adductors` directly, which fails Task 2's own test asserting the source contains neither word; reworded to 'the two hip-stabilizer groups a standard photo set never shows' (PHYS-02 cited instead of the group names). Both preserve the original meaning."

patterns-established:
  - "A physique observation is written and read as one repository call each; Phase 17's MCP write/read tools call create_observation/get_latest_observation directly rather than issuing their own SQL"

requirements-completed: [PHYS-01, PHYS-02, PHYS-03]

duration: 9min
completed: 2026-09-09
---

# Phase 16 Plan 03: Physique Repository Summary

**`app/db/repositories/physique.py` — the sole writer/reader of `physique_observations`/`physique_ratings`, enforcing D-07's 19-row completeness before any INSERT and proving abductors/adductors need no special-casing.**

## Performance

- **Duration:** 9 min
- **Tasks:** 2 completed
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments

- `create_observation` inserts one header row plus exactly 19 rating child rows (one per `CanonicalMuscleGroup`), validated for completeness/no-duplicates/level-XOR-reason/reason-length BEFORE any statement is issued
- `get_latest_observation` reads the newest observation by `observed_on DESC, created_at DESC`, tenant-scoped, returning `None` for a user with no observations
- Both functions proven end-to-end: a full 19-entry observation round-trips through `create_observation` → `get_latest_observation` with every note/confounder field, `pose_state`, `photo_angles_present` and per-group rating intact, in canonical `CanonicalMuscleGroup` order
- Abductors/adductors proven to take the identical `Not Assessable` path as every other omitted group, with the source file itself asserted (via a grep-style read in the test) to contain neither word
- Cross-tenant read isolation proven: a second user's observation is never returned to `DEFAULT_USER_ID`
- Full suite green (1119 passed, 11 skipped); `test_mcp_isolation.py`/`test_mcp_tool_schemas.py` and `test_migrations.py` integration tests unchanged and green, confirming Phase 16 adds no MCP surface

## Public surface (Phase 17 codes against this)

```python
# backend/app/db/repositories/physique.py

@dataclass(frozen=True, slots=True)
class RatingEntry:
    muscle_group: CanonicalMuscleGroup
    rating_level: PhysiqueRatingLevel | None = None
    not_assessable_reason: str | None = None

@dataclass(frozen=True, slots=True)
class PhysiqueObservationRecord:
    id: uuid.UUID
    observed_on: dt.date
    leanness_notes: str | None
    conditioning_notes: str | None
    symmetry_notes: str | None
    photo_angles_present: tuple[str, ...]
    pose_state: PoseState
    conditions_note: str | None
    superseded_at: dt.datetime | None
    superseded_reason: str | None
    superseded_by_id: uuid.UUID | None
    created_at: dt.datetime
    ratings: tuple[RatingEntry, ...]  # always length 19, CanonicalMuscleGroup order

async def create_observation(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    observed_on: dt.date,
    ratings: Sequence[RatingEntry],
    pose_state: PoseState,
    photo_angles_present: Sequence[str] = (),
    leanness_notes: str | None = None,
    conditioning_notes: str | None = None,
    symmetry_notes: str | None = None,
    conditions_note: str | None = None,
) -> PhysiqueObservationRecord: ...

async def get_latest_observation(
    session: AsyncSession, *, user_id: uuid.UUID
) -> PhysiqueObservationRecord | None: ...
```

**Open seam for Phase 17, stated explicitly in `get_latest_observation`'s own docstring:** this function does NOT filter `superseded_at IS NULL`. It returns the newest observation by `observed_on`/`created_at` regardless of supersede state. D-01 pulled the three supersede columns (`superseded_at`, `superseded_reason`, `superseded_by_id`) forward into migration 0007 and onto `PhysiqueObservationRecord`, but nothing in Phase 16 writes them and nothing in Phase 16 filters on them — PHYS-08's supersede semantics belong entirely to Phase 17. The predicate `get_latest_observation` would need to change is named in its own docstring so Phase 17's planner sees the seam rather than discovering it by reading code.

Both functions never call `session.commit()` — the caller owns the transaction, matching `programs.py`'s contract, so Phase 17's MCP write tool can make the commit the last statement it executes.

## Task Commits

1. **Task 1: Create backend/app/db/repositories/physique.py with create_observation and get_latest_observation** - `648ff22` (feat)
2. **Task 2: Append repository round-trip, completeness and tenant-scoping tests to test_db_physique.py** - `ce94c0a` (test)

_Note: this plan was executed by a worktree agent; the orchestrator applies the final `docs({phase}-{plan}): complete` metadata commit and updates STATE.md/ROADMAP.md after merge._

## Files Created/Modified

- `backend/app/db/repositories/physique.py` - `RatingEntry`, `PhysiqueObservationRecord`, `_validate_rating_coverage`, `create_observation`, `_read_observation`, `get_latest_observation`
- `backend/tests/test_db_physique.py` - appended 8 repository-layer integration tests after Plan 02's schema-layer tests, plus a `_full_rating_set` builder and `_repository_source` helper

## Decisions Made

- Reworded two docstring passages the plan specified verbatim, because writing them exactly as given would have failed the plan's own acceptance checks:
  1. The module docstring's "No `relationship()` and no `selectinload`" line contains both literal substrings a later grep guard (`grep -c "selectinload\|relationship(" ... returns 0`) requires to be absent from the file. Reworded to "No ORM relationship mapping and no eager-loading helper are used anywhere in this module" — same meaning, no literal match.
  2. The module docstring's "`abductors`/`adductors` need no special-casing" line directly names the two groups whose absence Task 2's own test (`test_abductors_and_adductors_take_the_not_assessable_path_without_special_casing`) asserts by reading the source file and checking `"abductor" not in source.lower()`. Reworded to "the two hip-stabilizer groups a standard photo set never shows need no special-casing (PHYS-02)" — cites the requirement instead of naming the groups, preserving the point without breaking the guard.
- Extracted the file-read in the abductors/adductors test into a synchronous module-level helper (`_repository_source()`) rather than calling `Path(...).read_text()` directly inside the `async def` test body, to satisfy Ruff's `ASYNC240` (async functions should not use blocking pathlib methods) rather than suppressing it.
- Used small local closures (`_rating_payload` in `create_observation`, `_rating_level` in `_read_observation`) to give mypy a narrowed `str | None` type before conversion, rather than inline conditional expressions indexing the same dict twice — mypy cannot narrow `Optional` across two separate dict lookups on the same key.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Plan-specified docstring text would fail the plan's own acceptance grep and Task 2's own source-scan test**
- **Found during:** Task 1 (writing the module docstring), confirmed while satisfying Task 2's acceptance criteria
- **Issue:** The plan's `<action>` block for Task 1 specified verbatim docstring wording containing "`relationship()`", "`selectinload`", "`abductors`" and "`adductors`" — but the plan's own Task 1 acceptance criteria (`grep -c "selectinload\|relationship(" ... returns 0`) and Task 2's test (asserting the source contains neither "abductor" nor "adductor") require those exact substrings to be absent from the file.
- **Fix:** Reworded both docstring passages to preserve their meaning without the literal substrings (see Decisions Made above).
- **Files modified:** `backend/app/db/repositories/physique.py`
- **Verification:** `grep -c "selectinload\|relationship(" backend/app/db/repositories/physique.py` returns 0; `grep -ci "abductor\|adductor" backend/app/db/repositories/physique.py` returns 0; `test_abductors_and_adductors_take_the_not_assessable_path_without_special_casing` passes.
- **Commit:** `648ff22`

**2. [Rule 3 - Blocking] mypy could not narrow `Optional` types across repeated dict lookups**
- **Found during:** Task 1, running `uv run mypy`
- **Issue:** `by_group[group].rating_level.value if by_group[group].rating_level is not None else None` re-indexes the dict for the narrowing check and the access, so mypy does not treat the second access as narrowed (`union-attr` and `arg-type` errors).
- **Fix:** Introduced small local helper closures (`_rating_payload`, `_rating_level`) that bind the looked-up value to a local variable once, giving mypy a real narrowing point.
- **Files modified:** `backend/app/db/repositories/physique.py`
- **Verification:** `uv run mypy backend/app/db/repositories/physique.py` exits 0.
- **Commit:** `648ff22`

**3. [Rule 3 - Blocking] Ruff `ASYNC240` on a synchronous file read inside an async test**
- **Found during:** Task 2, running `uv run ruff check`
- **Issue:** `Path(__file__)....read_text()` called directly inside `async def test_abductors_and_adductors_...` triggers Ruff's async-blocking-call rule.
- **Fix:** Moved the read into a synchronous module-level helper, `_repository_source()`, called from the test.
- **Files modified:** `backend/tests/test_db_physique.py`
- **Verification:** `uv run ruff check backend/tests/test_db_physique.py` passes with zero errors.
- **Commit:** `ce94c0a`

---

**Total deviations:** 3 auto-fixed (2x Rule 1/bug-in-plan-wording, 1x Rule 3/blocking lint). **Impact on plan:** All three are wording/lint corrections with no change to the module's public surface, behavior, or the plan's stated intent — `create_observation`/`get_latest_observation` implement exactly the signatures, validation order and read shape the plan specified.

## Issues Encountered

None beyond the deviations documented above.

## Known Stubs

None. Both repository functions are fully wired; no placeholder data paths exist.

## Threat Flags

None. This plan introduces no MCP or HTTP surface (`test_mcp_isolation.py`/`test_mcp_tool_schemas.py` unchanged and green) and every statement is a bound-parameter SQLAlchemy Core `insert()`/`select()` — no new trust boundary beyond the two already named in the plan's own threat model (caller → repository, repository → PostgreSQL).

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

`backend/app/db/repositories/physique.py` is ready for Phase 17 to build the MCP write/read tools directly against `create_observation`/`get_latest_observation`, and for Phase 18's monthly report to call `get_latest_observation` (plus whatever prior-observation lookup Phase 17 adds) for the physique section. The one open seam — `get_latest_observation` not filtering superseded rows — is documented in its own docstring and in this summary, so Phase 17's planner sees it as a known, deliberate gap rather than discovering it during implementation.

---
*Phase: 16-physique-data-model-repository*
*Completed: 2026-09-09*

## Self-Check: PASSED

- FOUND: `backend/app/db/repositories/physique.py`
- FOUND: `.planning/phases/16-physique-data-model-repository/16-03-SUMMARY.md`
- FOUND: commit `648ff22` (Task 1)
- FOUND: commit `ce94c0a` (Task 2)
