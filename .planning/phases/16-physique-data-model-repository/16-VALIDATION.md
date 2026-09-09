---
phase: 16
slug: physique-data-model-repository
status: planned
nyquist_compliant: true
wave_0_complete: true
created: 2026-09-09
updated: 2026-09-09
---

# Phase 16 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 + pytest-asyncio (`asyncio_mode = "auto"`), per `pyproject.toml` |
| **Config file** | `pyproject.toml` at the REPO ROOT (`testpaths = ["backend/tests"]`, `pythonpath = ["backend"]`); `backend/alembic.ini` for migrations |
| **Working directory** | Repo root for every `pytest`/`ruff`/`mypy` command. Only `alembic` runs with `cwd=backend/` (the `alembic` fixture already does this). |
| **Quick run command** | `uv run pytest -m "not integration"` |
| **Full suite command** | `uv run pytest` (includes `@pytest.mark.integration`, spins the shared session-scoped `postgres:18-alpine` container) |
| **Estimated runtime** | ~5s quick / ~60s full |

---

## Sampling Rate

- **After every task commit:** `uv run pytest -m "not integration"`
- **After every plan wave:** `uv run pytest` (full suite, including the migration round-trip and `test_db_physique.py`)
- **Before `/gsd-verify-work`:** Full suite green, with explicit confirmation that `test_migrations_round_trip` and `test_no_pending_model_drift` pass UNCHANGED (ROADMAP criteria 2 and 5 name these tests directly), and that `test_mcp_isolation.py` / `test_mcp_tool_schemas.py` pass unmodified (Phase 16 adds no MCP surface)
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 16-01-T1 | 01 | 1 | PHYS-01, PHYS-03 | T-16-01, T-16-04 | `PhysiqueRatingLevel`/`PoseState`/`PhotoAngle` carry exactly the locked values; four CHECK constraints resolve to `ck_<table>_<label>`; no native ENUM; no `relationship()` | unit | `uv run ruff check backend/app/db/models/physique.py` + the inline `python -c` assertion block in the plan | ❌ created by this task | ⬜ pending |
| 16-01-T2 | 01 | 1 | PHYS-01, PHYS-04, PHYS-05 | T-16-06, T-16-07 | Both tables named on purpose in the exact-equality metadata guard; note caps 500/500/200/160 not transposed; `observed_on` is a `Date`; `superseded_by_id` FK is SET NULL; credential-name guard still clean | unit | `uv run pytest backend/tests/test_db_models.py -k physique -q` and `uv run pytest -m "not integration" -q` | ❌ created by this task | ⬜ pending |
| 16-02-T1 | 02 | 2 | PHYS-01..PHYS-05 | T-16-11, T-16-16 | Migration 0007 applies, reverses to base leaving only `alembic_version`, and matches the models (`alembic check`) | integration | `uv run pytest backend/tests/test_migrations.py -m integration -q` | ✅ existing — must keep passing unchanged | ⬜ pending |
| 16-02-T2 | 02 | 2 | (all) | T-16-14 | Committed physique rows are purged FK-child-first between tests; no `KeyError` gap in `_mcp_purge_statements` | integration | `uv run pytest backend/tests/test_db_program_history.py backend/tests/test_migrations.py -m integration -q` | ✅ existing — extended | ⬜ pending |
| 16-02-T3 | 02 | 2 | PHYS-02 | T-16-10 | A rating row with neither or both of `rating_level`/`not_assessable_reason` is refused by the database | integration | `uv run pytest backend/tests/test_db_physique.py::test_not_assessable_xor_rating -m integration -q` | ❌ created by this task | ⬜ pending |
| 16-02-T3 | 02 | 2 | PHYS-04 | T-16-13 | Three note fields round-trip at their exact caps (500/500/500) and a 501-char write is refused | integration | `uv run pytest backend/tests/test_db_physique.py::test_note_field_caps -m integration -q` | ❌ created by this task | ⬜ pending |
| 16-02-T3 | 02 | 2 | PHYS-05 | T-16-10 | `photo_angles_present` restricted to `{front,back,side}` (the `<@` operator's only proof); `pose_state` restricted to `{relaxed,lightly_flexed}`; `conditions_note` independent of ratings | integration | `uv run pytest backend/tests/test_db_physique.py::test_confounder_metadata -m integration -q` | ❌ created by this task | ⬜ pending |
| 16-02-T3 | 02 | 2 | PHYS-03 | T-16-11, T-16-12 | Live column sets match exactly; `pg_type` holds no enum; duplicate `(observation_id, muscle_group)` refused | integration | `uv run pytest backend/tests/test_db_physique.py -m integration -q` | ❌ created by this task | ⬜ pending |
| 16-03-T1 | 03 | 3 | PHYS-02, PHYS-03 | T-16-17, T-16-18, T-16-20 | Repository never commits, scopes every query on `user_id`, and validates the 19-row coverage before issuing any statement | unit | `uv run mypy backend/app/db/repositories/physique.py` + `uv run pytest -m "not integration" -q` | ❌ created by this task | ⬜ pending |
| 16-03-T2 | 03 | 3 | PHYS-01, PHYS-02, PHYS-03 | T-16-17, T-16-19, T-16-22 | Full write/read round trip with 19 ratings in canonical order; abductors/adductors with no special-casing (grep-proven); incomplete/duplicate/both-or-neither refused with zero rows written; cross-tenant read returns nothing | integration | `uv run pytest backend/tests/test_db_physique.py -m integration -q` and `uv run pytest -q` | ❌ created by this task | ⬜ pending |
| (phase gate) | — | 3 | (all) | T-16-22 | Phase 16 adds no MCP surface — `_WRITE_ALLOWLIST` still `{"program_switch.py"}` | unit | `uv run pytest backend/tests/test_mcp_isolation.py backend/tests/test_mcp_tool_schemas.py -q` | ✅ existing — must pass unmodified | ⬜ pending |

---

## Wave 0 Requirements

All resolved — every MISSING test file is created by the plan task that also creates the code it
exercises, so no task ships with an unverifiable `<verify>`:

- [x] `backend/app/db/models/physique.py` — created by 16-01-T1, verified by 16-01-T2's unit tests
- [x] `backend/tests/test_db_models.py` physique guards — added by 16-01-T2 (existing file, edited: `test_metadata_contains_expected_tables` is an EXACT-equality assertion, so this edit is mandatory, not optional — 16-RESEARCH.md Pitfall 2)
- [x] `backend/tests/test_db_physique.py` — created by 16-02-T3 (schema half), extended by 16-03-T2 (repository half)
- [x] `backend/app/db/repositories/physique.py` — created by 16-03-T1
- [x] `GoldenBuilder.physique_observation` fixture helper + `_MCP_PURGE_TABLES` entries — added by 16-02-T2

---

## Manual-Only Verifications

*None — all phase behaviors have automated verification.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (all 7 tasks carry one)
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 60s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved at planning (2026-09-09)
