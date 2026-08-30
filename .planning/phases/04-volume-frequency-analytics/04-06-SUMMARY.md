---
phase: 04-volume-frequency-analytics
plan: 06
subsystem: analytics
tags: [pydantic, decimal, timezone, postgres, testcontainers, pytest, cross-tenant, golden-fixtures]

# Dependency graph
requires:
  - phase: 04-volume-frequency-analytics
    plan: 05
    provides: "resolve_window / AnalyticsWindow (with snap_to_weeks), SetRollupRow, weekly_set_rows -- the one indexed aggregate and its window guards"
  - phase: 04-volume-frequency-analytics
    plan: 04
    provides: "build_coverage / build_freshness / FRESHNESS_RESOURCES_WORKOUTS -- the DQ-01/DQ-02 envelope builders"
  - phase: 04-volume-frequency-analytics
    plan: 02
    provides: "WeeklyVolumeWeek / WeeklyVolumeResult in analytics/schemas.py, and the six static boundary assertions in test_analytics_isolation.py"
  - phase: 04-volume-frequency-analytics
    plan: 03
    provides: "golden_workout / GoldenBuilder / GoldenSet / GoldenExercise / ANALYTICS_SECOND_USER_ID"
  - phase: 04-volume-frequency-analytics
    plan: 01
    provides: "local_week_spine and snap_local_week_range in app/core/time.py"
provides:
  - "get_weekly_volume(session, *, user_id, start_day, end_day) -> WeeklyVolumeResult -- VOL-01, the first requirement this phase actually delivers"
  - "_fold_week_totals + _WeekTotals: the pure, container-free per-week accumulator"
  - "The composition every remaining Phase 4 metric copies: resolve window -> one aggregate -> pure fold -> project onto the spine -> attach coverage and freshness"
  - "backend/tests/test_analytics_volume.py: 13 test functions / 15 collected cases, the module 04-08 extends with VOL-02"
affects: [04-08, 04-09, 05-progression-plateau-pr, 06-mcp-tools]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Metric functions are pure composition: every guard, query and envelope builder already exists, and the metric owns only the fold and the spine projection"
    - "The result list is driven by an enumerated spine, never by the keys the fold happened to produce"
    - "A None-versus-zero distinction is carried by a paired count field rather than inferred from the magnitude"
    - "Every behavioural assertion is proven red by a reverted injection before its commit"

key-files:
  created:
    - backend/app/analytics/volume.py
    - backend/tests/test_analytics_volume.py
  modified: []

key-decisions:
  - "The spine loop is an explicit for/append rather than the plan's double-for comprehension: the plan permits either and the loop constructs WeeklyVolumeWeek exactly once, so the zero-week and trained-week branches cannot drift"
  - "No structlog line was emitted. The plan makes it conditional and both sibling analytics modules (rollup.py, metadata.py) log nothing; a per-call analytics log is noise, and T-04-04's 'at most one event' is satisfied by zero"
  - "The plan's mandated assertion prose split 'diagnostically interesting' across two source lines under ruff format, failing the plan's own grep criterion -- the implicit concatenation was reflowed rather than the sentence changed"
  - "REQUIREMENTS.md deliberately not written: two other wave-3 agents (04-07, 04-09) carry the same requirement IDs concurrently"

patterns-established:
  - "VOL-01's shape is the template for VOL-02 and VOL-03: resolve_window -> weekly_set_rows ONCE -> pure fold -> local_week_spine projection -> build_coverage + build_freshness"
  - "Freshness tuple selected by what the answer actually depends on, asserted as an exact key set so a per-muscle answer cannot inherit a workout-only claim"
  - "Boundary tables transcribed from test_time.py into each consuming module, so the pinned instants cannot drift between the helper and its callers"

requirements-completed: [VOL-01, DQ-01, DQ-02]

# Metrics
duration: 17min
completed: 2026-08-30
---

# Phase 4 Plan 06: Weekly Volume (VOL-01) Summary

**`get_weekly_volume` ships the phase's first real number — hard sets, reps and modality-aware tonnage per whole local Monday-start week, with the DQ-01/DQ-02 envelope attached — and 15 golden-fixture cases pin every rule that would otherwise produce a plausible-looking wrong figure: warm-up exclusion, dropset inclusion, `tonnage_kg is None` versus `Decimal("0.000")`, the Jakarta 17:00Z week boundary, the outward window snap, the gap-free spine, and cross-tenant scoping.**

## Performance

- **Duration:** ~17 min
- **Started:** 2026-08-30T17:27+07:00
- **Completed:** 2026-08-30T17:44+07:00
- **Tasks:** 3 of 3
- **Files created:** 2 (no existing file modified)

## Accomplishments

- **VOL-01 is delivered, not just scaffolded.** `get_weekly_volume` returns real `WeeklyVolumeWeek` rows computed from real workouts through the real aggregate, against a live Postgres container. This is the first requirement in Phase 4 where a number comes out the far end.
- **The load-bearing distinction is proven, not asserted.** `tonnage_kg is None` for a bodyweight week and `Decimal("0.000")` for a zero-load set were each verified against the container, and the difference was proven detectable: coercing the absent sum to a confident zero turns `test_modality_without_operands_reports_tonnage_none` and `test_duration_only_sets_count_as_hard_sets` red and leaves all 13 other cases green — exactly the failure profile the plan predicted.
- **The gap-free spine is structural and proven.** Replacing `local_week_spine(...)` with `sorted(folded)` fails 4 cases, including all three parametrized boundary rows, because the untrained candidate week vanishes instead of reporting a zero.
- **The Jakarta boundary is pinned against the transcribed `test_time.py` table and against the database column.** A workout at 16:30Z buckets to the 2026-08-17 week; at 17:00Z (exact Jakarta midnight) and 23:30Z it buckets to 2026-08-24. Flipping `users.timezone` to `America/New_York` moves the same 17:00Z instant back to 2026-08-17 — so the zone is demonstrably read from the column rather than defaulted.
- **Cross-tenant scoping is proven non-vacuously.** Three workouts for `ANALYTICS_SECOND_USER_ID` and one for `DEFAULT_USER_ID` in the same local week; the default user reports 1 session / 3 hard sets and the second reports 3 / 9. Removing `Workout.user_id == user_id` from `weekly_set_rows` turns exactly that test red.
- **Suite grew 323 -> 338 with zero regressions**, and `mypy backend/app` stays clean at 46 source files.

## Task Commits

Each task was committed atomically:

1. **Task 1: Write get_weekly_volume and the pure _fold_week_totals helper** — `89796e8` (feat)
2. **Task 2: Golden-fixture tests for VOL-01 — warmup, dropset, modality, zero_load, superset** — `7348f24` (test)
3. **Task 3: Test the week boundary, outward snap, gap-free spine, metadata and cross-tenant scoping** — `311641f` (test)

## Files Created/Modified

- `backend/app/analytics/volume.py` (created, 160 lines) — module docstring stating all five counter-intuitive rules with their measured consequences; `_WeekTotals`; `_fold_week_totals`; `get_weekly_volume`. Composition only: no SQL, no `text(`, no writes, no muscle-table identifiers, no binary floating point.
- `backend/tests/test_analytics_volume.py` (created, 620 lines) — 13 test functions, 15 collected cases. Twelve carry `@pytest.mark.integration`; `test_fold_week_totals_keeps_total_reps_none_when_no_row_reports_reps` deliberately does not, so the None-versus-zero rule stays verifiable with Docker down.

Nothing else in the repository changed. `git diff --name-only` against the base commit lists exactly those two paths.

## Decisions Made

- **The spine projection is an explicit loop, not the plan's double-`for` comprehension.** The plan states the requirement is the behaviour, not the syntax. The loop constructs `WeeklyVolumeWeek` exactly once — a zero week and a trained week go through the same constructor call with `totals` defaulted to a fresh `_WeekTotals()` — so the two branches cannot drift apart, and there is no shared mutable default.
- **No log line.** The plan makes structlog conditional ("only if you emit a line"). `rollup.py` and `metadata.py` both log nothing, and a log event per analytics call is noise on a read path that a Phase 6 tool may invoke several times per conversation. T-04-04's mitigation is "at most one event carrying counts only"; zero satisfies it, and there is no `str(exc)` or row content anywhere in the module.
- **`freshness` is asserted as an exact key set, not a superset.** `set(result.freshness.resources) == {"workouts"}` rather than `"workouts" in ...`. VOL-01 never resolves a muscle map, so `exercise_templates` staleness cannot move any number here — and plan 04-08's per-muscle answer must be forced to ask for the other tuple rather than inheriting this one.
- **The superset test compares two users rather than two windows.** Building the non-superset arrangement under `ANALYTICS_SECOND_USER_ID` (as the plan specifies) keeps both fixtures in the same week and the same session, so the equality is between two `WeeklyVolumeWeek` objects that differ in nothing but `supersets_id`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Worktree branch base was stale — fifth consecutive wave in this phase**

- **Found during:** First action (the mandated startup check)
- **Issue:** `git merge-base HEAD a02e5fdd` returned `1e97f3be`, i.e. HEAD was an *ancestor* of the required base. The worktree had branched from `chore(02-05): record auto-chain flag`, before Phase 4 planning existed and before both wave-1 and wave-2 output. `backend/app/analytics/rollup.py`, `metadata.py`, `schemas.py`, the `golden_workout` fixture and `04-06-PLAN.md` itself were all absent. Plans 04-04 and 04-05 each recorded the identical correction.
- **Fix:** `git reset --hard a02e5fdd77852059718289bc5cf2aeed6b7a8d81` per the startup check, verified at `a02e5fd` before any work began. The worktree was clean, so nothing was lost.
- **Files modified:** none
- **Verification:** `git log --oneline -1` → `a02e5fd docs(phase-04): update tracking after wave 2`; all wave-2 artifacts present and importable.
- **Committed in:** n/a

**2. [Rule 3 - Blocking] No `.venv` in the worktree, and `.gitignore` does not hide a symlink to one**

- **Found during:** Pre-Task 1 setup
- **Issue:** Every verify and acceptance command in the plan is written against `.venv/bin/python`, and a fresh worktree has none. Additionally, `.gitignore` line 6 is `.venv/` **with a trailing slash**, which matches a directory only — a symlink named `.venv` shows up as untracked in `git status`, so it is one careless `git add .` away from being committed.
- **Fix:** Symlinked the main checkout's `.venv` into the worktree root, as plans 04-02, 04-04 and 04-05 did. `pyproject.toml` sets `pythonpath = ["backend"]`, so `app` and `tests` resolve against the *worktree's* sources — confirmed by the RED check, which reported `No module named 'app.analytics.volume'` before Task 1. Every commit staged named files explicitly (never `git add .`/`-A`), and the symlink was removed before returning.
- **Files modified:** none tracked
- **Verification:** `git status --short` showed only the intended file plus `?? .venv` at every commit boundary; `git diff --name-only <base> HEAD` lists exactly two paths.
- **Committed in:** n/a

**3. [Rule 1 - Bug] The plan's mandated assertion prose fails the plan's own grep criterion once formatted**

- **Found during:** Task 3
- **Issue:** The plan mandates the assertion message *"a zero-training week vanished from the result — that is the most diagnostically interesting week Claude could have seen"* **and** the acceptance criterion `grep -c "diagnostically interesting"` → 1. Written naturally inside a 100-column implicit string concatenation, the wrap lands between the two words (`...the most diagnostically "` / `"interesting week Claude...`), and `grep -c` returned **0**. This is the same substring-versus-intent trap plans 04-01, 04-02, 04-04 and 04-05 each recorded, in a new form: line wrapping rather than prose collision.
- **Fix:** Reflowed the implicit concatenation so the phrase sits on one line (`"...that is the most "` / `"diagnostically interesting week Claude could have seen"`). The sentence the plan specified is byte-identical; only the split point moved.
- **Files modified:** `backend/tests/test_analytics_volume.py`
- **Verification:** `grep -c "diagnostically interesting"` → 1; `ruff format --check` reports the file already formatted; the test still passes and still fails under the spine injection.
- **Committed in:** `311641f`

**4. [Rule 2 - Missing Critical] Requirement IDs recorded here rather than written to the shared file**

- **Found during:** Post-execution
- **Issue:** This plan genuinely completes VOL-01 and genuinely puts the DQ-01/DQ-02 envelope on a real response, so unlike plans 04-01..04-05 the check-off would be *honest*. But `.planning/REQUIREMENTS.md` is a shared artifact under concurrent modification: plan **04-07 carries `[VOL-03, DQ-01, DQ-02]`** and plan **04-09 carries `[VOL-01, VOL-02, VOL-03]`**, both in this same wave 3. Three agents writing the same checkbox lines is an add/add merge conflict, and this executor is instructed not to write shared orchestrator artifacts from a worktree.
- **Fix:** `REQUIREMENTS.md` left untouched; `requirements-completed: [VOL-01, DQ-01, DQ-02]` recorded in this summary's frontmatter for the orchestrator to apply centrally after the wave merges.
- **Files modified:** none (the correction is the absence of a write)
- **Verification:** `git diff --name-only` against base lists only the two source paths.
- **Committed in:** n/a

---

**Total deviations:** 4 auto-fixed (2 worktree-environment blockers, 1 internal contradiction in the plan document, 1 false-conflict prevented)
**Impact on plan:** No scope creep and no functional drift. Every function name, signature, docstring rule, test name, expected value and assertion message is exactly as specified; deviation 3 moved a line break and nothing else. `pyproject.toml` is unmodified, zero dependencies were added, no migration was created, and `resolver.py` / `exercise_map.py` are untouched.

## TDD Gate Compliance

All three tasks carry `tdd="true"`, and the plan orders implementation (Task 1) before its tests (Tasks 2–3) — the same inversion plans 04-02 and 04-04 recorded.

- **RED gate:** confirmed before Task 1 that `import app.analytics.volume` raised `ModuleNotFoundError: No module named 'app.analytics.volume'`, with a full-suite baseline of 196 fast / 323 total at the base commit. For Tasks 2 and 3 the red phase was run as three separate reverted injections (table below), each turning exactly the intended tests red.
- **GREEN gate:** `89796e8` (`feat`) is the implementation; `7348f24` and `311641f` (`test`) constrain it. Every task's `<verify>` block passed before its commit.
- **REFACTOR gate:** not needed beyond `ruff format`, which reported both files already formatted at every boundary.
- **Gate commits:** a `feat(...)` commit exists and two `test(...)` commits follow it. The standard RED→GREEN commit ordering is inverted because the plan's task order is, not because a gate was skipped.

## Verification Evidence

### Plan `<verification>` block — 7 of 7

| # | Check | Result |
|---|-------|--------|
| 1 | `pytest backend/tests/test_analytics_volume.py -q` | **15 passed** in 2.58s |
| 2 | `pytest backend/tests/test_analytics_isolation.py -q` | **6 passed** — all six boundary guards green with `volume.py` present |
| 3 | `pytest backend/tests/test_time.py backend/tests/test_migrations.py -q` | **28 passed** — the `America/New_York` flip was reverted and the shared container is clean |
| 4 | `pytest -q -m "not integration"` | **197 passed**, 141 deselected in 0.82s (baseline 196; +1 markerless fold test) |
| 5 | `pytest -q` (full suite) | **338 passed** in 8.84s (baseline 323; +15) |
| 6 | `ruff check backend` / `mypy backend` | clean / 44 pre-existing errors in 13 test files, **0 from this plan** — see Deferred Issues. `mypy backend/app` → no issues in 46 source files |
| 7 | `pyproject.toml` unmodified; `resolver.py` / `exercise_map.py` untouched; no migration | `git diff --name-only <base> HEAD` → exactly `backend/app/analytics/volume.py` and `backend/tests/test_analytics_volume.py`; `backend/migrations/versions/` unchanged; zero deletions (`--diff-filter=D` empty) |

### Negative controls — each proven red, then reverted

| Injection | Result |
|---|---|
| `tonnage_kg=totals.tonnage_kg` (drop the `else None`) | `test_modality_without_operands_reports_tonnage_none` and `test_duration_only_sets_count_as_hard_sets` red: `assert Decimal('0') is None`. The other 13 stay green — precisely the blind spot the plan named |
| `for week_start in sorted(folded):` (drop the spine) | 4 red: all three parametrized boundary rows plus `test_weeks_are_gap_free_including_zero_training_weeks` |
| `snap_to_weeks=False` | `test_window_snaps_outward_to_whole_weeks` red |
| `Workout.user_id == user_id` removed from `rollup.weekly_set_rows` | `test_weekly_volume_is_scoped_to_one_user` red |

`git status` was confirmed clean after each revert; none of these injections appears in any commit.

### Task 1 acceptance criteria — 12 of 12

| Criterion | Required | Actual |
|---|---|---|
| `^async def get_weekly_volume` | 1 | 1 |
| `^def _fold_week_totals` | 1 | 1 |
| `snap_to_weeks=True` | 1 | 1 |
| `local_week_spine(` | 1 | 1 |
| `build_coverage(` / `build_freshness(` | 1 / 1 | 1 / 1 |
| `FRESHNESS_RESOURCES_WORKOUTS` | ≥1 | 2 |
| `tonnage_kg=None\|else None` | ≥1 | 2 |
| `session_ids.add(` | 1 | 1 |
| `exercise_type\|ExerciseMuscle\|text(\|session.commit\|session.flush\|session.add(` | 0 | 0 |
| `: float\|float(` | 0 | 0 |
| `min_lines: 110` | ≥110 | 160 |
| `pytest test_analytics_isolation.py` / `ruff` / `mypy` on the module | 0 / 0 / 0 | 6 passed / clean / clean |

The plan's inline `_fold_week_totals` probe printed `OK`: `(5, 30, 3, Decimal('1800.000'), 1)` from two rows of one workout, and `total_reps is None` / `tonnage_sets == 0` from a reps-free row.

### Task 2 acceptance criteria — 13 of 13

| Criterion | Required | Actual |
|---|---|---|
| module collects and passes | exit 0, 7 collected | 7 passed |
| `-k warmup` / `-k dropset` / `-k modality` / `-k zero_load` / `-k superset` | 1 each | 1 each (6 deselected each) |
| `Decimal("1800.000")` / `Decimal("3000.000")` | 1 / 1 | 1 / 1 |
| `tonnage_kg is None` | ≥2 | 3 |
| `Decimal("0.000")` | ≥1 | 3 |
| `SCHEDULING relationship` | 1 | 1 |
| `pytest -q -m "not integration"` | exit 0 | 197 passed |
| `ruff check` on the test module | 0 | clean |

### Task 3 acceptance criteria — 12 of 12

| Criterion | Required | Actual |
|---|---|---|
| module collects and passes | exit 0, 15 collected | 15 passed |
| `-k week_boundary` | exactly 4 | 4 passed, 11 deselected |
| `grep -c "def test_"` | 13 | 13 |
| `America/New_York` | ≥1 | 1 |
| `sa.text(` | 2, all bound-parameter | 2 — both `update users set timezone = :tz where id = :uid` with a params dict; zero f-string SQL |
| `ASVS V4 violated` | 1 | 1 |
| `diagnostically interesting` | 1 | 1 (after Deviation 3) |
| `dt.date(2026, 8, 10)` | ≥1 | 2 |
| `insufficient_data is False` | ≥1 | 1 |
| `pytest test_time.py test_migrations.py -q` afterwards | exit 0 | 28 passed |
| `pytest -q` (full suite) | exit 0 | 338 passed |
| `ruff check backend` / `mypy backend` | 0 / 0 | clean / 44 pre-existing (0 new) — see Deferred Issues |

### Behavioural results observed against the container

| Fixture | Observed |
|---|---|
| 2 `warmup` + 3 `normal` at 60 kg x 10 | `hard_sets=3, total_reps=30, tonnage_sets=3, tonnage_kg=Decimal("1800.000"), sessions=1` |
| 3 `normal` + 2 `dropset` at 60 kg x 10 | `hard_sets=5, total_reps=50, tonnage_sets=5, tonnage_kg=Decimal("3000.000")` |
| 3 `reps_only` sets, weight NULL, reps 15 | `hard_sets=3, total_reps=45, tonnage_sets=0, tonnage_kg=None` |
| 3 duration-only sets | `hard_sets=3, total_reps=None, tonnage_sets=0, tonnage_kg=None` |
| 1 set at `weight_kg=Decimal("0.000")`, reps 10 | `hard_sets=1, total_reps=10, tonnage_sets=1, tonnage_kg=Decimal("0.000")` |
| superset pair vs identical non-superset pair | `WeeklyVolumeWeek` objects compare equal, with `hard_sets=6 > 0` guarding vacuity |
| 16:30Z / 17:00Z / 23:30Z on 2026-08-23 | week `2026-08-17` / `2026-08-24` / `2026-08-24`; the other week is a `(0, 0)` row, not absent |
| 17:00Z with `users.timezone = America/New_York` | week `2026-08-17` |
| request Wed 2026-08-26 to Thu 2026-08-27 | exactly one week, `week_start=2026-08-24`, `hard_sets=3` |
| request 2026-08-10..2026-08-30, one workout in the last week | `[2026-08-10, 2026-08-17, 2026-08-24]`, first two fully zeroed with `total_reps is None` and `tonnage_kg is None` |
| one workout, then two | `sessions_in_window` 1 → 2, `insufficient_data` True → False, `earliest_data_at == 2026-08-24T02:00Z` |
| 3 second-user workouts + 1 default-user workout, same week | default user `(1, 3)`, second user `(3, 9)` |

## Threat Model Disposition

| Threat ID | Disposition | Status after this plan |
|-----------|-------------|------------------------|
| T-04-02 | mitigate | **Done, non-vacuously.** `user_id` is keyword-only with no default and is threaded into `resolve_window`, `weekly_set_rows`, `build_coverage` and `build_freshness` — every query the function composes. `test_weekly_volume_is_scoped_to_one_user` asserts 1/3 against 3/9 and goes red when the tenant predicate is removed. |
| T-04-01 | mitigate | **Done.** The window is built by `rollup.build_window`, which calls `validate_timezone` and rejects inverted/over-long ranges before any query. `volume.py` contains zero `text(` in any spelling (grep 0, and `test_analytics_uses_no_raw_sql_text` covers it by `rglob`). The two `sa.text` calls in the TEST module both use bound-parameter dicts scoped to one user id; Ruff `S608` is clean. |
| T-04-06 | mitigate | **Inherited, unchanged.** `MAX_ANALYTICS_WINDOW_DAYS = 1830` fires in `build_window` before `local_week_spine` is reached, bounding the spine at ~262 entries. Not re-implemented here. |
| T-04-07 | mitigate | **Done, on both counts, and both proven red.** `tonnage_kg` is `None` whenever `tonnage_sets == 0`; the week list comes from `local_week_spine`. The coercion injection and the spine injection each fail exactly the tests that exist to catch them. |
| T-04-04 | mitigate | **Done by construction.** The module emits no log line at all (see Decisions Made), so no workout title, weight or measurement can reach a log sink from it. No `str(exc)` anywhere. |
| T-04-03 | mitigate | **Inherited and re-asserted.** `build_freshness` returns `last_synced_at` only; `test_response_carries_freshness_and_coverage` pins `set(result.freshness.resources) == {"workouts"}` — an exact key set, so an extra key added later fails here too. |
| T-04-09 | mitigate | **Done.** Zero `session.commit/flush/add` and no write-construct import; `test_analytics_never_writes` (04-02) covers the new file automatically. |

## Threat Flags

None. This plan adds no network endpoint, no auth path, no file access and no schema change. The only user-controlled values reaching SQL are `users.timezone` (validated at the boundary, bound as a parameter by `rollup`) and the date range (validated and clamped by `build_window` before any query runs).

## Known Stubs

None. Every code path is executed: `get_weekly_volume` against a live Postgres container in 12 integration cases, `_fold_week_totals` additionally against hand-constructed rows with no container.

## Requirements Status

The plan frontmatter carries `requirements: [VOL-01, DQ-01, DQ-02]`. **All three are satisfied by this plan's code**, but `.planning/REQUIREMENTS.md` was deliberately left unmodified — see Deviation 4.

| Requirement | Delivered here? |
|---|---|
| VOL-01 — weekly training volume (hard sets, reps, modality-aware tonnage), warm-ups excluded | **Yes.** `get_weekly_volume` returns it, proven against golden fixtures for every observed set modality. Plan 04-09 adds the substrate-level tests for the aggregate underneath it. |
| DQ-01 — data freshness surfaced per source | **Yes, first time on a real response.** `WeeklyVolumeResult.freshness` carries the per-resource `last_synced_at` map, asserted as an exact key set. |
| DQ-02 — coverage / insufficient-data signalling | **Yes, first time on a real response.** `WeeklyVolumeResult.coverage` carries D-06's three fields, with the D-05 boundary pinned on both sides through the public function. |

**Action for the orchestrator:** mark VOL-01, DQ-01 and DQ-02 complete centrally after wave 3 merges. Plans 04-07 and 04-09 carry overlapping IDs and will report the same.

## Deferred Issues

Recorded here rather than in a phase-level `deferred-items.md`, which would be an add/add merge conflict between concurrent worktree agents.

1. **44 pre-existing `mypy backend` errors across 13 test files.** Task 3's criterion asks `mypy backend` to exit 0; it did not before this plan either. Plans 04-03, 04-04 and 04-05 measured the identical 44/13. The meaningful property holds: `mypy backend | grep -c "test_analytics_volume.py\|analytics/volume.py"` → **0**, and `mypy backend/app` is clean across 46 source files.
2. **11 pre-existing files fail `ruff format --check backend`** — `hevy/events.py`, `hevy/sync.py`, `hevy/workouts.py`, `normalization/resolver.py`, and 7 Phase-3 test modules. None is in `app/analytics/`, none was touched by this plan, and both files this plan created report "already formatted". Out of scope under the executor's scope-boundary rule; worth a standalone `ruff format backend` cleanup commit.
3. **Worktree base drift, fifth consecutive wave in this phase.** Every wave-1 and wave-2 summary records the same correction. This is a worktree-provisioning defect rather than something each agent should keep absorbing: an agent that skipped the mandated startup check would have rebuilt on a pre-Phase-4 tree and its "new" file would have overwritten nothing while importing modules that do not exist.
4. **`.gitignore` line 6 is `.venv/`, which does not match a symlink named `.venv`.** Any worktree agent that symlinks the main venv sees it as untracked. A single `git add .` would commit a broken absolute-path symlink into the repo. Changing the entry to `.venv` (no trailing slash) closes this permanently.

## Issues Encountered

- **`grep -c "diagnostically interesting"` returned 0 on the first check** despite the mandated sentence being present verbatim — the wrap point fell between the two words. Documented as Deviation 3. Worth generalising: five plans in this phase have now hit a version of "the plan's prose and the plan's greps disagree", and line wrapping is a new variant of it.
- No debugging cycle was needed otherwise. `volume.py` was green on first execution, and all 7 Task-2 tests and all 8 new Task-3 cases passed on their first run.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

**Ready.** Plan 04-08 (wave 4) can append `get_muscle_group_volume` to `backend/app/analytics/volume.py` and its tests to `backend/tests/test_analytics_volume.py` immediately. The contract it should honour:

- **Copy the composition, do not re-invent it.** `resolve_window(snap_to_weeks=True)` → `weekly_set_rows` **once** → `resolve_row_muscles` on those same rows → `fold_weeks_by_muscle` → project onto `local_week_spine(window.start_day, window.end_day)` → `build_coverage` + `build_freshness`.
- **Use `FRESHNESS_RESOURCES_MUSCLE`, not `FRESHNESS_RESOURCES_WORKOUTS`.** A per-muscle number depends on the template sync too, and `test_response_carries_freshness_and_coverage` deliberately pins VOL-01's key set exactly so 04-08 cannot inherit the wrong tuple by copy-paste.
- **The module has one docstring and one import block.** Both are written to be extended. `import sqlalchemy as sa` is already present in the test module; `sa.text(` currently appears exactly **2** times and 04-08's own criteria should account for that if it adds more.
- **Test-module constants already taken:** `_BENCH`, `_PUSHUP`, `_PLANK`, `_ROW`, `_MONDAY`, `_WEEK_START`, `_WEEK_END`, `_SIXTY`, `_BEFORE_MIDNIGHT`, `_AT_MIDNIGHT`, `_NEAR_MIDNIGHT_UTC`, `_EARLIER_WEEK`, `_BOUNDARY_WEEKS`, `_THREE_WEEK_START`, `_THREE_WEEK_END`, plus the `_one_week` helper (which asserts a single-week window and is reusable for VOL-02 only if a per-week muscle equivalent is written beside it, since it returns a `WeeklyVolumeWeek`).
- **`_fold_week_totals` and `_WeekTotals` are private and VOL-01-specific.** VOL-02's fan-out is `rollup.fold_weeks_by_muscle`; do not widen this one.
- **Do not sum per-week `sessions` to get a window total** (the 4x inflation 04-05 measured). Re-fold from the same rows with `fold_window_by_muscle`.

**Open item:** none blocking.

## Self-Check: PASSED

Files verified present on disk:

- FOUND: `backend/app/analytics/volume.py`
- FOUND: `backend/tests/test_analytics_volume.py`
- FOUND: `.planning/phases/04-volume-frequency-analytics/04-06-SUMMARY.md`

Commits verified in `git log`:

- FOUND: `89796e8` feat(04-06): add get_weekly_volume and the pure per-week fold (VOL-01)
- FOUND: `7348f24` test(04-06): pin VOL-01 against golden fixtures for every set modality
- FOUND: `311641f` test(04-06): pin the Jakarta week boundary, outward snap, spine and envelope

No file deletions in any commit (`git diff --diff-filter=D --name-only a02e5fd HEAD` empty). No untracked files left behind other than the removed `.venv` symlink. `STATE.md` and `ROADMAP.md` were not modified — the orchestrator owns those writes.

---
*Phase: 04-volume-frequency-analytics*
*Completed: 2026-08-30*
