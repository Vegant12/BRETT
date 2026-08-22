---
phase: 01-backend-foundation
plan: 04
subsystem: core
tags: [timezone, zoneinfo, timestamptz, analytics-foundation, found-03, found-04]
requires:
  - "app.db.models.User.timezone (Plan 01-03)"
  - "backend/tests/conftest.py session fixture + seeded default user (Plan 01-03)"
provides:
  - "app.core.time.utc_now / to_local / local_day / local_week_start / local_day_bounds / validate_timezone"
  - "backend/tests/test_time.py — the standing FOUND-03/FOUND-04 guard"
affects:
  - "Phase 4 analytics (weekly volume, training frequency, rolling averages) must bucket through app.core.time"
  - "Any future model adding a timestamp column is checked by test_timestamps_are_timestamptz"
tech-stack:
  added: []
  patterns:
    - "tz is always a function parameter, never a module constant or env var — FOUND-03 means users.timezone"
    - "Naive datetimes raise ValueError at the helper boundary rather than being assumed UTC"
    - "local_day_bounds() for index-friendly WHERE filtering; AT TIME ZONE only inside date_trunc aggregates"
    - "Container-mutating tests roll back in a finally instead of issuing a compensating UPDATE"
key-files:
  created:
    - backend/app/core/__init__.py
    - backend/app/core/time.py
    - backend/tests/test_time.py
  modified:
    - .planning/REQUIREMENTS.md
decisions:
  - "validate_timezone lives in app.core.time, not on the User model — the DB has no CHECK constraint on users.timezone, and the failure it prevents (ZoneInfoNotFoundError deep inside a Phase 4 aggregate) is a bucketing failure, so it belongs beside the bucketing helpers"
  - "Mutating integration tests roll back rather than issuing a compensating UPDATE; rollback also cleans up when an assertion fails mid-test, which a compensating write does not"
  - "The word 'utcnow' is absent from app/core/time.py even in prose — the repo-wide grep guard is a literal string search, so documenting the banned call by name would trip its own guard"
  - "SQL bind parameters are explicitly cast (cast(:ts as timestamptz) AT TIME ZONE cast(:tz as text)) because asyncpg cannot infer a parameter type in an AT TIME ZONE operand position"
metrics:
  duration: ~25 min
  tasks: 2
  completed: 2026-08-23
---

# Phase 1 Plan 04: Timezone Bucketing Helpers Summary

Six pure functions in `app/core/time.py` that convert aware-UTC instants into user-local days and weeks, with a naive-datetime guard, plus a 14-test acceptance suite proving the Jakarta boundary cases, DB-sourced timezone configurability, and exact agreement with Postgres `AT TIME ZONE` + `date_trunc`.

## What Was Built

**`app/core/time.py`** — the single sanctioned path for every day/week grouping in the project. The exported contract, which Phase 4+ analytics consume:

```python
def utc_now() -> dt.datetime                                                   # aware, UTC
def to_local(ts: dt.datetime, tz: str) -> dt.datetime
def local_day(ts: dt.datetime, tz: str) -> dt.date
def local_week_start(ts: dt.datetime, tz: str) -> dt.date                      # Monday
def local_day_bounds(day: dt.date, tz: str) -> tuple[dt.datetime, dt.datetime] # half-open UTC
def validate_timezone(tz: str) -> str                                          # ValueError on bad IANA
```

The private `_require_aware()` guard sits under `to_local`, so every derived helper (`local_day`, `local_week_start`) inherits naive-datetime rejection without repeating the check.

`tz` is a parameter on every function. There is no module-level constant, no `os.environ` read, and no `get_settings()` call — verified by grep in the acceptance criteria. This matters more than it looks: FOUND-03 says the timezone comes from user configuration, and a module default would let a "reads the wrong source" bug pass every test in the suite.

**`backend/tests/test_time.py`** — 14 tests, 8 of them container-backed and marked `@pytest.mark.integration`.

The core assertion is the boundary table, parametrized over four verified instants. `2026-08-23T23:30:00+00:00` — the "near midnight UTC" case named in the ROADMAP — buckets to local day `2026-08-24`, where naive-UTC bucketing would say `2026-08-23`. At UTC+7 this is not an edge case: every instant between 17:00Z and 24:00Z belongs to the next local day, which covers every morning workout.

Every bucketing test reads the timezone with `select timezone from users` and passes the *result* to the helper. Hardcoding `"Asia/Jakarta"` as the argument would make the tests pass even if the column were ignored entirely.

`test_python_and_sql_bucketing_agree` is the one that earns its keep long-term: analytics will filter in Python and aggregate in SQL, and a divergence between `local_day()` and `date_trunc('day', ts AT TIME ZONE tz)` would produce wrong numbers that no single-layer test could catch.

`test_timestamps_are_timestamptz` asserts across the whole `public` schema rather than just `users`, so it becomes a standing guard: any future model reaching for a bare `DateTime()` fails here.

## Key Decisions

**`validate_timezone` placement.** It went in `app.core.time` rather than as a model validator on `User`. `users.timezone` carries no DB-level CHECK constraint, so a bad IANA name would otherwise surface as a `ZoneInfoNotFoundError` raised from inside a Phase 4 aggregate query — far from the cause. The failure it prevents is a bucketing failure, so it belongs beside the bucketing helpers. It raises a bare `ValueError("unknown IANA timezone")` without echoing the offending value.

**Test isolation via rollback, not compensating writes.** The Postgres container is session-scoped, and `test_migrations.py` asserts both `count(*) == 1` on `users` and the seeded `Asia/Jakarta` value. The plan called for a `try/finally` compensating `UPDATE`. Both mutating tests do that *and* `await session.rollback()` in the `finally`. Rollback is the stronger guarantee — it also cleans up when an assertion fails partway through, where a compensating write placed after the failed assertion would never run. `test_roundtrip_is_aware_utc` never commits at all: `flush()` + `expire()` forces the value through Postgres and back inside the transaction, proving the TIMESTAMPTZ round-trip without leaving a second user row behind.

**No test-isolation fixture was added.** Per-test rollback inside the two mutating tests was sufficient; a shared autouse fixture would have added coupling for no gain. The full 44-test suite passes with no cross-test pollution.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed the literal string `utcnow` from the module docstring**

- **Found during:** Task 1, acceptance-criteria verification
- **Issue:** The plan supplied `utc_now()`'s docstring verbatim as "Never use `datetime.utcnow()`...". That prose tripped two of the plan's own checks: the Task 1 criterion `grep -c 'utcnow' backend/app/core/time.py` returns 0, and the plan-level verification `grep -rn "utcnow" backend/ --include=*.py` must return nothing. The guard is a literal string search, so documenting the banned call by name defeats it.
- **Fix:** Reworded to describe the deprecated no-argument UTC constructor without naming it, and pointed at Ruff's `DTZ` rules as the enforcement mechanism. The guidance is preserved; the token is gone.
- **Files modified:** `backend/app/core/time.py`
- **Commit:** db3eef2

**2. [Rule 1 - Bug] Removed the hardcoded `Asia/Jakarta` from the module docstring**

- **Found during:** Task 1, acceptance-criteria verification
- **Issue:** Same class of problem — the criterion `grep -c 'Asia/Jakarta' backend/app/core/time.py` returns 0, and the first draft of the module docstring used Jakarta to illustrate the 17:00Z boundary.
- **Fix:** Rephrased to "at a UTC+7 offset", which is the property that actually matters and does not imply a default.
- **Files modified:** `backend/app/core/time.py`
- **Commit:** db3eef2

**3. [Rule 3 - Blocking] Added explicit SQL casts around the `AT TIME ZONE` bind parameters**

- **Found during:** Task 2
- **Issue:** The plan's SQL was `date_trunc('day', :ts AT TIME ZONE :tz)::date`. asyncpg cannot infer a parameter type for an operand in that position, so the query risks `could not determine data type of parameter`.
- **Fix:** `date_trunc('day', cast(:ts as timestamptz) AT TIME ZONE cast(:tz as text))::date`. Still bound parameters only — no f-string SQL, so the Ruff `S608` / T-01-21 mitigation is intact.
- **Files modified:** `backend/tests/test_time.py`
- **Commit:** b1718ef

### Additions Beyond the Plan

Four helper-contract unit tests were added beyond the seven names VALIDATION.md requires: `test_utc_now_is_aware_utc`, `test_timezone_is_a_parameter_not_a_constant`, `test_local_day_bounds_is_half_open_utc`, and `test_validate_timezone`. They cover Task 1 `<behavior>` clauses (the half-open bounds contract, `validate_timezone`'s two cases, and tz-as-parameter) that the seven named tests do not reach. All seven required names are present and unchanged.

## Threat Model Compliance

| Threat ID | Disposition | Status |
|-----------|-------------|--------|
| T-01-19 | mitigate | `local_day`/`local_week_start` are the single sanctioned path; the verified boundary table is parametrized; Ruff `DTZ` is enabled and clean |
| T-01-20 | mitigate | `validate_timezone` raises `ValueError` at the boundary |
| T-01-21 | mitigate | All test SQL uses bound parameters; `ruff check` passes with `S` enabled |
| T-01-22 | accept | Timezone value is not sensitive; no redaction added |

## Verification

```
uv run pytest backend/tests/test_time.py -q   → 14 passed
uv run pytest backend/tests -q                → 44 passed (no state pollution)
uv run ruff check backend/app/core backend/tests/test_time.py → All checks passed
uv run mypy backend/app                       → Success: no issues found in 11 source files
grep -rn "utcnow" backend/ --include="*.py"   → no matches (exit 1)
```

All Task 1 and Task 2 acceptance criteria verified, including every `grep` assertion.

## TDD Gate Compliance

| Gate | Commit | Notes |
|------|--------|-------|
| RED | 809d844 | `test(01-04)` — failed with `ModuleNotFoundError: No module named 'app.core'` |
| GREEN | db3eef2 | `feat(01-04)` — 6 unit tests pass |
| REFACTOR | — | Not needed; no cleanup pass produced changes |

Task 2 is test-only by design (it adds the acceptance suite against an implementation that already exists), so its `test(01-04)` commit is the correct type.

## Known Stubs

None.

## Requirements Completed

- FOUND-03 — user's timezone is configurable and used for all daily/weekly calculations
- FOUND-04 — all timestamps stored in UTC, converted only at calculation boundaries

## For the Next Plan

Phase 4 analytics must import from `app.core.time` rather than calling `zoneinfo` directly, and must read `tz` from the `User` row it is already loading. Two rules that are easy to get wrong:

- In SQL, always write `AT TIME ZONE :tz` *before* `date_trunc` — the aggregate operates on local wall time, not the raw instant.
- For `WHERE`-clause filtering, use `local_day_bounds()` and compare the raw timestamp column against the two UTC constants. Wrapping the column in `AT TIME ZONE` inside a `WHERE` prevents index use and forces a sequential scan.

## Self-Check: PASSED

- `backend/app/core/__init__.py` — FOUND
- `backend/app/core/time.py` — FOUND
- `backend/tests/test_time.py` — FOUND
- Commit 809d844 — FOUND
- Commit db3eef2 — FOUND
- Commit b1718ef — FOUND
