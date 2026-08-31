---
phase: 06
slug: mcp-tools
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-08-31
---

# Phase 06 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 + pytest-asyncio 1.4.0 (`asyncio_mode = "auto"`) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths = ["backend/tests"]`, `pythonpath = ["backend"]`, marker `integration`) |
| **Quick run command** | `uv run pytest backend/tests -x -q -m "not integration"` |
| **Full suite command** | `uv run pytest backend/tests -q --cov=backend/app` |
| **Estimated runtime** | ~15s quick / ~90s full (testcontainers Postgres startup dominates) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest backend/tests -x -q -m "not integration"`
- **After every plan wave:** Run `uv run pytest backend/tests -q --cov=backend/app`
- **Before `/gsd-verify-work`:** Full suite must be green, plus one manual smoke against the deployed connector from a real Claude client (the in-memory `Client` bypasses auth, so it cannot prove the real path)
- **Max feedback latency:** ~15s (quick command; schema/isolation/budget-registry/window tests are all container-free by design)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 06-XX-01 | TBD | 0 | MCP-02 | — | All 12 tools registered and discoverable with expected names | unit | `uv run pytest backend/tests/test_mcp_tool_schemas.py::test_tool_registry_is_exactly_the_twelve -x` | ❌ W0 | ⬜ pending |
| 06-XX-02 | TBD | 1+ | MCP-02 | — | Each tool returns expected structured payload against golden fixture data | integration | `uv run pytest backend/tests/test_mcp_tools.py -x -m integration` | ✅ extend | ⬜ pending |
| 06-XX-03 | TBD | 1+ | MCP-02 | — | `fitness_get_training_summary` composes volume + muscle + frequency + recomposition in ONE call | integration | `uv run pytest backend/tests/test_mcp_tools.py::test_training_summary_composes_four_analytics -x` | ❌ W0 | ⬜ pending |
| 06-XX-04 | TBD | 1+ | MCP-02 / D-01 | — | Exercise name resolves to a template case-insensitively | integration | `uv run pytest backend/tests/test_mcp_tools.py::test_exercise_name_is_case_insensitive -x` | ❌ W0 | ⬜ pending |
| 06-XX-05 | TBD | 1+ | MCP-02 / D-02 | T-06-01 | Zero-match and multi-match both return candidates with `matched=False`, `is_error=False` | integration | `uv run pytest backend/tests/test_mcp_tools.py -k disambiguat -x` | ❌ W0 | ⬜ pending |
| 06-XX-06 | TBD | 0 | MCP-03 | T-06-02 | Every tool has a declared byte budget | unit | `uv run pytest backend/tests/test_mcp_tool_budget.py::test_every_registered_tool_has_a_budget -x` | ❌ W0 | ⬜ pending |
| 06-XX-07 | TBD | 1+ | MCP-03 | T-06-02 | Every tool's full `CallToolResult` fits its budget against worst-case history | integration | `uv run pytest backend/tests/test_mcp_tool_budget.py -x -m integration` | ❌ W0 | ⬜ pending |
| 06-XX-08 | TBD | 0 | MCP-03 / D-04 | — | `weeks > 52` rejected; `inputSchema` advertises `maximum: 52` | unit | `uv run pytest backend/tests/test_mcp_tool_schemas.py::test_week_caps_are_published_and_enforced -x` | ❌ W0 | ⬜ pending |
| 06-XX-09 | TBD | 1+ | MCP-03 / D-10 | — | `limit` above cap rejected; full-cap list stays in budget | integration | `uv run pytest backend/tests/test_mcp_tool_budget.py -k recent_workouts -x` | ❌ W0 | ⬜ pending |
| 06-XX-10 | TBD | 0 | MCP-05 | — | Every registered tool carries `readOnlyHint: true` | unit | `uv run pytest backend/tests/test_mcp_tool_schemas.py::test_every_tool_is_annotated_read_only -x` | ❌ W0 | ⬜ pending |
| 06-XX-11 | TBD | 0 | MCP-05 | T-06-03 | No module under `app/mcp/` mutates a session or imports insert/update/delete | unit | `uv run pytest backend/tests/test_mcp_isolation.py -x` | ❌ W0 | ⬜ pending |
| 06-XX-12 | TBD | 1+ | MCP-05 | T-06-03 | A write attempted on a tool's session raises `ReadOnlySQLTransactionError` | integration | `uv run pytest backend/tests/test_mcp_readonly.py -x` | ❌ W0 | ⬜ pending |
| 06-XX-13 | TBD | 1+ | MCP-06 | T-06-04 | An unreachable database leaks no DSN fragment into any tool result | integration | `uv run pytest backend/tests/test_mcp_tools.py -k leaks_nothing -x` | ✅ extend | ⬜ pending |
| 06-XX-14 | TBD | 0 | MCP-06 | T-06-04 | No module under `app/mcp/` interpolates an exception into a returned value | unit | `uv run pytest backend/tests/test_mcp_isolation.py::test_mcp_tools_never_interpolate_an_exception -x` | ❌ W0 | ⬜ pending |
| 06-XX-15 | TBD | 1+ | MCP-06 | T-06-04 | No tool response contains any `Settings.secret_values()` string | integration | `uv run pytest backend/tests/test_secret_redaction.py -k mcp_tool -x` | ✅ extend | ⬜ pending |
| 06-XX-16 | TBD | 0 | D-03 | — | `weeks=N` produces the correct local window under a frozen clock at `Asia/Jakarta` | unit | `uv run pytest backend/tests/test_mcp_window.py -x` | ❌ W0 | ⬜ pending |
| 06-XX-17 | TBD | 0 | D-03 | — | `weeks` window computed from user's LOCAL today, not UTC (17:00Z–24:00Z boundary) | unit | `uv run pytest backend/tests/test_mcp_window.py::test_evening_utc_belongs_to_next_local_day -x` | ❌ W0 | ⬜ pending |
| 06-XX-18 | TBD | 0 | A1 (safe_tool) | — | `@safe_tool` does not erase `inputSchema`/`outputSchema` | unit | `uv run pytest backend/tests/test_mcp_tool_schemas.py::test_decorated_tools_still_publish_schemas -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*Task IDs are placeholders (`06-XX-NN`) until the planner assigns real plan/task numbers; this table's requirement/behavior/command mapping is what must survive into the real plan.*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_mcp_tool_schemas.py` — covers MCP-02, MCP-03 (caps), MCP-05 (annotations), A1 (`@safe_tool` schema preservation)
- [ ] `backend/tests/test_mcp_tool_budget.py` — covers MCP-03 (D-13 byte budgets)
- [ ] `backend/tests/test_mcp_isolation.py` — covers MCP-05, MCP-06 (static source-walking guards)
- [ ] `backend/tests/test_mcp_readonly.py` — covers MCP-05 (runtime `ReadOnlySQLTransactionError`)
- [ ] `backend/tests/test_mcp_window.py` — covers D-03/D-04 (weeks→local-day window conversion)
- [ ] `backend/tests/conftest.py` — `worst_case_history` fixture (52 weeks × ~5 sessions/week × ~30 templates), built on `GoldenBuilder` with the same flush-and-rollback contract as `golden_workout`
- [ ] Framework install: none required — pytest, pytest-asyncio, testcontainers and time-machine are already in the `dev` dependency group

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|--------------------|
| Real Claude client can call all 12 tools through the deployed connector with auth | MCP-02, MCP-05 | The in-memory `mcp.Client` used by all automated tests deliberately bypasses auth (per `test_mcp_tools.py`'s existing precedent), so it cannot prove the real authenticated path end-to-end | Connect a real Claude client (Desktop/Web/Code) to the deployed connector, invoke each of the 12 tools once, confirm structured responses and no auth errors. Follow `02-DEPLOY-LOG.md`'s template |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s (quick command)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
