---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Apple Health, Strength Tracking & Coaching Programs
status: ready_to_plan
stopped_at: roadmap created, Phase 8 ready to plan
last_updated: "2026-09-02T00:00:00.000Z"
last_activity: 2026-09-02
progress:
  total_phases: 6
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-09-02)

**Core value:** Claude can retrieve real, normalized workout data through the MCP server and answer training questions from actual data instead of guessing.
**Current focus:** Phase 8 — Apple Health & Nutrition Ingest

## Current Position

Phase: 8 of 13 (Apple Health & Nutrition Ingest) — first phase of v2.0
Plan: — (none yet)
Status: Ready to plan
Last activity: 2026-09-02 — v2.0 roadmap created (Phases 8-13, 28/28 requirements mapped)

Progress: [░░░░░░░░░░] 0% (v2.0)

## Performance Metrics

**Velocity (v1.0, for reference):**

- Total plans completed: 65 (v1.0 milestone, all phases)
- Average duration: —
- Total execution time: —

**By Phase (v1.0):**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-07 | 65 | - | - |

**Recent Trend:**

- Last 5 plans: —
- Trend: —

*Updated after each plan completion*

## Accumulated Context

### Decisions

Full decision log lives in PROJECT.md Key Decisions table. v2.0 decisions pending validation:

- Apple Health ingestion = Health Auto Export webhook receiver, not a native iOS app
- Strength progression signal = max-weight-lifted primary, estimated-1RM secondary
- Reports = on-demand MCP tools driven by Claude's own scheduled-tasks feature
- Training programs = real data + confirm-gated two-call write tool (server-issued token, not `confirm: bool`)
- Apple Health workouts and Hevy-sourced body-mass rows excluded from ingestion
- Sleep/recovery cut from v2.0 — zero records in 4.5 years of real export data

### Pending Todos

[From .planning/todos/pending/ — ideas captured during sessions]

None yet.

### Blockers/Concerns

[Issues that affect future work]

- **Open (carried from v1.0):** Hevy's real rate limits remain undocumented — the existing retry policy is unverified against a real limit, not confirmed unnecessary.
- **Open (carried from v1.0):** MCP Python SDK had a breaking `FastMCP` → `MCPServer` rework mid-project; re-read SDK docs at the start of any phase touching `app/mcp/` (applies to Phases 12 and 13).
- **Phase 13 risk, known up front:** Claude scheduled-task sessions may never load MCP tool schemas (two GitHub issues, both closed "not planned"). Spike this early *within* Phase 13; reports must stay fully valuable on-demand regardless.
- **Phase 10 open question:** the re-derived max-weight dead-band values cannot be settled on paper — they need live-data calibration, like D-18's original.
- **Phase 8 open question:** `weight_body_mass` vs `weight_&_body_mass` metric-name spelling is unsettled across sources; capture one real Health Auto Export payload before writing the normalizer.
- **Deploy prerequisite for Phase 8:** Cloud Run `--memory=512Mi` is too small for JSON ingest (measured peak ~235 MB on a 10 MB body). Raise to 1Gi and add a body-size cap before the first real device sync.

## Deferred Items

Items acknowledged and deferred at v1.0 milestone close on 2026-09-02:

| Category | Item | Status |
|----------|------|--------|
| audit | No formal `/gsd-audit-milestone` run before v1.0 close | Substituted with a targeted spot-check of 8 stale requirements; user chose to proceed |
| tooling | `gsd-tools.cjs audit-open`/`--json` broken (`ReferenceError: output is not defined`) | Global GSD install bug, not a BRETT issue — worth reporting upstream |

## Session Continuity

Last session: 2026-09-02 (v2.0 roadmap created)
Stopped at: ROADMAP.md written with Phases 8-13; REQUIREMENTS.md traceability populated
Resume file: none — next step is `/gsd-plan-phase 8`
