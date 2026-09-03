---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Apple Health, Strength Tracking & Coaching Programs
status: verifying
stopped_at: Phase 10 context gathered
last_updated: "2026-09-03T13:20:09.184Z"
last_activity: 2026-09-03 -- Phase 09 production backfill run verified against all four success criteria
progress:
  total_phases: 6
  completed_phases: 2
  total_plans: 15
  completed_plans: 15
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-09-02)

**Core value:** Claude can retrieve real, normalized workout data through the MCP server and answer training questions from actual data instead of guessing.
**Current focus:** Phase 09 — historical-apple-health-backfill

## Current Position

Phase: 09 (historical-apple-health-backfill) — EXECUTION COMPLETE
Plan: 7 of 7
Status: Phase 09 execution complete. Next step is verification.
Last activity: 2026-09-03 -- Phase 09 production backfill run verified against all four success criteria

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
- Strength progression signal = estimated-1RM keeps classifying (unchanged); max-weight-lifted added as a labelled display-only field (rescoped 2026-09-03, was originally max-weight-primary/e1RM-secondary — see PROJECT.md Key Decisions)
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
- **Resolved 2026-09-03 (Phase 10 discuss-phase):** the dead-band re-derivation question is moot — Phase 10 was rescoped so max weight is a display-only field and e1RM keeps classifying trend/plateau, unchanged. No live-data calibration needed. **New open item:** Phase 12's roadmap entry says "Depends on: Phase 10 (recomposition thresholds settle once, not twice)" — that assumed Phase 10 would recalibrate `RECOMP_PROGRESSION_NET_BAND`, which it no longer does. Re-examine whether that dependency still holds when Phase 12 is discussed.
- **Phase 8 open question:** `weight_body_mass` vs `weight_&_body_mass` metric-name spelling is unsettled across sources; capture one real Health Auto Export payload before writing the normalizer.
- **Deploy prerequisite for Phase 8:** Cloud Run `--memory=512Mi` is too small for JSON ingest (measured peak ~235 MB on a 10 MB body). Raise to 1Gi and add a body-size cap before the first real device sync.
- **Resolved 2026-09-03:** Phase 8 plan 08-08 Task 3 completed. A real Health Auto Export run landed all 12 metrics live; a repeat run proved idempotency (23 rows / 23 samples unchanged). HEALTH-06 and NUTR-02 are now complete. RESEARCH Assumption A1 closed as **MOOT** (not confirmed, not refuted): the user's native Health app confirms Hevy is not currently writing `active_energy` to HealthKit at all, despite a Hevy workout existing on the exported day — consistent with D-01's note that Hevy's body-mass write-back "stops in May 2025", suggesting Hevy stopped writing to HealthKit generally around then. `_HEVY_SOURCE_ALIASES` was left unchanged (no live spelling was observed to add); the exclusion predicate remains necessary for Phase 9's `export.xml` historical backfill, which covers the pre-2025 period when Hevy demonstrably did write to HealthKit. **New open item:** if Hevy ever resumes HealthKit write-back, the exclusion predicate's string-matching is still formally unverified against a live payload — worth a periodic check, not urgent.
- **New (2026-09-03):** During Task 3, the live production database was found one migration behind deployed code (`alembic current` == `0004`, code needed `0005` for `health_daily_metrics`) — `scripts/deploy-cloud-run.sh` has no migration step, and this is the **second** occurrence of the exact failure mode already documented in `docs/runbook-sync-schedule.md`. Fixed live with the user's confirmation (`alembic upgrade head` against production). Recommend a structural fix (pre-deploy migration step, or an enforced `alembic current` vs `alembic heads` pre-flight check) before Phase 9 deploys its own migration and repeats this a third time.
- **Resolved 2026-09-03:** `docs/health-auto-export-setup.md` originally described the Daily-aggregation setting as an "Aggregation interval" dropdown; the user's HAE build (9.1.1) actually exposes it as a boolean **"Aggregate Data"** toggle, discovered when the doc's wrong wording sent them looking for a setting that doesn't exist. Corrected throughout the doc (§1, §3, §6, §7, §9) in the same session.
- **Resolved 2026-09-03:** RESEARCH Assumption **A2** (backfill/webhook day overlap) — confirmed zero overlapping days against production: the `export.xml` history ends 2026-08-26 and the live webhook feed begins 2026-09-02. Success criterion #3 ("no metric-day holds two rows for the same `source_name`") is therefore proven in production vacuously, not by an actual overlap; the overlapping-day case itself is proven mechanically by `backend/tests/test_backfill_idempotency.py`'s container tests.
- **Resolved 2026-09-03:** RESEARCH Assumption **A3** (device not renamed between research and the run) — confirmed: the production duplicate-metric-day query returned zero rows, the observable form of the backfill and webhook agreeing on `source_name` for the same device. `test_source_name_matches_device_capture` now pins it, so a future rename fails the fast suite instead of silently producing two rows per metric-day.
- **Open (accepted, documented):** `sample_count` semantics diverge between the backfill (raw sample count, >1 for 91.7% of rows) and the webhook (always 1). A falling `sample_count` on a backfilled day is a false positive for the Pitfall N-2 batch-split detector. Documented in `docs/health-auto-export-setup.md` §7. No day existed to actually exercise it during the production run (zero overlap, per A2), so it remains open rather than closed.
- **Open (decision, not an oversight):** `Gymverse` (2 records) and `Zing` (1 record) also wrote `ActiveEnergyBurned` into HealthKit and were **deliberately ingested**. HEALTH-08 names Hevy specifically, and its rationale — "BRETT already holds this data at higher fidelity" — is true of Hevy and false of these two, whose workouts BRETT does not hold at all. Widening `_HEVY_SOURCE_ALIASES` would have broken the constant's documented meaning and its Phase 8 tests.
- **New (2026-09-03):** During the plan 09-07 production run, the post-write verification queries were first run against the wrong `DATABASE_URL` (not the Neon connection string bound to the deployed service, held in Google Secret Manager as `brett-database-url`) and showed a stale before-state even though the `--write` command itself had logged success. This is the **third** occurrence this milestone of an operator's shell pointing somewhere other than the intended production target (the first two were the `alembic current`/`heads` migration-gap incidents above and in `docs/runbook-sync-schedule.md`). Resolved by retrieving the confirmed value with `gcloud secrets versions access latest --secret="brett-database-url"` and re-running the full sequence; the write is idempotent by natural key, so repeating it cost nothing. The structural fix — a pre-deploy migration step in `scripts/deploy-cloud-run.sh`, or a documented single source of truth for the production `DATABASE_URL` that the operator retrieves the same way every time — is still not done.
- **Resolved 2026-09-03:** Phase 9 (historical Apple Health backfill, HEALTH-10) executed and production-verified. 8,077 rows of Apple Health activity and nutrition history (2022-03-10 → 2026-08-26) landed in production alongside the live webhook feed; all four ROADMAP success criteria confirmed against the real database. See `docs/health-auto-export-setup.md` §9's "2026-09-03 — historical backfill, production run" entry for the full record.

## Deferred Items

Items acknowledged and deferred at v1.0 milestone close on 2026-09-02:

| Category | Item | Status |
|----------|------|--------|
| audit | No formal `/gsd-audit-milestone` run before v1.0 close | Substituted with a targeted spot-check of 8 stale requirements; user chose to proceed |
| tooling | `gsd-tools.cjs audit-open`/`--json` broken (`ReferenceError: output is not defined`) | Global GSD install bug, not a BRETT issue — worth reporting upstream |

## Session Continuity

Last session: 2026-09-03T13:20:09.103Z
Stopped at: Phase 10 context gathered
Resume: phase verification (goal-backward check against ROADMAP success criteria)
