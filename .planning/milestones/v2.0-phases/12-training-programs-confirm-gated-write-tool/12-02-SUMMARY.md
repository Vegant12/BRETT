---
phase: 12-training-programs-confirm-gated-write-tool
plan: 02
subsystem: database
tags: [sqlalchemy, postgresql, training-programs, atomic-update, security]

# Dependency graph
requires:
  - phase: 12-01
    provides: "ProgramPeriod/ProgramSwitchToken ORM models, TrainingProgram StrEnum, and the
      GoldenBuilder.program_period/.switch_token fixture builders with committed_history's
      purge-and-reseed teardown"
provides:
  - "app.db.repositories.programs: get_active_period, get_periods_overlapping,
    get_recent_periods, issue_switch_token, consume_switch_token, close_period_and_open_new --
    the six functions every later Phase 12 plan (thresholds, the switch tool, the read tool)
    calls into"
  - "SWITCH_TOKEN_TTL (5 minutes) as the module's D-11 default"
  - "13 integration tests pinning period resolution, nonce single-use/target-binding/TTL/
    tenant-scoping, and the guarded close-then-open pair"
affects: [12-03, 12-04, 12-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Single atomic UPDATE...WHERE...RETURNING for a confirmation-token consume, with every
      predicate (nonce, target program, not-yet-consumed, not-expired, tenant) in the same WHERE
      clause rather than checked afterwards"
    - "expires_at computed by the database (now() + :ttl) and read back via RETURNING, never by
      the application clock, so the value compared inside consume's WHERE is the same clock"
    - "Guarded close-then-open: the close is itself the existence check (UPDATE...WHERE id=...
      AND ended_on IS NULL RETURNING id), and the insert only happens if that returned a row --
      close always precedes insert so the partial unique index never turns an ordinary race into
      an IntegrityError"

key-files:
  created:
    - backend/app/db/repositories/programs.py
  modified:
    - backend/tests/test_db_program_history.py

key-decisions:
  - "issue_switch_token/close_period_and_open_new use session.get() after a Core insert()
    (rather than .returning() on the insert) to read back the newly created ProgramPeriod as an
    ORM object, matching close_period_and_open_new's ProgramPeriod-returning contract, while
    issue_switch_token uses .returning(ProgramSwitchToken.expires_at) directly since only the
    scalar expiry value is needed"
  - "get_periods_overlapping and issue_switch_token/consume_switch_token/close_period_and_open_new
    keep 4-5 keyword-only parameters on multi-line signatures per the plan's own code samples;
    get_periods_overlapping's signature was deliberately kept on ONE params-line (not one
    per-parameter) so it stays under the 100-char line-length limit as a single line -- this
    also satisfies the plan's acceptance-criteria grep for the exact `*, user_id: uuid.UUID`
    substring, which per-line-broken signatures would not"

requirements-completed: [GOAL-01, GOAL-03]

# Metrics
duration: ~40min
completed: 2026-09-04
---

# Phase 12 Plan 02: Program Repository -- Reads, Atomic Writes & Proofs Summary

**Six functions in one module -- three reads answering "which program, when, did the window
straddle a switch" and three writes that mint, atomically spend, and apply a confirmation
nonce -- with the atomic `UPDATE ... WHERE ... RETURNING` consume and the guarded close-then-open
pair each pinned by container-backed tests proving single-use, target-binding, TTL expiry, and
tenant scoping.**

## Performance

- **Duration:** ~40 min
- **Started:** 2026-09-04 (worktree agent, Wave 2)
- **Completed:** 2026-09-04
- **Tasks:** 3/3 completed
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments

- `backend/app/db/repositories/programs.py` created with `get_active_period`,
  `get_periods_overlapping`, `get_recent_periods` (Task 1) and `issue_switch_token`,
  `consume_switch_token`, `close_period_and_open_new` (Task 2) -- none of the six commits; the
  caller owns the transaction throughout
- The nonce consume is a single `UPDATE ProgramSwitchToken SET consumed_at = now() WHERE
  user_id = ... AND nonce = ... AND to_program = ... AND consumed_at IS NULL AND expires_at >
  now() RETURNING from_period_id` -- all four security predicates plus the tenant predicate in
  one round trip, so there is no read-then-write window a concurrent confirmation could win
- `close_period_and_open_new` closes the authorized period first (`UPDATE ... WHERE id = ...
  AND ended_on IS NULL RETURNING id`) and only inserts the new open period if that returned a
  row -- the partial unique index is therefore never the mechanism that reports "someone else
  already switched"
- 13 new integration tests (Task 3) extend `backend/tests/test_db_program_history.py` to 20
  total: six period-resolution tests (including the open-period-extends-forever edge and
  tenant scoping), five token tests (happy path, replay, wrong-program, expiry, cross-tenant),
  and two apply tests (moves the open period; refuses when it is no longer open)

## Task Commits

Each task was committed atomically:

1. **Task 1: The three reads -- active period, overlapping periods, recent periods** -
   `e131799` (feat)
2. **Task 2: The three writes -- issue, atomically consume, and apply** - `1c6e0e9` (feat)
3. **Task 3: The repository's proofs -- resolution, atomicity, TTL, wrong-program and replay** -
   `e79cc69` (test)

_No separate plan-metadata commit in worktree mode -- this SUMMARY.md is committed as the final
commit per the worktree executor protocol._

## Files Created/Modified

- `backend/app/db/repositories/programs.py` - the six functions: `get_active_period`,
  `get_periods_overlapping`, `get_recent_periods`, `issue_switch_token`, `consume_switch_token`,
  `close_period_and_open_new`, plus `SWITCH_TOKEN_TTL` and `_NONCE_BYTES` module constants
- `backend/tests/test_db_program_history.py` - extended from 7 to 20 tests; new imports for
  `TrainingProgram` and the six repository functions, plus `ANALYTICS_SECOND_USER_ID` for the
  cross-tenant tests

## Decisions Made

- Followed the plan's design exactly for all three writes: database-computed `expires_at` via
  `now() + :ttl` read back with `RETURNING`, the atomic single-statement consume with every
  predicate in one `WHERE`, and close-strictly-before-insert in the apply step
- `issue_switch_token`/`close_period_and_open_new` read back the newly inserted row via
  `session.get()` after a Core `insert()` rather than chaining `.returning(ProgramPeriod)` on
  the insert itself -- both achieve the same "one round trip, no second SELECT-then-INSERT race"
  property; `session.get()` was chosen because it returns a fully-typed ORM object without a
  second explicit `select()` construction
- `get_periods_overlapping`'s four-parameter signature was kept on one line (session, user_id,
  window_start, window_end all together) rather than one parameter per line, since the plan's
  own acceptance criteria greps for the literal substring `*, user_id: uuid.UUID` and a
  per-parameter-per-line signature (as literally shown in the plan's code sample) would put `*,`
  and `user_id: uuid.UUID` on different lines, failing that grep

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Module docstring literally contained `session.commit()`, which the plan's own acceptance criteria greps to forbid**
- **Found during:** Task 1 verification (`grep -c "session.commit()"` returned 1, not 0)
- **Issue:** The module docstring, following the plan's prose almost verbatim, described the
  "commit is the caller's job" contract using the literal string `session.commit()` -- the same
  string the acceptance criteria bans as a literal *usage*, and a bare substring grep cannot
  distinguish prose from code
- **Fix:** Reworded the docstring sentence to say "the switch's commit" instead of quoting the
  method call literally, preserving the same meaning without the banned substring
- **Files modified:** `backend/app/db/repositories/programs.py`
- **Verification:** `grep -c "session.commit()" backend/app/db/repositories/programs.py` returns
  0; full docstring meaning unchanged
- **Committed in:** `e131799` (Task 1 commit)

**2. [Rule 1 - Bug] `get_periods_overlapping`'s multi-line signature (as shown in the plan's own code sample) did not match the acceptance criteria's `*, user_id: uuid.UUID` grep**
- **Found during:** Task 1 verification (`grep -cE "\*, user_id: uuid.UUID"` returned 2, not at
  least 3)
- **Issue:** The plan's interface code sample for `get_periods_overlapping` puts `*,` and
  `user_id: uuid.UUID,` on separate lines (one parameter per line, `ruff format`'s default for a
  signature with 4+ keyword-only parameters that don't fit on one line). A line-anchored grep for
  the substring `*, user_id: uuid.UUID` cannot match across a line break, so following the
  sample's exact multi-line layout left only 2 of the 3 Task 1 functions matching instead of the
  required 3
- **Fix:** Reformatted `get_periods_overlapping`'s signature onto a single params-line (92
  characters, under the project's 100-char `ruff` line-length limit), which both `ruff format`
  and the acceptance grep accept
- **Files modified:** `backend/app/db/repositories/programs.py`
- **Verification:** `grep -cE "\*, user_id: uuid.UUID" backend/app/db/repositories/programs.py`
  returns 3; `uv run ruff format --check` and `uv run ruff check` both pass
- **Committed in:** `e131799` (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (both bugs in matching the plan's own literal acceptance
criteria, not design changes)
**Impact on plan:** No scope creep -- both fixes are wording/formatting adjustments confined to
the one file the plan's own verification commands required to pass.

## Known Stubs

None.

## Threat Flags

None. All new surface (the six repository functions) was already covered by this plan's own
`<threat_model>` (T-12-02 through T-12-05, T-12-16, T-12-17, T-12-18), and every `mitigate`
disposition in that register has a corresponding test in Task 3.

## Issues Encountered

**Pre-existing, unrelated test flake reproduced during full-suite verification (`uv run pytest
backend -q`):** `test_mcp_tools.py::test_body_measurement_trend_compares_latest_against_earliest`
failed with the same `uq_body_measurements_user_source_measured_on` `IntegrityError` first
documented in Plan 12-01's SUMMARY.md (a wall-clock-hour-dependent collision in an unrelated
`body_measurements` test fixture, reproduced again at ~11:02 UTC). Confirmed unrelated to this
plan's changes -- neither `backend/app/db/repositories/programs.py` nor
`backend/tests/test_db_program_history.py` touches `body_measurements`. Logged the recurrence to
`.planning/phases/12-training-programs-confirm-gated-write-tool/deferred-items.md` rather than
fixed, per the scope-boundary rule.

## Next Phase Readiness

- All six repository functions (`get_active_period`, `get_periods_overlapping`,
  `get_recent_periods`, `issue_switch_token`, `consume_switch_token`,
  `close_period_and_open_new`) are ready for Plan 03 (per-program recomposition thresholds, which
  needs `get_periods_overlapping` for the straddle caveat) and Plan 04 (the confirm-gated MCP
  write tool, which calls `issue_switch_token`/`consume_switch_token`/`close_period_and_open_new`
  directly and must never import `insert`/`update`/`delete` itself)
- `SWITCH_TOKEN_TTL` (5 minutes) is exported for Plan 04's warning-call response
- Recommend the same follow-up already logged in Plan 12-01: fix the `_seed_reference_history`
  time-of-day flake in `test_mcp_tools.py` (outside this plan's scope both times it recurred)

---
*Phase: 12-training-programs-confirm-gated-write-tool*
*Plan: 02*
*Completed: 2026-09-04*

## Self-Check: PASSED

All created/modified files confirmed present on disk (`backend/app/db/repositories/programs.py`,
`backend/tests/test_db_program_history.py`, this SUMMARY.md); all three task commits (`e131799`,
`1c6e0e9`, `e79cc69`) confirmed present in git log.
