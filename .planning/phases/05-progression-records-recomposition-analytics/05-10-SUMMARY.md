---
phase: 05-progression-records-recomposition-analytics
plan: 10
subsystem: analytics
tags: [recomposition, body-composition, decision-support, decimal, lookup-table, time-machine, postgres, composition]

# Dependency graph
requires:
  - phase: 05-03
    provides: "RecompositionResult / AggregateProgression / RecompositionStatus / ProgressionSignal schemas, FRESHNESS_RESOURCES_ALL"
  - phase: 05-06
    provides: "get_body_weight_trend — the D-16 smoothed trend_rate_percent_per_week and the shared anchor_day"
  - phase: 05-07
    provides: "get_exercise_trends — the one definition of improving/stable/declining/unclear"
  - phase: 04
    provides: "get_weekly_volume (context only), metadata.build_freshness"
provides:
  - "get_recomposition_status(session, *, user_id) -> RecompositionResult — BODY-02 end to end"
  - "aggregate_progression(verdicts) -> AggregateProgression — D-20's net-progression score, pure"
  - "classify_recomposition(*, rate_percent_per_week, signal) -> RecompositionStatus — the 24-pair matrix, pure and total"
  - "WEIGHT_GAIN_TOO_FAST_PERCENT_PER_WEEK / WEIGHT_LOSS_TOO_FAST_PERCENT_PER_WEEK / WEIGHT_STABLE_BAND_PERCENT_PER_WEEK / RECOMP_MIN_CLASSIFIED_EXERCISES / RECOMP_PROGRESSION_NET_BAND / RECOMP_LOOKBACK_WEEKS"
  - "INTERPRETATION_DISCLAIMER — the fixed decision-support safety label"
affects: ["phase-6 fitness_get_recomposition_status MCP tool", "phase-6 coaching prompt doc (the disclaimer is the contract it inherits)"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Label matrix as DATA in a MappingProxyType keyed on (bucket, signal), so a missing combination is a KeyError rather than a nested-if fallthrough"
    - "zip(_SIGNAL_ORDER, row, strict=True) at module load: a short or long matrix row is an import-time failure, not a silent mislabelling"
    - "Composition-only analytics module — no SQL of its own beyond the freshness envelope; every read is delegated to an already-tenant-scoped function"
    - "One shared anchor_day reused across all three delegated calls, so the halves of one answer cannot straddle a local midnight"

key-files:
  created:
    - backend/app/analytics/recomposition.py
    - backend/tests/test_analytics_recomposition.py
  modified:
    - backend/app/analytics/__init__.py

key-decisions:
  - "The label matrix is a flat MappingProxyType over all 24 (weight bucket, progression signal) pairs, built from six explicitly-written four-status rows rather than the plan's nested dict comprehension"
  - "WEIGHT_STABLE_BAND_PERCENT_PER_WEEK = 0.10 %/week — the one threshold CONTEXT.md delegated, set at one tenth of D-11"
  - "training_volume is returned but is never an input to the label (D-20); proven by a test that changes volume and asserts the status is unchanged"
  - "The plan's `latest_week_delta_kg` acceptance grep was satisfied by naming the field explicitly in the module docstring, with a sentence stating that is the only place it may appear"
  - "Task ordering was inverted to make the TDD gates real: the fast-suite spec was written and committed RED before either implementation task"

requirements-completed: []
requirements-satisfied-pending-orchestrator: [BODY-02]

# Metrics
duration: 14min
completed: 2026-08-31
---

# Phase 5 Plan 10: Recomposition Status Summary

**BODY-02 shipped: a seven-value recomposition verdict crossing D-16's smoothed body-weight rate with D-20's net-progression score over a 12-week lookback, as a 24-entry lookup table with a required decision-support disclaimer and a required progression signal, so no label can silently hide a disagreement between the two inputs.**

## Performance

- **Duration:** ~14 min
- **Started:** 2026-08-31T04:03Z
- **Completed:** 2026-08-31T04:17Z
- **Tasks:** 3 (5 commits — both TDD RED gates are their own commits)
- **Files modified:** 3 (2 created, 1 modified)

## Accomplishments

- `get_recomposition_status` composes three already-shipped functions over **one shared anchor** and writes no SQL of its own beyond the freshness envelope.
- All **24** `(weight bucket, progression signal)` pairs resolve to one of blueprint §26's seven values, asserted against a hand-written expected table. `likely_recomp_progressing` is proven reachable **only** from `(stable, positive)` and `(losing, positive)`.
- Both D-11 and D-12 threshold edges, both stable-band edges and both net-band edges are tested from each side.
- The live-data 9/9/10 aggregate reproduces `net_score == Decimal("-0.0357")` and reads `stable` — not the `declining` a plurality rule would return on a one-exercise margin.
- A null smoothed rate yields `insufficient_data` even with a `positive` progression signal, and the test that proves it deliberately seeds a **non-null, non-zero** `latest_week_delta_kg` so the wrong fallback has something to reach for.
- `disclaimer` and `progression_signal` are asserted populated on both the insufficient response and a fully populated one, inside a single test.
- **20 tests** in the new module (11 fast, 9 container-backed under a frozen clock). Full suite: **477 passed**.

## Task Commits

1. **TDD RED — fast-suite matrix spec fails on a missing module** — `677a0b2` (test)
2. **Task 1: constants, `aggregate_progression`, `_weight_bucket`, the label matrix** — `3f025bb` (feat)
3. **TDD RED — signature and package-index spec fails on a missing function** — `8d9eb2f` (test)
4. **Task 2: `get_recomposition_status` + the package docstring** — `4c06283` (feat)
5. **Task 3: nine frozen-clock integration tests** — `0c9daf1` (test)

Plan metadata commit follows this SUMMARY.

## Files Created/Modified

- `backend/app/analytics/recomposition.py` (340 lines, created) — exceeds the plan's `min_lines: 200`. Six constants, `INTERPRETATION_DISCLAIMER`, `aggregate_progression`, `_WeightBucket`, `_weight_bucket`, `_SIGNAL_ORDER`, `_MATRIX_ROWS`, `_LABEL_MATRIX`, `classify_recomposition`, `get_recomposition_status`.
- `backend/tests/test_analytics_recomposition.py` (686 lines, created) — 20 tests.
- `backend/app/analytics/__init__.py` (modified) — first line only; every other sentence byte-identical.

## Interface Record (requested by the plan's `<output>` block)

### Exact signature

```python
async def get_recomposition_status(
    session: AsyncSession, *, user_id: uuid.UUID
) -> RecompositionResult: ...
```

No date parameters at all. `user_id` is keyword-only with no default. Verified structurally via `inspect.signature` in `test_recomposition_status_takes_no_date_range`, which is in the **fast** suite.

### The 24-pair matrix, as shipped

| Weight rate (%/week) | Bucket | `positive` | `neutral` | `negative` | `insufficient` |
|---|---|---|---|---|---|
| `rate > +0.25` | too-fast gain | `weight_gain_too_fast` | `weight_gain_too_fast` | `weight_gain_too_fast` | `weight_gain_too_fast` |
| `+0.10 < rate <= +0.25` | on-target gain | `likely_muscle_gain` | `likely_muscle_gain` | `likely_muscle_gain` | `likely_muscle_gain` |
| `-0.10 <= rate <= +0.10` | stable | `likely_recomp_progressing` | `weight_stable` | `weight_stable` | `weight_stable` |
| `-1.00 <= rate < -0.10` | losing | `likely_recomp_progressing` | `likely_fat_loss` | `likely_fat_loss` | `likely_fat_loss` |
| `rate < -1.00` | too-fast loss | `weight_loss_too_fast` | `weight_loss_too_fast` | `weight_loss_too_fast` | `weight_loss_too_fast` |
| `rate is None` | insufficient | `insufficient_data` | `insufficient_data` | `insufficient_data` | `insufficient_data` |

Shipped exactly as the plan's `<locked_decisions>` specified — **no cell was changed**. Boundary conventions as implemented: the two too-fast thresholds are **strict** (`+0.25` is on target, `+0.26` is too fast; `-1.00` is losing, `-1.01` is too fast); the stable band is **inclusive** at both edges; D-20's `±0.25` net band is **exclusive** (exactly `±0.25` is `neutral`).

### Live-data aggregate combined with a null weight rate

```
aggregate_progression([IMPROVING]*9 + [STABLE]*9 + [DECLINING]*10)
  -> classified_exercises=28  net_score=Decimal("-0.0357")  signal=neutral  verdict=stable
classify_recomposition(rate_percent_per_week=None, signal=neutral)
  -> RecompositionStatus.INSUFFICIENT_DATA
```

**`insufficient_data` is the observed and correct answer on live data today**, because the D-16 anchor window holds zero weigh-ins after a real 52-day logging gap. It is a first-class tested path, not a failure. It will start returning a real label once four consecutive weeks each clear the 3-measured-day floor.

### SQL round trips per call: **18**

Measured empirically with a `before_cursor_execute` listener on a fully-seeded fixture (throwaway probe, run and deleted — never committed):

| Delegated call | Round trips | Breakdown |
|---|---|---|
| `get_body_weight_trend` | 4 | tz probe, 35-day weigh-in fetch, `earliest_measurement_at`, 1 freshness resource |
| `get_exercise_trends` | 6 | tz, qualifying sets, session count, `earliest_workout_at`, 2 freshness resources |
| `get_weekly_volume` | 5 | tz, weekly rollup, session count, `earliest_workout_at`, 1 freshness resource |
| `build_freshness(FRESHNESS_RESOURCES_ALL)` | 3 | one `sync_state` read per resource |
| **Total** | **18** | |

Three of the eighteen are the same `SELECT users.timezone` (once per delegated call). That redundancy is inherited from the delegated functions and was **not** optimised here: collapsing it would mean either a fourth `users.timezone` reader in this module or a signature change to all three delegates, and `rollup.resolve_window` is deliberately the only sanctioned reader. Worth revisiting in Phase 6 if latency matters, as a change to `resolve_window`'s callers rather than to this module.

### Phase-wide checks (run once here, as the plan directs)

| Check | Result |
|---|---|
| `git diff --stat 218cf81 HEAD -- pyproject.toml` | **empty** — zero new dependencies across the whole phase |
| `git diff --stat 218cf81 HEAD -- backend/migrations/versions/` | **empty** — no migration created in the phase |
| `ls backend/migrations/versions/` | 4 files, unchanged since before Phase 5 |
| `grep -rn "import pandas\|import numpy" backend/app/` | no matches |

**Path note:** the plan's verification names `backend/alembic/versions/`. The real path in this repo is `backend/migrations/versions/` (`alembic.ini` lives at `backend/` with `script_location = migrations`). Checked the correct path; the conclusion is unchanged.

## Decisions Made

1. **The matrix is six explicit four-status rows, flattened with `zip(..., strict=True)`.** The plan's own text permitted writing the 24 pairs literally if its nested dict comprehension "reads awkwardly", and it did. Writing all 24 as flat `(bucket, signal): status` entries would have wrapped every line onto three lines at the 100-char limit and destroyed the table shape. The shipped form still writes **all 24 statuses out**, keeps the `MappingProxyType` the plan requires, and adds a guarantee the plan did not have: `strict=True` makes a short or long row an **import-time** error rather than a `KeyError` months later.
2. **`RECOMP_LOOKBACK_WEEKS = 12` resolves to the window `[2026-06-08, 2026-08-30]` at the test anchor** — 83 days back from a Sunday anchor lands exactly on a Monday, so `get_weekly_volume`'s outward week-snapping is a no-op and the volume window is exactly 12 whole weeks. Confirmed rather than assumed.
3. **Volume is reported and never classified.** BODY-02's requirement text names "combined weight trend, training volume, and progression data". The shipped reading, following D-20: all three are **in the response**; only two are **in the label**. `test_training_volume_is_reported_but_never_classified` adds ten 15-rep filler sets and asserts `training_volume.weeks` changes while `status` and `net_score` do not. See "Requirement Status" below.
4. **Second RED gate for Task 2.** Task 2's plan verification was an inline `python -c` block with no committed test. Added `test_recomposition_status_takes_no_date_range` and `test_package_docstring_names_every_requirement` as a real failing spec first, both in the fast suite, so the signature contract and the package index are now regression-guarded rather than checked once at execution time.

## Deviations from Plan

Three, all textual or structural. **No behavioural deviation — every threshold, every matrix cell and every boundary convention shipped exactly as locked.**

### Auto-fixed Issues

**1. [Rule 3 - Blocking] The plan's task ordering made a TDD RED gate impossible**

- **Found during:** Task 1
- **Issue:** Tasks 1 and 2 are marked `tdd="true"`, but the entire test module is Task 3. Executing literally means implementation is committed before any test exists, so there is no RED gate and the `test(...)` → `feat(...)` sequence the executor contract requires cannot be produced. Writing a throwaway test in Task 1 that Task 3 would then overwrite would have been wasted work on the same file.
- **Fix:** Split the test module along the seam the plan itself draws. The eight fast-suite tests (the plan's Task 3 items 1–8, all pure) were written and committed **RED** first; Task 3 then appended the nine integration tests to the same file. Net result is the same single file the plan specifies, with two real RED gates.
- **Files modified:** `backend/tests/test_analytics_recomposition.py`
- **Verification:** `677a0b2` captured `ModuleNotFoundError: No module named 'app.analytics.recomposition'`; `8d9eb2f` captured `ImportError: cannot import name 'get_recomposition_status'`.
- **Committed in:** `677a0b2`, `3f025bb`, `8d9eb2f`, `4c06283`, `0c9daf1`

**2. [Rule 3 - Blocking] Two of the plan's own acceptance criteria contradicted its own suggested prose**

- **Found during:** Tasks 1 and 3 — the same trap `test_analytics_isolation.py`'s module docstring documents, and the same one 05-06 hit.
- **Issue:** (a) The plan's suggested test-module docstring ends "Never `pytest.approx`." while its acceptance criterion requires `grep -c "pytest.approx"` to return **0**. (b) The plan requires `grep -q "latest_week_delta"` to **succeed** while also requiring it to appear only inside the module docstring — but the plan's own suggested docstring says "D-17's raw single-week delta" and never names the field, so the grep would have returned 0 matches and failed.
- **Fix:** (a) Reworded to "No tolerance helper appears anywhere in this module, and deliberately not even in this sentence" — the rationale survives, the literal does not. (b) Named `latest_week_delta_kg` explicitly in the docstring and added a sentence stating that paragraph is the only place the field name may appear, so the grep now both succeeds and enforces what it was meant to enforce.
- **Files modified:** `backend/app/analytics/recomposition.py`, `backend/tests/test_analytics_recomposition.py`
- **Verification:** `grep -c "pytest.approx"` → 0; `grep -n "latest_week_delta"` → exactly one hit, on docstring line 13.
- **Committed in:** `3f025bb`, `0c9daf1`

**3. [Rule 1 - Bug] The plan's `freshness=await build_freshness(...)` line exceeded the 100-char limit**

- **Found during:** Task 2
- **Issue:** Transcribed as a single line it is 101 chars and `ruff check backend/app/analytics/` failed E501.
- **Fix:** Wrapped the call arguments, matching how every other `build_freshness` call site in the package is formatted.
- **Files modified:** `backend/app/analytics/recomposition.py`
- **Committed in:** `4c06283`

---

**Total deviations:** 3 auto-fixed (2 blocking-structural/textual, 1 lint). **Impact on plan:** none on behaviour or contract. No scope creep.

## Requirement Status — BODY-02

**BODY-02 is fully satisfied at the analytics layer.** Not marked complete here: `.planning/REQUIREMENTS.md` is deliberately untouched because sibling plan 05-09 was executing concurrently in another worktree and may also touch that file. **The orchestrator should mark BODY-02 complete after merge** — checkbox at line 53 and the traceability row at line 157.

Clause-by-clause against the requirement text:

| Clause | Status |
|---|---|
| "classifies overall recomposition status (progressing, muscle gain, fat loss, weight stable, too fast/slow, insufficient data)" | All seven values reachable and exhaustively tested |
| "from combined weight trend, ... and progression data" | Both are inputs to the label |
| "... training volume ..." | Present in the response as `training_volume`; **not** an input to the label, per D-20 |
| "explicitly framed as decision support rather than a medical or diagnostic claim" | `disclaimer` is a required model field, asserted populated on every response including the insufficient one |

The one clause worth a reviewer's eye is training volume. D-20 (locked, user-confirmed 2026-08-30) defines the classification as the weight-rate ladder crossed with the progression signal, and volume appears in neither. The shipped module returns twelve weeks of volume in the response so Claude has the full picture, and the module docstring records why it is not in the label: volume rises during a deload-free overreach as readily as during productive training, so admitting it would make the verdict *less* reliable. If a reviewer reads the requirement as demanding volume in the **label**, that is a D-20 revision, not a defect in this plan.

## Issues Encountered

- **Worktree base mismatch (the ninth consecutive occurrence in this phase).** `HEAD` was `1e97f3b`, an ancestor of the expected base `def87f5`. `git merge-base` confirmed it; `git reset --hard def87f5` corrected it before any work. Had it gone unnoticed, `recomposition.py`'s three delegated functions and every Phase 5 schema would have been absent and the plan would have looked unexecutable. This is now reliable enough to treat as the default state of a fresh worktree.
- **`mypy backend/` reports 44 pre-existing errors across 13 test modules**, exactly as flagged in the execution context. `mypy backend/app/` exits 0 (53 files). Filtering the output for this plan's two files returns **0**. The six errors that surface when type-checking the new test module in isolation are all in `backend/tests/conftest.py` (pytest-asyncio generator-fixture annotations), pre-existing and out of scope.
- **`.venv` is not present in worktrees.** Symlinked the main checkout's `.venv` to run verification, and removed the symlink before returning. It shows as untracked rather than ignored because `.gitignore` has `.venv/` (directory-only) and a symlink is not a directory — it was never staged.
- **`ruff format --check backend/` reports 15 pre-existing unformatted files.** Both files this plan created are formatted. Not fixed — out of scope.

## Verification Results

| Check | Result |
|---|---|
| `pytest -q` (full suite — the phase gate) | **477 passed** in 13.13 s |
| `pytest -q -m "not integration"` (fast suite) | **250 passed**, 227 deselected in 0.87 s |
| `pytest -q backend/tests/test_analytics_recomposition.py` | **20 passed** (11 fast + 9 integration) |
| `pytest -q -m integration backend/tests/test_analytics_recomposition.py` | **9 passed**, 11 deselected |
| `ruff check backend/` | All checks passed |
| `mypy backend/app/` | Success, 53 source files |
| `mypy backend/` | 44 pre-existing errors, **0 in this plan's files** |
| `git diff --stat` vs base | Exactly 3 files; `bodyweight.py`, `progression.py`, `volume.py`, `frequency.py`, `rollup.py`, `schemas.py`, `metadata.py`, `comparison.py`, `records.py`, `estimates.py`, `core/time.py`, `pyproject.toml` all untouched |
| Alembic migration created | None (correct — no schema change) |

Every plan acceptance-criteria grep verified individually and passing, including the four count-must-be-zero ones (`select(|session.execute|session.scalar` → 0, `FRESHNESS_RESOURCES_BODY|MUSCLE|WORKOUTS` → 0, `pytest.approx` → 0, `ExerciseMuscle(Override)?` in `__init__.py` → 0), the two count-must-be-one ones (`get_body_weight_trend(` → 1, `get_exercise_trends(` → 1), `tick=False` → 9 (criterion: ≥9), `grep -rl "RECOMP-" backend/tests/ | wc -l` → 1, and `git diff backend/app/analytics/__init__.py | grep -c "^-"` → 2.

## Known Stubs

None. Every field of `RecompositionResult` is computed from real rows or from a delegated result. `None` values (`net_score`, `trend_rate_percent_per_week`) are the documented D-20 and D-16 gates, not placeholders. There is no TODO, no hardcoded empty collection and no unwired component in either file.

## TDD Gate Compliance

Both gates present and in order, twice:

- `677a0b2` (test, RED — `ModuleNotFoundError` captured) → `3f025bb` (feat, GREEN)
- `8d9eb2f` (test, RED — `ImportError` captured) → `4c06283` (feat, GREEN)
- `0c9daf1` (test — Task 3's integration coverage, added against already-green code as the plan's structure dictates)

No REFACTOR commit was needed; nothing required cleanup after passing.

## User Setup Required

None — no external service configuration, no new dependency, no migration, no environment variable.

## Next Phase Readiness

- **Phase 6 can wrap `get_recomposition_status` directly.** `RecompositionResult` subclasses `_AnalyticsModel`, so the MCP `outputSchema` and `structured_content` come for free. It is the largest response in the project: it nests the full `BodyWeightTrendResult`, the eight-field `AggregateProgression` and twelve weeks of `WeeklyVolumeWeek`. Size is bounded by construction — no window is caller-sizable.
- **The MCP tool must surface `disclaimer` and `progression_signal` verbatim.** They are required fields precisely so a serialization change cannot drop them; a tool that projects a narrower shape would defeat T-05-78. `progression_signal` is what lets Claude say "you are gaining at a lean-bulk rate but your lifts are going backwards" instead of reading `likely_muscle_gain` at face value.
- **Live-data caveat for whoever demos this first:** the tool returns `insufficient_data` today and that is correct, not a bug. See the interface record above.
- **Latency note for Phase 6:** 18 round trips per call, three of which are a repeated `SELECT users.timezone`. If the MCP endpoint's cold-start budget becomes tight, that is the cheapest thing to collapse — and the change belongs in `rollup.resolve_window`'s calling convention, not in this module.
- **This is the last plan in Phase 5.** The analytics package now satisfies VOL-01..03, PROG-01..04, CMP-01, BODY-01, BODY-02, DQ-01 and DQ-02, and `app/analytics/__init__.py` says so.

## Self-Check: PASSED

- `backend/app/analytics/recomposition.py` — FOUND (340 lines, exceeds the plan's `min_lines: 200`)
- `backend/tests/test_analytics_recomposition.py` — FOUND (686 lines, contains `get_recomposition_status`)
- `backend/app/analytics/__init__.py` — FOUND (contains `PROG-01`)
- `.planning/phases/05-progression-records-recomposition-analytics/05-10-SUMMARY.md` — FOUND
- Commits `677a0b2`, `3f025bb`, `8d9eb2f`, `4c06283`, `0c9daf1` — all FOUND in `git log`
- All three `key_links` patterns present in `recomposition.py`: `get_body_weight_trend\(`, `get_exercise_trends\(`, `FRESHNESS_RESOURCES_ALL`
- All nine `exports` from the artifact spec importable — verified by the plan's own Task 1 and Task 2 `python -c` blocks, both printing `OK`

## Threat Flags

None. No new network endpoint, no auth path, no file access, no schema change. Every threat in the plan's register is mitigated as specified:

- **T-05-75** (cross-tenant) — `user_id` keyword-only with no default, passed unchanged to all three delegates. Proven by `test_second_users_data_does_not_change_the_verdict`, which seeds a second user with an opposing weight trend (70.00 vs 65.00 current, same anchor) **and** an opposing training signal (200–260 kg on the same template ids and the same dates, since Hevy's built-in template ids are global).
- **T-05-79** (classifying off the noisy raw delta) — `classify_recomposition` is called with `trend_rate_percent_per_week` only; `latest_week_delta_kg` appears exactly once in the module, in the docstring, in a sentence saying that is the only place it may appear.
- **T-05-80** (missing matrix branch) — matrix is data in a `MappingProxyType`; all 24 pairs asserted; `strict=True` promotes a malformed row to an import-time failure.
- **T-05-83** (write path) — `grep -c "select(|session.execute|session.scalar"` returns **0**; `test_analytics_isolation.py`'s `rglob` auto-covers the new module and all 8 of its guards pass.

---
*Phase: 05-progression-records-recomposition-analytics*
*Completed: 2026-08-31*
