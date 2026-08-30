---
phase: 04-volume-frequency-analytics
plan: 02
subsystem: analytics
tags: [pydantic, decimal, zoneinfo, static-analysis, boundary-tests, pytest, mypy, ruff]

# Dependency graph
requires:
  - phase: 03-hevy-integration-normalization
    provides: "CanonicalMuscleGroup / MuscleRole taxonomy (app/normalization/muscles.py), effective_muscles_bulk + apply_weights (app/normalization/resolver.py), RESOURCE_* sync_state keys, the test_hevy_isolation.py static-boundary pattern"
  - phase: 01-backend-foundation
    provides: "hide_input_in_errors ConfigDict convention (FOUND-05), Decimal-not-float numeric convention, pytest fast/integration marker split"
provides:
  - "backend/app/analytics/ package, a sibling of app/normalization/ and app/core/, with both import boundaries and the read-only rule stated in its docstring"
  - "Ten frozen Pydantic return types in app/analytics/schemas.py — the contract every Phase 4 plan (04-04..04-08) and Phase 6 MCP tool codes against"
  - "CoverageMetadata as D-06 verbatim (three fields) and FreshnessMetadata as a per-resource last_synced_at map that cannot structurally carry sync_state error text"
  - "Six static boundary assertions in the fast suite (test_analytics_isolation.py) banning app.mcp, app.integrations, the muscle ORM classes, raw SQL text(), and all session writes"
affects: [04-04, 04-05, 04-06, 04-07, 04-08, 04-09, 05-progression-plateau-pr, 06-mcp-tools]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Interface-first plan: every public return type declared once before any producer exists"
    - "Frozen Pydantic domain models with extra=forbid (inverted from the wire models' extra=ignore)"
    - "Static boundary test per package, fast suite, anchored regex over rglob'd committed source"

key-files:
  created:
    - backend/app/analytics/__init__.py
    - backend/app/analytics/schemas.py
    - backend/tests/test_analytics_isolation.py
  modified: []

key-decisions:
  - "Analytics domain models invert the wire models' extra policy: extra=forbid, not extra=ignore — an unexpected field in an internal type is a bug in this repo, not somebody else's release"
  - "frozen=True on every analytics return type — a mutable result object is one two consumers will disagree about (T-04-11, accepted risk closed)"
  - "The raw-SQL guard also bans the fully-qualified sqlalchemy.text( spelling, which the plan's verbatim regex let through"
  - "requirements mark-complete deliberately not run: 04-02 declares the VOL/DQ types, it does not compute them, and three wave-1 worktrees writing REQUIREMENTS.md would collide"

patterns-established:
  - "Muscle-table prose convention: app/analytics/ refers to the tables in lowercase (exercise_muscles), never by ORM class name, so the CamelCase ban stays a pure signal"
  - "Negative control as an execution gate: every static guard is proven to go red against an injected violation before its test file is committed"
  - "tonnage_kg is None vs Decimal('0.000') is a load-bearing distinction, made auditable by a tonnage_sets counter beside every tonnage figure"

requirements-completed: []  # VOL-01, VOL-02, VOL-03, DQ-01, DQ-02 are ADVANCED (types declared) but not satisfied — see Deviations #3

# Metrics
duration: 6min
completed: 2026-08-30
---

# Phase 4 Plan 02: Analytics Package & Schema Contract Summary

**Ten frozen Pydantic return types declaring the whole Phase 4 contract — Decimal-only magnitudes, D-06's exact three-field coverage block, U-03 per-muscle uncertainty — behind six fast-suite static assertions that make `effective_muscles_bulk` usage a compile-time-ish guarantee rather than a code-review hope.**

## Performance

- **Duration:** 6 min
- **Started:** 2026-08-30T09:59:52Z
- **Completed:** 2026-08-30T10:05:51Z
- **Tasks:** 3 of 3
- **Files created:** 3 (no existing file modified)

## Accomplishments

- Created `backend/app/analytics/` as a sibling of `normalization/` and `core/`, with a docstring-only `__init__.py` that states the two import bans, the muscle-table ban, and the read-only rule — so the constraints survive a refactor that nobody reruns the plan for.
- Declared all ten public return types in one file, before any producer exists. Plans 04-04 through 04-08 now code against fixed field names; deciding them later would have cost a rewrite of every expected value in every analytics test.
- Made two silent-wrong-answer classes structurally impossible rather than merely tested: `FreshnessMetadata` cannot carry `sync_state.last_error`/`status`/cursors (T-04-03), and `tonnage_kg: Decimal | None` beside `tonnage_sets: int` keeps "modality can't produce weight × reps" distinct from "computed, and it is zero" (Pitfall 3).
- Proved all six boundary guards bite. 11 injected violations, 11 reds — including the empty-walk guard-on-the-guards, and including a `sqlalchemy.text(` spelling the plan's specified regex would have missed.

## Task Commits

1. **Task 1: Create the app/analytics package with its boundary docstring** — `7a2fe44` (feat)
2. **Task 2: Declare every Phase 4 public return type in app/analytics/schemas.py** — `c43ae2b` (feat)
3. **Task 3: Create the static analytics boundary test (fast suite)** — `22a0209` (test)

**Plan metadata:** see final `docs(04-02)` commit.

## Files Created/Modified

- `backend/app/analytics/__init__.py` (19 lines) — Package boundary declaration. Docstring only: no imports, no re-exports, no `__all__`, mirroring `app/normalization/__init__.py`. States that nothing here may import `app.integrations` (HEVY-05) or `app.mcp` (the one-way Phase 6 arrow), that muscle resolution routes through `effective_muscles_bulk` because the override rule is REPLACEMENT not merge, and that the package never commits, flushes, inserts, updates or deletes.
- `backend/app/analytics/schemas.py` (169 lines) — `_AnalyticsModel` base (`hide_input_in_errors=True, extra="forbid", frozen=True`) plus ten public models: `FreshnessMetadata`, `CoverageMetadata`, `WeeklyVolumeWeek`, `WeeklyVolumeResult`, `MuscleGroupVolume`, `MuscleGroupVolumeWeek`, `MuscleGroupVolumeResult`, `MuscleGroupFrequency`, `ExerciseFrequency`, `TrainingFrequencyResult`. Imports nothing from `sqlalchemy`, `app.db`, `app.mcp` or `app.integrations` — only `datetime`, `Decimal`, `pydantic`, and `CanonicalMuscleGroup`.
- `backend/tests/test_analytics_isolation.py` (161 lines) — Six static assertions over `ANALYTICS.rglob("*.py")`, no marker so they run in the fast suite: walk-guard, no `app.integrations`, no `app.mcp`, no `ExerciseMuscle`/`ExerciseMuscleOverride` identifiers, no `text(`/`sa.text(`/`sqlalchemy.text(`, no `session.commit/flush/add/add_all` and no `insert`/`update`/`delete` import from sqlalchemy.

## Decisions Made

- **`extra="forbid"`, inverting the wire models.** `hevy/schemas.py` uses `extra="ignore"` deliberately and asymmetrically — Hevy adding a field must not break a sync. That reasoning does not transfer: these are internal domain types, so an unexpected field is a bug in this repo and should fail loudly rather than be dropped.
- **`frozen=True` on the shared base.** This is a read path. A result object a caller can mutate is a result object two callers will disagree about. This closes T-04-11 (previously dispositioned `accept`) at zero cost.
- **The raw-SQL guard covers three spellings, not two.** See Deviation #2.
- **Requirement IDs left unchecked.** See Deviation #3.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Two internal contradictions between the plan's verbatim docstring text and its own grep acceptance criteria**

- **Found during:** Task 2 (schemas.py)
- **Issue:** The plan supplied docstring text to write verbatim that directly violated two of its own machine-checkable acceptance criteria:
  - The `CoverageMetadata` docstring it specified contains the literal `` ``requested_window`` ``, while acceptance criterion 5 requires `grep -c "requested_window" backend/app/analytics/schemas.py` to return **0**.
  - The `_AnalyticsModel` docstring it specified contains the literal `extra="forbid"`, which together with the `model_config` line makes `grep -c 'extra="forbid"'` return **2**, while acceptance criterion 11 requires **1**.

  This is the same substring-versus-anchored-match trap the plan itself documents for the isolation test (`test_hevy_isolation.py:88-93`): a naive substring check fails on the sentence documenting the rule.
- **Fix:** Resolved toward the machine-checkable criteria, preserving the documented intent in both cases. `CoverageMetadata` now reads "Echoing the requested date range back here was explicitly considered and NOT selected; do not add it." `_AnalyticsModel` now reads "Extra fields are FORBIDDEN here, not ignored -- the opposite of the wire models". Every field name, type and model remains exactly as specified; only prose changed.
- **Files modified:** `backend/app/analytics/schemas.py`
- **Verification:** `grep -c "requested_window"` → 0; `grep -c "start_day\|end_day"` → 0; `grep -c 'extra="forbid"'` → 1. All 13 Task 2 acceptance criteria pass. Threat register T-04-04's stated assertion ("the `extra="forbid"` grep criterion plus the shared config being on the single base class") is satisfied by the surviving `model_config` line.
- **Committed in:** `c43ae2b` (Task 2 commit)

**2. [Rule 2 - Missing Critical] The specified raw-SQL regex had a documented bypass**

- **Found during:** Task 3 (boundary test)
- **Issue:** The plan specified `_RAW_SQL_TEXT = re.compile(r"(?<![\w.])(?:sa\.)?text\s*\(")`. Its `(?<![\w.])` lookbehind blocks any dotted attribute access, and the optional group whitelists only the `sa.` alias — so `import sqlalchemy` followed by `sqlalchemy.text("...")` slips through silently. A static injection guard (T-04-01) with one spelling missing is a guard with a way around it, and the whole point of this test is catching what review cannot.
- **Fix:** Widened the optional group to `(?:(?:sa|sqlalchemy)\.)?` and extended the accompanying comment to record why both spellings are covered. This only makes the guard stricter — no legitimate analytics code is newly rejected.
- **Files modified:** `backend/tests/test_analytics_isolation.py`
- **Verification:** Negative control run against a throwaway module in `app/analytics/`: `text("SELECT 1")`, `sa.text("SELECT 1")` and `sqlalchemy.text("SELECT 1")` each turn `test_analytics_uses_no_raw_sql_text` red. The third would have passed under the plan's regex.
- **Committed in:** `22a0209` (Task 3 commit)

**3. [Rule 4 → resolved as scope, not architecture] `requirements mark-complete` deliberately not run**

- **Found during:** Post-execution state updates
- **Issue:** The plan frontmatter lists `requirements: [VOL-01, VOL-02, VOL-03, DQ-01, DQ-02]`, and the executor's default flow marks those complete in REQUIREMENTS.md. Two independent problems: (a) 04-02 *declares* the types for those requirements and computes nothing — no weekly volume, no per-muscle rollup and no frequency figure exists yet; marking them complete would put a false green in the traceability table that only 04-04..04-08 can honestly earn. (b) Sibling wave-1 plans 04-01 and 04-03 carry overlapping requirement IDs, so three parallel worktrees checking the same boxes would guarantee a three-way merge conflict on a shared file.
- **Fix:** Left REQUIREMENTS.md untouched and set `requirements-completed: []` in this summary's frontmatter, with an inline note recording that the requirements are *advanced* rather than *satisfied*. No architectural change was needed, so this did not warrant a checkpoint.
- **Files modified:** none (deliberate no-op)
- **Verification:** `git status --short` shows no REQUIREMENTS.md change; the requirement rows remain owned by the implementing plans.
- **Committed in:** n/a

---

**Total deviations:** 3 (1 blocking contradiction, 1 missing-critical guard hardening, 1 scope correction)
**Impact on plan:** No scope creep. Deviation 1 was forced — the plan could not be satisfied as literally written. Deviation 2 strengthens an existing security control by two characters. Deviation 3 prevents a false completion claim and a predictable merge conflict. Every field name, type, model and test name in the plan shipped exactly as specified.

## TDD Gate Compliance

Task 3 carried `tdd="true"`. The artifact under test *is* a test file, so the cycle was run as a negative control rather than a red-then-implement loop — the implementation that makes these assertions green (`__init__.py`, `schemas.py`) was already committed by Tasks 1 and 2.

- **RED:** 11 deliberate violations injected one at a time into a throwaway module under `app/analytics/`, plus the plan's exact criterion-8 case (`from app.mcp.server import mcp` appended to the committed `schemas.py`). All 11 turned the matching test red; the criterion-8 case produced `1 failed, 5 passed`. The `ANALYTICS` path was also repointed at an empty directory to confirm `test_the_walk_actually_finds_files` catches a vacuous walk.
- **GREEN:** Injection reverted with `git checkout -- backend/app/analytics/schemas.py`; `test_analytics_isolation.py` + `test_hevy_isolation.py` → 11 passed.
- **REFACTOR:** Not needed.
- **Gate commits:** `22a0209` is a `test(...)` commit; the `feat(...)` commits it constrains (`7a2fe44`, `c43ae2b`) precede it. Sequence inverted relative to the standard RED→GREEN ordering, for the reason above.

No throwaway artifact survived: `git status --short` after the control run showed only the (gitignored-by-intent) venv symlink and the new test file.

## Issues Encountered

- **No `.venv` in the parallel worktree.** Every acceptance and verify command in the plan is written against `.venv/bin/python`, and a fresh worktree has no virtualenv. Resolved by symlinking the main checkout's `.venv` into the worktree root so the plan's commands run verbatim; `pyproject.toml` sets `pythonpath = ["backend"]`, so `app` resolves against the worktree's source, not the main checkout's. The symlink is removed before returning and was never staged.
- **Worktree branch base was stale.** `git merge-base HEAD a8332d7` returned `1e97f3b`, i.e. the worktree branched from an older commit than the phase HEAD. Hard-reset to `a8332d71f7bbdfe64ff602e8e35bd929562ad204` per the startup check, verified, then proceeded. The worktree was clean, so nothing was lost.

## Verification Results

All 7 of the plan's verification steps pass:

| # | Check | Result |
|---|-------|--------|
| 1 | `pytest backend/tests/test_analytics_isolation.py -q` | 6 passed, exactly 6 collected |
| 2 | `pytest backend/tests/test_hevy_isolation.py -q` | 5 passed — its `rglob` walk now covers `app/analytics/` with no edit |
| 3 | `pytest -q -m "not integration"` | **183 passed** in 0.81s (baseline was 177 in 1.01s; +6 new, no regression, no slowdown) |
| 4 | `ruff check backend` | All checks passed |
| 5 | `mypy backend/app` | Success, no issues in 43 source files |
| 6 | Negative control performed and reverted | 11/11 red, then 11 passed after revert |
| 7 | `pyproject.toml` and `backend/migrations/` unmodified | `git status --short` clean for both |

Additionally `ruff format --check` reports all 3 new files already formatted.

## Threat Model Disposition

| Threat ID | Disposition | Status after this plan |
|-----------|-------------|------------------------|
| T-04-03 | mitigate | **Structural.** `FreshnessMetadata` declares one field; `last_error`/`status`/`cursor_page`/`cursor_timestamp` are unrepresentable, and `extra="forbid"` stops a caller smuggling them in. The runtime no-leak assertion is plan 04-04's. |
| T-04-04 | mitigate | **Done.** `hide_input_in_errors=True` on the single `_AnalyticsModel` base, inherited by all ten models. |
| T-04-08 | mitigate | **Done.** `test_analytics_never_names_the_muscle_tables_directly`, proven red against both `ExerciseMuscle` and `ExerciseMuscleOverride`. |
| T-04-09 | mitigate | **Done.** `test_analytics_never_writes`, proven red against `session.commit(`, `session.add_all(` and `from sqlalchemy import insert`. |
| T-04-01 | mitigate | **Done, and widened.** `test_analytics_uses_no_raw_sql_text`, proven red against all three `text(` spellings. |
| T-04-11 | accept | **Upgraded to mitigated** at no cost — `frozen=True` makes results immutable. |

No new security-relevant surface was introduced: no endpoint, no auth path, no file access, no schema change. No threat flags to raise.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

**Ready for the rest of wave 1 and for waves 2+:**

- `from app.analytics.schemas import ...` is stable. Plans 04-04 (weekly volume), 04-05 (muscle-group volume), 04-06/07 (frequency) and 04-08 can write expected values against fixed field names today.
- Any module those plans add under `app/analytics/` is covered by all six boundary assertions the moment the file exists — the walk is `rglob`, not a hand-maintained list. Two consequences worth flagging to the implementers:
  1. `func.timezone(tz, col)` is the only sanctioned way to get `users.timezone` into a query. `text()` in any spelling will fail the fast suite.
  2. Muscle resolution must call `app.normalization.resolver.effective_muscles_bulk`. Importing the ORM classes to build a join will fail the fast suite even though the numbers would match today.
- Prose convention for future analytics docstrings: refer to the muscle tables in lowercase (`exercise_muscles`), never by ORM class name, or the CamelCase ban will fire on documentation.

**Open items carried forward (not blockers for this plan):**

- `VOL-01`/`VOL-02`/`VOL-03`/`DQ-01`/`DQ-02` remain unchecked in REQUIREMENTS.md by design (Deviation 3). The implementing plans own those rows.
- RESEARCH open question A1 — whether a `duration`-modality set with no reps and no weight should count as a hard set in VOL-01 — is untouched here and still needs a user call in 04-04. The schema accommodates either answer without a field change.

## Self-Check: PASSED

Files verified present on disk:

- FOUND: `backend/app/analytics/__init__.py`
- FOUND: `backend/app/analytics/schemas.py`
- FOUND: `backend/tests/test_analytics_isolation.py`

Commits verified in `git log`:

- FOUND: `7a2fe44` feat(04-02): create app/analytics package with boundary docstring
- FOUND: `c43ae2b` feat(04-02): declare every Phase 4 public return type in analytics/schemas.py
- FOUND: `22a0209` test(04-02): add six static analytics boundary assertions to the fast suite

---
*Phase: 04-volume-frequency-analytics*
*Completed: 2026-08-30*
