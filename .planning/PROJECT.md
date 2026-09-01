# BRETT

## What This Is

A personal fitness data platform that normalizes Hevy workout data, Apple Health data, body-composition measurements, and nutrition data into PostgreSQL, calculates fitness analytics (volume, progression, plateaus, PRs, trends), and exposes it through a remote MCP server so Claude can act as a long-term, data-driven body recomposition coach. v1 is backend-first: Hevy sync, analytics, and a read-only remote MCP server. The native iOS HealthKit app (and full Apple Health integration) is deferred to a second milestone.

## Core Value

Claude can retrieve real, normalized workout data through the MCP server and answer training questions ("Am I progressing?", "Which muscles are undertrained?") from actual data instead of guessing. This end-to-end path — Hevy → PostgreSQL → analytics → MCP → Claude — must work before anything else matters.

## Requirements

### Validated

- [x] Backend foundation: FastAPI app, PostgreSQL, Alembic migrations, users table (single-user now, schema not hard-coded to preclude multi-user), config, health endpoint — Validated in Phase 1: Backend Foundation (2026-08-23)
- [x] Deployed to Google Cloud Run over HTTPS, connected as a Claude custom remote MCP connector (Desktop/Web/Mobile) — Validated in Phase 2: Deploy & Connector Auth Spike (2026-08-29); verified end-to-end via Claude Desktop against the live `/mcp` endpoint
- [x] Hevy client isolated in `integrations/hevy/`, built against current official Hevy API docs; Hevy sync service (initial full sync with pagination, incremental sync via workout events, idempotent, handles deletions/errors/rate limits without corrupting data); Hevy data model (workouts, workout_exercises, sets); exercise normalization layer mapping exercise names to canonical muscle groups (primary/secondary), manually overridable — Validated in Phase 3: Hevy Integration & Normalization
- [x] Analytics layer (deterministic, testable, lives outside MCP handlers), volume/frequency slice: weekly training volume (hard sets, reps, modality-aware tonnage), per-muscle-group volume with direct/indirect weighting and query-time override support, training frequency (overall + per muscle group), plus the freshness/coverage metadata envelope (DQ-01, DQ-02) every analytics response carries — Validated in Phase 4: Volume & Frequency Analytics (2026-08-30)
- [x] Analytics layer, progression/records/recomposition slice: exercise progression time series with gated estimated-1RM, trend classification (improving/stable/declining/unclear), plateau detection reporting its window and threshold, personal record detection (max weight, max reps at a weight, estimated-1RM, session volume) excluding warm-up sets, per-week-normalized two-period comparison, body weight trend (7/14/30-day rolling averages + smoothed weekly rate of change), and a recomposition status verdict framed as decision-support — Validated in Phase 5: Progression, Records & Recomposition Analytics (2026-08-31)
- [x] Remote MCP server exposing purpose-built, read-only tools (fitness_get_recent_workouts, fitness_get_workout, fitness_get_training_summary, fitness_get_weekly_volume, fitness_get_muscle_group_volume, fitness_get_exercise_progression, fitness_get_plateaus, fitness_get_personal_records, fitness_get_training_frequency, fitness_get_body_weight_trend, fitness_compare_periods, fitness_get_recomposition_status) returning compact, budgeted structured JSON, with no secrets ever returned in a tool response — Validated in Phase 6: MCP Tools (2026-08-31)
- [x] Rate limiting on the MCP endpoint, registered ahead of routing and auth (token-bucket, 30/min with 30 burst, `/health` and discovery exempt) — Validated in Phase 7: Production Hardening & Coaching Layer (2026-09-01); proven live in production (89 of 120 concurrent requests correctly 429'd, zero leaked detail)
- [x] Claude fitness-coach system prompt/instructions document (`docs/coaching-instructions.md`) defining the body-recomposition coaching behavior and decision framework, drift-guarded against the live tool registry — Validated in Phase 7: Production Hardening & Coaching Layer (2026-09-01); a real Claude Project answered "Am I progressing?" and "Which muscles are undertrained?" from real synced data and correctly surfaced a freshness/sparsity signal unprompted when asked a question that could trigger it
- [x] Test coverage: Hevy sync (auth, pagination, incremental events, duplicates, deletions, failures), analytics calculations against known workouts, MCP tool schemas/auth/structured output, end-to-end mock-Hevy-to-MCP integration test — Validated in Phase 7: Production Hardening & Coaching Layer (2026-09-01); 687 tests green
- [x] Production-grade deployment: full backup/restore drill against real Neon PITR branching (byte-identical digests across all 9 tables), a real `MCP_AUTH_SECRET` rotation with old-token-rejected/new-token-accepted and a working post-rotation connector round-trip, and live production Hevy sync scheduling (6-hourly Cloud Run Job + Scheduler, first real sync of 327 workouts/463 templates/125 body measurements) — Validated in Phase 7: Production Hardening & Coaching Layer (2026-09-01)

### Active

- [ ] Body measurements: manual entry model (weight minimum viable; body fat %, waist, chest, arm, thigh optional) — not part of Phase 7's scope; not represented in REQUIREMENTS.md's v1 list, and Hevy sync already populates `body_measurements` automatically (125 measurements as of Phase 7), so this may be redundant rather than outstanding — worth a scope decision at the next milestone boundary rather than silently carrying it forward
- [ ] Nutrition: manual entry model (calories, protein, carbs, fat) — no scraping/auto-import in v1 — not part of Phase 7's scope; REQUIREMENTS.md lists only an automatic nutrition provider (NUTR-01) under v2, with no v1 nutrition requirement, so this item's status is ambiguous against the authoritative requirements list and should be resolved (validated, built, or formally moved to Out of Scope) at the next milestone boundary
- [ ] Data freshness surfaced per source (last_synced_at) so Claude knows when data may be stale — likely already satisfied by the Phase 4 freshness/coverage metadata envelope (DQ-01/DQ-02) and Phase 7's live `freshness.resources` evidence in the coaching UAT, but left here rather than silently removed since this document's evolution rules call for that check at a phase/milestone transition, not a mid-edit assumption

### Out of Scope

- iOS HealthKit app and all Apple Health data sync (steps, sleep, HRV, resting HR, Apple Health workouts, activity) — deferred to milestone 2; requires an Apple Developer account, which isn't set up yet
- Self-hosted / hand-rolled OAuth authorization servers — WorkOS AuthKit *is* the authorization server; BRETT is only a resource server that validates its tokens. *(This replaces the original scope note, which deferred OAuth for MCP auth on the grounds that a bearer token was sufficient for private v1 development. That note was overturned in Phase 2: a Claude custom connector cannot authenticate with a static bearer at all, so OAuth 2.1 was implemented rather than deferred — see the "MCP connector auth" row in Key Decisions. What stays out of scope is building the authorization server ourselves.)*
- Automatic/scraped nutrition data integration — manual entry only for v1; schema designed so a provider can be added later
- Write/delete MCP tools (modifying or deleting Hevy workouts, health data, nutrition, or measurements) — explicitly excluded; MCP is read-only in v1 to minimize security risk
- Multi-user product features (accounts for other people, per-user auth flows beyond schema readiness) — schema must not preclude multi-user later, but no multi-user UX is built now

## Context

- Source spec: [`BRETT blueprint.md`](../BRETT%20blueprint.md) in this repo — a detailed architecture/requirements document the user authored. Treat it as the authoritative reference for schema shapes, endpoint lists, MCP tool names, and phase ordering; this PROJECT.md scopes v1 to blueprint Phases 1–5 (backend foundation → Hevy → analytics → MCP → remote deployment).
- Hevy Pro subscription and API key are already available — no blocker to starting Hevy integration work.
- Google Cloud account, gcloud SDK 578.0.0 and an open billing account are already set up; the BRETT-specific GCP project and the Neon Postgres project are created during Phase 2. The previously-provisioned Render account is unused.
- User has an iPhone but no Apple Developer account yet — relevant when milestone 2 (HealthKit) is scoped; HealthKit does not work in the iOS Simulator, so real-device testing will be needed then.
- Default user timezone is Asia/Jakarta (must be configurable, not hard-coded); daily fitness calculations should group by local day, with timestamps stored in UTC.
- Internal units: kilograms, meters, kcal, seconds, centimeters — convert at the application boundary only.
- This is a self-paced personal project with no external deadline.

## Constraints

- **Tech stack**: Python 3.12+, FastAPI, PostgreSQL, SQLAlchemy 2.x, Alembic, Pydantic, httpx, MCP Python SDK, pytest, Ruff (mypy where practical) — specified in the blueprint, not open for re-litigation without cause
- **Repo layout**: Flat at the BRETT repo root (`backend/`, `ios/`, `docs/` as top-level dirs) — no extra `fitness-platform/` nesting, since this repo already is the project root
- **Security**: MCP tools read-only in v1; never expose API keys, DB credentials, or internal tokens through MCP responses or logs; HTTPS everywhere; secrets only via environment/secret storage, never committed
- **Data integrity**: Hevy sync must be idempotent and must never corrupt existing data on partial/failed sync
- **Provider isolation**: Hevy-specific logic confined to `backend/app/integrations/hevy/` so the API surface can change or a new provider can be added without spreading assumptions through the app
- **Deployment**: Google Cloud Run for v1 (supersedes Render as of 2026-08-27, revised D-06), with external managed Postgres (Neon) and Google Secret Manager; architecture stays portable to another host later

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| v1 = backend-first (blueprint Phases 1-5), iOS/HealthKit pushed to milestone 2 | No Apple Developer account yet; backend+Hevy+MCP alone already delivers real Claude coaching value | — Pending |
| ~~MCP auth = bearer token for v1, not OAuth~~ | Matches blueprint's private-development guidance; simpler to ship, revisit for broader production use | **Superseded 2026-08-29 by the row below.** Overturned, not confirmed: a Claude custom connector cannot authenticate with a static bearer at all. The assumption was never that bearer auth was insecure — it was that the *client* would accept it, and it does not |
| MCP connector auth = OAuth 2.1 via WorkOS AuthKit (managed IdP), with BRETT as a resource server only | Verified end-to-end on 2026-08-29, not chosen on paper. Claude Desktop completed the AuthKit consent flow and called `fitness_ping` successfully at the first attempt. **Claude identified itself via CIMD** (Anthropic's hosted client metadata document), which the tenant's discovery document predicted by advertising `client_id_metadata_document_supported: true` together with `"none"` in `token_endpoint_auth_methods_supported`; **DCR remains enabled and is the untested fallback**. The MCP SDK never issues tokens — it validates WorkOS-issued RS256 JWTs against the tenant JWKS and enforces `iss`/`aud`/`exp`, with `aud` pinned to the Resource Indicator to prevent cross-server token replay | **Decided 2026-08-29.** Evidence: `.planning/phases/02-deploy-connector-auth-spike/02-DEPLOY-LOG.md`. The static bearer is **not** retired: it remains the Claude Code CLI path (D-01, proven in plan 02-05) and the rollback for a WorkOS outage — `MCP_AUTH_MODE=static` in `deploy/cloud-run.env.yaml` plus a redeploy, a one-value config change and never a code change |
| Repo layout = flat at BRETT repo root, no `fitness-platform/` nesting | Project already lives at the root of this repo | — Pending |
| ~~Deploy target = Render~~ | Account already provisioned; blueprint recommends it; architecture stays portable | — Superseded 2026-08-27 by the row below |
| Deploy target = Google Cloud Run + Neon Postgres + Google Secret Manager | The original Cloud Run rejection (cost parity with a paid always-on tier, plus Cloud SQL provisioning surface) was re-presented on 2026-08-27 and the user chose to switch anyway. Neon replaces Cloud SQL, so the service needs only outbound egress and zero code change — `Settings.async_database_url` already translates the libpq DSN | — Pending Phase 2 |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-09-01 — Phase 7: Production Hardening & Coaching Layer complete (final phase of v1 milestone)*
