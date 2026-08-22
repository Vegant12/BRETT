# Roadmap: BRETT

## Overview

BRETT starts as an empty repo and ends as a live, authenticated remote MCP server that Claude can query to coach body recomposition from real data. The path: stand up the FastAPI/PostgreSQL foundation with correct timezone and secret handling (Phase 1), then immediately spike the riskiest unknown — whether a real Claude client can authenticate to a Render-hosted MCP endpoint at all (Phase 2) — before any real functionality is built on that assumption. With the transport proven, Hevy becomes the data source of truth: workouts, exercise templates, and body measurements sync idempotently into normalized tables with a canonical muscle map (Phase 3). Analytics then layer on as pure, testable functions — volume and frequency first, establishing the freshness/uncertainty envelope every answer carries (Phase 4), then progression, records, plateaus, and recomposition status (Phase 5). Only once the computation exists do the read-only MCP tools compose it into compact, budgeted responses (Phase 6). The final phase makes the deployment production-grade — full test coverage, rate limiting, backup/restore, secret rotation — and ships the coaching instructions document that turns the data layer into an actual coach (Phase 7).

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Backend Foundation** - FastAPI app, PostgreSQL, Alembic, configurable timezone, secret-safe logging, health endpoint
- [ ] **Phase 2: Deploy & Connector Auth Spike** - Prove a real Claude client can authenticate to a Render-hosted MCP endpoint before building on the assumption
- [ ] **Phase 3: Hevy Integration & Normalization** - Idempotent sync of workouts, exercise templates, and body measurements into a canonical muscle-mapped schema
- [ ] **Phase 4: Volume & Frequency Analytics** - Hard-set volume, per-muscle direct/indirect breakdown, training frequency, and the freshness/uncertainty envelope
- [ ] **Phase 5: Progression, Records & Recomposition Analytics** - Progression trends, plateau detection, PRs, period comparison, weight trend, recomposition verdict
- [ ] **Phase 6: MCP Tools** - Purpose-built, read-only, budgeted tools composing the analytics layer for Claude
- [ ] **Phase 7: Production Hardening & Coaching Layer** - Full test coverage, rate limiting, backup/restore, secret rotation, and the coaching instructions document

## Phase Details

### Phase 1: Backend Foundation
**Goal**: A running FastAPI service backed by a migration-managed PostgreSQL schema, with timezone and secret handling correct from the first line of code
**Depends on**: Nothing (first phase)
**Requirements**: FOUND-01, FOUND-02, FOUND-03, FOUND-04, FOUND-05
**Success Criteria** (what must be TRUE):
  1. Hitting the health endpoint on a running instance returns service status plus a live database connectivity check
  2. A fresh database can be built from empty to current schema by running Alembic migrations, and stepped back down, with no manual SQL
  3. Day/week bucketing helpers place a workout timestamped near midnight UTC into the correct Asia/Jakarta local day, with the timezone read from user configuration rather than hard-coded
  4. Every timestamp is stored in UTC and converted only at calculation boundaries — enforced by a test, not by convention
  5. A seeded secret passed through config, logs, and error output never appears in any log line or response
**Plans**: TBD

### Phase 2: Deploy & Connector Auth Spike
**Goal**: Resolve the project's single highest-uncertainty question — whether and how a real Claude client can authenticate to a remote MCP server — while it is still cheap to change the answer
**Depends on**: Phase 1
**Requirements**: MCP-01, MCP-04, DEPLOY-01, DEPLOY-02
**Success Criteria** (what must be TRUE):
  1. The service is live on Render over HTTPS with every secret supplied through environment configuration and nothing committed to the repo
  2. A Claude custom connector pointed at the deployed `/mcp` endpoint discovers a throwaway tool and successfully calls it from an actual Claude client (Desktop/Web/Mobile), not just a local test client
  3. An unauthenticated request to the MCP endpoint is rejected and an authenticated one succeeds, verified against the deployed URL
  4. The auth mechanism that actually works — static bearer header or a minimal OAuth 2.1 resource-server shim — is chosen and recorded in PROJECT.md Key Decisions, confirming or explicitly overturning the "bearer token, not OAuth" decision
**Plans**: TBD

### Phase 3: Hevy Integration & Normalization
**Goal**: PostgreSQL becomes the trustworthy source of truth for all Hevy data — workouts, exercise templates, and body measurements — normalized to a canonical muscle taxonomy
**Depends on**: Phase 1 (Phase 2 runs in parallel-safe isolation; no dependency)
**Requirements**: HEVY-01, HEVY-02, HEVY-03, HEVY-04, HEVY-05, HEVY-06, HEVY-07, HEVY-08, HEVY-09, NORM-01, NORM-02, NORM-03
**Success Criteria** (what must be TRUE):
  1. A full historical sync pulls the entire Hevy workout history into Postgres with enough fidelity to reconstruct any workout — exercises, sets, set types, weights, reps — and an incremental sync afterwards picks up only what changed
  2. Running sync repeatedly, in any order, produces no duplicate workouts, exercises, or sets; a workout deleted in Hevy disappears locally without disturbing any other record
  3. An injected mid-sync failure (network drop, malformed page, rate limit) leaves all previously-synced data intact and the sync resumable from where it left off
  4. Every synced exercise resolves to canonical muscle groups with direct/indirect distinction and a front/side/rear deltoid split, and a manual override changes the effective mapping while the original source mapping stays visible for audit
  5. Each data source reports a readable `last_synced_at`, and all Hevy request/response code lives only under `backend/app/integrations/hevy/`
**Plans**: TBD

### Phase 4: Volume & Frequency Analytics
**Goal**: The system can answer "how much work am I doing, and which muscles is it reaching?" from stored data, with honest metadata attached to every answer
**Depends on**: Phase 3
**Requirements**: VOL-01, VOL-02, VOL-03, DQ-01, DQ-02
**Success Criteria** (what must be TRUE):
  1. Weekly volume returns hard sets and reps for every Hevy exercise type, with tonnage reported only where the modality supports it, and warm-up sets excluded from every figure
  2. Per-muscle-group weekly volume breaks out direct versus indirect sets using the configurable weighting, making "which muscles are undertrained" answerable
  3. Training frequency per muscle group and per exercise reports sessions per week over a requested window
  4. Every analytics response carries freshness metadata (when the underlying data was last synced) and coverage/uncertainty metadata (sessions in window, insufficient-data flag)
  5. All calculations are verified against golden fixture workouts covering warm-ups, dropsets, supersets, and bodyweight exercises
**Plans**: TBD

### Phase 5: Progression, Records & Recomposition Analytics
**Goal**: The system returns verdicts, not just numbers — whether a lift is progressing, whether it has plateaued, what the records are, and where body recomposition stands
**Depends on**: Phase 4
**Requirements**: PROG-01, PROG-02, PROG-03, PROG-04, CMP-01, BODY-01, BODY-02
**Success Criteria** (what must be TRUE):
  1. Exercise progression returns a weight/reps/sets time series, with an estimated 1RM only where the exercise modality and rep range make it meaningful and an explicit null-plus-reason otherwise
  2. Each tracked exercise receives a trend verdict — improving, stable, declining, or unclear — derived from multiple sessions, and plateau detection reports the window and threshold it used alongside the result
  3. Personal records (max weight, max reps at a weight, estimated-1RM, volume, rep PR) are detected with their dates and exclude warm-up sets
  4. Two time periods can be compared with values normalized per week, so unequal-length windows do not produce misleading deltas
  5. Body weight trend (7/14/30-day rolling averages, weekly rate of change) and a recomposition status verdict are produced from synced measurements, degrading cleanly to insufficient-data and framed as decision support rather than a medical claim
**Plans**: TBD

### Phase 6: MCP Tools
**Goal**: Claude can reach every analytic through purpose-built, read-only tools that return compact structured answers instead of raw data
**Depends on**: Phase 2, Phase 5
**Requirements**: MCP-02, MCP-03, MCP-05, MCP-06
**Success Criteria** (what must be TRUE):
  1. Claude can call read-only tools covering recent workouts, training summary, weekly volume, muscle-group volume, exercise progression, personal records, plateaus, training frequency, body-weight trend, recomposition status, and period comparison
  2. A single `fitness_get_training_summary` call returns a composed picture of training state without Claude needing to chain several tools
  3. Every tool response is compact structured JSON within an enforced size cap — no raw table access, no unbounded result sets, no arithmetic pushed onto the model
  4. No tool can write, modify, or delete any data; every tool is annotated read-only and a write attempt has no surface to reach
  5. No tool response or log line contains an API key, database credential, or internal token, verified by test
**Plans**: TBD

### Phase 7: Production Hardening & Coaching Layer
**Goal**: The deployment is production-grade and Claude actually coaches — the end-to-end Hevy → Postgres → analytics → MCP → Claude path works against real data
**Depends on**: Phase 6
**Requirements**: DEPLOY-03, COACH-01
**Success Criteria** (what must be TRUE):
  1. An automated test suite covering Hevy sync (auth, pagination, incremental events, duplicate prevention, deletions, failures), analytics against known workouts, and MCP tool schemas/auth/output structure runs green, including an end-to-end mock-Hevy-to-MCP integration test
  2. The deployed connector serves the real tool set with finalized auth and rate limiting applied ahead of handler work; unauthenticated and over-limit requests are rejected without leaking detail
  3. A database backup restores into a fresh instance with no data loss, and a secret can be rotated without breaking the live connector
  4. The coaching system-prompt/instructions document exists, and with it loaded Claude answers "Am I progressing?" and "Which muscles are undertrained?" from real synced data, correctly flagging stale or sparse data when present
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Backend Foundation | 0/TBD | Not started | - |
| 2. Deploy & Connector Auth Spike | 0/TBD | Not started | - |
| 3. Hevy Integration & Normalization | 0/TBD | Not started | - |
| 4. Volume & Frequency Analytics | 0/TBD | Not started | - |
| 5. Progression, Records & Recomposition Analytics | 0/TBD | Not started | - |
| 6. MCP Tools | 0/TBD | Not started | - |
| 7. Production Hardening & Coaching Layer | 0/TBD | Not started | - |

## Coverage

All 39 v1 requirements are mapped to exactly one phase. See REQUIREMENTS.md Traceability.

| Phase | Requirements | Count |
|-------|--------------|-------|
| 1 | FOUND-01..05 | 5 |
| 2 | MCP-01, MCP-04, DEPLOY-01, DEPLOY-02 | 4 |
| 3 | HEVY-01..09, NORM-01..03 | 12 |
| 4 | VOL-01..03, DQ-01, DQ-02 | 5 |
| 5 | PROG-01..04, CMP-01, BODY-01, BODY-02 | 7 |
| 6 | MCP-02, MCP-03, MCP-05, MCP-06 | 4 |
| 7 | DEPLOY-03, COACH-01 | 2 |
| **Total** | | **39** |

## Notes

- **Phase 2 is a spike, deliberately placed before the real work.** All four researchers independently found that PROJECT.md's "MCP auth = bearer token" decision may not be implementable through Claude's custom-connector UI. Resolving it now costs hours; discovering it after Phases 3-6 are built costs an auth-layer rewrite. Phase 2 ships a throwaway tool — its value is the answer, not the code.
- **Exercise-template sync and the muscle map live in Phase 3, not later.** Per-muscle analytics structurally cannot start without them, so they are prerequisites of Phase 4, not a Phase 4 concern.
- **Hevy body measurements are synced in Phase 3 rather than entered manually.** The Hevy client already exists at that point and `/v1/body_measurements` is real, which unlocks weight trend and recomposition status in v1 without waiting for HealthKit.
- **Phase 4 establishes the freshness/uncertainty envelope** that Phase 5 analytics and Phase 6 tools both inherit — it is a shared contract created once, not retrofitted per metric.
- **No UI phase.** v1 is backend and MCP only; there is no frontend surface in this milestone.

---
*Roadmap created: 2026-08-23*
