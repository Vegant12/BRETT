---
phase: 12
slug: training-programs-confirm-gated-write-tool
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-09-04
---

# Phase 12 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 + pytest-asyncio 1.4.0 (`asyncio_mode = "auto"`), config in `pyproject.toml` `[tool.pytest.ini_options]` |
| **Config file** | `pyproject.toml` (`testpaths = ["backend/tests"]`, `pythonpath = ["backend"]`) |
| **Quick run command** | `uv run pytest -m "not integration"` |
| **Full suite command** | `uv run pytest` (spins up `testcontainers.community.postgres.PostgresContainer("postgres:18-alpine")` per `conftest.py`) |
| **Estimated runtime** | ~5s quick / ~90s full (existing suite baseline) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest -m "not integration"` (static guard tests in `test_mcp_isolation.py` / `test_mcp_tool_schemas.py` and pure-Python matrix/threshold unit tests don't need a container)
- **After every plan wave:** Run `uv run pytest` (full suite, container-backed — required for anything touching the partial unique index, the atomic `UPDATE...RETURNING` token consumption, or `read_only`/`writable` transaction behavior)
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** ~90 seconds (full suite)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 12-01-XX | 01 | 0 | GOAL-01 | — | `test_db_program_history.py` stubs created, `conftest.py` fixtures extended for program periods | fixture | `uv run pytest backend/tests/test_db_program_history.py -k fixture -x` | ❌ W0 | ⬜ pending |
| 12-01-XX | 01 | 1 | GOAL-01 | — | Migration creates `user_program_history` + `program_switch_tokens`, partial unique index rejects a second open period | integration | `uv run pytest -m integration backend/tests/test_db_program_history.py -k migration -x` | ❌ W0 | ⬜ pending |
| 12-01-XX | 01 | 1 | GOAL-01 | — | Seed migration inserts the initial Lean Bulk period from live synced Hevy history (earliest `workouts.start_time`), not a hardcoded date | integration | `uv run pytest -m integration backend/tests/test_db_program_history.py -k seed -x` | ❌ W0 | ⬜ pending |
| 12-01-XX | 01 | 1 | GOAL-01 | — | `get_active_period` / `get_periods_overlapping` return correct results across a switch | integration | `uv run pytest -m integration backend/tests/test_db_program_history.py -k active_period -x` | ❌ W0 | ⬜ pending |
| 12-02-XX | 02 | 1 | GOAL-02 | — | Per-program threshold/matrix tables (Lean Bulk/Cut/Recomp) classify correctly per D-01–D-06; `zip(..., strict=True)` unaffected | unit | `uv run pytest backend/tests/test_analytics_recomposition.py -k threshold -x` | ✅ existing, extend | ⬜ pending |
| 12-02-XX | 02 | 1 | GOAL-02 | — | Straddled 12-week lookback window classifies against CURRENT program but surfaces switch-date + prior-program caveat field (D-10) | integration | `uv run pytest -m integration backend/tests/test_analytics_recomposition.py -k straddle -x` | ✅ existing, extend | ⬜ pending |
| 12-03-XX | 03 | 2 | GOAL-03 (SC#3) | T-12-01 | Single call to `fitness_switch_training_program` (no/invalid token) writes nothing, returns a one-time confirmation token + expiry | integration (MCP `Client`) | `uv run pytest -m integration backend/tests/test_mcp_program_switch.py -k warn_branch -x` | ❌ W0 | ⬜ pending |
| 12-03-XX | 03 | 2 | GOAL-03 (SC#4) | T-12-02 | Token bound to wrong program is rejected without being consumed (available for retry) | integration | `uv run pytest -m integration backend/tests/test_mcp_program_switch.py -k wrong_program -x` | ❌ W0 | ⬜ pending |
| 12-03-XX | 03 | 2 | GOAL-03 (SC#4) | T-12-03 | Already-consumed token is rejected on replay (no double-apply) | integration | `uv run pytest -m integration backend/tests/test_mcp_program_switch.py -k replay -x` | ❌ W0 | ⬜ pending |
| 12-03-XX | 03 | 2 | GOAL-03 (SC#4) | T-12-04 | Expired token (past 5-minute TTL, D-11) is rejected | integration | `uv run pytest -m integration backend/tests/test_mcp_program_switch.py -k expired -x` | ❌ W0 | ⬜ pending |
| 12-03-XX | 03 | 2 | GOAL-03 | T-12-05 | Confirmed switch is atomic: closes prior period (`ended_on`=today), opens new period, `session.commit()` is the last statement | integration | `uv run pytest -m integration backend/tests/test_mcp_program_switch.py -k confirm_atomic -x` | ❌ W0 | ⬜ pending |
| 12-03-XX | 03 | 2 | GOAL-03 | T-12-06 | `safe_tool` exception path returns three-state `unknown` (never `not_applied`) on mid-write failure | integration | `uv run pytest -m integration backend/tests/test_mcp_program_switch.py -k degraded -x` | ❌ W0 | ⬜ pending |
| 12-04-XX | 04 | 2 | GOAL-01 | — | New read tool answers "what program am I on?" including start date and what it replaced | integration (MCP `Client`) | `uv run pytest -m integration backend/tests/test_mcp_tools.py -k program_status -x` | ❌ W0 | ⬜ pending |
| 12-05-XX | 05 | 3 | GOAL-04 (SC#5) | T-12-07 | Write-tool module registered OUTSIDE `_TOOLS`/`READ_ONLY` loop with explicit `ToolAnnotations` (readOnlyHint=False, destructiveHint=True) | unit (static) | `uv run pytest backend/tests/test_mcp_tool_schemas.py -k annotations -x` | ✅ existing, extend | ⬜ pending |
| 12-05-XX | 05 | 3 | GOAL-04 (SC#5) | T-12-08 | `test_every_tool_is_annotated_read_only` becomes exact-partition assertion: 14 read-only + 1 not | unit (static) | `uv run pytest backend/tests/test_mcp_tool_schemas.py -k exact_partition -x` | ✅ existing, extend | ⬜ pending |
| 12-05-XX | 05 | 3 | GOAL-04 (SC#5) | T-12-09 | `_WRITE_ALLOWLIST` in `test_mcp_isolation.py` contains exactly one entry (`programs.py`); a second write module fails the suite | unit (static) | `uv run pytest backend/tests/test_mcp_isolation.py -k write_allowlist -x` | ✅ existing, extend | ⬜ pending |
| 12-05-XX | 05 | 3 | GOAL-04 | — | `read_only_session` unmodified; `writable_session` sibling used only by `programs.py` | unit (static) | `uv run pytest backend/tests/test_mcp_isolation.py backend/tests/test_mcp_readonly.py -x` | ✅ existing, extend | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_db_program_history.py` — new file, covers GOAL-01: seed migration, partial unique index, `get_active_period`/`get_periods_overlapping`
- [ ] `backend/tests/test_mcp_program_switch.py` — new file, covers GOAL-03: warn/confirm two-call flow, wrong-program/replay/expired token rejection, atomic commit, degraded three-state result
- [ ] `backend/tests/conftest.py` — `GoldenBuilder` extension for seeding program periods/tokens in tests
- [ ] No new test framework install needed — pytest/testcontainers/time-machine already pinned

---

## Manual-Only Verifications

*None — all phase behaviors have automated verification.*

---

## Planner Reconciliation (2026-09-04)

The plan set landed as five plans across four waves. The Per-Task Verification Map above was
written before plan numbering existed; this section maps its rows onto the plans that own them, so
every `-k` selector in the table resolves against a real test name.

| Map row | Owning plan | Wave | Test file |
|---------|-------------|------|-----------|
| fixture / migration / seed / active_period (GOAL-01) | 12-01 (schema, migration, fixtures) and 12-02 (`active_period`, token atomicity) | 1, 2 | `backend/tests/test_db_program_history.py` |
| threshold / straddle (GOAL-02) | 12-03 | 3 | `backend/tests/test_analytics_recomposition.py` |
| warn_branch / wrong_program / replay / expired / confirm_atomic / degraded (GOAL-03) | 12-04 | 3 | `backend/tests/test_mcp_program_switch.py` |
| program_status (GOAL-01 read tool) | 12-05 | 4 | `backend/tests/test_mcp_tools.py` |
| annotations / exact_partition / write_allowlist (GOAL-04) | 12-04 (`write_allowlist`) and 12-05 (`annotations`, `exact_partition`) | 3, 4 | `test_mcp_isolation.py`, `test_mcp_tool_schemas.py` |

**Wave 0 gaps:** both new test files are created inside the plan that first makes them meaningful
rather than in a standalone wave-0 plan — `test_db_program_history.py` in 12-01 Task 3 (alongside
the `conftest.py` `GoldenBuilder` extension), `test_mcp_program_switch.py` in 12-04 Task 3. Neither
file can assert anything before the schema and the tool it covers exist, so a separate earlier
plan would produce stubs and nothing else. Every task in the set carries an `<automated>` verify
command with no `MISSING` reference.

**Deviation from the map, recorded:** the write tool lives in `backend/app/mcp/tools/program_switch.py`
and the program READ tool in `backend/app/mcp/tools/programs.py`, rather than both in one module.
This keeps `test_mcp_isolation._WRITE_ALLOWLIST` at exactly one entry AND keeps the read tool under
the full `_SESSION_WRITE` ban — a strictly narrower guard than allowlisting a module that holds
both.

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (two new test files, fixture extension)
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
