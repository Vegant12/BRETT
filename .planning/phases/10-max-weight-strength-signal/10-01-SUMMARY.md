---
phase: 10-max-weight-strength-signal
plan: 01
subsystem: api
tags: [pydantic, plateau-detection, mcp, analytics]

# Dependency graph
requires:
  - phase: 05-progression-records-recomposition-analytics
    provides: PlateauResult, get_plateaus, best_set_per_day/SessionBest fold, fitness_get_plateaus MCP tool
provides:
  - "PlateauResult.last_max_weight_kg: Decimal | None field, populated from series[-1].best_weight_kg"
  - "fitness_get_plateaus MCP response carrying last_max_weight_kg per exercise (zero code change in mcp/tools/progression.py)"
affects: [11-report-mcp-tools, coaching-instructions]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Display-only field added to an existing Pydantic response model without touching its classifier: new field is populated at the single construction site from data already computed by an existing fold (SessionBest.best_weight_kg), with zero new query and zero new column"

key-files:
  created: []
  modified:
    - backend/app/analytics/schemas.py
    - backend/app/analytics/progression.py
    - backend/tests/test_analytics_progression.py
    - backend/tests/test_mcp_tools.py

key-decisions:
  - "No no_max_weight_reason companion enum added alongside last_max_weight_kg -- best_weight_kg is bare-nullable everywhere else in the codebase (SessionBest, ProgressionPoint), and NoEstimateReason answers a different question (why an e1RM estimate failed from a present weight), so inventing a second convention for a condition already expressed with a bare None would duplicate existing semantics."

requirements-completed: [STR-01, STR-02, STR-03, STR-04]

# Metrics
duration: 15min
completed: 2026-09-03
---

# Phase 10 Plan 01: Max-Weight Strength Signal Summary

**Added `PlateauResult.last_max_weight_kg: Decimal | None`, a labelled display-only field sourced from the existing `best_set_per_day` fold (`series[-1].best_weight_kg`), so `fitness_get_plateaus` can cite the literal last weight lifted -- estimated-1RM keeps classifying `plateaued`/`threshold_percent` unchanged.**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-09-03T14:23:00Z (approx, first Read call)
- **Completed:** 2026-09-03T14:38:00Z
- **Tasks:** 2 completed (Task 1 was `tdd="true"`: RED + GREEN commits)
- **Files modified:** 4

## Accomplishments
- `PlateauResult` gained `last_max_weight_kg: Decimal | None` as its last field, with a docstring paragraph distinguishing it from `PersonalRecordType.MAX_WEIGHT` ("heaviest ever" vs "most recent")
- `get_plateaus` populates it from `series[-1].best_weight_kg` at the single construction site, with a comment explaining D-07/D-08 semantics -- no other line in the construction call changed
- Proved by test (not inspection) that `fitness_get_plateaus`'s MCP response forwards the new field with **zero code changes** to `backend/app/mcp/tools/progression.py`
- Proved by test that `test_mcp_tool_budget.py`'s byte-budget gate passes unmodified (no bump needed) and that `test_analytics_recomposition.py` passes unmodified (STR-04: `recomposition.py`'s `progression_signal` still sourced from `get_exercise_trends`, e1RM-based)
- Structurally confirmed (`git diff --stat` against the pre-plan base commit) that `recomposition.py`, `estimates.py`, and `mcp/tools/progression.py` show zero diff -- STR-01/STR-03 proven, not merely tested

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): add failing tests for `last_max_weight_kg`** - `b13720c` (test)
2. **Task 1 (GREEN): implement `PlateauResult.last_max_weight_kg`** - `4673674` (feat)
3. **Task 2: MCP passthrough proof, budget check, and regression confirmation** - `ba54838` (test)

**Plan metadata:** (this commit, docs: complete plan)

_Note: Task 1 carried `tdd="true"` and produced a test → feat pair (no refactor commit needed; the GREEN implementation required no cleanup)._

## Files Created/Modified
- `backend/app/analytics/schemas.py` - `PlateauResult.last_max_weight_kg: Decimal | None` field + docstring paragraph explaining D-07/D-08 semantics and the discretion call against a companion reason enum
- `backend/app/analytics/progression.py` - `get_plateaus`'s single `PlateauResult(...)` construction site gains `last_max_weight_kg=series[-1].best_weight_kg,` with an inline comment; no other line touched
- `backend/tests/test_analytics_progression.py` - three new integration tests: `test_plateau_reports_literal_last_weight_lifted` (ordinary case), `test_last_max_weight_diverges_from_streak_qualifying_weight` (D-07 divergence, the load-bearing test), `test_last_max_weight_is_none_not_zero_for_bodyweight_exercise` (D-08 honesty)
- `backend/tests/test_mcp_tools.py` - `test_plateaus_reports_its_window_and_threshold` extended with an assertion that every reported exercise's structured MCP response carries `last_max_weight_kg`

`backend/tests/test_mcp_tool_budget.py` was read and its full suite re-run per the plan's Task 2 step 2, but required **no changes** -- the byte budget for `fitness_get_plateaus` already had enough headroom for the new field, so this file is unmodified and not in the commits above.

## Decisions Made
- No `no_max_weight_reason`-style companion enum was added alongside `last_max_weight_kg` (the plan's stated discretion call, applied as written): `best_weight_kg` is bare-nullable everywhere it already exists in this codebase with no reason enum for "this day had no weight recorded"; `NoEstimateReason` answers a different question (why an e1RM *estimate* failed from a *present* weight). Inventing a new enum here would duplicate an existing convention rather than extend it.

## Deviations from Plan

None - plan executed exactly as written. The plan's interfaces section (exact line numbers, exact field-insertion points, exact test fixture patterns) matched the live code precisely; no exploration or improvisation was needed beyond following the plan's spelled-out steps.

## Issues Encountered

None. TDD flow (write three tests first, confirm all three fail with `AttributeError`, implement, confirm all three plus all 41 pre-existing tests in the file pass) proceeded exactly as the plan described. `mypy` and `ruff` were clean on the first run for every touched file.

## User Setup Required

None - no external service configuration required. This is a pure backend analytics/schema change with no new dependency, no migration, and no new MCP tool surface.

## Next Phase Readiness

`PlateauResult.last_max_weight_kg` is live and MCP-forwarded; `fitness_get_plateaus` responses now carry a citable "last weight lifted" figure per exercise alongside the unchanged e1RM-based plateau verdict. `ExerciseTrend`, `ExerciseProgressionResult`, and `fitness_get_exercise_progression` remain byte-for-byte unchanged (D-04/D-05), confirmed by the zero-diff structural check. No blockers for subsequent phases; this closes out the one Active v2.0 requirement item scoped to Phase 10 (STR-01 through STR-04).

---
*Phase: 10-max-weight-strength-signal*
*Completed: 2026-09-03*

## Self-Check: PASSED

- FOUND: `backend/app/analytics/schemas.py` line 383 `last_max_weight_kg: Decimal | None`
- FOUND: `backend/app/analytics/progression.py` line 769 `last_max_weight_kg=series[-1].best_weight_kg,`
- FOUND: `backend/tests/test_analytics_progression.py`
- FOUND: `backend/tests/test_mcp_tools.py`
- FOUND: commit `b13720c` (test: RED)
- FOUND: commit `4673674` (feat: GREEN)
- FOUND: commit `ba54838` (test: MCP passthrough proof)
