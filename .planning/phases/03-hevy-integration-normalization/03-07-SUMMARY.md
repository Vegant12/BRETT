---
phase: 03-hevy-integration-normalization
plan: 07
subsystem: database
tags: [hevy, normalization, sqlalchemy, postgres, muscle-taxonomy, override, testcontainers]

# Dependency graph
requires:
  - phase: 03-03
    provides: "CanonicalMuscleGroup / MuscleRole / MappingSource taxonomy, derive_assignments(), DEFAULT_ROLE_WEIGHTS"
  - phase: 03-04
    provides: "exercise_templates / exercise_muscles / exercise_muscle_overrides tables and the sync_state repository"
  - phase: 03-05
    provides: "HevyClient.get_exercise_templates() and PAGE_SIZE_EXERCISE_TEMPLATES=100"
provides:
  - "sync_exercise_templates(): walks /v1/exercise_templates and persists Hevy's raw template metadata"
  - "replace_exercise_muscles(): materialises the canonical muscle map from curated code on every sync"
  - "effective_muscles() / effective_muscles_bulk(): query-time override-replaces-base resolution"
  - "set_override() / clear_override(): auditable manual corrections that never mutate the derived rows"
  - "unmapped_template_ids(): curation-gap report computed by absence"
  - "apply_weights(): NORM-03 direct/indirect weighting as an argument, not a column"
affects: [04-analytics, 05-mcp-tools, 03-11-curation]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Raw provider values and derived canonical values live in separate tables so the derivation is auditable"
    - "Override-replaces-base per template (not per row), which is what makes muscle REMOVAL expressible"
    - "Per-row SAVEPOINT quarantine inside a page loop so one bad record cannot fail a page of 100"
    - "Bulk resolution in two queries for a whole set of templates, never two queries per template"

key-files:
  created:
    - backend/app/integrations/hevy/templates.py
    - backend/app/normalization/resolver.py
    - backend/tests/test_hevy_templates.py
    - backend/tests/test_normalization_mapping.py
  modified: []

key-decisions:
  - "The page-size cap is referenced only as HevyClient.PAGE_SIZE_EXERCISE_TEMPLATES; templates.py contains no page-size literal, so there is exactly one place to be wrong"
  - "clear_override counts deletions with RETURNING rather than Result.rowcount, which the async execute() signature does not expose"
  - "set_override with an empty assignment list writes nothing and returns 0; clear_override is the honest spelling of 'no override'"
  - "EffectiveMuscle.source reports MappingSource.OVERRIDE for every overridden row regardless of the stored base source, because that is the answer to 'why does Phase 4 believe this'"

patterns-established:
  - "Materialised-view-of-code: exercise_muscles is recomputed from app.normalization on every sync and never hand-edited"
  - "Failure by absence, not by status column: 'unmapped' is derived from having no rows in either mapping table"
  - "Loud enum decoding: a stored value outside the taxonomy raises ValueError naming the column and value, never the user"

requirements-completed: [HEVY-06, HEVY-09, NORM-01, NORM-02, NORM-03]

# Metrics
duration: 42min
completed: 2026-08-29
---

# Phase 3 Plan 7: Exercise Templates and Muscle Mapping Summary

**Hevy's flat `shoulders` bucket resolved into front/side/rear deltoid heads on the way into Postgres, with a manual override layer that replaces the derived set without touching it.**

## Performance

- **Duration:** ~42 min
- **Tasks:** 3
- **Files created:** 4
- **Tests:** 24 added (12 template-sync integration, 10 resolver integration, 2 pure) — full suite 219 passed

## Accomplishments

- `sync_exercise_templates` walks `/v1/exercise_templates` at the endpoint's real cap of 100 (not the 10 every other Hevy endpoint uses), stores Hevy's `primary_muscle_group` / `secondary_muscle_groups` verbatim as NORM-02's audit baseline, and materialises the canonical mapping in a second table.
- The NORM-01 split is proven end to end against a real Postgres container: `Lateral Raise (Dumbbell)` → `side_delts/direct/curated`, and `Bench Press (Barbell)`'s secondary `shoulders` → `front_delts/indirect/curated` with `side_delts` and `rear_delts` provably absent.
- The override layer resolves per template, not per row, so "this exercise does not actually work rear delts" is expressible — and `test_base_rows_survive_an_override_unchanged` asserts the derived rows including `created_at` are byte-identical afterwards, which is what makes the audit real rather than aspirational.
- A custom `full_body` template maps to zero rows, is named in `TemplateSyncResult.unmapped`, and the sync still closes with `status='idle'` (D-03).
- HEVY-09 verified in the direction that matters: syncing templates alone leaves the `workouts` freshness row NULL.

## Task Commits

1. **Task 1: Exercise template sync and muscle-mapping materialisation** — `402f634` (test, RED), `ccd6374` (feat, GREEN)
2. **Task 2: Effective-mapping resolver with auditable override** — `4785e0c` (test, RED), `2a0ea98` (feat, GREEN)
3. **Task 3: Template sync integration suite** — `54f5213` (test)

No `refactor` commit: neither GREEN implementation needed cleanup that changed behaviour.

## Files Created/Modified

- `backend/app/integrations/hevy/templates.py` (292 lines) — `TemplateSyncResult`, `upsert_exercise_template`, `replace_exercise_muscles`, `sync_exercise_templates`. Transport-adjacent; lives inside the Hevy package because the persistence decisions here are provider-shaped.
- `backend/app/normalization/resolver.py` (287 lines) — `EffectiveMuscle`, `effective_muscles`, `effective_muscles_bulk`, `unmapped_template_ids`, `set_override`, `clear_override`, `apply_weights`. Imports nothing from `app.integrations`; `test_hevy_isolation.py` still passes.
- `backend/tests/test_hevy_templates.py` — 12 integration tests, HTTP transport mocked, pagination/upsert/normalization all real.
- `backend/tests/test_normalization_mapping.py` — 10 integration + 2 pure tests. The two `apply_weights` tests deliberately carry no integration marker so NORM-03 stays verifiable without Docker.

## Decisions Made

- **Page size is referenced, never restated.** `templates.py` contains no page-size literal at all; it logs `HevyClient.PAGE_SIZE_EXERCISE_TEMPLATES`. A second copy of `100` is the kind of constant that drifts silently and costs ~40 requests per sync when it does.
- **`clear_override` counts with `RETURNING`.** `AsyncSession.execute()` is typed as `Result`, which has no `rowcount`; `DELETE ... RETURNING id` gives the exact count from Postgres with no cast and no type ignore.
- **`set_override([])` writes nothing and returns 0.** An "empty override" cannot be represented — with zero rows the base becomes effective again — so the honest spelling of that intent is `clear_override`, and the empty-list path simply does not pretend otherwise.
- **Overridden rows always report `MappingSource.OVERRIDE`.** The stored base source is deliberately discarded in the resolved result: the question a caller is asking is "why does Phase 4 believe this exercise trains rear delts", and the answer is "a human said so".

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Reworded two docstrings that would have failed the plan's own acceptance greps**

- **Found during:** Task 1
- **Issue:** The plan supplied verbatim docstring text for `templates.py` containing the literal `pageSize` and the literal `ExerciseMuscleOverride`, while the same task's acceptance criteria required `grep -q 'pageSize' … exits 1` and `grep -q 'ExerciseMuscleOverride' … exits 1`. Copying the prose as written would have failed the task's own verification.
- **Fix:** Reworded to "caps its page size at **100**" and "override rows are never touched here", preserving both meanings. Added a sentence pointing at `PAGE_SIZE_EXERCISE_TEMPLATES` as the single source of the cap, which also satisfies the `must_haves` `contains:` check.
- **Files modified:** `backend/app/integrations/hevy/templates.py`
- **Verification:** Both greps now exit as the criteria require; `PAGE_SIZE_EXERCISE_TEMPLATES` present.
- **Committed in:** `ccd6374`

**2. [Rule 2 - Missing Critical] `updated_at` set explicitly in the template `ON CONFLICT DO UPDATE`**

- **Found during:** Task 1
- **Issue:** SQLAlchemy's `onupdate=func.now()` fires for an `update()` statement but is **not** injected into an `ON CONFLICT DO UPDATE SET` clause. Without it, `exercise_templates.updated_at` would freeze at row creation and the audit timestamp would silently lie about when Hevy last changed a template.
- **Fix:** Added `"updated_at": func.now()` to the `set_` dict, matching the convention already documented in `app/db/repositories/sync_state.py::_upsert`.
- **Files modified:** `backend/app/integrations/hevy/templates.py`
- **Verification:** Idempotency test re-syncs and still passes; convention matches the established repository helper.
- **Committed in:** `ccd6374`

**3. [Rule 3 - Blocking] `clear_override` switched from `Result.rowcount` to `DELETE … RETURNING`**

- **Found during:** Task 2
- **Issue:** The plan's return contract ("Returns rows deleted") pointed at `rowcount`, which mypy rejects: `AsyncSession.execute()` is typed as `Result[Any]`, and `rowcount` lives on `CursorResult`. `uv run mypy backend/app` failed.
- **Fix:** `delete(...).returning(ExerciseMuscleOverride.id)` via `session.scalars`, returning `len(...)`. No cast, no `type: ignore`, and Postgres supplies the exact count.
- **Files modified:** `backend/app/normalization/resolver.py`
- **Verification:** `uv run mypy backend/app` → success (36 files); `test_clear_override_restores_the_base_mapping` asserts the returned count.
- **Committed in:** `2a0ea98`

**4. [Rule 3 - Blocking] Task 1's RED test written as a subset of Task 3's suite**

- **Found during:** Task 1
- **Issue:** Task 1 is marked `tdd="true"` and its `<verify>` runs `backend/tests/test_hevy_templates.py`, but that file is Task 3's deliverable — the plan is circular as written.
- **Fix:** Task 1's RED commit created `test_hevy_templates.py` containing the six behaviours listed in Task 1's own `<behavior>` block; Task 3 then extended the same file to the full 12 named tests. Both tasks retain a genuine failing-first gate and the file is never written twice.
- **Files modified:** `backend/tests/test_hevy_templates.py`
- **Verification:** RED confirmed at `402f634` (`ModuleNotFoundError: app.integrations.hevy.templates`); GREEN at `ccd6374`; all 12 plan-named tests present at `54f5213`.
- **Committed in:** `402f634`, `54f5213`

---

**Total deviations:** 4 auto-fixed (1 missing-critical, 3 blocking)
**Impact on plan:** No scope change. Three were internal contradictions in the plan text (its own greps, its own type contract, its own task ordering); one was a persistence-correctness fix consistent with an existing repo convention.

## Issues Encountered

- `backend/app/integrations/hevy/workouts.py` (plan 03-06, same wave) does not exist in this worktree, so its sync-driver shape could not be read directly. The structure described in the plan's `<interfaces>` block was followed instead: run opened in its own transaction, per-page commit with the checkpoint in the same transaction, error recorded without resetting the cursor, close with `complete_sync(..., cursor_page=None)`. Worth a look at merge time to confirm the two drivers really do read the same way.

## Known Stubs

None. Every function has a real implementation with database-backed test coverage.

## Threat Flags

None. This plan adds no network endpoint, no auth path, and no new trust boundary — the sync is outbound-only through the existing `HevyClient`, and the resolver is a read/write layer over tables that already existed. The five threats in the plan's register (T-03-28 … T-03-32) are all mitigated and covered:

| Threat | Covering test |
|---|---|
| T-03-28 tampering via upstream recategorisation | `test_raw_hevy_muscle_groups_are_preserved` |
| T-03-29 override auditability | `test_base_rows_survive_an_override_unchanged` |
| T-03-30 cross-user mapping resolution | `test_override_is_scoped_to_the_user` |
| T-03-31 stored value outside the enum | `test_unknown_stored_muscle_value_raises` |
| T-03-32 logging on skipped template | `hevy_template_skipped` logs `type(exc).__name__` only, never `str(exc)` |

## Verification

- `uv run pytest backend/tests -q` → **219 passed**
- `uv run mypy backend/app` → success, 36 source files
- `uv run ruff check .` → all checks passed
- `uv run pytest backend/tests/test_hevy_isolation.py -q` → 5 passed (`app/normalization/` still imports nothing from `app.integrations`)

## Next Phase Readiness

- Phase 4's per-muscle volume (VOL-02) now has its input: `effective_muscles_bulk` resolves a whole training week in two queries, and `apply_weights` takes the 1.0/0.5 mapping as an argument so "what if indirect counted 0.3?" needs no migration.
- `CURATED_BY_TEMPLATE_ID` in `exercise_map.py` is still empty by design. Plan 03-11 populates it from real template ids after a live sync; until then the title tables carry the split, which is what the deltoid tests exercise.
- `unmapped_template_ids` is the curation-gap report and has no caller yet. A CLI or MCP surface for it is not in this plan's scope.

## Self-Check: PASSED

All four created source files exist on disk and all five task commits (`402f634`, `ccd6374`,
`4785e0c`, `2a0ea98`, `54f5213`) are present in `git log`.

---
*Phase: 03-hevy-integration-normalization*
*Completed: 2026-08-29*
