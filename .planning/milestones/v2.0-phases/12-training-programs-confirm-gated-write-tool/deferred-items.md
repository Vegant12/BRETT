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

## Plan 12-03

Same pre-existing flake reproduced a third time during the full-suite verification (`uv run
pytest -q`, wall-clock ~11:24 UTC): `test_body_measurement_trend_compares_latest_against_
earliest` failed on the same `uq_body_measurements_user_source_measured_on` collision (950
passed, 1 failed, 11 skipped). Confirmed unrelated to this plan's changes
(`backend/app/analytics/recomposition.py`, `backend/app/analytics/schemas.py`, and
`backend/tests/test_analytics_recomposition.py`, none of which touch `body_measurements` or
`test_mcp_tools.py`). Not fixed here for the same reason as above -- still out of scope. This
is the third occurrence across three consecutive plans; the recommended fix (move
`_seed_reference_history`'s window to start at `offset=1`, or have the failing test's seed skip
the day already claimed) is worth prioritizing soon.

## Plan 12-04

Fourth recurrence (parallel Wave 3, independently discovered), during the full-suite
verification after Task 3 (`uv run pytest backend -q`, wall-clock ~11:18 UTC, i.e. `>= 2 UTC`):
`test_body_measurement_trend_compares_latest_against_earliest` failed on the same
`uq_body_measurements_user_source_measured_on` collision. Confirmed unrelated to this plan's
changes (`backend/app/mcp/tools/programs.py`, `backend/app/mcp/tools/program_switch.py`,
`backend/app/mcp/tools/_common.py`, `backend/app/mcp/tools/schemas.py`, and the three
`backend/tests/test_mcp_*.py` files this plan touches -- none reads or writes
`body_measurements`). Not fixed here for the same reason as above. Fourth occurrence across all
four Wave 1-3 plans now strongly reinforces the case for the follow-up fix recommended in Plan
12-01.

## Plan 12-05

Fifth recurrence, during `uv run pytest -m integration` verification (wall-clock ~11:42 UTC,
i.e. `>= 2 UTC`, same trigger condition as every prior occurrence):
`test_body_measurement_trend_compares_latest_against_earliest` failed on the same
`uq_body_measurements_user_source_measured_on` collision
(`(user_id, source, measured_on)=(..., hevy, 2026-09-04)` already exists). Confirmed unrelated
to this plan's changes: reproduced in isolation
(`uv run pytest -m integration backend/tests/test_mcp_tools.py::test_body_measurement_trend_compares_latest_against_earliest`)
and none of this plan's touched files (`backend/app/mcp/server.py`,
`backend/tests/test_mcp_tool_schemas.py`, `backend/tests/test_mcp_tool_budget.py`,
`backend/tests/test_mcp_auth.py`, `backend/tests/test_mcp_mount.py`, `docs/coaching-instructions.md`,
and the new `test_program_status_is_reported_with_its_start_date_and_what_it_replaced` test which
this plan added to `test_mcp_tools.py`) read or write `body_measurements`. Not fixed here for the
same reason as above -- still out of scope. Fifth occurrence across all five Wave 1-4 plans; the
follow-up fix recommended in Plan 12-01 should be prioritized now that it has recurred in every
single plan this phase.

### Also noted: pre-existing `ruff format` drift in 16 files outside this plan's scope

`uv run ruff format --check backend/tests backend/app docs` (run broadly during Task 3
verification, not the plan's own scoped verify command) reports 16 files that would be
reformatted -- none of them touched by this plan. Confirmed the six files this plan actually
modified (`backend/app/mcp/server.py`, `backend/tests/test_mcp_tool_budget.py`,
`backend/tests/test_mcp_tools.py`, `backend/tests/test_mcp_tool_schemas.py`,
`backend/tests/test_mcp_auth.py`, `backend/tests/test_mcp_mount.py`) are all correctly
formatted in isolation. Not fixed here -- out of scope (pre-existing drift in unrelated files).
