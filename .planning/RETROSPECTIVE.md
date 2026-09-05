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

## Cross-Milestone Trends

### Process Evolution

| Milestone | Sessions | Phases | Key Change |
|-----------|----------|--------|------------|
| v1.0 | — | 7 | Deploy target pivoted Render → Cloud Run mid-milestone (Phase 2); first milestone, no prior process to compare against |
| v2.0 | — | 6 | Discuss-phase reversals became load-bearing — 2 of 6 phases had their premise overturned before any code. Risk-spike-first pattern from v1.0 Phase 2 reused deliberately (Phase 13) |

### Cumulative Quality

| Milestone | Tests | Coverage | Zero-Dep Additions |
|-----------|-------|----------|--------------------|
| v1.0 | 687 | — | — |
| v2.0 | 925 | — | HAE package sealed dependency-free; reports add zero new arithmetic |

### Top Lessons (Verified Across Milestones)

1. De-risk the highest-uncertainty architectural question in its own early phase, before building functionality on top of an unverified assumption (v1.0, Phase 2: MCP connector auth; **re-confirmed** v2.0, Phase 13: RPT-03 scheduled-task spike run before the report tools existed).
2. A structural fix deferred is a fix paid for repeatedly. The missing pre-deploy migration step caused three live incidents in v2.0 alone, each during verification of unrelated work (v2.0, Phases 8/9/13).
3. Check the user's actual workflow before building to the roadmap's assumption — 2 of 6 v2.0 phases were rescoped in discuss-phase, before code (v2.0, Phases 10 and 11).
