---
gsd_state_version: 1.0
milestone: v2.1
milestone_name: Longitudinal Physique Analysis
status: executing
stopped_at: Phase 18 context gathered
last_updated: "2026-09-12T03:53:02.061Z"
last_activity: 2026-09-12 -- Phase 18 execution started
progress:
  total_phases: 6
  completed_phases: 4
  total_plans: 16
  completed_plans: 13
  percent: 81
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-09-05 after v2.0 milestone)

**Core value:** Claude can retrieve real, normalized workout data through the MCP server and answer training questions from actual data instead of guessing.
**Current focus:** Phase 18 — monthly-report-physique-integration

## Current Position

Milestone: v2.1 Longitudinal Physique Analysis
Phase: 18 (monthly-report-physique-integration) — EXECUTING
Plan: 1 of 3
Status: Executing Phase 18
Last activity: 2026-09-12 -- Phase 18 execution started

Progress: [███───────] 33% — 2/6 v2.1 phases complete

Two milestones shipped to date: v1.0 (7 phases, 65 plans) and v2.0 (6 phases, 34 plans).
Phase numbering continues from v2.0's last phase (13); v2.1 runs Phase 14 through Phase 19:
14 Deploy Pipeline Migration Safety, 15 Physique Rating Calibration Spike, 16 Physique Data
Model & Repository, 17 Physique Analytics & MCP Read/Write Tools, 18 Monthly Report Physique
Integration, 19 Production Deploy of Migration 0007.

## Performance Metrics

| Milestone | Phases | Plans | Tasks | Timeline | Commits |
|-----------|--------|-------|-------|----------|---------|
| v1.0 MVP | 7 | 65 | 151 | 2026-08-23 → 2026-09-01 (10 days) | — |
| v2.0 Apple Health & Coaching | 6 | 34 | 81 | 2026-09-02 → 2026-09-05 (4 days) | 220 |

**Codebase at v2.0 close:** ~52.3k LOC in `backend/`, 925 test functions, 20 MCP tools.

**Per-plan execution metrics (v2.1):**

| Plan | Duration | Tasks | Files |
|------|----------|-------|-------|
| Phase 15 P01 | 35 min | 4 tasks | 1 files |
| Phase 15 P02 | 13 min | 3 tasks | 1 files |

## Accumulated Context

### Decisions

Full decision log lives in PROJECT.md Key Decisions table. All v2.0 decisions were
validated at milestone close — no decision remains in "Pending" state.

- [Phase 15]: Moved user-supplied photos out of the repo working directory into the session scratchpad rather than copying, since they arrived sitting untracked inside the repo folder itself. — Leaving copies of a real body photo inside a git working tree is a disclosure risk even if uncommitted; mv + git status verification closed it before any rating call.
- [Phase 15]: Anchored chain in the 15-01 spike run showed zero drift across all 5 muscle groups (R1..R5 identical). Plan 15-02's pre-registered analysis found the blind condition BLIND-STABLE (range exactly 1 on every group, not the noisier informal read this entry originally logged) and the ratchet verdict RATCHET-NOT-OBSERVED (every group's anchored_travel == 0). — Corrected here after plan 15-02 computed the actual rule-applied statistics; see 15-SPIKE-RESULT.md.
- [Phase 15]: Post-execution code review found and fixed a self-contradictory constant (`PHYSIQUE_DIFF_MIN_LEVEL_DELTA` corrected 1→2), a real identifying-detail leak that evaded the automated audit (redacted), and an imprecise literature citation in the D-08 draft — none changed the run's verdicts. Full detail in 15-SPIKE-RESULT.md's "Post-execution code review" footer. — Documented so a future session doesn't need to re-discover these from the review transcript.

### Pending Todos

[From .planning/todos/pending/ — ideas captured during sessions]

None.

### Blockers/Concerns

Resolved items were cleared at the v2.0 milestone close. Open items only. **The deploy
migration gap below is now in v2.1 scope** rather than carried debt — see PROJECT.md
Requirements → Active:

- **Open (highest priority, 3 occurrences in v2.0):** `scripts/deploy-cloud-run.sh` has no
  migration step, so production repeatedly runs a schema behind the deployed code. It happened
  in Phase 8 (`alembic current` == `0004`, code needed `0005`), during the Phase 9 operator run
  (shell pointed at the wrong `DATABASE_URL`, showing a stale before-state), and again in the
  Phase 13 spike (`0005` vs `0006` → `UndefinedTableError: relation "user_program_history" does
  not exist`). Each was fixed live with the user's confirmation. The structural fix — a
  pre-deploy migration step, or an enforced `alembic current` vs `alembic heads` pre-flight,
  plus a documented single source of truth for the production `DATABASE_URL`
  (`gcloud secrets versions access latest --secret="brett-database-url"`) — is **still not done**
  and should lead the next milestone.

- **Open (carried from v1.0):** Hevy's real rate limits remain undocumented — the existing retry
  policy is unverified against a real limit, not confirmed unnecessary.

- **Open (carried from v1.0):** MCP Python SDK had a breaking `FastMCP` → `MCPServer` rework
  mid-project; re-read SDK docs at the start of any phase touching `app/mcp/`.

- **Open (from Phase 13, does not close with the milestone):** D-06's production
  nutrition/activity coverage re-query never ran — `gcloud secrets versions access` was blocked
  by the sandbox's command classifier. `MEASURED_DAY_FLOORS` (3/7, 5/14, 10/30) is reused for
  nutrition trend floors as a documented UNMEASURED fallback. See
  `docs/health-auto-export-setup.md` §11. Needs a human-operator re-query.

- **Open (accepted, documented):** `sample_count` semantics diverge between the backfill (raw
  sample count, >1 for 91.7% of rows) and the webhook (always 1), so a falling `sample_count` on
  a backfilled day is a false positive for the Pitfall N-2 batch-split detector. Documented in
  `docs/health-auto-export-setup.md` §7. No overlapping day existed to exercise it (zero overlap
  confirmed: export ends 2026-08-26, webhook begins 2026-09-02), so it stays open.

- **Open (low urgency):** the Hevy-source exclusion predicate's string matching is formally
  unverified against a live payload — Hevy stopped writing to HealthKit for this user around
  May 2025, so nothing live matched it during Phase 8. It remains load-bearing for historical
  data and would matter again if Hevy resumes write-back. Worth a periodic check.

- **Open (decision, not an oversight):** `Gymverse` (2 records) and `Zing` (1 record) also wrote
  `ActiveEnergyBurned` into HealthKit and were **deliberately ingested**. HEALTH-08 names Hevy
  specifically, and its rationale — "BRETT already holds this data at higher fidelity" — is true
  of Hevy and false of these two, whose workouts BRETT does not hold at all.

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260907-dsu | Formalize weekly/monthly report narrative as a reusable section template | 2026-09-07 | fe36e1c | [260907-dsu-formalize-weekly-monthly-report-narrativ](./quick/260907-dsu-formalize-weekly-monthly-report-narrativ/) |

## Deferred Items

Items acknowledged and deferred at v1.0 milestone close on 2026-09-02:

| Category | Item | Status |
|----------|------|--------|
| audit | No formal `/gsd-audit-milestone` run before v1.0 close | Substituted with a targeted spot-check of 8 stale requirements; user chose to proceed |
| tooling | `gsd-tools.cjs audit-open`/`--json` broken (`ReferenceError: output is not defined`) | Global GSD install bug, not a BRETT issue — worth reporting upstream |

Items acknowledged and deferred at v2.0 milestone close on 2026-09-05:

| Category | Item | Status |
|----------|------|--------|
| audit | No formal `/gsd-audit-milestone` run before v2.0 close | Skipped by explicit user choice at the pre-flight gate, same as v1.0. Substituted with direct code verification of HEALTH-10, BODY-05 and GOAL-02 — the three requirements whose traceability rows read `Pending` — all three confirmed implemented before archiving |
| tooling | `gsd-tools.cjs audit-open` still broken, second milestone running | Reported at v1.0 close, never fixed upstream. Bare `output()` at gsd-tools.cjs:784/786 that should be `core.output()`. Automated pre-close artifact audit could not run again |
| process | REQUIREMENTS.md traceability drift, second milestone running | Three requirements marked `Pending` despite being complete and production-verified; reconciled to 26/26 at close. Identical failure mode to v1.0 — suggests the per-phase workflow does not reliably update the traceability table. Worth a structural fix over a third manual reconciliation |
| ops | Deploy migration gap, 3 occurrences | Carried into next milestone as candidate scope — see Blockers/Concerns above and PROJECT.md Requirements → Active |
| data | D-06 nutrition-coverage re-query | Blocked by sandbox command classifier; documented UNMEASURED fallback in use |

## Session Continuity

Last session: 2026-09-12T03:13:21.300Z
Stopped at: Phase 18 context gathered
Resume: `/gsd-discuss-phase 16` (Phase 14 is already complete — do not re-run its discuss step).

### v2.1 milestone-gate decisions (made before research, carry into requirements)

| Decision | Choice |
|----------|--------|
| Where vision analysis happens | Claude, in-conversation, via MCP — not a server-side vision API. Keeps `app/analytics/` deterministic |
| Photo storage | **None.** Photos are never uploaded to or stored by BRETT; only structured observations persist |
| Photo ingest path | Attached directly in the Claude conversation — no upload endpoint, no new public surface |
| Observation schema | Per-muscle-group development ratings on the existing 19-value canonical taxonomy + bounded free-text notes |
| Write gating | Single call, append-only, `destructive_hint=False` — not the two-call token ceremony `program_switch.py` uses, because appending a dated row destroys nothing |
| Rating-drift mitigation | Prior observation returned as context at analysis time so ratings are relative, not absolute |
| Report integration | Monthly report only; weekly deliberately excluded, which requires splitting the shared `_report_body_fields` projection |
| Carried debt in scope | Pre-deploy migration step only. D-06 nutrition re-query and Hevy rate-limit verification stay deferred |
