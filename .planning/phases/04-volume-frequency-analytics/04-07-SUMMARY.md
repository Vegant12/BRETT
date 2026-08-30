---
phase: 04-volume-frequency-analytics
plan: 07
subsystem: analytics
tags: [decimal, quantization, set-deduplication, postgres, sqlalchemy, pydantic, timezone]

# Dependency graph
requires:
  - phase: 04-volume-frequency-analytics
    plan: 02
    provides: "MuscleGroupFrequency / ExerciseFrequency / TrainingFrequencyResult in app/analytics/schemas.py, and the six static isolation assertions"
  - phase: 04-volume-frequency-analytics
    plan: 03
    provides: "golden_workout builder, GoldenSet/GoldenExercise, ANALYTICS_SECOND_USER_ID"
  - phase: 04-volume-frequency-analytics
    plan: 04
    provides: "FRESHNESS_RESOURCES_MUSCLE, is_insufficient, build_freshness, build_coverage"
  - phase: 04-volume-frequency-analytics
    plan: 05
    provides: "resolve_window, weekly_set_rows, resolve_row_muscles, fold_window_by_muscle, fold_window_by_template"
  - phase: 03-hevy-integration-normalization
    provides: "exercise_templates table with its per-user title column, and effective_muscles_bulk behind resolve_row_muscles"
provides:
  - "get_training_frequency (VOL-03): sessions per week overall, per muscle group and per exercise over an arbitrary requested range"
  - "sessions_per_week(sessions, days): the pure, exact, quantized rate helper, public so Phase 5's CMP-01 reuses one definition"
  - "The D-03 unsnapped-window path: the first consumer to resolve a window with snap_to_weeks=False and divide by its true length"
  - "The per-row U-03 confidence pattern: per-muscle and per-exercise sessions + insufficient_data alongside an unchanged response-level D-06 block"
  - "12 tests in backend/tests/test_analytics_frequency.py, both directions of session de-duplication pinned by mutation-verified assertions"
affects: [04-09, 05-progression-plateau-pr, 06-mcp-tools]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Quantize a derived rate at exactly one boundary site, against a named module quantum, so no unrounded Decimal ever reaches a caller"
    - "Collapse accumulator buckets to per-key counts in one dict comprehension before building response rows, so len(session_ids) appears once per grain rather than three times per row"
    - "A raise, not a sentinel, for a zero-length window: a caller bug is not a zero rate"
    - "Mutation-verify a load-bearing test in both directions before committing it"

key-files:
  created:
    - backend/app/analytics/frequency.py
    - backend/tests/test_analytics_frequency.py
  modified: []

key-decisions:
  - "get_training_frequency's docstring describes the unsnapped window in prose rather than repeating the snap_to_weeks=False token, because the plan's own acceptance criterion caps that literal at one line and the call site is the line that must carry it"
  - "The module docstring names the regression warning sign as 'any total taken over the .sessions fields' rather than spelling the builtin call, because the plan simultaneously required that phrase and required zero occurrences of that call's literal text in the file"
  - "Per-muscle and per-exercise session counts are collapsed into two dict comprehensions before the response rows are built, so len(bucket.session_ids) is written once per grain instead of three times per row"
  - "Freshness and cross-tenant fixtures are written against ANALYTICS_SECOND_USER_ID, following test_analytics_metadata.py: the default user's sync_state rows belong to the Hevy sync suite and the container is session-scoped"
  - "The cross-tenant test gives both users a template under the SAME external id with different titles, so the new title lookup is proven scoped and not merely the workout aggregate"
  - "requirements mark-complete deliberately not run: DQ-01/DQ-02 say EVERY analytics response, which is only true once the concurrent wave-3 siblings land, and REQUIREMENTS.md is under concurrent modification"

patterns-established:
  - "Rate metrics resolve their window unsnapped and divide by window.days; bucketed metrics snap outward. The two are different questions and the divergence is documented at both call sites"
  - "A pure arithmetic helper that a later phase will reuse is public and tested without an integration marker, so the formula stays verifiable when Docker is not running"
  - "Paired directional tests for any de-duplication rule: one test that the naive sum fails, one that the naive constant fails"

requirements-completed: []

# Metrics
duration: 15min
completed: 2026-08-30
---

# Phase 4 Plan 07: Training Frequency (VOL-03) Summary

**`get_training_frequency` returns sessions/week overall, per muscle group and per exercise over any requested range, with per-muscle counts as distinct-workout set sizes rather than summed per-template counts — the 4.0x inflation RESEARCH flagged as the phase's most dangerous defect, now pinned in both directions by mutation-verified tests.**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-08-30T10:27Z
- **Completed:** 2026-08-30T10:42Z
- **Tasks:** 3
- **Files created:** 2 (683 lines)

## Accomplishments

- **VOL-03 shipped.** `get_training_frequency(session, *, user_id, start_day, end_day, weights=None)` composes the unsnapped window, the shared weekly aggregate, both window folds and a one-query title lookup into a `TrainingFrequencyResult`.
- **The 4.0x inflation is structurally impossible here.** Every session count is `len(...session_ids)` — the size of a set that `rollup.fold_window_by_muscle` de-duplicated — and the file contains zero occurrences of the summing builtin, enforced by grep.
- **Both failure directions are proven, not asserted.** The implementation was temporarily mutated to `sessions = 3` (the summing bug) and then to `sessions = 1` (the naive fix), and each mutation failed exactly one of the paired tests. Neither test is vacuous, and the second is what stops the first from being "fixed" wrongly.
- **D-03 landed.** Frequency is the first consumer to call `resolve_window(..., snap_to_weeks=False)`; a 10-day window is 10/7 weeks, verified against a deliberately non-multiple-of-7 range that would pass for an implementation dividing by whole weeks.
- **`sessions_per_week` is exact, quantized in one place, and public.** Phase 5's CMP-01 per-week normalization now has one definition to reuse rather than a formula to re-derive.
- **U-03 coexists with D-06 rather than replacing it.** A window holding two sessions where chest was trained once reports `coverage.insufficient_data is False` and `chest.insufficient_data is True` simultaneously — the case a single response-level flag cannot express.

## Task Commits

Each task was committed atomically:

1. **Task 1: Write `get_training_frequency` and the pure `sessions_per_week` helper** — `55bbf22` (feat)
2. **Task 2: Test VOL-03 — session de-duplication, per-week arithmetic, per-exercise rows** — `dfdc537` (test)
3. **Task 3: Test VOL-03 metadata, deterministic ordering and cross-tenant scoping** — `9f81b23` (test)

**Plan metadata:** committed separately with this SUMMARY.

## Files Created/Modified

- `backend/app/analytics/frequency.py` (175 lines, new) — `sessions_per_week` (pure, exact, quantized, rejects a zero-day window), `_template_titles` (one `IN` query, explicitly tenant-scoped), and `get_training_frequency` (VOL-03).
- `backend/tests/test_analytics_frequency.py` (508 lines, new) — 12 tests: 2 markerless arithmetic tests and 10 integration tests covering de-duplication in both directions, the arbitrary-range rate, per-exercise rows and titles, unsynced-template degradation, per-resource freshness, the D-06 block on both sides of the threshold, per-row U-03 confidence, deterministic ordering and cross-tenant scoping.

## Decisions Made

**1. The docstring describes the unsnapped window; the call site carries the token.**
The plan supplied a `get_training_frequency` docstring beginning with the literal `snap_to_weeks=False`, while its own acceptance criterion required that literal to appear on exactly one line. Since `grep -c` counts lines, the plan's docstring and its call site together would have failed the plan. The call site is the line that must carry it — a docstring cannot be wrong about behaviour it does not execute — so the docstring says "resolved WITHOUT week snapping" instead.

**2. The regression warning sign is named in prose, not in code-literal form.**
The plan required the module docstring to say the warning sign is `sum(... .sessions ...)` while simultaneously requiring `grep -c "sum("` to return 0 for the file. Written as "any total taken over the `.sessions` fields of these rows, anywhere downstream", which conveys the same warning and keeps the structural guard intact. `rollup.py` already carries the code-literal form of the same warning at its fold, where no such grep applies.

**3. Session counts are collapsed to per-key dicts before rows are built.**
`muscle_sessions = {group: len(bucket.session_ids) for group, bucket in by_muscle.items()}` runs first, then the response rows read from it. The plan's shape would have called `len(...)` three times per row (for `sessions`, for the rate, and for the flag). One collapse per grain keeps the load-bearing expression written once and readable.

**4. Second-user fixtures for the freshness and scoping tests.**
`test_analytics_metadata.py` documents why `sync_state` rows for `DEFAULT_USER_ID` belong to the Hevy sync suite in a session-scoped shared container. The freshness test follows that precedent rather than writing the default user's bookkeeping rows.

**5. The cross-tenant test proves the title lookup, not just the aggregate.**
Both users get a template under the same `external_id` with titles `"Mine"` and `"Theirs"`. Hevy's built-in template ids are global, so a `_template_titles` query missing its `user_id` predicate would attach the other user's exercise name to this user's row — a leak the workout aggregate's own scoping would not catch.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Worktree based on a stale commit**
- **Found during:** Startup, before Task 1
- **Issue:** `git merge-base HEAD a02e5fd` returned HEAD itself, meaning the worktree branch was created from an ancestor of the intended base and did not contain wave 2's `rollup.py` or `metadata.py`. This is the fifth consecutive occurrence across this phase's waves.
- **Fix:** `git reset --hard a02e5fd`, verified `git rev-parse HEAD` matched before any other work.
- **Files modified:** None (branch pointer only)
- **Verification:** `git rev-parse HEAD` == `a02e5fd`; `backend/app/analytics/rollup.py` and `metadata.py` present and importable.

**2. [Rule 3 - Blocking] No `.venv` in the worktree**
- **Found during:** Startup
- **Issue:** `.venv` is gitignored, so the worktree has no interpreter and every `.venv/bin/python` verify command would fail.
- **Fix:** Symlinked the main checkout's `.venv` into the worktree. Never staged; removed before returning.
- **Files modified:** None tracked
- **Verification:** `git status --short` shows no `.venv` entry after cleanup; `git diff --stat` against the base lists only the two intended files.

**3. [Rule 1 - Clarity] Renamed `_HAM_SETS` / `_hamstring_exercise` to `_WORKING_SETS` / `_working_exercise`**
- **Found during:** Task 3
- **Issue:** The plan named these fixtures for hamstrings in Task 2, then had Task 3 reuse them for a bench-press template and a glutes-mapped template. A constant named `_HAM_SETS` used to build a chest exercise is exactly the quiet lie this codebase's commentary exists to prevent.
- **Fix:** Renamed both to muscle-agnostic names and expanded the helper docstring to say the shape is deliberately shared so a test arrangement differs only in its mapping.
- **Files modified:** `backend/tests/test_analytics_frequency.py`
- **Verification:** Ruff clean; all 12 tests pass after the rename.
- **Committed in:** `9f81b23` (Task 3 commit)

**4. [Rule 2 - Missing Critical] Explicit tenant reasoning on the new title query**
- **Found during:** Task 1
- **Issue:** The plan's `_template_titles` docstring explained the missing-template case but not why the `user_id` predicate is there. Template external ids are global for Hevy's built-in exercises, making this a genuine cross-tenant surface (T-04-02) rather than a copied predicate.
- **Fix:** Added the reasoning to the docstring, and added `test_frequency_is_scoped_to_one_user`'s same-id/different-title arrangement plus a `[row.title for row in mine.exercises] == ["Mine"]` assertion so the predicate is behaviourally proven, not just present.
- **Files modified:** `backend/app/analytics/frequency.py`, `backend/tests/test_analytics_frequency.py`
- **Verification:** The scoping test passes; removing the predicate would surface `"Theirs"`.
- **Committed in:** `55bbf22`, `9f81b23`

---

**Total deviations:** 4 auto-fixed (2 blocking, 1 clarity, 1 missing critical)
**Impact on plan:** No scope creep. Deviations 1 and 2 are environment corrections identical to every prior wave in this phase. Deviations 3 and 4 are within the plan's own files and strengthen what it asked for.

## Issues Encountered

**The plan contained two self-contradicting requirements.** Both are documented as Decisions 1 and 2 above: the supplied `get_training_frequency` docstring would have made `grep -c "snap_to_weeks=False"` return 2 against a criterion of 1, and the supplied module-docstring sentence would have made `grep -c "sum("` return 1 against a criterion of 0. Both were resolved in favour of the grep criteria, because those criteria are the structural guard the plan's own threat register (T-04-07) relies on, while the prose carries the same meaning in either wording.

**Verification that the load-bearing test is not vacuous.** Rather than trusting a green run, the implementation was mutated twice and each mutation was confirmed to fail exactly the intended test:

| Mutation | Test that failed | Message |
|---|---|---|
| `muscle_sessions = {group: 3 ...}` (the summing bug) | `test_per_muscle_sessions_dedup_within_one_workout` | `assert 3 == 1` — "per-muscle sessions were SUMMED instead of de-duplicated" |
| `muscle_sessions = {group: 1 ...}` (the naive fix) | `test_per_muscle_sessions_count_separate_workouts_separately` | `assert 1 == 3` |

The implementation was restored from a scratch copy and `git status` confirmed `frequency.py` byte-identical to its commit before Task 2 was committed.

## Verification Results

| Check | Result |
|---|---|
| `pytest backend/tests/test_analytics_frequency.py -q` | 12 passed |
| `pytest backend/tests/test_analytics_frequency.py -q -m "not integration"` | 2 passed, 10 deselected, 0.03s (no Docker needed) |
| `pytest backend/tests/test_analytics_frequency.py -q -k dedup` | 1 passed |
| `pytest backend/tests/test_analytics_frequency.py -q -k per_week` | 3 passed |
| `pytest backend/tests/test_analytics_frequency.py -q -k exercise` | 2 passed |
| `pytest backend/tests/test_analytics_isolation.py -q` | 6 passed (boundary intact with `frequency.py` present) |
| `pytest backend/tests/test_sync_state.py backend/tests/test_migrations.py -q` | 13 passed (shared container unpolluted) |
| `pytest -q` (full suite) | **335 passed** |
| `pytest -q -m "not integration"` | 198 passed, 137 deselected |
| `ruff check backend` | All checks passed |
| `mypy backend/app` | Success, 46 source files |
| Task 1 grep criteria (11) | all PASS |
| Task 2 grep criteria (6) | all PASS |
| Task 3 grep criteria (7) | all PASS |
| `pyproject.toml`, `resolver.py`, `exercise_map.py` unmodified; no migration | confirmed by `git diff --stat` against the base — only the two intended files |

## Deferred Issues

**`mypy backend` reports 44 errors across 13 test files.** This is the exact pre-existing baseline recorded in 04-03's Deferred Issues and re-confirmed in 04-05's. Zero of them are in this plan's two files (`mypy backend | grep -c "frequency"` returns 0), and `mypy backend/app` is clean. Out of scope per the executor scope boundary; the plan's `mypy backend` exit-0 criterion is not achievable without touching unrelated files.

## Requirements Status

The plan frontmatter lists `requirements: [VOL-03, DQ-01, DQ-02]`. **None were marked complete in `REQUIREMENTS.md`, deliberately**, matching plans 04-01 through 04-05.

- **VOL-03** is genuinely delivered by this plan and is ready for the orchestrator to mark.
- **DQ-01 / DQ-02** read "*Every* analytics response includes…". That is only true once the concurrent wave-3 siblings (04-06 weekly volume, 04-08 per-muscle volume) land; frequency responses carry both blocks today, but the requirement as worded is a phase-level claim.
- `REQUIREMENTS.md` is a shared artifact under concurrent modification by the other wave-3 worktree agents. Three branches editing the same checkbox lines is a merge conflict for a claim the orchestrator can make correctly, once, after the wave merges.

## Known Stubs

None. Every field of `TrainingFrequencyResult` is computed from real query output; no placeholder value, empty literal or "coming soon" string exists in either file.

## Threat Flags

None. This plan adds no network endpoint, no auth path and no schema change. The one new query surface — `_template_titles` reading `exercise_templates` — is already in the plan's threat register as T-04-02, is explicitly tenant-scoped, and is behaviourally proven scoped by `test_frequency_is_scoped_to_one_user`.

## Threat Register Coverage

| Threat ID | Disposition | Where mitigated |
|---|---|---|
| T-04-07 (inflated per-muscle frequency) | mitigated | `len(...session_ids)` only; zero occurrences of the summing builtin; both directions mutation-verified |
| T-04-02 (cross-tenant sessions or titles) | mitigated | `user_id` predicate on the aggregate, the coverage count, the muscle resolution and the title lookup; `test_frequency_is_scoped_to_one_user` proves 1 vs 3 and `"Mine"` vs `"Theirs"` |
| T-04-03 (`sync_state` internals in `freshness`) | mitigated | inherited from `build_freshness`; the freshness test asserts the dict equals exactly the two seeded timestamps |
| T-04-01 (timezone or range as SQL text) | mitigated | window built by `resolve_window`; the title lookup uses a bound `IN`; `test_analytics_uses_no_raw_sql_text` passes |
| T-04-06 (unbounded range) | mitigated | `MAX_ANALYTICS_WINDOW_DAYS` rejects before any row is materialised; the title lookup is one query, not one per template |
| T-04-05 (`ValueError` leaking user data) | mitigated | fixed literal message, asserted by `pytest.raises(..., match=...)` in the markerless suite |
| T-04-09 (a write from a read path) | mitigated | `test_analytics_never_writes` passes with `frequency.py` present |

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

**Ready.** The contract downstream consumers must honour:

- **Call `sessions_per_week` rather than re-deriving the rate.** Phase 5's CMP-01 normalizes periods of different lengths to a per-week figure; that is this function's exact job, and a second copy is how two "per week" numbers in one response would eventually disagree.
- **`sessions_per_week` raises on a zero-day window.** It is not a `None`-returning helper. Callers that can construct an empty range must validate first — `resolve_window` already guarantees `days >= 1`, which is why `get_training_frequency` never has to.
- **Never total the `.sessions` fields of `muscle_groups`.** One template maps to up to 9 muscle groups; a cross-muscle total is several times the truth and it looks plausible. This is the 4.0x inflation re-introduced at the consumer.
- **`muscle_groups` and `exercises` are independent grains, not one derivable from the other.** Three templates hitting one muscle collapse to a single muscle row by design.
- **`title is None` means the template is not synced locally**, not that the exercise has no name. `workout_exercises.exercise_template_external_id` is deliberately not a foreign key.
- **Plan 04-09 owns the phase's end-to-end and performance assertions**; this plan's tests are unit and integration only.

**Open item:** the orchestrator should mark VOL-03 complete in `REQUIREMENTS.md` and decide on DQ-01/DQ-02 once 04-06 and 04-08 have merged. See "Requirements Status".

## Self-Check: PASSED

Files verified present on disk:

- FOUND: `backend/app/analytics/frequency.py`
- FOUND: `backend/tests/test_analytics_frequency.py`
- FOUND: `.planning/phases/04-volume-frequency-analytics/04-07-SUMMARY.md`

Commits verified in `git log`:

- FOUND: `55bbf22` feat(04-07): add get_training_frequency and the pure sessions_per_week helper
- FOUND: `dfdc537` test(04-07): pin VOL-03 session de-duplication and the exact per-week rate
- FOUND: `9f81b23` test(04-07): pin VOL-03 metadata, ordering and cross-tenant scoping

No file deletions in any commit (`git diff --diff-filter=D --name-only a02e5fd HEAD` empty). `git diff --stat a02e5fd` lists exactly the two intended files. `STATE.md` and `ROADMAP.md` untouched, per worktree mode.

---
*Phase: 04-volume-frequency-analytics*
*Completed: 2026-08-30*
