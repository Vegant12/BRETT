# Deferred Items -- Phase 12

Out-of-scope discoveries logged during execution, per the executor's scope-boundary rule
(only auto-fix issues directly caused by the current task's changes).

## Plan 12-01

### Pre-existing time-of-day-dependent flake: `test_body_measurement_trend_compares_latest_against_earliest`

**File:** `backend/tests/test_mcp_tools.py`
**Discovered during:** Task 3 full-suite verification (`uv run pytest`)

`_seed_reference_history`'s `REFERENCE_BODY_MEASUREMENT_DAYS = 30` window seeds a
`body_measurements` row at `offset=0` (i.e. `measured_on=anchor_day`, which equals "today"
whenever the wall-clock hour is `>= _REFERENCE_HOUR` (2 UTC)). `test_body_measurement_trend_
compares_latest_against_earliest` then separately seeds its own `measured_on=today` row,
colliding with the row `_seed_reference_history` already inserted and raising
`IntegrityError` on `uq_body_measurements_user_source_measured_on`.

**Confirmed pre-existing and unrelated to Phase 12**: reproduced with `git stash` applied on
top of Plan 12-01's Task 1+2 commits (before any Task 3 changes existed), at the same wall-clock
time. This is a latent bug in Phase 11's test fixture, not something this plan's changes touch
(`body_measurements` is untouched by this plan).

**Not fixed here** -- out of scope for Plan 12-01 (touches `test_mcp_tools.py`, not in this
plan's `files_modified`). Worth a follow-up fix: either move `_seed_reference_history`'s
measurement window to start at `offset=1` (yesterday) so it never lands on "today", or have the
failing test's own seed skip the day `_seed_reference_history` already claimed.

## Plan 12-02

Same pre-existing flake reproduced again during Task 3's full-suite verification (`uv run
pytest backend -q`, wall-clock ~11:02 UTC): `test_body_measurement_trend_compares_latest_
against_earliest` failed on the same `uq_body_measurements_user_source_measured_on` collision.
Confirmed unrelated to this plan's changes (`backend/app/db/repositories/programs.py` and
`backend/tests/test_db_program_history.py`, neither of which touches `body_measurements`). Not
fixed here for the same reason as above -- still out of scope.

## Plan 12-04

Third recurrence, during the full-suite verification after Task 3 (`uv run pytest backend -q`,
wall-clock ~11:18 UTC, i.e. `>= 2 UTC`): `test_body_measurement_trend_compares_latest_against_
earliest` failed on the same `uq_body_measurements_user_source_measured_on` collision. Confirmed
unrelated to this plan's changes (`backend/app/mcp/tools/programs.py`,
`backend/app/mcp/tools/program_switch.py`, `backend/app/mcp/tools/_common.py`,
`backend/app/mcp/tools/schemas.py`, and the three `backend/tests/test_mcp_*.py` files this plan
touches -- none reads or writes `body_measurements`). Not fixed here for the same reason as
above. Third occurrence across three consecutive plans now strengthens the case for the
follow-up fix recommended in Plan 12-01.
