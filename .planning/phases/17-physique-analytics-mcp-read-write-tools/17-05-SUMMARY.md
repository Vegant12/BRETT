---
phase: 17-physique-analytics-mcp-read-write-tools
plan: 05
subsystem: mcp
tags: [mcp, annotations, physique, write-tool, docs]

# Dependency graph
requires:
  - phase: 17-physique-analytics-mcp-read-write-tools
    plan: 03
    provides: fitness_log_physique_observation, fitness_get_latest_physique_observation (built but unregistered)
provides:
  - Both physique tools live in the MCP registry (22 tools total)
  - EXPECTED_WRITE_ANNOTATIONS, a per-tool write-annotation mapping (MCP-08) replacing the
    uniform destructiveHint=True claim
  - NON_DESTRUCTIVE_WRITE_TOOL annotation object in app/mcp/server.py
  - BUDGETS/WORST_CASE_ARGS entries for both physique tools
  - docs/coaching-instructions.md rows and anti-ratchet gotcha bullet for the physique tools
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Per-tool write-annotation mapping (EXPECTED_WRITE_ANNOTATIONS), asserted key-set-equal to
      WRITE_TOOLS, replaces a uniform 'every write tool is destructiveHint=True' loop once a
      second, non-destructive write tool exists -- a third write tool that skips the mapping
      fails the key-set assertion rather than passing by being skipped"
    - "A write tool's budget/degradation-test worst case is measured on its REFUSED (no-write)
      branch via a fixed, non-existent target id, not its LOGGED branch -- the same device
      fitness_switch_training_program's 'already active' branch established, now applied a
      second time in test_mcp_tool_budget.py and (newly) in test_mcp_tools.py's
      MINIMAL_TOOL_ARGUMENTS, so no shared session-scoped test container accumulates rows"

key-files:
  created: []
  modified:
    - backend/app/mcp/server.py
    - backend/tests/test_mcp_tool_schemas.py
    - backend/tests/test_mcp_tool_budget.py
    - backend/tests/test_mcp_mount.py
    - backend/tests/test_mcp_auth.py
    - backend/tests/test_mcp_tools.py
    - docs/coaching-instructions.md
    - .planning/phases/17-physique-analytics-mcp-read-write-tools/deferred-items.md

key-decisions:
  - "Placed the app.mcp.tools.physique import before app.mcp.tools.ping rather than between ping
    and program_switch as the plan's action text literally specified: ruff's isort ordering
    (h < i) put physique first, and the plan's own Task 1 <verify> block requires ruff check to
    pass -- the acceptance criterion's grep count still holds regardless of exact position (Rule 1)."
  - "Fixed a real E501 (line too long) in the write tool's description string and reflowed one
    comment line in test_mcp_tool_budget.py -- caught by ruff, not part of the plan's literal
    text (Rule 1)."
  - "Added both physique tools to MINIMAL_TOOL_ARGUMENTS in test_mcp_tools.py (not in this plan's
    files_modified list) because registering the tools in Task 1 broke two tests elsewhere
    (test_mcp_tools.py::test_every_tool_degradation_leaks_nothing and
    test_secret_redaction.py's shared-table test) that assert MINIMAL_TOOL_ARGUMENTS names
    exactly the registered tool set. The plan's own success criteria require 'uv run pytest
    backend/tests -q is fully green' (Rule 3 -- blocking issue)."
  - "The write tool's MINIMAL_TOOL_ARGUMENTS entry uses a fixed non-existent
    supersedes_observation_id to force the REFUSED (no-write) branch, mirroring
    test_mcp_tool_budget.py's _physique_log_arguments() device, so neither the dead-database
    degradation test nor the healthy-container secret-redaction test leaves a row behind in the
    shared session-scoped Postgres test container."
  - "Corrected two stale doc references (test_mcp_mount.py, test_mcp_auth.py) to the renamed
    test_tool_registry_is_exactly_the_twenty -> _twenty_two, so the comment cross-references stay
    accurate (Rule 2 -- documentation accuracy, same class of fix 17-03-SUMMARY.md documented)."

patterns-established: []

requirements-completed: [PHYS-06, PHYS-07, MCP-08]

# Metrics
duration: 16min
completed: 2026-09-11
---

# Phase 17 Plan 05: Register Physique Tools & Widen the Write-Annotation Guard Summary

**Both physique MCP tools registered in the live registry (22 tools total), the write-annotation
guard restructured from a uniform `destructiveHint=True` claim into a per-tool mapping (MCP-08)
so `fitness_log_physique_observation`'s non-destructive write can coexist with
`fitness_switch_training_program`'s destructive one without weakening either claim, and both new
tools documented with a byte budget and a coaching-doc entry.**

## Performance

- **Duration:** ~16 min
- **Started:** 2026-09-11T04:23:43Z (worktree base reset)
- **Completed:** 2026-09-11T04:39:17Z
- **Tasks:** 3 (plus one Rule-3 follow-up fix)
- **Files modified:** 8

## Accomplishments
- `app/mcp/server.py`: both physique tools registered — the read tool inside the shared
  `READ_ONLY` `_TOOLS` loop, the write tool outside it with a new `NON_DESTRUCTIVE_WRITE_TOOL`
  annotation object (`destructive_hint=False`, `idempotent_hint=False`, `open_world_hint=False`).
  `_INSTRUCTIONS` rewritten to name both write tools instead of claiming
  `fitness_switch_training_program` is the only one.
- `test_mcp_tool_schemas.py`: `WRITE_TOOLS` widened to an exact two-member set;
  `EXPECTED_WRITE_ANNOTATIONS` added as a per-tool mapping whose key set is asserted equal to
  `WRITE_TOOLS` (MCP-08) — a third write tool that skips the mapping fails the suite rather than
  passing by being skipped. `test_annotations_are_an_exact_partition`'s uniform
  `destructiveHint is True` loop replaced with a per-tool comparison against the mapping.
  `test_the_write_tool_publishes_explicit_write_annotations` renamed to
  `test_every_write_tool_publishes_explicit_write_annotations` and loops over both write tools.
  `test_tool_registry_is_exactly_the_twenty` renamed to `_twenty_two` with both physique names
  added to `EXPECTED_TOOLS`.
- `test_mcp_tool_budget.py`: `BUDGETS` gains `fitness_log_physique_observation` (2,048 — fixed
  shape, no echoed list) and `fitness_get_latest_physique_observation` (8,192 — derived from the
  schema's own caps). `WORST_CASE_ARGS` gains a no-write worst-case call for each, with the write
  tool's call forced onto its REFUSED branch via a fixed, non-existent
  `supersedes_observation_id` so the budget measurement commits nothing.
- `docs/coaching-instructions.md`: two new rows in the "Which tool answers which question" table
  with accurate required-parameter bolding, and one new gotcha bullet carrying the Phase 15 D-08
  anti-ratchet instruction (read the latest observation first, treat it as a sanity check not a
  target, `pose_state`/`photo_angles_present` gate comparability). No second restatement of the
  "subjective model output" framing (D-06) — the required `disclaimer` field already carries it.
  Trimmed unrelated prose (an explanatory sentence in "Example questions", one verbose metadata-
  envelope cell) to hold the document at 8,935 characters, under the 9,000 paste ceiling.
- `test_mcp_tools.py`: `MINIMAL_TOOL_ARGUMENTS` gains both physique tools (Rule 3 fix, see
  Deviations) so `test_every_tool_degradation_leaks_nothing` and `test_secret_redaction.py`'s
  shared-table test stay green with the newly-registered tools.

## Task Commits

Each task was committed atomically:

1. **Task 1: Register both tools and correct the instructions string** - `2ce4b37` (feat)
2. **Task 2: Restructure the annotation guard into a per-tool mapping (MCP-08) and budget both tools** - `db6836d` (test)
3. **Task 3: Tell Claude the tools exist and carry the anti-ratchet gotcha** - `fc5964f` (docs)
4. **Rule-3 follow-up: add both tools to MINIMAL_TOOL_ARGUMENTS** - `b783296` (fix)

## Files Created/Modified
- `backend/app/mcp/server.py` - Registered both physique tools; added `NON_DESTRUCTIVE_WRITE_TOOL`; rewrote `_INSTRUCTIONS`
- `backend/tests/test_mcp_tool_schemas.py` - `EXPECTED_WRITE_ANNOTATIONS` per-tool mapping (MCP-08); `WRITE_TOOLS` widened to two; two tests renamed; `EXPECTED_TOOLS` gains both names
- `backend/tests/test_mcp_tool_budget.py` - `BUDGETS`/`WORST_CASE_ARGS` entries and `_physique_log_arguments()` helper for both new tools
- `backend/tests/test_mcp_mount.py` - Corrected a stale cross-reference to the renamed registry test
- `backend/tests/test_mcp_auth.py` - Corrected a stale cross-reference to the renamed registry test
- `backend/tests/test_mcp_tools.py` - Added both physique tools to `MINIMAL_TOOL_ARGUMENTS` (Rule 3)
- `docs/coaching-instructions.md` - Two new table rows plus the anti-ratchet gotcha bullet; trimmed prose to stay under the paste ceiling
- `.planning/phases/17-physique-analytics-mcp-read-write-tools/deferred-items.md` - Logged pre-existing, out-of-scope drift found during verification

## Decisions Made
- **Import placement resolved by ruff, not the plan's literal wording (Rule 1):** the plan's action text said to place the `app.mcp.tools.physique` import "between `...ping` and `...program_switch`", but ruff's isort ordering places `physique` before `ping` (`h` < `i`). Since Task 1's own `<verify>` block requires `ruff check` to pass, the import was placed where ruff's `I001` rule requires. All of Task 1's acceptance-criteria greps still hold at this position.
- **Fixed two real ruff findings the plan's literal action text would have introduced (Rule 1):** an `E501` line-too-long in the new tool's `description=` string in `server.py`, and the same in a new comment in `test_mcp_tool_budget.py`. Both reflowed within the existing prose, no content change.
- **Added both physique tools to `test_mcp_tools.py::MINIMAL_TOOL_ARGUMENTS` (Rule 3, not in this plan's `files_modified`):** registering the tools in Task 1 made two tests outside this plan's listed files fail their own "the argument table must name exactly the registered tool set" assertions — `test_mcp_tools.py::test_every_tool_degradation_leaks_nothing` and `test_secret_redaction.py::test_mcp_tool_response_contains_no_configured_secret` (which imports the same table). The plan's own `<success_criteria>` requires `uv run pytest backend/tests -q` to be fully green, so this was a blocking issue, not a missed instruction. The write tool's minimal arguments use a fixed, non-existent `supersedes_observation_id` to force the REFUSED branch — the same no-write device `test_mcp_tool_budget.py::_physique_log_arguments()` uses — so this shared-container test does not leave a physique observation row behind for the rest of the session-scoped test run.
- **Corrected two stale doc cross-references (Rule 2):** `test_mcp_mount.py` and `test_mcp_auth.py` each had a comment naming `test_mcp_tool_schemas.test_tool_registry_is_exactly_the_twenty`, which Task 2 renamed to `_twenty_two`. Left uncorrected, the comments would point at a test name that no longer exists — the same class of fix 17-03-SUMMARY.md documented for `_common.py`'s docstrings.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Lint] Import placement and two E501 line-length findings**
- **Found during:** Task 1 and Task 2 verification (`uv run ruff check`)
- **Issue:** The plan's literal action text placed the `physique` import between `ping` and `program_switch`, which violates ruff's isort ordering; the write tool's description string and one budget-file comment each exceeded the 100-character line limit as written.
- **Fix:** Moved the import to before `ping` (ruff's required position); reflowed the two long lines.
- **Files modified:** `backend/app/mcp/server.py`, `backend/tests/test_mcp_tool_budget.py`
- **Verification:** `uv run ruff check` / `ruff format --check` both clean on all touched files.
- **Committed in:** `2ce4b37`, `db6836d`

**2. [Rule 3 - Blocking issue] Two tests outside this plan's file list broke on registration**
- **Found during:** Running the plan's own `<verification>` block (`uv run pytest backend/tests -q`)
- **Issue:** `test_mcp_tools.py::test_every_tool_degradation_leaks_nothing` and
  `test_secret_redaction.py::test_mcp_tool_response_contains_no_configured_secret` both assert
  `MINIMAL_TOOL_ARGUMENTS`'s key set equals the live registry. Registering two new tools in Task 1
  broke both assertions.
- **Fix:** Added a `{}` entry for the read tool and a schema-valid, REFUSED-branch entry (fixed
  non-existent `supersedes_observation_id`) for the write tool.
- **Files modified:** `backend/tests/test_mcp_tools.py`
- **Verification:** Both named tests pass individually; full suite `uv run pytest backend/tests -q` — 1,149 passed, 11 skipped, 0 failed.
- **Committed in:** `b783296`

**3. [Rule 2 - Documentation accuracy] Two stale test-name cross-references**
- **Found during:** Checking for other references to the renamed `test_tool_registry_is_exactly_the_twenty`
- **Issue:** `test_mcp_mount.py` and `test_mcp_auth.py` each named the pre-rename test in a
  docstring/comment, which Task 2 made stale.
- **Fix:** Updated both to `test_tool_registry_is_exactly_the_twenty_two`.
- **Files modified:** `backend/tests/test_mcp_mount.py`, `backend/tests/test_mcp_auth.py`
- **Verification:** `uv run pytest backend/tests/test_mcp_mount.py backend/tests/test_mcp_auth.py -q` passes; `ruff check`/`format --check` clean.
- **Committed in:** `db6836d`

---

**Total deviations:** 3 auto-fixed (2 lint, 1 blocking-issue, 1 documentation-accuracy — grouped above as 2 and 3)
**Impact on plan:** No scope creep beyond what the plan's own success criteria (a fully green
`backend/tests` suite) required. All fixes are additive to the plan's stated files or are the
minimum touch needed to keep an already-passing test suite passing after this plan's registration
change.

## Issues Encountered

- **Acceptance-criteria grep imprecision, `backend/app/mcp/server.py` (documented in
  `deferred-items.md`):** Task 1's acceptance criterion `grep -c "destructive_hint=False"` expects
  `2` but the real count is `3` — the third match is the literal phrase inside the
  `NON_DESTRUCTIVE_WRITE_TOOL` comment block (present verbatim in the plan's own action text),
  not a second field assignment. The two live field assignments (`READ_ONLY`,
  `NON_DESTRUCTIVE_WRITE_TOOL`) are correct and match PHYS-06's intent; this is the same class of
  plan-authoring grep imprecision 17-01-SUMMARY.md and 17-03-SUMMARY.md already documented, not an
  implementation defect.
- **Plan verification block references a nonexistent test file:** the plan's `<verification>`
  section lists `backend/tests/test_mcp_physique.py`, which does not exist — plan 17-03 put its
  physique tool coverage into `test_mcp_schemas.py`/`test_mcp_isolation.py` instead, per its own
  SUMMARY. Ran the verification block without that one path; the rest of the named suites all
  pass, and the full `backend/tests` run (which would include a file at that path if it existed)
  is green.
- **Manual registry sanity script from the plan's `<verification>` block not run standalone:** the
  plan includes a raw `uv run python -c "..."` script asserting the live registry via `mcp.Client`.
  Reproducing its required environment (MCP auth secret, issuer/resource URLs, allowed hosts)
  outside the pytest fixture stack was not attempted, since every assertion in that script is a
  strict subset of what `test_mcp_tool_schemas.py`'s passing tests already prove (22-tool registry,
  the write tool's exact four annotation flags, `ratings` published as an array, no `user_id`/`ctx`
  leak, a non-empty `outputSchema`) against the real fixture-backed app.
- **Pre-existing, out-of-scope drift found and logged, not fixed:** `ruff format --check
  backend/tests` reports 14 unrelated files needing reformatting (same class of drift 17-02 already
  logged, now covering more files); `test_mcp_tool_budget.py`'s
  `test_every_tool_response_fits_its_budget` docstring still says "Thirteen tools" though `BUDGETS`
  held 20 keys before this plan and 22 after. Both logged in `deferred-items.md` per the executor's
  SCOPE BOUNDARY rule.

## User Setup Required

None — no external service configuration required. This is the last plan of Phase 17; the
`docs/coaching-instructions.md` update is a paste target for the user's existing Claude Project
custom instructions, not a new setup step (the document was already in that role before this plan).

## Next Phase Readiness

Phase 17 (physique-analytics-mcp-read-write-tools) is now complete per its own success criteria:
the live registry serves 22 tools including both physique tools, the write tool's annotations are
distinct from the destructive tool's, `EXPECTED_WRITE_ANNOTATIONS`'s key-set assertion makes a
third unmapped write tool fail rather than pass silently, both new tools carry a budget and a
no-write worst case, `docs/coaching-instructions.md` documents both tools under the 9,000-character
ceiling, and `uv run pytest backend/tests -q` is fully green (1,149 passed, 11 skipped, 0 failed).

No blockers identified for Phase 18 (Monthly Report Physique Integration): both MCP tools are now
live and discoverable, so a real Claude conversation can call
`fitness_get_latest_physique_observation` and `fitness_log_physique_observation` today, ahead of
the monthly-report composition work.

---
*Phase: 17-physique-analytics-mcp-read-write-tools*
*Completed: 2026-09-11*

## Self-Check: PASSED

All created/modified files confirmed present on disk:
- `backend/app/mcp/server.py` — FOUND
- `backend/tests/test_mcp_tool_schemas.py` — FOUND
- `backend/tests/test_mcp_tool_budget.py` — FOUND
- `backend/tests/test_mcp_mount.py` — FOUND
- `backend/tests/test_mcp_auth.py` — FOUND
- `backend/tests/test_mcp_tools.py` — FOUND
- `docs/coaching-instructions.md` — FOUND
- `.planning/phases/17-physique-analytics-mcp-read-write-tools/deferred-items.md` — FOUND

All task commits confirmed present in git log:
- `2ce4b37` — FOUND
- `db6836d` — FOUND
- `fc5964f` — FOUND
- `b783296` — FOUND
