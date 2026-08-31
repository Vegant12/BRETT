---
phase: 06-mcp-tools
verified: 2026-09-01T00:00:00Z
status: passed
score: 9/9 must-haves verified
overrides_applied: 0
---

# Phase 6: MCP Tools Verification Report

**Phase Goal:** Claude can reach every analytic through purpose-built, read-only tools that return compact structured answers instead of raw data
**Verified:** 2026-09-01
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (Roadmap Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Claude can call read-only tools covering recent workouts, training summary, weekly volume, muscle-group volume, exercise progression, personal records, plateaus, training frequency, body-weight trend, recomposition status, and period comparison | ✓ VERIFIED | Live `MCPServer` import (env-seeded, no container) lists exactly 13 registered tools: `fitness_ping` + the 12 named ones (`fitness_get_recent_workouts`, `fitness_get_workout`, `fitness_get_training_summary`, `fitness_get_weekly_volume`, `fitness_get_muscle_group_volume`, `fitness_get_training_frequency`, `fitness_get_exercise_progression`, `fitness_get_personal_records`, `fitness_get_plateaus`, `fitness_compare_periods`, `fitness_get_body_weight_trend`, `fitness_get_recomposition_status`). Every one publishes a non-null `outputSchema` and its real named parameters (never `ctx`/`user_id`). |
| 2 | A single `fitness_get_training_summary` call returns a composed picture of training state without Claude needing to chain several tools | ✓ VERIFIED | `backend/app/mcp/tools/summary.py` composes `get_weekly_volume`, `get_muscle_group_volume` (via shared `roll_up_muscles`), `get_training_frequency`, and `get_recomposition_status` inside one `read_only_session`. `TrainingSummaryResponse.model_json_schema()['required']` independently confirmed to include `volume_by_week`, `muscles`, `recomposition_status`, `recomposition_disclaimer`, `progression_signal`, `progression_verdict`, `weight_trend_rate_percent_per_week`, `average_7d_kg`, `coverage`, `freshness`. `test_training_summary_composes_four_analytics` in `test_mcp_tools.py` asserts all elements present against seeded, committed data — passes. |
| 3 | Every tool response is compact structured JSON within an enforced size cap — no raw table access, no unbounded result sets, no arithmetic pushed onto the model | ✓ VERIFIED | `backend/tests/test_mcp_tool_budget.py` defines a `BUDGETS` table asserted equal to the live 13-tool registry (a 14th tool fails the build unbudgeted), and measures the *full* `CallToolResult` (structured + text-duplicate) against `worst_case_history` (52 weeks, ~260 workouts, ~5,200 sets) at every tool's published cap. All 13 tools measured within budget (headroom 13%–86%; 3 budgets were re-derived from real measurement rather than left as unverified research estimates — recorded transparently in the SUMMARY and `deferred-items.md`). Every truncatable list (`workouts`, `exercises`, progression `points`, comparison items) carries a `*_truncated` bool + `total_*` int pair, verified by `test_mcp_schemas.py`/`test_mcp_tool_budget.py`. |
| 4 | No tool can write, modify, or delete any data; every tool is annotated read-only and a write attempt has no surface to reach | ✓ VERIFIED | Live registry check confirms all 13 tools carry `ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)`. Runtime enforcement (not just the hint) confirmed by `backend/tests/test_mcp_readonly.py`: INSERT into `workouts`, UPDATE on `users`, DELETE from `sync_state` inside `read_only_session` all raise `ReadOnlySQLTransactionError` from PostgreSQL itself; unconditional rollback on exit; the read-only flag proven not to leak back into the pooled connection (a plain session opened after reads `transaction_read_only = off` and completes a real write). Static guard `test_mcp_isolation.py` bans write imports/calls and raw `text(` SQL across all of `app/mcp/` except the documented `ping.py` exemption. |
| 5 | No tool response or log line contains an API key, database credential, or internal token, verified by test | ✓ VERIFIED | `backend/tests/test_mcp_tools.py::test_every_tool_degradation_leaks_nothing` points the sessionmaker at a dead port and scans all 13 tools' full results for 9 leak markers (DSN fragments, driver names, tracebacks) — none found; every tool degrades via `@safe_tool` with `is_error=False`. `backend/tests/test_secret_redaction.py::test_mcp_tool_response_contains_no_configured_secret` drives all 13 tools against a healthy DB and scans for every `Settings.secret_values()` string — none found. `test_a_raising_tool_would_leak_without_the_guard` proves the leak channel is real (an unguarded tool does leak), which is what justifies `@safe_tool` being mandatory rather than a nice-to-have. |

**Score:** 5/5 roadmap truths verified

### Plan-Level Must-Haves (representative sample across 11 plans)

| # | Truth (plan) | Status | Evidence |
|---|---|---|---|
| 6 | Every MCP tool can open a database session that PostgreSQL itself refuses to let write (06-01) | ✓ VERIFIED | `read_only_session` in `_common.py` sets `postgresql_readonly=True`; proven at runtime in `test_mcp_readonly.py` |
| 7 | An exercise name resolves to zero, one, or many templates without any string interpolation reaching SQL (06-01/06-06) | ✓ VERIFIED | `find_templates_by_title` uses `func.lower(col) == bound_param`; `test_unknown_exercise_name_returns_no_candidates` / `test_ambiguous_exercise_name_returns_every_candidate` pass against seeded data with a real title collision (`MCP-LAT1`/`MCP-LAT2`) |
| 8 | A degraded (database-unreachable) response is distinguishable from a real "you have no training data" answer (06-02) | ✓ VERIFIED | Every `*Response` model carries `data_available: bool`; degraded factories set it `False`; confirmed via schema + `test_mcp_schemas.py` degraded-construction test |
| 9 | The recomposition disclaimer reaches Claude verbatim in every response that carries a verdict (06-02/06-07/06-08) | ✓ VERIFIED | `recomposition` is `required` in `RecompositionResponse` schema (confirmed live); `recomposition_disclaimer` is `required` in `TrainingSummaryResponse` (confirmed live); `test_recomposition_status_carries_its_disclaimer` asserts a non-empty string |

**Score:** 9/9 must-haves verified (5 roadmap-level + 4 representative plan-level; full plan-level detail in the 11 SUMMARY.md files was cross-checked against source and is consistent)

### Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `backend/app/mcp/tools/_common.py` | Shared session/window/name-lookup/guard module | ✓ VERIFIED | 304 lines; all 19 named exports (10 caps + 9 helpers) present and importable |
| `backend/app/mcp/tools/schemas.py` | 13 response models + projections | ✓ VERIFIED | 367+ lines (file now 14,451 bytes incl. later edits); all 20 named exports present; composes `app/analytics/schemas.py` and `app/normalization/muscles.py` |
| `backend/app/db/repositories/workouts.py` | `recent_workout_summaries`, `workout_detail` | ✓ VERIFIED | 366 lines; imports `hard_set_predicates` from `app.analytics.rollup`; no write construct |
| `backend/app/mcp/tools/workouts.py` | `fitness_get_recent_workouts`, `fitness_get_workout` | ✓ VERIFIED | Registered live, schemas published, `limit` max=25, `workout_id` maxLength=64 |
| `backend/app/mcp/tools/volume.py` | 3 volume/frequency tools + `roll_up_muscles` | ✓ VERIFIED | Registered live; `roll_up_muscles` reused by `summary.py` |
| `backend/app/mcp/tools/progression.py`, `records.py` | progression/plateaus/records tools | ✓ VERIFIED | Registered live; D-01/D-02 name resolution confirmed by integration tests |
| `backend/app/mcp/tools/comparison.py`, `body.py` | comparison + 2 body tools | ✓ VERIFIED | Registered live; `fitness_compare_periods` params confirmed `[period_a_start, period_a_end, period_b_start, period_b_end, include_muscle_groups]` |
| `backend/app/mcp/tools/summary.py` | `fitness_get_training_summary` | ✓ VERIFIED | Registered live; composes 4 analytics calls in one transaction |
| `backend/app/mcp/server.py` | All 13 tools registered with shared `READ_ONLY` annotation | ✓ VERIFIED | Live count = 13; all annotated `read_only_hint=True, destructive_hint=False, open_world_hint=False` |
| `backend/tests/test_mcp_tool_budget.py`, `test_mcp_readonly.py` | D-13 budgets + runtime read-only proof | ✓ VERIFIED | Present, run, pass (12 tests) |
| `backend/tests/test_mcp_tools.py`, `test_secret_redaction.py` | Per-tool behavioral + leak coverage | ✓ VERIFIED | 1021 + 322 lines; 175 MCP-specific tests pass independently re-run |

### Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| `app/mcp/tools/schemas.py` | `app/analytics/schemas.py` | embedding analytics result models | ✓ WIRED | `from app.analytics.schemas import (...)` at line 36, confirmed live |
| `app/mcp/tools/schemas.py` | `app/normalization/muscles.py` | `CanonicalMuscleGroup` | ✓ WIRED | `from app.normalization.muscles import CanonicalMuscleGroup` at line 55, 2 usages |
| `app/db/repositories/workouts.py` | `app/analytics/rollup.py` | `hard_set_predicates` | ✓ WIRED | Confirmed by 06-03-SUMMARY and static grep; sole non-legacy spelling in repo |
| `app/mcp/server.py` | `app/mcp/tools/*.py` | `mcp.add_tool(fn, annotations=READ_ONLY)` | ✓ WIRED | Loop registration confirmed; live introspection shows all 13 tools carry the annotation |
| `app/mcp/tools/summary.py` | `app/mcp/tools/volume.py` | `roll_up_muscles` import | ✓ WIRED | Confirmed in SUMMARY and consistent with schema composition |
| `app/mcp/tools/body.py` | `app/analytics/recomposition.py` | `get_recomposition_status` | ✓ WIRED | `RecompositionResponse.recomposition` required field confirmed live |

### Data-Flow Trace (Level 4)

All 13 tools were exercised end-to-end against real committed history in `test_mcp_tools.py` (16 behavioral tests) rather than against static/empty fixtures — e.g. `test_weekly_volume_excludes_warmups` asserts `hard_sets == 36` (not `42`, the with-warmups count) from real seeded sets; `test_muscle_group_volume_returns_all_nineteen_groups` asserts a specific trained muscle (chest) is non-zero and an untrained one (calves) is a zero row with `insufficient_data=True`. This confirms the wiring carries real, differentiated data rather than a static/empty fallback. Independently re-run: all pass.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Full backend test suite | `uv run pytest -q` (backend/) | 650 passed | ✓ PASS |
| MCP-specific test suite | `uv run pytest tests/test_mcp_*.py tests/test_repository_workouts.py tests/test_secret_redaction.py -q` | 175 passed | ✓ PASS |
| Tool registry live introspection | Import `app.mcp.server.mcp`, list tools | 13 tools, all read-only annotated, all with output schemas | ✓ PASS |
| `user_id` never a published tool parameter | `grep 'user_id:' app/mcp/tools/*.py` (excluding internal `_common.py` helpers) | 0 matches on any `fitness_*` tool signature | ✓ PASS |
| No `float` usage under `app/mcp/` | regex scan | 0 matches | ✓ PASS |
| `recomposition`/`recomposition_disclaimer` required in schema | `model_json_schema()['required']` | both present | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|---|---|---|---|---|
| MCP-02 | 06-01 through 06-11 (all) | Read-only tools covering the 11 named analytics + summary | ✓ SATISFIED | 13-tool registry confirmed live; REQUIREMENTS.md line 63 marked `[x]` |
| MCP-03 | 06-01, 06-02, 06-03, 06-04..09, 06-10 | Compact, structured JSON, no raw DB access, no unbounded results | ✓ SATISFIED | Byte-budget suite measures full `CallToolResult` against caps for all 13 tools; truncation flags verified; REQUIREMENTS.md line 64 marked `[x]` |
| MCP-05 | 06-01, 06-03, 06-04..09, 06-10 | No tool can write/modify/delete data | ✓ SATISFIED | Runtime-proven via PostgreSQL `READ ONLY` transaction rejection (`test_mcp_readonly.py`), plus static guard; REQUIREMENTS.md line 66 marked `[x]` |
| MCP-06 | 06-01, 06-02, 06-04..09, 06-11 | No secrets ever returned in a tool response | ✓ SATISFIED | Dead-DB leak test + secret-redaction scan across all 13 tools, both passing; REQUIREMENTS.md line 67 marked `[x]` |

No orphaned requirements: REQUIREMENTS.md's phase-mapping table lists exactly MCP-02, MCP-03, MCP-05, MCP-06 for Phase 6, matching every plan's `requirements:` frontmatter field.

**Note (informational, not a gap):** REQUIREMENTS.md's checkbox section (lines 62-67) correctly marks all four as `[x]` complete, but the separate traceability table further down the same file (lines 158-161) still shows them as "Pending". This is a pre-existing staleness pattern affecting the traceability table for multiple already-completed phases (e.g. Phase 5's PROG-01..04 show the same "Pending" mismatch despite Phase 5 being complete per STATE.md), not something introduced by or specific to this phase. Does not affect the actual requirement status or the phase goal.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|---|---|---|---|---|
| `backend/app/db/repositories/workouts.py` | 113-120 | `_duration_minutes` has no guard against `end_time < start_time`; no DB CHECK constraint prevents such a row | ⚠️ Warning (pre-existing, documented) | If a corrupted/edited workout row ever has `end_time < start_time`, `duration_minutes` silently returns a negative int with no signal, flowing into `fitness_get_recent_workouts`/`fitness_get_workout`. Identified in `06-REVIEW.md` (WR-01) as a narrow, not-currently-triggered edge case (no test exercises it, and no known real data hits it). Does not affect any of the 5 roadmap success criteria — it is a data-quality edge case, not a missing capability. Left open by design (fix requires a design choice: clamp to 0 vs. `int | None`) |

No blockers found. No TODO/FIXME/placeholder patterns in any file touched by this phase. No stub returns (`return null`/`return {}`/`return []`) flowing to any tool's actual response path — the only `data_available=False` / `None`-payload paths are the documented, tested degraded-response contract, not unwired stubs.

### Human Verification Required

None. Every observable truth in this phase is mechanically checkable (schema introspection, byte-budget measurement, PostgreSQL-enforced read-only transactions, string-scan leak tests) and all such checks were independently re-run against the live codebase during this verification, not just taken from SUMMARY.md claims.

### Gaps Summary

No gaps. All 5 roadmap success criteria and all sampled plan-level must-haves are verified against the actual codebase (not merely against SUMMARY.md claims): 13 tools registered and live-introspected, all read-only, all schema-valid, all budget-tested, all leak-tested, all behaviorally tested against real seeded data, full 650-test backend suite green on independent re-run. The one open item (WR-01, negative-duration edge case) is a pre-identified, narrow data-quality warning that does not block any success criterion and was already surfaced by the code review.

---

*Verified: 2026-09-01*
*Verifier: Claude (gsd-verifier)*
