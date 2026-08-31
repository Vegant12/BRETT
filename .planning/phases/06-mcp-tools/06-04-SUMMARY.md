---
phase: 06-mcp-tools
plan: 04
subsystem: mcp
tags: [mcp, pydantic, tools, workouts, read-only]

# Dependency graph
requires:
  - phase: 06-mcp-tools
    plan: "01"
    provides: safe_tool, read_only_session, resolve_user_id, local_timezone, MAX_RECENT_WORKOUTS, MAX_WORKOUT_SETS
  - phase: 06-mcp-tools
    plan: "02"
    provides: RecentWorkoutsResponse, WorkoutSummary, WorkoutDetailResponse, WorkoutDetail, WorkoutExerciseDetail, WorkoutSetDetail
  - phase: 06-mcp-tools
    plan: "03"
    provides: recent_workout_summaries and workout_detail read-only projections
  - phase: 04-volume-frequency-analytics
    provides: build_freshness and FRESHNESS_RESOURCES_WORKOUTS (DQ-01 envelope)
provides:
  - "fitness_get_recent_workouts: count-capped, newest-first workout summaries with a published maximum of 25"
  - "fitness_get_workout: the full exercise/set breakdown for one workout, keyed on the Hevy external id"
  - "The list-then-drill-in navigation pair Claude uses to reach an individual training session"
affects:
  - 06-08-PLAN (server.py tool registration)
  - 06-09-PLAN (static isolation guards over app/mcp/ — this module is text()-free and float-free)
  - 06-10-PLAN (byte-budget test: 20 KB list / 32 KB detail)
  - 06-11-PLAN (per-tool integration and leak tests)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Annotated[T, Field(...)] on tool parameters so the bound is PUBLISHED in inputSchema and enforced by the SDK before the body runs, rather than validated in-body"
    - "Module-level zero-argument degraded factories paired with @safe_tool, one per response model"
    - "found (no such row) kept strictly distinct from data_available (could not reach the data)"

key-files:
  created:
    - backend/app/mcp/tools/workouts.py
  modified: []

key-decisions:
  - "limit and workout_id are bounded declaratively via Field(le=MAX_RECENT_WORKOUTS) and Field(max_length=64); verified to land as maximum 25 and maxLength 64 in the published inputSchema, so the SDK rejects a bad call before any query runs"
  - "_degraded_workout reports requested_workout_id as an empty string rather than echoing the requested id, because safe_tool's factory takes no arguments by design and must not close over a failed call"
  - "The response objects are constructed AFTER the read_only_session closes, which is safe only because every value read is already a frozen dataclass or Pydantic model — nothing triggers a lazy load"
  - "Both tools call local_timezone directly for the tz string their repository needs, rather than going through local_today, keeping the single timezone read in _common.py"

patterns-established:
  - "A tool module that adapts a repository projection rather than an analytics function still publishes a fixed shape and a hard cap — never raw table access (MCP-03)"
  - "The workout_id a tool accepts is the same external id the sibling tool echoed; the internal workouts.id surrogate never appears in either direction (D-12, T-06-08)"

requirements-completed: [MCP-02, MCP-03, MCP-05, MCP-06]

# Metrics
duration: 21min
completed: 2026-08-31
---

# Phase 6 Plan 04: Workout Retrieval Tools Summary

Two MCP tools in one module — `fitness_get_recent_workouts` (count-capped summaries, published
`maximum: 25`) and `fitness_get_workout` (full set-level breakdown keyed on the Hevy external id) —
each wrapped in `safe_tool`, each returning a declared response model, with `found` and
`data_available` kept as separate facts.

## What Was Built

**`backend/app/mcp/tools/workouts.py`** (247 lines, 2 tools, 2 degraded factories).

`fitness_get_recent_workouts(ctx, limit=10)` resolves the user server-side, opens a `READ ONLY`
transaction, reads the user's timezone once, projects `recent_workout_summaries` rows
field-for-field into `WorkoutSummary`, and attaches the DQ-01 freshness envelope for the workouts
resource. `limit` is count-based (D-10), never days-based.

`fitness_get_workout(ctx, workout_id)` does the same read and calls `workout_detail` with
`max_sets=MAX_WORKOUT_SETS`, mapping the nested `WorkoutExerciseRow`/`WorkoutSetRow` dataclasses
into `WorkoutExerciseDetail`/`WorkoutSetDetail` and deriving `sets_truncated` from the repository's
true pre-truncation `total_sets`. A repository `None` becomes `data_available=True, found=False` —
an ordinary successful answer with a comment in the body explaining why that must never collapse
into the degraded payload's `data_available=False`.

Both parameter bounds were verified as *published*, not merely declared, by building a throwaway
`MCPServer` and reading the generated `inputSchema`:

- `limit` → `{"minimum": 1, "maximum": 25, "default": 10, "type": "integer"}`
- `workout_id` → `{"minLength": 1, "maxLength": 64, "type": "string"}`, `required: ["workout_id"]`

Neither schema contains `ctx` or `user_id`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `workout_detail` requires a `tz` keyword the plan's interface block omitted**

- **Found during:** Task 2
- **Issue:** The plan's `<interfaces>` sketch gave the signature as
  `workout_detail(session, *, user_id, external_id, max_sets)` and its action block prescribed the
  call `workout_detail(session, user_id=user_id, external_id=workout_id, max_sets=MAX_WORKOUT_SETS)`.
  The function 06-03 actually shipped is
  `workout_detail(session, *, user_id, external_id, tz, max_sets)` — `tz` is required with no
  default, because `WorkoutDetailRow.local_day` cannot be computed without it. Written as planned,
  the call is a `TypeError` at the first invocation.
- **Fix:** Passed the `tz` already read for the summaries path through to `workout_detail`. This is
  not a workaround — 06-03-SUMMARY.md records the required `tz` keyword as a deliberate decision
  ("a module-level default timezone is how a wrong-timezone bug passes every test"), and it is also
  what makes the two tools agree about which local day a workout belongs to. The plan's interface
  block was simply stale relative to what Wave 1 shipped.
- **Files modified:** `backend/app/mcp/tools/workouts.py`
- **Commit:** 2dc0420

No other deviations. No new dependencies (`git diff --stat pyproject.toml uv.lock` is empty), no
files deleted, no shared orchestrator artifacts touched.

## Verification

| Gate | Result |
|------|--------|
| `uv run ruff check backend/app/mcp` | All checks passed |
| `uv run mypy backend/app/mcp/tools/workouts.py` | Success: no issues found |
| `uv run pytest backend/tests -x -q -m "not integration"` | 358 passed, 246 deselected |
| `grep 'str(e)\|str(exc)\|repr(e)'` | 0 matches |
| `grep 'from sqlalchemy import text'` / `text(` | 0 matches (06-09's guard will pass) |
| `float` usage (`_FLOAT_USE` regex) | 0 matches |
| `grep 'user_id:'` | 0 matches — no tool parameter named `user_id` |
| `inspect.signature(fitness_get_recent_workouts)` | `['ctx', 'limit']` |
| `inspect.signature(fitness_get_workout)` | `['ctx', 'workout_id']` |
| `fitness_get_workout.__doc__` | present — `functools.wraps` survived `safe_tool` |
| `git diff --stat pyproject.toml uv.lock` | empty |

Behavioural proof (byte budgets, read-only enforcement at runtime, leak tests, per-tool
integration) lands in plans 06-10 and 06-11 as the plan specifies. This plan's own gate was
import-clean, type-clean and schema-shaped, and all three hold.

## Threat Model Coverage

| Threat ID | Disposition | How it is met in this module |
|-----------|-------------|------------------------------|
| T-06-01 | mitigate | Both tools carry `@safe_tool(degraded=...)`; no exception is interpolated into any string anywhere in the module |
| T-06-02 | mitigate | `resolve_user_id(ctx)` server-side; `user_id` absent from both published schemas; the repository filters on it |
| T-06-03 | mitigate | All reads inside `read_only_session`; no write construct imported |
| T-06-04 | mitigate | `workout_id` bound by the repository's Core expression; `max_length=64` rejects over-long input pre-query; no `text(` |
| T-06-05 | mitigate | `maximum: 25` and `max_sets=MAX_WORKOUT_SETS` both published/applied; `total_sets` reports the truth and `sets_truncated` flags it |
| T-06-08 | accept | Both parameters are scalars; the SDK's validation error can only echo the model's own argument |

No new security-relevant surface was introduced beyond the plan's `<threat_model>` — no new
endpoint, no new auth path, no schema change.

## Known Stubs

None. Both tools are fully wired to real repository data; nothing returns a hardcoded empty
collection except the two degraded factories, which are the documented failure path.

## Self-Check: PASSED

- `backend/app/mcp/tools/workouts.py` — FOUND (247 lines, ≥ 120 required)
- exports `fitness_get_recent_workouts`, `fitness_get_workout` — both importable, both correctly
  signed
- commit `e343bb7` — FOUND
- commit `2dc0420` — FOUND
