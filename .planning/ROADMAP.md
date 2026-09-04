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

**Milestone Goal:** Extend BRETT beyond Hevy-only into a full recomposition coach — ingesting Apple Health activity and nutrition data, surfacing max weight lifted alongside estimated 1RM so Claude can explain strength trends the way the user actually thinks about them, remembering physical progress over time, adapting to the active training program, and answering with concise, report-ready summaries.

- [x] **Phase 8: Apple Health & Nutrition Ingest** - Authenticated, idempotent, Hevy-filtered webhook receiver landing activity and nutrition data in BRETT (complete 2026-09-03)
- [ ] **Phase 9: Historical Apple Health Backfill** - One-time streaming import of 4.5 years of history from the user's `export.xml`
- [x] **Phase 10: Max-Weight Strength Signal** - Last max-weight-lifted surfaced as a labelled secondary display field on progression/plateau responses; estimated-1RM classification unchanged (completed 2026-09-03)
- [x] **Phase 11: Body Measurement History** - Trend/comparison analytics across circumference and body-composition measurements — not weight-only — over data already synced from Hevy (completed 2026-09-04)
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
**Plans**: 7 plans in 6 waves

Plans:
- [x] 09-01-PLAN.md — synthetic `export_sample.xml` fixture, XML loader, `realfile` marker, and the stale `normalize.py` Pitfall N-3 docstring correction (wave 1)
- [x] 09-02-PLAN.md — `backfill.py` read half: 12-entry `HK_TO_WIRE`, streaming `iterparse` with the two-clear discipline, per-record skip-not-abort, literal `HAEPayload` handoff (wave 2)
- [x] 09-03-PLAN.md — write half: chunked `ON CONFLICT` upsert with a per-row SAVEPOINT fallback, dry-run gate, freshness bookkeeping, and the SC#3 container proof (wave 3)
- [x] 09-04-PLAN.md — `backfill-apple-health` CLI verb with a required `--dry-run`/`--write` choice, and its parser/bootstrap guards (wave 4)
- [x] 09-05-PLAN.md — opt-in `realfile` test pinning the real 191 MB export, plus the `sample_count` false-positive note in the operator doc (wave 3)
- [x] 09-06-PLAN.md — §10 backfill runbook, then the rehearsed `--dry-run` against the real file with its figures recorded (wave 5)
- [x] 09-07-PLAN.md — the production import (human-gated on the D-02 credential) and the dated verification record (wave 6)

Notes for planning:
- Streaming `iterparse` with `elem.clear()`; `ElementTree.parse()` builds a 1.5-2 GB DOM and OOMs (PITFALLS #6).
- Runs as an `app.cli` subcommand against the database, never through the web service — a 191 MB HTTP upload walks into the 32 MiB Cloud Run cap.
- Must reuse Phase 8's normalizer and upsert path verbatim. Two parsers produce two shapes and the historical trend silently disagrees with the ongoing one.

### Phase 10: Max-Weight Strength Signal
**Goal**: Claude can cite the actual last weight the user lifted when explaining why an exercise is flagged as plateaued, without that figure ever driving, contradicting, or being confused with the estimated-1RM classification that continues to produce every verdict.
**Depends on**: Nothing in v2.0 (independent of Phases 8-9; movable earlier if Apple Health configuration stalls)
**Requirements**: STR-01, STR-02, STR-03, STR-04
**Success Criteria** (what must be TRUE):
  1. Trend and plateau classification (`ExerciseTrend.verdict`, `PlateauResult.plateaued`) remain fully driven by estimated-1RM, unchanged from today — a before/after comparison on live data shows identical verdicts.
  2. `PlateauResult` (`fitness_get_plateaus`) carries a last-max-weight-lifted figure, sourced from the existing `best_set_per_day`/`SessionBest.best_weight_kg` fold, clearly labelled as a secondary display field that plays no role in computing `plateaued`, `threshold_percent`, or any other existing field.
  3. Recomposition status's progression input still comes from the e1RM-based trend, unchanged — confirmed, not merely assumed, against live data.
  4. A bodyweight or duration-only exercise reports "we could not tell" for the new field (None + reason) rather than a weight of 0 kg presented as a real observation.
  5. `ExerciseTrend` and `fitness_get_exercise_progression` are unchanged — the latter already returns `best_weight_kg` per day, which is why "am I progressing on bench press?" needs no code change to answer with the last weight lifted.
**Plans**: 1 plan in 1 wave

Plans:
- [x] 10-01-PLAN.md — `PlateauResult.last_max_weight_kg` (schemas.py + get_plateaus), D-07/D-08 regression tests, MCP passthrough proof, budget check, and STR-01/STR-03/STR-04 regression confirmation (wave 1)

Notes for planning:
- **Scope correction, 2026-09-03 discuss-phase session, two rounds:** (1) this phase was originally scoped (see PITFALLS #10/#11/#12, ARCHITECTURE.md §3) as max-weight becoming the primary classifier with e1RM as secondary — a new classifier, re-derived dead-bands, changed insufficient-data semantics. The user reversed this: e1RM keeps classifying, unchanged; max weight is a labelled display-only field. (2) Follow-up investigation during the same session found `ExerciseTrend` (PROG-02) is never exposed through any MCP tool — it only feeds the aggregate whole-account signal in `fitness_get_recomposition_status`/`fitness_get_training_summary` — and `fitness_get_exercise_progression` already returns `best_weight_kg` per day. So the only response with an actual gap (e1RM-derived numbers only, no real weight figure) is `PlateauResult`. The user confirmed: scope narrows to `PlateauResult` only. Do **not** add a field to `ExerciseTrend` — it would be dead weight nothing reads.
- The dead-band re-derivation research flag (PITFALLS #12) and the insufficient-data semantics question (PITFALLS #11) **no longer apply** — the classifier's input isn't changing, so nothing downstream of it needs recalibrating. Treat PITFALLS #10/#11/#12 and the ARCHITECTURE.md §3 table as historical context for why this scope was originally proposed, not as instructions to implement.
- Two-signal design still applies, just not for classification: `best_set_per_day` already computes `best_weight_kg` for every session (including the ~17% with no e1RM-qualifying set) — reuse that fold directly as the source of the new field; do not add a second "best set" rule.
- Reuse the existing `_NO_WEIGHT_RANK` sentinel handling so a bodyweight/duration-only exercise's new field comes back as `None` with a reason, not a real `0 kg` — same honesty requirement PITFALLS #11 described, now scoped to this one display field instead of a classifier input.
- **Decided in discussion:** the new field is the most recent training day in the lookback window (`series[-1].best_weight_kg` after the ascending-by-`local_day` sort `get_plateaus` already produces), regardless of whether that day qualified for the e1RM plateau streak — not the most recent streak-qualifying session. On a deload/high-rep week these can differ; the literal "last weight you lifted" wins.
- **Ripple effect, not yet resolved:** Phase 12's "Depends on: Phase 10 (recomposition thresholds settle once, not twice)" assumed Phase 10 would recalibrate `RECOMP_PROGRESSION_NET_BAND` against a new verdict distribution. Under this narrower scope, Phase 10 doesn't touch that constant at all, so the dependency rationale is stale. Re-examine it when Phase 12 is discussed rather than assuming it still holds.

### Phase 11: Body Measurement History
**Goal**: Asked how a circumference or body-composition metric has changed — not just body weight — Claude answers from data already synced from Hevy, or honestly reports insufficient coverage.
**Depends on**: Nothing in v2.0 (independent; sequenced here to sit beside Phase 12's data-model work and before reports need it)
**Requirements**: BODY-05 (~~BODY-03~~, ~~BODY-04~~ dropped — see Scope Reversal below)
**Success Criteria** (what must be TRUE):
  1. Asked "how has my waist changed?" (or any of the 16 non-weight `body_measurements` columns), Claude answers with a latest-vs-90-days-ago comparison sourced from already-synced Hevy data, or honestly reports insufficient coverage for that specific metric.
  2. A stale "latest" reading (2+ readings exist but the most recent is old) is reported as stale, distinct from a metric with no usable data at all.
  3. Existing weight-trend behavior (`fitness_get_body_weight_trend`, BODY-01) is unchanged — this phase adds a new, separate tool rather than modifying it.
**Plans**: 3 plans in 3 waves

Plans:
- [x] 11-01-PLAN.md — `BodyMeasurementMetric` enum + `BodyMeasurementTrendResult`, the `{90: 2}` coverage floor, the column-scoped `earliest_metric_measurement_at`, and the `GoldenBuilder` fixture extension (wave 1)
- [x] 11-02-PLAN.md — `analytics/body_measurements.py`: the one generic latest-vs-earliest 90-day function, with the floor/staleness four-quadrant proof (wave 2)
- [x] 11-03-PLAN.md — `fitness_get_body_measurement_trend` (the 14th tool), its registration, the six structural drift guards, and the coaching-doc entry (wave 3)

Notes for planning:
- **Scope correction, 2026-09-03 discuss-phase session:** this phase was originally scoped (see PITFALLS #9, ROADMAP notes below the strikethrough) around a manual-entry write path (BODY-03) plus the source-merge fix that path would trigger (BODY-04). The user reversed this: Hevy's app already captures every measurement they log, and BRETT already syncs it automatically (`backend/app/integrations/hevy/body.py`) — there is no manual-entry need. BODY-03 and BODY-04 are **dropped from v2.0 entirely**, not deferred to a later phase. See `.planning/phases/11-body-measurement-history/11-CONTEXT.md` for the full discussion.
- Because no manual rows will ever be written, `_dedupe_by_day`'s row-grain "manual wins" precedence bug (PITFALLS #9) stays dormant — exactly as it is today. No source-precedence map, no per-column merge logic, no regression test for multi-source column resolution. This is a deliberate no-op, not an oversight.
- BODY-05's design does **not** reuse BODY-01's rolling-average shape. Data is thin (`fat_percent`/`lean_mass_kg` are 0 of 123 live rows, `waist_cm` is 15 of 123) — a 7/14/30-day-average design with 3/5/10-measured-day floors would return `insufficient_data` almost universally. Instead: latest reading vs. earliest reading inside a fixed 90-day window, with its own (lower) coverage floor tailored to spot-check metrics, and staleness flagged separately from insufficient data.
- Architecture: one generic metric-parameterized analytics function + one MCP tool taking a metric selector (a `StrEnum`, matching `PersonalRecordType`/`TrendVerdict` in `analytics/schemas.py` — not a free string), covering all 16 non-weight columns. Not 16 near-duplicate per-metric functions.
- No CLI write path, no bulk import format — those were discussed before the scope reversal and are now moot.

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
**Plans**: 5 plans in 4 waves

Plans:
- [x] 12-01-PLAN.md — `TrainingProgram` enum, `user_program_history` + `program_switch_tokens` models, migration 0006 with the live-data-derived D-08 seed, and the GoldenBuilder/purge fixtures (wave 1)
- [x] 12-02-PLAN.md — `app/db/repositories/programs.py`: period resolution plus the atomic single-use token issue/consume/apply, with the TTL, replay, wrong-program and interleaving proofs (wave 2)
- [ ] 12-03-PLAN.md — `recomposition.py` per-program thresholds and three explicit label matrices (76 cells), plus `RecompositionResult`'s active-program and D-10 straddle fields (wave 3)
- [ ] 12-04-PLAN.md — `writable_session`, the two wire models, the read tool and the confirm-gated write tool, and the narrowed single-module write allowlist (wave 3)
- [ ] 12-05-PLAN.md — registration outside the `_TOOLS` loop with explicit write annotations, the exact read-only/write partition, budgets, leak scans and the coaching-doc entry (wave 4)

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
| 9. Historical Apple Health Backfill | v2.0 | 0/7 | Planned | - |
| 10. Max-Weight Strength Signal | v2.0 | 1/1 | Complete   | 2026-09-03 |
| 11. Body Measurement History | v2.0 | 3/3 | Complete    | 2026-09-04 |
| 12. Training Programs & Confirm-Gated Write Tool | v2.0 | 2/5 | In Progress|  |
| 13. Health Analytics, Reports & Coaching Style | v2.0 | 0/TBD | Not started | - |

## Requirement Coverage (v2.0)

All 28 originally-defined v2.0 requirements map to exactly one phase. No orphans, no duplicates.
2 (BODY-03, BODY-04) were dropped from Phase 11 during its 2026-09-03 discuss-phase session — see
`.planning/phases/11-body-measurement-history/11-CONTEXT.md`. 26 remain active.

| Phase | Requirements | Count |
|-------|--------------|-------|
| 8. Apple Health & Nutrition Ingest | HEALTH-06, HEALTH-07, HEALTH-08, HEALTH-09, HEALTH-11, NUTR-02, NUTR-03, NUTR-05 | 8 |
| 9. Historical Apple Health Backfill | HEALTH-10 | 1 |
| 10. Max-Weight Strength Signal | STR-01, STR-02, STR-03, STR-04 | 4 |
| 11. Body Measurement History | BODY-05 (~~BODY-03~~, ~~BODY-04~~ dropped) | 1 |
| 12. Training Programs & Confirm-Gated Write Tool | GOAL-01, GOAL-02, GOAL-03, GOAL-04 | 4 |
| 13. Health Analytics, Reports & Coaching Style | HEALTH-12, NUTR-04, NUTR-06, RPT-01, RPT-02, RPT-03, COACH-02, COACH-03 | 8 |
| **Total (active)** | | **26** |

---
*v2.0 roadmap created: 2026-09-02*
