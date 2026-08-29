# BRETT

## What This Is

A personal fitness data platform that normalizes Hevy workout data, Apple Health data, body-composition measurements, and nutrition data into PostgreSQL, calculates fitness analytics (volume, progression, plateaus, PRs, trends), and exposes it through a remote MCP server so Claude can act as a long-term, data-driven body recomposition coach. v1 is backend-first: Hevy sync, analytics, and a read-only remote MCP server. The native iOS HealthKit app (and full Apple Health integration) is deferred to a second milestone.

## Core Value

Claude can retrieve real, normalized workout data through the MCP server and answer training questions ("Am I progressing?", "Which muscles are undertrained?") from actual data instead of guessing. This end-to-end path — Hevy → PostgreSQL → analytics → MCP → Claude — must work before anything else matters.

## Requirements

### Validated

- [x] Backend foundation: FastAPI app, PostgreSQL, Alembic migrations, users table (single-user now, schema not hard-coded to preclude multi-user), config, health endpoint — Validated in Phase 1: Backend Foundation (2026-08-23)
- [x] Deployed to Google Cloud Run over HTTPS, connected as a Claude custom remote MCP connector (Desktop/Web/Mobile) — Validated in Phase 2: Deploy & Connector Auth Spike (2026-08-29); verified end-to-end via Claude Desktop against the live `/mcp` endpoint

### Active

- [ ] Hevy client isolated in `integrations/hevy/`, built against current official Hevy API docs (not invented endpoints)
- [ ] Hevy sync service: initial full sync with pagination, incremental sync via workout events, idempotent (unique on user_id+provider+external_id), handles deletions/errors/rate limits without corrupting data
- [ ] Hevy data model: workouts, workout_exercises, sets — enough fidelity to reconstruct workouts and drive analytics
- [ ] Exercise normalization layer mapping exercise names to canonical muscle groups (primary/secondary), manually overridable
- [ ] Body measurements: manual entry model (weight minimum viable; body fat %, waist, chest, arm, thigh optional)
- [ ] Nutrition: manual entry model (calories, protein, carbs, fat) — no scraping/auto-import in v1
- [ ] Analytics layer (deterministic, testable, lives outside MCP handlers): weekly training volume, per-muscle-group volume with direct/indirect weighting, exercise progression, progressive-overload/plateau detection, personal record detection, training frequency, weight trend (7/14/30-day averages), recomposition status classification (explicitly framed as decision-support, not medical/diagnostic)
- [ ] Remote MCP server exposing purpose-built, read-only tools (fitness_get_recent_workouts, fitness_get_training_summary, fitness_get_weekly_volume, fitness_get_muscle_group_volume, fitness_get_exercise_progression, fitness_get_personal_records, fitness_get_plateaus, fitness_get_training_frequency, fitness_get_body_weight_trend, fitness_compare_periods, etc.) returning compact structured JSON
- [ ] MCP authentication via strong bearer token (env secret) + HTTPS + rate limiting; no secrets ever returned in tool responses
- [ ] Data freshness surfaced per source (last_synced_at) so Claude knows when data may be stale
- [ ] Claude fitness-coach system prompt/instructions document (separate doc) defining the body-recomposition coaching behavior and decision framework
- [ ] Test coverage: Hevy sync (auth, pagination, incremental events, duplicates, deletions, failures), analytics calculations against known workouts, MCP tool schemas/auth/structured output, end-to-end mock-Hevy-to-MCP integration test

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
*Last updated: 2026-08-29 — Phase 2: Deploy & Connector Auth Spike complete*
