<!-- GSD:project-start source:PROJECT.md -->
## Project

**BRETT**

A personal fitness data platform that normalizes Hevy workout data, Apple Health data, body-composition measurements, and nutrition data into PostgreSQL, calculates fitness analytics (volume, progression, plateaus, PRs, trends), and exposes it through a remote MCP server so Claude can act as a long-term, data-driven body recomposition coach. v1 is backend-first: Hevy sync, analytics, and a read-only remote MCP server. The native iOS HealthKit app (and full Apple Health integration) is deferred to a second milestone.

**Core Value:** Claude can retrieve real, normalized workout data through the MCP server and answer training questions ("Am I progressing?", "Which muscles are undertrained?") from actual data instead of guessing. This end-to-end path — Hevy → PostgreSQL → analytics → MCP → Claude — must work before anything else matters.

### Constraints

- **Tech stack**: Python 3.12+, FastAPI, PostgreSQL, SQLAlchemy 2.x, Alembic, Pydantic, httpx, MCP Python SDK, pytest, Ruff (mypy where practical) — specified in the blueprint, not open for re-litigation without cause
- **Repo layout**: Flat at the BRETT repo root (`backend/`, `ios/`, `docs/` as top-level dirs) — no extra `fitness-platform/` nesting, since this repo already is the project root
- **Security**: MCP tools read-only in v1; never expose API keys, DB credentials, or internal tokens through MCP responses or logs; HTTPS everywhere; secrets only via environment/secret storage, never committed
- **Data integrity**: Hevy sync must be idempotent and must never corrupt existing data on partial/failed sync
- **Provider isolation**: Hevy-specific logic confined to `backend/app/integrations/hevy/` so the API surface can change or a new provider can be added without spreading assumptions through the app
- **Deployment**: Google Cloud Run for v1 (revised 2026-08-27; see .planning/phases/02-deploy-connector-auth-spike/02-CONTEXT.md, D-06), but architecture should stay portable to another host later
<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->
## Technology Stack

## Critical Findings — read before the tables
### 1. The MCP Python SDK had a major rework — `FastMCP` no longer exists
| v1 (training-data era) | v2.0.0 (current) |
|---|---|
| `from mcp.server.fastmcp import FastMCP` | `from mcp.server import MCPServer` |
| Session-centric protocol, `Mcp-Session-Id`, `initialize` handshake | **Stateless** request/response; protocol-level sessions removed |
| Standalone `GET` SSE stream on the MCP endpoint | **GET stream removed** — single `POST` endpoint |
| Types bundled in `mcp` | Split into standalone `mcp-types` package |
| Decorator-based handler registration on low-level `Server` | Constructor params (`on_list_tools=`, `on_call_tool=`) |
| — | New `Resolve()` dependency-injection system for tool params |
| — | OpenTelemetry tracing built in |
| — | Requests must carry `MCP-Protocol-Version`, `Mcp-Method`, `Mcp-Name` headers |
### 2. Claude custom connectors do **not** accept a plain bearer token out of the box
| Type | Availability |
|---|---|
| `oauth_dcr` (OAuth 2.0 + RFC 7591 Dynamic Client Registration) | Supported out of the box |
| `oauth_cimd` (Client ID Metadata Document) | Supported out of the box |
| `oauth_anthropic_creds` | Requires emailing `mcp-review@anthropic.com` |
| `static_headers` (fixed API key / bearer token entered as a request header) | **Beta — "being slowly rolled out; contact Anthropic for early access"** |
| `none` (authless) | Supported |
- A GitHub issue asking for bearer-token support in the connector UI ([#112](https://github.com/anthropics/claude-ai-mcp/issues/112), Mar 2026) was **closed as "not planned"** — superseded by the `static_headers` beta.
- Tokens in the connector URL (`?token=…`) are explicitly **not recommended** and are **prohibited by the MCP authorization spec**.
- The official Python SDK is a **resource server only**. Its docs state plainly: the SDK "never issues tokens", and the legacy `auth_server_provider` parameter "exists for legacy use cases and should be avoided in new implementations."
- FastMCP's `OAuthProvider` (full self-hosted AS) carries a doc warning: *"This is an extremely advanced pattern that most users should avoid."*
### 3. `httpx` is effectively unmaintained; the successor is `httpx2` (and `mcp` already depends on it)
- `mcp==2.0.0` requires `httpx2>=2.5.0`.
- `starlette==1.6.0`'s `TestClient` imports `httpx2 as httpx`, falling back to `httpx` only if absent. **Verified by reading the installed source.**
- Consequence: a clean install of `mcp + fastapi + starlette` pulls **only `httpx2`**. Standardise on it and you carry one HTTP client, not two.
- **Gotcha:** `respx` and `pytest-httpx` are pinned to httpx 0.x and will **not** mock `httpx2`. Use `pytest-httpx2` (1.0.0) or `httpx2.MockTransport`.
## Recommended Stack
### Core Technologies
| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **Python** | **3.13.x** (pin via `.python-version`) | Runtime | Blueprint says 3.12+. 3.13 gives modern typing (`type` statement, better `TypedDict`) with the widest wheel coverage. Render's default is now 3.14.3 and I verified the *entire* stack installs and imports cleanly on 3.14 — but `mcp` has 3.14-conditional dependency pins (`starlette>=0.48` only on ≥3.14), which signals 3.14 is still the less-trodden path. Pin 3.13, revisit at milestone 2. Confidence: HIGH (compat), MEDIUM (the 3.13-vs-3.14 call) |
| **FastAPI** | **0.141.1** | HTTP API for sync triggers, health, future iOS endpoints | Blueprint choice, still correct. Pydantic v2 native, OpenAPI for free, and it's a Starlette app so the MCP ASGI app mounts directly into it |
| **Starlette** | **1.6.0** (transitive) | ASGI foundation | Note the **0.x → 1.x major jump**. FastAPI 0.141.1 declares `starlette>=0.46.0` with no upper bound; verified resolving to 1.6.0 alongside `mcp` 2.0.0 with no conflict |
| **MCP Python SDK** | **`mcp==2.0.0`** (+ transitive `mcp-types==2.0.0`) | Remote MCP server | Official Anthropic SDK, targets the current `2026-07-28` spec. `MCPServer.streamable_http_app()` returns a Starlette app you mount into FastAPI — one service, one deploy, one Render instance |
| **PostgreSQL** | Render Managed Postgres, latest major offered | Source of truth | Blueprint choice. Analytics here (weekly volume, per-muscle rollups, trend windows) is exactly what window functions + `date_trunc` + `generate_series` are for. No need for a separate analytics store |
| **SQLAlchemy** | **2.0.52** (`sqlalchemy[asyncio]`) | ORM + query builder | 2.0 typed `Mapped[]` / `DeclarativeBase` style is fully static-analysable — no mypy plugin needed. Async engine matches FastAPI + MCP's async handlers |
| **asyncpg** | **0.31.0** | Async Postgres driver | Fastest async driver; SQLAlchemy's reference asyncio dialect (`postgresql+asyncpg://`). cp313 **and** cp314 wheels published |
| **Alembic** | **1.19.1** | Migrations | Blueprint choice, the only real option for SQLAlchemy. Use `--autogenerate` but always hand-review |
| **Pydantic** | **2.13.4** | Validation, Hevy response schemas, MCP tool I/O schemas | Blueprint choice. In MCP v2, returning a `BaseModel` from a tool auto-generates the JSON output schema and populates `structured_content` — directly satisfies the blueprint's "return structured JSON" rule |
| **pydantic-settings** | **2.15.0** | Typed config from env / `.env` | Satisfies blueprint §45 (env-var config) with validation at boot, so a missing `HEVY_API_KEY` fails fast instead of at first sync |
| **httpx2** | **2.12.0** | Hevy API client | See Critical Finding #3. `AsyncClient`, HTTP/2, `MockTransport` for tests |
| **uvicorn** | **0.52.4** | ASGI server | Render's documented start command. Single worker is correct for v1 |
### Supporting Libraries
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **tenacity** | 9.1.4 | Retry with exponential backoff | **Not optional here.** Hevy's `/v1/workouts` caps `pageSize` at **10** (verified from their live OpenAPI doc), so an initial full sync is dozens-to-hundreds of sequential requests. You *will* hit transient failures and rate limits. Alternative: `stamina` 26.1.0 (thinner tenacity wrapper, nicer defaults) |
| **structlog** | 26.1.0 | Structured logging | Blueprint §44 wants sync-lifecycle logs with correlation IDs and an explicit deny-list (no API keys, no raw health samples). Structured key/value logging makes redaction a processor, not a discipline |
| **asgi-correlation-id** | 5.0.1 | Request/correlation IDs | Blueprint §44: "Include correlation/request IDs where useful" |
| **greenlet** | 3.5.5 | SQLAlchemy async bridge | Transitive via `sqlalchemy[asyncio]`. Listed only because it's the usual culprit in Python-version upgrade failures — cp313/cp314 wheels confirmed present |
| **orjson** | 3.12.0 | Fast JSON | Optional. Only if MCP payload serialisation shows up in profiling. Skip for v1 |
| `zoneinfo` | stdlib | `Asia/Jakarta` local-day grouping | Blueprint §40. Store UTC, convert with `ZoneInfo(user.timezone)` before `date_trunc`. No third-party tz library needed |
### Development Tools
| Tool | Purpose | Notes |
|------|---------|-------|
| **uv 0.12.5** | Dependency management + lockfile | **Replaces the blueprint's `requirements.txt`.** Render supports it natively: commit `uv.lock`, set `UV_VERSION`. Build: `uv sync --frozen`. Gives reproducible deploys, which `pip install -r requirements.txt` does not |
| **Ruff 0.16.4** | Lint + format | Blueprint choice. One tool replaces flake8 + isort + black. Enable `E,F,I,UP,B,ASYNC,S` (`S` = bandit rules — relevant for a health-data app) |
| **mypy 2.3.1** | Type checking | Blueprint says "mypy if practical" — it *is* practical: SQLAlchemy 2.0 `Mapped[]` and Pydantic v2 are both natively typed, no plugins. Note **mypy 2.x is a new major**; if it fights you, `--strict` on `app/analytics/` only. Do **not** use `sqlalchemy2-stubs` (it's for SQLAlchemy 1.4 and last shipped 2023) |
| **pytest 9.1.1** + **pytest-asyncio 1.4.0** + **pytest-cov 7.1.0** | Test runner | Blueprint choice. `asyncio_mode = "auto"` in config saves a decorator per test |
| **pytest-httpx2 1.0.0** | Mock the Hevy API | **Use this, not `respx`/`pytest-httpx`** — those pin `httpx==0.28.*` and cannot see `httpx2` requests |
| **testcontainers[postgres] 4.15.0** | Real Postgres in tests | Blueprint §42/§43 wants an end-to-end mock-Hevy → PostgreSQL → analytics → MCP test. SQLite will silently diverge on `date_trunc`, window functions, and timezone arithmetic — exactly the code you most need to trust |
| **time-machine 3.4.0** | Freeze time | Plateau detection ("3–6 weeks"), 7/14/30-day trends and "weeks=12" windows are all clock-dependent. Faster and more reliable than `freezegun` |
| **`mcp.client.Client`** | In-memory MCP tool tests | SDK v2 ships a unified `Client` that connects directly to an `MCPServer` object — tests tool discovery, schemas and structured output with no HTTP. **Caveat:** in-memory and stdio connections bypass auth entirely, so auth tests must go over HTTP |
| **pre-commit** | Hook runner | Ruff + mypy on commit. Also add a `detect-secrets`/`gitleaks` hook — blueprint §33 forbids committing `.env` |
## Installation
# Project init (uv, not pip/requirements.txt)
# Core
# Dev
## The FastAPI + MCP Integration Pattern
# app/main.py
# MUST be called at import time, before lifespan runs.
# `mcp.session_manager` raises RuntimeError until streamable_http_app() has been called
# ("The session manager is created lazily to avoid unnecessary initialization").
- Signature: `streamable_http_app(*, streamable_http_path="/mcp", json_response=False, stateless_http=False, event_store=None, retry_interval=None, max_request_body_size=4194304, transport_security=None, host="127.0.0.1") -> Starlette`
- **The app rejects all non-localhost requests with `421 Misdirected Request` by default.** You *must* pass `TransportSecuritySettings(allowed_hosts=[...])` or the Render deployment will fail with a confusing 421 and no MCP-level error. This is the single most likely Phase-5 blocker.
- `@mcp.custom_route("/health", methods=["GET"])` exists, but the docs warn: *"Custom routes are never authenticated, even when the rest of the server is."* Put your health endpoint on the FastAPI side instead.
- CORS is **not** needed here — Claude's connectors call from Anthropic's servers (egress `160.79.104.0/21`), not from a browser.
- Tools reach the database via the server lifespan: `MCPServer("BRETT", lifespan=app_lifespan)` yields an `AppContext`, read inside a tool as `ctx.request_context.lifespan_context.db`. This is exactly the blueprint §37 requirement ("MCP should call internal service functions rather than making HTTP requests back into the same application") — no HTTP round-trip.
- SDK v2 also has an `Annotated[T, Resolve(fn)]` DI system; resolved params are hidden from the model's tool schema. Useful for injecting "current user" without exposing it as a tool argument.
## Authentication Decision Path
# app/mcp/server.py
| Stage | Client | Mechanism | Effort |
|---|---|---|---|
| Phase 4 — local verify | Claude Code | `claude mcp add brett --transport http --header "Authorization: Bearer $TOKEN" https://…/mcp` | Zero extra infra |
| Phase 5 — Desktop/Web/Mobile, **preferred** | Claude connector | `static_headers` beta. Enter `Bearer <token>` (include the scheme and space — Claude sends the value verbatim). Header names are allowlisted; `authorization` is on the list. Max 4 headers | Email Anthropic for beta access |
| Phase 5 — **fallback** | Claude connector | Managed IdP with DCR. Set `AuthSettings.issuer_url` to its issuer; keep `TokenVerifier` as a JWKS/introspection check | ~half a day of IdP setup |
| Never | — | Token in the URL query string; hand-rolled OAuth AS; authless server | — |
## Deployment (Render)

> **SUPERSEDED 2026-08-27.** The deploy target is Google Cloud Run, not Render. The rows below
> stay accurate about Render and about the host-independent constraints (one service serving both
> `/api` and `/mcp`; cold start versus Claude's 10-second discovery budget; migrations run
> out-of-band rather than at app startup), but every Render-specific mechanism is replaced by
> `scripts/deploy-cloud-run.sh` and the "RESEARCH ADDENDUM 2026-08-27: Cloud Run Deployment
> Pivot" section of `.planning/phases/02-deploy-connector-auth-spike/02-RESEARCH.md`.

| Concern | Recommendation | Confidence |
|---|---|---|
| Service shape | **One Web Service** serving both `/api/v1/*` and `/mcp`. Blueprint §45 allows this ("They may initially run in one application/service if that simplifies deployment") and it halves cost and removes cross-service DB config | HIGH |
| Runtime | Native Python runtime, not Docker, for v1. Fewer moving parts; keep the blueprint's `Dockerfile` as the portability escape hatch | MEDIUM |
| Python pin | `.python-version` file containing `3.13`. Render's precedence is `PYTHON_VERSION` env var → `.python-version` → default (currently `3.14.3` for services created after 2026-02-11) | HIGH |
| Package manager | uv — set `UV_VERSION`, commit `uv.lock`. Build `uv sync --frozen`, start `uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT` | MEDIUM |
| IaC | `render.yaml` blueprint at repo root, so the web service + Postgres + cron job are versioned | MEDIUM |
| **Instance tier** | **Do not use the free web-service tier for the MCP endpoint.** Free services spin down after 15 min idle and cold-start in 30–60s for Python. Claude's OAuth/discovery calls have a **10-second** timeout (30s for refresh) — a cold start will look like "Couldn't reach the MCP server." Budget for Starter | HIGH (the 10s limit is from Anthropic's docs) |
| Database tier | Render's **free Postgres is deleted after 30 days**. This is real fitness history — pay for it from day one | MEDIUM |
| Migrations | Run `alembic upgrade head` in a Render **pre-deploy command**, not at app startup — startup migrations race across restarts | MEDIUM |
| Hevy sync scheduling | **Render Cron Job** (separate service running `uv run python -m app.cli sync-hevy`), **not** in-process APScheduler. Blueprint §38 wants every 1–6h; an in-process scheduler dies with a spun-down or restarted web dyno and gives you no run history | MEDIUM |
| Networking | Anthropic egress is `160.79.104.0/21` if you ever add IP allowlisting. Must be publicly reachable over HTTPS — blueprint §2.1 is correct | HIGH |
| SSE buffering | Largely moot under the 2026-07-28 stateless transport, but the spec says servers **SHOULD** send `X-Accel-Buffering: no` on SSE responses. The SDK handles this; don't add a buffering proxy in front | HIGH |
## Alternatives Considered
| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| `mcp` 2.0.0 (official SDK) | **FastMCP 3.4.7** (`jlowin/fastmcp`, standalone) | If the `static_headers` beta is refused **and** you want batteries-included auth. FastMCP ships `JWTVerifier`, `RemoteAuthProvider`, `OAuthProxy` (presents a DCR facade over non-DCR providers like GitHub/Google) and `MultiAuth` — materially less work than wiring an IdP by hand. Costs: a fast-moving third-party dep in the critical path of your health data, and it's a different API from the official SDK. The blueprint explicitly says "MCP Python SDK", so stay official unless auth forces your hand |
| `httpx2` | `httpx` 0.28.1 | Only if a hard dependency pins httpx 0.x. Note you'd then ship *both* clients, since `mcp` requires `httpx2` regardless |
| `pytest-httpx2` | `httpx2.MockTransport` | Hand-rolled `MockTransport` is fine (and dependency-free) if you only need a handful of canned Hevy responses; the plugin wins once you're asserting on request sequences across pagination |
| `asyncpg` | `psycopg` 3.3.4 (`postgresql+psycopg://`) | psycopg3 supports both sync and async on one driver and has friendlier `COPY`/type-adaptation. Pick it if you find yourself wanting sync sessions for Alembic/CLI without a second driver. asyncpg is faster and is SQLAlchemy's reference async dialect |
| Render Cron Job | APScheduler 3.11.3 in-process | Acceptable only on an always-on paid instance where you'd rather not manage a second Render service. You lose independent run history and retry |
| SQLAlchemy Core/ORM | SQLModel 0.0.39 | Merges Pydantic + SQLAlchemy models. Tempting, but still `0.0.x` after years, and it blurs the DB-model/API-schema boundary that this project explicitly wants separate (`db/models/` vs `integrations/hevy/schemas.py` vs `mcp/schemas.py`) |
| mypy 2.3.1 | `ty` 0.0.74 / `pyrefly` 1.2.0 | Astral's `ty` and Meta's `pyrefly` are dramatically faster. `ty` is still `0.0.x` — revisit at milestone 2, don't bet Phase 1 on it |
| Custom rate-limit middleware | `slowapi` 0.1.10 | With one user and one connector, a ~20-line in-process token bucket keyed on client IP is sufficient and adds no dependency. Reach for `slowapi`/`limits` only if the API opens to the iOS app in milestone 2 — and verify its Starlette 1.x compatibility first |
## What NOT to Use
| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `from mcp.server.fastmcp import FastMCP` | Removed in SDK v2. Every pre-2026 tutorial, blog post and LLM completion uses this import | `from mcp.server import MCPServer` |
| `mcp` v1.x (`1.29.0`) | Maintenance mode — security fixes only. Speaks the pre-`2026-07-28` session-based transport | `mcp==2.0.0` |
| The deprecated HTTP+SSE transport (`2024-11-05`) — dual `/sse` + `/messages` endpoints | Deprecated since `2025-03-26`, "eligible for removal in a future revision". Claude's connector docs list Streamable HTTP | Single `POST /mcp` Streamable HTTP endpoint |
| `respx`, `pytest-httpx` | Both pin `httpx>=0.25`/`httpx==0.28.*`. They will not intercept `httpx2` calls — your Hevy tests will silently hit the real API or hang | `pytest-httpx2`, or `httpx2.MockTransport` |
| Bearer token in the connector URL (`/mcp?token=…`) | Anthropic: "not recommended… a credential in a URL is a security vulnerability". The MCP authorization spec **prohibits** access tokens in the URI query string. Blueprint §32 already says don't rely on an obscure URL | `Authorization` request header (`static_headers`) or OAuth |
| Hand-rolled OAuth authorization server | Official SDK: `auth_server_provider` "should be avoided in new implementations." FastMCP: "extremely advanced pattern that most users should avoid." WorkOS reports several 2025 MCP CVEs traced to custom OAuth proxy implementations. This is health data | `static_headers` beta, or a managed IdP with DCR |
| SQLite for tests | `date_trunc`, `generate_series`, window frames and `AT TIME ZONE` behave differently or not at all. Your entire analytics layer (blueprint §16–26) depends on them | `testcontainers[postgres]` |
| pandas / numpy for v1 analytics | Blueprint rule #10: "Make analytics deterministic and testable." Pushing weekly volume and per-muscle rollups into SQL + plain Python keeps them trivially unit-testable against known workouts. A dataframe layer adds ~50 MB, cold-start time, and float-comparison flakiness for no gain at this data volume | SQL aggregates + `dataclasses`/Pydantic models |
| `requirements.txt` (as written in blueprint §4) | No lockfile → non-reproducible Render builds → "works locally, breaks in prod" | `pyproject.toml` + `uv.lock` |
| `sqlalchemy2-stubs` | Despite the name, it's stubs for SQLAlchemy **1.4**; last release Dec 2023 | Nothing — SQLAlchemy 2.0 is natively typed |
| `python-jose` | Effectively unmaintained (last release May 2025), historical CVEs | `pyjwt[crypto]` 2.13.0 — already in the tree via `mcp` |
| Two separate Render services (`fitness-api` + `fitness-mcp`) | Doubles cost and forces the MCP layer to talk to analytics over HTTP, which blueprint §37 explicitly forbids | One service, MCP mounted at `/mcp` |
## Stack Patterns by Variant
- Keep `StaticTokenVerifier` + `AuthSettings`; generate the secret with `secrets.token_urlsafe(48)`
- Blueprint's auth plan ships unchanged; Phase 5 stays a one-day phase
- Add an IdP (WorkOS or Keycloak) before Phase 5 — treat it as its own phase, not a Phase-5 subtask
- Swap `StaticTokenVerifier` → a JWKS-validating `TokenVerifier`; `AuthSettings.issuer_url` → the IdP issuer. Tool code, analytics and DB are untouched
- Or switch the MCP layer to FastMCP 3's `RemoteAuthProvider` — accept the framework swap as the price of skipping OAuth plumbing
- Static bearer via `--header` works today with zero extra infra. Ship Phases 1–4, defer the whole connector-auth question. **Worth considering as a de-risking move** — it gets the Hevy → Postgres → analytics → MCP → Claude loop (the stated Core Value) proven before any OAuth work
- The stack is host-agnostic (uv + uvicorn + Postgres). Fly.io, Railway, and a $6 VPS with Docker Compose all take it unchanged. Blueprint's portability constraint is satisfied by construction
## Version Compatibility
| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| `fastapi 0.141.1` | `starlette 1.6.0` | FastAPI declares `starlette>=0.46.0`, **no upper bound**. Resolves to 1.6.0. Verified installed and importable together — but note 1.x is a fresh major, so watch FastAPI's changelog if anything odd surfaces |
| `mcp 2.0.0` | `starlette>=0.27` (py<3.14) / `starlette>=0.48.0` (py≥3.14) | The version-conditional pin is your signal that 3.14 is newer ground for this SDK |
| `mcp 2.0.0` | `pydantic>=2.12.0`, `httpx2>=2.5.0`, `pyjwt[crypto]>=2.10.1`, `sse-starlette>=3.0.0`, `mcp-types==2.0.0` (exact), `opentelemetry-api>=1.28.0` | `mcp-types` is pinned exactly — expect lockstep upgrades. Requires Python `>=3.10` |
| `starlette 1.6.0` TestClient | `httpx2` preferred, `httpx` fallback | Source reads `import httpx2 as httpx`, falling back. Install only `httpx2` |
| `sqlalchemy 2.0.52` | `asyncpg 0.31.0`, `greenlet 3.5.5` | cp310–cp314 wheels for all three. Use `postgresql+asyncpg://` |
| `pydantic 2.13.4` | `pydantic-core 2.46.4` | pydantic-core has cp314 **and cp315** wheels; not the constraint |
| `respx 0.23.1` / `pytest-httpx 0.36.2` | `httpx 0.x` **only** | **Incompatible with httpx2.** The trap to avoid |
| Render default runtime | Python 3.14.3 | Pin explicitly; don't inherit the default |
## Sources
- `/websites/py_sdk_modelcontextprotocol_io_v2` (Context7 via ctx7 CLI) — ASGI mounting, authorization, lifespan, dependency injection, structured output, v1→v2 migration — **HIGH**
- https://py.sdk.modelcontextprotocol.io/v2/run/asgi — mounting, `TransportSecuritySettings`, `streamable_http_path`, lifespan requirement, `custom_route` warning — **HIGH**
- https://py.sdk.modelcontextprotocol.io/v2/run/authorization — resource-server-only design, `TokenVerifier`, `AuthSettings`, RFC 9728 metadata, `auth_server_provider` deprecation — **HIGH**
- https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http — stateless transport, GET-stream removal, required headers, `X-Accel-Buffering`, HTTP+SSE deprecation — **HIGH**
- https://claude.com/docs/connectors/building/authentication — supported auth types table, `static_headers` beta, no-tokens-in-URL, 10s/30s endpoint timeouts, `160.79.104.0/21` egress — **HIGH**
- https://claude.com/docs/connectors/custom/remote-mcp — request-header auth UX, allowlisted header names, "enter the full header value including `Bearer `" — **HIGH**
- https://github.com/anthropics/claude-ai-mcp/issues/112 — bearer-token UI request closed as "not planned" (Mar 2026) — **MEDIUM**
- PyPI JSON API (`pypi.org/pypi/<pkg>/json`), queried 2026-08-23 — all version numbers, release dates, `requires_dist`, wheel platform tags — **HIGH**
- Live install into a clean venv (`mcp 2.0.0 + fastapi 0.141.1 + sqlalchemy 2.0.52 + asyncpg 0.31.0 + alembic 1.19.1 + pydantic-settings 2.15.0`) + `inspect.signature` / source reads of `mcp/server/mcpserver/server.py` and `starlette/testclient.py` — **HIGH** (this is the strongest evidence in this document)
- https://api.hevyapp.com/docs/ live OpenAPI 3.0.0 doc (`swagger-ui-init.js`, parsed) — endpoint list, `api-key` **header** auth, `page`/`pageSize` (default 5, **max 10**), `since` cursor on `/v1/workouts/events` — **HIGH**
- https://render.com/docs/python-version — 3.14.3 default, `.python-version`/`PYTHON_VERSION` precedence, `UV_VERSION` + `uv.lock` support — **HIGH**
- https://render.com/docs/deploy-fastapi + community guides — start command, `render.yaml`, free-tier spin-down (15 min idle, 30–60s cold start), free Postgres 30-day deletion — **MEDIUM** (spin-down/deletion figures from third-party guides)
- https://gofastmcp.com/servers/auth/authentication and `/full-oauth-server` — FastMCP 3 auth classes; "extremely advanced pattern most users should avoid" warning on self-hosted OAuth AS — **MEDIUM**
- https://workos.com/blog/best-mcp-server-authentication-providers — IdP comparison (DCR/CIMD support). Vendor-authored, treat as a shortlist not a verdict — **LOW/MEDIUM**
### Open questions for the roadmap
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, or `.github/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
