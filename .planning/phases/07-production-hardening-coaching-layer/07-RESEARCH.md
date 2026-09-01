# Phase 7: Production Hardening & Coaching Layer - Research

**Researched:** 2026-09-01
**Domain:** Test-suite composition, ASGI rate limiting, Neon backup/restore, Google Secret Manager rotation, LLM coaching-instruction design
**Confidence:** HIGH for everything verified against this repo and the installed SDK; MEDIUM for Neon/Cloud Run mechanics (official docs, not yet exercised against this project); LOW for how Claude's connector UI behaves on 429 and on server-supplied `instructions`

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Backup & Restore**
- **D-01:** Rely on **Neon Postgres's built-in point-in-time recovery (PITR) and branching** as
  the backup/restore mechanism. No independent `pg_dump`/`pg_restore` script is built this
  phase — Neon-native is sufficient for this project's scale and self-paced, single-user,
  cost-conscious posture. (User explicitly chose Neon-only over "also build a scripted
  pg_dump/pg_restore path" and over "both".)
- **D-02:** ROADMAP success criterion #3 ("a database backup restores into a fresh instance with
  no data loss") is proven via a **one-time manual verification during phase execution**, not an
  automated/CI test: create a Neon branch from a recent point in time, compare row
  counts/checksums against production, and document the exact steps and result in a runbook doc.
  This mirrors how Phase 2's connector-auth verification matrix worked (manual checklist, not
  CI) — Neon branching needs real Neon API/CLI access against the live project, which isn't
  something to script into the automated test suite this phase also has to build.

**Secret Rotation**
- **D-03:** Only **`MCP_AUTH_SECRET`** (the static bearer token compared in `StaticTokenVerifier`)
  gets a documented/tested rotation procedure this phase. `DATABASE_URL` and `HEVY_API_KEY` were
  explicitly considered and **not** selected — `HEVY_API_KEY` isn't in the live connector's
  request path at all (sync-job only), and `DATABASE_URL` rotation wasn't chosen as in-scope
  despite being offered as an option.
- **D-04:** Rotation procedure, matching how secrets are actually wired
  (`--set-secrets=...:latest` in `scripts/deploy-cloud-run.sh`, which only takes effect on
  redeploy): add a new version to the existing `brett-mcp-auth-secret` Secret Manager secret,
  run the deploy script (picks up `:latest`), then verify against the **live** `/mcp` endpoint —
  one request with the **old** token (expect 401) and one with the **new** token (expect
  success). No new code — this exercises `StaticTokenVerifier` exactly as already built. No
  dual-secret/grace-period mechanism (was offered, not chosen) — a rotation is a hard cutover,
  which is acceptable because the static path is CLI/rollback-only, not the primary live
  connector auth.

**Coaching Instructions Document (COACH-01)**
- **D-05:** Follow blueprint §34-36 closely: the "Personal Body Recomposition Coach" persona,
  the 5 core objectives, the 7-step decision framework, and the example-question list, all
  reproduced/adapted from the blueprint (CLAUDE.md names the blueprint authoritative for phase
  content).
- **D-06:** Additionally include an **explicit mapping from question types to actual MCP tool
  names** — e.g. "for progression questions, call `fitness_get_exercise_progression`; for 'am I
  progressing overall', call `fitness_get_training_summary`" — using the real 12 tool names built
  in Phase 6, not generic guidance. Makes the document immediately actionable instead of relying
  on Claude to infer tool choice from schemas alone.
- **D-07:** File location: **`docs/coaching-instructions.md`**, alongside the existing
  `docs/hevy-api-observations.md`.
- **D-08:** Loading mechanism the document is written for: pasted into a **Claude.ai/Desktop
  Project's custom instructions**, once, in a Project that also has the BRETT MCP connector
  attached — so every conversation in that Project automatically has both the coach persona and
  live data access, rather than being re-pasted per conversation.
- **D-09:** ROADMAP success criterion #4 is proven via a **manual UAT checkpoint during phase
  execution**: set up (or reuse) a Claude Project with the connector attached and the document
  loaded as custom instructions, ask both example questions from the criterion ("Am I
  progressing?", "Which muscles are undertrained?") plus one question expected to surface
  stale/sparse data, and record the transcript/result in a verification doc. This is
  human-in-the-loop by nature — it is not something a subagent can script, same category as the
  Phase 2 connector-auth checkpoint.

### Claude's Discretion
- Exact runbook doc name/location for the backup-restore verification steps (D-02) and the
  secret-rotation steps (D-04) — no existing convention to match beyond "documented, like Phase
  2's verification matrix"
- Exact wording/structure of the coaching document beyond the blueprint outline (D-05) and the
  tool-name mapping (D-06) — e.g. how much narrative vs. bulleted framework
- Where the UAT transcript/result gets recorded (D-09) — e.g. a `07-COACH-VERIFICATION.md` or
  similar, Claude's discretion on naming, consistent with other phase verification artifacts

### Areas Explicitly Not Discussed (left to research/planning discretion)
- **Rate limiting** — mechanism, keying (IP vs. authenticated identity), limit numbers, and 429
  response shape are all open. CLAUDE.md's "Alternatives Considered" table recommends an
  in-process token-bucket keyed on client IP as sufficient at this project's scale, reaching for
  `slowapi`/`limits` only if the API opens to the iOS app later — a reasonable default absent
  further user input, but not a locked decision.
- **Test coverage gap** — how deep the new mock-Hevy-to-MCP end-to-end integration test (ROADMAP
  criterion #1, blueprint §43) needs to go, and whether any other coverage gaps count against
  DEPLOY-03, beyond the 47 test files that already cover Hevy sync, analytics, and MCP tools
  individually. `backend/tests/test_hevy_end_to_end.py` currently stops at Postgres — it does not
  exercise analytics or MCP.

### Deferred Ideas (OUT OF SCOPE)
- Independent `pg_dump`/`pg_restore` backup path — considered and explicitly not chosen (D-01);
  Neon-native only for now. Revisit only if there's ever a reason to distrust Neon-internal
  recovery or to plan a migration off Neon.
- `DATABASE_URL` and `HEVY_API_KEY` rotation procedures — considered and not selected into this
  phase's scope (D-03). Not lost, just not built now; `HEVY_API_KEY` in particular has no urgency
  since it's off the live connector's request path entirely.
- Dual-secret/grace-period rotation mechanism for `MCP_AUTH_SECRET` — considered and not chosen
  (D-04); a hard-cutover rotation was judged acceptable given the static path is CLI/rollback-only.
- Per-conversation (non-Project) loading of the coaching document — considered and not chosen
  (D-08); Project-level custom instructions was preferred.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| **DEPLOY-03** | System includes automated tests covering Hevy sync (auth, pagination, incremental events, duplicate prevention, deletions, failures), analytics calculations against known workouts, and MCP tool schemas/auth/output structure | § *Blueprint §42 Coverage Audit* proves 6 of 7 Hevy items and all 6 MCP items already have named tests `[VERIFIED: test-name inventory]`. The real deliverable is § *Pattern 2: The full-chain composition test* (blueprint §43) plus two small named gaps. § *Validation Architecture* maps every criterion to a runnable command. |
| **COACH-01** | A separate system-prompt/instructions document defines the body-recomposition coaching behavior and decision framework for Claude to follow when using the MCP tools | § *Pattern 5: The coaching instructions document* gives the exact section skeleton, the verified 13-tool signature table for D-06's mapping, the exact freshness/coverage field names Claude must be told to read, and the D-09 UAT script. |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

Directives extracted from `./CLAUDE.md` that bind this phase's plan:

| Directive | Source | How this phase must comply |
|---|---|---|
| Tech stack is fixed (Python 3.13, FastAPI 0.141.1, `mcp==2.0.0` with `MCPServer`, SQLAlchemy 2.0.52 async, asyncpg, `httpx2` **not** `httpx`, pytest 9.1.1) | §Constraints, §Recommended Stack | This phase adds **zero** runtime dependencies. See § *Standard Stack*. |
| **Do not use** `respx` / `pytest-httpx` — they pin httpx 0.x and cannot intercept `httpx2` | §What NOT to Use | Use `pytest-httpx2` (already a dev dep). Note the transitive nuance in § *Pitfall 6*. |
| **Do not use** SQLite for tests — `date_trunc`, window frames and `AT TIME ZONE` diverge | §What NOT to Use | The composition test uses `testcontainers[postgres]`, like every other integration test. |
| Custom rate-limit middleware preferred over `slowapi`/`limits` at this scale | §Alternatives Considered | Recommendation honoured: a ~40-line pure-ASGI limiter, no new dependency. Keying differs from CLAUDE.md's suggestion — see § *Pitfall 3* for the evidence. |
| Never expose API keys, DB credentials or internal tokens through MCP responses or logs | §Constraints, blueprint §44 | The 429 body must be key-set-asserted like the existing 401 (`test_401_leaks_nothing`). |
| Secrets only via environment/secret storage, never committed | §Constraints | The rotation runbook must contain **no** secret value; commands only. |
| MCP tools read-only in v1 | §Constraints | Nothing this phase adds may open a writable session. |
| Ruff lint set `E,F,I,UP,B,ASYNC,S` + `DTZ`; mypy `disallow_untyped_defs` | `pyproject.toml` | New middleware and test modules must be fully annotated and pass `S` (bandit). |
| Deployment: Google Cloud Run, portable architecture | §Constraints (superseded Render note) | All deploy work goes through `scripts/deploy-cloud-run.sh`, which `test_cloud_run_deploy.py` asserts against. |

## Summary

Phase 7 is **not a build phase** — it is a gap-closure, redeploy and documentation phase, and the
research finding that matters most is how *small* the code gap actually is. A named-test inventory
of all 548 tests across 47 files shows blueprint §42's Hevy checklist is 6/7 covered by name, its
analytics checklist 7/7, and its MCP checklist 6/6. The one structural gap DEPLOY-03 leaves open is
blueprint §43's full-chain composition test: `test_hevy_end_to_end.py` stops at Postgres and never
touches `app/analytics/*` or `app/mcp/*` `[VERIFIED: read of the file; zero `mcp` imports]`.
Everything else in this phase is infrastructure procedure and prose.

Three findings will change the plan if the planner does not know them, and all three were verified
against real repo state rather than assumed:

1. **The live service does not serve the Phase 6 tool set.** The last deploy is
   `brett-00005-gcx` from Phase 2 (2026-08-29); `git log` shows no deploy since, and Phase 6 added
   twelve tools that have never reached Cloud Run. ROADMAP criterion #2 ("the deployed connector
   serves the **real tool set**") therefore requires an explicit redeploy task, which is also the
   prerequisite for D-09's coaching UAT.
2. **D-04's rotation verification cannot succeed as written against the current production
   config.** `deploy/cloud-run.env.yaml` sets `MCP_AUTH_MODE: "authkit"`, and
   `build_token_verifier` returns `AuthKitJWTVerifier` in that mode — `StaticTokenVerifier` is
   never constructed, so a bearer request carrying the *new* `MCP_AUTH_SECRET` gets **401, not
   success**. The runbook must flip `MCP_AUTH_MODE` to `static`, verify old→401 / new→200, then
   flip back — which usefully also exercises the documented WorkOS-outage rollback path for the
   first time.
3. **Neon's Free plan gives a 6-hour restore window, capped at 1 GB of change.** D-02's
   verification is fully executable inside that window, but the runbook must state the coverage
   honestly: this is "recover from a bad sync you noticed today", not "restore last month's data".
   And the correct primitive is `neon branches create --parent <RFC3339-timestamp>` (a
   non-destructive fresh branch with its own connection string), **not** `neon branches restore`,
   which overwrites the target branch in place.

For rate limiting, the correct seam is a pure-ASGI middleware registered with
`app.add_middleware()` on the FastAPI app: Starlette applies app-level middleware outermost, before
routing, so it sits ahead of the `/` mount and therefore ahead of the SDK's own
`RequireAuthMiddleware` — satisfying "applied ahead of handler work" and also limiting
*unauthenticated* floods. It must be pure ASGI and not `BaseHTTPMiddleware`, both to match the
project's existing precedent (`main.py`'s comment on `CorrelationIdMiddleware`) and because the MCP
endpoint returns a streaming SSE response that `BaseHTTPMiddleware` breaks.

**Primary recommendation:** Treat this phase as four independent tracks — (a) one composition test
plus two named coverage gaps, (b) one ~40-line clock-injectable ASGI token bucket exempting
`/health` and `/.well-known/*`, (c) a redeploy and two runbook documents proven once by hand
against the live Neon project and Cloud Run service, (d) `docs/coaching-instructions.md` built
around the verified 13-tool signature table below. Add zero dependencies and no migration.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Request rate limiting | FastAPI app / ASGI middleware | — | Must run before routing so it covers both `/api/v1/*` and the `/`-mounted MCP sub-app, and before `RequireAuthMiddleware` so an unauthenticated flood is also bounded. Cannot live in the MCP tool layer: by then auth, transport and dispatch have already run. |
| 429 / 401 response shaping | ASGI middleware (429) / MCP SDK (401) | — | The 401 envelope is produced by `RequireAuthMiddleware` from `AuthSettings` and is **not ours to change** (see `test_mcp_auth.py` docstring). The 429 is entirely ours and must be shaped to match the 401's minimal-key discipline. |
| Full-chain composition test | pytest integration test | Postgres testcontainer + respx `httpx2_mock` | The chain crosses four packages; the only place it can be asserted is a test that owns all four. |
| Backup / restore | Neon control plane (external) | Runbook doc in repo | Neon owns WAL retention and branch creation. The repo owns only the reproducible procedure and the verification record. |
| Secret storage & rotation | Google Secret Manager (external) | `scripts/deploy-cloud-run.sh` + runbook | Secret Manager holds versions; Cloud Run resolves `:latest` **at instance start**, so the repo's deploy script is the mechanism that makes a rotation take effect. |
| Coaching behaviour / persona | Claude client (Project custom instructions) | `docs/coaching-instructions.md` in repo | MCP is read-only, stateless and request-response; the server has no channel that injects a system prompt into a conversation. The document is the artifact; the client is the loader. |
| Data-freshness / sparsity signalling | Analytics layer (already shipped, DQ-01/DQ-02) | Coaching doc (tells Claude to read it) | The envelope exists on every response. Phase 7 adds no code here — it adds the instruction to *use* it. |

## Standard Stack

### Core

**This phase adds zero runtime dependencies and zero dev dependencies.** Every tool it needs is
already pinned in `pyproject.toml` and installed in `.venv`. A proposed new dependency is a signal
the design drifted.

| Library | Version | Purpose in Phase 7 | Why standard here |
|---------|---------|--------------------|-------------------|
| `pytest` | 9.1.1 | Test runner for the composition test and the limiter tests | `[VERIFIED: pyproject.toml + importlib.metadata]` Already the project's runner; `asyncio_mode = "auto"` removes per-test decorators |
| `pytest-asyncio` | 1.4.0 | Async test support | `[VERIFIED: pyproject.toml]` |
| `testcontainers[postgres]` | 4.15.0 | Real Postgres for the composition test | `[VERIFIED: pyproject.toml]` CLAUDE.md forbids SQLite here; the composition test runs `date_trunc`-backed analytics |
| `pytest-httpx2` | 1.0.0 | Mock Hevy in the composition test | `[VERIFIED: pyproject.toml]` The `httpx2_mock` fixture is already used by `test_hevy_end_to_end.py` |
| `mcp` (`Client`) | 2.0.0 | Drive tools in-memory at the end of the chain | `[VERIFIED: importlib.metadata + live import]` `Client(mcp)` connects straight to the `MCPServer` object; already used in `test_mcp_mount.py`/`test_mcp_tools.py` |
| `fastapi.testclient.TestClient` | 0.141.1 | Drive the limiter and auth over real HTTP | `[VERIFIED: pyproject.toml]` Already the `client` conftest fixture |
| `starlette` | 1.6.0 | Pure-ASGI middleware base (`Scope`/`Receive`/`Send`, `Response`) | `[VERIFIED: importlib.metadata]` Transitive via FastAPI; no direct dependency needed |
| `structlog` | 26.1.0 | Rate-limit rejection logging through the existing redaction chain | `[VERIFIED: pyproject.toml]` FOUND-05's pipeline is already wired |
| `time-machine` | 3.4.0 | Deterministic clock in **date**-based tests | `[VERIFIED: pyproject.toml]` — but see § *Pitfall 4*: it does **not** patch `time.monotonic()` |

### Supporting (external, not Python packages)

| Tool | Version | Purpose | When to use |
|------|---------|---------|-------------|
| `gcloud` | 578.0.0 | Deploy, secret version add, revision inspection | `[VERIFIED: gcloud --version on this machine]` Every deploy/rotation step |
| Neon CLI (`neon`) | latest | Branch-from-timestamp for the D-02 restore proof | `[VERIFIED: not installed on this machine]` — use `npx neonctl@latest` or the REST API; see § *Environment Availability* |
| `psql` | 18.6 | Row-count / checksum comparison between the production branch and the restored branch | `[VERIFIED: psql --version on this machine]` D-02's verification step |
| Docker | 29.4.2 (client) | Postgres testcontainer | `[VERIFIED: docker --version]` Required for the integration suite |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Pure-ASGI token bucket | `slowapi` 0.1.x | Adds a dependency, pins `limits`, and **its Starlette 1.x compatibility is unverified** — CLAUDE.md already tells you to defer it until the API opens to the iOS app. Rejected. |
| Pure-ASGI middleware | `BaseHTTPMiddleware` | **Do not.** It buffers the response body and breaks streaming; the MCP endpoint returns `text/event-stream` (the app is built with `json_response` left at its `False` default). `main.py` already documents the pure-ASGI requirement for `CorrelationIdMiddleware`. Rejected. |
| ASGI middleware | `MCPServer(middleware=[ServerMiddleware])` | `[VERIFIED: source read of mcp/server/context.py:146 and mcpserver/server.py:175]` This hook is real and runs per inbound MCP message — but it runs *inside* the ASGI stack, i.e. **after** `RequireAuthMiddleware`, so it cannot bound an unauthenticated flood. The SDK's own docstring says the API is "expected to change before v2 is final". Rejected for rate limiting; noted as a future observability seam. |
| `neon branches create --parent <ts>` | `neon branches restore` | `restore` is an **in-place overwrite** of the target branch ("a complete overwrite, not a merge") and renames the original to `{branch}_old_{ts}`. Running it against production to *prove a backup works* is the wrong shape of risk. Use it only in a genuine recovery. |
| `neon branches create --parent <ts>` | `neon snapshots create` / `restore` | Snapshots are a valid alternative and restore into a **new** branch with a preview + `finalize` step. But the Free plan allows only **1 manual snapshot**, so spending it on a drill costs the one slot. Branch-from-timestamp is free within the 6-hour window and non-destructive. |
| Neon-native restore | `pg_dump`/`pg_restore` script | Explicitly deferred by D-01. |

**Installation:** none. Verify the existing lock is intact instead:

```bash
uv sync --group dev --frozen
```

**Version verification performed 2026-09-01** against the live `.venv` via
`importlib.metadata.version`: `mcp 2.0.0`, `mcp-types 2.0.0`, `starlette 1.6.0`,
`fastapi 0.141.1`, `httpx2 2.12.0`, `pydantic 2.13.4`. All match `pyproject.toml`.

## Architecture Patterns

### System Architecture Diagram

The two request paths this phase touches, and where the new limiter sits:

```
                    ┌──────────────────────────────────────────────────────────┐
  Claude Desktop ──▶│ Cloud Run edge (terminates TLS, sets X-Forwarded-For)     │
  / Web / Mobile    └───────────────────────────┬──────────────────────────────┘
  (egress                                       │  HTTP/1.1, original Host header
   160.79.104.0/21)                             ▼
                    ┌──────────────────────────────────────────────────────────┐
                    │ uvicorn ──▶ FastAPI `app`                                 │
                    │                                                           │
                    │  ① ServerErrorMiddleware        (Starlette, outermost)    │
                    │  ② ★ RateLimitMiddleware ★      ← NEW, pure ASGI          │
                    │       ├─ exempt: /health, /.well-known/*  ──────────────┐ │
                    │       └─ over limit ─▶ 429 + Retry-After ──▶ RESPOND    │ │
                    │  ③ CorrelationIdMiddleware      (existing)              │ │
                    │  ④ ROUTING                                              │ │
                    │       ├─ GET /health ──────────▶ health.py ──▶ engine ◀─┘ │
                    │       ├─ /openapi.json, /docs                             │
                    │       └─ mount("/", mcp_app)                              │
                    │            ├─ /.well-known/oauth-protected-resource/mcp   │
                    │            │     (anonymous — RFC 9728 discovery)         │
                    │            └─ POST /mcp                                   │
                    │                 ├─ AuthenticationMiddleware(BearerAuth)   │
                    │                 ├─ RequireAuthMiddleware ─▶ 401 + WWW-Auth│
                    │                 │     └─ AuthKitJWTVerifier (PROD)        │
                    │                 │        StaticTokenVerifier (rollback)   │
                    │                 └─ StreamableHTTP dispatch                │
                    │                      └─ ServerMiddleware chain (OTel)     │
                    │                           └─ tool handler @safe_tool      │
                    │                                └─ read_only_session ──────┼─▶ Neon Postgres
                    └──────────────────────────────────────────────────────────┘        │
                                                                                         │
  Hevy API ──▶ HevyClient (httpx2 + tenacity) ──▶ HevySyncService ──▶ (commit) ──────────┘
      ▲                                                                                  │
      │ (manual: `python -m app.cli sync-hevy`)                          app/analytics/* ─┘
      │                                                                     (pure reads)
   OPEN QUESTION 1: nothing schedules this today
```

Data flow for the **composition test** (blueprint §43), which is the phase's one real code artifact:

```
 canned Hevy JSON fixtures            (backend/tests/fixtures/hevy/*.json)
            │
            ▼  respx Router intercepts httpx2
   HevyClient ──▶ HevySyncService.sync_all()   [templates → workouts → body]
            │
            ▼  COMMITTED rows
   Postgres testcontainer  (schema built by `alembic upgrade head`)
            │
            ├──▶ app/analytics/volume.get_weekly_volume        ─┐
            ├──▶ app/analytics/rollup / muscle folds             │  assert hand-computed
            └──▶ app/analytics/metadata.build_freshness         ─┘  values from the fixtures
            │
            ▼  same engine, new session via app.state.sessionmaker
   Client(mcp) ──▶ fitness_get_training_summary / fitness_get_weekly_volume
            │
            ▼
   assert structured_content matches the SAME hand-computed numbers
```

### Recommended file placement

```
backend/app/
├── middleware/                        # NEW package (or a single module — see note)
│   └── rate_limit.py                  # pure-ASGI token bucket + key fn + 429 body
backend/tests/
├── test_rate_limit.py                 # NEW: bucket unit tests (fast, injected clock)
│                                      #      + over-HTTP 429 tests (integration)
└── test_full_chain_end_to_end.py      # NEW: blueprint §43 composition test
docs/
├── coaching-instructions.md           # NEW (COACH-01, D-07)
├── runbook-backup-restore.md          # NEW (D-02)   ← name is Claude's discretion
└── runbook-secret-rotation.md         # NEW (D-04)   ← name is Claude's discretion
.planning/phases/07-.../
└── 07-COACH-VERIFICATION.md           # NEW (D-09 UAT record) ← naming is Claude's discretion
```

*Note on placement:* `backend/app/` has no `middleware/` package today. A single module
`backend/app/middleware.py` is equally acceptable and arguably better — there is exactly one
middleware to write, and `app/logging.py` and `app/config.py` set the precedent for
single-module cross-cutting concerns. Either way, `test_mcp_isolation.py`'s static guards scan
`app/mcp/` only, so a limiter outside that tree is unaffected.

---

### Pattern 1: Pure-ASGI token-bucket rate limiter

**What:** A fixed-capacity token bucket refilled at a constant rate, evaluated in a pure-ASGI
middleware registered on the FastAPI app, with an injected clock.

**Why this seam:** Starlette applies `app.add_middleware()` middleware **outermost, wrapping the
router** `[CITED: starlette.io/middleware — "ServerErrorMiddleware is added as the very outermost
middleware... ExceptionMiddleware as the very innermost, to deal with... routing or endpoints"]`.
Routing — and therefore `app.mount("/", mcp_app)` — happens *inside* that wrapper, so an app-level
middleware runs before the MCP sub-app's `AuthenticationMiddleware`/`RequireAuthMiddleware` chain
`[VERIFIED: mcp/server/mcpserver/server.py builds those as Starlette `middleware=` on the sub-app]`.
This satisfies ROADMAP criterion #2's "rate limiting applied ahead of handler work" in its
strongest reading: ahead of auth, too.

**Registration order matters.** `add_middleware` **prepends**, so the middleware added *last* runs
*first*. `main.py` currently adds `CorrelationIdMiddleware` and nothing else. To have the limiter
run outermost, add it **after** `CorrelationIdMiddleware`; to have correlation IDs available in the
limiter's rejection log, add it **before**. Recommendation: add it **before**
`CorrelationIdMiddleware` in source order — i.e. the correlation ID is set first — so a
`rate_limit_rejected` log line carries the same `correlation_id` as everything else and the
existing `unhandled_exception_handler` contract is unchanged. The limiter is still ahead of
routing and auth either way.

**Exemptions (non-negotiable):**

| Path | Why exempt |
|---|---|
| `GET /health` | Cloud Run startup/liveness probes hit it, and it is the only endpoint an uptime monitor can poll. A limiter that 429s a probe makes the revision look unhealthy for a reason nothing in `health.py` explains — the exact failure class `test_health_still_wins_after_mount` already guards against. |
| `/.well-known/oauth-protected-resource/mcp` | Fetched **anonymously** by Claude during connector discovery, inside a documented 10-second budget `[CITED: claude.com/docs/connectors/building/authentication]`. Throttling it breaks connector setup with the opaque "Couldn't reach the MCP server". |

**Configuration:** two `Settings` fields with safe defaults (`RATE_LIMIT_PER_MINUTE`,
`RATE_LIMIT_BURST`). Adding them to `Settings` **requires** a matching entry in
`deploy/cloud-run.env.yaml` only if you want to override the default — but note
`test_cloud_run_deploy.py` cross-checks the env file's keys against `Settings` fields in **both**
directions, so read that module before touching either file.

**When to use:** always on. There is no "development bypass" — a limiter that is off in
development is a limiter nobody has ever seen fire.

---

### Pattern 2: The full-chain composition test (blueprint §43, ROADMAP criterion #1)

**What:** One new module that runs mock-Hevy → `sync_all()` → Postgres → analytics → an MCP tool,
asserting the *same* hand-computed number at the analytics boundary and at the MCP boundary.

**Why a new module rather than extending `test_hevy_end_to_end.py`:** that module's helpers
(`_counts`, `_cleanup`, `_mock_hevy`) are scoped to sync assertions and every test there ends in a
`finally: await _cleanup(maker)`. The MCP half needs `app.state.sessionmaker` wired and possibly a
`TestClient`, which is a different fixture shape. Copying `_mock_hevy` into the new module matches
this repo's established discipline of *not* sharing fixtures across test modules (stated explicitly
in `test_mcp_auth.py` and `test_mcp_mount.py`: "test modules in this repo do not import each other").

**The three non-obvious mechanics:**

1. **Committed vs flushed.** `sync_all()` commits, so the data really is visible to another
   connection — unlike `golden_workout`. Good. But the test must still clean up with a
   compensating `DELETE`, exactly as `test_hevy_end_to_end.py::_cleanup` does, because a rollback
   cannot undo a commit and the container is session-scoped.
2. **The MCP tool opens its own session.** `Client(mcp)` runs `mcp_lifespan`, which reads
   `app.state.sessionmaker` `[VERIFIED: app/mcp/context.py:41]`. The test must assign
   `app.state.sessionmaker` to a sessionmaker over the **same testcontainer engine** the sync
   wrote through, or the tool queries a different database. `test_mcp_mount.py::mcp_server` is the
   pattern to copy (save the pre-existing value, restore it in `finally`).
3. **Assert the same number twice.** The whole value of a composition test is catching a layer
   that is individually correct and collectively wrong. Call the analytics function directly,
   assert the hand-computed value, then call the MCP tool and assert the *same* value out of
   `structured_content`. A test that only asserts "the tool returned something" would have passed
   throughout Phase 6 and proves nothing new.

**Fixture arithmetic:** the canned fixtures yield 2 workouts / 4 sets / 4 templates / 2 body
measurements `[VERIFIED: assertions in test_hevy_end_to_end.py:250-254]`. That is enough for a
composition proof but the fixture workout dates are fixed, so a `weeks=N` window anchored on
*today* will not contain them. Either (a) freeze the clock with `time-machine` to a date inside the
fixture window, or (b) call the analytics function with an explicit range. Option (b) is simpler
for the analytics half; option (a) is required for the MCP half, since every `weeks`-taking tool
computes its window from `local_today()` `[VERIFIED: app/mcp/tools/_common.py docstring]`.

---

### Pattern 3: Neon backup/restore verification (D-01, D-02)

**What:** A non-destructive branch created from a past timestamp inside the history window,
compared row-for-row against the live branch, then deleted.

**The primitive:** `neon branches create --parent <RFC3339 timestamp>`
`[CITED: neon.com/docs/reference/cli-branches — "Parent branch name or id or timestamp or LSN";
example `neon branches create --name data_recovery --parent 2023-07-11T10:00:00Z`]`. This produces
a **new branch with its own connection string** — literally "restores into a fresh instance" as
ROADMAP criterion #3 phrases it — while leaving production untouched.

**What NOT to use:** `neon branches restore <target> ^self@<ts>` performs "a complete overwrite,
not a merge" of the target branch and renames the original to `{branch}_old_{ts}`
`[CITED: neon.com/docs/guides/branching-pitr]`. That is the real-incident procedure, and the
runbook should document it *as* the real-incident procedure — but the *drill* must not run it
against production.

**Free-plan constraints that must be written into the runbook:**

| Constraint | Value | Consequence |
|---|---|---|
| History (restore) window | **6 hours**, capped at 1 GB of change `[CITED: neon.com/docs/introduction/plans]` | Any `--parent` timestamp older than ~6h fails. The drill must pick a timestamp minutes-to-hours old. **And the honest coverage statement is "6 hours", not "backed up".** |
| Branches per project | 10 | The drill branch must be deleted afterwards; leaking drill branches eventually blocks the next one. |
| Manual snapshots | **1** | Do not spend it on the drill. |
| Storage | 0.5 GB/project | Current dataset (327 workouts, 463 templates, 123 measurements) is far below; branches are copy-on-write so the drill adds ~nothing. |
| Restorable source | **root branches only** | `main`/`production` is a root branch; this is satisfied by default. |

**The comparison step (what makes it a *proof*, not a ritual):** connect to the drill branch with
`psql` and run the same aggregate query against both branches. Row counts alone are weak — an
identical count with corrupted rows passes. Use a per-table count **plus** a content digest:

```sql
SELECT 'workouts' AS t, count(*), md5(string_agg(external_id, ',' ORDER BY external_id)) FROM workouts
UNION ALL SELECT 'workout_sets', count(*), md5(string_agg(id::text, ',' ORDER BY id)) FROM workout_sets
UNION ALL SELECT 'exercise_templates', count(*), md5(string_agg(external_id, ',' ORDER BY external_id)) FROM exercise_templates
UNION ALL SELECT 'body_measurements', count(*), md5(string_agg(measured_on::text, ',' ORDER BY measured_on)) FROM body_measurements
ORDER BY 1;
```

Run it on both branches and diff the output. If the branch timestamp is genuinely in the past and a
sync ran since, the digests will legitimately differ — which is why the drill should pick a
timestamp from a quiet period, or the runbook should record *why* a difference is expected.

**Cleanup:** `neon branches delete <name>`. The runbook must include it; the drill is not finished
until the branch is gone.

---

### Pattern 4: `MCP_AUTH_SECRET` rotation (D-03, D-04)

**What:** Add a Secret Manager version, redeploy, verify, disable the old version.

**The mechanism, verified:** Cloud Run resolves `--set-secrets=NAME=secret:latest` into an
**environment variable at instance start**, not per request. "Newly started instances use the
current latest version, but already running instances keep the value they received at startup"
`[CITED: docs.cloud.google.com/run/docs/configuring/services/secrets]`. So adding a version has
**zero effect** until a new revision serves traffic — exactly what D-04 assumes, and exactly why
the runbook is a deploy procedure and not a `gcloud secrets` procedure.

**The blocker D-04 does not account for.** `deploy/cloud-run.env.yaml:50` sets
`MCP_AUTH_MODE: "authkit"`, and `build_token_verifier` returns `AuthKitJWTVerifier` whenever the
mode is `authkit` — `StaticTokenVerifier` is never constructed `[VERIFIED: app/mcp/auth.py:127-141]`.
Against the current production config, a `curl` to `/mcp` with `Authorization: Bearer <new
MCP_AUTH_SECRET>` returns **401**, identically to the old token, because the JWKS verifier rejects
a non-JWT. D-04's stated verification ("old → 401, new → success") is therefore not executable
without a mode flip.

**Recommended runbook sequence** (preserves every D-04 constraint — no new code, no dual-secret
window, no secret value in the repo — while making the verification meaningful):

```bash
# 0. PRECONDITION: confirm which mode is live, so the flip is deliberate.
gcloud run services describe brett --project="$BRETT_GCP_PROJECT" --region=us-central1 \
  --format='value(spec.template.spec.containers[0].env)'

# 1. Mint and add a new version. Never echoed, never written to a file in the repo.
python -c 'import secrets; print(secrets.token_urlsafe(48))' \
  | tr -d '\n' \
  | gcloud secrets versions add brett-mcp-auth-secret --project="$BRETT_GCP_PROJECT" --data-file=-

# 2. Flip to the static verifier (this is the documented WorkOS-outage rollback path,
#    exercised here for the first time) and deploy. `:latest` resolves on this deploy.
#    Edit deploy/cloud-run.env.yaml: MCP_AUTH_MODE: "static"
./scripts/deploy-cloud-run.sh

# 3. VERIFY against the live endpoint.
#    old token  -> 401       new token -> 200 with the 13-tool list
#    (use the MCP envelope from test_mcp_auth.py: MCP_HDRS + LIST_BODY; params._meta is mandatory)

# 4. Flip back to authkit and deploy again. Confirm the Claude connector still works.
#    Edit deploy/cloud-run.env.yaml: MCP_AUTH_MODE: "authkit"
./scripts/deploy-cloud-run.sh

# 5. Only after step 4 is green: DISABLE (never destroy) the previous version, so a rollback
#    is still possible for the retention period.
gcloud secrets versions disable <PREV_VERSION> --secret=brett-mcp-auth-secret --project="$BRETT_GCP_PROJECT"
```

**IAM note:** `roles/secretmanager.secretAccessor` is granted on the *secret*, not per version
`[ASSUMED — standard Secret Manager IAM model; confirm against the project's actual binding before
relying on it]`. If the Phase 2 bootstrap bound the role at version scope instead, step 2 fails at
instance start with a permission error and the revision never becomes ready.

**"Without breaking the live connector":** with `MCP_AUTH_MODE=authkit` (the steady state),
rotating `MCP_AUTH_SECRET` has no effect on the Claude connector at all — Claude authenticates with
a WorkOS JWT. That is the property the criterion asks for, and it is trivially true; the runbook
should say so plainly rather than implying the rotation was risky.

---

### Pattern 5: The coaching instructions document (COACH-01, D-05..D-09)

**What:** A markdown file the user pastes once into a Claude Project's custom instructions.

**Why there is no server-side alternative that satisfies D-08.** The MCP tool surface is read-only
and the 2026-07-28 transport is stateless; there is no per-conversation server hook that injects a
system prompt. What *does* exist, and is worth knowing:

- `MCPServer(instructions=...)` is a real constructor parameter and **is** delivered under the
  stateless transport — the `server/discover` handler returns `DiscoverResult(instructions=...)`
  `[VERIFIED: source read of mcp/server/lowlevel/server.py:660-676 and
  mcp_types/_v2026_07_28/__init__.py:3165, whose docstring says "This can be used by clients to
  improve an LLM's understanding of available tools (e.g., by including it in a system prompt)"]`.
- Whether **Claude's connector** actually injects it is **unverified** `[LOW confidence]`. Some MCP
  clients do; no Anthropic documentation found that confirms it for custom connectors.
- MCP *prompts* (`mcp.add_prompt`) are also available `[VERIFIED: MCPServer.add_prompt exists]` and
  surface as user-invocable templates in some clients — but that is a per-invocation mechanism,
  which D-08 explicitly rejected in favour of Project-level loading.

**Recommendation:** build `docs/coaching-instructions.md` as D-08 specifies. Optionally, and as a
*separate small task*, also pass a short (≤ ~1 KB) `instructions=` string to `MCPServer` naming the
tool-selection rules — it costs one constructor argument, cannot break anything, and D-09's UAT is
already a live Claude session where its effect (or absence) can be observed for free. Do **not**
make the coaching document depend on it.

**Section skeleton** (blueprint §34-36 order preserved, per D-05):

1. **Role** — "Personal Body Recomposition Coach" (blueprint §34, verbatim).
2. **Core objectives** — the 5, verbatim: build muscle; reduce unnecessary body fat; improve
   strength; maintain sustainable habits; avoid unnecessary program changes.
3. **The data rule** — "Use the MCP tools before making any claim about the user's recent
   training. If a tool call fails or returns `data_available: false`, say so; never substitute
   general training knowledge for the user's actual data."
4. **Decision framework** — the 7 steps, verbatim (blueprint §35), including the closing
   constraint "Do not immediately change the training program."
5. **Question → tool mapping** (D-06) — the table below.
6. **How to read the metadata envelope** — the exact field names, below.
7. **Units, timezone and framing** — kilograms, centimetres, `Asia/Jakarta` local weeks starting
   Monday; the recomposition verdict is decision support, and its `recomposition_disclaimer` field
   must be surfaced when the verdict is.
8. **Example questions** — blueprint §36's list, each annotated with its first tool call.

**D-06's question → tool mapping.** Verified against the live registry on 2026-09-01 by importing
`app.mcp.server.mcp` and calling `list_tools()` — these are the real names, the real parameter
names, and the real required-parameter sets, not schema guesses:

| The user asks | Call | Parameters (required in **bold**) |
|---|---|---|
| "Am I progressing?" / "How's my training going?" / any broad opener | `fitness_get_training_summary` | `weeks` (default; max 52) |
| "Which muscles are undertrained?" / "too much volume?" / "how many sets for side delts?" | `fitness_get_muscle_group_volume` | `weeks` |
| "How much am I training?" / "is my volume up or down?" | `fitness_get_weekly_volume` | `weeks` |
| "How often do I train X?" / "am I hitting each muscle enough times a week?" | `fitness_get_training_frequency` | `weeks` |
| "Is my bench going up?" / "show me my squat over time" | `fitness_get_exercise_progression` | **`exercise_name`**, `weeks` |
| "What are my PRs?" / "biggest strength improvements" | `fitness_get_personal_records` | **`exercise_name`**, `weeks` |
| "Which exercises have stalled?" | `fitness_get_plateaus` | `lookback_weeks`, `plateaued_only` |
| "Compare my last 4 weeks to the previous 4" | `fitness_compare_periods` | **`period_a_start`, `period_a_end`, `period_b_start`, `period_b_end`**, `include_muscle_groups` |
| "Has my weight trend changed?" / "am I gaining too fast?" | `fitness_get_body_weight_trend` | *(none)* |
| "Is my training appropriate for recomposition?" | `fitness_get_recomposition_status` | *(none)* |
| "What did I do this week?" / "my last few sessions" | `fitness_get_recent_workouts` | `limit` (max 25) |
| "What exactly did I do in that session?" | `fitness_get_workout` | **`workout_id`** (from `fitness_get_recent_workouts`) |
| "Is the connector working?" | `fitness_ping` | *(none)* |

Two behaviours the document must state explicitly, because they are non-obvious from the schemas:

- **`fitness_compare_periods` takes four explicit dates, not a `weeks` count.** Claude must compute
  the four dates itself. Tell it to, and give a worked example.
- **`exercise_name` resolution is by title and can be ambiguous.** Two templates can share a title;
  the tool returns every candidate with `matched=False` rather than guessing
  `[VERIFIED: 06-VERIFICATION.md; `test_ambiguous_exercise_name_returns_every_candidate`]`. Tell
  Claude to present the candidates and ask, never to pick one.

**Staleness / sparsity instructions — the exact field names.** ROADMAP criterion #4 requires Claude
to "correctly flag stale or sparse data when present". Every analytics-backed response carries
`[VERIFIED: app/analytics/schemas.py:57-84]`:

| Field | Type | What the document must tell Claude |
|---|---|---|
| `freshness.resources` | `dict[str, datetime \| None]` keyed by `workouts`, `exercise_templates`, `body_measurements` | Compare each against today. If the relevant resource's `last_synced_at` is more than a few days old — or `null` — say so **before** answering, and say which resource. A stale `exercise_templates` sync silently changes every per-muscle number. |
| `coverage.sessions_in_window` | `int` | State it when it is low. "3 sessions" is not a trend. |
| `coverage.insufficient_data` | `bool` | When `true`, do not give a verdict. Say what is missing and what would make the answer possible. |
| `coverage.earliest_data_at` | `datetime \| None` | Distinguishes "you did not train in this window" from "your synced history does not reach back that far". Use it before concluding a gap in training. |
| `data_available` | `bool` (every `*Response`) | `false` means the server could not answer — a degraded response, not an empty result. Never read `false` as "the user has no training data". |

**D-09 UAT script** (the record artifact is Claude's discretion; the *content* should be):
1. Confirm the deployed revision serves 13 tools (see § *Pitfall 1* — this is not currently true).
2. Confirm the Project has the connector attached and the document pasted into custom instructions.
3. Ask "Am I progressing?" — record which tools Claude called, in what order, and whether it used
   `fitness_get_training_summary` as the opener the mapping specifies.
4. Ask "Which muscles are undertrained?" — record whether it used
   `fitness_get_muscle_group_volume` and whether it distinguished direct from indirect sets.
5. **Force the staleness case.** Do not wait for it to occur naturally: ask a question whose window
   provably outruns the data (e.g. `weeks=52` when history is shorter, or ask after deliberately
   not syncing) and record whether Claude surfaced `coverage`/`freshness` unprompted.
6. Record the transcript (or a faithful summary) and one line per criterion: pass/fail.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Postgres backup & restore | A `pg_dump`/`pg_restore` cron + retention policy + integrity checker | Neon branch-from-timestamp / snapshots | D-01 locks this. Neon's PITR is WAL-level and instant; a hand-rolled dump path has its own untested restore, its own storage, and its own silent-failure mode. |
| Restoring into a fresh instance | Provisioning a second Neon project and replaying a dump into it | `neon branches create --parent <ts>` | Copy-on-write: milliseconds, no data copied, own connection string. `[CITED: neon.com/docs/introduction/branching]` |
| Secret versioning & rollback | A `secrets/` directory, a version file, or a `.env.old` | Google Secret Manager versions + `disable` | Already the project's mechanism (D-06d). Versions are immutable, `disable` is reversible, `destroy` is not. |
| Distributed rate limiting | Redis/Memorystore + a Lua token bucket | An in-process bucket | One user, one connector, `--max=2` instances. A Redis dependency doubles the failure surface and the bill to enforce a limit whose whole purpose is cost/abuse protection. |
| Rate-limit policy engine | `slowapi` / `limits` / a decorator DSL | ~40 lines with an injected clock | CLAUDE.md's explicit guidance; `slowapi`'s Starlette 1.x compatibility is unverified. |
| Constant-time secret comparison | Anything | `secrets.compare_digest`, already in `StaticTokenVerifier` | Already built and tested (`test_static_verifier_uses_constant_time_comparison`). Rotation reuses it; it must not be re-implemented. |
| JWT validation for the rotation drill | Anything | Existing `AuthKitJWTVerifier` | Untouched by this phase. |
| Sanitized error responses | A per-endpoint error formatter | The existing `@app.exception_handler(Exception)` + `@safe_tool` | Two proven layers already exist. The 429 is the only new response shape, and it is a literal dict. |
| Backend-generated coaching prose | Any natural-language generation in Python | The instructions document + Claude | REQUIREMENTS.md lists this under Out of Scope: "backend prose would be untestable and could contradict Claude's own reasoning in the same response". |

**Key insight:** every remaining piece of Phase 7 either already exists in this repo (auth,
redaction, read-only sessions, the deploy script, the test infrastructure) or belongs to an external
control plane (Neon, Secret Manager, Claude's Project UI). The only genuinely new code is one
middleware and one test module. Any plan that grows beyond that has misread the phase.

## Runtime State Inventory

*Not a rename/refactor/migration phase — this section is omitted by the template's own rule.
However, this phase does change deployed runtime state, so the equivalent inventory is recorded
here for the planner's benefit:*

| Category | Items Found | Action Required |
|---|---|---|
| Live service config | Cloud Run service `brett`, revision `brett-00005-gcx`, deployed 2026-08-29 from Phase 2 — **serves only `fitness_ping`**; the 12 Phase 6 tools have never been deployed | Redeploy via `./scripts/deploy-cloud-run.sh` (ROADMAP criterion #2) |
| Live service config | `MCP_AUTH_MODE: "authkit"` in `deploy/cloud-run.env.yaml` — flipped twice by the rotation runbook, must end on `authkit` | Verify the final revision's env before closing the phase |
| Secrets | `brett-database-url`, `brett-mcp-auth-secret` in Google Secret Manager, bound `:latest` via `--set-secrets` | Add one new `brett-mcp-auth-secret` version (D-04); disable, never destroy, the previous |
| Stored data | Neon `neondb` on branch `main`, ~327 workouts / 463 templates / 123 body measurements from the Phase 3 live sync | Read-only for this phase; the D-02 drill must not write to it |
| Client-side state | The existing Claude connector registration and (possibly) an existing Project | D-09 reuses or creates a Project; the connector's WorkOS consent survives a redeploy because `MCP_RESOURCE_URL` is unchanged |
| OS-registered state | None — no cron, no scheduler, no launchd. `README.md` states "Production scheduling is Phase 7 — nothing here runs the sync on a timer" | **See Open Question 1** — no requirement or success criterion covers this |
| Build artifacts | None stale — this phase adds no package rename |

## Common Pitfalls

### Pitfall 1: Planning around a deployment that does not exist yet
**What goes wrong:** ROADMAP criterion #2 ("the deployed connector serves the real tool set") and
D-09's UAT are both written as if the live service already exposes the Phase 6 tools. It does not.
**Why it happens:** Phase 6 was verified entirely against local test clients — `06-VERIFICATION.md`
records "Live `MCPServer` import (env-seeded, no container)", which is an *import*, not a request to
Cloud Run. `git log` since Phase 2 contains no deploy commit.
**How to avoid:** make the redeploy an explicit, early task. It is a prerequisite for D-09, and it
also has to happen **before** the rotation runbook is exercised (otherwise the rotation drill leaves
production on a revision that still serves one tool).
**Warning signs:** any plan whose first live-endpoint interaction is the coaching UAT.

### Pitfall 2: Writing the rotation runbook for a verifier that is not running
**What goes wrong:** D-04's "new token → success" step returns 401, and the phase looks broken.
**Why it happens:** `MCP_AUTH_MODE=authkit` in production means `build_token_verifier` returns
`AuthKitJWTVerifier`; `StaticTokenVerifier` is not in the request path at all
`[VERIFIED: app/mcp/auth.py:127; deploy/cloud-run.env.yaml:50]`.
**How to avoid:** the runbook must flip `MCP_AUTH_MODE` to `static`, deploy, verify, flip back,
deploy — and must state the precondition check first. See § *Pattern 4*.
**Warning signs:** a runbook draft that contains a single `./scripts/deploy-cloud-run.sh` call.

### Pitfall 3: Keying the rate limiter on a client IP that is neither trustworthy nor distinguishing
**What goes wrong:** the limiter appears to work in tests and is trivially evaded (or degenerately
global) in production.
**Why it happens — three compounding facts, all verified:**
- `request.client.host` under Cloud Run is the **proxy**, not the client: uvicorn's
  `--forwarded-allow-ips` defaults to `127.0.0.1` and the Procfile passes no override
  `[VERIFIED: Procfile; CITED: uvicorn.dev/settings]`. So the naive key is one constant value.
- `X-Forwarded-For`'s first entry is the client per GCP's own docs
  `[CITED: docs.cloud.google.com/functions/docs/reference/headers — "X-Forwarded-For: clientIp,
  proxy1Ip, proxy2Ip"]` — but the service is `--allow-unauthenticated`, so any internet client can
  send its own XFF header and Cloud Run appends to it. The key is attacker-controlled.
- All legitimate traffic originates from Anthropic's egress range `160.79.104.0/21`
  `[CITED: claude.com/docs/connectors/building/authentication]`, so per-IP keying is *already*
  near-global for the only client that matters.

**How to avoid:** make the **global bucket** the enforceable control — one bucket for the whole
process, which no header can evade and which is the right shape for a single-user connector. If a
per-key bucket is also wanted (useful for logs), derive the key from
`X-Forwarded-For.split(",")[0].strip()` in a small, separately-tested function, and document in the
module that it is advisory only. This is a deliberate, evidence-backed departure from CLAUDE.md's
"keyed on client IP" suggestion, which CONTEXT.md explicitly leaves open.

### Pitfall 4: Testing the token bucket with `time-machine`
**What goes wrong:** the refill test hangs, sleeps for real, or passes vacuously.
**Why it happens:** `time_machine.travel()` patches `time.time()` but **not** `time.monotonic()`.
Verified in this session:

```
>>> m0 = time.monotonic()
>>> with time_machine.travel(1000000000.0, tick=False): m1 = time.monotonic()
>>> m1 - m0
9.4e-06        # unaffected
```

A correct token bucket uses `time.monotonic()` (wall-clock jumps and NTP steps must not refill it),
so `time-machine` cannot drive it.
**How to avoid:** inject the clock — `RateLimiter(..., clock: Callable[[], float] = time.monotonic)`
— and pass a fake in tests. This is the project's established pattern: `HevyClient(sleep=...)` is
injected for exactly this reason `[VERIFIED: test_hevy_end_to_end.py:92-97]`.
**Warning signs:** any test containing `await asyncio.sleep(...)` to wait for a refill.

### Pitfall 5: Using `BaseHTTPMiddleware` for the limiter
**What goes wrong:** MCP responses hang or arrive truncated, intermittently, and only under real
HTTP.
**Why it happens:** `mcp_app` is built with `json_response` at its `False` default
`[VERIFIED: app/mcp/server.py:192-201]`, so `/mcp` responds `text/event-stream`.
`BaseHTTPMiddleware` materialises the response and interferes with streaming.
**How to avoid:** write pure ASGI (`async def __call__(self, scope, receive, send)`), which is what
`main.py`'s existing comment already mandates for `CorrelationIdMiddleware`: "Pure-ASGI middleware,
not BaseHTTPMiddleware".
**Warning signs:** `from starlette.middleware.base import BaseHTTPMiddleware` anywhere in the diff.

### Pitfall 6: Reaching for `respx` types in the composition test
**What goes wrong:** `AssertionError: assert isinstance(resolved.response, httpx.Response)` from
inside `respx/router.py`, with nothing pointing at the type as the cause.
**Why it happens:** `pytest-httpx2` is a thin adapter over `respx`, and respx asserts on the
`httpx` **0.x** `Response` type, while the client under test is `httpx2`.
**How to avoid:** follow the rule already written into `conftest.py`: **responses** use
`httpx.Response` (0.x); **exceptions** use `httpx2` types (`httpx2.ConnectError`, ...). Copy
`_mock_hevy` from `test_hevy_end_to_end.py`, which already obeys it. Also note respx asserts every
registered route was called — do not register `/v1/workouts/events` in a test that never goes
incremental.

### Pitfall 7: Rate-limiting `/health` or the RFC 9728 metadata document
**What goes wrong:** the revision is marked unhealthy, or the Claude connector fails discovery with
"Couldn't reach the MCP server" — neither symptom points at the limiter.
**How to avoid:** exempt both paths explicitly, and assert the exemption with a test
(`test_health_is_never_rate_limited`, `test_discovery_document_is_never_rate_limited`).
**Warning signs:** a limiter whose only test drives `/mcp`.

### Pitfall 8: A 429 body that grows a field
**What goes wrong:** the rejection response starts echoing the presented credential, the configured
issuer, or an exception detail — on an endpoint anyone on the internet can make emit it.
**Why it happens:** the 429 body is ours, and unlike the 401 it has no SDK contract holding it
still.
**How to avoid:** mirror `test_401_leaks_nothing`'s discipline exactly — assert the **exact key
set** of the JSON body, not merely the absence of known-bad strings. A substring check cannot
notice a new field; a key-set check cannot miss one.

### Pitfall 9: Assuming a 429 is well-behaved for MCP clients
**What goes wrong:** Claude retries immediately, amplifying the load the limiter exists to shed, or
gives up and surfaces an opaque error.
**Why it happens:** the MCP Streamable HTTP spec "doesn't standardize what `429` means... clients
see a `429`, have no specified behavior, and do something arbitrary. Some retry immediately. Some
give up." `[CITED: zuplo.com/blog/never-ship-mcp-server-without-rate-limit]`
**How to avoid:** (a) set limits generously enough that normal coaching conversations never reach
them — a single "Am I progressing?" turn may fire several tool calls; (b) always send a
`Retry-After` header, harmless if ignored; (c) treat any 429 observed during D-09's UAT as a
limit-tuning bug, not a client bug.

### Pitfall 10: The in-process bucket is per-instance
**What goes wrong:** the effective ceiling is `MAX_INSTANCES ×` the configured rate.
**Why it happens:** `scripts/deploy-cloud-run.sh` sets `--max="${BRETT_MAX_INSTANCES:-2}"`
`[VERIFIED: line 24]`, and each instance holds its own bucket.
**How to avoid:** document the multiplier in the module docstring, and pick the per-instance number
knowing it. Do not add Redis to fix it (see § *Don't Hand-Roll*).

### Pitfall 11: `mcp.session_manager._has_started` in a second `TestClient`
**What goes wrong:** the second and every later test that uses the `client` fixture fails at
lifespan startup with "can only be called once per instance".
**How to avoid:** the `client` conftest fixture already clears the flag
`[VERIFIED: conftest.py:881]`. If the composition test builds its own `TestClient` rather than using
that fixture, it must do the same — or, better, use the `Client(mcp)` in-memory path and the
`mcp_server`-style `app.state` wiring, which avoids the session manager entirely.

## Code Examples

### The limiter's shape (pure ASGI, injected clock)

```python
# backend/app/middleware.py  (illustrative; not a drop-in)
#
# Pure ASGI, never BaseHTTPMiddleware: `/mcp` responds text/event-stream and
# BaseHTTPMiddleware breaks streaming (Pitfall 5).
#
# `clock` is injected because time_machine does NOT patch time.monotonic()
# (verified 2026-09-01) and monotonic is the only correct source for a refill
# interval -- an NTP step must not top the bucket up (Pitfall 4).

import time
from collections.abc import Awaitable, Callable

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = structlog.get_logger()

# Never limited. `/health` is Cloud Run's probe target; the RFC 9728 document is
# fetched anonymously by Claude inside a 10s discovery budget (Pitfall 7).
EXEMPT_PREFIXES = ("/health", "/.well-known/")


class TokenBucket:
    def __init__(self, *, capacity: int, refill_per_second: float,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._capacity = capacity
        self._refill = refill_per_second
        self._clock = clock
        self._tokens = float(capacity)
        self._last = clock()

    def take(self) -> float | None:
        """Return None if allowed, else the seconds to wait (for Retry-After)."""
        now = self._clock()
        self._tokens = min(self._capacity, self._tokens + (now - self._last) * self._refill)
        self._last = now
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return None
        return (1.0 - self._tokens) / self._refill
```

The middleware body then sends a literal, minimal 429 — no exception text, no key echo:

```python
        retry_after = max(1, int(wait_seconds) + 1)
        # EXACT key set, asserted by test. Mirrors test_401_leaks_nothing's discipline.
        body = b'{"error":"rate_limited"}'
        await send({
            "type": "http.response.start",
            "status": 429,
            "headers": [
                (b"content-type", b"application/json"),
                (b"retry-after", str(retry_after).encode("ascii")),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        })
        await send({"type": "http.response.body", "body": body})
        # Counts and the path only. Never the token, never the header value.
        log.info("rate_limit_rejected", path=scope["path"], retry_after=retry_after)
```

### Registering it (order is load-bearing)

```python
# backend/app/main.py
# add_middleware PREPENDS, so the LAST one added runs FIRST.
# Correlation id is added second => it runs first => the limiter's rejection log
# carries the same correlation_id as every other line.
app.add_middleware(RateLimitMiddleware, limiter=build_limiter(settings))
app.add_middleware(CorrelationIdMiddleware)
```

### Wiring the MCP half of the composition test

```python
# Pattern copied from test_mcp_mount.py::mcp_server -- Client(mcp) runs mcp_lifespan,
# which reads app.state.sessionmaker (app/mcp/context.py:41). Without this the tool
# queries whatever DATABASE_URL pointed at, not the testcontainer the sync wrote to.
from mcp import Client

from app.main import app
from app.mcp.server import mcp

preexisting = getattr(app.state, "sessionmaker", None)
app.state.sessionmaker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
try:
    async with Client(mcp) as client:
        result = await client.call_tool("fitness_get_weekly_volume", {"weeks": 4})
    # Assert the SAME number the analytics call produced, not merely "not empty".
    assert result.structured_content["weekly_volume"]["weeks"][-1]["hard_sets"] == expected
finally:
    if preexisting is not None:
        app.state.sessionmaker = preexisting
```

### The Neon restore drill (D-02)

```bash
# The Neon CLI is NOT installed on this machine -- use npx (verified available, 11.6.1).
export NEON_API_KEY=...                     # never committed
NEON="npx --yes neonctl@latest"

$NEON projects list
$NEON branches list --project-id "$PROJECT_ID"

# A NON-DESTRUCTIVE fresh branch from a past point. Must be inside the Free plan's
# 6-hour history window, RFC 3339, and the parent must be a ROOT branch.
$NEON branches create --project-id "$PROJECT_ID" \
      --name restore-drill-2026-09-01 \
      --parent "2026-09-01T04:00:00Z"

$NEON connection-string restore-drill-2026-09-01 --project-id "$PROJECT_ID"

# Compare. Same query on both branches; diff the output.
psql "$PROD_DSN"  -f scripts/verify-restore.sql > /tmp/prod.txt
psql "$DRILL_DSN" -f scripts/verify-restore.sql > /tmp/drill.txt
diff /tmp/prod.txt /tmp/drill.txt

# The drill is not finished until this runs.
$NEON branches delete restore-drill-2026-09-01 --project-id "$PROJECT_ID"
```

## State of the Art

| Old approach | Current approach | When changed | Impact on this phase |
|---|---|---|---|
| MCP `initialize` handshake carries `instructions` | Stateless `server/discover` returns `DiscoverResult(instructions=...)` | spec revision `2026-07-28` | Server-supplied instructions **survive** the statelessness change — see § *Pattern 5*. Any older guidance saying "stateless servers cannot send instructions" is wrong. |
| Rate limiting as a per-route decorator (`slowapi`) | ASGI middleware ahead of routing | — | Required here: the MCP endpoint is inside a mounted sub-app, so there is no FastAPI route object to decorate. |
| `pg_dump` cron as the canonical Postgres backup | WAL/branch-based instant restore (Neon, and the same model at Aurora/AlloyDB) | Neon PITR GA | Restore is a control-plane call in seconds, not a dump replay. But retention is a *plan* attribute, not infinite — 6h on Free. |
| `neon branches restore` as the only PITR path | `neon snapshots create/restore/finalize` added to the CLI | Neon changelog 2026-05-22 / 2026-07-24 | A second valid mechanism; not used here because Free allows only 1 manual snapshot. |
| Mount secrets as env vars with `:latest` | Mount as **volumes** for true hot reload | Long-standing GCP guidance | Google recommends pinning a version when using env vars, or using a volume mount if you want rotation without redeploy. This project uses env vars (D-06d/D-04) — so redeploy is the mechanism, by design, not by accident. |

**Deprecated / outdated for this phase:**
- `respx` / `pytest-httpx` — cannot see `httpx2` traffic. `pytest-httpx2` only.
- `from mcp.server.fastmcp import FastMCP` — removed in SDK v2.
- Any Render-era deploy instruction — superseded 2026-08-27.

## Blueprint §42 Coverage Audit (DEPLOY-03 evidence)

Compiled 2026-09-01 from a name-level inventory of all 548 test functions across 47 files
`[VERIFIED: grep of `^def test_` / `^async def test_`]`. This is the audit DEPLOY-03 asks for, and
it shows the requirement is close to already-satisfied.

| Blueprint §42 item | Covered by | Status |
|---|---|---|
| Hevy: API authentication | `test_hevy_client.py::test_auth_error_is_not_retried`, `::test_workouts_request_sends_key_header_and_page_size`, `::test_build_hevy_client_requires_the_env_var` | ✅ |
| Hevy: pagination | `test_hevy_sync.py::test_full_sync_paginates_across_two_pages`; `test_hevy_client.py::test_page_size_constants_match_the_live_caps` | ✅ |
| Hevy: incremental events | `test_hevy_events.py` (17 tests: frozen cursor, oldest-first apply, cursor advance/non-advance, overlap margin) | ✅ |
| Hevy: duplicate prevention | `test_hevy_sync.py::test_sync_is_idempotent_across_three_runs`; `test_hevy_end_to_end.py::test_full_sync_is_idempotent_end_to_end` | ✅ |
| Hevy: deleted workouts | `test_hevy_sync.py::test_delete_workout_cascades_and_leaves_siblings`; `test_hevy_events.py::test_deleted_event_removes_workout_and_children_leaving_siblings` | ✅ |
| Hevy: API failures | `test_hevy_resilience.py` (7 tests: page-2 failure, checkpoint resume, quarantine); `test_hevy_client.py` retry/exhaustion tests | ✅ |
| Hevy: rate limiting | `test_hevy_client.py::test_rate_limit_is_retried_then_succeeds`, `::test_rate_limit_headers_are_logged` | ⚠️ Covered against a *mocked* 429. STATE.md records the open concern that Hevy's real limits were never observed. No further work possible this phase. |
| Analytics: weekly volume / muscle volume / PRs / progression / plateau / weight trends / period comparison | `test_analytics_volume.py` (21), `_rollup` (17), `_records` (9), `_progression` (41), `_bodyweight` (14), `_comparison` (11), `_frequency` (12), `_recomposition` (20), `_metadata` (19), all against `golden_workout` fixtures | ✅ 7/7 |
| MCP: tool discovery | `test_mcp_tool_schemas.py::test_tool_registry_is_exactly_the_thirteen` | ✅ |
| MCP: tool schemas | `test_mcp_tool_schemas.py` (9 tests incl. `test_decorated_tools_still_publish_schemas`, `test_no_tool_publishes_a_user_id_argument`) | ✅ |
| MCP: authentication | `test_mcp_auth.py` (23 tests: static + AuthKit unit, plus 5 over-HTTP wire-contract tests) | ✅ |
| MCP: correct structured output | `test_mcp_tools.py` (21), `test_mcp_schemas.py` (7), `test_mcp_tool_budget.py` (6) | ✅ |
| MCP: unauthorized access | `test_mcp_auth.py::test_rejects_unauthenticated`, `::test_rejects_bad_token`, `::test_401_leaks_nothing` | ✅ |
| MCP: malformed parameters | `test_mcp_tool_schemas.py::test_a_request_above_the_cap_is_rejected_before_the_body_runs` | ⚠️ **Gap.** Only the over-cap case. Wrong-type and missing-required-argument are not asserted. One small test closes it. |
| **§43 full-chain integration test** | — | ❌ **The gap.** `test_hevy_end_to_end.py` stops at Postgres; zero `mcp` references in the file. |

**Net DEPLOY-03 work:** one composition test module, one malformed-parameter test, plus the new
rate-limiter tests. Not a test-suite build.

## Assumptions Log

| # | Claim | Section | Risk if wrong |
|---|---|---|---|
| A1 | `roles/secretmanager.secretAccessor` is bound at the *secret* level for `brett-run@`, so a new version is readable without an IAM change | Pattern 4 | Step 2 of the rotation deploys a revision that cannot start; recovers by granting the role, but the drill fails confusingly. **Confirm with `gcloud secrets get-iam-policy brett-mcp-auth-secret` before running the rotation.** |
| A2 | The Neon project is on the **Free** plan (deploy log says CIMD/DCR "nothing was paid-gated" and notes Free-plan autosuspend) | Pattern 3 | If it is on Launch/Scale the history window is 7/30 days and the drill is easier, not harder — a favourable direction. Confirm with `neon projects get`. |
| A3 | The Claude connector's WorkOS consent survives a redeploy, because `MCP_RESOURCE_URL` and the issuer are unchanged | Pitfall 1 / D-09 | If re-consent is needed, D-09's UAT gains a step. Low impact, easy to observe. |
| A4 | Claude's connector does **not** currently inject `DiscoverResult.instructions` into its system prompt | Pattern 5 | If it does, the optional `instructions=` addition is more valuable than described. Observable for free during D-09. |
| A5 | Cloud Run's `X-Forwarded-For` places the real client first, per the Cloud Functions header reference (Cloud Run shares the ingress path) | Pitfall 3 | If it is last-position instead, the *advisory* key is wrong — but the recommended global bucket is unaffected, which is why the recommendation is structured that way. |
| A6 | Normal coaching conversations issue well under ~30 tool calls/minute | Pattern 1 | Too tight a limit throttles a legitimate turn. D-09's UAT is the natural place to measure it; treat any 429 there as a tuning bug. |

## Open Questions

1. **Does Hevy sync scheduling belong to this phase?**
   - What we know: `README.md` states verbatim "**Production scheduling is Phase 7** — nothing here
     runs the sync on a timer." Blueprint §38 wants a sync every 1–6h. CLAUDE.md's deployment table
     (Render-era, but the reasoning is host-independent) says an in-process scheduler is wrong and a
     platform cron job is right — on Cloud Run that is Cloud Scheduler → an authenticated HTTP
     trigger, or a Cloud Run **Job**.
   - What's unclear: neither ROADMAP Phase 7's four success criteria, nor REQUIREMENTS.md
     (DEPLOY-03/COACH-01), nor `07-CONTEXT.md` mentions scheduling at all. It is not in any phase's
     requirement set, and it is not in the deferred list.
   - Why it matters: without it, "the deployed connector works against **real** data" (the phase
     goal) degrades every day the user does not run `python -m app.cli sync-hevy` by hand — and
     D-09's staleness test would then pass for an accidental reason.
   - Recommendation: **surface to the user before planning.** Either (a) fold a minimal Cloud
     Scheduler task into this phase, (b) record it explicitly as deferred to v1.x so the README's
     claim stops being wrong, or (c) accept manual sync and correct the README line. Do not let the
     planner silently pick one.

2. **What rate-limit numbers?**
   - What we know: one user, one connector, `--max=2` instances, all traffic from a /21. A single
     coaching turn can fan out to several tool calls; `fitness_get_training_summary` exists
     precisely to reduce that fan-out.
   - What's unclear: the real per-turn call count. Nobody has watched Claude use these 13 tools yet.
   - Recommendation: start deliberately generous — capacity ~30, refill ~30/min (i.e. 30 burst,
     30/min sustained) — make both `Settings` fields so they are tunable without a code change, and
     record the observed per-turn call count during D-09's UAT as the evidence for any later
     tightening.

3. **Should the phase spend its one Neon manual snapshot?**
   - What we know: Free allows exactly 1. The branch-from-timestamp drill does not need it.
   - Recommendation: **no.** Keep the snapshot slot free for a real "before a risky migration"
     moment. Document in the runbook that it exists and is unspent.

4. **Do the three over-budget tools from Phase 6 (`deferred-items.md` D-06-10-A) get retuned here?**
   - What we know: `fitness_compare_periods` measures 59.6 KB (~20K tokens) at full cap; the
     deferred note explicitly says the tuning judgement "wants real Claude transcripts rather than a
     byte count".
   - Recommendation: D-09's UAT **is** the first real transcript. Record token/latency observations
     there, but do not retune in this phase unless the UAT actually shows a problem — retuning
     changes shipped tool behaviour and is out of this phase's boundary
     ("Explicitly NOT this phase: ... new MCP tools").

## Environment Availability

| Dependency | Required by | Available | Version | Fallback |
|---|---|---|---|---|
| `gcloud` | Redeploy, secret rotation, revision inspection | ✓ | 578.0.0 | — |
| Docker | Postgres testcontainer for the composition test | ✓ | 29.4.2 (client) | — (integration suite cannot run without it) |
| `uv` | Dependency sync, test running | ✓ | 0.12.1 | — |
| `psql` | Row-count/digest comparison in the D-02 drill | ✓ | 18.6 | Neon SQL Editor in the Console |
| `npx` | Running the Neon CLI without installing it | ✓ | 11.6.1 | — |
| **Neon CLI (`neon`/`neonctl`)** | D-02 branch create/list/delete | **✗** | — | `npx --yes neonctl@latest ...`, or the Neon REST API via `curl` with `$NEON_API_KEY`, or the Neon Console UI |
| `claude` CLI | Optional static-bearer smoke test during rotation (`claude mcp add --header`) | ✓ | 2.1.251 | `curl` with the `test_mcp_auth.py` envelope |
| Claude Desktop/Web with a Pro/Max plan | D-09 coaching UAT (connector + Project) | ? | — | **None.** Remote connectors require Pro/Max/Team/Enterprise. Phase 2 already proved a connector round-trip on this account, so this is expected to hold. |
| `NEON_API_KEY` | Neon CLI/API auth | ? | — | Neon Console UI (fully sufficient for the drill, just not scriptable) |
| `BRETT_GCP_PROJECT` env / gcloud auth | Deploy script | ? | — | Named in the script's `:?` guard; the developer must export it |

**Missing dependencies with no fallback:** none.

**Missing dependencies with fallback:**
- Neon CLI — use `npx --yes neonctl@latest`. The plan should *not* add a global install step; `npx`
  keeps the drill reproducible without changing the developer machine.

## Validation Architecture

### Test Framework

| Property | Value |
|---|---|
| Framework | pytest 9.1.1 + pytest-asyncio 1.4.0 (`asyncio_mode = "auto"`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths = ["backend/tests"]`, `pythonpath = ["backend"]`, marker `integration`) |
| Quick run command | `uv run pytest backend/tests -x -q -m "not integration"` |
| Full suite command | `uv run pytest backend/tests -q --cov=backend/app` |
| Baseline | 650 passed as of Phase 6 verification `[VERIFIED: 06-VERIFICATION.md behavioral spot-checks]` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test type | Automated command | File exists? |
|---|---|---|---|---|
| DEPLOY-03 | Mock-Hevy → sync → Postgres → analytics → MCP tool returns the hand-computed answer | integration | `uv run pytest backend/tests/test_full_chain_end_to_end.py -x -m integration` | ❌ Wave 0 |
| DEPLOY-03 | The chain's analytics value and MCP value are the **same** number | integration | `uv run pytest backend/tests/test_full_chain_end_to_end.py -k same_answer -x` | ❌ Wave 0 |
| DEPLOY-03 | A tool call with a wrong-typed argument is rejected before the body runs | unit (fast) | `uv run pytest backend/tests/test_mcp_tool_schemas.py -k malformed -x` | ❌ extend existing file |
| DEPLOY-03 | A tool call missing a required argument is rejected before the body runs | unit (fast) | `uv run pytest backend/tests/test_mcp_tool_schemas.py -k missing_required -x` | ❌ extend existing file |
| DEPLOY-03 | Blueprint §42's Hevy / analytics / MCP checklists stay green | full suite | `uv run pytest backend/tests -q` | ✅ (650 passing) |
| ROADMAP-2 | An over-limit request receives 429 | integration | `uv run pytest backend/tests/test_rate_limit.py -k over_limit -x` | ❌ Wave 0 |
| ROADMAP-2 | The 429 body's key set is exactly `{"error"}` and leaks no token/DSN/traceback | integration | `uv run pytest backend/tests/test_rate_limit.py -k leaks_nothing -x` | ❌ Wave 0 |
| ROADMAP-2 | The 429 carries a `Retry-After` header | integration | `uv run pytest backend/tests/test_rate_limit.py -k retry_after -x` | ❌ Wave 0 |
| ROADMAP-2 | The limiter runs **ahead of auth** — an unauthenticated flood is 429'd, not 401'd | integration | `uv run pytest backend/tests/test_rate_limit.py -k before_auth -x` | ❌ Wave 0 |
| ROADMAP-2 | `/health` is never rate-limited | integration | `uv run pytest backend/tests/test_rate_limit.py -k health -x` | ❌ Wave 0 |
| ROADMAP-2 | `/.well-known/oauth-protected-resource/mcp` is never rate-limited | integration | `uv run pytest backend/tests/test_rate_limit.py -k discovery -x` | ❌ Wave 0 |
| ROADMAP-2 | The bucket refills at the configured rate (fake clock, no sleeping) | unit (fast) | `uv run pytest backend/tests/test_rate_limit.py -k refill -x` | ❌ Wave 0 |
| ROADMAP-2 | New `RATE_LIMIT_*` settings stay in sync with `deploy/cloud-run.env.yaml` | unit (fast) | `uv run pytest backend/tests/test_cloud_run_deploy.py -x` | ✅ existing guard covers it automatically |
| ROADMAP-2 | Unauthenticated `/mcp` is still 401 with `resource_metadata=` after the limiter is added | integration | `uv run pytest backend/tests/test_mcp_auth.py -x -m integration` | ✅ regression |
| ROADMAP-2 | The deployed revision serves 13 tools | **manual** | `curl` the live `/mcp` with a valid credential and the `test_mcp_auth.py` envelope; record in the deploy record | manual-only — requires the live service |
| ROADMAP-3 | A Neon branch from a past timestamp matches production row-for-row | **manual** | § *Pattern 3*'s `psql` digest diff | manual-only by D-02 (needs live Neon API access) |
| ROADMAP-3 | `MCP_AUTH_SECRET` rotates without breaking the connector | **manual** | § *Pattern 4*'s five-step runbook | manual-only by D-04 (needs live Cloud Run + Secret Manager) |
| COACH-01 | `docs/coaching-instructions.md` exists and names only real tools | unit (fast) | `uv run pytest backend/tests/test_coaching_doc.py -x` — parse the doc, assert every `fitness_*` token it mentions is in the live registry, and that all 12 non-ping tools appear | ❌ Wave 0 *(recommended: this is the one part of COACH-01 that is automatable, and it stops the doc rotting the next time a tool is renamed)* |
| COACH-01 | Claude answers both criterion questions from real data and flags staleness | **manual** | § *Pattern 5*'s D-09 UAT script | manual-only by D-09 |

### Sampling Rate

- **Per task commit:** `uv run pytest backend/tests -x -q -m "not integration"` — the bucket refill
  tests, the malformed-parameter tests, the coaching-doc tool-name test and the
  `test_cloud_run_deploy.py` drift guard are all container-free, so the fastest loop covers most of
  the phase.
- **Per wave merge:** `uv run pytest backend/tests -q --cov=backend/app`
- **Phase gate:** full suite green **plus** three signed-off manual records (deploy, restore drill,
  rotation) **plus** the D-09 UAT record, before `/gsd-verify-work`.

### Wave 0 Gaps

- [ ] `backend/app/middleware.py` (or `app/middleware/rate_limit.py`) — the limiter itself
- [ ] `backend/tests/test_rate_limit.py` — covers ROADMAP criterion #2
- [ ] `backend/tests/test_full_chain_end_to_end.py` — covers DEPLOY-03 / blueprint §43
- [ ] `backend/tests/test_coaching_doc.py` — covers the automatable half of COACH-01
- [ ] Two new `Settings` fields (`rate_limit_per_minute`, `rate_limit_burst`) + matching keys in
      `deploy/cloud-run.env.yaml` if overridden — **read `test_cloud_run_deploy.py` first**, it
      cross-checks both directions
- [ ] Extensions to `backend/tests/test_mcp_tool_schemas.py` — malformed / missing-required params
- No framework install needed; every tool is already pinned.

## Security Domain

### Applicable ASVS Categories

| ASVS category | Applies | Standard control in this phase |
|---|---|---|
| V2 Authentication | yes | Unchanged mechanism (WorkOS AuthKit OAuth 2.1 / `StaticTokenVerifier` rollback). This phase only *rotates* the static credential and *exercises* the rollback path. No new verifier, no new algorithm allowlist. |
| V3 Session Management | no | The 2026-07-28 transport is stateless; there are no protocol-level sessions to manage. |
| V4 Access Control | yes | Unchanged: single user, `DEFAULT_USER_ID`, every query scoped. The composition test must not introduce an unscoped query. `test_analytics_isolation.py` / `test_mcp_isolation.py` remain the guards. |
| V5 Input Validation | yes | The malformed-parameter tests are new V5 coverage. The rate limiter parses `X-Forwarded-For` — a fully attacker-controlled header — so its parser must not index blindly, must cap the length it reads, and must never place the raw value in a log line without treating it as untrusted. |
| V6 Cryptography | yes | `secrets.token_urlsafe(48)` for the new secret; `secrets.compare_digest` for comparison (already built). Nothing hand-rolled. |
| V7 Error Handling & Logging | yes | The 429 body and its log line are the only new output channels. Both must go through the existing structlog redaction chain and the exact-key-set assertion discipline. |
| V8 Data Protection | yes | The restore drill copies **real health data** to a new branch with a new connection string. The runbook must require deleting the drill branch, and must never paste a DSN into a committed document. |
| V11 Business Logic / Anti-automation | yes | This is what the rate limiter *is*. See § *Pattern 1*. |
| V14 Configuration | yes | The rotation runbook temporarily sets `MCP_AUTH_MODE=static`, which is a **weaker** configuration. The runbook must make the flip-back a mandatory, verified step, not a trailing note. |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard mitigation | State in this phase |
|---|---|---|---|
| Credential echoed in a rejection body | Information Disclosure | Exact-key-set assertion on the response JSON | Exists for 401 (`test_401_leaks_nothing`); **must be replicated for 429** |
| DSN / traceback leaking through a tool result | Information Disclosure | `@safe_tool` + parametrized leak test | Already shipped; the composition test must not bypass `@safe_tool` |
| Rate-limit evasion via forged `X-Forwarded-For` | Tampering / DoS | Global bucket as the enforceable control; per-key bucket advisory only | § *Pitfall 3* |
| 429 storm amplification (client retries immediately) | DoS | Generous limits + `Retry-After` + measure during UAT | § *Pitfall 9* |
| Limiter throttling the health probe or discovery document | DoS (self-inflicted) | Explicit path exemptions, asserted by test | § *Pitfall 7* |
| Left in the weaker `static` auth mode after a rotation | Elevation of Privilege | Mandatory verified flip-back; assert the final revision's env | § *Pitfall 2*, V14 |
| Real health data left on an undeleted drill branch | Information Disclosure | Mandatory `neon branches delete` step | § *Pattern 3* |
| Secret destroyed before rollback is possible | Denial of Service | `gcloud secrets versions disable`, never `destroy` | § *Pattern 4* step 5 |
| Startup migrations racing across revisions | Tampering / data corruption | Migrations run out-of-band; never at app startup | Already enforced (`main.py` lifespan docstring); the redeploy must not change it |

## Sources

### Primary (HIGH confidence — verified in this session)

- **This repository, read directly:** `backend/app/main.py`, `backend/app/mcp/server.py`,
  `backend/app/mcp/auth.py`, `backend/app/mcp/context.py`, `backend/app/mcp/tools/_common.py`,
  `backend/app/config.py`, `backend/app/api/routes/health.py`, `backend/app/analytics/schemas.py`,
  `backend/tests/conftest.py`, `backend/tests/test_hevy_end_to_end.py`,
  `backend/tests/test_mcp_auth.py`, `backend/tests/test_mcp_mount.py`,
  `backend/tests/test_mcp_tools.py`, `backend/tests/test_cloud_run_deploy.py`,
  `scripts/deploy-cloud-run.sh`, `deploy/cloud-run.env.yaml`, `Procfile`, `pyproject.toml`,
  `README.md`
- **Installed SDK source read:** `mcp/server/mcpserver/server.py` (constructor params incl.
  `instructions` and `middleware`; `streamable_http_app` delegation), `mcp/server/context.py`
  (the `ServerMiddleware` protocol and its ordering guarantees),
  `mcp/server/lowlevel/server.py:660-676` (`_handle_discover` returns
  `DiscoverResult(instructions=...)`), `mcp_types/_v2026_07_28/__init__.py:3165`
  (`instructions` field docstring)
- **Live introspection:** `app.mcp.server.mcp.list_tools()` → the exact 13 tool names, parameter
  names and required sets used in the D-06 mapping table
- **Live version check:** `importlib.metadata.version` for `mcp`, `mcp-types`, `starlette`,
  `fastapi`, `httpx2`, `pydantic`
- **Empirical:** `time_machine.travel()` does not patch `time.monotonic()` (§ *Pitfall 4*) —
  reproduced twice with a delta of 9.4 µs
- **Environment probes:** `gcloud --version` (578.0.0), `docker --version` (29.4.2),
  `uv --version` (0.12.1), `psql --version` (18.6), `npx --version` (11.6.1),
  `claude --version` (2.1.251), `command -v neon`/`neonctl` (both absent)
- **Test inventory:** `grep`-derived counts of all 548 test functions across 47 files, and full
  name listings for `test_hevy_client`, `test_hevy_resilience`, `test_hevy_sync`,
  `test_hevy_events`, `test_mcp_tool_schemas` — the basis of the § *Blueprint §42 Coverage Audit*
- **Planning artifacts:** `.planning/phases/07-.../07-CONTEXT.md`, `.planning/REQUIREMENTS.md`,
  `.planning/ROADMAP.md`, `.planning/PROJECT.md`, `.planning/STATE.md`,
  `.planning/phases/06-mcp-tools/06-VERIFICATION.md`,
  `.planning/phases/06-mcp-tools/deferred-items.md`,
  `.planning/phases/02-deploy-connector-auth-spike/02-DEPLOY-LOG.md`,
  `BRETT blueprint.md` §34-36, §42-44
- **git:** `git log --oneline -30` — no deploy commit since Phase 2

### Secondary (MEDIUM confidence — official documentation, not exercised against this project)

- Neon — [Instant restore](https://neon.tech/docs/guides/branching-pitr) (in-place overwrite
  semantics, `branches restore` syntax, root-branch-only constraint)
- Neon — [CLI branches reference](https://neon.com/docs/reference/cli-branches)
  (`branches create --parent <timestamp>`, `list`, `delete`, `connection-string`)
- Neon — [Plans](https://neon.com/docs/introduction/plans) (Free: 6h history / 1 GB, 1 manual
  snapshot, 10 branches/project, 0.5 GB storage)
- Neon — [Announcing Point-in-Time Restore](https://neon.com/blog/announcing-point-in-time-restore)
- Google Cloud — [Configure secrets for services](https://docs.cloud.google.com/run/docs/configuring/services/secrets)
  (env-var secrets resolve at instance start; `latest` requires a new revision)
- Google Cloud — [Request headers reference](https://docs.cloud.google.com/functions/docs/reference/headers)
  (`X-Forwarded-For: clientIp, proxy1Ip, proxy2Ip`)
- Uvicorn — [Settings](https://uvicorn.dev/settings/) (`--forwarded-allow-ips` defaults to
  `127.0.0.1`; `--proxy-headers` only trusts listed peers)
- Starlette — [Middleware](https://www.starlette.io/middleware/) (app-level middleware is outermost
  and wraps routing; `Mount` middleware is scoped and skips exception handling)
- Anthropic — [Connector authentication](https://claude.com/docs/connectors/building/authentication)
  (10s discovery timeout, `160.79.104.0/21` egress) *(recorded in CLAUDE.md from Phase 2 research)*

### Tertiary (LOW confidence — single source or community, flagged for validation)

- [Zuplo — Never ship an MCP server without a rate limit](https://zuplo.com/blog/never-ship-mcp-server-without-rate-limit)
  — the claim that the MCP spec defines no 429 semantics and that clients "do something arbitrary".
  Vendor-authored. The *negative* claim (no 429 convention in the spec) is consistent with the
  2026-07-28 transport text but was not independently confirmed against the spec document itself.
- Neon changelog coverage of the `neon snapshots` CLI group (2026-05-22 / 2026-07-24) — via search
  result summaries, not the changelog pages themselves.
- Claude Project custom-instruction length limits — search results give ~8,000 characters but note
  Anthropic does not publish a figure. Treated as "keep the document tight", not as a hard bound.
- Whether Claude injects MCP `DiscoverResult.instructions` into its system prompt — general MCP
  ecosystem reporting says "major MCP clients have chosen the path to inject server instructions";
  **no Anthropic source found**. Logged as A4.

## Metadata

**Confidence breakdown:**

- Existing repo state and test inventory: **HIGH** — read directly, counted directly, introspected
  the live server object
- SDK capabilities (`instructions`, `middleware`, discover delivery): **HIGH** — source read of the
  installed 2.0.0 package
- Rate-limiter seam and ordering: **HIGH** for the mechanism (Starlette semantics + the SDK's own
  middleware construction, both read); **MEDIUM** for the recommended limit numbers (A6)
- Neon mechanics: **MEDIUM** — official docs, current, but not yet run against this project's
  Neon instance; plan tier is assumed (A2)
- Cloud Run secret resolution: **MEDIUM-HIGH** — official docs, and consistent with how
  `--set-secrets` is already wired here
- Client IP under Cloud Run: **MEDIUM** — GCP docs are clear, but a community source disagreed on
  first-vs-last position (A5); the recommendation is deliberately structured not to depend on it
- Claude connector 429 behaviour and `instructions` injection: **LOW** — no authoritative source
  found; both are observable during D-09's UAT at no extra cost

**Research date:** 2026-09-01
**Valid until:** 2026-10-01 for the repo-state and SDK findings (they change only when this repo
changes). **2026-09-15** for the Neon plan limits and Cloud Run secret semantics — both are
provider policy and Neon in particular shipped two relevant CLI changes in the last four months.
