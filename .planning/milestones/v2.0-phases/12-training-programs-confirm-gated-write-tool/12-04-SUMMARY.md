---
phase: 12-training-programs-confirm-gated-write-tool
plan: 04
subsystem: mcp
tags: [mcp, confirmation-token, write-guard, training-programs, pydantic, security]

# Dependency graph
requires:
  - phase: 12-01
    provides: "ProgramPeriod/ProgramSwitchToken ORM models and the TrainingProgram StrEnum"
  - phase: 12-02
    provides: "app.db.repositories.programs -- get_active_period, get_recent_periods,
      issue_switch_token, consume_switch_token, close_period_and_open_new, SWITCH_TOKEN_TTL"
provides:
  - "writable_session in _common.py -- read_only_session's sibling, the ONE session in
    app/mcp/ PostgreSQL will let write, used by exactly one module"
  - "ProgramSwitchStatus/ProgramSwitchResponse/TrainingProgramResponse wire models in
    schemas.py, composing TrainingProgram"
  - "fitness_get_training_program (programs.py) -- the read tool"
  - "fitness_switch_training_program (program_switch.py) -- the only write tool in the
    system, a two-call server-issued-token confirmation"
  - "test_mcp_isolation._WRITE_ALLOWLIST (exactly one entry, self-asserted) and
    test_only_one_module_opens_a_writable_session"
  - "backend/tests/test_mcp_program_switch.py: 11 integration tests proving the two-call
    gate, all four refusal paths, atomicity, and the unknown-vs-not_applied contract"
affects: [12-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Confirmation gate as a server-minted, stored, single-use, target-bound opaque token
      (never a `confirm: bool`) -- the model cannot manufacture the credential"
    - "writable_session: no postgresql_readonly execution option, no unconditional rollback
      in finally, caller commits explicitly as the LAST statement on every branch that writes"
    - "Three-state write outcome (applied/not_applied/unknown) where the exception path is
      structurally forced to UNKNOWN via safe_tool's degraded factory, never NOT_APPLIED"
    - "All ORM attribute reads on rows returned from read_only_session/writable_session must
      happen INSIDE the `async with` block -- rollback-on-exit expires the instances"

key-files:
  created:
    - backend/app/mcp/tools/programs.py
    - backend/app/mcp/tools/program_switch.py
    - backend/tests/test_mcp_program_switch.py
  modified:
    - backend/app/mcp/tools/_common.py
    - backend/app/mcp/tools/schemas.py
    - backend/tests/test_mcp_schemas.py
    - backend/tests/test_mcp_isolation.py
    - .planning/phases/12-training-programs-confirm-gated-write-tool/deferred-items.md

key-decisions:
  - "Neither tool is registered in server.py -- registration, ToolAnnotations, the budget
    guard and the coaching-doc entry are deliberately Plan 05's job, so those guards trip in
    the same commit that satisfies them rather than silently passing early"
  - "The read tool (programs.py) and the write tool (program_switch.py) are separate modules
    so the write allowlist can name exactly one module without also exempting a read tool
    from the write guard"
  - "All four token-refusal causes (missing, wrong-program, expired, already-consumed) share
    one reason string -- distinguishing them would be an oracle telling a caller which guess
    was closest"
  - "A no-op switch (requesting the already-active program) issues no token and writes
    nothing, rather than minting a credential for a call that changes nothing"

requirements-completed: [GOAL-03, GOAL-04]

# Metrics
duration: ~50min
completed: 2026-09-04
---

# Phase 12 Plan 04: Confirm-Gated Write Tool Summary

**BRETT's only MCP write path -- a two-call, server-issued-token confirmation that a model
cannot short-circuit -- plus the write guard narrowed (never relaxed) to exactly one named
module, with both facts self-asserted by the test suite.**

## Performance

- **Duration:** ~50 min
- **Started:** 2026-09-04 (worktree agent, Wave 3)
- **Completed:** 2026-09-04T04:19:38Z
- **Tasks:** 3/3 completed
- **Files modified:** 8 (3 created, 5 modified)

## Accomplishments

- `writable_session` added to `_common.py` directly below `read_only_session`, which stays
  byte-identical (verified by diff) -- three deliberate differences (no read-only execution
  option, no unconditional rollback, caller-owned commit as the last statement) all recorded
  in its docstring
- `ProgramSwitchStatus` (applied/not_applied/unknown), `ProgramSwitchResponse` and
  `TrainingProgramResponse` added to `schemas.py`, composing `TrainingProgram` from Plan 01;
  `test_mcp_schemas.py`'s `_DEGRADED_OVERRIDES` extended for the bare-enum `switch_status`
  field, which the generic degraded-kwargs builder cannot handle on its own
- `fitness_get_training_program` (`programs.py`): a read-only tool answering "what program am
  I on and what did it replace", built entirely inside its `read_only_session` block
- `fitness_switch_training_program` (`program_switch.py`): the only write tool in the system.
  A call with no token issues a single-use, 5-minute, target-bound nonce and writes nothing;
  a second call echoing that exact token atomically closes the old period and opens the new
  one, with `session.commit()` as the tool's last statement on both writing branches
- `test_mcp_isolation._WRITE_ALLOWLIST = frozenset({"program_switch.py"})`, asserted to hold
  exactly one entry in two places (inline in `test_mcp_never_writes` and in its own
  `test_the_write_allowlist_holds_exactly_one_module`), plus
  `test_only_one_module_opens_a_writable_session` covering the runtime half (who may even
  open a session that can write, not just who commits); the tool-coroutine floor raised
  13 -> 15
- 11 new integration tests in `test_mcp_program_switch.py`: the warn branch writes nothing,
  the token is not derivable from the arguments, the confirm branch is atomic, replayed /
  wrong-program / expired / fabricated tokens are all refused with the identical reason text,
  a no-op switch mints no token, the exception path degrades to `unknown` (never
  `not_applied`) and leaks none of `test_mcp_tools.LEAK_MARKERS`, and the read tool reports
  the post-switch program and what it replaced

## Task Commits

Each task was committed atomically:

1. **Task 1: writable_session and the two wire models** - `342900a` (feat)
2. **Task 2: The read tool and the confirm-gated write tool** - `bbafd8c` (feat)
3. **Task 3: Narrow the write guard, and prove the whole gate** - `d55c361` (test)

_No separate plan-metadata commit in worktree mode -- this SUMMARY.md is committed as the
final commit per the worktree executor protocol._

## Files Created/Modified

- `backend/app/mcp/tools/_common.py` - `writable_session` added below `read_only_session`
  (unmodified); docstring gained a sixth rule bullet
- `backend/app/mcp/tools/schemas.py` - `ProgramSwitchStatus`, `ProgramSwitchResponse`,
  `TrainingProgramResponse`; `TrainingProgram` added to the analytics-schemas import block
- `backend/app/mcp/tools/programs.py` (new) - `fitness_get_training_program`
- `backend/app/mcp/tools/program_switch.py` (new) - `fitness_switch_training_program`
- `backend/tests/test_mcp_schemas.py` - `_DEGRADED_OVERRIDES` extended with
  `ProgramSwitchStatus.UNKNOWN` for `switch_status`
- `backend/tests/test_mcp_isolation.py` - `_WRITE_ALLOWLIST`, the narrowed
  `test_mcp_never_writes`, `test_the_write_allowlist_holds_exactly_one_module`,
  `test_only_one_module_opens_a_writable_session`, tool-coroutine floor 13 -> 15
- `backend/tests/test_mcp_program_switch.py` (new) - 11 integration tests
- `.planning/phases/12-training-programs-confirm-gated-write-tool/deferred-items.md` - logged
  the third recurrence of the pre-existing `body_measurements` time-of-day flake

## Decisions Made

- Followed the plan's design for the token gate exactly: no `confirm: bool` anywhere in the
  tool's schema, a server-minted opaque nonce as the only accepted confirmation, and the
  commit as the tool's last statement on every writing branch so an exception past a
  successful commit degrades to `unknown` rather than inviting a double-apply retry
- Kept the read tool and the write tool in separate modules per the plan's explicit
  reasoning: a single combined module would exempt the read tool from the write guard for no
  reason and complicate the allowlist's "exactly one entry" invariant

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] The plan's own docstring/action text wrote several literal substrings its own acceptance-criteria greps ban**
- **Found during:** Task 1 and Task 2 verification
- **Issue:** Three separate instances of the same category of self-conflict already
  documented in Plan 12-02's SUMMARY: the plan's action text instructs writing a docstring
  sentence containing the exact substring a later acceptance-criteria grep bans as a literal
  usage.
  - `_common.py`'s `writable_session` docstring said "no `postgresql_readonly` execution
    option", making `grep -c postgresql_readonly` return 2 instead of the required 1
  - `schemas.py`'s `ProgramSwitchResponse` docstring said "never `confirm: bool`", making
    `grep -c "confirm: bool"` return 1 instead of the required 0
  - `program_switch.py`'s module docstring said "PITFALLS #13's whole point is that
    `confirm: bool` is..." and "must NOT import `read_only_session`", making both the
    `confirm: bool` and `read_only_session` greps return 1 instead of 0
- **Fix:** Reworded each sentence to preserve its exact meaning without the banned literal
  substring (e.g. "no read-only execution option set on the connection", "never a plain
  boolean confirmation flag", "must NOT import the read-only session helper from `_common`")
- **Files modified:** `backend/app/mcp/tools/_common.py`, `backend/app/mcp/tools/schemas.py`,
  `backend/app/mcp/tools/program_switch.py`
- **Verification:** all four greps now return their required counts; full docstring meaning
  unchanged
- **Committed in:** `342900a`, `bbafd8c`

**2. [Rule 1 - Bug] `programs.py` read ORM attributes on `ProgramPeriod` rows after `read_only_session`'s rollback-on-exit had already expired them**
- **Found during:** Task 3's integration test run
  (`test_the_read_tool_reports_the_program_and_what_it_replaced` failed with
  `sqlalchemy.orm.exc.DetachedInstanceError`)
- **Issue:** The plan's own code sample for `fitness_get_training_program` builds the
  `TrainingProgramResponse` OUTSIDE the `async with read_only_session(ctx) as session:`
  block (same indentation level, after the block exits). `read_only_session`'s unconditional
  `rollback()` in its `finally` expires every ORM instance the session loaded, so accessing
  `current.program`/`previous.started_on` etc. after the block closes triggers a lazy reload
  attempt against an already-detached session -- caught by `safe_tool` and silently degraded
  to `data_available=False`, which is exactly the kind of masked failure the whole
  `data_available` contract exists to prevent, verified only because a real integration test
  asserted on the real payload rather than merely `is_error is False`
- **Fix:** Moved the `current`/`previous` extraction and the `TrainingProgramResponse`
  construction inside the `async with` block, with the response returned via a local variable
  after the block closes (avoiding a `return` inside `async with` for symmetry with the
  writable-session pattern elsewhere in this plan)
- **Files modified:** `backend/app/mcp/tools/programs.py`
- **Verification:** `test_the_read_tool_reports_the_program_and_what_it_replaced` and all 11
  tests in `test_mcp_program_switch.py` pass; full fast + integration suite green
- **Committed in:** `d55c361`

---

**Total deviations:** 2 auto-fixed (both bugs; the first is wording/formatting confined to
docstrings matching the plan's own literal acceptance criteria, the second is a genuine
runtime bug caught by the plan's own integration tests)
**Impact on plan:** No scope creep -- both fixes are confined to the files this plan's own
verification requires to pass, and the second fix is exactly the kind of defect an
integration-level test (rather than a schema-shape test) exists to catch.

## Known Stubs

None.

## Threat Flags

None. Every trust boundary this plan touches (model -> tool arguments, tool -> database,
exception -> tool result) and every new write/read surface (`fitness_switch_training_program`,
`fitness_get_training_program`) is already named in this plan's own `<threat_model>`
(T-12-01 through T-12-06, T-12-09, T-12-24 through T-12-26), and every `mitigate` disposition
has a corresponding test in Task 3.

## Issues Encountered

**Environment-specific verification-script quirk, not a code defect:** the plan's Task 2
acceptance criteria includes a literal `awk` invocation using `\s` as a whitespace class
(`awk '/await session.commit\(\)/{getline; if ($0 !~ /^\s*(return|$|#)/) exit 1}'`). macOS's
BSD `awk` does not support `\s` as a whitespace escape (it matches a literal backslash-s,
which never appears at the start of an indented line), so the literal command always exits 1
regardless of the code under test. Re-running the identical check with a POSIX-portable
`[ \t]` character class instead of `\s` exits 0, confirming the actual property holds:
nothing but `return` follows either `session.commit()` call in `program_switch.py`. Not fixed
(the acceptance-criteria text itself, not a project file) -- noted here so a future BSD-awk
environment does not mistake this for a regression.

**Third recurrence of the pre-existing `body_measurements` time-of-day flake:** logged to
`deferred-items.md`, same root cause as Plans 12-01 and 12-02 (unrelated to this plan's
files). See that file for the full history.

## Next Phase Readiness

- `fitness_get_training_program` and `fitness_switch_training_program` are fully implemented,
  tested, and ready for Plan 05 to register in `server.py` alongside `ToolAnnotations`, the
  budget guard, and the coaching-doc entry
- `_WRITE_ALLOWLIST` and the tool-coroutine floor (15) are the two structural facts Plan 05's
  registration must land inside without breaking
- Recommend the same follow-up flagged in Plans 12-01/12-02: fix the
  `_seed_reference_history` time-of-day flake in `test_mcp_tools.py`, now reproduced a third
  time

---
*Phase: 12-training-programs-confirm-gated-write-tool*
*Plan: 04*
*Completed: 2026-09-04*

## Self-Check: PASSED

All created/modified files confirmed present on disk (`backend/app/mcp/tools/_common.py`,
`backend/app/mcp/tools/schemas.py`, `backend/app/mcp/tools/programs.py`,
`backend/app/mcp/tools/program_switch.py`, `backend/tests/test_mcp_isolation.py`,
`backend/tests/test_mcp_schemas.py`, `backend/tests/test_mcp_program_switch.py`,
`deferred-items.md`, this SUMMARY.md); all three task commits (`342900a`, `bbafd8c`,
`d55c361`) confirmed present in `git log`.
