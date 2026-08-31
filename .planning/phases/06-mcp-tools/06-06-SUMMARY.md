---
phase: 06-mcp-tools
plan: 06
subsystem: api
tags: [mcp, tools, progression, plateaus, personal-records, name-resolution, truncation]

# Dependency graph
requires:
  - phase: 06-mcp-tools
    provides: "_common.py — find_templates_by_title, safe_tool, read_only_session, resolve_user_id, window_from_weeks, truncate, MAX_* caps (plan 06-01)"
  - phase: 06-mcp-tools
    provides: "schemas.py — ExerciseCandidate, ExerciseProgressionResponse, PlateauResponse, PersonalRecordsResponse (plan 06-02)"
  - phase: 05-progression-records-recomposition-analytics
    provides: "get_exercise_progression, get_plateaus, DEFAULT_PLATEAU_LOOKBACK_WEEKS, get_personal_records"
provides:
  - "fitness_get_exercise_progression(ctx, exercise_name, weeks=12)"
  - "fitness_get_plateaus(ctx, lookback_weeks=12, plateaued_only=True)"
  - "fitness_get_personal_records(ctx, exercise_name, weeks=52)"
  - "The D-01/D-02 name-resolution block as an implemented, copyable shape for any future name-keyed tool"
affects: [06-08 tool registration, 06-09 schema/isolation guards, 06-10 payload budgets, 06-11 D-02 behavioural proof]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Name in, id resolved server-side: Annotated[str, Field(min_length=1, max_length=255)] + find_templates_by_title, never a template-id parameter"
    - "len(matches) != 1 short-circuits to matched=False + candidates; a successful result, never an exception"
    - "Tail truncation (points[-CAP:]) where recency is the question being asked, head truncation elsewhere"
    - "model_copy(update={...}) to narrow one field of an analytics result rather than rebuilding it field by field"
    - "Analytics functions that own a relative window keep it (D-05); only absolute-window functions get window_from_weeks"

key-files:
  created:
    - backend/app/mcp/tools/progression.py
    - backend/app/mcp/tools/records.py
  modified: []

key-decisions:
  - "The name-resolution block is duplicated verbatim across progression.py and records.py on purpose — the shared half is already in _common.find_templates_by_title; what remains is each tool's own response-model construction, and a helper covering both would be one function knowing two unrelated wire shapes"
  - "fitness_get_personal_records defaults weeks=52 rather than 12: a 12-week default would report a three-month best AS a personal record with the narrowing visible only in a parameter default"
  - "Personal records are NOT truncated, stated as a decision in the code — 5 records + <=12 reps-at-weight rows is 1,601 bytes structured, and the row count is bounded by the data rather than by the window"
  - "Progression points truncate from the TAIL: 'am I progressing?' is a question about recent sessions, so the head is what may be dropped"
  - "fitness_get_plateaus passes lookback_weeks straight through (D-05) — get_plateaus resolves its own anchor day in the user's timezone, and a start/end pair computed here would duplicate that and freeze an accruing duration"
  - "Plateau candidates re-sorted by (not plateaued, -duration, external_id) so the cap keeps the longest-standing plateaus and two runs over the same data cannot disagree"
  - "total_exercises counts the FILTERED candidate set, not the whole report, so '3 of 47 plateaued, showing 3' stays expressible"

requirements-completed: []

# Metrics
duration: 22min
completed: 2026-08-31
---

# Phase 6 Plan 06: Exercise-Keyed MCP Tools Summary

**Three read-only MCP tools — exercise progression, plateaus and personal records — where Claude names an exercise and never sees a Hevy template id, an ambiguous name returns its candidate list as a successful result rather than a guess or an error, and every list that can grow carries the cap flag and the true total beside it.**

## What Was Built

### `backend/app/mcp/tools/progression.py` (227 lines)

`fitness_get_exercise_progression(ctx, exercise_name, weeks=12)` and
`fitness_get_plateaus(ctx, lookback_weeks=12, plateaued_only=True)`.

The progression tool is where D-01 and D-02 are implemented for the first time in the phase:

- **D-01** — `exercise_name: Annotated[str, Field(min_length=1, max_length=255)]` is the only way
  in. `exercise_template_external_id` appears in this module exclusively as a *keyword argument* to
  the analytics function, never as a parameter of the tool. `grep -c 'exercise_template_external_id:'`
  returns `0` for both new modules.
- **D-02** — `len(matches) != 1` short-circuits to
  `ExerciseProgressionResponse(data_available=True, matched=False, candidates=[...])`. Zero matches
  gives an empty candidate list ("no such exercise"); two or more gives them all ("be more
  specific"). Neither path raises, so `is_error` stays false and the requested name never reaches
  Claude through the SDK's `str(e)` error-text channel.
- **Truncation** — the point series is cut to the most recent `MAX_PROGRESSION_POINTS` (60) via
  `result.points[-MAX_PROGRESSION_POINTS:]`, and the narrowed result is produced with
  `model_copy(update={"points": kept})` so a field added to `ExerciseProgressionResult` later cannot
  be silently dropped here. `points_truncated` and `total_points` travel with it.

`fitness_get_plateaus` is the one window-taking tool in the phase that does **not** call
`window_from_weeks` (D-05, commented at the call site precisely because every sibling does convert).
`get_plateaus` takes a relative lookback by design and resolves the anchor day in the user's
timezone itself. The `Field(ge=1, le=MAX_WEEKS)` bound is also what makes the analytics function's
own `ValueError("lookback_weeks must be positive")` unreachable from MCP (T-06-01). Results are
filtered by `plateaued_only`, re-sorted longest-standing-first with a total deterministic key, then
capped at `MAX_PLATEAU_EXERCISES` (30) with `exercises_truncated` / `total_exercises`. The window
and threshold are echoed from `PlateauReport` / `PlateauResult` rather than re-derived — PROG-03
requires them to travel with the verdict and a second copy of the threshold in this module is a
second copy that drifts.

### `backend/app/mcp/tools/records.py` (133 lines)

`fitness_get_personal_records(ctx, exercise_name, weeks=52)`. Same D-02 resolution semantics,
implemented as a deliberate second copy (documented in the module docstring), against its own
response model. Two decisions are written into the code rather than left implicit:

- `weeks` defaults to `MAX_WEEKS` (52), not the 12 the other tools use — "what is my PR" is an
  all-time-ish question, and a 12-week default would report a three-month best *as* a personal
  record.
- **No truncation**, stated as a decision: five records plus at most ~12 reps-at-weight rows is
  1,601 bytes structured / 3,940 on the wire, well inside the 8 KB budget, and the row count is
  bounded by the data rather than by the requested window. A permanently-false `*_truncated` flag is
  a field nobody reads and therefore one nobody would notice becoming true.

## Verification

| Check | Result |
| ----- | ------ |
| `uv run pytest backend/tests -x -q -m "not integration"` | 358 passed, 246 deselected |
| `uv run ruff check backend/app/mcp` | All checks passed |
| `uv run ruff format --check` (both new files) | already formatted |
| `uv run mypy backend/app/mcp/tools/progression.py backend/app/mcp/tools/records.py` | Success, no issues in 2 source files |
| `inspect.signature(fitness_get_exercise_progression)` | `['ctx', 'exercise_name', 'weeks']` |
| `inspect.signature(fitness_get_plateaus)` | `['ctx', 'lookback_weeks', 'plateaued_only']` |
| `inspect.signature(fitness_get_personal_records)` | `['ctx', 'exercise_name', 'weeks']`, `weeks` default `52` |
| `grep -c 'exercise_template_external_id:'` on both new modules | `0` (D-01) |
| `grep -rn 'str(e)\|str(exc)\|repr(e)'` on both new modules | no matches |
| `grep -c 'from sqlalchemy import text' records.py` | `0` |
| `git diff --stat pyproject.toml uv.lock` | no change |
| `grep -c '@safe_tool(degraded=' progression.py` | `2` |
| Call sites of `window_from_weeks` in `progression.py` | exactly `1` (the progression tool) |

Behavioural proof of the D-02 zero-match and multi-match paths lands in plan 06-11, as the plan
specifies; nothing in this plan asserts runtime behaviour against a database.

## Deviations from Plan

None material — the plan was executed as written. Two acceptance criteria are worth recording
because their literal grep form and their stated intent differ:

**1. `grep 'window_from_weeks' progression.py` "matches exactly once"**
- **Found during:** Task 2 verification
- **Situation:** The file matches three times: the import, the one call site in
  `fitness_get_exercise_progression`, and the D-05 comment in `fitness_get_plateaus` that the plan
  itself mandates ("Add that as a comment, because every other window-taking tool in the phase does
  convert"). A literal count of one is unsatisfiable given the plan's own instructions, since the
  import alone is required.
- **Resolution:** The intent — exactly one *call site*, in the progression tool only — is verified
  and holds (`grep -n` shows the call at one line). No code changed.

**2. Plan-level verification `grep -rn 'exercise_template_external_id:' backend/app/mcp/tools/` "returns nothing"**
- **Found during:** Final verification
- **Situation:** Two matches exist, both in `backend/app/mcp/tools/schemas.py` (plan 06-02):
  `ExerciseCandidate.exercise_template_external_id` and
  `WorkoutExerciseDetail.exercise_template_external_id`. These are *response* fields, and the first
  is required by this plan's own D-02 contract — the candidate list is useless without the id.
- **Resolution:** The rule is "never a tool *parameter*", and both modules this plan owns return
  `0`. Nothing in `schemas.py` was changed; removing those fields would break the disambiguation
  payload the plan asks for.

## Threat Mitigations Applied

| Threat | How |
| ------ | --- |
| T-06-04 (SQLi via `exercise_name`) | Resolution goes only through `_common.find_templates_by_title`, which compares `func.lower(col) == bound_param`; `Field(max_length=255)` matches the column and rejects longer input before any query; no `text(` import in either module |
| T-06-02 (cross-tenant name resolution) | `user_id` comes from `resolve_user_id(ctx)`, server-side, and is never a tool parameter; the title lookup filters on `user_id` AND `provider` |
| T-06-12 (silently answering about the wrong exercise) | D-02 short-circuit on `len(matches) != 1`, in both name-taking tools |
| T-06-01 (exception text / DSN reaching Claude) | `@safe_tool(degraded=...)` on all three tools, each with its own degraded factory; `Field(ge=1)` makes `get_plateaus`' own `ValueError` unreachable |
| T-06-03 (a write reaching the database) | `read_only_session(ctx)` in every body; no write construct imported |
| T-06-05 / T-06-11 (unbounded or silently-capped payloads) | `MAX_PROGRESSION_POINTS` tail-cut and `MAX_PLATEAU_EXERCISES` cap, each with a `*_truncated` + `total_*` pair; records documented as bounded by shape |

## Known Stubs

None. All three tools are fully wired to shipped analytics functions; no placeholder data, no empty
literals flowing to a response, no TODOs.

Registration into `MCPServer` is intentionally not here — `backend/app/mcp/server.py` is a
contended file in this parallel wave and plan 06-08 owns the tool registry.

## Threat Flags

None. Neither module opens a network endpoint, an auth path, a file-access pattern, or a schema
change; both are read-only adapters over existing analytics functions.

## Self-Check: PASSED

- `backend/app/mcp/tools/progression.py` — FOUND (227 lines, exports
  `fitness_get_exercise_progression`, `fitness_get_plateaus`)
- `backend/app/mcp/tools/records.py` — FOUND (133 lines, exports `fitness_get_personal_records`)
- Commit `8d99aa5` — FOUND
- Commit `73ac1b9` — FOUND
- Commit `6e5046a` — FOUND
