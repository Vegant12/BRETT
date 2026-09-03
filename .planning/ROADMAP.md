# Roadmap: BRETT

## Milestones

- ✅ **v1.0 MVP** — Phases 1-7 (shipped 2026-09-02)
- 🚧 **v2.0 Apple Health, Strength Tracking & Coaching Programs** — Phases 8-13 (in progress)

Full v1.0 phase detail archived at `.planning/milestones/v1.0-ROADMAP.md`.

## Phases

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

### 🚧 v2.0 Apple Health, Strength Tracking & Coaching Programs (In Progress)

**Milestone Goal:** Extend BRETT beyond Hevy-only into a full recomposition coach — ingesting Apple Health activity and nutrition data, tracking strength the way the user actually trains (max weight, not just estimated 1RM), remembering physical progress over time, adapting to the active training program, and answering with concise, report-ready summaries.

- [x] **Phase 8: Apple Health & Nutrition Ingest** - Authenticated, idempotent, Hevy-filtered webhook receiver landing activity and nutrition data in BRETT (complete 2026-09-03)
- [ ] **Phase 9: Historical Apple Health Backfill** - One-time streaming import of 4.5 years of history from the user's `export.xml`
- [ ] **Phase 10: Max-Weight Strength Signal** - Progression and plateau verdicts driven by heaviest weight lifted, with estimated 1RM retained as a second opinion
- [ ] **Phase 11: Body Measurement History** - Manual measurement entry, per-field source merging, and trends beyond weight-only
- [ ] **Phase 12: Training Programs & Confirm-Gated Write Tool** - Programs as real data, program-aware thresholds, and BRETT's only MCP write path
- [ ] **Phase 13: Health Analytics, Reports & Coaching Style** - Activity/nutrition trends, weekly and monthly report tools, and a tightened coaching document

## Phase Details

### Phase 8: Apple Health & Nutrition Ingest
**Goal**: Apple Health activity and nutrition data flows from the user's phone into BRETT continuously — authenticated, deduplicated, and free of Hevy re-exports.
**Depends on**: Phase 7 (v1.0 production deployment)
**Requirements**: HEALTH-06, HEALTH-07, HEALTH-08, HEALTH-09, HEALTH-11, NUTR-02, NUTR-03, NUTR-05
**Success Criteria** (what must be TRUE):
  1. A real Health Auto Export run from the user's phone lands steps, active/basal energy, distance, flights climbed, and calories plus the six tracked macros in BRETT — verified against the live deployment, not a fixture.
  2. A POST to the ingest endpoint with no credential or a wrong credential is rejected, writes nothing, and returns no detail about why.
  3. Re-sending an overlapping export window leaves row counts and every computed daily value unchanged.
  4. Apple Health workouts and Hevy-originated body-mass rows never enter BRETT's training or body data — the volume, frequency, and body-weight numbers Claude reports are identical before and after Apple Health data exists.
  5. Claude can see when Apple Health data last arrived, reported separately from when Hevy last synced, through the existing freshness envelope.
**Plans**: 8 plans in 6 waves

Plans:
- [x] 08-01-PLAN.md — `health_daily_metrics` table, migration 0005, and the HAE test fixtures (wave 1)
- [x] 08-02-PLAN.md — freshness envelope takes `(provider, resource)` pairs; two Apple Health resources (wave 1)
- [x] 08-03-PLAN.md — ingest secret, dedicated rate-limit bucket, body cap, `--memory=1Gi` (wave 1)
- [x] 08-04-PLAN.md — HAE package core: metric registry, wire quarantine, errors, bearer verifier (wave 2)
- [x] 08-05-PLAN.md — normalize: Hevy-source exclusion, unit conversion, whole-payload aggregation (wave 3)
- [x] 08-06-PLAN.md — idempotent upsert + independent activity/nutrition freshness bookkeeping (wave 4)
- [x] 08-07-PLAN.md — the webhook route, its wiring above the MCP mount, and the criterion-#4 proof (wave 5)
- [x] 08-08-PLAN.md — setup doc, secret creation, deploy, and the live device verification checkpoint (wave 6)
      **COMPLETE (2026-09-03).** All three tasks done. A real Health Auto Export run from the
      user's phone landed all 12 registry metrics live; a repeat run proved idempotency (23 rows,
      unchanged). Two live incidents diagnosed and fixed along the way: a device misconfiguration
      (413, Aggregate Data toggle off) and a production migration gap (0004 vs the deployed
      code's 0005, fixed with `alembic upgrade head` against production). RESEARCH Assumption A1
      closed as MOOT — Hevy is not currently writing to HealthKit for this user at all, so the
      exclusion predicate had nothing live to match; it stays in place for Phase 9's `export.xml`
      backfill. **All five success criteria verified** — see `08-VERIFICATION.md` (status: passed).

Notes for planning:
- Register the ingest route **above** `app.mount("/", mcp_app)` in `main.py` — the mount is a catch-all and a route below it is dead in production (PITFALLS #1).
- Ingest gets its **own** rate-limit bucket, not an exemption — Health Auto Export has no documented retry, so a 429 is permanent data loss (PITFALLS #2).
- `build_freshness` must take `(provider, resource)` pairs rather than one default provider; this is on the critical path for every health-aware response (PITFALLS #7).
- Resolve the `weight_body_mass` vs `weight_&_body_mass` metric-name spelling and capture one real payload as a fixture before writing the normalizer (SUMMARY.md gaps).
- Deploy change required: `--memory=1Gi`, a body-size cap returning 413 before parse, and `HEALTH_INGEST_SECRET` in Secret Manager (PITFALLS #5).

### Phase 9: Historical Apple Health Backfill
**Goal**: 4.5 years of Apple Health activity and nutrition history is present in BRETT, imported once from the user's existing `export.xml` through the same code path the live webhook uses.
**Depends on**: Phase 8
**Requirements**: HEALTH-10
**Success Criteria** (what must be TRUE):
  1. The real 191 MB `export.xml` imports to completion within the instance memory budget — tested against the actual file, not a trimmed fixture.
  2. Activity and nutrition history from 2022-03 through the export date is queryable in BRETT alongside the ongoing webhook feed.
  3. Days covered by both the backfill and the live webhook hold one value per metric per day, not two — running the backfill after the webhook has been live is a no-op on overlapping days.
  4. No Hevy-originated workout or body-mass row from the export enters BRETT.
**Plans**: TBD

Notes for planning:
- Streaming `iterparse` with `elem.clear()`; `ElementTree.parse()` builds a 1.5-2 GB DOM and OOMs (PITFALLS #6).
- Runs as an `app.cli` subcommand against the database, never through the web service — a 191 MB HTTP upload walks into the 32 MiB Cloud Run cap.
- Must reuse Phase 8's normalizer and upsert path verbatim. Two parsers produce two shapes and the historical trend silently disagrees with the ongoing one.

### Phase 10: Max-Weight Strength Signal
**Goal**: Progression and plateau verdicts reflect the heaviest weight the user actually lifted, with estimated 1RM retained as a visible second opinion rather than deleted.
**Depends on**: Nothing in v2.0 (independent of Phases 8-9; movable earlier if Apple Health configuration stalls)
**Requirements**: STR-01, STR-02, STR-03, STR-04
**Success Criteria** (what must be TRUE):
  1. Asked "am I progressing on bench press?", Claude reports a trend classified from max weight lifted, with the estimated-1RM view carried alongside it as a labelled secondary signal.
  2. Plateau reports name the max-weight threshold and window they used, with both re-derived against plate increments and still sharing one underlying number so the trend and plateau verdicts cannot contradict each other.
  3. An exercise where load is flat but reps are climbing is visibly distinguishable — "max weight flat, estimated 1RM improving" — instead of being silently reported as stable.
  4. The recomposition verdict's progression input comes from the max-weight trend, and the before/after verdict distribution on live data is recorded rather than assumed unchanged.
  5. A bodyweight or duration-only exercise still reports "we could not tell" rather than a max weight of 0 kg presented as a real observation.
**Plans**: TBD

Notes for planning:
- `progression.py`'s own docstring argues *against* max weight and explains why. Quote and answer it in the phase context; do not delete it (PITFALLS #10).
- Two-signal design, not a substitution — `best_set_per_day` already computes `best_weight_kg`; add a second projection of the same fold, never a second "best set" rule.
- Max weight is ungated where e1RM is gated, so `UNCLEAR`, `no_estimate_reason`, and `scan_plateau`'s skip semantics all change meaning. Decide per consumer what "insufficient" means before writing code (PITFALLS #11).
- **Research flag:** the re-derived dead-band values have no correct answer on paper. Live-data calibration, reported as an improving/stable/declining split like D-18's original, is the actual work (PITFALLS #12).

### Phase 11: Body Measurement History
**Goal**: The user can record the measurements Hevy never captures, and see how circumference and composition — not just body weight — have moved over time.
**Depends on**: Nothing in v2.0 (independent; sequenced here to sit beside Phase 12's data-model work and before reports need it)
**Requirements**: BODY-03, BODY-04, BODY-05
**Success Criteria** (what must be TRUE):
  1. User can record a body measurement — weight and/or any circumference/composition field — and it is stored as a manual entry.
  2. A manual entry on a day that already has a Hevy row keeps both sources' data: the manual weight wins, and the Hevy waist and chest readings for that day survive rather than disappearing.
  3. Asked "how has my waist changed?", Claude answers with a trend across circumference/composition columns, or honestly reports insufficient coverage for that specific metric.
**Plans**: TBD

Notes for planning:
- BODY-04 must ship **in this phase**, with BODY-03, not after. `_dedupe_by_day`'s row-grain "manual wins" rule is dormant only because zero manual rows exist; the first manual entry activates it (PITFALLS #9).
- Replace alphabetical source ordering with an explicit `MappingProxyType` precedence map that raises on an unknown source, and resolve **per column**, not per row.
- Regression test that does not exist today: one day, multiple sources, partially overlapping columns, every column resolving independently.
- Data is thin (`fat_percent`/`lean_mass_kg` are 0 of 123 live rows, `waist_cm` is 15 of 123) — per-metric coverage floors are required or most windows honestly return `insufficient_data`.
- Write path: CLI (`add-measurement` + bulk import) is recommended over a new authenticated HTTP route; confirm explicitly in the phase context rather than defaulting.

### Phase 12: Training Programs & Confirm-Gated Write Tool
**Goal**: The user's training program is real, switchable data — and switching it takes a genuine two-step confirmation, while every other MCP tool stays provably read-only.
**Depends on**: Phase 10 (recomposition thresholds settle once, not twice)
**Requirements**: GOAL-01, GOAL-02, GOAL-03, GOAL-04
**Success Criteria** (what must be TRUE):
  1. Asked "what program am I on?", Claude answers from stored data, including when that program started and what it replaced.
  2. Recomposition verdicts and recommendations use the active program's thresholds, and a verdict whose lookback window straddles a program switch reports that fact instead of silently picking one.
  3. A single tool call cannot change the active program — the first call writes nothing and returns a one-time token; only a second call echoing that exact token performs the switch.
  4. A token issued for one program cannot be replayed to switch to a different one, cannot be reused after consumption, and stops working after its short TTL expires.
  5. Every MCP tool except the one named program-switch tool is still machine-checked as read-only, and adding a second write module would fail the test suite.
**Plans**: TBD

Notes for planning:
- **Defining criterion is #3.** `confirm: bool` is a naming convention, not a gate — the model can set it `true` on the first call. `ctx.elicit()` is unavailable under `stateless_http=True` and is not a guaranteed human gate anyway (PITFALLS #13).
- Narrow the three static guards to a named single-module allowlist asserting **exactly one** entry; never delete or relax them. `read_only_session` must not be weakened — add a `writable_session` sibling (PITFALLS #14).
- Register the write tool **outside** the shared `_TOOLS`/`READ_ONLY` loop with all four `ToolAnnotations` set explicitly; SDK defaults advertise a destructive open-world tool.
- Append-only `user_program_history` with a partial unique index, not a mutable `users.active_program` column — a mutable value retroactively re-classifies the last 12 weeks of verdicts (PITFALLS #16).
- Give the write tool a three-state result (`applied`/`not_applied`/`unknown`); `safe_tool`'s degraded payload otherwise invites a retry that double-applies (PITFALLS #15).
- **Research flag:** token issuance/storage/TTL/consumption, `required_scopes` strategy against WorkOS AuthKit claims, and program-dependent vs program-independent label matrix are all explicit design decisions for the phase context.

### Phase 13: Health Analytics, Reports & Coaching Style
**Goal**: Claude delivers concise, report-ready answers that combine training, activity, nutrition, measurements, and program context from one call.
**Depends on**: Phases 8, 9, 10, 11, 12
**Requirements**: HEALTH-12, NUTR-04, NUTR-06, RPT-01, RPT-02, RPT-03, COACH-02, COACH-03
**Success Criteria** (what must be TRUE):
  1. Asked "how active have I been?", Claude reports steps, active/basal energy, and distance trends over 7/14/30-day windows from real Apple Health data.
  2. Asked about nutrition, Claude reports calorie and macro averages and trends from a dedicated read-only tool.
  3. One tool call returns a complete weekly report — volume, strength progression, weight and measurement changes, nutrition summary, trends, recommendations — and another does the same for a month, both inside the measured latency and response-size budgets.
  4. A real Claude scheduled task has been run against the report tools, and the outcome — working, or broken with a documented workaround — is written into `docs/coaching-instructions.md` rather than assumed.
  5. Claude's coaching answers are short and cite real figures, and the coaching document describes the v2.0 tool surface without drifting from the live tool registry.
**Plans**: TBD

Notes for planning:
- **Run the scheduled-task spike first, before the report tools are built.** Two GitHub issues (closed "not planned") report scheduled sessions completing the MCP handshake but never injecting tool schemas. A negative result should reshape scope, not sink the phase at its end (PITFALLS #17).
- `analytics/reports.py` owns composition and windowing, never arithmetic — `summary.py` is the model to copy. A report with its own volume sum is how the report and the summary disagree about the same week.
- Closed-period anchoring: recommend reporting closed-period volume/frequency/PRs while carrying the anchored-on-today recomposition verdict beside them, clearly labelled. Decide explicitly in the phase context.
- Budget is measured, not estimated: `fitness_get_training_summary` is ~9.5 KB against a 16 KB cap and is already the most expensive call in the system. New `MAX_REPORT_*` caps belong in `_common.py`'s existing budget block.
- Activity data is recomposition **context**, never a classifier input. Recovery/sleep analytics are cut, not deferred — zero records exist.

## Progress

**Execution Order:**
Phases execute in numeric order: 8 → 9 → 10 → 11 → 12 → 13

| Phase | Milestone | Plans Complete | Status   | Completed  |
| ----- | --------- | --------------- | -------- | ---------- |
| 1. Backend Foundation | v1.0 | 5/5 | Complete | 2026-08-23 |
| 2. Deploy & Connector Auth Spike | v1.0 | 8/8 | Complete | 2026-08-29 |
| 3. Hevy Integration & Normalization | v1.0 | 12/12 | Complete | 2026-08-30 |
| 4. Volume & Frequency Analytics | v1.0 | 9/9 | Complete | 2026-08-30 |
| 5. Progression, Records & Recomposition Analytics | v1.0 | 10/10 | Complete | 2026-08-31 |
| 6. MCP Tools | v1.0 | 11/11 | Complete | 2026-09-01 |
| 7. Production Hardening & Coaching Layer | v1.0 | 10/10 | Complete | 2026-09-01 |
| 8. Apple Health & Nutrition Ingest | v2.0 | 8/8 | Complete | 2026-09-03 |
| 9. Historical Apple Health Backfill | v2.0 | 0/TBD | Not started | - |
| 10. Max-Weight Strength Signal | v2.0 | 0/TBD | Not started | - |
| 11. Body Measurement History | v2.0 | 0/TBD | Not started | - |
| 12. Training Programs & Confirm-Gated Write Tool | v2.0 | 0/TBD | Not started | - |
| 13. Health Analytics, Reports & Coaching Style | v2.0 | 0/TBD | Not started | - |

## Requirement Coverage (v2.0)

All 28 v2.0 requirements map to exactly one phase. No orphans, no duplicates.

| Phase | Requirements | Count |
|-------|--------------|-------|
| 8. Apple Health & Nutrition Ingest | HEALTH-06, HEALTH-07, HEALTH-08, HEALTH-09, HEALTH-11, NUTR-02, NUTR-03, NUTR-05 | 8 |
| 9. Historical Apple Health Backfill | HEALTH-10 | 1 |
| 10. Max-Weight Strength Signal | STR-01, STR-02, STR-03, STR-04 | 4 |
| 11. Body Measurement History | BODY-03, BODY-04, BODY-05 | 3 |
| 12. Training Programs & Confirm-Gated Write Tool | GOAL-01, GOAL-02, GOAL-03, GOAL-04 | 4 |
| 13. Health Analytics, Reports & Coaching Style | HEALTH-12, NUTR-04, NUTR-06, RPT-01, RPT-02, RPT-03, COACH-02, COACH-03 | 8 |
| **Total** | | **28** |

---
*v2.0 roadmap created: 2026-09-02*
