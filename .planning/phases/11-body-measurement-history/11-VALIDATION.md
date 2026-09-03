---
phase: 11
slug: body-measurement-history
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-09-03
---

# Phase 11 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 + pytest-asyncio 1.4.0 (`asyncio_mode = "auto"`), config in `pyproject.toml` `[tool.pytest.ini_options]` |
| **Config file** | `pyproject.toml` (`testpaths = ["backend/tests"]`, `pythonpath = ["backend"]`) |
| **Quick run command** | `pytest -m "not integration" backend/tests/test_analytics_body_measurements.py` |
| **Full suite command** | `pytest backend/tests` (runs `integration`-marked tests against `testcontainers[postgres]`) |
| **Estimated runtime** | ~5s quick / ~90s full (existing suite baseline) |

---

## Sampling Rate

- **After every task commit:** Run `pytest -m "not integration" backend/tests/test_analytics_body_measurements.py`
- **After every plan wave:** Run `pytest backend/tests` (full suite, container-backed)
- **Before `/gsd-verify-work`:** Full suite must be green, including the four structural drift-guard files (`test_mcp_tool_schemas.py`, `test_mcp_tool_budget.py`, `test_mcp_tools.py`, `test_coaching_doc.py`)
- **Max feedback latency:** ~90 seconds (full suite)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 11-01-XX | 01 | 0 | BODY-05 | — | `GoldenBuilder.body_measurement()` accepts non-weight columns | fixture | `pytest backend/tests/test_analytics_body_measurements.py -k fixture -x` | ❌ W0 | ⬜ pending |
| 11-01-XX | 01 | 1 | BODY-05 | — | Two-point delta computed correctly, exact `Decimal` | unit | `pytest backend/tests/test_analytics_body_measurements.py -k delta -x` | ❌ W0 | ⬜ pending |
| 11-01-XX | 01 | 1 | BODY-05 | — | Floor (recommended `{90: 2}`) gates `insufficient_data` at the boundary | integration | `pytest -m integration backend/tests/test_analytics_body_measurements.py -k floor -x` | ❌ W0 | ⬜ pending |
| 11-01-XX | 01 | 1 | BODY-05 | — | `is_stale`/`days_since_latest_reading` computed independent of `insufficient_data` (2+ old readings; 1 old reading; 1 fresh reading; 0 readings) | integration | `pytest -m integration backend/tests/test_analytics_body_measurements.py -k stale -x` | ❌ W0 | ⬜ pending |
| 11-02-XX | 02 | 2 | BODY-05 | — | Unrecognized metric name rejected by the MCP tool's own input schema (not a 500, not a silent empty result) | integration (MCP `Client`) | `pytest -m integration backend/tests/test_mcp_tools.py -k body_measurement_trend -x` | ❌ W0 | ⬜ pending |
| 11-02-XX | 02 | 2 | BODY-05 (success criterion #3) | — | Existing BODY-01 tool (`fitness_get_body_weight_trend`) unchanged | integration | `pytest -m integration backend/tests/test_analytics_bodyweight.py backend/tests/test_mcp_tools.py -k body_weight_trend -x` | ✅ (regression check, no new file) | ⬜ pending |
| 11-02-XX | 02 | 2 | — (structural) | — | New tool appears in `EXPECTED_TOOLS`, `BUDGETS`, `WORST_CASE_ARGS`, `MINIMAL_TOOL_ARGUMENTS`, and `docs/coaching-instructions.md` | unit/integration (schema/doc drift guards) | `pytest backend/tests/test_mcp_tool_schemas.py backend/tests/test_mcp_tool_budget.py backend/tests/test_coaching_doc.py` | ✅ (existing tests, currently red until touch points made) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_analytics_body_measurements.py` — new file, mirrors `test_analytics_bodyweight.py`'s structure (pure-Python delta/window tests with no marker, integration tests with `@pytest.mark.integration` + `time_machine.travel`), covers REQ BODY-05
- [ ] `backend/tests/conftest.py` — `GoldenBuilder.body_measurement()` needs new kwargs for at least one circumference column and one composition column (currently only accepts `weight_kg`) — every integration test above depends on this
- [ ] No new test framework install needed — pytest/testcontainers/time-machine already pinned

---

## Manual-Only Verifications

*None — all phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (fixture extension, new test file)
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
