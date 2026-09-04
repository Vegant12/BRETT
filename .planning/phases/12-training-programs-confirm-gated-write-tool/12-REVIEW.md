---
phase: 12-training-programs-confirm-gated-write-tool
reviewed: 2026-09-04T05:15:27Z
depth: standard
files_reviewed: 24
files_reviewed_list:
  - backend/app/analytics/recomposition.py
  - backend/app/analytics/schemas.py
  - backend/app/db/models/__init__.py
  - backend/app/db/models/program.py
  - backend/app/db/repositories/programs.py
  - backend/app/mcp/server.py
  - backend/app/mcp/tools/_common.py
  - backend/app/mcp/tools/program_switch.py
  - backend/app/mcp/tools/programs.py
  - backend/app/mcp/tools/schemas.py
  - backend/migrations/versions/0006_user_program_history.py
  - backend/tests/conftest.py
  - backend/tests/test_analytics_recomposition.py
  - backend/tests/test_db_models.py
  - backend/tests/test_db_program_history.py
  - backend/tests/test_mcp_auth.py
  - backend/tests/test_mcp_isolation.py
  - backend/tests/test_mcp_mount.py
  - backend/tests/test_mcp_program_switch.py
  - backend/tests/test_mcp_schemas.py
  - backend/tests/test_mcp_tool_budget.py
  - backend/tests/test_mcp_tool_schemas.py
  - backend/tests/test_mcp_tools.py
  - docs/coaching-instructions.md
  - scripts/verify-restore.sql
findings:
  critical: 0
  warning: 1
  info: 1
  total: 2
status: issues_found
---

# Phase 12: Code Review Report

**Reviewed:** 2026-09-04T05:15:27Z
**Depth:** standard
**Files Reviewed:** 24
**Status:** issues_found

## Summary

This phase adds the append-only `user_program_history` / `program_switch_tokens` schema, the
`programs.py` repository (the system's one writer of program data), the confirm-gated
`fitness_switch_training_program` write tool, the paired `fitness_get_training_program` read
tool, the per-program recomposition threshold/label matrices in `app/analytics/recomposition.py`,
and the MCP registration/annotation/budget/isolation guards that keep the write tool narrowly
scoped.

The implementation is unusually well-defended: the two-call token-gate design (server-minted
CSPRNG nonce, single-use, target-program-bound, atomically consumed via one `UPDATE ... WHERE
... RETURNING`), the `_WRITE_ALLOWLIST`/`_WRITE_IMPORT`/`_SESSION_WRITE` static guards restricting
writes to exactly one module, the PostgreSQL-enforced "one open period" partial unique index, and
the three independently-verified label matrices (76 cells total) in `recomposition.py` are all
correctly implemented and align with their extensive design-rationale docstrings. `ruff check` and
`mypy` are clean on every reviewed source file, and the full backend test suite passes except for
one pre-existing, unrelated flaky test noted below (982 passed, 1 failed on a full run; the two
Phase-12-specific integration suites, `test_db_program_history.py` and `test_mcp_program_switch.py`,
pass 31/31).

No security, correctness, or data-integrity issues were found in the phase's own code (schema,
repository, tools, migration, coaching doc, restore-verification script). The two findings below
are minor: one pre-existing test-reliability bug in a file that is in scope but was not touched by
this phase's diff, and one stale code comment.

## Warnings

### WR-01: Time-of-day-dependent flaky test collides on `measured_on` with its own fixture

**File:** `backend/tests/test_mcp_tools.py:963-981` (also see `_seed_reference_history`,
`backend/tests/test_mcp_tools.py:191-283`, and `_reference_anchor`, `backend/tests/test_mcp_tools.py:176-188`)

**Issue:** `test_body_measurement_trend_compares_latest_against_earliest` calls
`_seed_reference_history`, which inserts one `body_measurements` row per day for
`REFERENCE_BODY_MEASUREMENT_DAYS` (30) days counting back from `_reference_anchor().date()`
(`anchor_day`) — including `offset=0`, i.e. `measured_on=anchor_day` itself. `_reference_anchor()`
returns *today* (UTC) whenever `utc_now().hour >= _REFERENCE_HOUR` (2), which is true for 22 of
every 24 hours. The test then separately calls
`committed_history.body_measurement(measured_on=today, weight_kg=None, waist_cm=Decimal("81.50"))`
where `today = utc_now().date()`. When `anchor_day == today` (the common case), this is a second
INSERT for the same `(user_id, source, measured_on)` key, and it raises
`IntegrityError: duplicate key value violates unique constraint
"uq_body_measurements_user_source_measured_on"`. Verified live: running the full backend suite at
the time of this review failed exactly this test with that error.

This bug predates Phase 12 (introduced in commit `249b13b`, "test(11-03)"), and no Phase 12 diff
touches this test function — it is unrelated to the training-program/write-tool work under
review. It is flagged here because `backend/tests/test_mcp_tools.py` is in this phase's reviewed
file list and the failure is real and currently reproducible (fails ~22 hours out of every 24),
which threatens CI reliability for a file this phase does touch elsewhere (the `MINIMAL_TOOL_ARGUMENTS`
map, the leak-test parametrization, the new `fitness_get_training_program`/`fitness_switch_training_program`
integration test added at the end of the file).

**Fix:** Pick a `measured_on` for the test's own two explicit rows that cannot collide with
`_seed_reference_history`'s 30-day window regardless of time of day, e.g. anchor everything off
the same `anchor_day` the fixture already returns instead of a freshly computed `utc_now().date()`:

```python
async def test_body_measurement_trend_compares_latest_against_earliest(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """BODY-05 end to end: a real two-point comparison arrives as structured content."""
    from mcp import Client

    from app.mcp.server import mcp

    anchor_day = (await _seed_reference_history(committed_history, session)).date()
    await committed_history.body_measurement(
        measured_on=anchor_day - dt.timedelta(days=60),
        weight_kg=None,
        waist_cm=Decimal("85.00"),
    )
    # anchor_day itself already carries a seeded row (offset=0); overwrite is not possible via
    # the builder, so pick a day inside the window `_seed_reference_history` does NOT touch, or
    # update the pre-seeded row's waist_cm at anchor_day instead of inserting a second one.
    ...
```
The simplest fix is to reuse the anchor day the fixture already returns and update (rather than
re-insert) that day's row, or to choose an explicit offset outside `range(REFERENCE_BODY_MEASUREMENT_DAYS)`
for both points so neither can collide with the fixture's own seeded days.

## Info

### IN-01: Stale comment describes tools as unregistered after they were registered

**File:** `backend/tests/test_mcp_isolation.py:296-301`

**Issue:** The comment above `test_every_tool_module_guards_its_public_tools`'s count assertion
still reads: *"Raised from 13 to 15 in Plan 12-04, which adds `fitness_get_training_program`
(`programs.py`) and `fitness_switch_training_program` (`program_switch.py`) -- neither is
registered in `server.py` yet, deliberately: that is Plan 05's job..."* This was accurate when
Plan 12-04 landed, but `backend/app/mcp/server.py` now registers both tools (confirmed by reading
`server.py:48-61` and the `_TOOLS`/`mcp.add_tool` calls for `fitness_switch_training_program`).
The comment no longer describes the current state of the code, which could mislead a future
reader auditing the write-tool registration story.

**Fix:** Update or remove the now-stale clause, e.g.:

```python
# The literal 15 is the whole point of this assertion, so it is written as a literal rather
# than derived from anything: the loop above proves every tool it FINDS is decorated, which
# says nothing if the walk found none of them. Raised from 13 to 15 in Plan 12-04, which added
# `fitness_get_training_program` (`programs.py`) and `fitness_switch_training_program`
# (`program_switch.py`); both are now registered in `server.py` by Plan 12-05.
```

---

_Reviewed: 2026-09-04T05:15:27Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
