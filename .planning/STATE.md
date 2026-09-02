---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Apple Health, Strength Tracking & Coaching Programs
status: executing
stopped_at: Phase 08 plan 08-08 PAUSED at Task 3 blocking checkpoint (device export)
last_updated: "2026-09-02T10:41:20.365Z"
last_activity: 2026-09-02 -- Phase 08 plan 08-08 paused at its blocking checkpoint
progress:
  # 08-08-SUMMARY.md exists on disk but its plan is NOT complete -- it was written to carry
  # Tasks 1-2 across a blocking checkpoint. `state record-session` derives these numbers by
  # counting SUMMARY files and therefore reported 8/8 and 100%; hand-corrected to 7/8.
  # Re-derive only after 08-08 Task 3 lands.
  total_phases: 6
  completed_phases: 0
  total_plans: 8
  completed_plans: 7
  percent: 88
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-09-02)

**Core value:** Claude can retrieve real, normalized workout data through the MCP server and answer training questions from actual data instead of guessing.
**Current focus:** Phase 08 — apple-health-nutrition-ingest

## Current Position

Phase: 08 (apple-health-nutrition-ingest) — EXECUTING, PAUSED AT A BLOCKING CHECKPOINT
Plan: 8 of 8 (Tasks 1-2 of 3 done; Task 3 awaits a real iPhone export)
Status: Awaiting user action — see Blockers
Last activity: 2026-09-02 -- 08-08 Tasks 1-2 committed, deploy live, checkpoint reached

Progress: [█████████░] 88% (v2.0) — 7 of 8 plans complete; 08-08 is in progress, not done

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
- Phase 8 plan 08-08 is PAUSED at its Task 3 blocking checkpoint. Tasks 1-2 are done: brett-health-ingest-secret exists in Secret Manager and Cloud Run revision brett-00010-kln runs at 1Gi with HEALTH_INGEST_SECRET bound. OUTSTANDING: the user must configure the Health Auto Export iOS automation and trigger one real export that includes a training day. Until then ROADMAP criterion #1 is unmet, RESEARCH Assumption A1 (does the HAE webhook spell Hevy as 'hevy'?) is still OPEN, and HEALTH-06 + NUTR-02 remain pending. If A1 is refuted, _HEVY_SOURCE_ALIASES in backend/app/integrations/health_auto_export/normalize.py needs the real spelling added and Phase 9 inherits the answer.

## Deferred Items

Items acknowledged and deferred at v1.0 milestone close on 2026-09-02:

| Category | Item | Status |
|----------|------|--------|
| audit | No formal `/gsd-audit-milestone` run before v1.0 close | Substituted with a targeted spot-check of 8 stale requirements; user chose to proceed |
| tooling | `gsd-tools.cjs audit-open`/`--json` broken (`ReferenceError: output is not defined`) | Global GSD install bug, not a BRETT issue — worth reporting upstream |

## Session Continuity

Last session: 2026-09-02T10:41:20.358Z
Stopped at: Phase 08 plan 08-08 PAUSED at Task 3 blocking checkpoint (device export)
Resume file: .planning/phases/08-apple-health-nutrition-ingest/08-08-PLAN.md
