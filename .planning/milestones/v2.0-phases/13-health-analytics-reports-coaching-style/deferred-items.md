# Deferred Items — Phase 13

Items discovered during plan execution that are out of scope for the plan touching them (per
the executor's scope-boundary rule: only auto-fix issues directly caused by the current task's
changes).

## From plan 13-02

- **Pre-existing failure, unrelated to this plan's changes:**
  `backend/tests/test_mcp_tools.py::test_body_measurement_trend_compares_latest_against_earliest`
  fails with `IntegrityError: duplicate key value violates unique constraint
  "uq_body_measurements_user_source_measured_on"` when run today (2026-09-04). Confirmed via
  `git stash` that this fails identically on the pre-13-02 `conftest.py` — plan 13-02's changes
  (the `health_metric` fixture builder and the widened `worst_case_history` Apple Health seeding)
  do not touch `body_measurements` seeding at all and are not the cause.

  Root cause (not investigated further, out of scope for this plan): the test calls
  `committed_history.body_measurement(measured_on=today - timedelta(days=60), ...)` and
  `committed_history.body_measurement(measured_on=today, ...)` where `today = utc_now().date()`.
  Some other seeded row in `_seed_reference_history` (called earlier in the same test) likely
  already writes a `source='hevy'` row for one of these exact calendar days, given today's real
  date — a date-dependent collision, not a fixture design bug introduced by this plan.

  Confirmed NOT a regression from plan 13-02: `uv run pytest backend/ -q --deselect
  backend/tests/test_mcp_tools.py::test_body_measurement_trend_compares_latest_against_earliest`
  passes 975/975 (11 skipped for unrelated `realfile`/other markers).

## From plan 13-03: `test_body_measurement_trend_compares_latest_against_earliest` fails on 2026-09-04

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

**Note:** Plans 13-02 and 13-03 independently discovered the same pre-existing bug during
full-suite verification. Both write-ups are kept above since they corroborate each other from
different angles (13-02 confirms the rest of the suite is unaffected; 13-03 has the deeper
root-cause trace). One fix will resolve both entries.

## RESOLVED (orchestrator, after Wave 1 merge)

Fixed during Wave 1's post-merge test gate: both test points now anchor on
`_seed_reference_history`'s own returned `anchor` (its exact reserved 30-day range,
`REFERENCE_BODY_MEASUREMENT_DAYS`), placed just past that range, instead of on independent
`utc_now().date()` arithmetic that could collide with it depending on the real wall-clock day.
This removes the date-dependence entirely — no more relying on which calendar day the suite
happens to run on. `uv run pytest -q` — 999 passed, 0 failed. See commit
`fix(13): remove date-dependent collision in body-measurement-trend test`.
