---
phase: 06-mcp-tools
reviewed: 2026-09-01T00:00:00Z
depth: standard
files_reviewed: 28
files_reviewed_list:
  - backend/app/analytics/records.py
  - backend/app/analytics/rollup.py
  - backend/app/cli.py
  - backend/app/config.py
  - backend/app/db/repositories/workouts.py
  - backend/app/mcp/server.py
  - backend/app/mcp/tools/_common.py
  - backend/app/mcp/tools/body.py
  - backend/app/mcp/tools/comparison.py
  - backend/app/mcp/tools/progression.py
  - backend/app/mcp/tools/records.py
  - backend/app/mcp/tools/schemas.py
  - backend/app/mcp/tools/summary.py
  - backend/app/mcp/tools/volume.py
  - backend/app/mcp/tools/workouts.py
  - backend/tests/conftest.py
  - backend/tests/test_analytics_rollup.py
  - backend/tests/test_mcp_auth.py
  - backend/tests/test_mcp_isolation.py
  - backend/tests/test_mcp_mount.py
  - backend/tests/test_mcp_readonly.py
  - backend/tests/test_mcp_schemas.py
  - backend/tests/test_mcp_tool_budget.py
  - backend/tests/test_mcp_tool_schemas.py
  - backend/tests/test_mcp_tools.py
  - backend/tests/test_mcp_window.py
  - backend/tests/test_repository_workouts.py
  - backend/tests/test_secret_redaction.py
findings:
  critical: 0
  warning: 1
  info: 1
  total: 2
status: issues_found
---

# Phase 06: Code Review Report

**Reviewed:** 2026-09-01T00:00:00Z
**Depth:** standard
**Files Reviewed:** 28
**Status:** issues_found

## Summary

This phase adds twelve read-only MCP tools plus the shared `_common.py`/`schemas.py`
infrastructure on top of the Phase 4/5 analytics layer, and it is unusually
well-defended: `read_only_session` enforces read-only at the PostgreSQL
transaction level (not just via `ToolAnnotations` hints), `safe_tool` closes a
verified exception-leak channel in the MCP SDK, static analysis tests
(`test_mcp_isolation.py`) forbid raw SQL, floats, exception interpolation and
`app.integrations` imports across the whole package, and a response-budget
suite measures actual wire bytes against published caps rather than trusting
estimates. `backend/tests/test_mcp_tools.py` (the largest test file in scope, ~1,000 lines) drives every one of the thirteen tools through real seeded history end to end and reads as a thorough behavioral suite with no gaps found. `uv run ruff check` passes clean on every reviewed source file.

Two issues were found, both narrow. Neither is a security vulnerability;
both are pre-existing correctness/documentation gaps rather than anything
introduced carelessly in this phase's design. They are recorded below in case
they were not yet tracked.

## Warnings

### WR-01: `_duration_minutes` does not guard against `end_time < start_time`

**File:** `backend/app/db/repositories/workouts.py:113-121`

**Issue:** `_duration_minutes` computes `round((end - start).total_seconds() / 60)`
with no check that `end >= start`. Both `Workout.start_time` and
`Workout.end_time` are `NOT NULL` `DateTime(timezone=True)` columns with no
database `CHECK` constraint enforcing ordering (confirmed in
`backend/app/db/models/workout.py`), and neither the Hevy client schema
(`backend/app/integrations/hevy/schemas.py`) nor the upsert path
(`backend/app/integrations/hevy/workouts.py`) validates that a synced or
subsequently-edited workout's `end_time` is not earlier than its
`start_time`. If such a row ever exists — a manually edited Hevy workout, a
provider bug, or a future migration/import path — `_duration_minutes` silently
returns a negative integer. That value flows unguarded into
`WorkoutSummaryRow.duration_minutes` (used by `fitness_get_recent_workouts`)
and `WorkoutDetailRow.duration_minutes` (used by `fitness_get_workout`), both
of which declare `duration_minutes: int` with no `ge=0` bound in
`app/mcp/tools/schemas.py`. Claude would receive and could report a
nonsensical negative session duration with no signal that anything was wrong
— exactly the class of "wrong answer with no indication" this phase's own
design philosophy (`safe_tool`, `data_available`, `*_truncated`) otherwise
takes care to avoid. No test in `test_repository_workouts.py` exercises this
edge case, which is why it currently ships unnoticed.

**Fix:**
```python
def _duration_minutes(start: dt.datetime, end: dt.datetime) -> int:
    """Whole minutes between two aware instants, rounded to nearest.

    Both columns are NOT NULL, but neither carries a DB CHECK that `end >=
    start`, and nothing upstream validates it on sync or edit. Clamp rather
    than let a corrupted row report a negative session length to Claude.
    """
    seconds = (end - start).total_seconds()
    if seconds < 0:
        log.warning("workout_duration_negative", start=start.isoformat(), end=end.isoformat())
        return 0
    return round(seconds / _SECONDS_PER_MINUTE)
```
(Requires a module-level `log = structlog.get_logger()` in this file, which
it does not currently import.) An equally valid alternative consistent with
this codebase's "never invent a false zero" convention would be to make
`duration_minutes` `int | None` end-to-end and report `None` for an
inconsistent record rather than `0` — but that is a larger, deliberate design
change and should be a conscious choice rather than a side effect of this fix.

## Info

### IN-01: Stale docstring reference to a tool name that does not exist

**File:** `backend/app/mcp/tools/schemas.py:196`

**Issue:** `WorkoutSummary`'s docstring says: *"This omission is what keeps the
list compact regardless of how many workouts are requested --
`fitness_get_workout_detail` exists to expand exactly one of these on
demand."* No tool named `fitness_get_workout_detail` exists or is registered;
the actual tool is `fitness_get_workout` (see `app/mcp/tools/workouts.py` and
the registry in `app/mcp/server.py`/`EXPECTED_TOOLS` in
`test_mcp_tool_schemas.py`). This is documentation-only — it does not affect
runtime behavior or the published tool schema — but it is misleading to a
future reader trying to find the referenced tool by name.

**Fix:**
```python
    This omission is what keeps the list compact regardless of how many workouts are requested --
    ``fitness_get_workout`` exists to expand exactly one of these on demand.
```

---

_Reviewed: 2026-09-01T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
