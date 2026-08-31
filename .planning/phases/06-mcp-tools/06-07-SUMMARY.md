---
phase: 06-mcp-tools
plan: 07
subsystem: api
tags: [mcp, mcp-sdk-v2, pydantic, analytics, comparison, bodyweight, recomposition]

# Dependency graph
requires:
  - phase: 06-mcp-tools plan 06-01
    provides: "_common.py — MAX_COMPARISON_ITEMS, MAX_COMPARISON_PERIOD_DAYS, resolve_user_id, read_only_session, safe_tool, truncate"
  - phase: 06-mcp-tools plan 06-02
    provides: "schemas.py — PeriodComparisonResponse, BodyWeightTrendResponse, RecompositionResponse"
  - phase: 05-progression-records-recomposition-analytics
    provides: "compare_periods (CMP-01), get_body_weight_trend (BODY-01), get_recomposition_status (BODY-02)"
provides:
  - "fitness_compare_periods — the phase's only explicit-date tool (D-06), per-week normalized, both exercise lists capped by largest movement"
  - "fitness_get_body_weight_trend — no window parameter (D-07), analytics result embedded verbatim"
  - "fitness_get_recomposition_status — no window parameter (D-07), RecompositionResult embedded whole so the disclaimer survives serialization"
  - "The in-body argument-validation pattern for date arguments, which cannot carry a Field bound"
affects: [06-08 tool registration, 06-09 schema/isolation guards, 06-10 response budgets, 06-11 behavioural tests]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Date-argument validation returns a degraded response instead of raising (Pitfall 3)"
    - "Truncation sorted by largest movement, not by the analytics layer's id ordering"
    - "Whole-result embedding as the structural guarantee for a required field"

key-files:
  created:
    - backend/app/mcp/tools/comparison.py
    - backend/app/mcp/tools/body.py
  modified: []

key-decisions:
  - "fitness_compare_periods keeps four explicit dates rather than the phase-wide integer weeks convention (D-06); the module docstring says so and tells a future reader not to 'fix' it"
  - "Invalid date ranges return data_available=False rather than raising, because an exception message reaches Claude verbatim and the four dates are the model's own arguments"
  - "Both per-exercise comparison lists are sorted by absolute delta before truncation, so the cap keeps the biggest movements rather than the alphabetically-first 25"
  - "The recomposition tool is named fitness_get_recomposition_status, matching the analytics function it wraps, not the blueprint's indicative '..._summary' spelling"
  - "body.py carries no module logger: neither tool has a branch of its own to report, and an unused logger reads as a missing log line"

patterns-established:
  - "Argument validation in the tool body: the only place in Phase 6 where a tool validates its own arguments, because dt.date cannot carry Field(ge=/le=) the way int can"
  - "Degraded-response factories keep the truncation flag/total pairs present and honest (False/0) rather than omitting them"
  - "A required downstream field is protected by embedding its whole parent model, never by hand-listing fields"

requirements-completed: [MCP-02, MCP-03, MCP-05, MCP-06]

# Metrics
duration: 18min
completed: 2026-08-31
---

# Phase 6 Plan 07: Comparison & Body Tools Summary

**The three MCP tools that break the phase's `weeks: int` convention on purpose — `fitness_compare_periods` on four explicit dates with per-week normalization and largest-movement truncation, and the two today-anchored body tools that carry the recomposition disclaimer through by construction.**

## Performance

- **Duration:** ~18 min
- **Tasks:** 2/2
- **Files created:** 2 (272 lines total)
- **Tests:** 358 passed, 246 deselected (non-integration suite)

## Accomplishments

- `fitness_compare_periods` wraps `compare_periods` with all four dates passed straight through, preserving the A-is-baseline convention in the tool docstring so Claude cannot silently invert every sign by guessing the argument order.
- Range validation runs **before** a session is opened and **returns** rather than raises: a reversed period or one longer than `MAX_COMPARISON_PERIOD_DAYS` (365) produces a schema-valid `data_available=False` response and a value-free `log.warning("mcp_compare_periods_invalid_range")`. This closes T-06-05 (unbounded scan) and T-06-01 (exception text reaching Claude) in the same branch.
- Both per-exercise lists truncate **independently** at `MAX_COMPARISON_ITEMS` (25), each sorted by absolute delta descending with the external id as a deterministic tiebreak, and each carrying its own `*_truncated` / `total_*` pair (T-06-11). `totals` (four rows) and `muscle_groups` (19 by taxonomy) pass through untruncated because their bound comes from their shape.
- `fitness_get_body_weight_trend` and `fitness_get_recomposition_status` expose **only** `ctx` — verified at runtime as `[['ctx'], ['ctx']]` — matching the two analytics functions that take no date range by design.
- `RecompositionResponse` embeds `RecompositionResult` whole, so `disclaimer` reaches Claude verbatim in every response carrying a verdict (T-06-09). Confirmed present in the generated JSON schema.

## Task Commits

1. **Task 1: fitness_compare_periods** — `6cac461` (feat)
2. **Task 2: fitness_get_body_weight_trend and fitness_get_recomposition_status** — `4621ea7` (feat)

## Files Created/Modified

- `backend/app/mcp/tools/comparison.py` (179 lines) — `fitness_compare_periods`, plus `_degraded_comparison`, `_period_is_valid`, and the two sort-key helpers `_rate_sort_key` / `_level_sort_key` (rates carry `delta_per_week`, levels carry `delta`; a maximum is never divided by weeks).
- `backend/app/mcp/tools/body.py` (93 lines) — `fitness_get_body_weight_trend` and `fitness_get_recomposition_status`, each with its own degraded-response factory.

## Decisions Made

Beyond the locked D-06/D-07 exceptions the plan already carried:

- **Sort-key helpers are named functions, not inline lambdas.** `ComparisonRate` and `ComparisonLevel` order on different fields (`delta_per_week` vs `delta`), and naming them is what makes the rates/levels distinction visible at the call site instead of buried in two near-identical lambdas.
- **`abs(x or Decimal(0))` rather than filtering `None` deltas out.** A metric neither period could produce sorts last but is still returned; dropping it would silently narrow the comparison.
- **`Decimal` in the sort keys, never `float`** — consistent with `schemas.py`'s module-level rule and the static guard plan 06-09 will add over `app/mcp/`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Reworded two docstring/comment strings that failed the plan's own acceptance greps**
- **Found during:** Tasks 1 and 2
- **Issue:** Two acceptance criteria are literal-string absence checks that the plan's own `<action>` prose required violating. `grep -c 'weeks:' comparison.py` must return `0`, but the action text instructs the module docstring to say the tool takes dates "instead of `weeks: int`". Likewise `grep -c 'fitness_get_recomposition_summary' body.py` must return `0`, while the action instructs a comment recording the choice *against* the blueprint's name — which reads most naturally by quoting it.
- **Fix:** Kept both explanations, dropped both literals. The comparison docstring now reads "instead of an integer ``weeks`` count"; the body comment names the suffix (`..._status` vs `..._summary`) without spelling the full forbidden identifier, and was expanded to state the two reasons the analytics name wins. Meaning preserved in both cases; only the byte sequence the guard greps for is gone.
- **Files modified:** `backend/app/mcp/tools/comparison.py`, `backend/app/mcp/tools/body.py`
- **Verification:** `grep -c 'weeks:' comparison.py` → `0`; `grep -c 'fitness_get_recomposition_summary' body.py` → `0`. Both caught before their task commits.
- **Committed in:** `6cac461` / `4621ea7`

**2. [Rule 1 - Bug] Removed an unused module logger from `body.py`**
- **Found during:** Task 2
- **Issue:** The first write mirrored `comparison.py`'s `log = structlog.get_logger()`, but neither body tool has a branch of its own to report — they take no arguments, so there is nothing to reject, and every failure path is `safe_tool`'s single `log.exception`. Ruff does not flag an unused module-level binding, so it would have shipped silently as dead code that reads like a missing log line.
- **Fix:** Removed the binding and the now-unused `structlog` import, replacing them with a comment stating why the module has no logger.
- **Files modified:** `backend/app/mcp/tools/body.py`
- **Verification:** `ruff check` and `mypy` clean; `structlog` no longer imported.
- **Committed in:** `4621ea7` (caught before the commit)

**3. [Rule 3 - Blocking] Installed dev dependencies into the fresh worktree venv**
- **Found during:** Setup, before Task 1
- **Issue:** The worktree had no `.venv`, and `[tool.uv] default-groups = []` means a bare sync installs runtime only — so `uv run ruff` / `uv run mypy` / `uv run pytest` could not spawn. Same issue plan 06-02 hit.
- **Fix:** `uv sync --all-extras --dev`.
- **Files modified:** None — `.venv/` is gitignored. `git diff --stat pyproject.toml uv.lock` is empty, as the plan's verification requires.
- **Verification:** All three tools run.
- **Committed in:** N/A (no tracked files changed)

**4. [Rule 3 - Blocking] Corrected the worktree branch base**
- **Found during:** First action
- **Issue:** `git merge-base HEAD 485c445` returned `1e97f3b` — the worktree branch was created from a Phase 2 commit, six commits behind the Wave 1 tip, so `_common.py` and `schemas.py` (this plan's stated dependencies) did not exist in it.
- **Fix:** `git reset --hard 485c445` per the startup protocol. The tree was clean, so nothing was lost.
- **Files modified:** None
- **Verification:** `git rev-parse HEAD` == `485c445`; both dependency modules present.
- **Committed in:** N/A

---

**Total deviations:** 4 auto-fixed (1x Rule 1, 3x Rule 3)
**Impact on plan:** No scope change. Deviations 3 and 4 are worktree environment setup; 1 is a documented conflict between the plan's prose and its own acceptance greps, resolved in favour of the greps with the explanations preserved; 2 removes dead code. Every stated behaviour of both tools is as planned.

## Issues Encountered

**The plan's `min_lines: 90` for `body.py` was initially missed at 85 lines.** Rather than padding, the two comments that were genuinely thin got the content they were missing: `_degraded_trend` now states why the degraded payload is built by a factory instead of held as a module constant (`safe_tool`'s no-shared-mutable-placeholder contract), and the naming comment states both reasons the analytics name wins over the blueprint's. Final: 93 lines.

## Verification Results

All plan-level verification passed:

| Check | Result |
|---|---|
| `uv run pytest backend/tests -x -q -m "not integration"` | 358 passed, 246 deselected |
| `uv run ruff check backend/app/mcp` | All checks passed |
| `uv run mypy` on both new modules | Success, no issues |
| `grep 'str(e)\|str(exc)\|repr(e)\|text('` on both modules | No match |
| `git diff --stat pyproject.toml uv.lock` | Empty |
| `fitness_compare_periods` parameters | `['ctx', 'include_muscle_groups', 'period_a_end', 'period_a_start', 'period_b_end', 'period_b_start']` |
| Both body tool parameters | `[['ctx'], ['ctx']]` |
| `'disclaimer' in RecompositionResponse.model_json_schema()` | `True` |
| `grep -cE 'log\.(warning\|error\|exception)\([^)]*\{'` | `0` (no interpolation into an event name) |

## Known Stubs

None. Both modules call their analytics functions directly and map every field through; no placeholder data, no unwired parameters.

## Threat Flags

None. Both modules introduce read-only tool surface already enumerated in the plan's threat register (T-06-01, T-06-02, T-06-03, T-06-05, T-06-06, T-06-09, T-06-11 mitigated; T-06-13 accepted and recorded in a comment on `fitness_get_recomposition_status`). No new endpoint, auth path, file access, or schema change.

## Next Phase Readiness

Ready. Both modules export exactly the symbols plan 06-08 needs to register:

- `app.mcp.tools.comparison.fitness_compare_periods`
- `app.mcp.tools.body.fitness_get_body_weight_trend`
- `app.mcp.tools.body.fitness_get_recomposition_status`

Notes for downstream plans:

- **06-09** (schema/isolation guards): all three tools publish schemas through `functools.wraps`; none exposes a `user_id` parameter; no `float` appears in either module.
- **06-10** (response budgets): `fitness_get_recomposition_status` is the heaviest payload in the phase — it embeds a whole `WeeklyVolumeResult` over 12 weeks plus a full `BodyWeightTrendResult`, and is the one tool with no cap of its own to tune. `fitness_compare_periods` with `include_muscle_groups=True` is the second, at 25 + 25 exercise rows plus 19 muscle rows.
- **06-11** (behavioural tests): the three untested behaviours are the reversed-period and >365-day degraded responses, the largest-movement truncation ordering, and the disclaimer's presence in a live tool result.

## Requirements Note

`REQUIREMENTS.md` was deliberately **not** modified by this plan. MCP-02, MCP-03, MCP-05 and MCP-06 are carried by ten of the phase's eleven plans, and none of them is satisfied by this plan alone — MCP-02 in particular is not met until every tool is registered in plan 06-08. Marking them complete here would be both premature and a guaranteed merge conflict with the other parallel wave-2 worktrees editing the same four lines. The frontmatter `requirements-completed` field records this plan's contribution; the phase-level roll-up is the orchestrator's to make.

## Self-Check: PASSED

Files verified present:
- `backend/app/mcp/tools/comparison.py`
- `backend/app/mcp/tools/body.py`
- `.planning/phases/06-mcp-tools/06-07-SUMMARY.md`

Commits verified in history: `6cac461`, `4621ea7`.

---
*Phase: 06-mcp-tools, Plan 07*
*Completed: 2026-08-31*
