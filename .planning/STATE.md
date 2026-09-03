---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Apple Health, Strength Tracking & Coaching Programs
status: verifying
stopped_at: Phase 9 context gathered
last_updated: "2026-09-03T03:46:24.939Z"
last_activity: 2026-09-03 -- Phase 08 complete
progress:
  total_phases: 6
  completed_phases: 1
  total_plans: 8
  completed_plans: 8
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-09-02)

**Core value:** Claude can retrieve real, normalized workout data through the MCP server and answer training questions from actual data instead of guessing.
**Current focus:** Phase 9 — historical-apple-health-backfill

## Current Position

Phase: 9 (historical-apple-health-backfill) — not yet planned
Plan: Not started
Status: Phase 08 verified and complete. Ready to discuss/plan Phase 9
Last activity: 2026-09-03 -- Phase 08 complete

Progress: [██████████] 100% (v2.0) — 8 of 8 plans complete

## Performance Metrics

**Velocity (v1.0, for reference):**

- Total plans completed: 73 (v1.0 milestone, all phases)
- Average duration: —
- Total execution time: —

**By Phase (v1.0):**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-07 | 65 | - | - |
| 08 | 8 | - | - |

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
- **Resolved 2026-09-03:** Phase 8 plan 08-08 Task 3 completed. A real Health Auto Export run landed all 12 metrics live; a repeat run proved idempotency (23 rows / 23 samples unchanged). HEALTH-06 and NUTR-02 are now complete. RESEARCH Assumption A1 closed as **MOOT** (not confirmed, not refuted): the user's native Health app confirms Hevy is not currently writing `active_energy` to HealthKit at all, despite a Hevy workout existing on the exported day — consistent with D-01's note that Hevy's body-mass write-back "stops in May 2025", suggesting Hevy stopped writing to HealthKit generally around then. `_HEVY_SOURCE_ALIASES` was left unchanged (no live spelling was observed to add); the exclusion predicate remains necessary for Phase 9's `export.xml` historical backfill, which covers the pre-2025 period when Hevy demonstrably did write to HealthKit. **New open item:** if Hevy ever resumes HealthKit write-back, the exclusion predicate's string-matching is still formally unverified against a live payload — worth a periodic check, not urgent.
- **New (2026-09-03):** During Task 3, the live production database was found one migration behind deployed code (`alembic current` == `0004`, code needed `0005` for `health_daily_metrics`) — `scripts/deploy-cloud-run.sh` has no migration step, and this is the **second** occurrence of the exact failure mode already documented in `docs/runbook-sync-schedule.md`. Fixed live with the user's confirmation (`alembic upgrade head` against production). Recommend a structural fix (pre-deploy migration step, or an enforced `alembic current` vs `alembic heads` pre-flight check) before Phase 9 deploys its own migration and repeats this a third time.
- **Resolved 2026-09-03:** `docs/health-auto-export-setup.md` originally described the Daily-aggregation setting as an "Aggregation interval" dropdown; the user's HAE build (9.1.1) actually exposes it as a boolean **"Aggregate Data"** toggle, discovered when the doc's wrong wording sent them looking for a setting that doesn't exist. Corrected throughout the doc (§1, §3, §6, §7, §9) in the same session.

## Deferred Items

Items acknowledged and deferred at v1.0 milestone close on 2026-09-02:

| Category | Item | Status |
|----------|------|--------|
| audit | No formal `/gsd-audit-milestone` run before v1.0 close | Substituted with a targeted spot-check of 8 stale requirements; user chose to proceed |
| tooling | `gsd-tools.cjs audit-open`/`--json` broken (`ReferenceError: output is not defined`) | Global GSD install bug, not a BRETT issue — worth reporting upstream |

## Session Continuity

Last session: 2026-09-03T03:46:24.931Z
Stopped at: Phase 9 context gathered
Resume: /gsd-discuss-phase 9 or /gsd-plan-phase 9
