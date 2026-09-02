# Milestones

## v1.0 MVP (Shipped: 2026-09-02)

**Phases completed:** 7 phases, 65 plans, 151 tasks
**Timeline:** 2026-08-23 → 2026-09-01 (10 days)
**Git range:** `b6a78a2` (initialize project) → `750ff56` (evolve PROJECT.md after Phase 7) — 345 files changed, +111,596/-21 lines, ~33.9k LOC in `backend/`

**Delivered:** The full Hevy → PostgreSQL → analytics → MCP → Claude loop is live in production. A real Claude Project, pointed at the deployed Cloud Run MCP server, answers "Am I progressing?" and "Which muscles are undertrained?" from real synced training data — the project's Core Value, observed working end-to-end for the first time.

**Key accomplishments:**

- **Foundation (Phase 1):** FastAPI + PostgreSQL + Alembic scaffold with UTC-storage enforcement, Asia/Jakarta-configurable timezone bucketing, and a three-layer structlog pipeline that provably strips secrets from every log channel.
- **Deploy & auth spike (Phase 2):** Resolved the project's single highest-uncertainty question first — a real Claude Desktop client authenticates to the Cloud Run-hosted MCP server via WorkOS AuthKit (OAuth 2.1), overturning the original "bearer token, not OAuth" assumption with evidence rather than argument.
- **Hevy integration (Phase 3):** Idempotent full + incremental sync (correct oldest-first event application, no duplicate/corrupted data on failure), a 19-value canonical muscle taxonomy with front/side/rear deltoid split, and an auditable manual-override layer — all isolated inside `backend/app/integrations/hevy/` and validated against the real Hevy API (463 exercise templates curated, unmapped count driven 77 → 44).
- **Analytics layer (Phases 4-5):** Deterministic, SQL-first volume/frequency, progression trend classification, plateau detection, personal records, period comparison, body-weight trend, and a recomposition verdict — every response carrying a freshness/coverage uncertainty envelope (DQ-01/DQ-02) so sparse data is never reported as confident.
- **MCP tool surface (Phase 6):** Thirteen purpose-built, read-only, byte-budgeted MCP tools composing the analytics layer directly (no HTTP round-trip), with zero secret leakage proven by a full-registry redaction test and a live check that the DB session structurally cannot write.
- **Production hardening (Phase 7):** Live token-bucket rate limiting (proven against a real 429 flood), a real Neon PITR backup/restore drill (byte-identical across all 9 tables), a real `MCP_AUTH_SECRET` rotation with zero connector disruption, 6-hourly production Hevy sync (327 workouts/463 templates/125 body measurements), 687 green tests, and the coaching-instructions document that turned the data layer into an actual working coach.

**Known gaps at close:**
- No formal `/gsd-audit-milestone` was run before this close (skipped by explicit user choice — see pre-flight gate). Substituted with a targeted spot-check of 8 requirements whose REQUIREMENTS.md checkboxes/traceability rows were stale (HEVY-01/02/05/06/07/08/09, NORM-02) — all 8 confirmed implemented directly against code before archiving.
- `gsd-tools.cjs audit-open` (and `--json`) is broken in this GSD install (`ReferenceError: output is not defined` — a bare `output()` call at gsd-tools.cjs:784/786 that should be `core.output()`). The pre-close automated artifact audit could not run as a result. This is a tooling bug in the global `~/.claude/get-shit-done/` install, not a BRETT project issue.
- REQUIREMENTS.md's traceability table and checkboxes had drifted out of sync with actual progress since 2026-08-30 (only updated through Phase 4); reconciled to reflect all 39/39 v1 requirements complete as part of this milestone close.
- Three PROJECT.md "Active" items remain genuinely open scope questions rather than incomplete v1 work: body-measurement manual entry, nutrition manual entry, and freshness surfacing — each flagged in PROJECT.md as likely already satisfied or redundant, pending a scope decision at the v1.1 boundary.

---
