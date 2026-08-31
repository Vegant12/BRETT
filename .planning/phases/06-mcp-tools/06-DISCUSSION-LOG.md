# Phase 6: MCP Tools - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-08-31
**Phase:** 06-mcp-tools
**Areas discussed:** Exercise identification, Time-window parameters, Training summary & recent-workouts scope, Response size budget

---

## Exercise identification

| Option | Description | Selected |
|--------|-------------|----------|
| Name lookup | Tool accepts exercise name, case-insensitive match against `exercise_templates.title`, resolves to `external_id` internally | ✓ |
| External ID only | Tool requires exact `exercise_template_external_id` | |
| Accept either | Tool resolves either an external_id or a name | |

**User's choice:** Name lookup.
**Notes:** Chosen because Claude should never need to know an opaque Hevy template ID exists.

| Option | Description | Selected |
|--------|-------------|----------|
| Return all matches, no data | Ambiguous name match returns candidate list, computes nothing | ✓ |
| Auto-pick most-recently-used | Silently resolves to the most recently trained matching template | |
| Auto-pick, but flag it | Same auto-pick, with a note in the response that a choice was made | |

**User's choice:** Return all matches, no data.
**Notes:** No silent auto-pick — a wrong-exercise answer with no signal is worse than an extra round trip.

---

## Time-window parameters

| Option | Description | Selected |
|--------|-------------|----------|
| Weeks-back, relative | `weeks=N`, MCP layer converts to start/end days ending today | ✓ |
| Explicit start/end dates | Tool takes ISO date strings directly, no conversion layer | |
| Weeks-back with date override | `weeks=N` primary, optional explicit-date override | |

**User's choice:** Weeks-back, relative.
**Notes:** Matches every blueprint example (`weeks=12`, `weeks=8`). Claude never computes a date. New weeks→dates conversion logic must be built — doesn't exist in the analytics layer today.

| Option | Description | Selected |
|--------|-------------|----------|
| Keep explicit dates for compare_periods | period_a/period_b start/end as ISO dates, matches blueprint example verbatim | ✓ |
| Weeks-back pairs | Two weeks=N-style params computed relative to today | |

**User's choice:** Keep explicit dates.
**Notes:** "Compare August to July" can't be expressed as two relative weeks=N values.

*Follow-up: default weeks value, max weeks, and timezone-anchoring questions were offered but the user moved to the next area without raising them — left to Claude's discretion, captured as such in CONTEXT.md.*

---

## Training summary & recent-workouts scope

| Option | Description | Selected |
|--------|-------------|----------|
| Volume + frequency + recomposition | Recent-window volume, per-muscle volume/frequency, current recomposition verdict | ✓ |
| Everything, one big call | Same plus recent PRs and active plateaus | |
| Minimal: volume + frequency only | No recomposition verdict | |

**User's choice:** Volume + frequency + recomposition.
**Notes:** Directly answers PROJECT.md's Core Value questions in one call; PRs/plateaus stay on their own dedicated tools.

| Option | Description | Selected |
|--------|-------------|----------|
| Workout-level summary | date, title, duration, exercise count, hard sets, tonnage — no per-set breakdown | ✓ |
| Full exercise/set breakdown | Every workout expands to full exercise/set detail | |

**User's choice:** Workout-level summary.

| Option | Description | Selected |
|--------|-------------|----------|
| Not this phase | fitness_get_workout deferred — not named in ROADMAP's 11-tool success criterion | |
| Include it | Add fitness_get_workout(workout_id) as a 12th tool, matching blueprint §29 | ✓ |

**User's choice:** Include it.
**Notes:** Diverges from the recommended default. Recorded in CONTEXT.md D-11 as a deliberate choice, not scope creep — blueprint §29 explicitly lists it and CLAUDE.md treats the blueprint as authoritative for MCP tool names, even though ROADMAP's success-criterion sentence doesn't name it individually.

| Option | Description | Selected |
|--------|-------------|----------|
| Count-based limit | limit=N for fitness_get_recent_workouts | ✓ |
| Days-based limit | days=N | |

**User's choice:** Count-based.
**Notes:** Bounds response size by construction regardless of training frequency.

| Option | Description | Selected |
|--------|-------------|----------|
| Hevy external workout id | fitness_get_workout keyed by the id recent_workouts echoes per item | ✓ |
| Date | Keyed by calendar date | |

**User's choice:** Hevy external workout id.
**Notes:** Avoids needing a same-day-multiple-workouts policy.

---

## Response size budget

| Option | Description | Selected |
|--------|-------------|----------|
| Per-tool item caps + tested byte budget | Fixed item caps plus a test asserting serialized size against realistic fixtures | ✓ |
| Item caps only, no byte test | Same caps, compactness reviewed rather than tested | |
| SDK's max_request_body_size only | Rely on the existing 4MB request-body ceiling alone | |

**User's choice:** Per-tool item caps + tested byte budget.
**Notes:** Makes MCP-03 concretely verifiable rather than a design intention.

| Option | Description | Selected |
|--------|-------------|----------|
| 52 weeks | One-year max for weeks=N window tools | ✓ |
| 26 weeks | Six-month max | |
| No hard cap | Any weeks=N accepted | |

**User's choice:** 52 weeks.
**Notes:** Long enough for real trend questions, bounds a weekly series to at most 52 rows.

---

## Claude's Discretion

- Exact name-matching permissiveness beyond case-insensitive exact match
- Default `weeks` value per tool; default/max `limit` for fitness_get_recent_workouts
- Default window for fitness_get_training_summary
- Exact serialized byte budget number and how it's measured
- Tool file/package layout under `backend/app/mcp/tools/`
- Exact response Pydantic model field naming (follows `_AnalyticsModel` pattern)
- Recomposition tool name (`fitness_get_recomposition_status` is the default, aligned with ROADMAP wording and the analytics function name, over blueprint's literal `fitness_get_recomposition_summary`)

## Deferred Ideas

- `fitness_get_body_composition`, `fitness_get_activity_summary`, `fitness_get_recovery_summary` — Apple Health/HealthKit-dependent, deferred to milestone 2
- Rate limiting on the MCP endpoint — Phase 7 (Production Hardening)
