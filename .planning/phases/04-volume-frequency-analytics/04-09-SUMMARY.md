---
phase: 04-volume-frequency-analytics
plan: 09
subsystem: analytics
tags: [pytest, testcontainers, postgres, date-trunc, decimal, mutation-probe, asvs]

# Dependency graph
requires:
  - phase: 04-volume-frequency-analytics
    plan: 05
    provides: "app/analytics/rollup.py — build_window / resolve_window / weekly_set_rows / the three folds"
  - phase: 04-volume-frequency-analytics
    plan: 03
    provides: "golden_workout builder, GoldenSet/GoldenExercise, ANALYTICS_SECOND_USER_ID"
  - phase: 04-volume-frequency-analytics
    plan: 01
    provides: "validate_timezone / snap_local_week_range, whose error literals the guard tests match on"
provides:
  - "backend/tests/test_analytics_rollup.py — the missing test(...) gate commit for rollup.py"
  - "Seven container-free business-rule tests: three window guards, the snap/no-snap distinction, session de-duplication in both directions, query-time weighting, unmapped-template tolerance"
  - "Four container-backed aggregate tests: local-week bucketing from users.timezone, the date-not-datetime guarantee, warm-up exclusion with dropset inclusion, operand-presence tonnage including the computed zero, cross-tenant scoping"
  - "A recorded six-mutation non-vacuity probe proving every load-bearing assertion fails against the corresponding wrong implementation"
affects: [04-06, 04-07, 04-08, 05-progression-plateau-pr, 06-mcp-tools]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Every integration test resolves its window through resolve_window, so no test can pass against code that ignores users.timezone"
    - "Paired-direction assertions: the bug AND its naive fix are both pinned red"
    - "Non-vacuity guard before the real assertion (assert theirs, ...) so an empty fixture cannot fake a pass"
    - "Consequence-naming assertion messages quoting live-data counts, so a failure reads as a business impact rather than a number mismatch"

key-files:
  created:
    - backend/tests/test_analytics_rollup.py
  modified: []

key-decisions:
  - "Imports were introduced per task rather than as one block, because Ruff F401 would have failed Task 1's own lint gate on the Task 2 symbols"
  - "A six-mutation probe was run against rollup.py and reverted, because a test plan that never observes a red is a test plan that proves nothing"
  - "`mypy backend` is not clean and cannot be made clean by this plan: 44 errors pre-exist in 13 unrelated test files. `mypy backend/app` is green and the new file contributes zero errors"

patterns-established:
  - "Test module docstring names the load-bearing test and states what it would catch, so a future reader knows which assertion not to delete"
  - "Fixture ids namespaced per module (ROLLUP-*) because the Postgres container is session-scoped and shared"

# This plan tests the substrate; it computes no weekly volume figure, no per-muscle result and
# no frequency rate. See "Requirements Status".
requirements-completed: []
requirements-advanced: [VOL-01, VOL-02, VOL-03]

# Metrics
duration: 11min
completed: 2026-08-30
---

# Phase 4 Plan 09: Rollup Test Suite Summary

**Eleven tests pinning `app/analytics/rollup.py` — seven business rules that stay verifiable with Docker stopped and four SQL behaviours that have no meaning outside real PostgreSQL — every load-bearing assertion of which was individually proven to go red against the corresponding wrong implementation before being trusted.**

## Performance

- **Duration:** ~11 min
- **Started:** 2026-08-30T17:28Z (worktree base correction)
- **Completed:** 2026-08-30T17:38Z
- **Tasks:** 2 of 2
- **Files created:** 1 (no existing file modified)

## Accomplishments

- **`rollup.py` now has its `test(...)` gate.** Plan 04-05 shipped 385 lines of the phase's one genuinely new architectural tier with a deliberately-deleted throwaway probe and no committed test. `backend/tests/test_analytics_rollup.py` (432 lines, 11 tests) is that file's designated owner and closes the gap 04-05's TDD Gate Compliance section flagged.
- **Every assertion was proven non-vacuous by mutation, not by reasoning.** Six mutations were applied to `rollup.py`, run, and reverted (details in Verification Evidence). Each one turned exactly the predicted test red, with the predicted message. This is the difference between "the tests pass" and "the tests would notice".
- **The business rules survive a stopped Docker.** Seven of the eleven carry no marker: `pytest -m "not integration"` runs them in 0.01s. The three window guards, the U-01/D-03 snap distinction, session de-duplication and NORM-03 weighting are all decisions about what a number *means*, and none of them needs a database to be checked.
- **Session de-duplication is pinned in both directions.** The summing bug (`len == 1` asserted) and the naive "always return 1" fix (`len == 3` asserted) both fail. A mutation replacing `session_ids.add(...)` with `session_ids = {...}` — the exact shape of the naive fix — was confirmed red on the second assertion only.
- **Cross-tenant scoping is proven with a non-vacuity guard in front of it.** `assert theirs, "the second user's fixture produced no rows -- this test proves nothing"` runs before the disjointness check, so a broken fixture reports itself rather than certifying isolation by writing nothing.
- **The shared container is provably unpolluted.** `test_migrations.py` and `test_normalization_mapping.py` were re-run in the same session immediately after this module: 26 passed. All fixture ids use the `ROLLUP-*` prefix and every write is rolled back by `golden_workout`.

## Task Commits

Each task was committed atomically:

1. **Task 1: Fast-suite tests — window guards and the pure muscle folds** — `a504403` (test)
2. **Task 2: Integration tests — the SQL aggregate against a real Postgres container** — `bbffc72` (test)

## Files Created/Modified

- `backend/tests/test_analytics_rollup.py` (created, 432 lines) — module docstring naming the three counter-intuitive rules and the load-bearing test; the `ROLLUP-*` fixture ids, `_JAKARTA_MONDAY_MIDNIGHT`, `_WEEK_START`/`_WEEK_END`, `_CUSTOM_WEIGHTS`; the `_ham_row` / `_direct` / `_indirect` pure builders; seven unmarked tests; four `@pytest.mark.integration` tests.

Nothing else in the repository changed. `git diff --name-only` against the base commit lists exactly one path.

## Decisions Made

- **Imports were introduced per task.** Same trap plan 04-05 hit. The plan asks for "ONE import block that Task 2 extends", but Task 1's own acceptance criteria include `ruff check` exiting 0, and Ruff `F401` fails on the Task 2 symbols (`AsyncSession`, `resolve_window`, `weekly_set_rows`, the four `conftest` names) while they are unused. See Deviation 1.
- **The probe was run, then reverted.** Writing eleven green tests against an implementation that was never observed failing would have certified nothing. Six one-line mutations, four runs, all reverted with a per-file `git checkout --`. See Verification Evidence.
- **Two small pure helpers (`_direct`, `_indirect`) were added** beyond the plan's `_ham_row`. The plan's inline `[EffectiveMuscle(CanonicalMuscleGroup.HAMSTRINGS, MuscleRole.DIRECT, MappingSource.CURATED)]` is 96 characters before indentation and would have wrapped across three lines inside every `resolved` dict, burying the one thing each fold test varies. The helpers make the DIRECT-vs-INDIRECT difference the only visible difference between tests 5 and 6.
- **`zero_load_message` is bound to a name and asserted twice.** The plan asks for the operand-presence message on both `tonnage_sets == 1` and `tonnage_kg == Decimal("0.000")`. One shared literal keeps the two halves of the same claim from drifting apart.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] The plan's single import block cannot satisfy its own Task 1 lint gate**

- **Found during:** Task 1
- **Issue:** The plan's Task 1 `<action>` says to write "ONE import block that Task 2 extends", while Task 1's acceptance criteria require `ruff check backend/tests/test_analytics_rollup.py` to exit 0. Ruff `F401` fails on `AsyncSession`, `resolve_window`, `weekly_set_rows`, `ANALYTICS_SECOND_USER_ID`, `DEFAULT_USER_ID`, `GoldenBuilder`, `GoldenExercise` and `GoldenSet` while only the fast-suite tests exist. The two instructions are mutually unsatisfiable at the Task 1 commit boundary.
- **Fix:** Task 1 imported exactly what it used (`dt`, `uuid`, `Decimal`, `pytest`, six `rollup` names, three `muscles` names, `EffectiveMuscle`). Task 2 extended the same single block in place — the file still has ONE import block, which is the instruction's actual intent. The final block is the plan's, plus nothing extra.
- **Files modified:** `backend/tests/test_analytics_rollup.py`
- **Verification:** `ruff check` exits 0 at both commit boundaries; `ruff format --check` reports the file already formatted at each.
- **Committed in:** `a504403`, `bbffc72`

**2. [Rule 3 - Blocking] `mypy backend` cannot exit 0 — 44 errors pre-exist in 13 unrelated test files**

- **Found during:** Task 2 verification
- **Issue:** Task 2's acceptance criteria include `.venv/bin/python -m mypy backend` exiting 0. It exits 1 with `Found 44 errors in 13 files (checked 82 source files)` — the identical count recorded as pre-existing in 04-03's Deferred Issues and re-confirmed in 04-05. The offenders are `conftest.py`, `test_cloud_run_deploy.py`, `test_config.py`, `test_db_models.py`, `test_health.py`, `test_hevy_body.py`, `test_hevy_client.py`, `test_hevy_end_to_end.py`, `test_hevy_resilience.py`, `test_hevy_sync.py`, `test_mcp_auth.py`, `test_mcp_tools.py`, `test_secret_redaction.py`. Fixing them is out of this plan's scope boundary (none is touched by this plan's changes).
- **Fix:** Verified the meaningful invariant instead — `mypy backend` reports **zero** errors on `test_analytics_rollup.py`, and `mypy backend/app` is green (`Success: no issues found in 45 source files`). The pre-existing 44 are unchanged in count and in file list, before and after.
- **Files modified:** none
- **Verification:** `mypy backend 2>&1 | grep -c test_analytics_rollup` → `0`; error total `44` at base and at HEAD.
- **Committed in:** n/a

**3. [Rule 3 - Blocking] No `.venv` in the parallel worktree**

- **Found during:** Pre-Task 1 setup
- **Issue:** Every verify and acceptance command in the plan is written against `.venv/bin/python`, and a fresh worktree has no virtualenv. Note that `.gitignore` line 6 is `.venv/` with a trailing slash, which matches a *directory* — a symlink is not a directory to git, so the symlink shows as `?? .venv` in `git status` rather than being ignored.
- **Fix:** Symlinked the main checkout's `.venv` into the worktree root, as plans 04-02 and 04-05 did. `pyproject.toml` sets `pythonpath = ["backend"]`, so `app` and `tests` resolve against the *worktree's* sources. The symlink was never staged, and is removed before returning.
- **Files modified:** none tracked
- **Verification:** `git status --short` shows only the intended path plus `?? .venv` at every commit boundary; `git diff --name-only` against base lists exactly one file.
- **Committed in:** n/a

**4. [Rule 3 - Blocking] Worktree branch base was stale — fifth consecutive occurrence**

- **Found during:** Startup check
- **Issue:** `git merge-base HEAD a02e5fd` returned `1e97f3b`, which *is* HEAD — meaning the worktree branched from `chore(02-05): record auto-chain flag`, before Phase 4 planning existed and before either wave's output. `backend/app/analytics/rollup.py` — the entire subject of this plan — was absent.
- **Fix:** `git reset --hard a02e5fdd77852059718289bc5cf2aeed6b7a8d81` per the startup check, verified at `a02e5fd` before any work began. The worktree was clean, so nothing was lost.
- **Files modified:** none
- **Verification:** `git rev-parse HEAD` → `a02e5fdd77852059718289bc5cf2aeed6b7a8d81`; `rollup.py`, `04-09-PLAN.md` and both wave summaries present.
- **Committed in:** n/a

**5. [Rule 2 - Missing Critical] A mutation probe was added, because green-on-first-write proves nothing**

- **Found during:** Post-Task 2
- **Issue:** This is a test-only plan against an already-written module, so the ordinary TDD RED gate (write a failing test, then implement) is not expressible. Without a substitute, eleven tests that passed on their first run would carry no evidence that any of them would ever fail.
- **Fix:** Six one-line mutations applied to `rollup.py`, run, and reverted with a per-file `git checkout -- backend/app/analytics/rollup.py`. Each mutation turned exactly the predicted test red. Full table in Verification Evidence. `rollup.py` appears in no commit from this plan.
- **Files modified:** none (all mutations reverted; `git diff --name-only` against base lists only the test file)
- **Verification:** full suite green after the revert — 334 passed.
- **Committed in:** n/a

**6. [Rule 2 - Missing Critical] Requirement IDs deliberately not checked off**

- **Found during:** Post-execution
- **Issue:** The plan frontmatter carries `requirements: [VOL-01, VOL-02, VOL-03]`. This plan tests the substrate those requirements are computed *from*; it produces no weekly volume figure, no per-muscle result and no frequency rate. Marking them complete would assert a capability the code cannot yet perform, and this executor is instructed not to write shared orchestrator artifacts from a worktree.
- **Fix:** `REQUIREMENTS.md` left untouched; `requirements-completed: []` with `requirements-advanced: [VOL-01, VOL-02, VOL-03]` recorded here instead. Consistent with the identical calls made by plans 04-01, 04-02, 04-03 and 04-05.
- **Files modified:** none (the correction is the absence of a write)
- **Verification:** `git diff --name-only` against base lists only `backend/tests/test_analytics_rollup.py`.
- **Committed in:** n/a

---

**Total deviations:** 6 auto-fixed (1 internal contradiction in the plan document, 1 unachievable pre-existing-state criterion, 2 worktree-environment blockers, 1 evidence gap closed, 1 false-completion prevented)
**Impact on plan:** No scope creep and no functional drift. Every test named in both `<behavior>` blocks exists and asserts exactly what was specified, and every machine-checkable grep criterion passes. No production file was modified in any commit, `pyproject.toml` is unmodified, and zero dependencies were added.

## TDD Gate Compliance

Both tasks carry `tdd="true"`. This plan writes tests for a module that already exists, so the standard RED-then-GREEN commit pair is not expressible — there is no implementation commit to make.

- **RED gate:** satisfied twice over. (1) A pre-implementation check recorded `backend/tests/test_analytics_rollup.py: No such file or directory` before Task 1, with a full-suite baseline of 196 fast / 323 total at the base commit. (2) More meaningfully, the six-mutation probe below observes a genuine red for every load-bearing assertion in the file.
- **GREEN gate:** each task's `<verify>` block was executed and passed before its commit — 7 fast tests at Task 1, 11 total at Task 2, 334 full-suite.
- **Gate commits:** two `test(...)` commits, no `feat(...)` commit. **This is the intended shape** — the `feat(...)` commits for this module are plan 04-05's `77c5a27` / `499c4c8` / `9a55547`, and this plan is the `test(...)` half that 04-05's own summary predicted would land in wave 3.

## Verification Evidence

### Plan `<verification>` block — 6 of 7 pass, 1 unachievable and superseded

| # | Check | Result |
|---|-------|--------|
| 1 | `pytest backend/tests/test_analytics_rollup.py -q` | **11 passed** in 2.28s |
| 2 | `pytest backend/tests/test_analytics_rollup.py -q -m "not integration"` | **7 passed**, 4 deselected in 0.01s (no Docker needed) |
| 3 | `pytest test_migrations.py test_normalization_mapping.py` alongside this module | **26 passed** — shared container unpolluted, no id collisions |
| 4 | `pytest -q -m "not integration"` | **203 passed**, 131 deselected in 0.89s (baseline 196 in 1.02s — +7, no slowdown) |
| 5 | `pytest -q` (full suite) | **334 passed** in 9.28s (baseline 323 — +11, zero regressions) |
| 6 | `ruff check backend` / `mypy backend` | ruff **exits 0**. mypy exits 1 on 44 **pre-existing** errors in 13 unrelated files; `mypy backend/app` is green and this file contributes **zero**. See Deviation 2 |
| 7 | `git diff --name-only` lists only the test file | exactly `backend/tests/test_analytics_rollup.py` |

### Non-vacuity probe — six mutations to `rollup.py`, run and reverted

Applied in two batches, run against the committed test file, then reverted with a per-file `git checkout --`. `rollup.py` appears in no commit from this plan and the working tree was confirmed clean afterwards.

| # | Mutation to `rollup.py` | The wrong implementation it simulates | Predicted red | Observed |
|---|---|---|---|---|
| A | `set_type != WARMUP_SET_TYPE` → `set_type == "normal"` | the allow-list that discards 823 live dropset sets | `test_rows_exclude_warmups_and_count_dropsets` | ✓ red |
| B | `session_ids.add(row.workout_id)` → `.add(uuid.uuid4())` | summing sessions instead of de-duplicating | `test_fold_dedupes_sessions_within_one_workout` | ✓ red |
| C | `Workout.user_id == user_id` → `Workout.user_id.is_not(None)` | the missing tenant predicate (T-04-02) | `test_rows_are_scoped_to_one_user` | ✓ red |
| D | drop the `cast(..., Date)` around `date_trunc` | Pitfall 1 — a naive datetime week key | `test_rows_use_the_local_week_from_the_users_timezone` | ✓ red |
| E | `weight_kg.is_not(None)` → `weight_kg > 0` | "cleaning" the input, dropping 48 real zero-load sets | `test_tonnage_is_gated_on_operand_presence` | ✓ red |
| F | `session_ids.add(...)` → `session_ids = {row.workout_id}` | the naive fix — always report exactly 1 session | `test_fold_dedupes_sessions_within_one_workout`, second assertion only | ✓ red |

Batch 1 (A–D) produced `4 failed, 7 passed` — exactly the four predicted, no collateral. Batch 2 (E–F) produced `2 failed, 9 passed`, and the failure output was the intended prose verbatim:

```
E  AssertionError: the partner assertion: 'always return 1' must also fail
E  AssertionError: `0` is not NULL. Filtering `weight_kg > 0` to 'clean' the input would drop
   48 real live sets, and `tonnage_sets == 1` is what tells the caller this zero is computed
   rather than missing
```

Mutation F is the one that matters most: it leaves the *first* assertion of `test_fold_dedupes_sessions_within_one_workout` green and fails only the partner. That is precisely why the plan demanded both directions.

### Grep acceptance criteria — 16 of 16 pass

| Criterion | Required | Actual |
|---|---|---|
| `def test_` (after Task 1 / after Task 2) | 7 / 11 | 7 / 11 |
| `pytest.mark.integration` (after Task 1 / after Task 2) | 0 / 4 | 0 / 4 |
| `Decimal("6.0")` | 1 | 1 |
| `Decimal("4.4")` | 1 | 1 |
| `inflated hamstrings` | 1 | 1 |
| `exceeds the maximum span` | 1 | 1 |
| `unknown IANA timezone` | 1 | 1 |
| `always return 1` | 1 | 1 |
| `resolve_window(` | ≥4 | 5 |
| `not isinstance(rows[0].week_start, dt.datetime)` | 1 | 1 |
| `Decimal("3000.000")` | 1 | 1 |
| `Decimal("0.000")` | ≥2 | 2 |
| `ASVS V4 violated` | 1 | 1 |
| `823 live dropset` | 1 | 1 |
| file length | ≥220 lines | 432 |
| `ruff check` / `ruff format --check` on the file | exit 0 / formatted | exit 0 / already formatted |

### The `must_haves` key_links

| From | To | Via | Verified |
|---|---|---|---|
| `test_analytics_rollup.py` | `app.analytics.rollup.resolve_window` | every integration test resolves its window through the production path | 5 call sites across 4 tests; **no test names a timezone in an integration path** |
| `test_analytics_rollup.py` | `conftest.golden_workout` | flush-and-rollback golden fixtures | all 4 integration tests take the `golden_workout` fixture; `test_migrations.py` re-run clean afterwards |

## Threat Model Disposition

| Threat ID | Disposition | Status after this plan |
|-----------|-------------|------------------------|
| T-04-02 | mitigate | **Done, non-vacuously.** `test_rows_are_scoped_to_one_user` builds a second user's workout at the same instant in the same window, guards against an empty fixture *before* asserting, and requires the two `workout_id` sets to be disjoint. Mutation C confirmed it goes red without the predicate. |
| T-04-06 | mitigate | **Done.** `test_build_window_rejects_an_absurd_span` asserts a 200-year request raises before any query runs, with a docstring recording *why* it must be a rejection rather than a row cap — which is what keeps the guard from being removed as "unnecessary". |
| T-04-01 | mitigate | **Done.** `test_build_window_rejects_an_unknown_timezone` pins the boundary rejection by exact message; every integration test resolves through `resolve_window`, so nothing hardcodes a known-good zone and no test can pass against code that ignores `users.timezone`. |
| T-04-07 | mitigate | **Done on all three counts, each mutation-verified.** Warm-up exclusion with dropset inclusion (mutation A), operand-presence tonnage including the computed zero (mutation E), and session de-duplication pinned in both directions (mutations B and F). |
| T-04-05 | mitigate | **Done.** All three guard tests use `pytest.raises(..., match=...)` against fixed literals, so adding an interpolated date or user id to any message fails the suite. |
| T-04-12 | mitigate | **Done.** All ids use the `ROLLUP-*` prefix (distinct from `RESOLVER-*`, `VOL-*`, `FREQ-*` and the hevy ids); every write goes through `golden_workout`, which rolls back in a `finally`; `test_migrations.py` and `test_normalization_mapping.py` were re-run in the same session and pass. |

## Threat Flags

None. This plan adds no network endpoint, no auth path, no file access and no schema change. It adds one test module and nothing else.

## Known Stubs

None. All eleven tests are fully implemented, all eleven execute, and each load-bearing assertion was individually observed failing against a mutated implementation.

## Requirements Status

`.planning/REQUIREMENTS.md` was **deliberately left unmodified** — VOL-01, VOL-02 and VOL-03 remain unchecked.

| Requirement | Text | Delivered here? |
|---|---|---|
| VOL-01 | *System calculates weekly training volume…* | No — this plan proves the hard-set and tonnage rules the calculation depends on. Plan 04-04 produces the figure. |
| VOL-02 | *System calculates weekly per-muscle-group volume…* | No — this plan proves `fold_weeks_by_muscle`'s weighting and de-duplication. 04-06 assembles the result. |
| VOL-03 | *System calculates training frequency…* | No — this plan proves the session-set semantics and the no-snap rule frequency depends on. 04-07 divides by the window. |

The orchestrator should mark these complete once the plans that produce the actual figures land.

## Issues Encountered

- **Worktree base drift, fifth consecutive occurrence.** Documented as Deviation 4. This is now recorded in every Phase 4 wave summary. It warrants treatment as a worktree-provisioning defect rather than continued per-agent absorption: this particular occurrence would have been especially destructive, since the file under test (`rollup.py`) did not exist at the stale base and an agent skipping the startup check would have concluded the plan's premise was wrong.
- **No `.venv` in the worktree**, documented as Deviation 3, with the additional detail that `.gitignore`'s `.venv/` does not match a symlink.
- **Pre-existing `mypy backend/tests/` errors** (44 across 13 files) are untouched and out of scope, documented as Deviation 2.
- **Pre-existing `ruff format --check backend` drift** (11 files would be reformatted) is likewise pre-existing and out of scope; `ruff check backend` — the criterion the plan actually names — exits 0, and this plan's file is already formatted.

## User Setup Required

None — no external service configuration required. Docker must be running for the four integration tests; the other seven do not need it, which is the point.

## Next Phase Readiness

**Ready.** `rollup.py` is now a tested module rather than an executed-once one, and the contract plans 04-06/04-07/04-08 must honour is now enforced rather than merely documented:

- **Never sum `len(bucket.session_ids)` across buckets.** `test_fold_dedupes_sessions_within_one_workout` proves the fold does not inflate; nothing yet stops a consumer from re-introducing the 4.0x inflation on top of a correct fold. Each consumer needs its own equivalent assertion.
- **Weekly metrics pass `snap_to_weeks=True`, frequency passes `False`.** `test_build_window_snaps_only_when_asked` pins the 63-vs-61 distinction; a consumer that passes the wrong flag divides by the wrong denominator and this suite will not catch it.
- **`tonnage_kg is None` is not zero.** `test_tonnage_is_gated_on_operand_presence` pins the distinction at the aggregate; carrying it into `schemas.py` is the consumer's job.
- **Add a second-user assertion to every new query.** `test_rows_are_scoped_to_one_user` covers `weekly_set_rows` only. Every new function taking a `user_id` needs its own, with the same non-vacuity guard.

**Open item:** none blocking.

## Self-Check: PASSED

Files verified present on disk:

- FOUND: `backend/tests/test_analytics_rollup.py` (432 lines)
- FOUND: `backend/app/analytics/rollup.py` (unmodified — reverted after the probe)
- FOUND: `.planning/phases/04-volume-frequency-analytics/04-09-SUMMARY.md`

Commits verified in `git log`:

- FOUND: `a504403` test(04-09): add fast-suite tests for rollup window guards and pure folds
- FOUND: `bbffc72` test(04-09): add container-backed tests for the weekly set aggregate

No file deletions in either commit (`git diff --diff-filter=D --name-only a02e5fd HEAD` empty). `git diff --name-only a02e5fd HEAD` lists exactly one path. No untracked files left behind other than the removed `.venv` symlink.

---
*Phase: 04-volume-frequency-analytics*
*Completed: 2026-08-30*
