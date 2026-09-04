---
phase: 11-body-measurement-history
plan: 03
subsystem: mcp
tags: [mcp, pydantic, strenum, pytest, body-composition]

# Dependency graph
requires:
  - phase: 11-body-measurement-history
    plan: 01
    provides: BodyMeasurementMetric StrEnum, BodyMeasurementTrendResult schema
  - phase: 11-body-measurement-history
    plan: 02
    provides: get_body_measurement_trend, the analytics function this plan exposes as an MCP tool
provides:
  - fitness_get_body_measurement_trend -- the 14th read-only MCP tool
  - BodyMeasurementTrendResponse wire model in mcp/tools/schemas.py
  - A measured MCP-03 byte budget (2,048) for the new tool
  - docs/coaching-instructions.md routing entry for BODY-05
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "A closed StrEnum tool argument (BodyMeasurementMetric) is the first Phase 6-11 MCP argument
      that is neither a window nor a free-text name -- the SDK derives inputSchema's enum from it,
      so an unrecognized value is refused at the schema layer before any code in this repo runs"

key-files:
  created: []
  modified:
    - backend/app/mcp/tools/schemas.py
    - backend/app/mcp/tools/body.py
    - backend/app/mcp/server.py
    - backend/tests/test_mcp_tool_schemas.py
    - backend/tests/test_mcp_tool_budget.py
    - backend/tests/test_mcp_tools.py
    - backend/tests/test_mcp_isolation.py
    - backend/tests/test_mcp_auth.py
    - backend/tests/test_mcp_mount.py
    - docs/coaching-instructions.md

key-decisions:
  - "Fixed a DTZ011 lint violation the plan's own literal test code introduced (dt.date.today())
    by switching to the file's existing utc_now().date() convention, matching every other
    anchor-date computation in test_mcp_tools.py"
  - "Reordered the budget-table comment for fitness_get_body_measurement_trend so the line
    immediately preceding the dict entry contains the word 'Measured', satisfying the plan's
    literal grep acceptance criterion while keeping the full rationale in the same three-line block"

patterns-established:
  - "fitness_get_body_measurement_trend sits immediately before fitness_get_body_weight_trend in
    both the EXPECTED_TOOLS frozenset and the server.py _TOOLS tuple, grouping the two body tools"

requirements-completed: [BODY-05]

# Metrics
duration: ~45min
completed: 2026-09-04
---

# Phase 11 Plan 03: Body Measurement MCP Tool Summary

**Registered `fitness_get_body_measurement_trend` as the fourteenth read-only MCP tool, wrapping Plan 02's analytics function behind a closed 16-member metric enum, and brought all six hand-maintained structural drift guards plus the coaching-instructions doc back to green in the same wave.**

## Performance

- **Duration:** ~45 min
- **Tasks:** 3 completed
- **Files modified:** 10 (0 created, 10 extended)

## Accomplishments
- `BodyMeasurementTrendResponse` added to `mcp/tools/schemas.py`, composing `BodyMeasurementTrendResult` verbatim; `fitness_get_body_measurement_trend` added to `mcp/tools/body.py`, `@safe_tool`-guarded, resolving the user server-side, opening a `read_only_session`, and taking one `Annotated[BodyMeasurementMetric, Field(...)]` argument -- the first MCP argument in this codebase that is neither a window nor a free-text exercise name
- Registered through the shared `_TOOLS` loop in `server.py` with `READ_ONLY` annotations, immediately before `fitness_get_body_weight_trend`; `fitness_get_body_weight_trend` and `fitness_get_recomposition_status` are byte-for-byte unchanged except for the module docstring explaining the new tool's argument
- All six structural drift guards updated: `EXPECTED_TOOLS` (now fourteen, test renamed to `..._is_exactly_the_fourteen`), a MEASURED 2,048-byte budget entry (1,351 bytes measured against the worst-case history), `MINIMAL_TOOL_ARGUMENTS` (also covers `test_secret_redaction.py`), the `@safe_tool` coroutine count raised from 12 to 13, and two stale cross-references to the renamed registry test fixed in `test_mcp_auth.py`/`test_mcp_mount.py`
- Two new integration tests: a real latest-vs-earliest comparison against seeded `waist_cm` readings (85.00 at -60 days, 81.50 today, asserting `delta_value == -3.50`), and a schema-level rejection proof for an unrecognized metric (`elbow_cm`) with a leak-marker scan
- `docs/coaching-instructions.md` gained one routing-table row and one example-question line; document is 7,439 characters, under the 9,000-character paste ceiling
- Phase gate: full backend suite green -- 920 passed, 11 skipped. `ruff check backend/`, `mypy backend/app/` both clean. `ruff format --check backend/app/mcp/` clean; the repo-wide `ruff format --check backend/` count of pre-existing unrelated files stayed at 18 (documented in Plan 01/02's summaries), confirmed by diffing against `HEAD` that neither touched line was introduced by this plan

## Task Commits

Each task was committed atomically:

1. **Task 1: The fourteenth tool -- wire model, tool function, registration** - `7579565` (feat)
2. **Task 2: The six structural drift guards** - `249b13b` (test)
3. **Task 3: Coaching-doc entry and the full-suite phase gate** - `9e2b138` (docs)

## Files Created/Modified
- `backend/app/mcp/tools/schemas.py` - Added `BodyMeasurementTrendResponse`, imported `BodyMeasurementTrendResult`
- `backend/app/mcp/tools/body.py` - Added `_degraded_measurement_trend`, `fitness_get_body_measurement_trend`; extended module docstring to explain the new argument-taking tool alongside the two argument-free ones
- `backend/app/mcp/server.py` - Added the import and one `_TOOLS` tuple entry
- `backend/tests/test_mcp_tool_schemas.py` - `EXPECTED_TOOLS` gains the name; test renamed to `test_tool_registry_is_exactly_the_fourteen`; docstring updated
- `backend/tests/test_mcp_tool_budget.py` - `BUDGETS` gains a measured 2,048-byte entry; `WORST_CASE_ARGS` gains `{"metric": "waist_cm"}`
- `backend/tests/test_mcp_tools.py` - `MINIMAL_TOOL_ARGUMENTS` gains the entry; docstring phrasing updated (fourteen/thirteen); two new integration tests added
- `backend/tests/test_mcp_isolation.py` - `assert len(found) == 12` raised to `13`, comment and failure message updated
- `backend/tests/test_mcp_auth.py` - Stale cross-reference to the renamed test fixed
- `backend/tests/test_mcp_mount.py` - Stale cross-reference and "thirteen registered" phrasing fixed
- `docs/coaching-instructions.md` - One routing-table row, one example-question line
- `.planning/phases/11-body-measurement-history/deferred-items.md` (new) - Two pre-existing, out-of-scope `ruff format` findings, documented rather than fixed

## Decisions Made
- Reworded the budget-table comment for the new entry so the line immediately preceding the dict key contains the word "Measured" (rather than ending on a different clause), satisfying the plan's literal grep-based acceptance criterion while keeping the full three-line rationale.
- Fixed a self-introduced DTZ011 lint violation (see Deviations) by using the file's existing `utc_now()` import rather than adding a new one.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Plan's literal test code used `dt.date.today()`, tripping ruff's DTZ011**
- **Found during:** Task 2 verification (`ruff check backend/tests/test_mcp_tools.py`)
- **Issue:** The plan's action text for `test_body_measurement_trend_compares_latest_against_earliest` uses `today = dt.date.today()`, which `flake8-datetimez` (ruff's `DTZ011` rule, part of this project's enabled `ASVS`-adjacent lint set) rejects as timezone-naive.
- **Fix:** Replaced with `today = utc_now().date()`, using the module's already-imported `utc_now` helper -- the exact pattern `_reference_anchor()` in the same file already uses for the same reason.
- **Files modified:** `backend/tests/test_mcp_tools.py`
- **Verification:** `uv run ruff check backend/tests/test_mcp_tools.py` -> All checks passed; `uv run pytest -m integration backend/tests/test_mcp_tools.py -k body_measurement_trend -q` -> 2 passed (re-run after the fix, confirming no collision with `_seed_reference_history`'s own body-measurement rows)
- **Committed in:** `249b13b` (part of Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 lint bug introduced by following the plan's literal example code)
**Impact on plan:** No semantic change -- the test's seeded dates and assertions are identical; only the date-construction call changed.

## Issues Encountered

**Acceptance-criteria grep mismatch (not fixed, documented only):** Task 1's acceptance criterion `grep -c "add_tool" backend/app/mcp/server.py` returns 1 expects exactly one occurrence, but the file already contained 4 matches before this plan touched it (the `fitness_ping` registration call, the shared loop call, and two comments mentioning `add_tool` by name). Confirmed via `git show HEAD:backend/app/mcp/server.py | grep -c add_tool` -> `4`, i.e. unrelated to this plan's one-entry `_TOOLS` tuple addition. Not fixed, since the criterion's intent ("no hand-written registration outside the shared loop") is independently verified by inspection: the new tool has no `add_tool` call of its own.

**Two pre-existing, out-of-scope `ruff format` findings** (documented in `deferred-items.md`, not fixed per the scope-boundary rule):
- `backend/app/mcp/server.py:182` -- an unrelated tuple-entry description (`fitness_get_muscle_group_volume`) that `ruff format` would reflow onto one line. Present verbatim in `HEAD` (Phase 7 commit `d04cd15`), never touched by this plan's diff.
- `backend/tests/test_mcp_isolation.py:73` -- `ruff format` wants an extra blank line before `def _mcp_modules()`. Confirmed present in `HEAD` before this plan's two one-line edits (`12`->`13`) to the same file.

Both are part of the 18-file repo-wide `ruff format --check backend/` count Plan 01 and Plan 02 already documented as pre-existing and unrelated; this plan's own `<verify>` blocks scope the format check to `backend/app/mcp/` (clean) rather than the whole repo.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 11 (Body Measurement History) is now feature-complete: BODY-05 ships as `fitness_get_body_measurement_trend`, the 14th MCP tool, with its analytics function (Plan 02) and schema/metadata foundations (Plan 01).
- The live MCP registry serves exactly 14 tools; `EXPECTED_TOOLS` names them exactly; no occurrence of `test_tool_registry_is_exactly_the_thirteen` remains anywhere under `backend/tests/`.
- `fitness_get_body_weight_trend`'s code, response model and behavioural test are unchanged and still green -- BODY-01 fully unregressed (confirmed via empty `git diff` on `backend/app/analytics/bodyweight.py`).
- Full backend suite (`uv run pytest backend/tests -q`): 920 passed, 11 skipped. `ruff check`/`mypy backend/app/` clean.
- No blockers for the next phase.

---
*Phase: 11-body-measurement-history*
*Completed: 2026-09-04*

## Self-Check: PASSED

All claimed files exist (`backend/app/mcp/tools/schemas.py`, `backend/app/mcp/tools/body.py`,
`backend/app/mcp/server.py`, `backend/tests/test_mcp_tool_schemas.py`,
`backend/tests/test_mcp_tool_budget.py`, `backend/tests/test_mcp_tools.py`,
`backend/tests/test_mcp_isolation.py`, `backend/tests/test_mcp_auth.py`,
`backend/tests/test_mcp_mount.py`, `docs/coaching-instructions.md`,
`.planning/phases/11-body-measurement-history/deferred-items.md`, this SUMMARY.md), and all three
task commits (`7579565`, `249b13b`, `9e2b138`) are present in `git log --oneline --all`.
