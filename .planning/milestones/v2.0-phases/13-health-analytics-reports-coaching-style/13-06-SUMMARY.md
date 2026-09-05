---
phase: 13-health-analytics-reports-coaching-style
plan: 06
subsystem: mcp
tags: [mcp, health, nutrition, activity, tools]
dependency-graph:
  requires: ["13-02", "13-04"]
  provides: ["fitness_get_activity_trend", "fitness_get_nutrition_trend"]
  affects: ["backend/app/mcp/server.py", "docs/coaching-instructions.md"]
tech-stack:
  added: []
  patterns:
    - "Zero-argument, today-anchored MCP trend tool (mirrors fitness_get_body_weight_trend)"
    - "Analytics result embedded whole via a data_available + optional-field response model"
key-files:
  created:
    - backend/app/mcp/tools/health.py
  modified:
    - backend/app/mcp/tools/schemas.py
    - backend/app/mcp/server.py
    - backend/tests/test_mcp_tool_schemas.py
    - backend/tests/test_mcp_tools.py
    - backend/tests/test_mcp_isolation.py
    - backend/tests/test_mcp_mount.py
    - backend/tests/test_mcp_auth.py
    - backend/tests/test_mcp_tool_budget.py
    - docs/coaching-instructions.md
decisions: []
metrics:
  duration: "~45 minutes"
  completed: "2026-09-04"
---

# Phase 13 Plan 06: Activity and Nutrition MCP Tools Summary

Exposed HEALTH-12 and NUTR-06 as two new dedicated, read-only, zero-argument MCP tools
(`fitness_get_activity_trend`, `fitness_get_nutrition_trend`), bringing the registry to
eighteen tools with all five structural guards updated in lockstep.

## What Was Built

**`backend/app/mcp/tools/health.py` (new).** Two tools following `body.py`'s exact
zero-argument-trend template: `resolve_user_id` -> `read_only_session` -> one analytics await
-> response constructed outside the session. Each has a `_degraded_*` factory returning
`data_available=False, trend=None` so an outage can never be narrated as "no activity"/"no
nutrition". Both are `@safe_tool`-guarded with the decorator on the line immediately preceding
`async def`, satisfying the isolation-guard's adjacency check.

**`backend/app/mcp/tools/schemas.py`.** Added `ActivityTrendResponse` and
`NutritionTrendResponse`, each composing (never restating) `ActivityTrendResult`/
`NutritionTrendResult` from `app.analytics.schemas` as a single optional field beside
`data_available: bool`.

**`backend/app/mcp/server.py`.** Registered both tools inside the `_TOOLS` loop (never a
hand-rolled `add_tool` call), placed immediately after `fitness_get_body_weight_trend` so the
trend family stays contiguous, both carrying `annotations=READ_ONLY`.

**All five registry guards updated:**
1. `test_mcp_tool_schemas.py` -- `EXPECTED_TOOLS` gained both names; the whole-registry test
   renamed `test_tool_registry_is_exactly_the_sixteen` -> `..._eighteen`; docstring counts
   updated ("fifteen" -> "seventeen" read-only tools, "sixteen" -> "eighteen" tools). No
   `EXPECTED_CAPS` entries added -- both tools take no parameters, which is the point.
2. `test_mcp_tools.py` -- `MINIMAL_TOOL_ARGUMENTS` gained both `{}"` entries; two new
   behavioural tests added (`test_activity_trend_returns_all_five_metrics`,
   `test_nutrition_trend_returns_all_seven_metrics_with_independent_coverage`), both seeded
   through `committed_history`/`GoldenBuilder.health_metric`, never `golden_workout`, per the
   module's own warning that a tool opens its own transaction and cannot see uncommitted rows.
3. `test_mcp_tool_budget.py` -- `WORST_CASE_ARGS` gained both `{}` entries; `BUDGETS` gained
   both entries at measured + ~30% headroom (see Measurements below).
4. `test_mcp_isolation.py` -- the literal tool-coroutine count raised from 15 to 17, with the
   comment's changelog extended per Plan 12-04's own pattern.
5. `docs/coaching-instructions.md` -- two new rows in the "Which tool answers which question"
   table, and the metadata-envelope table's `freshness.resources` parenthetical extended with
   `activity`, `nutrition`. Document stays at 8,165 characters, well under the 9,000 ceiling.

Also updated the two cross-file references to the renamed registry test
(`test_mcp_mount.py:119`, `test_mcp_auth.py:573`) so they name
`test_tool_registry_is_exactly_the_eighteen` rather than a test that no longer exists.

## Measurements (Task 3)

Measured via a throwaway instrumented test against `worst_case_history` (45 seeded Apple
Health days x 12 registry metrics), removed before committing:

| Tool | Measured bytes (full `CallToolResult`) | Budget (measured + ~30% headroom) |
|---|---|---|
| `fitness_get_activity_trend` | 10,861 | 16,384 |
| `fitness_get_nutrition_trend` | 14,875 | 20,480 |

Both are fixed-shape objects (5 and 7 metrics x 3 windows respectively, no caller-widenable
list), so neither grows with data once the 30-day fetch window is saturated -- the budget does
not need to account for an unbounded list the way `fitness_compare_periods` does.

## Verification

- `cd backend && uv run pytest -q` (full suite): **1009 passed, 11 skipped**
- `cd backend && uv run ruff check .`: all checks passed
- `cd backend && uv run mypy app/mcp/tools/health.py app/mcp/tools/schemas.py app/mcp/server.py`:
  no issues in 3 source files
- `wc -c docs/coaching-instructions.md`: 8,165 (under 9,000)
- Task-scoped acceptance-criteria greps (registry loop count, guard renames, literal counts,
  coaching-doc rows) all confirmed individually during execution.

## Deviations from Plan

None -- plan executed exactly as written. The one instrumented measurement script used for
Task 3 was a throwaway test file (`backend/tests/test_measure_budget_scratch.py`), removed
before the Task 3 commit; `git status --short` confirmed no untracked files remained.

## Known Stubs

None. Both tools are fully wired: real analytics functions, real response models, real
registration, real guard coverage, real measured budgets.

## Self-Check: PASSED

- FOUND: backend/app/mcp/tools/health.py
- FOUND: backend/app/mcp/tools/schemas.py (ActivityTrendResponse, NutritionTrendResponse)
- FOUND: backend/app/mcp/server.py (fitness_get_activity_trend / fitness_get_nutrition_trend
  registered in `_TOOLS`)
- FOUND commit c4c0d91 (Task 1)
- FOUND commit 1ae9d41 (Task 2)
- FOUND commit 121c8e5 (Task 3)
