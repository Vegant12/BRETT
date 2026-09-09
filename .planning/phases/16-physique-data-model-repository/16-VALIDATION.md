---
phase: 16
slug: physique-data-model-repository
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-09-09
---

# Phase 16 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 + pytest-asyncio (`asyncio_mode = "auto"`), per `pyproject.toml` |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`), `backend/alembic.ini` for migrations |
| **Quick run command** | `uv run pytest -m "not integration"` |
| **Full suite command** | `uv run pytest` (includes `@pytest.mark.integration`, spins the shared session-scoped Postgres container) |
| **Estimated runtime** | ~5s quick / ~60s full (Postgres container) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest -m "not integration"`
- **After every plan wave:** Run `uv run pytest` (full suite, including migration round-trip and new `test_db_physique.py` integration tests)
- **Before `/gsd-verify-work`:** Full suite must be green, with explicit confirmation that `test_migrations_round_trip` and `test_no_pending_model_drift` pass unchanged (phase success criteria 2 and 5 name these tests directly)
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 16-01-XX | 01 | 0 | PHYS-01 | — | `PhysiqueRatingLevel` StrEnum has exactly the 5 spike-confirmed values, no invented intermediate | unit | `pytest backend/tests/test_db_models.py -k physique -x` | ❌ W0 | ⬜ pending |
| 16-01-XX | 01 | 0 | PHYS-02 | — | A rating row with `rating_level=None, not_assessable_reason=None` (or both set) is rejected by the DB | integration | `pytest backend/tests/test_db_physique.py::test_not_assessable_xor_rating -x -m integration` | ❌ W0 | ⬜ pending |
| 16-01-XX | 01 | 0 | PHYS-03 | — | Header + child insert/read round-trips; `rating_level` uses `String`+CHECK not native ENUM; migration `0007` up/down leaves no orphaned `pg_type` | integration | `pytest backend/tests/test_migrations.py::test_migrations_round_trip -x -m integration` | ✅ existing — must keep passing unchanged | ⬜ pending |
| 16-01-XX | 01 | 0 | PHYS-04 | — | Three independently-capped note fields persist and round-trip at their exact caps (500/500/500) | integration | `pytest backend/tests/test_db_physique.py::test_note_field_caps -x -m integration` | ❌ W0 | ⬜ pending |
| 16-01-XX | 01 | 0 | PHYS-05 | — | `photo_angles_present` restricted to `{front,back,side}`; `pose_state` restricted to `{relaxed,lightly_flexed}`; `conditions_note` independent of ratings | integration | `pytest backend/tests/test_db_physique.py::test_confounder_metadata -x -m integration` | ❌ W0 | ⬜ pending |
| 16-01-XX | 01 | 0 | (all) | — | `Base.metadata` table set includes the two new tables | unit | `pytest backend/tests/test_db_models.py::test_metadata_contains_expected_tables -x` | ✅ existing — must be edited (Pitfall 2) | ⬜ pending |
| 16-01-XX | 01 | 0 | (all) | — | No new column trips the credential-shaped-name guard | unit | `pytest backend/tests/test_db_models.py -k credential -x` | ✅ existing — should pass unmodified | ⬜ pending |

*Task IDs are placeholders pending planner output; the planner must map each row to its actual task ID.*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_db_physique.py` — new file, covers PHYS-02/04/05 and the header/child round-trip (PHYS-03's non-migration half)
- [ ] `backend/app/db/models/physique.py` — new model file (prerequisite the above tests import)
- [ ] `backend/app/db/repositories/physique.py` — new repository file (same prerequisite note)
- [ ] `backend/tests/test_db_models.py::test_metadata_contains_expected_tables` — existing test, needs its expected-table set and docstring updated (Pitfall 2), not created fresh
- [ ] Optional: a `GoldenBuilder`-style fixture helper for constructing a full 19-rating observation in tests, mirroring `conftest.py`'s existing `golden_workout`/`GoldenBuilder` pattern — not strictly required (tests can hand-build 19 rows inline) but reduces repetition across the PHYS-02/04/05 test cases

---

## Manual-Only Verifications

*None — all phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
