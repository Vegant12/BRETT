---
phase: 13
slug: health-analytics-reports-coaching-style
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-09-04
---

# Phase 13 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 + pytest-asyncio 1.4.0 (`asyncio_mode = "auto"`) |
| **Config file** | `backend/pyproject.toml` |
| **Quick run command** | `uv run pytest backend/tests/test_analytics_health.py backend/tests/test_analytics_reports.py backend/tests/test_mcp_tools.py -x` |
| **Full suite command** | `uv run pytest` (container-backed integration tests included) |
| **Estimated runtime** | ~90 seconds (full suite, testcontainers Postgres) |

---

## Sampling Rate

- **After every task commit:** Run the unit test file for the module just touched (e.g. `uv run pytest backend/tests/test_analytics_health.py -x`)
- **After every plan wave:** Run `uv run pytest` (full suite, container-backed)
- **Before `/gsd-verify-work`:** Full suite must be green; RPT-03's manual spike result documented regardless of outcome
- **Max feedback latency:** ~90 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 13-01-01 | 01 | 0 | HEALTH-12 | V4/V5 | `resolve_user_id`, no free-form params | unit | `pytest backend/tests/test_analytics_health.py -k activity -x` | ❌ Wave 0 | ⬜ pending |
| 13-01-02 | 01 | 0 | NUTR-04 | V4/V5 | closed 7-metric set, no caller-supplied string | unit | `pytest backend/tests/test_analytics_health.py -k nutrition -x` | ❌ Wave 0 | ⬜ pending |
| 13-02-01 | 02 | 1 | NUTR-06 | V4/V8 | `safe_tool` degraded path, `read_only_session` | integration | `pytest backend/tests/test_mcp_tools.py -k nutrition_trend -x` | ❌ Wave 0 (extend) | ⬜ pending |
| 13-02-02 | 02 | 1 | HEALTH-12 | V4/V8 | `safe_tool` degraded path, `read_only_session` | integration | `pytest backend/tests/test_mcp_tools.py -k activity_trend -x` | ❌ Wave 0 (extend) | ⬜ pending |
| 13-03-01 | 03 | 2 | RPT-01 | V4/V5/V8 | narrow-extras composer, `MAX_REPORT_*` cap, `truncate()` | integration | `pytest backend/tests/test_analytics_reports.py -k weekly -x` | ❌ Wave 0 | ⬜ pending |
| 13-03-02 | 03 | 2 | RPT-02 | V4/V5/V8 | same composer, calendar-month window, deterministic narrative field | integration | `pytest backend/tests/test_analytics_reports.py -k monthly -x` | ❌ Wave 0 | ⬜ pending |
| 13-03-03 | 03 | 2 | MCP-03 (budget) | V5 (DoS via unbounded payload) | measured `MAX_REPORT_*`, not estimated | integration | `pytest backend/tests/test_mcp_tool_budget.py -x` (extend `BUDGETS`) | ✅ (extend) | ⬜ pending |
| 13-04-01 | 04 | 3 | RPT-03 | — | human-gated spike, no automated substitute | manual | N/A — see Manual-Only Verifications | N/A | ⬜ pending |
| 13-05-01 | 05 | 4 | COACH-02, COACH-03 | — | ≤9,000 char ceiling, bidirectional tool-name drift guard | unit | `pytest backend/tests/test_coaching_doc.py -x` (already exists) | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_analytics_health.py` — stubs for HEALTH-12 (activity rolling averages/floors) and NUTR-04 (nutrition rolling averages/floors), mirroring `bodyweight.py`'s existing test shape
- [ ] `backend/tests/test_analytics_reports.py` — stubs for RPT-01/RPT-02 (composer, both periods, narrow extras, degraded-input path)
- [ ] Extend `backend/tests/test_mcp_tools.py` — NUTR-06 and the activity-trend tool's schema + degraded-path cases
- [ ] Extend `backend/tests/test_mcp_tool_budget.py`'s `BUDGETS`/`WORST_CASE_ARGS` — the two new report tools, measured against real composed payloads per Pitfall 4 (research measured a rough 13-22 KB estimate; confirm with real fixture before locking `MAX_REPORT_*`)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|--------------------|
| Real Claude scheduled task run against the report tools via BRETT's live MCP connector | RPT-03 | Human-gated: requires the user's own Claude Desktop client and live connector (D-12); no automated substitute exists for verifying whether tool schemas actually reach a scheduled session | Create a scheduled task in Claude Desktop against BRETT's connector referencing `fitness_get_weekly_report`/`fitness_get_monthly_report`; record whether the task calls the tool successfully or reproduces the "tool schemas never injected" failure; write the outcome into `docs/coaching-instructions.md` (D-13: workaround preamble added ONLY if the failure reproduces) |
| Nutrition coverage floor re-query against production data | D-06 (informs NUTR-04 implementation) | This session's sandbox blocked all live-database query attempts (`psql`/`asyncpg`/`gcloud secrets access` denied); needs a human operator with real `DATABASE_URL` access | Run the coverage-count SQL from `13-RESEARCH.md` Pitfall 3 against production before finalizing `MEASURED_DAY_FLOORS`-equivalent constants in `analytics/health.py`'s nutrition function |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
