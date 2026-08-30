---
phase: 4
slug: volume-frequency-analytics
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-08-30
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 + pytest-asyncio 1.4.0 (`asyncio_mode = "auto"` — no decorator needed) |
| **Config file** | `pyproject.toml` → `[tool.pytest.ini_options]` (`testpaths = ["backend/tests"]`, `pythonpath = ["backend"]`, marker `integration`) |
| **Quick run command** | `.venv/bin/python -m pytest -q -m "not integration"` |
| **Full suite command** | `.venv/bin/python -m pytest -q` |
| **Estimated runtime** | ~1 second fast suite (measured baseline: 177 passed, 114 deselected in 0.94s); full suite is container-backed (testcontainers[postgres]) |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/python -m pytest -q -m "not integration"`
- **After every plan wave:** Run `.venv/bin/python -m pytest -q` (full suite, container-backed)
- **Before `/gsd-verify-work`:** Full suite green + `ruff check` + `mypy`
- **Max feedback latency:** ~5 seconds (fast suite must stay near the 0.94s baseline)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | TBD | 0 | VOL-01 | — | Warm-up sets excluded from hard sets, reps and tonnage | integration | `pytest backend/tests/test_analytics_volume.py -k warmup -x` | ❌ Wave 0 | ⬜ pending |
| TBD | TBD | 0 | VOL-01 | — | `dropset` counts as a hard set; filter is `!= 'warmup'` not `== 'normal'` | integration | `pytest backend/tests/test_analytics_volume.py -k dropset -x` | ❌ Wave 0 | ⬜ pending |
| TBD | TBD | 0 | VOL-01 | — | Tonnage is `None` (never `0`) where the modality has no `weight × reps`; `tonnage_sets` reports coverage | integration | `pytest backend/tests/test_analytics_volume.py -k modality -x` | ❌ Wave 0 | ⬜ pending |
| TBD | TBD | 0 | VOL-01 | — | `weight_kg = 0` counts as a tonnage set contributing `Decimal("0.000")` | integration | `pytest backend/tests/test_analytics_volume.py -k zero_load -x` | ❌ Wave 0 | ⬜ pending |
| TBD | TBD | 0 | VOL-01 / D-02 | — | A `2026-08-23T17:00:00Z` workout buckets to local week `2026-08-24`; changing `users.timezone` changes the bucket | integration | `pytest backend/tests/test_analytics_volume.py -k week_boundary -x` | ❌ Wave 0 | ⬜ pending |
| TBD | TBD | 0 | VOL-02 | — | `direct_sets` / `indirect_sets` raw counts + `weighted_sets` exact `Decimal` at default 1.0/0.5 | integration | `pytest backend/tests/test_analytics_volume.py -k muscle_split -x` | ❌ Wave 0 | ⬜ pending |
| TBD | TBD | 0 | VOL-02 / NORM-03 | — | Passing `{DIRECT: 0.8, INDIRECT: 0.3}` changes `weighted_sets` and leaves raw counts untouched | integration | `pytest backend/tests/test_analytics_volume.py -k custom_weights -x` | ❌ Wave 0 | ⬜ pending |
| TBD | TBD | 0 | VOL-02 / NORM-02 | — | An `exercise_muscle_overrides` row changes the per-muscle result (proves the resolver is used, not a raw join) | integration | `pytest backend/tests/test_analytics_volume.py -k override -x` | ❌ Wave 0 | ⬜ pending |
| TBD | TBD | 0 | VOL-03 | — | Per-muscle `sessions` de-duplicates workouts — 3 hamstring exercises in one workout is 1 session | integration | `pytest backend/tests/test_analytics_frequency.py -k dedup -x` | ❌ Wave 0 | ⬜ pending |
| TBD | TBD | 0 | VOL-03 | — | `sessions_per_week` over an arbitrary (non-multiple-of-7) range is exact and quantized | unit + integration | `pytest backend/tests/test_analytics_frequency.py -k per_week -x` | ❌ Wave 0 | ⬜ pending |
| TBD | TBD | 0 | VOL-03 | — | Per-exercise frequency reported alongside per-muscle | integration | `pytest backend/tests/test_analytics_frequency.py -k exercise -x` | ❌ Wave 0 | ⬜ pending |
| TBD | TBD | 0 | DQ-01 | — | Response carries `last_synced_at` from `sync_state`; per-muscle responses carry both `workouts` and `exercise_templates` | integration | `pytest backend/tests/test_analytics_metadata.py -k freshness -x` | ❌ Wave 0 | ⬜ pending |
| TBD | TBD | 0 | DQ-01 | — | No `sync_state.last_error`, status detail, DSN or credential appears in any return model | unit | `pytest backend/tests/test_analytics_metadata.py -k no_leak -x` | ❌ Wave 0 | ⬜ pending |
| TBD | TBD | 0 | DQ-02 | — | `insufficient_data` is `True` at 1 session, `False` at 2 (D-05 boundary, both sides) | integration | `pytest backend/tests/test_analytics_metadata.py -k insufficient -x` | ❌ Wave 0 | ⬜ pending |
| TBD | TBD | 0 | DQ-02 | — | `earliest_data_at` is the oldest synced workout, and is `None` with no data | integration | `pytest backend/tests/test_analytics_metadata.py -k earliest -x` | ❌ Wave 0 | ⬜ pending |
| TBD | TBD | 0 | Criterion 5 | — | Superset fixture produces numbers identical to the non-superset equivalent | integration | `pytest backend/tests/test_analytics_volume.py -k superset -x` | ❌ Wave 0 | ⬜ pending |
| TBD | TBD | 0 | Architecture | — | `app/analytics/` imports nothing from `app.mcp` or `app.integrations` | unit (static, no integration marker) | `pytest backend/tests/test_analytics_isolation.py -x` | ❌ Wave 0 | ⬜ pending |
| TBD | TBD | 0 | Regression | — | Fast suite stays green and fast | unit | `.venv/bin/python -m pytest -q -m "not integration"` | ✅ 177 passing | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_analytics_volume.py` — VOL-01, VOL-02
- [ ] `backend/tests/test_analytics_frequency.py` — VOL-03
- [ ] `backend/tests/test_analytics_metadata.py` — DQ-01, DQ-02
- [ ] `backend/tests/test_analytics_isolation.py` — architectural boundary (static, fast suite)
- [ ] `backend/tests/conftest.py` — `golden_workout` builder fixture (flush + rollback, never commit)
- [ ] Framework install: **none needed** — pytest, pytest-asyncio, testcontainers and time-machine are all installed and already used by 291 existing tests

---

## Manual-Only Verifications

*None — all phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
