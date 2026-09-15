# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

## Milestone: v1.0 — MVP

**Shipped:** 2026-09-02
**Phases:** 7 | **Plans:** 65 | **Tasks:** 151

### What Was Built
- FastAPI + PostgreSQL backend with UTC-storage enforcement and Asia/Jakarta-configurable timezone bucketing
- A working, production-verified auth path from a real Claude client to a self-hosted remote MCP server (WorkOS AuthKit OAuth 2.1)
- Idempotent Hevy sync (full + incremental) into a canonical 19-muscle taxonomy with an auditable manual-override layer
- A deterministic, SQL-first analytics layer (volume, frequency, progression, plateaus, PRs, period comparison, recomposition verdict) carrying a freshness/uncertainty envelope on every response
- Thirteen purpose-built, read-only, byte-budgeted MCP tools with zero secret-leakage, proven live against Cloud Run
- Production hardening proven against real infrastructure: a Neon PITR backup/restore drill, a live secret rotation, live rate limiting, and 6-hourly production Hevy sync

### What Worked
- **De-risking the biggest unknown first.** Phase 2 existed solely to answer "can a real Claude client authenticate to a remote MCP server at all?" before any analytics or tool work was built on that assumption. It overturned the standing "bearer token, not OAuth" decision — cheaply, in isolation, before the cost of being wrong compounded across five more phases.
- **Real-infrastructure verification over mocks for the claims that mattered.** Phase 7's hardening claims (backup/restore, secret rotation, rate limiting, connector round-trip) were each proven against the actual deployed Cloud Run + Neon + WorkOS stack, not simulated — so "done" meant the same thing as "would survive an incident."
- **Self-correcting plans.** Several plans (e.g. 02-01, 04-08, 07-01) caught and fixed their own defects mid-execution (a vacuous test, a stale worktree branch base, a docstring contradicting its own acceptance criteria) before they reached a SUMMARY — deviations were resolved in-flow rather than accumulating as debt.
- **Provider isolation held.** HEVY-05 (Hevy logic confined to `backend/app/integrations/hevy/`) is enforced by a standing static-analysis test, not just a code-review convention — it stayed true across 12 Hevy-touching plans in Phase 3 plus every later phase that consumed synced data.

### What Was Inefficient
- **REQUIREMENTS.md traceability drifted silently for three phases.** The checkbox list and traceability table were last synced through Phase 4 (2026-08-30); Phases 5, 6, and 7 all shipped and were validated in PROJECT.md without the corresponding REQUIREMENTS.md rows ever being flipped. Discovered only at milestone close, requiring a spot-check of 8 requirements against live code before archiving. Nothing in the per-phase completion flow currently forces this file to stay in sync with PROJECT.md's Validated section.
- **ROADMAP.md's top-level phase checklist had the same drift** (Phases 5-7 still shown unchecked despite full completion) — a second, independent symptom of the same missing sync step.
- **No milestone audit was run.** `/gsd-audit-milestone` was never invoked before this close; the gap was substituted with a targeted manual spot-check rather than the intended structured audit.

### Patterns Established
- Deploy-target pivots (Render → Cloud Run, 2026-08-27) get a dated Key Decision row with the old decision struck through and a "Superseded" pointer to the new row, rather than being edited in place — preserves the reasoning trail.
- Every analytics/MCP response type carries a freshness + coverage/uncertainty envelope (DQ-01/DQ-02) as a structural property of the return type, not an optional field — established in Phase 4, inherited by every later phase without re-litigation.

### Key Lessons
1. When a milestone's PROJECT.md Validated section and REQUIREMENTS.md traceability table are updated by different steps, they will drift — the next milestone should either update REQUIREMENTS.md's traceability row in the same step that adds a PROJECT.md Validated entry, or drop one of the two as redundant.
2. `gsd-tools.cjs audit-open` (and `--json`) throws `ReferenceError: output is not defined` in this install (bare `output()` call at gsd-tools.cjs:784/786 that should be `core.output()`) — a global GSD tooling bug, not a BRETT issue, worth reporting upstream before the next milestone close needs it.
3. Proving a hardening claim against real infrastructure (not a mock) once, at the end of the phase that introduces it, is worth the extra setup cost — it turns "should work" into "did work" for exactly the claims (backup/restore, secret rotation, rate limiting under load) where being wrong in production is expensive.

### Cost Observations
- Sessions: not tracked per-session in this project's artifacts
- Notable: 65 plans across 7 phases in 10 calendar days, with three same-day multi-plan phases (3, 6, 7 each landed 9-12 plans in a single day), suggesting the wave-based parallel execution model held up well for this codebase's size

---

## Milestone: v2.0 — Apple Health, Strength Tracking & Coaching Programs

**Shipped:** 2026-09-05
**Phases:** 6 | **Plans:** 34 | **Tasks:** 81 | **Commits:** 220 | **Timeline:** 4 days

### What Was Built

Apple Health activity and nutrition ingest via an authenticated, idempotent Health Auto Export
webhook (12 metrics), backed by 8,077 rows of history streamed once from a real 191 MB
`export.xml` through the *same* normalizer and upsert path as the live feed. Body-measurement
trends across all 16 non-weight columns. Max-weight-lifted as a labelled display field on
`PlateauResult`. Training programs as append-only, effective-dated data driving per-program
recomposition thresholds, switched through BRETT's only write path — a two-call, server-issued
token. Weekly and monthly report tools composing nine existing analytics functions. MCP registry
grew 13 → 20 tools; `backend/` grew to ~52.3k LOC and 925 test functions.

### What Worked

- **Spiking the milestone's central risk first, then re-proving it at the end.** RPT-03 (Claude
  scheduled sessions might never receive MCP tool schemas) was tested with `fitness_ping` in plan
  13-01 *before* any report tool existed, then re-run against the real `fitness_get_weekly_report`
  in 13-10. A negative result would have reshaped scope cheaply instead of sinking the phase at
  its end. Both PASSed. This is the same pattern that made v1.0's Phase 2 work, now confirmed
  twice.
- **Reusing one code path for historical and live data.** Phase 9's backfill went through Phase
  8's unchanged `normalize_payload` and upsert rather than a second parser. Two parsers produce
  two shapes and the historical trend silently disagrees with the ongoing one; this never came up
  because it structurally could not.
- **Narrowing the write guard instead of relaxing it.** Introducing the first MCP write tool could
  have weakened `read_only_session`. Instead a `writable_session` sibling was added and the guard
  narrowed to a named single-module allowlist, with the suite asserting a *second* write tool
  cannot pass by being skipped.
- **Scope reversals caught in discuss-phase, before code.** Phase 10 was rescoped from "max weight
  replaces e1RM as classifier" down to one display field, and Phase 11 dropped its entire
  manual-entry premise (BODY-03/BODY-04) — both after investigation showed the original scope
  solved a problem the user did not have. Zero code was written against either wrong scope.

### What Was Inefficient

- **The deploy migration gap cost three separate live incidents.** Production ran behind deployed
  code in Phase 8, during the Phase 9 operator run, and again in the Phase 13 spike. Every one was
  caught by live verification rather than by tooling, and the structural fix was deferred each
  time — so the same failure was paid for three times in one milestone.
- **REQUIREMENTS.md traceability drifted again.** Three requirements read `Pending` at close
  despite being complete and production-verified, needing manual reconciliation — the identical
  failure logged at v1.0 close. Fixing the symptom twice has not fixed the cause.
- **Sandbox tooling blocked a real measurement, twice.** `gcloud secrets versions access` was
  blocked by the command classifier in both the original research session and the Phase 13
  re-query, so D-06's nutrition coverage floors ship as a documented UNMEASURED fallback rather
  than a measured value.
- **Phase 10 produced one plan after two rounds of scope discussion.** The discussion was correct
  and cheap relative to building the wrong thing, but the original roadmap entry, PITFALLS #10-12
  and an ARCHITECTURE.md section all described a scope that was never built.

### Patterns Established

- Put `source_name` inside the natural key when a provider may re-export another provider's data —
  it turns an exclusion rule into a row-count fact rather than a summing decision.
- Report composition modules own windowing and assembly, never arithmetic. `analytics/reports.py`
  calls nine existing functions; a report with its own volume sum is how a report and a summary
  come to disagree about the same week.
- A `confirm: bool` parameter is not a gate. A server-issued, single-use, target-bound, TTL-limited
  token that the caller must echo back is.
- Report `insufficient_data` and `is_stale` as two independently-gated facts, not one merged
  "no answer" — and pick the analytic shape from measured coverage (Phase 11's latest-vs-earliest
  over a rolling average, because waist was 15/123 days and body fat 0/123).

### Key Lessons

1. **Deferring a structural fix has a compounding price.** The missing pre-deploy migration step
   was diagnosed correctly the first time and deferred three times; each recurrence cost a live
   production incident during verification of unrelated work.
2. **Spike the capability, don't assume the platform.** Two closed-"not planned" GitHub issues said
   scheduled MCP sessions never load tool schemas. Testing it directly — twice — was worth more
   than either believing or dismissing the reports.
3. **Discuss-phase reversals are the cheapest possible correction.** Two of six phases had their
   premise overturned before implementation. Both reversals came from checking what the user
   actually does against what the roadmap assumed.
4. **A process failure that recurs is a tooling problem, not a discipline problem.** Requirements
   drift and the broken `audit-open` both showed up at v1.0 close, were noted, and both recurred
   unchanged at v2.0 close.

### Cost Observations

- Model mix: not instrumented this milestone.
- Sessions: not instrumented.
- Notable: 34 plans in 4 days against 65 plans in 10 days for v1.0 — roughly 1.6× the plan rate,
  on a codebase that was already standing rather than being bootstrapped.

---

## Milestone: v2.1 — Longitudinal Physique Analysis

**Shipped:** 2026-09-15
**Phases:** 6 | **Plans:** 17 | **Tasks:** 46 | **Timeline:** 10 days (2026-09-05 → 2026-09-15)

### What Was Built

A longitudinal physique-observation record built on the same "photo never stored, only structure
persists" boundary decided at the milestone gate. `physique_observations`/`physique_ratings`
persist per-muscle-group ordinal ratings on the existing 19-value canonical taxonomy, confounder
metadata, and a supersede-with-reason correction path. BRETT's second MCP write path
(`fitness_log_physique_observation`, single-call/append-only/non-destructive) ships alongside its
required companion read tool. `analytics/physique.py` computes a deterministic ordinal diff and a
volume cross-reference with no model call and no new arithmetic. The monthly report gained a
physique section; the weekly report structurally cannot carry it. The milestone opened by closing
v2.0's carried-forward deploy-migration gap (Phase 14) and closed by proving that fix in production
against its own new migration (Phase 19, Cloud Run revision `brett-00012-n6r`). `backend/` grew to
~58.1k LOC and 1195 tests; MCP registry grew 20 → 22 tools.

### What Worked

- **Retiring the feature's central uncertainty with a measurement spike before locking the schema.**
  Phase 15 ran 5 blind ratings plus a 5-step anchored chain on one real, unchanged photo set,
  pre-registering the ratchet decision rule before any data existed. The result (BLIND-STABLE,
  RATCHET-NOT-OBSERVED) set `PHYSIQUE_DIFF_MIN_LEVEL_DELTA` and `PHYSIQUE_MIN_ELAPSED_DAYS` from
  measured behavior rather than a guess baked into the migration — the same pattern v1.0's Phase 2
  and v2.0's Phase 13 spikes established, now applied to a model-calibration question instead of an
  infrastructure one.
- **Fixing the recurring structural debt before building on top of it.** Phase 14 was sequenced
  first specifically because this milestone ships its own new migration into a pipeline that had
  already let production drift three times in v2.0. The fix was rehearsed against a real drifted
  Postgres container, not asserted only against fixtures.
- **Proving the fix, not just building it.** Phase 19 didn't stop at "the pre-flight exists and
  passes in CI" — it ran the real `scripts/deploy-cloud-run.sh` against production, unmodified,
  producing a real Cloud Run revision and a real live MCP call against the deployed schema. This
  closes a three-time recurring incident class with evidence rather than a fourth assertion.
- **Amending the read-only guard instead of relaxing it, a second time.** The same posture from
  v2.0's Phase 12 (`program_switch.py` as the first write path) was reapplied to `physique.py`
  as the second: `_WRITE_ALLOWLIST` became an exact two-member frozenset, and the annotation guard
  was restructured into a per-tool mapping rather than loosened to accommodate a non-destructive
  write coexisting with a destructive one.

### What Was Inefficient

- **REQUIREMENTS.md traceability drifted a third consecutive time.** PHYS-01 through PHYS-05 were
  unchecked and marked `Planned` at milestone close despite Phase 16's own `16-VERIFICATION.md`
  confirming all five satisfied; PHYS-12 was checked but still marked `Planned`. Reconciled to
  18/18 at close — identical failure mode to v1.0 (8 stale) and v2.0 (3 stale). Three milestones
  running the same per-phase workflow have now produced the same symptom each time.
- **`gsd-tools.cjs audit-open` is still broken.** Reported at v1.0 close, still unfixed at v2.1
  close — the automated pre-close artifact audit could not run a third time. The one item it did
  surface (`audit-open` still functioned enough to flag a missing quick-task SUMMARY.md) turned out
  to be a documentation gap, not incomplete work, but the tool itself remains unreliable.
- **No milestone audit was run, a third time.** `/gsd-audit-milestone` was skipped by explicit user
  choice at the pre-flight gate in all three milestone closes to date.

### Patterns Established

- Persist per-source-of-truth confounder metadata as fields independent of the measurement itself
  (`photo_angles_present`, `pose_state`, `conditions_note` separate from the rating rows) — "the
  rating changed" and "the conditions were comparable" stay two separately inspectable facts.
- A single-call, append-only, non-destructive write tool does not need the two-call confirmation-
  token ceremony that gates a genuinely destructive one — the ceremony exists for irreversibility,
  and an append-only row has nothing to be confirmed against.
- A supersede-with-reason correction path (retain the row, exclude from diffs, never hard-delete)
  is the correction mechanism for an appendable ledger, avoiding both a destructive delete tool and
  a widened write-guard membership.

### Key Lessons

1. **A 3-for-3 recurring process failure is a tooling gap, not a discipline gap.** REQUIREMENTS.md
   traceability has drifted at every milestone close so far, each time reconciled manually. The
   fix that would actually stop this — a phase-completion check comparing REQUIREMENTS.md
   checkboxes against the phase's own VERIFICATION.md — has been named as a lesson twice before
   and still not built.
2. **Proving a fix in production is worth more than asserting it in tests, especially for a
   recurring incident class.** Phase 14 could have stopped at "the pre-flight exists and the tests
   pass." Sequencing a dedicated Phase 19 to run the real deploy against production converted "the
   deploy-migration gap is closed" from a claim into an observed fact.
3. **A calibration spike belongs before the schema, not after.** Locking `PHYSIQUE_DIFF_MIN_LEVEL_DELTA`
   from Phase 15's measured noise floor (rather than shipping a guessed threshold in Phase 16's
   migration and hoping it held) meant zero schema rework was needed once the spike's results came
   in — the migration was written once, against a value already measured to be right.

### Cost Observations

- Model mix: not instrumented this milestone.
- Sessions: not instrumented.
- Notable: 17 plans in 10 days — the slowest per-day plan rate of the three milestones to date
  (v1.0: 6.5/day, v2.0: 8.5/day, v2.1: 1.7/day), consistent with this milestone containing a
  measurement spike (Phase 15) and a real-production deploy (Phase 19) rather than pure feature
  build-out — both phases trade plan count for verification depth.

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Sessions | Phases | Key Change |
|-----------|----------|--------|------------|
| v1.0 | — | 7 | Deploy target pivoted Render → Cloud Run mid-milestone (Phase 2); first milestone, no prior process to compare against |
| v2.0 | — | 6 | Discuss-phase reversals became load-bearing — 2 of 6 phases had their premise overturned before any code. Risk-spike-first pattern from v1.0 Phase 2 reused deliberately (Phase 13) |
| v2.1 | — | 6 | Risk-spike-first pattern applied to a model-calibration question (Phase 15) rather than infrastructure for the first time. First milestone to close by *proving* a prior fix in production (Phase 19) rather than shipping new features last |

### Cumulative Quality

| Milestone | Tests | Coverage | Zero-Dep Additions |
|-----------|-------|----------|--------------------|
| v1.0 | 687 | — | — |
| v2.0 | 925 | — | HAE package sealed dependency-free; reports add zero new arithmetic |
| v2.1 | 1195 | — | `analytics/physique.py` composed entirely from already-tested functions, zero new SQL |

### Top Lessons (Verified Across Milestones)

1. De-risk the highest-uncertainty architectural question in its own early phase, before building functionality on top of an unverified assumption (v1.0, Phase 2: MCP connector auth; **re-confirmed** v2.0, Phase 13: RPT-03 scheduled-task spike run before the report tools existed; **re-confirmed a third time** v2.1, Phase 15: rating-drift calibration spike before the observation schema locked).
2. A structural fix deferred is a fix paid for repeatedly. The missing pre-deploy migration step caused three live incidents in v2.0 alone, each during verification of unrelated work (v2.0, Phases 8/9/13) — **finally closed and proven in production** in v2.1 (Phase 14 built the fix, Phase 19 proved it against a real deploy).
3. Check the user's actual workflow before building to the roadmap's assumption — 2 of 6 v2.0 phases were rescoped in discuss-phase, before code (v2.0, Phases 10 and 11).
4. **A process failure that recurs three times running is a tooling problem, not a discipline problem.** REQUIREMENTS.md traceability has drifted and needed manual reconciliation at every milestone close so far — v1.0 (8 stale requirements), v2.0 (3 stale), v2.1 (6 stale: PHYS-01–05, PHYS-12). The same is true of `gsd-tools.cjs audit-open`, broken since it was first reported at v1.0 close. Both remain open going into the next milestone.
