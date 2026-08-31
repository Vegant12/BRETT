---
phase: 06-mcp-tools
plan: 05
subsystem: api
tags: [mcp, analytics, volume, frequency, pydantic, decimal]

# Dependency graph
requires:
  - phase: 06-mcp-tools (plan 06-01)
    provides: _common.py — MAX_WEEKS, MAX_FREQUENCY_EXERCISES, resolve_user_id, read_only_session, window_from_weeks, safe_tool, truncate
  - phase: 06-mcp-tools (plan 06-02)
    provides: schemas.py — WeeklyVolumeResponse, MuscleGroupRollup, MuscleGroupVolumeResponse, TrainingFrequencyResponse
  - phase: 04-volume-frequency-analytics
    provides: get_weekly_volume, get_muscle_group_volume, get_training_frequency
provides:
  - "roll_up_muscles: the pure 19-row window fold shared with plan 06-08's training summary"
  - "fitness_get_weekly_volume MCP tool (VOL-01)"
  - "fitness_get_muscle_group_volume MCP tool (VOL-02, window rollup)"
  - "fitness_get_training_frequency MCP tool (VOL-03, exercise list capped at 30)"
affects: [06-08 training summary, 06-09 schema/isolation tests, 06-10 response budget tests, 06-11 behavioural tests, mcp server tool registration]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Tool adapter: resolve_user_id -> read_only_session -> window_from_weeks -> one or two analytics calls -> response model"
    - "Pure synchronous fold (roll_up_muscles) extracted from the tool body so its invariant is testable with no container"
    - "Truncation always paired with its flag and total via _common.truncate"

key-files:
  created:
    - backend/app/mcp/tools/volume.py
  modified: []

key-decisions:
  - "fitness_get_muscle_group_volume returns a window rollup, not a weeks x 19 grid — the phase's one deliberate reshape (resolved Open Question 1, option (a))"
  - "Untrained muscle groups are emitted as zero rows with insufficient_data=True rather than omitted"
  - "sessions/sessions_per_week come from get_training_frequency and are never summed across weeks"
  - "Coverage and freshness on the muscle response are taken from the VOLUME result, whose freshness covers exercise_templates as well as workouts"
  - "The frequency exercise list is re-sorted by (-sessions, external_id) before the 30-item cap, because the analytics result sorts by external_id"

patterns-established:
  - "Degraded-payload factory per response type (_degraded_weekly/_degraded_muscle/_degraded_frequency) feeding @safe_tool"
  - "Volume and frequency composed over the SAME unsnapped (start_day, end_day) pair, with the snap asymmetry justified in the module docstring"

requirements-completed: [MCP-02, MCP-03, MCP-05, MCP-06]

# Metrics
duration: 14min
completed: 2026-08-31
---

# Phase 6 Plan 05: Volume & Frequency Tools Summary

**Three MCP tools composing the Phase 4 volume/frequency analytics, plus `roll_up_muscles` — the pure fold that collapses a weeks x 19 muscle grid (128 KB at 52 weeks) into a fixed 19-row window rollup where an untrained muscle is a zero row rather than an absence.**

## Performance

- **Duration:** ~14 min
- **Started:** 2026-08-31T11:52:00Z
- **Completed:** 2026-08-31T12:06:31Z
- **Tasks:** 2
- **Files modified:** 1 (created)

## Accomplishments

- `roll_up_muscles` returns exactly 19 `MuscleGroupRollup` rows for any input, sorted by `CanonicalMuscleGroup.value`, with `Decimal("0")` accumulators — verified against a synthetic two-week, two-muscle grid.
- `fitness_get_weekly_volume`, `fitness_get_muscle_group_volume` and `fitness_get_training_frequency` each expose exactly `ctx` and `weeks`, with `weeks` published as `{minimum: 1, maximum: 52, default: 12}` and no `user_id` anywhere in the module (ASVS V4, T-06-02).
- All three tools are `@safe_tool`-guarded with their own degraded-payload factory, so no exception text can reach Claude through the SDK's verbatim `str(e)` error channel (T-06-01).
- The muscle tool's docstring carries the measured byte figures that justify the reshape (128,290 structured / ~347,707 wire at 52 weeks, versus ~7,851 for the rollup at any window) and points readers at `fitness_get_weekly_volume` / `fitness_compare_periods` for what the rollup gives up.
- The frequency tool re-sorts before capping, so the 30 exercises returned are the 30 most-trained rather than 30 alphabetically-lucky external ids.

## Task Commits

Each task was committed atomically:

1. **Task 1: roll_up_muscles and fitness_get_weekly_volume** - `d2b02d6` (feat)
2. **Task 2: fitness_get_muscle_group_volume and fitness_get_training_frequency** - `0cde6b3` (feat)

## Files Created/Modified

- `backend/app/mcp/tools/volume.py` (created, 279 lines) — module docstring recording the no-pre-snapping rule and the volume/frequency snap asymmetry; `_MuscleTotals` Decimal accumulator; `roll_up_muscles`; the three tools with their degraded factories.

## Decisions Made

- **Window rollup over per-week grid** for `fitness_get_muscle_group_volume`. This is the resolved Open Question 1 (option (a)) and the phase's single deliberate exception to CONTEXT.md's "compose, don't reshape" rule. Stated explicitly in the tool docstring so it cannot be mistaken for an oversight.
- **Zero rows, not absences.** `metadata.is_insufficient(0)` is `True`, so a missing frequency entry defaults to `sessions=0`, `sessions_per_week=Decimal("0")`, `insufficient_data=True`. Defaulting `insufficient_data` to `False` would let an untrained muscle read as a confident zero.
- **Coverage/freshness sourced from the volume result**, not the frequency one, because `FRESHNESS_RESOURCES_MUSCLE` covers both `workouts` and `exercise_templates` and a stale template sync silently changes every per-muscle number.
- **`_MuscleTotals` as a `slots=True` dataclass** with a `Decimal("0")` default factory rather than an inline tuple accumulator — it makes the "these three fields are additive, the session fields are not" boundary explicit at the type level.
- **`roll_up_muscles` kept pure and synchronous** (no session, no `await`) so plan 06-08 can reuse it and plan 06-11 can assert the 19-row invariant with no container.

## Deviations from Plan

None - plan executed exactly as written.

The plan's code sketches used a local variable named `user_id`; that was renamed to `user` in the implementation so the plan's own acceptance criterion `grep -c 'user_id:' == 0` holds unambiguously and no reader mistakes a local for a published parameter. The keyword arguments passed to analytics remain `user_id=`.

## Issues Encountered

The worktree started at a commit behind the required base (`485c445`); it was hard-reset to the correct base before any work, per the startup check. The worktree had no `.venv`, so `uv sync --all-extras --dev` was run once to make `ruff`/`mypy`/`pytest` available — no change to `pyproject.toml` or `uv.lock`.

## Verification

- `uv run ruff check app/mcp` — All checks passed
- `uv run ruff format --check app/mcp/tools/volume.py` — already formatted
- `uv run mypy app/mcp/tools/volume.py` — Success, no issues
- `uv run pytest tests -x -q -m "not integration"` — 358 passed, 246 deselected
- Signature probe: all three tools report `['ctx', 'weeks']`
- `grep -c '@safe_tool(degraded='` → 3; `grep -c 'user_id:'` → 0; no `float`, no `str(e)`/`str(exc)`/`repr(e)`, `snap_local_week_range` appears only in the module docstring
- `git diff --stat pyproject.toml uv.lock` — no change
- Behavioural spot-check of `roll_up_muscles` against a synthetic grid: 19 rows, sorted by enum value, chest sets summed across two weeks (7 direct / `Decimal("7.0")` weighted) with `sessions=3` taken from frequency, and `lats` a zero row with `insufficient_data=True`

## Known Stubs

None. Every field of every response is populated from an analytics result or from a `_common` helper; the degraded factories are the documented `data_available=False` contract from plan 06-02, not placeholders.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `roll_up_muscles` is exported and ready for plan 06-08's `TrainingSummaryResponse.muscles`.
- The three tools are **not yet registered** on `mcp` — `backend/app/mcp/server.py` is deliberately untouched (it is outside this plan's `files_modified`), so registration happens in the plan that owns the tool registry.
- Behavioural proof (exactly N week rows, the 19-row guarantee end to end, the truncation flag under load) is deferred to plans 06-10 and 06-11 as the plan specifies.

## Self-Check: PASSED

- `backend/app/mcp/tools/volume.py` — FOUND
- `.planning/phases/06-mcp-tools/06-05-SUMMARY.md` — FOUND
- Commit `d2b02d6` — FOUND
- Commit `0cde6b3` — FOUND

---
*Phase: 06-mcp-tools*
*Completed: 2026-08-31*
