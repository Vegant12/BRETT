---
phase: 17-physique-analytics-mcp-read-write-tools
plan: 01
subsystem: database
tags: [sqlalchemy, postgresql, physique, repository]

# Dependency graph
requires:
  - phase: 16-physique-data-model-repository
    provides: PhysiqueObservation/PhysiqueRating models, migration 0007 with supersede columns, single-writer repository (create_observation/get_latest_observation)
provides:
  - PHYSIQUE_RATING_DISCLAIMER constant (PHYS-11), importable from app.db.models.physique
  - get_observation (public, renamed from _read_observation) for tenant-scoped lookup by id
  - get_recent_observations holding the ONE superseded_at IS NULL read predicate
  - get_latest_observation as a limit=1 delegate, now supersede-aware
  - _mark_superseded and create_observation(supersedes_observation_id=, superseded_reason=) — the PHYS-08 supersede write
affects: [17-02, 17-03, 18]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "RETURNING over Result.rowcount for UPDATE row counts (matches normalization/resolver.py::clear_override)"
    - "Supersede-write-after-flush: self-referential FK requires the new row to exist before the old row can point at it"

key-files:
  created: []
  modified:
    - backend/app/db/models/physique.py
    - backend/app/db/repositories/physique.py
    - backend/tests/test_db_physique.py

key-decisions:
  - "Used RETURNING instead of the plan's suggested Result.rowcount in _mark_superseded — Result.rowcount does not exist on the async Result type and mypy rejected it; RETURNING matches the codebase's existing convention (normalization/resolver.py::clear_override)."

patterns-established:
  - "One superseded_at IS NULL predicate lives in get_recent_observations only; get_latest_observation and future diff analytics delegate to it rather than re-querying."

requirements-completed: [PHYS-08, PHYS-11]

# Metrics
duration: 20min
completed: 2026-09-11
---

# Phase 17 Plan 01: Physique Supersede Repository Semantics Summary

**PHYS-08 supersede write/read semantics and the PHYS-11 disclaimer constant added to the Phase 16 physique repository, with eight new database-layer tests proving retention, exclusion, and tenant scoping.**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-09-11T03:55:00Z
- **Completed:** 2026-09-11T04:15:00Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments
- `PHYSIQUE_RATING_DISCLAIMER` added to `app/db/models/physique.py` (PHYS-11) — the one disclaimer string every physique response in this phase must carry verbatim
- Read path made supersede-aware: `get_recent_observations` (new) holds the single `superseded_at IS NULL` predicate; `get_latest_observation` is now a `limit=1` delegate
- `_read_observation` renamed to public `get_observation` so the future MCP write tool can validate `supersedes_observation_id` through the same tenant-scoped lookup rather than a second query path
- `create_observation` accepts an all-or-nothing `supersedes_observation_id` + `superseded_reason` pair; `_mark_superseded` is now the only writer of the three supersede columns, always an UPDATE, never a DELETE
- Eight new tests in `test_db_physique.py` prove the write, the 19-rating retention, the read exclusion, both refusal directions (cross-tenant, double-supersede), the paired-argument validation, and the length cap

## Task Commits

Each task was committed atomically:

1. **Task 1: Add PHYSIQUE_RATING_DISCLAIMER and make the read path supersede-aware** - `0ab790f` (feat)
2. **Task 2: Add _mark_superseded and the supersede parameters on create_observation** - `c624f26` (feat)
3. **Task 3: Prove PHYS-08 at the database layer** - `2908254` (test)

_Note: This plan was not TDD-flagged at the task level (`tdd="true"` appears on tasks 1-2 but the RED/GREEN split was not separately committed, since the plan's `<action>` blocks specified the target code and tests directly rather than a driving-test-first cycle). Task 3 wrote the tests after the implementation was in place and green, consistent with how the plan sequenced verification._

## Files Created/Modified
- `backend/app/db/models/physique.py` - Added `PHYSIQUE_RATING_DISCLAIMER` constant (PHYS-11)
- `backend/app/db/repositories/physique.py` - Renamed `_read_observation`→`get_observation` (public); added `get_recent_observations` (the one `superseded_at IS NULL` predicate); `get_latest_observation` now a `limit=1` delegate; added `_mark_superseded` and supersede parameters on `create_observation`; module docstring updated to reflect PHYS-08 is implemented
- `backend/tests/test_db_physique.py` - Added eight tests under a `# --- PHYS-08: supersede ---` section proving write, retention, read exclusion, both refusal directions, paired-argument validation, and the reason-length cap

## Decisions Made
- **RETURNING over `Result.rowcount`**: the plan's `<action>` block for `_mark_superseded` specified `result.rowcount`, but the async `execute()` result is typed as a plain `Result[Any]` with no `rowcount` attribute — mypy failed with `attr-defined`. Fixed per deviation Rule 1 (auto-fix bug) using the codebase's existing `RETURNING`-based row-count pattern from `app/normalization/resolver.py::clear_override`, which exists for exactly this reason (documented in that function's own docstring). No behavioral change — same refusal semantics, same predicate set.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `_mark_superseded` used `Result.rowcount`, which does not exist on the typed async `Result`**
- **Found during:** Task 2 (`_mark_superseded` implementation)
- **Issue:** The plan's action block specified `result.rowcount` after an `update(...)` execute; mypy raised `"Result[Any]" has no attribute "rowcount"  [attr-defined]`. This mirrors a documented pitfall already solved elsewhere in the codebase (`app/normalization/resolver.py::clear_override`'s own docstring: "the async `execute()` is typed as a plain `Result`, which has no `rowcount`").
- **Fix:** Switched to `.returning(PhysiqueObservation.id)` + `session.scalars(...)` + `len(updated.all())`, identical row-count semantics, matching the established codebase pattern.
- **Files modified:** `backend/app/db/repositories/physique.py`
- **Verification:** `uv run mypy backend/app/db/repositories/physique.py` — 0 errors; `test_superseding_another_users_observation_is_refused` and `test_superseding_an_already_superseded_observation_is_refused` both assert the refusal count behavior is unchanged.
- **Committed in:** `c624f26` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug)
**Impact on plan:** No scope creep; the fix is a type-safe equivalent of the plan's specified logic, following an existing codebase convention documented at the exact call site the plan itself analogized to.

## Issues Encountered
- One acceptance-criteria grep in the plan (`grep -c "not a measurement" backend/app/db/models/physique.py` expected `>= 1`) does not match, because the plan's own verbatim `PHYSIQUE_RATING_DISCLAIMER` text (copied exactly as specified) splits that phrase across two adjacent string literals — `"...not a "` ends one line, `"measurement. ..."` begins the next, so a line-based grep for the phrase spanning both lines returns 0. This is a discrepancy in the plan's own authoring, not an implementation defect: the plan's authoritative `<verify>` block uses a Python assertion against the joined runtime string (`'not a measurement' in d`), which passed. The disclaimer text itself was NOT reworded to satisfy the grep, since the plan explicitly requires it be copied "verbatim, including the comment" and the wording "carries decision provenance."
- One of my own initial test drafts (`test_get_latest_observation_returns_none_when_the_only_observation_is_superseded`) was over-engineered on the first pass — it tried to reach "the only observation is superseded" through two chained `create_observation` supersede calls across two tenants, which cannot actually produce that state (a supersede always creates a new, non-superseded row). Simplified to a direct column-level UPDATE via `sa.update(...)` to set up the precondition, which is what the test is actually about (the read predicate), not the write path (already covered by other tests in this batch).
- `test_an_over_long_superseded_reason_is_refused`'s first draft asserted `get_latest_observation(...) is None` after the refused call, which is wrong: the prior seeded observation is never touched by a refused call, so it remains the un-superseded latest. Corrected to assert the prior observation is still returned, unsuperseded.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

`get_observation`, `get_recent_observations`, and `create_observation`'s supersede parameters are ready for:
- Plan 17-02 (`app/analytics/physique.py`'s diff), which reads its two inputs from `get_recent_observations`
- Plan 17-03 (the MCP write tool `fitness_log_physique_observation`), which validates a caller-supplied `supersedes_observation_id` through `get_observation` before calling `create_observation`

No migration was created or modified in this plan — migration `0007` already carries all three supersede columns, as expected. No blockers identified for the next plans in this phase.

---
*Phase: 17-physique-analytics-mcp-read-write-tools*
*Completed: 2026-09-11*

## Self-Check: PASSED

All created/modified files confirmed present on disk:
- `backend/app/db/models/physique.py` — FOUND
- `backend/app/db/repositories/physique.py` — FOUND
- `backend/tests/test_db_physique.py` — FOUND
- `.planning/phases/17-physique-analytics-mcp-read-write-tools/17-01-SUMMARY.md` — FOUND

All task commits confirmed present in git log:
- `0ab790f` — FOUND
- `c624f26` — FOUND
- `2908254` — FOUND
