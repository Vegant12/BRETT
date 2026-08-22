# Project Research Summary

**Project:** BRETT — personal fitness analytics backend + remote MCP coaching layer
**Domain:** External-API sync (Hevy) → normalized PostgreSQL → deterministic analytics → read-only remote MCP server consumed by Claude
**Researched:** 2026-08-23
**Confidence:** HIGH

## Executive Summary

BRETT is a solo-developer, single-user backend that syncs Hevy workout data into PostgreSQL, computes deterministic fitness analytics (volume, progression, plateaus, PRs, recomposition status), and exposes them to Claude through a remote MCP server. All four researchers converge on the same architecture: one FastAPI ASGI application per Render Web Service, with the MCP server mounted as a Starlette sub-app at `/mcp`, backed by a strict layering discipline — `integrations/hevy/` (anti-corruption boundary) → `db/repositories/` → `analytics/` (pure functions, zero I/O) → `services/` (the only layer both adapters call) → `api/routes/` and `mcp/tools/` (thin translators). This is the standard shape for "external API → normalized store → analytics → LLM surface" systems, and the blueprint's existing rules (analytics outside MCP handlers, MCP calls internal functions not HTTP, provider isolation) are validated as correct, not aspirational.

The recommended approach is table-stakes-first: sync workouts/sets/exercise templates, classify hard sets, build the canonical muscle mapping (with a delt-head split Hevy's own taxonomy cannot provide), compute weekly and per-muscle volume with fractional (direct/indirect) counting, then layer progression, plateau, PR, and recomposition analytics on top — culminating in one high-leverage composed tool, `fitness_get_training_summary`. Every analytic must carry uncertainty, freshness, and methodology metadata; the data layer's job is to hand Claude verdicts with evidence, never raw rows for it to sum. Feature research independently confirms the blueprint's table-stakes list matches what Hevy Pro, Strong, Boostcamp, and RP Hypertrophy all converge on — the actual differentiator is not more analytics but returning a *verdict* ("improving/stable/declining", "plateaued") instead of a chart, which none of the four competitor products do.

The single largest risk, identified independently and with high confidence by all four researchers, is that **PROJECT.md's "MCP auth = bearer token" Key Decision is not directly implementable through Claude's custom-connector UI** — that UI only exposes OAuth Client ID/Secret; the `static_headers` beta is org-admin-shaped and a GitHub feature request for bearer support was closed as "not planned." A second cluster of risk comes from the Hevy API itself diverging from the blueprint's assumed schema (pageSize max 10, no `rir` field, no stable child-object IDs, newest-to-oldest event ordering, an existing `/v1/body_measurements` endpoint) and from the MCP Python SDK's very recent (26-day-old) breaking rework from `FastMCP` to `MCPServer` under a new stateless spec revision. All three are mitigated the same way: resolve them early and cheaply, before deep work is built on top of unverified assumptions — specifically via a small deploy+connector spike inserted right after Phase 1, and by treating the real (not assumed) Hevy schema as ground truth from Phase 2 onward.

## Key Findings

### Recommended Stack

The blueprint's stack (Python/FastAPI/PostgreSQL/SQLAlchemy/Alembic/Pydantic/MCP SDK/pytest/Ruff) holds up, with three corrections verified by live install and primary sources: pin `mcp==2.0.0` (not the v1/`FastMCP` shape most tutorials and training data assume), standardize on `httpx2` (Pydantic's maintained successor to `httpx`, and already a transitive dependency of `mcp` 2.x — mixing in `httpx` adds a redundant, incompatible-with-test-tooling second client), and use `uv` + `pyproject.toml`/`uv.lock` instead of `requirements.txt` for reproducible Render deploys.

**Core technologies:**
- Python 3.13 (pin via `.python-version`) — widest wheel coverage; Render's 3.14 default is less-trodden ground for `mcp` 2.x
- FastAPI 0.141.1 + Starlette 1.6.0 — HTTP layer; a Starlette app, so MCP mounts directly into it
- `mcp==2.0.0` (official SDK) — targets the current 2026-07-28 stateless spec; `MCPServer.streamable_http_app()` returns a Starlette sub-app
- PostgreSQL (Render **paid** managed instance) — source of truth; window functions/`date_trunc` cover all analytics needs, no separate analytics store
- SQLAlchemy 2.0.52 (`Mapped[]`/`DeclarativeBase`) + asyncpg 0.31.0 (or sync SQLAlchemy — see Architecture) + Alembic 1.19.1
- Pydantic 2.13.4 + pydantic-settings 2.15.0 — validation and typed config; MCP v2 auto-derives `output_schema` from a returned `BaseModel`
- httpx2 2.12.0 — Hevy API client; tenacity 9.1.4 for retry/backoff (not optional — Hevy pageSize caps at 10)
- uv, Ruff, mypy, pytest+pytest-asyncio, `pytest-httpx2` (not `respx`/`pytest-httpx` — incompatible with httpx2), `testcontainers[postgres]` (SQLite will silently diverge on `date_trunc`/window functions/timezone arithmetic)

### Expected Features

**Must have (table stakes, v1):**
- Hevy workout/set/exercise-template sync with hard-set classification (`normal`+`failure` count, `warmup` excluded)
- Exercise normalization with a canonical muscle map and delt-head split (front/side/rear) — Hevy's single `shoulders` bucket cannot answer the flagship "side delts" question on its own
- Fractional set counting (direct 1.0 / indirect 0.5, configurable, evidence-backed per Pelland et al. 2025)
- Local-timezone (Asia/Jakarta, configurable) week bucketing
- Weekly volume, per-muscle volume (direct/indirect), exercise progression with modality-gated e1RM, PR detection, progressive-overload classification, plateau detection, training frequency
- Body-weight trend and recomposition status — **now automatable in v1** via Hevy's `GET /v1/body_measurements` (no HealthKit dependency required, contrary to PROJECT.md's current assumption)
- Period comparison (normalized per-week), data freshness/coverage envelope on every response, `fitness_get_training_summary` composed tool
- Read-only MCP tools, `readOnlyHint: true`, bearer/OAuth auth, rate limiting

**Should have (differentiators, v1.x — add after v1 validated):**
- Volume landmark bands (MEV/MAV/MRV, user-configurable, honestly labeled as heuristics)
- Muscle balance ratios (push:pull, quad:hamstring, delt-head share)
- RPE-derived stimulus-quality metrics with explicit `rpe_coverage_pct`
- Exercise substitution/equivalence grouping (prevents false plateaus from variant swaps)
- "What to progress next" ranked candidates, routine adherence, session density trends

**Defer (Milestone 2 — HealthKit/nutrition):**
- Activity/recovery/sleep analytics, Apple Health workouts, nutrition auto-import, composite readiness scores, full multi-input recomposition analytics

**Anti-features (explicitly avoid):** gamification, push notifications, social/sharing, write/mutation MCP tools, generic "run a query" tools, backend-generated coaching prose, composite readiness scores without sleep/HRV data, ACWR/training-monotony metrics, live Hevy fetch on MCP request, charts/images from MCP, and a tool-per-question explosion (target 6–13 well-parameterized tools, not 40+).

### Architecture Approach

One deployable service: a FastAPI app with the MCP server mounted as an ASGI sub-app at `/mcp`, sharing one Render Web Service, one Postgres instance, one connection pool, and one settings/logging setup. The two adapters (`api/routes/` and `mcp/tools/`) are both thin ~5-line translators over a shared `services/` layer, which is the only thing that touches both `db/repositories/` (I/O) and `analytics/` (pure, deterministic, zero-I/O functions). MCP 2.0's removal of protocol-level sessions makes this stateless-HTTP topology safe to run as a single instance with no sticky-session concerns.

**Major components:**
1. `integrations/hevy/` (client, schemas, mapper, sync) — hard anti-corruption boundary; nothing outside imports Hevy's payload shapes directly
2. `db/repositories/` + `analytics/` — the only place SQL lives, and pure computation with zero DB/clock/HTTP access respectively
3. `services/` — composes repository reads + analytics into response DTOs; the single source of truth both adapters call
4. `mcp/tools/` and `api/routes/` — thin, schema-only translators; if a tool handler is >8 lines, logic has leaked
5. `domain/` — provider-agnostic vocabulary (canonical muscle taxonomy finer than Hevy's, `SetType`/`ProgressionStatus` enums, volume-weighting config)

### Critical Pitfalls

1. **MCP auth around a bearer token Claude's connector UI cannot send** — decide the auth strategy in the Phase-1.5 spike (recommended: minimal OAuth 2.1 resource-server shim using the SDK's `TokenVerifier`/`AuthSettings`, or accept desktop/Claude-Code-only for longer if that's acceptable).
2. **Idempotency assumed at the workout level is insufficient** — Hevy's child objects (exercises, sets) have no stable IDs; sync must delete-and-reinsert children inside one transaction per workout, keyed on `(user_id, provider, external_id)` at the parent only.
3. **Sync built on an assumed page size** — Hevy caps `pageSize` at 10 (not 50–100); scheduled syncs must use the events endpoint only, never a scheduled full re-sync.
4. **Cursor advanced against a newest-first, paginated events feed** — drain all pages before applying anything, apply oldest-first, commit the cursor once (set to `run_start_time`, not the newest event seen), with an overlap window.
5. **Volume math (`SUM(weight_kg * reps)`) ignoring set type and the 8 exercise types** — warmups inflate every number, bodyweight exercises silently evaluate to zero/NULL, and 5 of 8 Hevy exercise types don't fit weight×reps at all. Compute `hard_sets` (works for all types) as the primary metric and gate `tonnage_kg` to applicable types.

## Implications for Roadmap

Based on combined research, suggested phase structure:

### Phase 1: Backend Foundation
**Rationale:** Everything downstream depends on config, DB, and the timezone helper being correct from the start; timezone bugs written once and copy-pasted are the hardest class of bug to catch later (PITFALLS #16).
**Delivers:** FastAPI app skeleton, PostgreSQL (paid tier — free Postgres expires in 30 days), Alembic migrations, users table with configurable timezone, structured logging with a secret-redaction filter, `/healthz`, `core/time.py` local-day/week helper.
**Addresses:** Local-tz week bucketing (table stakes), data-integrity constraints.
**Avoids:** Pitfall 16 (timezone/week-boundary bugs), Pitfall 18 (expiring free Postgres), Pitfall 17 (log leakage — set up redaction now, not retrofitted).

### Phase 1.5: Deploy + Connector Auth Spike (NEW — inserted per unanimous researcher recommendation)
**Rationale:** The single highest-uncertainty item in the entire project is whether a personal Claude account can authenticate to a custom remote MCP connector with a bearer token. `static_headers` is beta and org-admin-shaped; the GitHub request for bearer support in the connector UI was closed "not planned." Finding this out now costs ~2 hours; finding it out in a "Phase 5" deployment push invalidates a Key Decision after everything else is built.
**Delivers:** A throwaway "hello world" MCP tool, deployed to Render, mounted correctly (lifespan wired, `TransportSecuritySettings.allowed_hosts` set), first verified via Claude Code's `--header` bearer support (de-risking the Hevy→Postgres→analytics→MCP loop against the real transport before touching connector auth), then attempted as an actual Claude Desktop/Web/Mobile custom connector add. Resolves whether `static_headers` beta access is obtainable, or whether a minimal OAuth 2.1 resource-server shim (SDK's `TokenVerifier` + `AuthSettings`) must be built.
**Addresses:** PROJECT.md's "MCP auth = bearer token, not OAuth" Key Decision — validates or explicitly invalidates it before Phase 4/5 are built around the assumption.
**Avoids:** Pitfall 1 (auth mechanism unusable from the connector), Pitfall 10 (MCP SDK v1→v2 breaking rework — surfaces immediately if you build against stale training data), Pitfall 11 (mounted-lifespan and transport-security defaults that fail silently in production).

### Phase 2: Hevy Integration
**Rationale:** The whole system is downstream of sync; exercise-template sync and the canonical muscle map are hard prerequisites for Phase 3's analytics, not a nice-to-have — moved up from the blueprint's implied Phase 3 placement per architecture research.
**Delivers:** `integrations/hevy/` client (auth via `api-key` header, not `Authorization: Bearer`; pagination at the real max of 10; retry/backoff), Pydantic schemas matching the *live* Hevy OpenAPI spec (no `rir`, no `weight_unit`, no stable child IDs), mapper, idempotent cursor-based incremental sync with soft deletes, `exercise_templates` sync feeding a `muscle_map_overrides` table (delt-head split), and — reconsidering PROJECT.md's manual-entry-only assumption — Hevy `body_measurements` sync as a low-cost addition that unlocks automatic weight trend and recomposition status in v1.
**Uses:** httpx2, tenacity, the real Hevy schema (see Research Flags below).
**Implements:** the anti-corruption-layer pattern; cursor + event-replay idempotent sync pattern.
**Avoids:** Pitfalls 2–9 (idempotency, page-size assumptions, cursor ordering, hard-delete data loss, schema mismatches, name-based exercise matching, two sources of truth for body weight).

### Phase 3: Analytics
**Rationale:** Pure, deterministic functions over rows the sync layer has already normalized; cannot start until Phase 2's effective muscle map exists.
**Delivers:** `analytics/` modules — volume (hard-set-based, not naive `SUM(weight*reps)`), muscle_volume (direct/indirect split), progression (modality- and rep-range-gated e1RM), plateau, prs, frequency, trends, recomposition — each independently unit-tested against golden fixtures covering all 8 Hevy exercise types, warmups, dropsets, and supersets.
**Addresses:** Progressive-overload classification, plateau detection, PR detection, recomposition status (the project's namesake synthesis — built last, degrades cleanly to `insufficient_data`).
**Avoids:** Pitfall 8 (volume math ignoring set/exercise type) — the single most consequential correctness bug in the project.

### Phase 4: MCP Tools
**Rationale:** Composition over `services/`, not new computation; can be built and tested in-memory via the SDK's `Client` once analytics exist.
**Delivers:** 6–13 purpose-built, read-only, budgeted MCP tools (not the blueprint's full 15 at once), each carrying a shared `DataFreshness` envelope, uncertainty fields, and hard response-size caps; `fitness_get_training_summary` as the highest-leverage composed tool.
**Uses:** MCP SDK v2's structured-output derivation from Pydantic return types; `ToolAnnotations(read_only_hint=True)`.
**Implements:** the dual-adapter-over-shared-service-core pattern; typed/budgeted MCP responses pattern.
**Avoids:** Pitfall 13 (unbounded/raw-data tool responses blowing the context window), Pitfall 14 (silent staleness — freshness must be unconditional, not an opt-in tool), Pitfall 15 (never trigger sync from a tool call).

### Phase 5: Production Hardening
**Rationale:** By this point Phase 1.5 has already resolved the auth question, so this phase is "make deployment production-grade," not "make deployment work" — a much better risk profile than the blueprint's original ordering.
**Delivers:** Finalized auth (OAuth shim or `static_headers`, per the Phase 1.5 finding), `TransportSecuritySettings.allowed_hosts` for the real Render hostname, rate limiting applied before auth, verified backup/restore drill, secret-rotation rehearsal, cold-start verification from a phone on cellular, alerting on consecutive sync failures.
**Addresses:** Deployment requirement, security constraints (§32/§33).
**Avoids:** Pitfall 12 (cold starts + proxy buffering breaking the connector experience), Pitfall 17 (data minimization/text neutralization), Pitfall 18 (unbacked-up source of truth).

### Phase Ordering Rationale

- The Phase 1.5 spike exists because auth is the one unknown that can invalidate a stated Key Decision after the rest of the project is built — resolving it in week 1 costs a day; discovering it in a final deployment push costs a rewrite of the auth layer under time pressure.
- Exercise-template sync and the muscle-map override table move from an implied Phase 3 concern to a Phase 2 deliverable because per-muscle analytics (the flagship "undertrained muscles" question) structurally cannot start without them.
- Hevy body-measurement sync is reconsidered from "manual entry only" to "sync it in Phase 2" because it is nearly free given the client already exists, and it unlocks weight-trend/recomposition-status features in v1 without waiting for HealthKit.
- Analytics (Phase 3) must follow Hevy integration (Phase 2) completely, including the effective muscle map, because per-muscle volume, progression, and plateau detection all depend on it.
- MCP tools (Phase 4) are composition, not computation, and should be built last among the "real work" phases so `fitness_get_training_summary` can depend on everything else already existing.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 1.5 (spike):** direct — this phase's entire purpose is resolving an open question (`static_headers` beta availability for a personal account) that only Anthropic can answer definitively; treat the spike itself as the research.
- **Phase 2 (Hevy integration):** the real Hevy schema differs materially from the blueprint's assumed schema (see below) — use `.planning/research/PITFALLS.md` Pitfalls 2–9 and `ARCHITECTURE.md`'s data-flow section as primary references rather than re-deriving from the blueprint.
- **Phase 4 (MCP tools):** the MCP Python SDK had a breaking rework 26 days before this research (`FastMCP`→`MCPServer`, spec revision 2026-07-28); re-read the SDK docs at phase start rather than trusting any cached mental model, including this summary's.

Phases with standard patterns (skip deep research-phase):
- **Phase 1 (backend foundation):** well-documented FastAPI/SQLAlchemy/Alembic patterns; no domain-specific unknowns.
- **Phase 3 (analytics):** the math and thresholds are documented in FEATURES.md and PITFALLS.md with peer-reviewed backing (Pelland et al. 2025); implementation is standard Python/SQL, no new research needed once the definitions are fixed in `docs/analytics-definitions.md`.
- **Phase 5 (hardening):** the specific gotchas (transport security, cold starts, backups) are already fully enumerated in PITFALLS.md with concrete remediations.

**Explicit note for Phase 2 and Phase 3 planning:** build against the real Hevy schema, not the blueprint's assumed one. Concretely: no `rir` field exists (derive `rir ≈ 10 − rpe` or treat as unavailable); no `weight_unit` field exists (Hevy always returns `weight_kg`); `pageSize` maxes at 10 for workouts/events/body_measurements (100 for exercise_templates); `/v1/exercise_templates` already provides `primary_muscle_group`/`secondary_muscle_groups` — do not hand-build a name-matching table; `/v1/body_measurements` exists and can supply v1 weight-trend/recomposition data without HealthKit; the events endpoint returns results newest-to-oldest and is the only source of deletion signals, requiring careful drain-then-apply-oldest-first handling to avoid permanent, silent data loss.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Core versions verified by a live clean-venv install with zero dependency conflicts; MCP SDK behavior verified against installed source, not memory. Render-specific pricing/spin-down figures are MEDIUM (third-party guides, not Render's own pricing page). |
| Features | HIGH for Hevy API surface (live OpenAPI spec parsed same day) and volume methodology (peer-reviewed meta-regression); MEDIUM for competitor feature comparisons (vendor pages/review sites) and MCP token-economics figures (industry write-ups, not a formal spec). |
| Architecture | HIGH for MCP SDK mounting/lifespan/auth and the Hevy API contract (verified against primary sources); MEDIUM for the sync-vs-async SQLAlchemy recommendation and in-process-scheduler-vs-cron call (defensible engineering judgment, not documented consensus). |
| Pitfalls | HIGH for Hevy API surface and MCP transport/auth (live spec + official docs + a closed Anthropic GitHub issue as direct evidence); MEDIUM for analytics-semantics conventions and Render operational specifics; a few items explicitly flagged LOW and marked "verify during execution" (e.g., whether Hevy stores dumbbell weight per-dumbbell or combined; actual undocumented rate limits). |

**Overall confidence:** HIGH — all four researchers independently reached the same conclusions on the two load-bearing risks (MCP connector auth, real vs. assumed Hevy schema), each corroborated against live primary sources (Hevy's own OpenAPI spec, Anthropic's connector docs, a closed GitHub issue, and a clean SDK install) rather than training-data assumptions.

### Gaps to Address

- **Is `static_headers` beta access obtainable for an individual Pro/Max account?** The single highest-leverage open question in the project. Anthropic's docs frame it in organization-admin terms. Resolve directly in the Phase 1.5 spike by requesting access and/or attempting a connector add; if refused, plan a minimal OAuth 2.1 resource-server shim (~1 day of work, SDK provides the primitives) rather than defaulting to desktop-only.
- **Hevy's real-world rate limits are undocumented.** Must be discovered empirically during the first full sync in Phase 2 and recorded in `integrations/hevy/README.md`; design the client with conservative concurrency (1–2) and full backoff/jitter from day one rather than tuning after a 429 storm.
- **Whether Hevy stores dumbbell exercise weight per-dumbbell or combined.** Unverified; affects tonnage calculations for a common exercise category. Verify against the user's own Hevy account in Phase 2 and record the finding before analytics ship.
- **Which MCP protocol revision Claude's connector infrastructure currently negotiates.** The SDK handles multi-era backward compatibility, but empirically confirming this during the Phase 1.5 spike (log the received `MCP-Protocol-Version` header) closes the loop rather than assuming.
- **mypy 2.x against SQLAlchemy 2.0.52's `Mapped[]` typing** — a very recent mypy major version; if friction appears, scope `--strict` to `app/analytics/` only rather than fighting it project-wide.

## Sources

### Primary (HIGH confidence)
- Live OpenAPI spec, `https://api.hevyapp.com/docs/` (parsed 2026-08-23) — endpoint list, pagination limits, all schema shapes, `MuscleGroup`/exercise-type enums, event ordering semantics
- Live clean-venv install and `inspect.signature`/source reads of `mcp/server/mcpserver/server.py`, `starlette/testclient.py` — FastAPI+MCP integration pattern, dependency resolution
- MCP specification 2026-07-28 (Streamable HTTP transport) — https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http
- MCP Python SDK docs — https://py.sdk.modelcontextprotocol.io/v2/run/asgi, /v2/run/authorization
- Claude connector docs — https://claude.com/docs/connectors/building/authentication, /connectors/custom/remote-mcp
- anthropics/claude-ai-mcp issue #112 (closed "not planned") — https://github.com/anthropics/claude-ai-mcp/issues/112
- PyPI JSON API for all package versions, queried 2026-08-23
- Render docs — https://render.com/docs/python-version, /docs/free
- Pelland et al. 2025, *Sports Medicine*, DOI 10.1007/s40279-025-02344-w — fractional set-counting evidence base

### Secondary (MEDIUM confidence)
- Render pricing/spin-down figures — third-party 2026 guides, not Render's own pricing page
- Competitor analytics feature sets — Hevy/Strong/Boostcamp/RP vendor pages and review sites
- WorkOS blog, gofastmcp.com docs — IdP/OAuth alternative comparisons
- MCP tool-design token economics — pydantic.dev, kansei-link.com, mindstudio.ai engineering write-ups

### Tertiary (LOW confidence)
- Whether Hevy stores dumbbell weight per-dumbbell vs. combined — flagged explicitly for empirical verification in Phase 2
- Hevy's actual (undocumented) rate limits — flagged for empirical discovery during first full sync

---
*Research completed: 2026-08-23*
*Ready for roadmap: yes*
