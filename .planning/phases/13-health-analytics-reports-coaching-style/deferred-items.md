# Deferred Items — Phase 13

Items discovered during plan execution that are out of scope for the current plan (pre-existing,
unrelated to the files the plan touches) and therefore not fixed here.

## 13-03: `test_body_measurement_trend_compares_latest_against_earliest` fails on 2026-09-04

**Discovered during:** Plan 13-03, full-suite verification (`uv run pytest -q`).

**File:** `backend/tests/test_mcp_tools.py::test_body_measurement_trend_compares_latest_against_earliest`

**Symptom:** Fails both in the full suite and in isolation with:
```
sqlalchemy.exc.IntegrityError: duplicate key value violates unique constraint
"uq_body_measurements_user_source_measured_on"
DETAIL: Key (user_id, source, measured_on)=(00000000-0000-0000-0000-000000000001, hevy,
2026-09-04) already exists.
```

**Root cause (not fixed, not verified further):** The test computes `today = utc_now().date()`
and writes a `body_measurements` row dated `today`, on top of a COMMITTED reference-history
fixture (`committed_history`) that appears to already hold a row for the literal calendar date
`2026-09-04`. This is a real-wall-clock time bomb: the test passes on every day except the one
hardcoded into the committed fixture, which is today's actual date in this environment. It is
unrelated to any file plan 13-03 modifies (`app/core/time.py`, `app/analytics/metadata.py`,
`app/analytics/schemas.py`, `app/analytics/records.py`) and was not introduced by this plan's
changes — confirmed by running the test in isolation with a clean stash of this plan's diff
(same failure, same date collision).

**Disposition:** Out of scope per the scope-boundary rule (pre-existing failure, unrelated
files). Not fixed here. Flagging for the phase orchestrator / a future plan to investigate the
`committed_history` fixture's seeded dates and either freeze time in this test or move its fixed
reference date away from a live calendar boundary.
