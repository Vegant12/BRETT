# Roadmap: BRETT

## Milestones

- ✅ **v1.0 MVP** — Phases 1-7 (shipped 2026-09-02)
- ✅ **v2.0 Apple Health, Strength Tracking & Coaching Programs** — Phases 8-13 (shipped 2026-09-05)
- 🚧 **v2.1 Longitudinal Physique Analysis** — Phases 14-19 (in progress, started 2026-09-05)

Full phase detail for shipped milestones is archived:
- `.planning/milestones/v1.0-ROADMAP.md`
- `.planning/milestones/v2.0-ROADMAP.md` (phase artifacts in `.planning/milestones/v2.0-phases/`)

## Overview

v2.1 gives BRETT a longitudinal record of physique observations — produced by Claude from
progress photos BRETT never stores — so the monthly report reads across training, nutrition,
measurements and visible physique in one view. The milestone opens by closing v2.0's
carried-forward deploy-migration debt (a genuine dependency: this milestone ships its own new
migration into a pipeline that has already let production drift three times), then retires the
feature's central uncertainty — how much a rating actually drifts across repeated/anchored
model calls — with a measurement spike before locking the observation schema. From there the
build proceeds foundation-up: schema and repository, then the write tool and its required
prior-observation read tool together (an append-only write with nowhere to recover to needs a
read path in the same phase), then deterministic diff/cross-reference analytics wired into the
monthly report only, and finally a real production deploy of this milestone's own migration to
prove the opening fix actually works.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order. v2.1 continues
numbering from v2.0's last phase (13); it does not restart at 1.

<details>
<summary>✅ v1.0 MVP (Phases 1-7) — SHIPPED 2026-09-02</summary>

- [x] Phase 1: Backend Foundation (5/5 plans) — completed 2026-08-23
- [x] Phase 2: Deploy & Connector Auth Spike (8/8 plans) — completed 2026-08-29
- [x] Phase 3: Hevy Integration & Normalization (12/12 plans) — completed 2026-08-30
- [x] Phase 4: Volume & Frequency Analytics (9/9 plans) — completed 2026-08-30
- [x] Phase 5: Progression, Records & Recomposition Analytics (10/10 plans) — completed 2026-08-31
- [x] Phase 6: MCP Tools (11/11 plans) — completed 2026-09-01
- [x] Phase 7: Production Hardening & Coaching Layer (10/10 plans) — completed 2026-09-01

</details>

<details>
<summary>✅ v2.0 Apple Health, Strength Tracking & Coaching Programs (Phases 8-13) — SHIPPED 2026-09-05</summary>

- [x] Phase 8: Apple Health & Nutrition Ingest (8/8 plans) — completed 2026-09-03
- [x] Phase 9: Historical Apple Health Backfill (7/7 plans) — completed 2026-09-03
- [x] Phase 10: Max-Weight Strength Signal (1/1 plan) — completed 2026-09-03
- [x] Phase 11: Body Measurement History (3/3 plans) — completed 2026-09-04
- [x] Phase 12: Training Programs & Confirm-Gated Write Tool (5/5 plans) — completed 2026-09-04
- [x] Phase 13: Health Analytics, Reports & Coaching Style (10/10 plans) — completed 2026-09-05

</details>

### 🚧 v2.1 Longitudinal Physique Analysis (Phases 14-19) — IN PROGRESS

- [x] **Phase 14: Deploy Pipeline Migration Safety** - Close the deploy-migration gap before this milestone ships its own new migration (completed 2026-09-07)
- [x] **Phase 15: Physique Rating Calibration Spike** - Measure real rating drift/anchoring before the observation schema locks (completed 2026-09-08)
- [ ] **Phase 16: Physique Data Model & Repository** - Persist a physique observation's full shape with no MCP surface yet
- [ ] **Phase 17: Physique Analytics & MCP Read/Write Tools** - Claude can log and retrieve physique observations; diff and volume-correlation analytics land alongside
- [ ] **Phase 18: Monthly Report Physique Integration** - The monthly report gains a physique section; the weekly report structurally cannot
- [ ] **Phase 19: Production Deploy of Migration 0007** - Prove Phase 14's fix works by deploying this milestone's own migration through it

## Phase Details

### Phase 14: Deploy Pipeline Migration Safety
**Goal**: Deploys can no longer silently run production behind the applied schema.
**Depends on**: Nothing (first phase of this milestone; picks up carried-forward v2.0 debt)
**Requirements**: DEPLOY-04
**Success Criteria** (what must be TRUE):
  1. Running `scripts/deploy-cloud-run.sh` against a database with pending migrations fails loudly before `gcloud run deploy` executes, instead of deploying code against a stale schema.
  2. The script (or a documented equivalent pre-flight) runs `alembic upgrade head`, or an enforced `alembic current` vs `alembic heads` check that aborts on mismatch, with a documented single source of truth for the production `DATABASE_URL` (today: `gcloud secrets versions access latest --secret="brett-database-url"`).
  3. A new static assertion in `backend/tests/test_cloud_run_deploy.py` proves the migration step/pre-flight exists in the script, mirroring the existing `_REQUIRED_FLAGS` guard pattern (lines 54-64).
  4. The fix is rehearsed against a real drift scenario (a database intentionally behind head), not asserted only against fixtures.
**Plans**: 3 plans

Plans:
- [x] 14-01-PLAN.md — Extract the migration pre-flight predicate and rehearse it against a real drifted Postgres container
- [x] 14-02-PLAN.md — Add the fetch/apply/verify block to scripts/deploy-cloud-run.sh with static DEPLOY-04 guards
- [x] 14-03-PLAN.md — Execute the real deploy script against drift with gcloud stubbed, and write the deploy runbook

### Phase 15: Physique Rating Calibration Spike
**Goal**: The rating scale's diff thresholds and any elapsed-time floor are set from measured model behavior, not a guess baked into the migration.
**Depends on**: Phase 14 (sequenced first in the milestone; no technical dependency on Phase 14's content, but this is the milestone's designated risk-retirement step before any schema work starts)
**Requirements**: PHYS-12
**Success Criteria** (what must be TRUE):
  1. A recorded spike result (same shape as `13-SPIKE-RESULT.md`) documents how much a rating moves across repeated, blind, and anchored calls on the same fixed photo set.
  2. The spike explicitly tests and reports whether PHYS-07's prior-observation-as-context mitigation produces a self-reinforcing ratchet — a slow drift no adjacent-pair diff can detect.
  3. The spike's findings state concrete recommended values (rating step count/anchors, diff thresholds, any minimum-elapsed-time floor) that Phase 16's schema and Phase 17's analytics consume as constants.
  4. Phase 16's observation schema is not started until this result exists.
**Plans**: 2 plans

Plans:
- [x] 15-01-PLAN.md — Pause for the user's real photo-set, stage it in the session scratchpad, smoke-test isolated-subagent image reads, pre-register the ratchet decision rule, then collect 5 blind ratings and a 5-step anchored chain as verbatim evidence
- [x] 15-02-PLAN.md — Compute both conditions' descriptive statistics, state the ratchet verdict by the pre-registered rule, write the named constants Phase 16/17 copy verbatim, and run the leak/zero-code-change audit

### Phase 16: Physique Data Model & Repository
**Goal**: A physique observation's full shape — ratings, notes, confounder metadata, not-assessable handling — persists correctly and reads back out cleanly, with no MCP surface yet.
**Depends on**: Phase 15 (schema constants informed by the spike's measured results)
**Requirements**: PHYS-01, PHYS-02, PHYS-03, PHYS-04, PHYS-05
**Success Criteria** (what must be TRUE):
  1. A `PhysiqueObservation` header row plus one `PhysiqueRating` child row per rated `(observation, muscle_group)` can be inserted and read back through `backend/app/db/repositories/physique.py`, keyed on the existing 19-value `CanonicalMuscleGroup` enum with no new taxonomy.
  2. Ratings persist as a `String`-backed `StrEnum` guarded by a named `CHECK` constraint — never a native PostgreSQL `ENUM` type — verified by `test_migrations_round_trip` passing unchanged.
  3. `Not Assessable` is representable per muscle group with a short reason rather than a forced numeric guess; `abductors` and `adductors` can be recorded this way without special-casing.
  4. Each observation stores three independently-capped free-text note fields (leanness, conditioning, symmetry) plus confounder metadata (photo angles present, pose state as a bounded enum, a short conditions note) as fields separate from the ratings — "the rating changed" and "conditions were comparable" stay two independently inspectable facts.
  5. Migration `0007` (next after `0006_user_program_history.py`) applies cleanly and round-trips (up/down) without orphaning a `pg_type`.
**Plans**: 3 plans

Plans:
- [x] 16-01-PLAN.md — Declare the PhysiqueObservation/PhysiqueRating models with the Phase 15 locked constants and extend the fast-suite metadata guards
- [ ] 16-02-PLAN.md — Hand-write migration 0007, wire the new tables into the test-fixture purge, and prove every CHECK constraint refuses a real bad value
- [ ] 16-03-PLAN.md — Build repositories/physique.py (create_observation + get_latest_observation) and prove the 19-row round trip, refusal paths and tenant scoping

### Phase 17: Physique Analytics & MCP Read/Write Tools
**Goal**: Claude can record one physique observation per photo session and retrieve the prior one for context; deterministic diff and volume-correlation analytics exist underneath; the write-tool guard suite reflects a truthful two-write-module system rather than a widened but still-uniform one.
**Depends on**: Phase 16
**Requirements**: PHYS-06, PHYS-07, PHYS-08, PHYS-09, PHYS-10, PHYS-11, MCP-07, MCP-08
**Success Criteria** (what must be TRUE):
  1. Calling `fitness_log_physique_observation` once persists a complete observation (ratings + notes + confounders), is annotated `destructive_hint=False`/no confirmation-token ceremony, and every response carries a required (never `| None`) disclaimer stating the ratings are subjective model output, not measurement.
  2. Calling a dedicated read tool (`fitness_get_latest_physique_observation`) returns the most recent prior observation's ratings, notes and confounder metadata; both the write tool's own description and `docs/coaching-instructions.md` state the read tool is the required precursor to logging a new one.
  3. A later observation can mark an earlier one superseded with a reason; the superseded row is retained (never hard-deleted) and excluded from `analytics/physique.py`'s diff output.
  4. `get_physique_diff` returns improved/unchanged/regressed/not-comparable per muscle group computed from stored rows only, with no model call, no image, and no arithmetic beyond ordinal comparison.
  5. A composed function in `analytics/physique.py` cross-references physique ratings against `get_muscle_group_volume` ("is the underdeveloped area also the undertrained one?"), so BRETT performs the join and Claude is never asked to correlate two separate tool responses.
  6. The write-guard suite describes a truthful two-write-module system: `backend/tests/test_mcp_isolation.py`'s `_WRITE_ALLOWLIST` asserts exact membership of `{"program_switch.py", "physique.py"}` with `len == 2` (widened deliberately, never loosened to a prefix/substring check), and `backend/tests/test_mcp_tool_schemas.py`'s uniform `destructiveHint=True` assertion is restructured into a per-tool `EXPECTED_WRITE_ANNOTATIONS` mapping that asserts the physique tool's non-destructive annotations distinctly from `program_switch.py`'s destructive ones. A hypothetical third write tool still fails the suite rather than passing by being skipped.
**Plans**: TBD

### Phase 18: Monthly Report Physique Integration
**Goal**: The monthly report reads across training, nutrition, measurements and visible physique in one view; the weekly report structurally cannot carry it.
**Depends on**: Phase 17 (needs `analytics/physique.py`'s diff and cross-reference functions to compose against)
**Requirements**: RPT-04, RPT-05
**Success Criteria** (what must be TRUE):
  1. `fitness_get_monthly_report` includes a physique section (latest observation, per-muscle diff, volume cross-reference) populated via a one-line period conditional inside `compose_report` — `physique: PhysiqueSection | None` on `ReportResult`, mirroring the shipped `narrative` field's None-only-when-weekly precedent — while `fitness_get_weekly_report`'s response has no `physique` attribute at all (a structural, tested absence via `hasattr`/model-field-set check, not omission by convention).
  2. `build_narrative`'s physique section is byte-identical across repeated runs on the same input, contains none of the ten banned recommendation tokens (`_BANNED_NARRATIVE_TOKENS`), and every number it renders already exists in `report.model_dump_json()`.
  3. Claude-authored free-text notes (leanness/conditioning/symmetry) are present as structured JSON fields on the report response so Claude can relay them conversationally, but never appear inside `build_narrative`'s own rendered markdown output.
  4. A new assertion confirms every rating/verdict word rendered in the narrative matches the corresponding `.value` read directly off `report.physique`'s own fields — the word-level equivalent of the existing numeric-provenance test.
**Plans**: TBD

### Phase 19: Production Deploy of Migration 0007
**Goal**: Phase 14's deploy-safety fix is proven by a real deploy of this milestone's own schema change, not merely asserted.
**Depends on**: Phase 14 (the fixed pipeline) and Phase 16 (migration `0007` must exist); sequenced last per the milestone's ordering constraint so it closes the loop after the feature itself has shipped
**Requirements**: DEPLOY-05
**Success Criteria** (what must be TRUE):
  1. Migration `0007` reaches the production database through the Phase 14 pre-deploy mechanism, with no manual `psql`/operator intervention required.
  2. `alembic current` on production matches `alembic heads` immediately after the deploy completes.
  3. The live MCP tool registry in production includes the physique tools, and a real call against the deployed schema (e.g. `fitness_get_latest_physique_observation` returning an empty-but-valid response, or a real logged observation) succeeds.
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 14 → 15 → 16 → 17 → 18 → 19

| Phase | Plans Complete | Status | Completed |
|-------|-----------------|--------|-----------|
| 1. Backend Foundation | 5/5 | Shipped (v1.0) | 2026-08-23 |
| 2. Deploy & Connector Auth Spike | 8/8 | Shipped (v1.0) | 2026-08-29 |
| 3. Hevy Integration & Normalization | 12/12 | Shipped (v1.0) | 2026-08-30 |
| 4. Volume & Frequency Analytics | 9/9 | Shipped (v1.0) | 2026-08-30 |
| 5. Progression, Records & Recomposition Analytics | 10/10 | Shipped (v1.0) | 2026-08-31 |
| 6. MCP Tools | 11/11 | Shipped (v1.0) | 2026-09-01 |
| 7. Production Hardening & Coaching Layer | 10/10 | Shipped (v1.0) | 2026-09-01 |
| 8. Apple Health & Nutrition Ingest | 8/8 | Shipped (v2.0) | 2026-09-03 |
| 9. Historical Apple Health Backfill | 7/7 | Shipped (v2.0) | 2026-09-03 |
| 10. Max-Weight Strength Signal | 1/1 | Shipped (v2.0) | 2026-09-03 |
| 11. Body Measurement History | 3/3 | Shipped (v2.0) | 2026-09-04 |
| 12. Training Programs & Confirm-Gated Write Tool | 5/5 | Shipped (v2.0) | 2026-09-04 |
| 13. Health Analytics, Reports & Coaching Style | 10/10 | Shipped (v2.0) | 2026-09-05 |
| 14. Deploy Pipeline Migration Safety | 3/3 | Complete    | 2026-09-07 |
| 15. Physique Rating Calibration Spike | 2/2 | Complete    | 2026-09-08 |
| 16. Physique Data Model & Repository | 1/3 | In Progress|  |
| 17. Physique Analytics & MCP Read/Write Tools | 0/TBD | Not started | - |
| 18. Monthly Report Physique Integration | 0/TBD | Not started | - |
| 19. Production Deploy of Migration 0007 | 0/TBD | Not started | - |
