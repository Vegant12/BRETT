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

| Plan | Wave | Requirement(s) | Objective | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|------|------|-----------------|-----------|-----------------|-----------|-------------------|-------------|--------|
| 13-01 | 1 | RPT-03 | Capability spike w/ `fitness_ping`, run before report tools are built (checkpoint: human-gated) | — | manual | N/A — see Manual-Only Verifications | N/A | ⬜ pending |
| 13-02 | 1 | HEALTH-12, NUTR-04 | `GoldenBuilder.health_metric`, Apple Health in `worst_case_history`, D-06 production coverage measurement | V4 (`resolve_user_id`) | unit + manual (D-06 query) | `pytest backend/tests/test_analytics_health.py -x` | ❌ Wave 0 | ⬜ pending |
| 13-03 | 1 | RPT-01, RPT-02 | `local_month_start`, `FRESHNESS_RESOURCES_REPORT`, `get_recent_records` cross-exercise PR scan | V4/V5 | unit | `pytest backend/tests/test_time.py backend/tests/test_analytics_metadata.py backend/tests/test_analytics_records.py -x` | ❌ Wave 0 | ⬜ pending |
| 13-04 | 2 | HEALTH-12, NUTR-04 | `analytics/health.py` + metric enums/models (independent per-metric coverage, multi-source SUM) | V4/V5 (closed 7-metric set) | unit | `pytest backend/tests/test_analytics_health.py -k "activity or nutrition" -x` | ❌ Wave 0 (extend 13-02) | ⬜ pending |
| 13-05 | 3 | HEALTH-12, NUTR-04 | Container-backed proof of all four health entry points (per-metric independence, multi-source sum, user isolation) | V4 (user isolation proven) | integration | `pytest backend/tests/test_analytics_health.py -x` (container-backed) | ❌ Wave 0 (extend) | ⬜ pending |
| 13-06 | 3 | HEALTH-12, NUTR-06, COACH-03 | Activity + nutrition MCP tools, registration, 5 guards, measured budgets | V4/V8 (`safe_tool`, `read_only_session`, no `user_id` in schema) | integration | `pytest backend/tests/test_mcp_tools.py backend/tests/test_mcp_tool_schemas.py backend/tests/test_mcp_tool_budget.py backend/tests/test_mcp_isolation.py -x` | ❌ Wave 0 (extend) | ⬜ pending |
| 13-07 | 4 | RPT-01, RPT-02 | `analytics/reports.py` — `ReportResult` + one composer, two windows (D-01 closed-period, D-04 one composer) | V4/V5 (composition only, no arithmetic) | unit | `pytest backend/tests/test_analytics_reports.py -x` | ❌ Wave 0 | ⬜ pending |
| 13-08 | 5 | RPT-01, RPT-02 | D-14 deterministic narrative + composer test suite (byte-identical output, degraded-source case) | V8 (no free-form/LLM text) | unit + integration | `pytest backend/tests/test_analytics_reports.py -x` (extend) | ❌ Wave 0 (extend 13-07) | ⬜ pending |
| 13-09 | 6 | RPT-01, RPT-02, COACH-03 | Report MCP tools, `MAX_REPORT_*`, registration, measured budgets | V4/V5/V8 (measured, not estimated, per Pitfall 4) | integration | `pytest backend/tests/test_mcp_tools.py backend/tests/test_mcp_tool_schemas.py backend/tests/test_mcp_tool_budget.py backend/tests/test_mcp_isolation.py -x` | ❌ Wave 0 (extend) | ⬜ pending |
| 13-10 | 7 | RPT-03, COACH-02, COACH-03 | Coaching-doc rewrite against the 20-tool registry + RPT-03 spike on real report tools (checkpoint: human-gated) | — | unit + manual | `pytest backend/tests/test_coaching_doc.py -x` (already exists) | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_analytics_health.py` — stubs for HEALTH-12 (activity rolling averages/floors) and NUTR-04 (nutrition rolling averages/floors), mirroring `bodyweight.py`'s existing test shape (introduced 13-02, filled 13-04, container-backed 13-05)
- [ ] `backend/tests/test_time.py`, `backend/tests/test_analytics_metadata.py`, `backend/tests/test_analytics_records.py` — stubs for `local_month_start`, `FRESHNESS_RESOURCES_REPORT`, `get_recent_records` (13-03)
- [ ] `backend/tests/test_analytics_reports.py` — stubs for RPT-01/RPT-02 (composer, both periods, narrow extras, degraded-input path, narrative determinism — 13-07/13-08)
- [ ] Extend `backend/tests/test_mcp_tools.py` — NUTR-06 and the activity-trend tool's schema + degraded-path cases (13-06), then the two report tools (13-09)
- [ ] Extend `backend/tests/test_mcp_tool_budget.py`'s `BUDGETS`/`WORST_CASE_ARGS` — activity/nutrition tools (13-06) and the two report tools (13-09), measured against real composed payloads per Pitfall 4 (research measured a rough 13-22 KB estimate for reports; confirm with real fixture before locking `MAX_REPORT_*`)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|--------------------|
| Capability probe: real Claude scheduled task calls `fitness_ping` via BRETT's live MCP connector | RPT-03 (plan 13-01, wave 1) | Human-gated: requires the user's own Claude Desktop client and live connector (D-12); no automated substitute exists for verifying whether tool schemas actually reach a scheduled session | Create a scheduled task in Claude Desktop against BRETT's connector calling `fitness_ping`; record whether it succeeds or reproduces the "tool schemas never injected" failure into `13-SPIKE-RESULT.md`'s `## Spike 1` section, run FIRST so a negative result reshapes scope early (PITFALLS #17) |
| Real Claude scheduled task run against the actual report tools | RPT-03 (plan 13-10, wave 7) | Same as above — human-gated, live connector | Create a scheduled task referencing `fitness_get_weekly_report`/`fitness_get_monthly_report`; record the outcome into `docs/coaching-instructions.md` and `13-SPIKE-RESULT.md`'s `## Spike 2` section (D-13: workaround preamble added ONLY if the failure reproduces) |
| Nutrition coverage floor query against production data | D-06 (plan 13-02, wave 1, informs plan 13-04's NUTR-04 implementation) | This session's research sandbox blocked all live-database query attempts (`psql`/`asyncpg`/`gcloud secrets access` denied); needs a human operator or the executor's own `gcloud secrets versions access` path with real `DATABASE_URL` access | Run the coverage-count SQL from `13-RESEARCH.md` Pitfall 3 against production; if unreachable, fall back to the documented historical estimate (~3.3% coverage) and flag `MEASURED_DAY_FLOORS`-equivalent constants as UNMEASURED with a follow-up required, per the BODY-05 (Phase 11) precedent |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
