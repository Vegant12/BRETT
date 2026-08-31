---
phase: 06-mcp-tools
plan: 08
subsystem: api
tags: [mcp, analytics, summary, recomposition, volume, frequency, decimal]

# Dependency graph
requires:
  - phase: 06-mcp-tools (plan 06-01)
    provides: _common.py — MAX_SUMMARY_WEEKS, resolve_user_id, read_only_session, window_from_weeks, safe_tool
  - phase: 06-mcp-tools (plan 06-02)
    provides: schemas.py — TrainingSummaryResponse, SummaryVolumeWeek, MuscleGroupRollup
  - phase: 06-mcp-tools (plan 06-05)
    provides: volume.py — roll_up_muscles, the pure 19-row window fold
  - phase: 04-volume-frequency-analytics
    provides: get_weekly_volume, get_muscle_group_volume, get_training_frequency
  - phase: 05-progression-records-recomposition-analytics
    provides: get_recomposition_status (BODY-02) and its INTERPRETATION_DISCLAIMER
provides:
  - "fitness_get_training_summary MCP tool (D-08) — the one call answering both Core Value questions"
affects: [06-09 schema/isolation tests, 06-10 response budget tests, 06-11 behavioural tests, mcp server tool registration]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Composite tool: four analytics calls inside ONE read-only transaction for a single consistent snapshot"
    - "Lean projection of analytics results (SummaryVolumeWeek drops tonnage_sets; muscles folded to 19 rows) rather than verbatim composition"
    - "Shared fold imported from a sibling tool module (roll_up_muscles) instead of re-derived"

key-files:
  created:
    - backend/app/mcp/tools/summary.py
  modified: []

key-decisions:
  - "weeks capped at MAX_SUMMARY_WEEKS (12), default 4 — one training block, ~9.5 KB wire against the 16 KB budget"
  - "roll_up_muscles imported from volume.py so the summary and the muscle tool can never disagree about a set count"
  - "recomposition_disclaimer copied verbatim from RecompositionResult.disclaimer (T-06-09)"
  - "freshness taken from the MUSCLE result (workouts + exercise_templates), coverage from the weekly result (T-06-14)"
  - "Personal records and plateaus deliberately excluded; the per-week x per-muscle grid and per-exercise frequency list dropped for size (T-06-05)"
  - "The ~seven-aggregate-query cost is recorded in the module docstring and accepted for v1 rather than pre-optimized (T-06-13)"

patterns-established:
  - "Degraded factory empties EVERY field rather than partially filling, so a failure cannot read as a real 'no signal' verdict"
  - "Composite-tool cost and exclusions documented at the module, with the measured byte figures that justify them"

requirements-completed: [MCP-02, MCP-03, MCP-05, MCP-06]

# Metrics
duration: 12min
completed: 2026-08-31
---

# Phase 6 Plan 08: Training Summary Tool Summary

**`fitness_get_training_summary` — one call that composes weekly volume, the 19-row muscle rollup, training frequency and the recomposition verdict inside a single read-only transaction, projected into a ~9.5 KB wire shape instead of the ~57 KB a verbatim composition of the same four results would cost.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-08-31T12:02:00Z
- **Completed:** 2026-08-31T12:14:21Z
- **Tasks:** 1
- **Files modified:** 1 (created)

## Accomplishments

- `fitness_get_training_summary` exposes exactly `ctx` and `weeks`; the generated input schema publishes `weeks` as `{"minimum": 1, "maximum": 12, "default": 4, "type": "integer"}` — verified by building the SDK `Tool` from the function and dumping `parameters`.
- All four analytics calls (`get_weekly_volume`, `get_muscle_group_volume`, `get_training_frequency`, `get_recomposition_status`) run inside one `read_only_session`, so the volume figures and the recomposition verdict describe one consistent snapshot and PostgreSQL itself refuses any write on the path (MCP-05, T-06-03).
- `muscles` is built by importing `roll_up_muscles` from `volume.py` — the same fold `fitness_get_muscle_group_volume` uses — so the two tools cannot drift apart on a muscle's set count, and all 19 canonical groups (including zero rows) always appear.
- `recomposition_disclaimer` is `recomposition.disclaimer` verbatim: no rewording, no truncation, no reconstruction from a constant (T-06-09).
- `freshness` comes from the muscle-volume result (covers `workouts` **and** `exercise_templates`) while `coverage` comes from the weekly result — the summary reports per-muscle numbers a stale template sync would silently change, so the workouts-only freshness would overclaim (T-06-14).
- `@safe_tool(degraded=_degraded_summary)` guards the tool-result channel; the degraded payload empties every field so a failure cannot be read as a genuine "no recomposition signal" (T-06-01).
- The module docstring records both what is excluded (PRs, plateaus, the weeks x 19 grid, the per-exercise list) with the measured byte figures, and what the tool costs (~seven aggregate queries, `get_recomposition_status` being the expensive half) against Claude's 10 s discovery / 30 s call budgets.

## Task Commits

Each task was committed atomically:

1. **Task 1: fitness_get_training_summary** - `b406662` (feat)

## Files Created/Modified

- `backend/app/mcp/tools/summary.py` (created, 172 lines) — module docstring covering the exclusions and the query cost; `_degraded_summary` factory; `fitness_get_training_summary` composing the four analytics calls and projecting them into `TrainingSummaryResponse`.

## Decisions Made

- **Default `weeks=4`, cap 12.** D-08 leaves the default to discretion. Four weeks is one training block, and it measures ~9.5 KB on the wire against the 16 KB budget while 12 weeks measures ~11.5 KB — the default is the block a coaching question is usually about, and widening it is one argument away. The cap is `MAX_SUMMARY_WEEKS` rather than `MAX_WEEKS` because this response carries a per-week row *and* a 19-row rollup, so its size grows with the window where the single-purpose tools' does not (T-06-05).
- **`tonnage_sets` dropped from each week row.** It is the operand-presence denominator for `tonnage_kg` — useful when auditing a number, not when summarizing one. `fitness_get_weekly_volume` returns the full row.
- **`coverage` from the weekly result, `freshness` from the muscle result.** They are deliberately sourced from different calls, and the reason is commented inline: coverage describes the window's training data, freshness must describe the stalest resource any number in the response depends on.
- **The recomposition call takes no window and is not made to take one.** "Where does my recomposition stand" is always anchored on today over its own fixed 12-week lookback; passing `weeks` into it would have made the verdict move with an argument that BODY-02 never classifies against.
- **Local variable named `user`, not `user_id`**, matching `volume.py` — the keyword arguments passed to analytics remain `user_id=`, and no reader can mistake a local for a published parameter.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Rewrapped an over-length docstring line**
- **Found during:** Task 1 verification
- **Issue:** The tool docstring line the plan supplied verbatim (`Personal records and plateaus are deliberately not included -- ask \`fitness_get_personal_records\``) is 101 characters, one over the project's Ruff `E501` limit of 100. `ruff check` failed, blocking the task's own `<automated>` verification.
- **Fix:** Wrapped the sentence across two lines. Wording is unchanged, and both tool names remain in the docstring where the acceptance criteria expect them (docstring-only, never in code).
- **Files modified:** `backend/app/mcp/tools/summary.py`
- **Commit:** `b406662`

No other deviations. No architectural decisions were required.

## Issues Encountered

The worktree started one commit behind the required base (`1e97f3b`) and was hard-reset to `ff870f8` before any work, per the startup check. The worktree had no `.venv`; `uv sync --group dev --frozen` was run once to make `ruff`/`mypy`/`pytest` available — `pyproject.toml` sets `default-groups = []`, so the bare `uv sync` that `uv run` performs implicitly does not install dev tooling. No change to `pyproject.toml` or `uv.lock`.

## Verification

- `uv run ruff check backend/app/mcp/tools/summary.py` — All checks passed
- `uv run ruff format --check backend/app/mcp/tools/summary.py` — 1 file already formatted
- `uv run mypy backend/app/mcp/tools/summary.py` — Success, no issues found
- `uv run pytest backend/tests -x -q -m "not integration"` — 358 passed, 246 deselected
- Signature probe: `['ctx', 'weeks']`
- Schema probe (`Tool.from_function(...).parameters`): `weeks` → `{"default": 4, "minimum": 1, "maximum": 12, "type": "integer"}`, no `user_id` property, nothing required
- File is 172 lines (≥ 110); `grep -c 'async def fitness_get_training_summary'` → 1; `grep -c '@safe_tool(degraded='` → 1
- `from app.mcp.tools.volume import roll_up_muscles` present; `recomposition.disclaimer` present; `le=MAX_SUMMARY_WEEKS` present
- `grep -n 'get_personal_records\|get_plateaus'` → lines 12 and 107 only, both inside docstrings; zero occurrences in code
- `grep -n 'str(e)\|str(exc)\|repr(e)\|float'` → no matches
- `git diff --stat pyproject.toml uv.lock` — no change
- `git diff --diff-filter=D HEAD~1 HEAD` — no deletions; `git status --short` clean after commit

## Known Stubs

None. Every field of `TrainingSummaryResponse` is populated from an analytics result; `_degraded_summary` is the documented `data_available=False` contract from plan 06-02, not a placeholder.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `fitness_get_training_summary` is **not yet registered** on `mcp` — `backend/app/mcp/server.py` is outside this plan's `files_modified`, so registration belongs to the plan that owns the tool registry.
- The 16 KB response budget assertion for this tool is plan 06-10's; the behavioural proof (four analytics composed, disclaimer non-empty in a live response) is plan 06-11's, exactly as this plan specifies.
- The ~seven-aggregate-query latency figure (T-06-13) is accepted, not measured — the phase's live smoke test is where it should be re-checked against the 10 s discovery budget.

## Self-Check: PASSED

- `backend/app/mcp/tools/summary.py` — FOUND
- `.planning/phases/06-mcp-tools/06-08-SUMMARY.md` — FOUND
- Commit `b406662` — FOUND

---
*Phase: 06-mcp-tools*
*Completed: 2026-08-31*
