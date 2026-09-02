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

## Cross-Milestone Trends

### Process Evolution

| Milestone | Sessions | Phases | Key Change |
|-----------|----------|--------|------------|
| v1.0 | — | 7 | Deploy target pivoted Render → Cloud Run mid-milestone (Phase 2); first milestone, no prior process to compare against |

### Cumulative Quality

| Milestone | Tests | Coverage | Zero-Dep Additions |
|-----------|-------|----------|--------------------|
| v1.0 | 687 | — | — |

### Top Lessons (Verified Across Milestones)

1. De-risk the highest-uncertainty architectural question in its own early phase, before building functionality on top of an unverified assumption (v1.0, Phase 2: MCP connector auth).
