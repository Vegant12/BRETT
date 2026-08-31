---
phase: 06-mcp-tools
plan: 01
subsystem: api
tags: [mcp, sqlalchemy, postgres, structlog, pep695, read-only-transaction, timezone]

# Dependency graph
requires:
  - phase: 01-backend-foundation
    provides: "app/config.py Settings, app/core/time.py (utc_now, local_day, snap_local_week_range, local_week_spine), users.timezone"
  - phase: 02-deploy-connector-auth-spike
    provides: "app/mcp/context.py AppContext + lifespan-wired sessionmaker, app/mcp/tools/ping.py tool conventions"
  - phase: 03-hevy-integration-normalization
    provides: "ExerciseTemplate model, PROVIDER_HEVY constant"
  - phase: 04-volume-frequency-analytics
    provides: "app/analytics/rollup.py bounded-constant + resolve_window conventions"
provides:
  - "backend/app/mcp/tools/_common.py: the single module every Phase 6 tool imports"
  - "read_only_session — a server-enforced READ ONLY transaction (MCP-05, T-06-03)"
  - "week_window / window_from_weeks — Monday-anchored weeks -> inclusive local date range (D-03, D-04)"
  - "local_timezone / local_today — the one timezone read in the MCP layer (FOUND-03, D-13)"
  - "find_templates_by_title — bound-parameter, multi-match exercise name lookup (D-01, D-02)"
  - "safe_tool — the decorator that stops any exception reaching Claude as text (MCP-06, T-06-01)"
  - "truncate — capped list plus truncated flag plus total_available"
  - "Ten per-tool response cap constants in one block"
  - "app.config.DEFAULT_USER_ID — the single application-side identity constant"
affects: [06-02, 06-03, 06-04, 06-05, 06-06, 06-07, 06-08, 06-09, 06-10, 06-11]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "PEP 695 type parameters (`def f[T](...)`) for generic helpers, required by Ruff UP047 at target-version py313"
    - "Server-enforced read-only transactions via the postgresql_readonly execution option applied before the first query"
    - "Monday-anchored week windows so a downstream snap_local_week_range cannot widen the row count"
    - "safe_tool degraded-payload decorator with functools.wraps to preserve the SDK-visible signature and docstring"

key-files:
  created:
    - backend/app/mcp/tools/_common.py
    - backend/tests/test_mcp_window.py
  modified:
    - backend/app/config.py
    - backend/app/cli.py

key-decisions:
  - "DEFAULT_USER_ID is a plain module constant in app/config.py, not a Settings field: it is a migration-fixed identity, and env-overridability would allow pointing production at a user_id with no users row behind it"
  - "PEP 695 type parameters replace the plan's module-level ParamSpec/TypeVar objects — semantically identical binding, but Ruff UP047 rejects the older form at this repo's py313 target, and a noqa would be a suppression standing in for a two-character change"
  - "time_machine.travel is given an aware datetime rather than an ISO string: string parsing routes through dateutil, which this project does not depend on and the plan forbids adding"
  - "resolve_user_id accepts an unused ctx on purpose so the future subject->user seam already has the value it will need"

patterns-established:
  - "One cap constant per tool, each with a comment naming the requirement ID and the concrete consequence of the number"
  - "Docstrings state the counter-intuitive rule and the measured consequence of breaking it, not what the function does"
  - "Every truncated list is returned alongside its truncated flag and total_available count"

requirements-completed: [MCP-02, MCP-03, MCP-05, MCP-06]

# Metrics
duration: 18min
completed: 2026-08-31
---

# Phase 6 Plan 01: MCP Tool Common Module Summary

**A single `app/mcp/tools/_common.py` giving every Phase 6 tool a PostgreSQL-enforced read-only session, Monday-anchored `weeks` → date-range conversion off the user's local today, bound-parameter exercise-name lookup, a `safe_tool` guard that keeps asyncpg DSNs out of Claude's context, and ten response-cap constants.**

## Performance

- **Duration:** 18 min
- **Started:** 2026-08-31T18:47:00Z
- **Completed:** 2026-08-31T19:05:00Z
- **Tasks:** 3
- **Files modified:** 4 (2 created, 2 modified)

## Accomplishments

- `read_only_session` opens the transaction READ ONLY at the server, so an INSERT/UPDATE/DELETE from a tool raises `ReadOnlySQLTransactionError` from PostgreSQL rather than relying on `ToolAnnotations(read_only_hint=True)`, which the SDK documents as a non-enforcing hint.
- `week_window` is Monday-anchored, which is what makes `weeks=N` survive the volume tools' own `snap_local_week_range` as exactly N week rows. Proven for N in 1, 4, 12, 52 across all seven weekdays — 61 parametrized assertions, container-free.
- `safe_tool` closes the verified `mcp 2.0.0` leak where `MCPServer._handle_call_tool` returns `str(exception)` to the model verbatim; an asyncpg connection error carries the full DSN and structlog's redaction never sees that channel.
- `DEFAULT_USER_ID` promoted from `cli.py` into `app/config.py`, so the CLI and the MCP layer share one application-side identity while the migration and conftest copies stay deliberately duplicated.

## Task Commits

1. **Task 1: Promote DEFAULT_USER_ID to app/config.py** — `fe7026b` (refactor)
2. **Task 2: Create backend/app/mcp/tools/_common.py** — `3377cfc` (feat)
3. **Task 3: Create backend/tests/test_mcp_window.py** — `db06778` (test)

## Files Created/Modified

- `backend/app/mcp/tools/_common.py` (created, 304 lines) — `resolve_user_id`, `read_only_session`, `week_window`, `local_timezone`, `local_today`, `window_from_weeks`, `find_templates_by_title`, `safe_tool`, `truncate`, plus `MAX_WEEKS`, `MAX_SUMMARY_WEEKS`, `MAX_RECENT_WORKOUTS`, `MAX_CANDIDATES`, `MAX_WORKOUT_SETS`, `MAX_FREQUENCY_EXERCISES`, `MAX_PLATEAU_EXERCISES`, `MAX_PROGRESSION_POINTS`, `MAX_COMPARISON_ITEMS`, `MAX_COMPARISON_PERIOD_DAYS`.
- `backend/tests/test_mcp_window.py` (created, 131 lines) — seven test functions, 61 parametrized cases, no container, not marked `integration`.
- `backend/app/config.py` (modified) — added `import uuid` and the `DEFAULT_USER_ID` module constant beside `_SECRET_FIELDS`.
- `backend/app/cli.py` (modified) — imports `DEFAULT_USER_ID` from `app.config` instead of defining its own; the argparse `default=` use site is unchanged.

## Decisions Made

- **PEP 695 over module-level `ParamSpec`/`TypeVar`.** The plan specified the older form verbatim, but Ruff's `UP047` rejects it at this repo's `target-version = "py313"`, and the plan's own `<verify>` block requires `ruff check backend/app/mcp` to pass. `def safe_tool[**P, R](...)` and `def truncate[T](...)` bind the variables to exactly the same scope, so this is a syntax translation and not a typing change. mypy 2.3.1 accepts both. A comment in the file records why.
- **`time_machine.travel` takes an aware datetime, not the plan's `"2026-08-30T17:30:00Z"` string.** `python-dateutil` is not installed and is not in `pyproject.toml`; time_machine's string parsing requires it. `test_time.py` already uses aware datetimes and documents the naive-datetime `TypeError` trap, so this matches established style and adds no dependency (which the plan's verification forbids).
- **The `postgresql_readonly` literal appears exactly once in the file.** The docstring describes the option in prose rather than repeating the string, so a grep for the flag returns the one line that actually sets it.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Converted `safe_tool` and `truncate` to PEP 695 type parameters**

- **Found during:** Task 2 (Create `_common.py`)
- **Issue:** The plan's verbatim code used `P = ParamSpec("P")` / `R = TypeVar("R")` at module scope. Ruff `UP047` ("Generic function should use type parameters") failed on both functions, so `uv run ruff check backend/app/mcp` — the task's own automated verification — did not pass.
- **Fix:** Rewrote the two signatures as `def safe_tool[**P, R](...)` and `def truncate[T](...)`, dropped the now-unused `from typing import ParamSpec, TypeVar` import, and added a comment recording that the binding is identical and why a `noqa` was rejected.
- **Files modified:** `backend/app/mcp/tools/_common.py`
- **Verification:** `ruff check backend/app/mcp` and `mypy backend/app/mcp/tools/_common.py` both clean; `truncate([1,2,3,4], 2)` returns `([1, 2], True, 4)`.
- **Committed in:** `3377cfc` (Task 2 commit)

**2. [Rule 3 - Blocking] `time_machine.travel` given an aware datetime instead of an ISO string**

- **Found during:** Task 3 (Create `test_mcp_window.py`)
- **Issue:** The plan specified `time_machine.travel("2026-08-30T17:30:00Z", tick=False)`. time_machine parses string arguments via `dateutil`, which is not installed in this project and is not a declared dependency. The test would have raised at collection.
- **Fix:** Used `dt.datetime(2026, 8, 30, 17, 30, tzinfo=dt.UTC)`, matching `test_time.py`'s existing convention. The test asserts the same three facts the plan named.
- **Files modified:** `backend/tests/test_mcp_window.py`
- **Verification:** `pytest backend/tests/test_mcp_window.py -q` → 61 passed; `git diff --stat pyproject.toml uv.lock` shows no change.
- **Committed in:** `db06778` (Task 3 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 3 — blocking)
**Impact on plan:** Both were mechanical adaptations to this repo's actual lint config and dependency set. No behaviour, no scope change, no new dependency. Every acceptance criterion in the plan still holds.

## Threat Model Coverage

| Threat ID | Disposition | Where it landed |
|-----------|-------------|-----------------|
| T-06-01 | mitigate | `safe_tool` — catches every exception, routes detail to `log.exception("mcp_tool_failed")`, returns the caller's degraded payload. Static guard due in 06-09, runtime leak test in 06-11 |
| T-06-02 | mitigate | `resolve_user_id(ctx)` resolves server-side from `app.config.DEFAULT_USER_ID`; `user_id` is never a tool parameter. Asserted in 06-09 |
| T-06-03 | mitigate | `read_only_session` applies the read-only execution option before the first query and rolls back unconditionally. Runtime proof due in 06-10 |
| T-06-04 | mitigate | `find_templates_by_title` uses `func.lower(col) == bound_param`; no `text(` import in the module at all |
| T-06-05 | mitigate | Ten cap constants defined here; `truncate` forces `truncated` + `total_available`. Byte budgets in 06-10 |
| T-06-08 | accept | Unchanged — the SDK echoes back the model's own argument, never server state |

## Verification Results

- `uv run pytest backend/tests -q -m "not integration"` — **318 passed, 236 deselected** (was 257 passed before this plan; +61 from `test_mcp_window.py`)
- `uv run ruff check backend/app backend/tests` — **All checks passed**
- `uv run mypy backend/app/mcp/tools/_common.py backend/app/config.py backend/app/cli.py` — **Success: no issues found in 3 source files**
- `git diff --stat pyproject.toml uv.lock` — **no change** (no dependency drift)
- `grep -c 'from sqlalchemy import text' backend/app/mcp/tools/_common.py` → `0`
- `grep -c 'postgresql_readonly' backend/app/mcp/tools/_common.py` → `1`
- All 19 named exports importable and present.

## Issues Encountered

None beyond the two blocking deviations above, both resolved inside their own task.

## Known Stubs

None. Every helper is fully implemented; nothing returns placeholder data.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Wave 2 plans (06-02 onward) can import everything from `app.mcp.tools._common` immediately. All ten cap constants and all nine helpers are live and typed.
- Two facts about `read_only_session` are asserted only in prose so far — that the option works at the default isolation level, and that the flag does not leak back into the pooled connection. Plan 06-10 owns the runtime proof against a real container; nothing in this plan can demonstrate them without one.
- Plan 06-09's static guard should ban `text(` under `app/mcp/` except `ping.py`. `_common.py` is already compliant.
- `MAX_SUMMARY_WEEKS`, `MAX_FREQUENCY_EXERCISES`, `MAX_PLATEAU_EXERCISES` and `MAX_COMPARISON_ITEMS` are defined but not yet referenced by any tool — expected, since their tools land in later plans.

## Requirements Note

`requirements-completed` above lists the four IDs from this plan's frontmatter, but
`.planning/REQUIREMENTS.md` was **deliberately not** edited and its checkboxes remain unticked.
MCP-02, MCP-03, MCP-05 and MCP-06 are phase-wide and are shared by all eleven Phase 6 plans —
MCP-02 alone requires eleven tools, none of which exist yet. Ticking them here would record a
completion that has not happened, and eleven parallel worktree agents editing one shared file
would conflict. The orchestrator should mark them complete once the phase closes.

## Self-Check: PASSED

All claimed files exist on disk (`_common.py`, `test_mcp_window.py`, `config.py`, `cli.py`,
`06-01-SUMMARY.md`) and all three task commits are present in `git log` (`fe7026b`, `3377cfc`,
`db06778`). Working tree clean after each commit; no untracked files left behind.

---
*Phase: 06-mcp-tools*
*Completed: 2026-08-31*
