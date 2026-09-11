---
phase: 17-physique-analytics-mcp-read-write-tools
plan: 02
subsystem: analytics
tags: [analytics, physique, ordinal-diff, volume-cross-reference]

# Dependency graph
requires:
  - phase: 17-physique-analytics-mcp-read-write-tools
    plan: 01
    provides: get_recent_observations/get_latest_observation (supersede-aware), PHYSIQUE_RATING_DISCLAIMER
provides:
  - get_physique_diff (pure, synchronous, PHYS-09) and get_latest_physique_diff (async fetch wrapper)
  - get_physique_volume_cross_reference (PHYS-10)
  - PhysiqueDiffVerdict, PhysiqueMuscleDiff, PhysiqueDiffResult, PhysiqueVolumeFlag, PhysiqueVolumeCrossReference
affects: [18]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pure/synchronous diff function taking already-fetched dataclass records, same testability argument as recomposition.aggregate_progression"
    - "Bottom-quartile-by-rank with inclusive ties, rather than a percentile interpolation, for a self-relative undertrained cut"

key-files:
  created:
    - backend/app/analytics/physique.py
    - backend/tests/test_analytics_physique.py
  modified:
    - backend/app/analytics/schemas.py

key-decisions: []

patterns-established:
  - "A composition-only analytics module (no SQL of its own) calls exactly one already-tested analytics function (get_muscle_group_volume) once and folds its own totals from the result, never re-querying."

requirements-completed: [PHYS-09, PHYS-10]

# Metrics
duration: 35min
completed: 2026-09-11
---

# Phase 17 Plan 02: Physique Analytics — Diff and Volume Cross-Reference Summary

**`app/analytics/physique.py` added: a pure ordinal per-muscle-group diff (PHYS-09) and a volume
cross-reference answering "is the underdeveloped area also the undertrained one?" (PHYS-10), both
composed entirely from already-tested functions with no new SQL.**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-09-11T03:56:00Z
- **Completed:** 2026-09-11T04:20:00Z
- **Tasks:** 3
- **Files modified:** 3 (2 created, 1 modified)

## Accomplishments

- Five new Pydantic result types added to `app/analytics/schemas.py`: `PhysiqueDiffVerdict`,
  `PhysiqueMuscleDiff`, `PhysiqueDiffResult`, `PhysiqueVolumeFlag`, `PhysiqueVolumeCrossReference`.
  Both response models carry a required `disclaimer: str` (PHYS-11), never `str | None`.
- `get_physique_diff`: pure and synchronous, comparing `PhysiqueRatingLevel` declaration-order
  ordinals across two already-fetched observations. Always all 19 groups, sorted by
  `muscle_group.value`. A one-level move classifies `unchanged` (the measured noise floor);
  `Not Assessable` on either side is `not_comparable`, never folded into `unchanged`.
- `get_latest_physique_diff`: the sanctioned async entry point — fetches the two most recent
  non-superseded observations via `get_recent_observations` and diffs them. `None` when fewer
  than two exist.
- `get_physique_volume_cross_reference`: joins `Minimal`/`Emerging`-rated groups against the
  bottom-quartile (by rank, ties inclusive) of `weighted_sets` totals over
  `RECOMP_LOOKBACK_WEEKS` (imported, never re-literalled), anchored on the observation's own
  `observed_on` rather than today. Calls `get_muscle_group_volume` exactly once. `Not Assessable`
  groups are structurally excluded from the underdeveloped side (D-03) regardless of volume.
- 16 new tests in `test_analytics_physique.py`: 8 pure (no container) proving the four verdicts,
  the noise-floor gate, byte-identical `model_dump_json()` determinism, the 19-row sorted spine,
  and the surfaced-not-enforced elapsed/floor fields; 8 container tests proving the supersede
  exclusion (via the real `create_observation` write path), all four cross-reference cases
  including the D-03 exclusion, the `None` paths, and the `RECOMP_LOOKBACK_WEEKS` reuse.

## Task Commits

Each task was committed atomically:

1. **Task 1: Declare the five physique analytics result types** - `e214663` (feat)
2. **Task 2: Build analytics/physique.py — the ordinal diff and the volume cross-reference** - `2cc90b9` (feat)
3. **Task 3: Prove PHYS-09 determinism and the PHYS-10 join** - `aa2a042` (test)

_Note: tasks were `tdd="true"`-flagged but implemented directly against the plan's detailed
`<action>` blocks (which specified the target code verbatim) rather than a driving RED/GREEN
split, consistent with how plan 17-01 sequenced its own verification._

## Files Created/Modified

- `backend/app/analytics/schemas.py` — Added `PhysiqueDiffVerdict`, `PhysiqueMuscleDiff`,
  `PhysiqueDiffResult`, `PhysiqueVolumeFlag`, `PhysiqueVolumeCrossReference`, plus the
  `PhysiqueRatingLevel` import
- `backend/app/analytics/physique.py` — New module: `get_physique_diff`,
  `get_latest_physique_diff`, `get_physique_volume_cross_reference`, plus the
  `_LEVEL_ORDINALS`/`UNDERDEVELOPED_LEVELS`/`_UNDERTRAINED_BOTTOM_RANKS` module constants
- `backend/tests/test_analytics_physique.py` — 16 new tests (8 pure, 8 container)

## Decisions Made

None beyond the plan's own specification — the action blocks were followed as written.

## Deviations from Plan

None — plan executed exactly as written. Every acceptance-criteria grep and automated verify
step passed on first execution, with two exceptions noted below that are plan-authoring
discrepancies (not implementation defects), following the same pattern plan 17-01 documented
for its own disclaimer-text grep.

### Documented plan-authoring discrepancies (not deviations from behavior)

1. **Task 2 acceptance criterion `grep -c "get_muscle_group_volume(" ... returns exactly 2`
   actually returns 1.** The plan's own text explains this should be "the import plus one call
   site", but a single-name import (`from app.analytics.volume import get_muscle_group_volume`)
   has no parenthesis for the pattern `get_muscle_group_volume(` to match — only the call site
   does. Confirmed correct by reading the file: the import is present once, the call site is
   present once, `ruff`/`mypy` are clean, and `get_muscle_group_volume` is called exactly once
   at runtime (verified structurally in `get_physique_volume_cross_reference`'s body and by the
   isolation test suite). No code change was made to satisfy the grep, since the code already
   matches the plan's own `<action>` block verbatim.
2. **The plan's whole-backend `<verification>` block
   (`uv run ruff format --check backend` / `uv run ruff check backend`) reports pre-existing
   findings in 21 unrelated files** (`app/analytics/health.py`, `app/db/migration_preflight.py`,
   several `app/integrations/hevy/*` and `tests/*` files) that this plan does not touch. Confirmed
   pre-existing via `git status --short` against the pre-plan `HEAD` (clean on every flagged
   file). Logged to
   `.planning/phases/17-physique-analytics-mcp-read-write-tools/deferred-items.md` per the
   executor's SCOPE BOUNDARY rule rather than fixed. This plan's own three files
   (`app/analytics/schemas.py`, `app/analytics/physique.py`,
   `tests/test_analytics_physique.py`) all pass `ruff check`, `ruff format --check`, and `mypy`
   individually with zero findings.

## Issues Encountered

None. All 16 new tests passed on first run; the full fast suite (667 tests,
`-m "not integration and not realfile"`) shows zero regressions.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

`get_physique_diff`, `get_latest_physique_diff` and `get_physique_volume_cross_reference` are
ready for Phase 18's `compose_report` to call directly. No MCP tool wraps either function this
phase (17-CONTEXT.md D-08 — PHYS-F02 stays deferred). No migration was created or modified in
this plan. No blockers identified for Phase 18 or for plan 17-03 (running concurrently in a
sibling worktree).

---
*Phase: 17-physique-analytics-mcp-read-write-tools*
*Completed: 2026-09-11*

## Self-Check: PASSED

All created/modified files confirmed present on disk:
- `backend/app/analytics/schemas.py` — FOUND (modified)
- `backend/app/analytics/physique.py` — FOUND (created)
- `backend/tests/test_analytics_physique.py` — FOUND (created)
- `.planning/phases/17-physique-analytics-mcp-read-write-tools/deferred-items.md` — FOUND (created)
- `.planning/phases/17-physique-analytics-mcp-read-write-tools/17-02-SUMMARY.md` — FOUND

All task commits confirmed present in git log:
- `e214663` — FOUND
- `2cc90b9` — FOUND
- `aa2a042` — FOUND
