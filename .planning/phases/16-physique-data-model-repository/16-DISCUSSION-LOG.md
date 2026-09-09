# Phase 16: Physique Data Model & Repository - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-09
**Phase:** 16-physique-data-model-repository
**Areas discussed:** Migration scope for 'superseded' (PHYS-08); Confounder metadata storage
shape; Free-text field length caps; Rating row completeness per observation

---

## Gray areas presented (single combined multiSelect turn)

| Option | Description | Selected |
|--------|-------------|----------|
| Migration scope for 'superseded' (PHYS-08) | Whether migration 0007 includes Phase 17's supersede/reason columns now, given ROADMAP never names a migration beyond 0007 anywhere in the milestone | (see below) |
| Confounder metadata storage shape | How "photo angles present" and pose_state get stored — booleans, array, CSV — and whether the CHECK-not-native-ENUM rule extends to pose_state | (see below) |
| Free-text field length caps | Concrete character limits for leanness/conditioning/symmetry notes and the Not-Assessable reason text | (see below) |
| Rating row completeness per observation | Always exactly 19 rows (uniform, NA where unratable) vs. only rows for groups actually visible | (see below) |

**User's response:** "Lets go with you recommendation/decision" — the user did not select
individual options or discuss areas one at a time. This was treated as an explicit delegation
of all four questions to Claude's judgment, not as an empty/skip response, per the instruction
to read answers carefully and follow what they actually say.

**Resulting approach:** Rather than silently picking defaults, each of the four areas was
resolved with a concrete, named decision (D-01 through D-08 in CONTEXT.md), each carrying its own
stated rationale grounded in ROADMAP wording, prior-phase precedent, or existing codebase
patterns — so a downstream agent can inspect *why* each call was made, not just *what* was
decided.

## Decisions made under delegation

1. **Migration scope (D-01):** Migration 0007 includes PHYS-08's `superseded_at`,
   `superseded_reason`, `superseded_by_id` columns now, built but unused until Phase 17.
   Rationale: ROADMAP names no migration beyond 0007 anywhere in the v2.1 milestone; Phase 19's
   goal is deploying "this milestone's own migration" (singular).

2. **Confounder metadata (D-02, D-03):** `pose_state` as a `StrEnum` + named CHECK constraint
   (`relaxed` / `lightly_flexed`); `photo_angles_present` as `ARRAY(String(16))` + CHECK,
   reusing the exact pattern already in `exercise_templates.secondary_muscle_groups`.

3. **Free-text caps (D-04, D-05, D-06):** Notes fields (leanness/conditioning/symmetry) at
   `String(500)` each; per-rating `Not Assessable` reason at `String(160)` (mirrors the spike's
   own "20 words maximum" convention); confounder `conditions_note` at `String(200)`.

4. **Rating completeness (D-07, D-08):** Every observation writes exactly 19 rating rows
   (one per `CanonicalMuscleGroup`), never a variable subset — justified directly by ROADMAP's
   own "without special-casing" wording for abductors/adductors. A named unique constraint on
   `(observation_id, muscle_group)` enforces this at the database level.

## Claude's Discretion

- Exact table/column names beyond what's specified (follow existing snake_case conventions)
- Migration filename (`0007_physique_observations.py`, following the `NNNN_description.py`
  pattern)
- Repository function surface beyond "insert and read back" (mirror `programs.py`'s shape)
- Physical location of the four Phase-15 constants (values are fixed verbatim regardless of
  which module holds them)

## Deferred Ideas

None — no scope-creep arose. The one substantive question (migration scope) was a boundary
clarification within already-committed milestone scope, not a new capability.
