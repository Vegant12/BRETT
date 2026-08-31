---
phase: 06-mcp-tools
plan: 02
subsystem: api
tags: [mcp, pydantic, schemas, structured-output, decimal]

# Dependency graph
requires:
  - phase: 04-volume-frequency-analytics
    provides: WeeklyVolumeResult, MuscleGroupFrequency, ExerciseFrequency, CoverageMetadata, FreshnessMetadata
  - phase: 05-progression-records-recomposition-analytics
    provides: ExerciseProgressionResult, PlateauResult, PersonalRecordsResult, PeriodComparisonResult, BodyWeightTrendResult, RecompositionResult
  - phase: 03-hevy-integration-normalization
    provides: CanonicalMuscleGroup taxonomy, workouts/workout_exercises/sets column types
provides:
  - "_McpModel base mirroring _AnalyticsModel's ConfigDict (frozen, extra-forbid, hide_input_in_errors)"
  - "Thirteen *Response models — the wire contract every Phase 6 tool returns"
  - "Nested projection models for the workout tree (WorkoutSummary, WorkoutDetail, WorkoutSetDetail, WorkoutExerciseDetail)"
  - "MuscleGroupRollup — the per-window muscle reshape used by both fitness_get_muscle_group_volume and fitness_get_training_summary"
  - "data_available convention that makes safe_tool's degraded payload schema-valid and honest"
  - "ExerciseCandidate + matched/candidates disambiguation shape that keeps D-02 out of the is_error channel"
affects: [06-mcp-tools remaining plans, mcp tool adapters, _common.safe_tool, test_mcp_isolation]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Response wrapper composes an analytics result as an optional field; never restates its arithmetic"
    - "No union RETURN annotations — mcp 2.0.0 sets wrap_output=True for unions and would nest structured_content under 'result'"
    - "Every truncatable list carries an explicit *_truncated: bool + total_*: int pair"
    - "Degraded-form construction proven by a generic annotation-driven builder rather than a per-model fixture"

key-files:
  created:
    - backend/app/mcp/tools/schemas.py
    - backend/tests/test_mcp_schemas.py
  modified: []

key-decisions:
  - "MuscleGroupRollup reshapes MuscleGroupVolumeResult to per-window totals — the one deliberate break of CONTEXT.md's compose-don't-reshape rule, documented at the model itself"
  - "workout_id carries workouts.external_id only; the internal surrogate UUID appears in no response model"
  - "matched=False with candidates is a SUCCESSFUL result, not an error — disambiguation must never travel through the SDK's is_error channel"
  - "List fields are declared required with no `= []` default, so a constructor that forgets one is a ValidationError at test time rather than a silently empty list in production"
  - "REQUIREMENTS.md left untouched: MCP-02/03/06 are not satisfied by schemas alone and the file is contended in this parallel wave"

patterns-established:
  - "_McpModel: shared ConfigDict as a security control, not a style choice — hide_input_in_errors is the only defence against a ValidationError raised inside the SDK's convert_result"
  - "Module-walk test discovery (vars(schemas) filtered to _McpModel subclasses named *Response) plus a guard-on-the-guards floor assertion"

requirements-completed: []

# Metrics
duration: 18min
completed: 2026-08-31
---

# Phase 6 Plan 02: MCP Response Schemas Summary

**Thirteen frozen, extra-forbidding Pydantic response models that compose the shipped analytics results verbatim, carry `data_available` so a database outage cannot masquerade as "you trained zero sets", and are proven degraded-constructible by an annotation-driven module walk.**

## Performance

- **Duration:** ~18 min
- **Tasks:** 3
- **Files modified:** 2 (both created)
- **Tests:** 40 passing in `test_mcp_schemas.py`; 297 passing in the full fast suite

## Accomplishments

- `_McpModel` mirrors `_AnalyticsModel`'s `ConfigDict` exactly, with a docstring stating why `hide_input_in_errors` matters *doubly* in `app/mcp/`: an output-model `ValidationError` is raised inside the SDK's `convert_result`, outside `safe_tool`'s reach, and its default message renders weekly tonnage and body-composition-adjacent numbers into the text handed to Claude (T-06-01).
- Thirteen `*Response` models plus seven nested projection models, all composing `app/analytics/schemas.py` results as fields rather than reshaping them — with the single exception documented at the model that performs it.
- `MuscleGroupRollup` records the measured justification for the one reshape: the per-week × per-muscle grid is 988 rows / ~347,707 wire bytes at D-04's 52-week cap versus 19 rows / ~7,851 bytes rolled up, and its docstring carries the non-additive-sessions rule (summing per-week session counts inflated 14 of 16 muscle groups by up to 4.0×, verified against `analytics/frequency.py`'s module docstring).
- `TrainingSummaryResponse.recomposition_disclaimer` is a declared field and appears in the model's JSON-schema `required` list, closing T-06-09.
- `test_mcp_schemas.py` discovers response models by walking the module, so a fourteenth tool's model is covered the moment it exists; the walk itself is guarded by a `>= 12` floor assertion so an empty collection cannot make the other checks vacuously true.

## Task Commits

1. **Task 1: `_McpModel` base and the straight-compose response models** — `8d513d9` (feat)
2. **Task 2: workout projections, muscle rollup and training summary models** — `21153ce` (feat)
3. **Task 3: `backend/tests/test_mcp_schemas.py`** — `56f504a` (test)

## Files Created/Modified

- `backend/app/mcp/tools/schemas.py` (367 lines) — `_McpModel` + 13 `*Response` models + `WorkoutSummary`, `WorkoutSetDetail`, `WorkoutExerciseDetail`, `WorkoutDetail`, `MuscleGroupRollup`, `SummaryVolumeWeek`, `ExerciseCandidate`. No `float` anywhere; `Decimal | None` only.
- `backend/tests/test_mcp_schemas.py` (222 lines) — container-free, unmarked, never imports `app.mcp.server`. Six test functions, 40 parametrized cases.

## Decisions Made

- **Degraded-form construction is derived from annotations, not hardcoded per model.** The plan listed the exact kwargs per model; a hardcoded table would go stale the first time a field is added and the test would keep passing while checking a shape that no longer exists. `_degraded_kwargs` walks `model_fields` and *raises* on an annotation it cannot degrade, so a new required field with no degraded value fails the test rather than being skipped.
- **`plateaued_only=True` is the only non-zero degraded value**, recorded in a one-entry `_DEGRADED_OVERRIDES` map with the reason inline: it echoes the tool's default filter, and a degraded payload claiming the caller asked for every exercise would misreport the request it is degrading.
- **`instance.model_dump()["data_available"]` rather than attribute access** in the degraded-form test — `_McpModel` does not declare `data_available`, so attribute access would need a `type: ignore` and `warn_unused_ignores = true` makes stale ignores an error.
- **REQUIREMENTS.md not touched.** MCP-02 requires the server to *expose* the eleven tools and MCP-03/MCP-06 are properties of tool *responses at runtime*; this plan ships only the type contract. Marking them complete here would be a false claim, and the file is being edited by sibling worktree agents in the same wave. `requirements-completed` is deliberately empty; the orchestrator or a later plan in this phase should mark them once the tools ship.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Restored the missing `supersets_id` field on `WorkoutExerciseDetail`**
- **Found during:** Task 2 (workout projection models)
- **Issue:** The first write of `WorkoutExerciseDetail` omitted `supersets_id: int | None`, which the plan's model spec, the `must_haves` interface block, and `workout_exercises.supersets_id` in `db/models/workout.py` all require. Without it a superset — two exercises performed alternately — is indistinguishable from two ordinary consecutive exercises in the D-11 detail view, which is a materially wrong description of the session.
- **Fix:** Added `supersets_id: int | None` between `exercise_template_external_id` and `sets`, matching the plan's field order.
- **Files modified:** `backend/app/mcp/tools/schemas.py`
- **Verification:** `uv run ruff check` and `uv run mypy` clean; field present in the model's JSON schema.
- **Committed in:** `21153ce` (Task 2 commit — caught before the commit was made)

**2. [Rule 3 - Blocking] Split the analytics enum/taxonomy imports across the two task commits**
- **Found during:** Task 1
- **Issue:** `ProgressionSignal`, `RecompositionStatus`, `TrendVerdict` and `CanonicalMuscleGroup` are only used by the Task 2 models. Importing them in Task 1 would have left `8d513d9` failing `ruff check` with F401, breaking the plan's own per-task `<verify>` gate and leaving a non-lint-clean commit in history.
- **Fix:** Task 1 imports only what it uses; Task 2's edit extends the import block.
- **Files modified:** `backend/app/mcp/tools/schemas.py`
- **Verification:** `ruff check` clean at both `8d513d9` and `21153ce`.
- **Committed in:** `8d513d9` / `21153ce`

**3. [Rule 3 - Blocking] Installed dev dependencies into the worktree venv**
- **Found during:** Task 1 verification
- **Issue:** The fresh worktree had no `.venv`; `uv run ruff` failed with "Failed to spawn: ruff" because the implicit sync installed only the runtime group.
- **Fix:** `uv sync --all-extras --dev`.
- **Files modified:** None — `.venv/` is gitignored; `git diff --stat pyproject.toml uv.lock` is empty, as the plan's verification requires.
- **Verification:** `uv run ruff check` and `uv run mypy` both run.
- **Committed in:** N/A (no tracked file changed)

---

**Total deviations:** 3 auto-fixed (1 bug, 2 blocking)
**Impact on plan:** All three were necessary to make the plan's own acceptance criteria and per-task verify gates pass. No scope creep — no model, field or test beyond the plan's spec was added, and the two extra tests (`test_response_models_are_pydantic_models`, plus the parametrization of the three per-model checks) are refinements of the six the plan listed, not new surface.

## Issues Encountered

- **The worktree branch was based on a stale commit.** `git merge-base HEAD 38088b1` returned `1e97f3b` ("chore(02-05): record auto-chain flag"), i.e. the worktree branch had been cut from an older point rather than from the phase-06 feature HEAD. Resolved by the mandated `git reset --hard 38088b1` at agent start, before any file was touched. This is why the three task commits sit directly on `38088b1`.

## Verification Results

| Check | Result |
|---|---|
| `uv run pytest backend/tests/test_mcp_schemas.py -q` | 40 passed |
| `uv run pytest backend/tests -q -m "not integration"` | 297 passed, 236 deselected — no regression |
| `uv run ruff check backend/app/mcp backend/tests/test_mcp_schemas.py` | All checks passed |
| `uv run ruff format --check` | 2 files already formatted |
| `uv run mypy backend/app/mcp/tools/schemas.py backend/tests/test_mcp_schemas.py` | Success, no issues |
| `git diff --stat pyproject.toml uv.lock` | empty — no dependency change |
| `grep -P '(?<![\w.])float\s*\(\|:\s*float\b\|->\s*float\b'` on `schemas.py` | 0 matches |
| `TrainingSummaryResponse.model_json_schema()['required']` | includes `recomposition_disclaimer` |
| All 20 `must_haves.exports` defined exactly once | confirmed via `grep -nE '^class '` |

## Known Stubs

None. This plan ships a type contract only — no tool body, no data source, and no placeholder value flows to a rendered surface. The `| None` payload fields (`volume`, `progression`, `records`, `trend`, `recomposition`, `workout`) are the *designed* degraded representation guarded by `data_available`, not unwired stubs; `test_every_response_model_has_a_constructible_degraded_form` asserts exactly that shape.

## Threat Flags

None. No new network endpoint, auth path, file access or schema change at a trust boundary. The plan's `<threat_model>` dispositions are all satisfied:

| Threat | Mitigation shipped |
|---|---|
| T-06-01 (ValidationError leaks `input_value`) | `_McpModel` sets `hide_input_in_errors=True`; asserted per model by `test_every_response_model_is_frozen_and_forbids_extras` |
| T-06-01 (invalid degraded payload → second unguarded exception) | `test_every_response_model_has_a_constructible_degraded_form` |
| T-06-05 (unbounded nested list) | every truncatable list carries `*_truncated` + `total_*`; `MuscleGroupVolumeResponse` bounded at 19 rows by the taxonomy |
| T-06-09 (dropped recomposition disclaimer) | `recomposition_disclaimer` declared and in `required`; `RecompositionResponse` embeds `RecompositionResult` whole |
| T-06-08 (internal surrogate key exposure) | `workout_id: str` carries `workouts.external_id`; `grep 'workout_id: uuid'` returns nothing |

## User Setup Required

None — no external service configuration.

## Next Phase Readiness

Ready. The wire contract every remaining Phase 6 tool adapter returns is now fixed and statically enforced. Notes for the plans that consume it:

- `_common.safe_tool` must construct its degraded payload with `data_available=False` and the same shape `_degraded_kwargs` proves is valid; if `safe_tool` grows a per-tool fallback table, it should reuse that builder's logic rather than duplicate it.
- Tool functions must annotate their return as a single `*Response` model. Any union, list, tuple or scalar return annotation flips `wrap_output=True` in `mcp 2.0.0` and nests `structured_content` under `"result"` on every call, including successes.
- `MuscleGroupRollup.sessions` / `.sessions_per_week` must be sourced from `get_training_frequency`, never summed from the per-week grid.
- Plan 06-09's `test_mcp_isolation.py` should carry the `_FLOAT_USE` regex across all of `app/mcp/`; `test_mcp_schemas.py::test_no_response_model_uses_float` is the module-scoped version and can be retired or kept as a fast local guard.
- MCP-02, MCP-03 and MCP-06 remain unmarked in `REQUIREMENTS.md` — see Decisions Made.

## Self-Check: PASSED

- `backend/app/mcp/tools/schemas.py` — FOUND
- `backend/tests/test_mcp_schemas.py` — FOUND
- Commit `8d513d9` — FOUND
- Commit `21153ce` — FOUND
- Commit `56f504a` — FOUND

---
*Phase: 06-mcp-tools*
*Plan: 02*
*Completed: 2026-08-31*
