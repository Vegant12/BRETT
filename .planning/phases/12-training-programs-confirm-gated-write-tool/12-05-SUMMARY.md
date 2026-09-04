---
phase: 12-training-programs-confirm-gated-write-tool
plan: 05
subsystem: mcp
tags: [mcp, tool-registration, write-guard, annotations, coaching-doc, budgets]

# Dependency graph
requires:
  - phase: 12-03
    provides: "Program-aware recomposition thresholds (RecompositionResult's five new
      program fields), unaffected by this plan but confirmed still green"
  - phase: 12-04
    provides: "fitness_get_training_program (programs.py) and
      fitness_switch_training_program (program_switch.py), fully implemented and tested
      but NOT YET registered on the server -- this plan's whole job"
provides:
  - "Sixteen registered MCP tools: fifteen through the shared READ_ONLY loop plus
    fitness_switch_training_program registered outside it with its own explicit
    WRITE_TOOL ToolAnnotations (readOnlyHint=False, destructiveHint=True,
    idempotentHint=False, openWorldHint=False)"
  - "test_annotations_are_an_exact_partition -- the annotation guard rewritten from
    'every tool is read-only' to a partition asserting exactly fifteen read-only names
    and exactly one write name (WRITE_TOOLS, asserted len==1)"
  - "Both new tools carry measured MCP-03 byte budgets (2_048 each), appear in the
    degradation leak scan (dead database) and the secret-redaction scan (healthy
    database) with a write-free minimal call, and are proven end to end over the real
    MCP transport"
  - "docs/coaching-instructions.md names both tools and the two-call write protocol,
    still within the 9,000-character paste ceiling (7,934 chars)"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "A write tool is registered by a SEPARATE mcp.add_tool call placed AFTER the
      shared _TOOLS loop, carrying its own explicitly-constructed ToolAnnotations
      object (all four flags set, none omitted) -- never added to the loop, which
      would silently hand it READ_ONLY"
    - "The annotation guard is written as an exact PARTITION (WRITE_TOOLS asserted to
      hold exactly one entry, read-only-hint-true set == EXPECTED_TOOLS - WRITE_TOOLS,
      read-only-hint-false set == WRITE_TOOLS) rather than 'every tool except the known
      exception' -- a second write tool fails the length assertion instead of silently
      passing by being skipped"
    - "A budget for a fixed-shape, no-list response (both new tools) is measured once,
      given ~30% headroom, and rounded up to the smallest already-used budget figure
      (2_048) rather than a bespoke number"
    - "A write tool's MINIMAL_TOOL_ARGUMENTS/WORST_CASE_ARGS entry requests the SEEDED
      already-active program, so the minimal/worst-case call is a no-op refusal that
      writes nothing and mints no token -- safe to run against both a dead database
      (degradation scan) and a healthy shared container (secret-redaction scan, budget
      measurement)"

key-files:
  created: []
  modified:
    - backend/app/mcp/server.py
    - backend/tests/test_mcp_tool_schemas.py
    - backend/tests/test_mcp_tool_budget.py
    - backend/tests/test_mcp_tools.py
    - backend/tests/test_mcp_auth.py
    - backend/tests/test_mcp_mount.py
    - docs/coaching-instructions.md
    - .planning/phases/12-training-programs-confirm-gated-write-tool/deferred-items.md

key-decisions:
  - "test_every_tool_is_annotated_read_only was REPLACED (not kept alongside a new
    test) by test_annotations_are_an_exact_partition, per the plan's explicit
    PITFALLS #14 instruction: a skipped exception stops proving anything about the
    other fifteen the moment a second exception is added, so the guard must be
    narrowed into a partition rather than relaxed with an exclusion list"
  - "The write tool's published annotations were asserted as a SUBSET (the four
    hint keys only), not full dict equality, because the SDK also publishes a
    `title: None` key that full equality would have to account for on every call
    site -- narrowing to the four flags that are this plan's actual claim keeps the
    assertion about what T-12-07 cares about"
  - "Both budget-table comments were written as two SEPARATE single-line comments
    (shape claim, then the measured figure) rather than one wrapped multi-line
    comment, so the acceptance-criteria grep for a 'Measured'-bearing line
    immediately preceding the dict entry is satisfied without exceeding the
    100-character line length"

requirements-completed: [GOAL-01, GOAL-04]

# Metrics
duration: ~55min
completed: 2026-09-04
---

# Phase 12 Plan 05: Register the Confirm-Gated Write Tool Summary

**`server.py` now registers all sixteen MCP tools -- fifteen read-only through the shared
loop, and `fitness_switch_training_program` outside it with its own explicit write
annotations -- and every structural guard that goes red the moment a write tool exists
(the exact registry set, the read-only/write partition, the byte budgets, the two leak
scans, and the coaching document) is updated to match, with the partition rewritten as an
assertion that a SECOND write tool cannot pass by being skipped.**

## Performance

- **Duration:** ~55 min
- **Started:** 2026-09-04 (worktree agent, Wave 4)
- **Tasks:** 3/3 completed
- **Files modified:** 8 (0 created, 8 modified)

## Accomplishments

- `server.py`: `fitness_get_training_program` registered inside the shared `_TOOLS`/
  `READ_ONLY` loop, beside `fitness_get_recomposition_status`; `fitness_switch_training_program`
  registered AFTER the loop with a new `WRITE_TOOL` annotations object (`readOnlyHint=False`,
  `destructiveHint=True`, `idempotentHint=False`, `openWorldHint=False`), all four flags
  explicit; `_INSTRUCTIONS` gained one sentence naming the write tool's two-call protocol;
  `required_scopes=None` and its D-12 comment left untouched, as required
- `test_mcp_tool_schemas.py`: `EXPECTED_TOOLS` grows to sixteen names;
  `test_tool_registry_is_exactly_the_fourteen` renamed to `...the_sixteen`;
  `test_every_tool_is_annotated_read_only` replaced by `test_annotations_are_an_exact_partition`
  (`WRITE_TOOLS = frozenset({"fitness_switch_training_program"})`, `assert len(WRITE_TOOLS) == 1`,
  and the read-only-true/read-only-false sets asserted equal to `EXPECTED_TOOLS - WRITE_TOOLS`/
  `WRITE_TOOLS`) plus a sibling `test_the_write_tool_publishes_explicit_write_annotations`
  pinning the write tool's four published flags exactly
- Stale `is_exactly_the_fourteen` cross-references updated in `test_mcp_auth.py` and
  `test_mcp_mount.py` (confirmed zero remaining occurrences repo-wide)
- `test_mcp_tool_budget.py`: both tools added to `WORST_CASE_ARGS` (the write tool's worst
  case requests the seeded `lean_bulk` program, which is already active, so it is a
  writes-nothing no-op) and to `BUDGETS` with MEASURED figures (554 bytes and 880 bytes
  respectively, both budgeted at 2,048 with headroom, both fixed-shape and non-growing)
- `test_mcp_tools.py`: both tools added to `MINIMAL_TOOL_ARGUMENTS` for the same reason;
  new integration test `test_program_status_is_reported_with_its_start_date_and_what_it_replaced`
  closes the seeded `lean_bulk` period, opens a `cut` period, commits, and proves
  `fitness_get_training_program` reports the new program, its start date, the previous
  program, and the previous period's end date -- all over the real MCP transport
- `docs/coaching-instructions.md` gained two tool-table rows and one example-question
  line describing the two-call write protocol; still 7,934 characters, well under the
  9,000-character paste ceiling

## Task Commits

Each task was committed atomically:

1. **Task 1: Register both tools -- the read one inside the loop, the write one outside it**
   - `6dd2d4e` (feat)
2. **Task 2: The registry set and the read-only/write partition** - `f315027` (test)
3. **Task 3: Budgets, degradation coverage, the behavioural proofs, and the coaching document**
   - `b1c7bfb` (test)

_No separate plan-metadata commit in worktree mode -- this SUMMARY.md is committed as the
final commit per the worktree executor protocol._

## Files Created/Modified

- `backend/app/mcp/server.py` - imports for both new tools; `fitness_get_training_program`
  added to `_TOOLS`; `WRITE_TOOL` annotations object and `fitness_switch_training_program`'s
  `add_tool` call added after the loop; `_INSTRUCTIONS` extended by one sentence
- `backend/tests/test_mcp_tool_schemas.py` - `EXPECTED_TOOLS` (16 names), the renamed exact-
  registry test, `WRITE_TOOLS`/`test_annotations_are_an_exact_partition` replacing the old
  read-only-only test, and `test_the_write_tool_publishes_explicit_write_annotations`
- `backend/tests/test_mcp_tool_budget.py` - `WORST_CASE_ARGS`/`BUDGETS` entries for both
  new tools with measured, commented byte figures
- `backend/tests/test_mcp_tools.py` - `MINIMAL_TOOL_ARGUMENTS` entries for both new tools;
  the new `test_program_status_is_reported_with_its_start_date_and_what_it_replaced`
  integration test; "fourteen"/"thirteen" prose updated to "sixteen"/"fifteen" throughout
- `backend/tests/test_mcp_auth.py`, `backend/tests/test_mcp_mount.py` - stale
  `is_exactly_the_fourteen` cross-references renamed, "fourteen"/"thirteen registered"
  prose updated
- `docs/coaching-instructions.md` - two tool-table rows and one example-question line for
  the two new tools
- `.planning/phases/12-training-programs-confirm-gated-write-tool/deferred-items.md` -
  logged the fifth recurrence of the pre-existing `body_measurements` time-of-day flake,
  and pre-existing `ruff format` drift in 16 files outside this plan's scope

## Decisions Made

- Followed the plan's design exactly for the registration split (read tool inside the
  loop, write tool outside it with explicit annotations) and for rewriting the annotation
  guard as an exact partition rather than an exclusion list
- Two budget-table comments split into two single-line comments each (shape claim, then
  measured figure) so the "Measured"-bearing line sits immediately above the dict entry,
  satisfying both the acceptance-criteria grep and the 100-character line-length limit
- The write tool's published-annotations assertion in
  `test_the_write_tool_publishes_explicit_write_annotations` checks only the four hint
  keys (`readOnlyHint`/`destructiveHint`/`idempotentHint`/`openWorldHint`), not full dict
  equality, because the SDK also publishes an unrelated `title: None` key on every tool

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking issue] Pre-existing `ruff format` drift on an unrelated line inside `server.py`**
- **Found during:** Task 1 verification (`uv run ruff format --check backend/app/mcp`)
- **Issue:** `server.py`'s pre-existing `fitness_get_muscle_group_volume` tuple entry (two
  lines, joined by string concatenation) was already one `ruff format` pass away from being
  reformatted onto a single 89-character line, on the `main` branch before this plan
  started -- confirmed via `git stash` against the unmodified file. This blocked the plan's
  own `ruff format --check` verification step, which covers the whole `backend/app/mcp`
  directory including this pre-existing line.
- **Fix:** Ran `uv run ruff format backend/app/mcp/server.py`, which joined the one
  pre-existing two-line string onto one line and left every other line -- including all of
  this plan's new code -- untouched (confirmed via `git diff`)
- **Files modified:** `backend/app/mcp/server.py`
- **Verification:** `uv run ruff format --check backend/app/mcp` passes; diff confirmed to
  touch only the one pre-existing line plus this plan's own additions
- **Committed in:** `6dd2d4e`

**2. [Rule 1 - Bug] `test_the_write_tool_publishes_explicit_write_annotations`'s full-dict-equality assertion failed on an unrelated `title` key**
- **Found during:** Task 2's own test run
- **Issue:** The SDK's published `annotations` dict includes a `title: None` key on every
  tool alongside the four hint flags; asserting full dict equality against only the four
  flags therefore always fails, regardless of the four flags' correctness
- **Fix:** Narrowed the assertion to the four hint keys via a `_WRITE_ANNOTATION_KEYS`
  tuple, keeping the assertion focused on T-12-07's actual claim
- **Files modified:** `backend/tests/test_mcp_tool_schemas.py`
- **Verification:** `uv run pytest backend/tests/test_mcp_tool_schemas.py -q` passes (12/12)
- **Committed in:** `f315027`

---

**Total deviations:** 2 auto-fixed (one blocking pre-existing formatting issue in a file
this plan touches, one test-correctness bug caught while getting the plan's own new test
green)
**Impact on plan:** No scope creep. Both fixes are confined to files this plan's own
verification requires to pass, and neither changes the annotation values, the budget
figures, or any registered tool's behavior.

## Known Stubs

None.

## Threat Flags

None. Every trust boundary this plan touches (server registry -> Claude's tool schema,
tool response -> Claude's context window, repository -> the operator's Claude Project) is
already named in this plan's own `<threat_model>` (T-12-07, T-12-08, T-12-27 through
T-12-30), and every `mitigate` disposition has a corresponding test added or verified in
this plan's three tasks.

## Issues Encountered

**Acceptance-criteria grep undercounts an occurrence its own action text required
(pre-existing pattern in this phase, not a new one):** Task 1's acceptance criteria expects
`grep -c "fitness_switch_training_program" backend/app/mcp/server.py` to return 3 (import,
`add_tool` call, `name=` literal), but the same task's action text also instructs adding a
sentence to `_INSTRUCTIONS` naming `fitness_switch_training_program` -- which makes the
actual, correct count 4. Verified this is the intended, correct property (import once,
write registration once outside the loop, `_INSTRUCTIONS` updated once) rather than a bug;
the same self-conflict pattern is documented in Plans 12-02 and 12-04's SUMMARY.md. Not
"fixed" since there is nothing wrong in the source -- the plan's own literal count is
simply one short of what its own action text produces.

**Fifth recurrence of the pre-existing `body_measurements` time-of-day flake:** reproduced
in isolation during `uv run pytest -m integration` verification (wall-clock ~11:42 UTC,
`>= 2 UTC`, the same trigger condition documented in every prior plan this phase). Confirmed
unrelated to this plan's files (none of the seven files this plan modifies reads or writes
`body_measurements`). Logged as the fifth occurrence to `deferred-items.md`; the follow-up
fix recommended since Plan 12-01 should now be prioritized, having recurred in every plan
this phase.

**Pre-existing `ruff format` drift in 16 unrelated files, discovered while broadly checking
formatting beyond this plan's scoped verify command:** confirmed none of this plan's six
touched Python files are among them, and confirmed all six are correctly formatted in
isolation. Logged to `deferred-items.md`, not fixed (out of scope).

## Next Phase Readiness

- All sixteen MCP tools are registered and structurally guarded: the exact-name registry,
  the read-only/write annotation partition, the byte budget table, both leak scans, and the
  coaching document all cover both new tools
- This is the final plan of Phase 12 (training-programs-confirm-gated-write-tool). The
  full non-flake test suite is green (971 passed, 11 skipped, one pre-existing unrelated
  flake deselected); `uv run mypy backend/app` and `uv run ruff check backend` are both
  clean
- Recommend the same follow-up flagged in every prior plan this phase: fix the
  `_seed_reference_history` time-of-day flake in `test_mcp_tools.py`
  (`test_body_measurement_trend_compares_latest_against_earliest`), now reproduced in all
  five plans

---
*Phase: 12-training-programs-confirm-gated-write-tool*
*Plan: 05*
*Completed: 2026-09-04*

## Self-Check: PASSED

All created/modified files confirmed present on disk (`backend/app/mcp/server.py`,
`backend/tests/test_mcp_tool_schemas.py`, `backend/tests/test_mcp_tool_budget.py`,
`backend/tests/test_mcp_tools.py`, `backend/tests/test_mcp_auth.py`,
`backend/tests/test_mcp_mount.py`, `docs/coaching-instructions.md`,
`deferred-items.md`, this SUMMARY.md); all three task commits (`6dd2d4e`, `f315027`,
`b1c7bfb`) confirmed present in `git log`.
