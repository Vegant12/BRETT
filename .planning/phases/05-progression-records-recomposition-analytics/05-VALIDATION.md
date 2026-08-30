---
phase: 05
slug: progression-records-recomposition-analytics
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-08-30
---

# Phase 05 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 + pytest-asyncio 1.4.0 (`asyncio_mode = "auto"` — no decorator needed) |
| **Config file** | `pyproject.toml` → `[tool.pytest.ini_options]` (`testpaths = ["backend/tests"]`, `pythonpath = ["backend"]`, marker `integration`) |
| **Quick run command** | `.venv/bin/python -m pytest -q -m "not integration"` |
| **Full suite command** | `.venv/bin/python -m pytest -q` |
| **Estimated runtime** | ~1 second fast suite (206 passed, 163 deselected in 0.94s measured baseline, 2026-08-30); full suite is container-backed (testcontainers[postgres]) |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/python -m pytest -q -m "not integration"`
- **After every plan wave:** Run `.venv/bin/python -m pytest -q` (full suite, container-backed)
- **Before `/gsd-verify-work`:** Full suite green + `ruff check` + `mypy`
- **Max feedback latency:** ~5 seconds (fast suite); full suite budget ~60s (container startup)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD-01 | TBD | 0 | PROG-01/D-01 | — | Epley exact values, Decimal-only | unit (fast) | `pytest backend/tests/test_analytics_estimates.py -k epley -x` | ❌ W0 | ⬜ pending |
| TBD-02 | TBD | 0 | PROG-01/D-02 | — | ≤12 reps gate boundary | unit (fast) | `pytest backend/tests/test_analytics_estimates.py -k rep_gate -x` | ❌ W0 | ⬜ pending |
| TBD-03 | TBD | 0 | PROG-01/D-03 | — | modality gate returns null+reason | unit (fast) | `pytest backend/tests/test_analytics_estimates.py -k modality -x` | ❌ W0 | ⬜ pending |
| TBD-04 | TBD | 0 | PROG-01 | — | Epley never computed in SQL (integer-division trap) | unit (static) | `pytest backend/tests/test_analytics_isolation.py -k formula -x` | ❌ W0 | ⬜ pending |
| TBD-05 | TBD | 1 | PROG-01/D-04 | — | best-e1RM set selection + tie-break | integration | `pytest backend/tests/test_analytics_progression.py -k best_set -x` | ❌ W0 | ⬜ pending |
| TBD-06 | TBD | 1 | PROG-02/D-05 | — | 4-week minimum boundary | integration | `pytest backend/tests/test_analytics_progression.py -k min_weeks -x` | ❌ W0 | ⬜ pending |
| TBD-07 | TBD | 1 | PROG-02 | — | Decimal-exact OLS slope + dead-band | unit (fast) | `pytest backend/tests/test_analytics_progression.py -k slope_exact -x` | ❌ W0 | ⬜ pending |
| TBD-08 | TBD | 1 | PROG-03/D-06/D-07 | — | adaptive window + calendar floor + tolerance | integration | `pytest backend/tests/test_analytics_progression.py -k plateau_window -x` | ❌ W0 | ⬜ pending |
| TBD-09 | TBD | 1 | PROG-03/D-07a/D-07b | — | null-e1RM skip + full result shape | integration | `pytest backend/tests/test_analytics_progression.py -k skip_null -x` | ❌ W0 | ⬜ pending |
| TBD-10 | TBD | 1 | PROG-04/D-08/D-09 | — | set_type eligibility + earliest-date tie-break | integration | `pytest backend/tests/test_analytics_records.py -k set_type -x` | ❌ W0 | ⬜ pending |
| TBD-11 | TBD | 1 | CMP-01 | — | per-week normalization, no snap, null baseline | integration | `pytest backend/tests/test_analytics_comparison.py -k unequal_length -x` | ❌ W0 | ⬜ pending |
| TBD-12 | TBD | 1 | BODY-01/D-13-D-17 | — | no interpolation, source tie-break, per-window floors, smoothed rate | integration | `pytest backend/tests/test_analytics_bodyweight.py -k no_interpolation -x` | ❌ W0 | ⬜ pending |
| TBD-13 | TBD | 2 | BODY-02/D-10-D-12 | — | threshold boundaries + aggregation matrix | integration | `pytest backend/tests/test_analytics_recomposition.py -k gain_threshold -x` | ❌ W0 | ⬜ pending |
| TBD-14 | TBD | 0/2 | ASVS V4 | T-05-01 | tenant isolation on all new queries | integration | `pytest backend/tests/test_analytics_progression.py -k tenant -x` | ❌ W0 | ⬜ pending |
| TBD-15 | TBD | 0/2 | C-2 | T-05-02 | no float in app/analytics | unit (static, fast) | `pytest backend/tests/test_analytics_isolation.py -k no_float -x` | ⚠️ extend | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*
*Exact Task IDs are assigned by the planner; this table's rows are the requirement-to-test contract every plan must satisfy — see 05-RESEARCH.md "Phase Requirements → Test Map" for the full 40-case list.*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_analytics_estimates.py` — PROG-01 D-01/D-02/D-03 (fast suite, no container)
- [ ] `backend/tests/test_analytics_progression.py` — PROG-01/02/03
- [ ] `backend/tests/test_analytics_records.py` — PROG-04
- [ ] `backend/tests/test_analytics_comparison.py` — CMP-01
- [ ] `backend/tests/test_analytics_bodyweight.py` — BODY-01
- [ ] `backend/tests/test_analytics_recomposition.py` — BODY-02
- [ ] `backend/tests/conftest.py` — add `GoldenBuilder.body_measurement()` (flush + rollback, never commit)
- [ ] `backend/tests/test_analytics_isolation.py` — extend with a `no_float` guard and a "no Epley in SQL" guard
- [ ] `backend/tests/test_analytics_metadata.py` — extend for `MeasurementCoverage` and body freshness
- [ ] Framework install: none needed — pytest, pytest-asyncio, testcontainers and time-machine already installed and used by 369 existing tests

---

## Manual-Only Verifications

*None — all phase behaviors have automated verification. BODY-01/BODY-02 live-data timing sensitivity (the D-16 anchor window clears its coverage floor around 2026-09-06) is handled via `time-machine` fixtures, not manual checks.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s (fast suite) / < 60s (full suite)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
