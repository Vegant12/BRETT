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
