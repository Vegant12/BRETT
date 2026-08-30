---
phase: 04-volume-frequency-analytics
plan: 08
subsystem: analytics
tags: [pydantic, decimal, muscle-mapping, override-semantics, query-time-weighting, postgres, testcontainers, pytest, cross-tenant, golden-fixtures]

# Dependency graph
requires:
  - phase: 04-volume-frequency-analytics
    plan: 06
    provides: "volume.py itself -- get_weekly_volume, _WeekTotals and _fold_week_totals, which this plan reuses rather than duplicates"
  - phase: 04-volume-frequency-analytics
    plan: 05
    provides: "resolve_window / weekly_set_rows / resolve_row_muscles / fold_weeks_by_muscle / MuscleBucket -- the one aggregate and the muscle fan-out"
  - phase: 04-volume-frequency-analytics
    plan: 04
    provides: "FRESHNESS_RESOURCES_MUSCLE, is_insufficient, build_coverage, build_freshness"
  - phase: 04-volume-frequency-analytics
    plan: 03
    provides: "GoldenBuilder.template(muscles=...) and GoldenBuilder.override(...), plus ANALYTICS_SECOND_USER_ID"
  - phase: 04-volume-frequency-analytics
    plan: 02
    provides: "MuscleGroupVolume / MuscleGroupVolumeWeek / MuscleGroupVolumeResult, and the static muscle-table identifier ban"
  - phase: 03-hevy-integration-normalization
    plan: n/a
    provides: "effective_muscles_bulk replacement semantics and apply_weights (NORM-02, NORM-03)"
provides:
  - "get_muscle_group_volume(session, *, user_id, start_day, end_day, weights=None) -> MuscleGroupVolumeResult -- VOL-02, the last metric this phase owed"
  - "The runtime half of the T-04-08 defence: an exercise_muscle_overrides row provably changes the per-muscle answer"
  - "backend/tests/test_analytics_volume.py: 21 test functions / 23 collected cases (was 13 / 15)"
affects: [05-progression-plateau-pr, 06-mcp-tools]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "A raw split and a weighted blend are reported side by side; neither is derivable from the other, so neither is dropped"
    - "The tuning parameter is a function argument, never a stored column, and a test asserts the un-tuned fields are invariant under it"
    - "A correctness property that is byte-identical on today's data gets TWO independent guards: one static over source, one runtime over a fixture that creates the distinguishing condition"
    - "A legitimate-looking inequality (18 per-muscle sets vs 7 hard sets) is asserted deliberately so it is recorded as intended rather than later 'fixed' into a wrong number"

key-files:
  created: []
  modified:
    - backend/app/analytics/volume.py
    - backend/tests/test_analytics_volume.py
    - .planning/REQUIREMENTS.md

key-decisions:
  - "The freshness test is written against ANALYTICS_SECOND_USER_ID rather than the default user, matching test_analytics_frequency.py: sync_state rows for the default user are the Hevy sync suite's territory and the container is session-scoped"
  - "The nested sort comprehension the plan sketched was hoisted into a named, annotated local (`in_week`); the plan explicitly permits this and it is what justifies the CanonicalMuscleGroup import the plan also mandates"
  - "REQUIREMENTS.md WAS updated this time -- unlike every prior plan in this phase -- because this is the final plan, this agent is the sole executor in the wave, and the add/add conflict every earlier plan cited cannot occur"
  - "Negative controls were run as scratchpad pytest plugins that monkeypatch at runtime, so no source file was ever mutated and no injection could survive into a commit"

patterns-established:
  - "VOL-02 reuses VOL-01's _fold_week_totals for the per-week session count rather than deriving it from the muscle buckets -- summing per-muscle session counts is the 4x inflation 04-05 measured"
  - "Whole-list equality for the primary assertion (catches a missing OR extra row) plus by-group lookups only where the fact is about one group"
  - "Every behavioural claim proven by a reverted injection that turns exactly the intended tests red and leaves the rest green"

requirements-completed: [VOL-01, VOL-02, VOL-03, DQ-01, DQ-02]

# Metrics
duration: 34min
completed: 2026-08-30
---

# Phase 4 Plan 08: Per-Muscle-Group Volume (VOL-02) Summary

**`get_muscle_group_volume` completes Phase 4's metric surface — D-04's three numbers (raw `direct_sets`, raw `indirect_sets`, blended `weighted_sets`) per muscle group per whole local week, with per-row U-03 confidence and freshness for both `workouts` and `exercise_templates` — and `test_override_changes_the_per_muscle_result` supplies the runtime proof the resolver is actually used, verified by an injection that makes it the *only* failing test out of 19.**

## Performance

- **Duration:** ~34 min
- **Tasks:** 3 of 3
- **Files modified:** 3 (2 source, 1 planning artifact); 0 created
- **Suite:** 361 → 369 passing (+8); fast suite 206 → 206 (all new cases are integration)

## Accomplishments

- **VOL-02 is delivered, and the delivery is the last one Phase 4 owed.** All three metrics (`get_weekly_volume`, `get_muscle_group_volume`, `get_training_frequency`) now exist, and all three return a result model carrying both `coverage` and `freshness` — verified programmatically, which is what makes DQ-01/DQ-02's "*every* analytics response" a true phase-level claim rather than a per-plan one.
- **The latent-defect guard is real, not asserted.** Injecting a base-only resolver — precisely what a merge-shaped `JOIN exercise_muscles` produces — turned `test_override_changes_the_per_muscle_result` red and left **all 18 other tests green**. That is the exact failure profile the plan predicted and the reason the test exists: every other VOL-02 assertion in the module passes against the wrong implementation.
- **NORM-03's query-time weighting is proven to be honoured, not merely accepted.** Custom weights of 0.8/0.3 produce the hand-computed blend, and the raw `direct_sets`/`indirect_sets` list is asserted byte-identical between the default and custom calls. An implementation that took the argument and ignored it fails on the first tuple (`Decimal('1.5')` vs `Decimal('0.9')`).
- **Pitfall 11 is recorded as intended behaviour.** The fixture's 7 hard sets fan out to 18 per-muscle set counts, and the inequality is asserted with a message explaining why — so a future reviewer reading 18-vs-7 cannot "fix" it into a wrong number.
- **D-04's rejection of the either/or framing is honoured.** The raw split and the weighted blend both ship; neither is derivable from the other once more than one role is present.
- **Zero new dependencies, zero migrations, zero deletions.** `git diff --name-only` against the base lists exactly `backend/app/analytics/volume.py`, `backend/tests/test_analytics_volume.py` and `.planning/REQUIREMENTS.md`.

## Task Commits

Each task was committed atomically:

1. **Task 1: Write get_muscle_group_volume beside get_weekly_volume** — `7db8a37` (feat)
2. **Task 2: Test the direct/indirect split, query-time weights, and the override** — `1de8ca8` (test)
3. **Task 3: Test U-03 per-row confidence, the cross-muscle inequality, freshness and scoping** — `146650d` (test)

## Files Created/Modified

- `backend/app/analytics/volume.py` (modified, 160 → 286 lines) — module docstring extended with the four VOL-02 rules (D-04's three numbers, NORM-03's query-time weighting, resolver-not-join, Pitfall 11); import block extended; `get_muscle_group_volume` appended. `get_weekly_volume`, `_WeekTotals` and `_fold_week_totals` are untouched and `_fold_week_totals` is **reused**, not duplicated.
- `backend/tests/test_analytics_volume.py` (modified, 620 → 1064 lines) — module docstring extended to name the VOL-02 load-bearing test and explain why the static ban and the runtime test are two independent mechanisms; 8 tests appended under a section banner; `_build_split_fixture`, `_bench_exercise`, `_row_exercise` and `_by_group` helpers added.
- `.planning/REQUIREMENTS.md` (modified) — VOL-01, VOL-02, VOL-03, DQ-01, DQ-02 checked off and their traceability rows moved Pending → Complete. See "Requirements Status" for why this plan wrote it when five earlier ones deliberately did not.

## Decisions Made

- **The sort comprehension became a named, annotated local.** The plan sketched a nested generator inside the `MuscleGroupVolume` comprehension and explicitly said "write it as explicit loops — the requirement is the behavior and the ordering, not the syntax". Hoisting it to `in_week: list[tuple[CanonicalMuscleGroup, MuscleBucket]]` is more readable *and* is what gives the plan-mandated `CanonicalMuscleGroup` import an actual use — otherwise Ruff `F401` would have failed the plan's own `ruff check` criterion. `MuscleBucket` was imported for the same reason. Behaviour is unchanged: still the spine, still `key=lambda pair: pair[0].value`, still `len(bucket.session_ids)`.
- **The freshness test targets the second user.** The plan does not name a user. `test_analytics_frequency.py` establishes the precedent and states the reason: `sync_state` rows for the default user belong to the Hevy sync suite, and the Postgres container is session-scoped and shared. The VOL-01 contrast assertion in the same test is therefore also made against the second user; it asserts a *key set*, so the user makes no difference to what is proven.
- **`set(volume.freshness.resources) == {RESOURCE_WORKOUTS}` rather than the plan's literal `{"workouts"}`.** The constant is already imported for the other half of the test, and asserting against the shared constant means a rename cannot leave this test asserting a dead string. No acceptance criterion depends on the literal.
- **Negative controls run as runtime monkeypatches from the scratchpad, never as source edits.** Five injections were needed. Editing `resolver.py` or `volume.py` and reverting risks an un-reverted injection reaching a commit; a `pytest -p <plugin>` fixture cannot, because nothing on disk in the repo ever changes. `git status --short` was clean of unexpected modifications at every commit boundary.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Worktree branch base was stale — sixth consecutive wave in this phase**

- **Found during:** First action (the mandated startup check)
- **Issue:** `git rev-parse HEAD` returned `1e97f3be` and `git merge-base HEAD 4295910` returned the same value — i.e. HEAD was an *ancestor* of the required base, not equal to it. The worktree had branched from `chore(02-05): record auto-chain flag`, before Phase 4 existed at all. `backend/app/analytics/` in its entirety, the `golden_workout` fixture and `04-08-PLAN.md` itself were all absent. Plans 04-02, 04-04, 04-05, 04-06 and 04-07 each recorded the identical correction.
- **Fix:** `git reset --hard 4295910` per the startup check, verified at `4295910` before any other action. The worktree was clean, so nothing was lost.
- **Files modified:** none
- **Verification:** `git rev-parse HEAD` → `42959101168bbb7856fd5ef9f08afd0114ea04ae`; wave-3 output (`get_weekly_volume`, `get_training_frequency`) present and importable.
- **Committed in:** n/a

**2. [Rule 3 - Blocking] No `.venv` in the worktree**

- **Found during:** Pre-Task 1 setup
- **Issue:** Every `<verify>` and acceptance command in the plan is written against `.venv/bin/python`, and a fresh worktree has none. As plan 04-06 recorded, `.gitignore` line 6 is `.venv/` **with a trailing slash**, which matches a directory only — a symlink named `.venv` shows as untracked.
- **Fix:** Symlinked the main checkout's `.venv` into the worktree root, as plans 04-02 and 04-04 through 04-07 did. `pyproject.toml` sets `pythonpath = ["backend"]`, so `app` and `tests` resolve against the *worktree's* sources — confirmed by the RED check, which reported `cannot import name 'get_muscle_group_volume'` before Task 1. Every commit staged named files explicitly (never `git add .` / `-A`), and the symlink is removed before returning.
- **Files modified:** none tracked
- **Verification:** `git status --short` showed only the intended file plus `?? .venv` at every commit boundary; `git diff --name-only 4295910 HEAD` lists exactly three paths.
- **Committed in:** n/a

**3. [Rule 2 - Missing Critical] The plan's mandated import block would have failed the plan's own `ruff check` criterion**

- **Found during:** Task 1
- **Issue:** The plan mandates `from app.normalization.muscles import CanonicalMuscleGroup, MuscleRole` **and** an acceptance criterion of `ruff check backend/app/analytics/volume.py` exiting 0. In the plan's own sketched function body, `MuscleRole` is used (the `weights` annotation) but `CanonicalMuscleGroup` never is — the sort is a bare comprehension with an inferred type. Ruff `F401` (`F` is in the enabled rule set) would have flagged it as an unused import. This is the sixth variant of "the plan's prose and the plan's greps disagree" recorded in this phase.
- **Fix:** Hoisted the sort into an explicitly annotated local, `in_week: list[tuple[CanonicalMuscleGroup, MuscleBucket]]`, which the plan expressly permits ("write it as explicit loops"). This uses the mandated import for its stated purpose rather than deleting it, and additionally documents the intermediate's shape. `MuscleBucket` was added to the `rollup` import for the same annotation.
- **Files modified:** `backend/app/analytics/volume.py`
- **Verification:** `ruff check backend/app/analytics/volume.py` → All checks passed; `mypy backend/app` → clean across 47 source files; all 12 Task-1 grep criteria still satisfied, including `key=lambda pair: pair[0].value` ≥ 1 and `snap_to_weeks=True` == 2.
- **Committed in:** `7db8a37`

**4. [Rule 2 - Missing Critical] `requirements mark-complete` leaves the traceability table stale**

- **Found during:** Post-execution
- **Issue:** `gsd-tools requirements mark-complete VOL-01 VOL-02 VOL-03 DQ-01 DQ-02` reported `{"updated": true, "total": 5}` and flipped the five `- [ ]` checkboxes, but left all five rows of the **Traceability** table at the bottom of the file reading `Pending`. Phases 1 and 2 record `Complete` in that column, so the file would have been internally inconsistent and any reader trusting the table would conclude Phase 4 had shipped nothing.
- **Fix:** Edited the five traceability rows Pending → Complete by hand, and refreshed the file's "Last updated" footer, which still read `2026-08-23 after roadmap creation`.
- **Files modified:** `.planning/REQUIREMENTS.md`
- **Verification:** `git diff .planning/REQUIREMENTS.md` shows exactly 5 checkbox flips, 5 table-cell flips and 1 footer line; no other requirement's status changed.
- **Committed in:** the metadata commit

---

**Total deviations:** 4 auto-fixed (2 worktree-environment blockers, 1 internal contradiction in the plan document, 1 tooling gap). None required a checkpoint.
**Impact on plan:** No scope creep and no functional drift. Every function name, signature, docstring rule, test name, expected value and assertion message is as specified. `pyproject.toml` is unmodified, zero dependencies were added, no migration was created, and `resolver.py` / `exercise_map.py` / `rollup.py` / `metadata.py` / `schemas.py` are all untouched.

## TDD Gate Compliance

All three tasks carry `tdd="true"`, and the plan orders implementation (Task 1) before its tests (Tasks 2–3) — the same inversion plans 04-02, 04-04 and 04-06 recorded.

- **RED gate:** confirmed before Task 1 that `from app.analytics.volume import get_muscle_group_volume` raised `ImportError: cannot import name 'get_muscle_group_volume'`, against a baseline of 206 fast / 361 total at the base commit. For Tasks 2 and 3 the red phase was run as five separate runtime injections (table below), each turning exactly the intended tests red and nothing else.
- **GREEN gate:** `7db8a37` (`feat`) is the implementation; `1de8ca8` and `146650d` (`test`) constrain it. Every task's `<verify>` block passed before its commit.
- **REFACTOR gate:** not needed beyond `ruff format`, which reformatted each file once on first write and reported clean thereafter.
- **Gate commits:** a `feat(...)` commit exists and two `test(...)` commits follow it. The standard RED→GREEN commit ordering is inverted because the plan's task order is, not because a gate was skipped.

## Verification Evidence

### Plan `<verification>` block — 8 of 8

| # | Check | Result |
|---|-------|--------|
| 1 | `pytest backend/tests/test_analytics_volume.py -q` | **23 passed** in 2.91s (13 → 21 test functions, 15 → 23 cases) |
| 2 | `pytest backend/tests/test_analytics_isolation.py -q` | **6 passed** — all six boundary guards green with the new code present, including the muscle-table identifier ban |
| 3 | `pytest test_migrations.py test_sync_state.py test_normalization_mapping.py -q` | **25 passed** — shared container unpolluted, no fixture-id collisions |
| 4 | `pytest -q -m "not integration"` | **206 passed**, 163 deselected in 0.84s (baseline 206; every new case is integration-marked) |
| 5 | `pytest -q` (full suite) | **369 passed** in 9.95s (baseline 361; +8) |
| 6 | `ruff check backend` / `mypy backend` | **All checks passed** / 44 pre-existing errors in 13 test files, **0 from this plan** — see Deferred Issues. `mypy backend/app` → clean, 47 source files |
| 7 | `pyproject.toml` unmodified; `resolver.py` / `exercise_map.py` untouched; no migration | `git diff --name-only 4295910 HEAD` → exactly the three intended paths; `backend/migrations/versions/` unchanged; zero deletions (`--diff-filter=D` empty on every commit) |
| 8 | Every phase requirement exercised | `get_weekly_volume` (VOL-01), `get_muscle_group_volume` (VOL-02) and `get_training_frequency` (VOL-03) all exist and all three result models carry `coverage` **and** `freshness` (DQ-01/DQ-02) — asserted programmatically, output in Requirements Status below |

### Negative controls — each proven red, then discarded

Run as scratchpad `pytest -p <plugin>` fixtures that monkeypatch at runtime. No repository file was modified by any of them.

| Injection | Result |
|---|---|
| Resolver returns the BASE mapping only, discarding overrides (what a merge-shaped `JOIN exercise_muscles` produces) | **`test_override_changes_the_per_muscle_result` red, all 18 others green.** Diff: `At index 2 ... FRONT_DELTS != UPPER_BACK; Left contains 2 more items, first extra item: TRICEPS`. Exactly the blind spot the plan names |
| `fold_weeks_by_muscle` called with `None` instead of the caller's `weights` | **`test_custom_weights_change_weighted_sets_only` red**, 18 green. Diff: `(BICEPS, Decimal('1.5')) != (BICEPS, Decimal('0.9'))` |
| `FRESHNESS_RESOURCES_MUSCLE` swapped for `FRESHNESS_RESOURCES_WORKOUTS` | **`test_muscle_group_volume_carries_both_freshness_resources` red**, 22 green |
| Per-muscle `session_ids` inflated to one id per row (counting rows, not distinct workouts) | **`test_per_muscle_rows_carry_their_own_sessions_and_insufficient_data` and `test_muscle_group_volume_is_scoped_to_one_user` red**, 21 green |
| The tenant id never reaches the aggregate (`weekly_set_rows` always called with the second user) | **`test_muscle_group_volume_is_scoped_to_one_user` red** (`At index 0 diff: 3 != 1`), and `test_weekly_volume_is_scoped_to_one_user` red alongside it, since both metrics share the aggregate |

### Task 1 acceptance criteria — 12 of 12

| Criterion | Required | Actual |
|---|---|---|
| `^async def get_muscle_group_volume` | 1 | 1 |
| `^async def get_weekly_volume` (04-06 intact) | 1 | 1 |
| `^def _fold_week_totals` (reused, not duplicated) | 1 | 1 |
| `resolve_row_muscles(` | 1 | 1 |
| `fold_weeks_by_muscle(` | 1 | 1 |
| `FRESHNESS_RESOURCES_MUSCLE` | ≥1 | 2 |
| `FRESHNESS_RESOURCES_WORKOUTS` | ≥1 | 2 |
| `key=lambda pair: pair[0].value` / `muscle_group.value` | ≥1 | 1 |
| `len(bucket.session_ids)` | ≥2 | 2 |
| `snap_to_weeks=True` | 2 | 2 |
| `ExerciseMuscle\|exercise_type\|text(\|session.commit\|session.flush\|session.add(` | 0 | 0 |
| `Decimal("1.0")\|Decimal("0.5")` | 0 | 0 |
| signature probe / `test_analytics_isolation.py` / `ruff` / `mypy` | OK / 0 / 0 / 0 | `OK` / 6 passed / clean / clean |

### Task 2 acceptance criteria — 11 of 11

| Criterion | Required | Actual |
|---|---|---|
| module collects and passes | exit 0, 19 collected | **19 passed** |
| `-k muscle_split` / `-k custom_weights` / `-k override` | 1 each | 1 each (18 deselected each) |
| `Decimal("1.5")` | ≥1 | 1 |
| `Decimal("3.2")` / `Decimal("0.9")` | 1 / 1 | 1 / 1 |
| `effective_muscles_bulk` | ≥1 | 1 |
| `muscle_groups == []` | ≥1 | 1 |
| `golden_workout.override(` | 1 | 1 |
| `ruff check` on the test module | 0 | clean |

### Task 3 acceptance criteria — 11 of 11

| Criterion | Required | Actual |
|---|---|---|
| module collects and passes | exit 0, 23 collected | **23 passed** |
| `grep -c "def test_"` | 21 | 21 |
| `cross_muscle_total == 18` | 1 | 1 |
| `hard_sets == 7` | ≥1 | 1 |
| `ASVS V4 violated` | 2 | 2 |
| `_SYNCED_TEMPLATES_AT` | ≥2 | 3 |
| `result.coverage.insufficient_data is False` | ≥1 | 1 |
| `pytest -q` (full suite) | exit 0 | **369 passed** |
| `pytest -q -m "not integration"` | exit 0 | **206 passed** |
| `test_migrations.py test_sync_state.py` afterwards | exit 0 | **25 passed** (with `test_normalization_mapping.py`) |
| `ruff check backend` / `mypy backend` | 0 / 0 | clean / 44 pre-existing (0 new) — see Deferred Issues |

### Behavioural results observed against the container

Fixture: `VOL-BENCH` → (chest direct, triceps indirect, front_delts indirect) with 4 sets at 60 kg × 10; `VOL-ROW` → (upper_back direct, biceps indirect) with 3 sets at 50 kg × 12; one workout, Monday 2026-08-24.

| Query | Observed |
|---|---|
| default weights | `biceps (0,3,1.5)`, `chest (4,0,4.0)`, `front_delts (0,4,2.0)`, `triceps (0,4,2.0)`, `upper_back (3,0,3.0)`; `week.sessions == 1` |
| `weights={DIRECT: 0.8, INDIRECT: 0.3}` | `biceps 0.9`, `chest 3.2`, `front_delts 1.2`, `triceps 1.2`, `upper_back 2.4`; raw `(direct, indirect)` list byte-identical to the default call |
| after `override(VOL-BENCH, [(CHEST, DIRECT)])` | groups collapse to `[biceps, chest, upper_back]`; `chest.direct_sets` still 4; triceps and front_delts gone |
| a template with no mapping at all | `week.sessions == 1`, `muscle_groups == []`, nothing raised |
| BENCH+ROW Monday, ROW-only Wednesday | `upper_back (2, False)`, `chest (1, True)`, `week.sessions == 2`, `coverage.insufficient_data is False` |
| cross-muscle sum vs the same week's VOL-01 | 18 vs `hard_sets == 7` — asserted as intended, not a defect |
| two seeded `sync_state` rows 25 min apart | `{workouts: 05:43:18Z, exercise_templates: 06:08:04Z}`, two distinct values; the same window's `get_weekly_volume` reports `{workouts}` only |
| 3 second-user workouts + 1 default-user workout, same template external id | default user chest `(1, 4)`, second user chest `(3, 12)` |

## Threat Model Disposition

| Threat ID | Disposition | Status after this plan |
|-----------|-------------|------------------------|
| T-04-08 | mitigate | **Done, and this plan is the half that was missing.** Both mechanisms are now live: the static identifier ban (04-02, covers `volume.py` automatically via `rglob`) and `test_override_changes_the_per_muscle_result`. The runtime half was verified *necessary* — with a base-only resolver injected it is the sole failure out of 19. |
| T-04-02 | mitigate | **Done, non-vacuously.** `user_id` is keyword-only with no default and threaded into `resolve_window`, `weekly_set_rows`, `resolve_row_muscles`, `build_coverage` and `build_freshness`. `test_muscle_group_volume_is_scoped_to_one_user` builds the SAME template external id for two users and asserts `(1, 4)` against `(3, 12)`; it goes red when the tenant id is withheld from the aggregate. |
| T-04-03 | mitigate | **Inherited and re-asserted.** `test_muscle_group_volume_carries_both_freshness_resources` pins `result.freshness.resources` to an exact two-key dict, so an extra key or a leaked `last_error` / `status` / cursor field fails here. |
| T-04-07 | mitigate | **Done on all three counts.** Sessions come from a de-duplicated set (inflating it turns two tests red); the raw split is asserted invariant under a weighting change; the 18-vs-7 inequality is asserted deliberately with an explanatory message. |
| T-04-01 | mitigate | **Inherited, unchanged.** The window is built by `rollup.build_window` (validates the tz, rejects inverted and over-long ranges). `volume.py` contains zero `text(` in any spelling; `test_analytics_uses_no_raw_sql_text` covers the file by `rglob`. |
| T-04-06 | mitigate | **Inherited, unchanged.** `MAX_ANALYTICS_WINDOW_DAYS = 1830` fires before any row is materialised, bounding the spine at ~262 weeks; the muscle axis is bounded at 19 by the `CanonicalMuscleGroup` enum. |
| T-04-09 | mitigate | **Done.** Zero `session.commit/flush/add` and no write-construct import in `volume.py`; `test_analytics_never_writes` (04-02) covers it statically. |

## Threat Flags

None. This plan adds no network endpoint, no auth path, no file access and no schema change. The only new user-controlled value reaching the analytics tier is the `weights` mapping, which is keyed by a `MuscleRole` enum and multiplied into a `Decimal` — it never reaches SQL.

## Known Stubs

None. Every field of `MuscleGroupVolumeResult` is computed from real query output against a live Postgres container. No placeholder value, empty literal or "coming soon" string exists in either source file.

## Requirements Status

The plan frontmatter carries `requirements: [VOL-02, DQ-01, DQ-02]`. **`.planning/REQUIREMENTS.md` was updated this time** — the first plan in this phase to do so — and five requirements were marked complete, not three.

| Requirement | Satisfied? | Evidence |
|---|---|---|
| **VOL-02** | **Yes, by this plan.** | `get_muscle_group_volume` returns the raw direct/indirect split *and* the weighted blend per muscle per week, proven against hand-computed golden fixtures and against an override. |
| **VOL-01** | **Yes, by plan 04-06.** | `04-06-SUMMARY.md` records `requirements-completed: [VOL-01, DQ-01, DQ-02]` and 15 passing cases; its "Action for the orchestrator" asks for exactly this check-off. |
| **VOL-03** | **Yes, by plan 04-07.** | `04-07-SUMMARY.md` states "VOL-03 is genuinely delivered by this plan and is ready for the orchestrator to mark". |
| **DQ-01** | **Yes, now phase-wide.** | The requirement reads "*Every* analytics response includes freshness metadata". 04-07 correctly declined to claim it because that is a phase-level statement its own plan could not make alone. It is now verifiable: all three of `WeeklyVolumeResult`, `MuscleGroupVolumeResult` and `TrainingFrequencyResult` declare a `freshness` field, and each is asserted against seeded `sync_state` rows in its own test module. |
| **DQ-02** | **Yes, now phase-wide.** | Same argument for `coverage`. All three result models declare it; the D-05 threshold is pinned on both sides through the public functions. |

**Why this plan wrote the file when five earlier ones deliberately did not.** Plans 04-01 through 04-07 each cited the same concrete reason: `REQUIREMENTS.md` is a shared artifact and multiple worktree agents in the same wave carried overlapping requirement IDs, so three branches editing the same checkbox lines would be an add/add merge conflict. That condition does not hold here — this is the final plan of the phase, wave 4 contains **one** executor, and the executing prompt explicitly authorised the write once the IDs were confirmed genuinely and fully satisfied across the whole phase. The verification above is that confirmation.

**Note for the orchestrator:** the change is two-part, because `gsd-tools requirements mark-complete` only flips checkboxes. The five **Traceability** table rows were moved `Pending` → `Complete` by hand (Deviation 4). If the orchestrator re-runs `mark-complete` centrally it will be a no-op (`already_complete`), which is safe.

## Deferred Issues

Recorded here rather than in a phase-level `deferred-items.md`, consistent with the rest of this phase.

1. **44 pre-existing `mypy backend` errors across 13 test files.** Task 3's criterion asks `mypy backend` to exit 0; it did not before this plan either, and plans 04-03 through 04-07 each measured the identical 44/13. The meaningful property holds: `mypy backend | grep -c "test_analytics_volume.py\|analytics/volume.py"` → **0**, and `mypy backend/app` is clean across 47 source files. Out of scope under the executor's scope-boundary rule.
2. **Pre-existing `ruff format --check` failures outside `app/analytics/`.** Unchanged from 04-06's list. Both files this plan touched report "already formatted". Worth a standalone `ruff format backend` cleanup commit.
3. **Worktree base drift, sixth consecutive wave in this phase.** Every wave in Phase 4 has recorded the same correction. This is a worktree-provisioning defect, not something each agent should keep absorbing: an agent that skipped the mandated startup check would have branched from a pre-Phase-4 tree and produced a `volume.py` that overwrote nothing while importing modules that do not exist.
4. **`.gitignore` line 6 is `.venv/`, which does not match a symlink named `.venv`.** Flagged by 04-06 and still open. Changing the entry to `.venv` (no trailing slash) closes it permanently.
5. **`gsd-tools requirements mark-complete` does not update the Traceability table.** Deviation 4. Worth fixing in the tool, since the table is what a human reads to judge phase progress and it silently disagreed with the checkboxes directly above it.

## Issues Encountered

- **The plan's mandated import block would have failed the plan's own `ruff check` criterion** (Deviation 3) — `CanonicalMuscleGroup` is mandated but unused in the sketched body. This is the sixth instance in Phase 4 of the plan document contradicting its own acceptance criteria; the earlier five were grep-versus-prose collisions, this one is a lint rule versus a mandated import. Worth generalising: plans in this project should run their own greps and lints against their sketched code before they ship.
- **No debugging cycle was needed otherwise.** `get_muscle_group_volume` was green on first execution and every one of the 8 new tests passed on its first run, against the hand-computed values transcribed straight from the plan's `expected_values` block — including all five `weighted_sets` figures under both weightings.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

**Ready. Phase 4 is functionally complete**: all 9 plans have landed, all five phase requirements are satisfied, and the suite is at 369 passing with `ruff check backend` clean and `mypy backend/app` clean.

What Phase 5 and Phase 6 should know:

- **The composition is now proven three times over** and is the template for every remaining metric: `resolve_window` → `weekly_set_rows` **once** → pure fold → project onto `local_week_spine` → `build_coverage` + `build_freshness`.
- **Never sum per-week `sessions` to get a window total** (the 4x inflation 04-05 measured). Re-fold from the same rows with `fold_window_by_muscle`.
- **`tonnage_kg is None` is not zero**, and `total_reps is None` is not zero. Both distinctions are load-bearing and each has a test that exists solely to preserve it.
- **Any new analytics module gets the six static boundary guards for free** (`test_analytics_isolation.py` walks `app/analytics/` with `rglob`) — including the muscle-table identifier ban. Prose in that package must refer to tables in lowercase, never by ORM class name, or the ban fires on the documentation.
- **Test-module constants now taken in `test_analytics_volume.py`:** everything 04-06 listed, plus `_BENCH_MUSCLES`, `_ROW_MUSCLES`, `_BARE`, `_FIFTY`, `_CUSTOM_WEIGHTS`, `_SYNCED_WORKOUTS_AT`, `_SYNCED_TEMPLATES_AT`, and the helpers `_build_split_fixture`, `_bench_exercise`, `_row_exercise`, `_by_group`.
- **Phase 6's `fitness_get_muscle_group_volume` tool** can call `get_muscle_group_volume` directly with no adapter: it already returns a Pydantic `BaseModel`, which MCP SDK v2 turns into an `outputSchema` and `structured_content` for free.

**Open item:** none blocking.

## Self-Check: PASSED

Files verified present on disk:

- FOUND: `backend/app/analytics/volume.py`
- FOUND: `backend/tests/test_analytics_volume.py`
- FOUND: `.planning/REQUIREMENTS.md`
- FOUND: `.planning/phases/04-volume-frequency-analytics/04-08-SUMMARY.md`

Commits verified in `git log`:

- FOUND: `7db8a37` feat(04-08): add get_muscle_group_volume beside get_weekly_volume (VOL-02)
- FOUND: `1de8ca8` test(04-08): pin the VOL-02 split, query-time weights and the override proof
- FOUND: `146650d` test(04-08): pin U-03 per-row confidence, Pitfall 11, freshness and VOL-02 scoping

No file deletions in any commit (`git diff --diff-filter=D --name-only 4295910 HEAD` empty). No untracked files left behind other than the removed `.venv` symlink. `STATE.md` and `ROADMAP.md` were **not** modified — the orchestrator owns those writes. `.planning/REQUIREMENTS.md` **was** modified, deliberately and with explicit authorisation; see Requirements Status.

---
*Phase: 04-volume-frequency-analytics*
*Completed: 2026-08-30*
