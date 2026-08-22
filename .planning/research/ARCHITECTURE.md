# Architecture Research

**Domain:** External-API sync → normalized relational store → deterministic analytics → remote MCP server for an LLM
**Researched:** 2026-08-23
**Confidence:** HIGH (MCP SDK, Hevy API contract, Render constraints verified against primary sources) / MEDIUM (sync-vs-async and scheduler recommendations are opinionated engineering judgement, not externally documented consensus)

---

## Executive Answer (read this first)

Systems in this shape are almost always built as a **single deployable "shared core" service with thin adapters**, not as a distributed pipeline. The recurring structure is:

```
provider client → anti-corruption mapper → idempotent upsert sync → normalized DB
                                                                        ↓
                                                        repositories (I/O)
                                                                        ↓
                                                    pure analytics functions (no I/O)
                                                                        ↓
                                                        service layer (DTOs)
                                                          ↙                  ↘
                                              REST routers            MCP tool handlers
```

The two things that go wrong most often in this architecture are (a) calculation logic leaking into MCP tool handlers, and (b) provider payload shapes leaking past the integration boundary. Both are structural, not stylistic — both cause rewrites.

**For BRETT specifically: run one FastAPI ASGI app, one Render Web Service, with the MCP server mounted at `/mcp`.** Rationale and tradeoffs in "The Deployment Topology Question" below.

The blueprint's §37 guidance ("MCP should call internal service functions rather than HTTP back into the same app") is **correct and validated** — that is the standard pattern, and it is what makes the single-service topology work.

---

## Standard Architecture

### System Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│  EXTERNAL SOURCES                                                         │
│  ┌────────────────────┐         ┌───────────────────────────┐            │
│  │ Hevy REST API      │         │ iOS / HealthKit (M2)      │            │
│  │ api.hevyapp.com/v1 │         │ push → /api/v1/healthkit  │            │
│  └─────────┬──────────┘         └────────────┬──────────────┘            │
└────────────┼─────────────────────────────────┼───────────────────────────┘
             │ pull (scheduled)                │ push (device-initiated)
┌────────────▼─────────────────────────────────▼───────────────────────────┐
│  INTEGRATION LAYER  (app/integrations/) — anti-corruption boundary        │
│  ┌──────────┐  ┌───────────┐  ┌──────────┐  ┌──────────────────────┐     │
│  │ client   │→ │ schemas   │→ │ mapper   │→ │ sync (orchestration) │     │
│  │ (HTTP,   │  │ (provider │  │ (DTO →   │  │ cursor, upsert,      │     │
│  │  retry)  │  │  DTOs)    │  │  domain) │  │ deletes, txn scope   │     │
│  └──────────┘  └───────────┘  └──────────┘  └──────────┬───────────┘     │
│  ── nothing above this line is importable from below ──┼─────────────    │
└────────────────────────────────────────────────────────┼──────────────────┘
                                                         ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  PERSISTENCE  (app/db/)                                                   │
│  ┌────────────────┐  ┌─────────────────┐  ┌──────────────────────────┐   │
│  │ models/ (ORM)  │  │ repositories/   │  │ Alembic migrations       │   │
│  └────────┬───────┘  └────────┬────────┘  └──────────────────────────┘   │
│           └───────────────────┴───► PostgreSQL (source of truth)         │
└──────────────────────────────────┬───────────────────────────────────────┘
                                   │ rows in
┌──────────────────────────────────▼───────────────────────────────────────┐
│  ANALYTICS  (app/analytics/) — PURE, deterministic, zero I/O              │
│  volume · muscle_volume · progression · plateau · prs · frequency ·       │
│  trends · recomposition            (inputs: rows + config + `now`)        │
└──────────────────────────────────┬───────────────────────────────────────┘
                                   │ domain results
┌──────────────────────────────────▼───────────────────────────────────────┐
│  SERVICE LAYER  (app/services/) — the ONLY thing adapters call            │
│  fetch via repositories → call analytics → return Pydantic DTOs           │
└──────────┬──────────────────────────────────────────┬────────────────────┘
           │                                          │
┌──────────▼──────────────────┐         ┌─────────────▼────────────────────┐
│  REST ADAPTER (app/api/)    │         │  MCP ADAPTER (app/mcp/)          │
│  FastAPI routers            │         │  MCPServer + read-only tools     │
│  /healthz /api/v1/*         │         │  mounted at /mcp                 │
│  auth: JWT / internal token │         │  auth: TokenVerifier (bearer)    │
└──────────┬──────────────────┘         └─────────────┬────────────────────┘
           │                                          │ Streamable HTTP
           ▼                                          ▼
    iOS app (M2), curl, cron                   Claude Desktop / Web / Mobile
```

Everything inside the boxes runs in **one Python process** on Render. The layer boundaries are import-direction rules enforced by convention (and optionally by an import-linter rule in CI), not process boundaries.

### Component Responsibilities

| Component | Owns | Must NOT do | Typical implementation |
|-----------|------|-------------|------------------------|
| `integrations/hevy/client.py` | HTTP mechanics: `api-key` header, pagination loop, 429/5xx backoff, timeouts, correlation logging | Touch the DB, know about domain models | `httpx2.Client` wrapper, no ORM imports |
| `integrations/hevy/schemas.py` | Pydantic models mirroring Hevy payloads *exactly* | Be used outside `integrations/hevy/` | Field names match Hevy JSON (`weight_kg`, `exercise_template_id`) |
| `integrations/hevy/mapper.py` | Hevy DTO → internal domain/ORM shape; unit + timezone normalization | Perform I/O | Pure functions, individually unit-testable |
| `integrations/hevy/sync.py` | Sync orchestration: full vs incremental, cursor, transaction scope, delete handling, idempotency | Contain analytics; contain raw HTTP | Service class taking `(client, session, user_id)` |
| `db/models/` | Table definitions, constraints, indexes | Contain business logic | SQLAlchemy 2.x `DeclarativeBase` + `Mapped[]` |
| `db/repositories/` | Query composition, the *only* place SQL/ORM queries live | Compute metrics | Functions returning row DTOs, not ORM objects, to callers above |
| `analytics/` | Deterministic metric computation | Any I/O, any `datetime.now()`, any DB session | Pure functions over row sequences + injected `now`/config |
| `services/` | Compose repository reads + analytics; own the response DTOs | Know about HTTP or MCP | Plain functions/classes returning Pydantic models |
| `api/routes/` | HTTP contract, request validation, HTTP auth, status codes | Compute anything | Thin FastAPI routers |
| `mcp/tools/` | Tool name/description/param schema, argument coercion, response shaping/truncation | Compute anything | Thin `@mcp.tool()` functions calling `services/` |
| `core/` | Settings, logging, security, time/timezone helpers, units | Import from any layer above it | `pydantic-settings`, structlog |
| `scheduler.py` | Trigger `HevySyncService` on a cadence | Contain sync logic | APScheduler in the app lifespan (see below) |

---

## The Deployment Topology Question

**Recommendation: one FastAPI app, one Render Web Service, MCP mounted at `/mcp`. HIGH confidence.**

### Options considered

| Option | Description | Verdict |
|--------|-------------|---------|
| **A. Mounted (recommended)** | `MCPServer` ASGI sub-app mounted into the FastAPI app; one Render Web Service | **Choose this** |
| B. Two Render Web Services, shared repo | `fitness-api` and `fitness-mcp` deployed from the same codebase, different start commands, same DB | Defer. Valid escape hatch; costs 2× and buys nothing at this scale |
| C. Two services, MCP calls API over HTTP | MCP service does HTTP requests back into the API service | **Reject.** Explicitly warned against by blueprint §37 |
| D. MCP-only service, no REST API | Skip FastAPI entirely | Reject — you still need `/healthz`, manual-entry endpoints, and a sync trigger |

### Why A

1. **Cost.** Render Web Service Starter is $7/mo each; two services doubles it, plus you need a paid Postgres regardless (see gotcha below). For a personal project, $7 vs $14 for zero benefit.
2. **They share everything that matters.** Both adapters need the same settings, the same DB engine/pool, and the same service layer. Splitting them duplicates process overhead and connection pools against a small Postgres instance while sharing 95% of the code.
3. **MCP 2.0 is stateless, so there's no session-affinity argument for isolation.** The 2026-07-28 spec revision removed the `initialize` handshake and protocol-level session IDs — "every request is self-describing… any server instance can handle any request." Historically, one reason to isolate an MCP server was sticky-session management. That reason is gone.
4. **The blueprint already sanctions it** (§45: "They may initially run in one application/service if that simplifies deployment").
5. **Extraction stays cheap.** Because `app/mcp/` only calls `app/services/`, splitting later is a new start command + `render.yaml` entry, not a refactor. Design for the split; don't pay for it yet.

### Honest tradeoffs of A

| Tradeoff | Impact here | Mitigation |
|----------|-------------|------------|
| Shared blast radius — a bad MCP tool can hang/OOM the REST API | Low (single user) | Per-tool result caps; DB statement timeout; separate rate-limit buckets for `/mcp` vs `/api` |
| Can't scale MCP independently of API | Nil at this scale | — |
| Larger attack surface on one origin | Real | Distinct auth middleware per mount path; MCP path has *no* write tools; never mount admin routes |
| Lifespan coupling — MCP session manager failure kills app startup | Real | Fail loudly at boot; `/healthz` is a plain FastAPI route so Render's health check is independent of MCP internals |

### Four mounting gotchas that will bite you (all verified against the SDK source/docs)

1. **A mounted sub-app's lifespan never runs.** Starlette does not run nested lifespans under `Mount`. The *host* app's lifespan must enter `mcp.session_manager.run()` itself, or every MCP request fails with `RuntimeError: Task group is not initialized`. This is the single most common failure mode reported for this pattern.
2. **DNS-rebinding protection defaults to localhost-only.** `TransportSecuritySettings.enable_dns_rebinding_protection` defaults to `True` with an empty `allowed_hosts`; `streamable_http_app()` auto-configures localhost when `transport_security=None`. In production the Render hostname must be in `allowed_hosts` or Claude's requests are rejected on the `Host` header. This is a config value, not a code change — put it in settings.
3. **Route ordering.** `Mount("/", ...)` matches every path. Register your own routes *before* the mount, or use a non-root prefix.
4. **`@mcp.custom_route()` bypasses MCP authentication.** Do not put the health endpoint (or anything else) there. Health lives on the FastAPI side.

### Shape of it

```python
# app/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from starlette.routing import Mount

from app.core.config import settings
from app.mcp.server import build_mcp_server
from app.api.routes import health, sync, metrics, entries
from app.scheduler import start_scheduler, stop_scheduler

mcp = build_mcp_server()          # MCPServer instance + registered tools

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp.session_manager.run():      # REQUIRED — Mount does not run it
        start_scheduler()
        try:
            yield
        finally:
            stop_scheduler()

app = FastAPI(title="BRETT", lifespan=lifespan)
app.include_router(health.router)                      # /healthz  (Render health check)
app.include_router(sync.router,    prefix="/api/v1")
app.include_router(metrics.router, prefix="/api/v1")
app.include_router(entries.router, prefix="/api/v1")   # manual nutrition / measurements

app.router.routes.append(                              # LAST — matches everything under /mcp
    Mount("/mcp", app=mcp.streamable_http_app(
        streamable_http_path="/",                      # endpoint is /mcp itself, not /mcp/mcp
        stateless_http=True,
        transport_security=settings.mcp_transport_security,   # allowed_hosts = [render host]
    ))
)
```

---

## Recommended Project Structure

Flat at the BRETT repo root per the PROJECT.md constraint (no `fitness-platform/` nesting). This refines blueprint §4 by adding the three layers the blueprint implies but doesn't name: `services/`, `domain/`, and `core/`.

```
BRETT/
├── backend/
│   ├── app/
│   │   ├── main.py                    # ASGI app: routers + MCP mount + lifespan
│   │   ├── scheduler.py               # APScheduler trigger for Hevy sync
│   │   │
│   │   ├── core/                      # depends on NOTHING in app/
│   │   │   ├── config.py              # pydantic-settings; all env vars
│   │   │   ├── logging.py             # structured logs + redaction filter
│   │   │   ├── security.py            # token hashing/compare, rate limiting
│   │   │   ├── time.py                # UTC store / Asia-Jakarta local-day grouping
│   │   │   └── units.py               # kg / m / kcal / s / cm boundary conversions
│   │   │
│   │   ├── domain/                    # provider-agnostic vocabulary
│   │   │   ├── muscles.py             # CANONICAL taxonomy (finer than Hevy's — see below)
│   │   │   ├── enums.py               # SetType, Provider, ProgressionStatus, ...
│   │   │   └── config.py              # volume weighting (primary 1.0 / secondary 0.5), thresholds
│   │   │
│   │   ├── db/
│   │   │   ├── session.py             # engine, sessionmaker, get_session dependency
│   │   │   ├── models/                # users, external_connections, sync_state,
│   │   │   │                          # workouts, workout_exercises, sets,
│   │   │   │                          # exercise_templates, muscle_map_overrides,
│   │   │   │                          # body_measurements, daily_nutrition
│   │   │   └── repositories/          # ONLY place ORM queries live
│   │   │       ├── workouts.py
│   │   │       ├── exercises.py
│   │   │       ├── measurements.py
│   │   │       └── sync_state.py
│   │   │
│   │   ├── integrations/
│   │   │   ├── base.py                # Protocol a provider must satisfy (2nd provider later)
│   │   │   └── hevy/                  # ← HARD BOUNDARY. Nothing outside imports these names.
│   │   │       ├── client.py
│   │   │       ├── schemas.py
│   │   │       ├── mapper.py
│   │   │       └── sync.py
│   │   │
│   │   ├── analytics/                 # PURE. No DB session, no clock, no HTTP.
│   │   │   ├── volume.py
│   │   │   ├── muscle_volume.py
│   │   │   ├── progression.py         # incl. estimated 1RM
│   │   │   ├── plateau.py
│   │   │   ├── prs.py
│   │   │   ├── frequency.py
│   │   │   ├── trends.py              # 7/14/30-day rolling averages
│   │   │   └── recomposition.py
│   │   │
│   │   ├── services/                  # repositories + analytics → response DTOs
│   │   │   ├── training.py
│   │   │   ├── body.py
│   │   │   ├── sync.py                # provider-agnostic sync facade
│   │   │   └── freshness.py           # last_synced_at per source
│   │   │
│   │   ├── api/
│   │   │   ├── dependencies.py
│   │   │   └── routes/{health,sync,metrics,entries}.py
│   │   │
│   │   └── mcp/
│   │       ├── server.py              # MCPServer construction, auth, tool registration
│   │       ├── auth.py                # TokenVerifier implementation
│   │       ├── schemas.py             # compact Pydantic response models → output_schema
│   │       └── tools/{training,body,summary}.py
│   │
│   ├── migrations/                    # Alembic
│   ├── tests/{unit,integration,e2e}/
│   ├── pyproject.toml
│   └── Dockerfile
├── docs/{architecture,api,mcp,deployment,coach-prompt}.md
├── render.yaml
├── .env.example
└── README.md
```

### Structure Rationale

- **`services/` is the load-bearing addition.** Without it, MCP tools grow query + calculation logic (blueprint rule #11 violated by default). With it, a tool handler is 5 lines and the same logic backs a REST endpoint and a test.
- **`domain/` exists because Hevy's vocabulary is not yours.** Hevy's `MuscleGroup` enum is `[abdominals, shoulders, biceps, triceps, forearms, quadriceps, hamstrings, calves, glutes, abductors, adductors, lats, upper_back, traps, lower_back, chest, cardio, neck, full_body, other]`. Blueprint §18 requires `front_delts / side_delts / rear_delts` separately. Hevy cannot give you that. The canonical taxonomy must live in `domain/`, seeded from Hevy templates and refined via overrides.
- **`integrations/base.py` is 20 lines and pays for itself.** Defining `SyncProvider` as a Protocol (`full_sync()`, `incremental_sync()`, `cursor_key`) is what actually makes the provider-isolation constraint testable rather than aspirational.
- **`analytics/` separate from `services/`** so analytics can be tested with hand-built fixtures and zero database.
- **`core/time.py` and `core/units.py` are not over-engineering.** The UTC-store / local-day-group split and the kg/m/kcal/s/cm rule are stated project constraints; scattering `tz.localize()` calls across eight analytics modules is exactly how they get violated inconsistently.

---

## Architectural Patterns

### Pattern 1: Anti-Corruption Layer (provider isolation)

**What:** Provider payloads are parsed into provider-specific Pydantic DTOs, then mapped to domain shapes by pure functions. No provider type crosses the boundary.
**When:** Always, when the upstream API is not yours — and Hevy's own docs say *"we make no guarantees that we won't completely change the structure or abandon the project entirely."*
**Trade-offs:** One extra model layer and a mapper to maintain; in exchange, an upstream breaking change is a diff confined to two files, and a second provider is additive.

```python
# integrations/hevy/schemas.py — mirrors Hevy JSON exactly
class HevySet(BaseModel):
    index: int
    type: Literal["normal", "warmup", "dropset", "failure"]
    weight_kg: float | None = None
    reps: int | None = None
    distance_meters: float | None = None
    duration_seconds: float | None = None
    rpe: float | None = None
    custom_metric: float | None = None

# integrations/hevy/mapper.py — pure
def to_set_row(s: HevySet, workout_exercise_id: UUID) -> SetRow:
    return SetRow(
        workout_exercise_id=workout_exercise_id,
        set_index=s.index,
        set_type=SetType(s.type),          # domain enum
        weight_kg=s.weight_kg,             # already kg — no conversion needed for Hevy
        reps=s.reps,
        distance_m=s.distance_meters,
        duration_s=s.duration_seconds,
        rpe=s.rpe,
    )
```

**Boundary test worth writing:** a CI check asserting no module outside `app/integrations/hevy/` imports `app.integrations.hevy.schemas`. That single test is what keeps the constraint real.

### Pattern 2: Cursor + Event-Replay Idempotent Sync

**What:** Two distinct paths sharing one upsert core.
- *Full sync*: page `GET /v1/workouts?page=N&pageSize=10` (max 10 — confirmed) until `page == page_count`.
- *Incremental*: `GET /v1/workouts/events?since=<cursor>&page=N&pageSize=10`, which returns discriminated events: `{type: "updated", workout: {...}}` (full workout body — no second fetch needed) or `{type: "deleted", id, deleted_at}`.

**Non-obvious details from the actual API contract:**
- Events are ordered **newest → oldest**. Collect all pages first and apply oldest→newest, *or* apply newest-first with last-write-wins per workout id. Naïvely streaming pages in order and applying them will resurrect a workout that was updated-then-deleted.
- `/v1/workouts/events` is the **only** way to learn about deletions. Full sync alone will silently retain deleted workouts forever.
- Set the new cursor to the timestamp captured **before** the sync started, not the newest event's timestamp. This re-processes a small overlap window on the next run, which is free because the sync is idempotent, and it closes the race where a workout is edited mid-sync.

**Trade-offs:** More state (`sync_state` table) than "refetch everything," but `pageSize` maxes at 10, so refetching a 500-workout history is 50 requests against an API with undocumented rate limits.

```python
def upsert_workout(session, user_id, w: WorkoutRow, exercises, sets):
    # ONE transaction per workout: a mid-sync failure leaves prior workouts intact
    with session.begin_nested():
        wid = session.execute(
            insert(Workout).values(...)
            .on_conflict_do_update(
                index_elements=["user_id", "provider", "external_id"],   # the idempotency key
                set_={...},
            ).returning(Workout.id)
        ).scalar_one()
        # children are fully replaced, never merged — set indexes shift on edit
        session.execute(delete(WorkoutExercise).where(WorkoutExercise.workout_id == wid))
        session.bulk_insert_mappings(...)
```

**Soft-delete rather than hard-delete** on `type: "deleted"` (`deleted_at` column, filtered in repositories). Preserves the audit trail, makes deletion replay idempotent, and prevents a bad event from destroying history.

### Pattern 3: Pure Analytics Functions

**What:** Every analytics function takes rows + config + an explicit `now`, and returns a value. No session, no clock, no network.
**When to use:** Always here — blueprint rule #10 ("deterministic and testable") is unachievable otherwise.
**Trade-offs:** The service layer must load rows first, so you can't push aggregation into SQL as easily. At this data scale (one person, low thousands of sets/year) that's irrelevant; the testability is worth far more.

```python
# analytics/muscle_volume.py — pure
def weekly_muscle_volume(
    sets: Sequence[SetRow],
    muscle_map: Mapping[str, MuscleAssignment],   # from domain/, override-aware
    weights: VolumeWeights,                        # primary=1.0, secondary=0.5 — CONFIG not literal
    tz: ZoneInfo,
    now: datetime,
    weeks: int,
) -> list[WeeklyMuscleVolume]:
    ...
```

Three rules that come straight from the blueprint and directly shape the signatures:
- **`set_type` matters.** Hevy tags sets `normal | warmup | dropset | failure`. "Hard sets" must exclude `warmup`. Counting warmups is the most common silent volume inflation bug in this domain.
- **Direct and indirect sets stay separate in the output**, not pre-summed (§18).
- **Weights are injected config**, so a coaching-methodology change is a config edit, not a code change plus recomputation of stored results.

### Pattern 4: Dual Adapter over a Shared Service Core

**What:** REST routers and MCP tools are both ~5-line translators over `services/`. Neither knows the other exists.
**When to use:** Any time an LLM-facing surface and a machine-facing surface expose the same domain — which is exactly this project.
**Trade-offs:** Feels like indirection for one caller each; it's the thing that makes the single-service deployment safe and the eventual service split a config change.

```python
# services/training.py — the single source of truth
def get_muscle_group_volume(session, user_id: UUID, weeks: int, now: datetime) -> MuscleVolumeReport:
    sets = repositories.workouts.sets_in_window(session, user_id, weeks, now)
    muscle_map = repositories.exercises.effective_muscle_map(session, user_id)
    return MuscleVolumeReport(
        weeks=analytics.muscle_volume.weekly_muscle_volume(sets, muscle_map, cfg.weights, tz, now, weeks),
        data_freshness=services.freshness.for_sources(session, user_id, ["hevy"]),
    )

# mcp/tools/training.py — thin
@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True))
def fitness_get_muscle_group_volume(weeks: int = 8) -> MuscleVolumeReport:
    """Weekly sets/reps per muscle group, split into direct and indirect sets."""
    with get_session() as s:
        return services.training.get_muscle_group_volume(s, current_user_id(), weeks, utcnow())

# api/routes/metrics.py — equally thin, same call
```

### Pattern 5: Typed, Budgeted MCP Responses

**What:** Annotate the tool's return type with a Pydantic model. MCP Python SDK v2 derives `output_schema` from the return annotation, publishes it in `tools/list`, validates the return value before it leaves the server, and emits both `content` (text for the model) and `structured_content` (typed object). Blueprint §30's "return structured JSON" is a one-line annotation, not a serialization chore.

**Two things to add on top:**
- **Response budgets.** Every list-returning tool takes a `limit` with a sane default and a hard cap enforced server-side. MCP responses land in Claude's context window; an unbounded `fitness_get_recent_workouts` is a context-window denial-of-service on yourself.
- **`data_freshness` on every response.** Blueprint §39. Claude cannot reason about staleness it can't see. Make it a shared nested model on every DTO so it can't be forgotten.

```python
class DataFreshness(BaseModel):
    source: str
    last_synced_at: datetime | None
    age_minutes: int | None

class RecentWorkouts(BaseModel):
    workouts: list[WorkoutSummary]     # summaries, NOT full set-by-set payloads
    truncated: bool
    data_freshness: list[DataFreshness]
```

Mark every tool `read_only_hint=True, idempotent_hint=True`. These are *hints*, not enforcement — the actual read-only guarantee is that no write tool exists and, ideally, that the MCP path's DB role is `SELECT`-only.

### Pattern 6 (recommended, MEDIUM confidence): Synchronous SQLAlchemy + threadpooled handlers

**What:** Use sync SQLAlchemy 2.x `Session`, plain `def` FastAPI path functions, and plain `def` MCP tools.
**Why it works here:** MCP SDK v2 runs sync tool functions on a worker thread rather than blocking the event loop; FastAPI runs `def` path operations in a threadpool. Both surfaces therefore tolerate blocking DB calls without an `async` DB stack.
**Trade-offs:** Caps concurrency at the threadpool size — irrelevant for one user on one Render instance. Buys: no greenlet/async-session friction, simpler tests, simpler Alembic, straightforward `httpx2.Client` in the sync job.
**When to revisit:** If the deployment ever becomes multi-user with real concurrency. Migrating is mechanical; starting async is a persistent tax on a solo developer.

---

## Data Flow

### Ingest flow (Hevy → PostgreSQL)

```
scheduler tick (every 1–6h)
      ↓
services.sync.run("hevy", user_id)
      ↓
HevySyncService.incremental()          # or .full() on first run
      ↓
read sync_state.cursor  ──►  started_at = utcnow()
      ↓
HevyClient.iter_workout_events(since=cursor)      # api-key header; pageSize=10; 429 backoff
      ↓
parse → HevyWorkoutEvent DTOs           [ integrations/hevy/schemas.py ]
      ↓
collect all pages, order oldest→newest, dedupe by workout id (last wins)
      ↓
for each event:
   updated → mapper.to_workout_rows() → upsert (user_id, provider, external_id)
                                        children replaced in a nested txn
   deleted → soft-delete by external_id
      ↓
ensure referenced exercise_template_ids exist  →  fetch missing from
   GET /v1/exercise_templates (pageSize max 100) → seed canonical muscle mapping
      ↓
commit; write sync_state.cursor = started_at; write last_sync_at
      ↓
log: started/completed, imported/updated/deleted counts, duration    (never payloads, never keys)
```

### Query flow (Claude question → MCP response)

```
User in Claude: "Which muscles are undertrained?"
      ↓
Claude selects fitness_get_muscle_group_volume(weeks=8)
      ↓
POST https://<render-host>/mcp        (Anthropic egress 160.79.104.0/21)
Headers: Authorization: Bearer <MCP_AUTH_SECRET>
      ↓
Starlette route match → mounted MCPServer ASGI app
      ↓
TransportSecurityMiddleware   → Host header ∈ allowed_hosts?   else reject
BearerAuthBackend             → TokenVerifier.verify_token()   else 401 + WWW-Authenticate
      ↓
tool dispatch → sync handler runs on worker thread
      ↓
mcp/tools/training.py  →  services.training.get_muscle_group_volume(...)
      ↓
db/repositories/*  ──SELECT──►  PostgreSQL     (excludes soft-deleted, excludes warmup sets)
      ↓
analytics.muscle_volume.weekly_muscle_volume(rows, muscle_map, weights, tz, now)   [PURE]
      ↓
MuscleVolumeReport(...) + DataFreshness
      ↓
SDK validates against output_schema → CallToolResult{content, structured_content}
      ↓
Claude reads structured JSON, applies coach decision framework, answers
```

**Note the absence of an HTTP hop between the MCP tool and the analytics layer.** That is blueprint §37, and it is what makes the single-service topology strictly better than a split here.

### Key Data Flows Summary

1. **Scheduled pull (Hevy):** backend-initiated, cursor-driven, idempotent, soft-deleting.
2. **Manual entry (nutrition, measurement overrides):** REST `POST /api/v1/...` → repositories → DB. Same tables the analytics layer reads; `source` column distinguishes `manual` from `hevy`.
3. **LLM read (MCP):** stateless, authenticated, read-only, budgeted, freshness-annotated.
4. **Device push (HealthKit, milestone 2):** iOS → `POST /api/v1/healthkit/sync/batch` → *the same upsert core* as pattern 2, keyed on `(user_id, provider, external_id)`. Designing the upsert core provider-agnostically in v1 is what makes milestone 2 additive.

---

## Suggested Build Order

The blueprint's Phase 1→5 ordering is **sound and I recommend keeping it**, with four refinements. Refinements 1 and 2 are the ones that matter.

### Refinement 1 (important): insert a deployment + connector spike before Phase 2

**Do a throwaway "hello world MCP on Render, connected to Claude" spike immediately after Phase 1.**

Rationale: the highest-uncertainty item in the entire project is **not** the sync or the analytics — it is whether you can authenticate a personal Claude account to a custom remote MCP connector using a static bearer token. Per Claude's connector docs, `static_headers` (fixed API-key/bearer header) is **in beta**: *"This feature is being slowly rolled out to customers; contact Anthropic for early access."* If your account doesn't have it, the fallback is implementing an OAuth 2.1 authorization server (DCR or CIMD, PKCE S256, RFC 9728 protected-resource metadata, 401 + `WWW-Authenticate: Bearer resource_metadata="..."`). That is a *phase-sized* piece of work that PROJECT.md currently assumes away.

Finding this out in week 1 costs a day. Finding it out in Phase 5 invalidates a Key Decision after everything else is built. The spike is ~2 hours: one tool returning `{"ok": true}`, deployed, added as a custom connector.

Order impact: **Phase 1 → Phase 1.5 (deploy + connector spike) → Phase 2 → 3 → 4 → Phase 5 (harden deployment)**. Phase 5 shrinks from "make deployment work" to "make deployment production-grade," which is a much better risk profile.

### Refinement 2 (important): exercise templates are a Phase 2 deliverable, not a Phase 3 one

`GET /v1/exercise_templates` exists and returns `{id, title, type, primary_muscle_group, secondary_muscle_groups[], equipment_category, is_custom}`. The blueprint (§9, written before/without this) implies hand-building a name→muscle map. Don't. Sync templates as first-class rows during Phase 2, keyed by `exercise_template_id`, and **seed** the canonical map from Hevy's values.

But it is only a seed: Hevy's muscle enum has a single `shoulders` value, while blueprint §18 requires `front_delts / side_delts / rear_delts`. So the architecture is: *Hevy template → seeded mapping → `muscle_map_overrides` table → effective map*. All muscle-group analytics read the effective map. The override table is required, not optional — without it, "How many sets am I doing for side delts?" (an explicit §36 target question) is unanswerable.

This is a dependency: **Phase 3's muscle-volume analytics cannot start until the effective-map resolution exists.**

### Refinement 3 (minor): body measurements can be synced, not typed

`GET /v1/body_measurements` exists, returning `weight_kg, lean_mass_kg, fat_percent, neck_cm, shoulder_cm, chest_cm, left/right_bicep_cm, left/right_forearm_cm, abdomen, waist, hips, left/right_thigh, left/right_calf` per date. PROJECT.md scopes body measurements to manual entry. Reconsider: if you already log weight in Hevy, the same sync machinery gets weight trends for near-zero extra cost, and manual entry becomes the fallback rather than the only path. Model the table `source`-aware either way. Only nutrition genuinely requires manual entry.

### Refinement 4 (minor): keep the scheduler in-process for v1

Render Cron Jobs cost ~$1/mo and run a separate instance of your image. An APScheduler job in the app's lifespan on the always-on $7 Starter Web Service costs nothing extra and is one fewer deploy target. Guard it with a Postgres advisory lock so a future second instance can't double-run. Expose `POST /api/v1/hevy/sync` (internal-token auth) so you can trigger manually, which also gives you a Render Cron escape hatch later without code changes.

### Dependency graph

```
Phase 1  backend foundation (config, db, alembic, users, /healthz, logging+redaction)
   │
   ├──► Phase 1.5  SPIKE: deploy to Render + hello-world MCP + Claude connector  ★ de-risks everything
   │
   └──► Phase 2  Hevy integration
             ├── client (auth, pagination, backoff)
             ├── schemas + mapper
             ├── workouts / workout_exercises / sets  + unique(user_id, provider, external_id)
             ├── exercise_templates sync                        ★ moved up from Phase 3
             ├── sync_state + cursor + event replay + soft delete
             └── canonical muscle map + overrides                ★ blocks muscle analytics
                     │
                     └──► Phase 3  Analytics (pure functions; each independently testable)
                               volume · muscle_volume · progression · prs
                               frequency · plateau · trends · recomposition
                               │
                               └──► Phase 4  MCP tools (thin wrappers; parallelizable per tool)
                                         │
                                         └──► Phase 5  Production hardening
                                                   rate limiting, token rotation, transport_security,
                                                   paid Postgres, backups, e2e mock-Hevy→MCP test
```

`services/` is built incrementally alongside Phases 2–4; it is not a phase.

---

## Scaling Considerations

Be honest: this is a single-user system with a few thousand sets per year. Almost nothing scales. The real limits are ergonomic, not computational.

| Scale | Adjustments |
|-------|-------------|
| 1 user (actual) | Single Render Starter Web Service + Render Postgres. No cache, no queue, no read replica. Recompute analytics on every call. |
| 2–50 users (if ever shared) | Add per-user sync locking; move the scheduler to a Render Cron Job or background worker; add response caching keyed on `(user, window, last_sync_at)`. |
| 1000+ users | Split `fitness-mcp` from `fitness-api` (config change, by design); materialize weekly rollup tables; per-user OAuth replaces the shared bearer token. |

### What actually breaks first, in order

1. **Render free Postgres expires 30 days after creation** (1 GB cap, no backups, one per workspace). For a system whose entire value is *long-term* history, free Postgres is disqualified. Budget for paid Postgres from day one. This is the single most likely way to lose the project's data.
2. **Render free Web Services spin down after 15 minutes of inactivity**, with a ~1-minute cold start. Claude connector requests would intermittently time out. Use Starter ($7/mo) — keep-alive pinging a free instance is a workaround for a problem you shouldn't have on a service Anthropic's infrastructure calls.
3. **MCP response size vs. context window.** The first genuine "performance" issue you hit will be a tool returning too much JSON. Fix with `limit` caps and summary-shaped DTOs, not pagination.
4. **Hevy full-sync request count.** `pageSize` maxes at 10 for workouts; rate limits are undocumented. Full sync of a long history is dozens-to-hundreds of sequential requests. Needs backoff + resumability from the start, which the cursor design already provides.
5. **Analytics recomputation.** A full-history progression scan over thousands of sets per tool call. Not a problem at personal scale; if it ever is, add an indexed `(user_id, start_time)` covering read and a rollup table — not a cache layer.

---

## Anti-Patterns

### 1. Computing metrics inside MCP tool handlers
**What people do:** The tool handler queries the DB and does the math, because it's "just a few lines."
**Why it's wrong:** Analytics become untestable without an MCP client, unreusable by the REST API, and duplicated across tools with subtly divergent definitions of "a set." Blueprint rule #11 exists because this is the default failure mode.
**Instead:** Handler → `services/` → `analytics/`. If a tool handler is longer than ~8 lines, logic has leaked.

### 2. Making the MCP tool call your own REST API over HTTP
**What people do:** `httpx.get("https://myapp.onrender.com/api/v1/metrics/...")` from inside the tool.
**Why it's wrong:** A network hop, a serialization round trip, a second auth path, a self-deadlock risk on a small worker pool, and a new failure mode — all to reach code in the same process. Explicitly called out in blueprint §37.
**Instead:** Call the service function directly.

### 3. Letting provider DTOs become your domain model
**What people do:** Persist Hevy's JSON shape directly and pass `HevyWorkout` around the app.
**Why it's wrong:** Hevy's docs explicitly disclaim structural stability. Worse, it forecloses milestone 2 — HealthKit workouts have no `exercise_template_id`.
**Instead:** `client → schemas → mapper → domain`, with an import-boundary test.

### 4. Counting warmup sets as working sets
**What people do:** `SELECT count(*) FROM sets` for volume.
**Why it's wrong:** Hevy explicitly types sets as `normal | warmup | dropset | failure`. Including warmups inflates every volume metric, corrupts plateau detection, and produces confidently wrong coaching. It's silent — the numbers look plausible.
**Instead:** Filter on `set_type` explicitly in every volume/frequency query, and make the inclusion rule a documented config constant.

### 5. Hard-coding muscle-group weighting or trusting Hevy's taxonomy verbatim
**What people do:** `if secondary: sets += 0.5` inline; use Hevy's `shoulders` as-is.
**Why it's wrong:** Weighting is a coaching-methodology parameter that will change. And Hevy's enum physically cannot express `side_delts`, which §36 requires you to answer questions about.
**Instead:** `domain/config.py` for weights; `muscle_map_overrides` table resolved into an effective map.

### 6. Storing computed analytics as denormalized columns
**What people do:** Write `estimated_1rm` or `weekly_volume` onto rows at sync time.
**Why it's wrong:** The formula *will* change; now you have stale derived data with no way to know which rows used which formula, and every methodology tweak becomes a backfill migration.
**Instead:** Compute on read from immutable source rows. Revisit only if profiling proves a problem.

### 7. Hard-deleting on a Hevy delete event
**What people do:** `DELETE FROM workouts WHERE external_id = ...`.
**Why it's wrong:** Irreversible, destroys history on a spurious/replayed event, and a partially-applied delete cascade can corrupt referential state mid-sync.
**Instead:** Soft delete (`deleted_at`), filtered at the repository layer.

### 8. Relying on `@mcp.custom_route()` for health checks or admin endpoints
**What people do:** Attach `/healthz` to the MCP app for convenience.
**Why it's wrong:** Custom routes bypass MCP authentication entirely. Anything mounted there is public.
**Instead:** Health and all operational endpoints live on the FastAPI side, with their own auth.

### 9. Advancing the sync cursor to the newest event's timestamp
**What people do:** `cursor = max(event.timestamp)`.
**Why it's wrong:** Loses any workout edited between the newest returned event and the end of the sync run.
**Instead:** `cursor = started_at` (captured before the first request). The overlap is free because the upsert is idempotent.

---

## Integration Points

### External Services

| Service | Integration pattern | Verified gotchas |
|---------|--------------------|------------------|
| Hevy API (`https://api.hevyapp.com/v1`) | Scheduled pull, `api-key` header (not `Authorization`), cursor-based incremental | `pageSize` max **10** for workouts/events/routines/body_measurements, max **100** for exercise_templates. Events are newest→oldest. `/workouts/events` is the only deletion signal. Sets expose `rpe` but **no `rir`** — the blueprint's `sets.rir` column has no Hevy source. Weights are always `weight_kg` and distances `distance_meters`, so no unit conversion is needed for Hevy (keep `source_unit` nullable for future providers). Rate limits undocumented → mandatory exponential backoff on 429/5xx. Hevy Pro required. |
| Claude custom connector | Remote MCP over Streamable HTTP, public HTTPS | Anthropic connects **from its own infrastructure** (egress `160.79.104.0/21`), not from your device — no localhost, no tunnels in prod. `static_headers` bearer auth is **beta / limited rollout**; OAuth (DCR or CIMD, PKCE S256) is the supported-out-of-the-box path. When auth is required, return **401** with `WWW-Authenticate: Bearer resource_metadata="..."` — Claude ignores `WWW-Authenticate` on a 200. For an `Authorization` header, the admin must type the literal `Bearer <token>` including the scheme; Claude adds no prefix. Header names come from an allowlist (`authorization`, `x-api-key`, `x-auth-token`, …). Never put the token in a query string. |
| Render | One Web Service (Starter, $7/mo) + managed Postgres; `render.yaml` blueprint | Free Postgres **expires after 30 days** (1 GB, no backups) — disqualified for this project. Free Web Services spin down after 15 min idle (~1 min cold start). Cron Jobs ~$1/mo, per-minute billed. Set `MCP_ALLOWED_HOSTS` to the Render hostname or transport security rejects Claude's requests. |
| Apple HealthKit (milestone 2) | Device-push into the same upsert core, anchor-based incremental | Not v1. The v1 payoff is designing `(user_id, provider, external_id)` upsert generically now. |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| `integrations/hevy/` ↔ rest of app | Direct call, domain types only | Hard boundary. Enforce with an import test. |
| `analytics/` ↔ `db/` | **None — forbidden** | Analytics receive rows as arguments. This is what makes them testable and deterministic. |
| `services/` ↔ `analytics/` + `db/repositories/` | Direct function calls | The only layer that touches both. |
| `api/routes/` ↔ `services/` | Direct call | Router is a translator. |
| `mcp/tools/` ↔ `services/` | Direct call, **never HTTP** | Blueprint §37. |
| FastAPI app ↔ MCP sub-app | ASGI `Mount` + shared lifespan | Host lifespan must enter `mcp.session_manager.run()`. Separate auth middleware per mount. |
| `scheduler` ↔ `services/sync` | Direct call in-process | Guard with a Postgres advisory lock. |

---

## Confidence Notes and Open Questions

**HIGH confidence (verified against primary sources):**
- MCP Python SDK v2 mounting, lifespan, transport-security, auth, and structured-output behaviour — verified against SDK source and official docs.
- Hevy API endpoint list, parameters, pagination limits, event semantics, and all schema shapes — parsed directly from Hevy's live OpenAPI document.
- Render free-tier constraints — verified against Render's own docs.
- Claude connector auth options and the `static_headers` beta status — verified against Claude's connector documentation.

**MEDIUM confidence (engineering judgement):**
- Sync-SQLAlchemy-over-async recommendation. Defensible and, I think, correct for a solo developer at this scale, but it is a preference, not a documented best practice.
- In-process APScheduler over a Render Cron Job.

**Open questions the roadmap should carry:**
1. **Does this Claude account have `static_headers`?** Blocks the auth design. Resolve in the Phase 1.5 spike. If no → an OAuth phase must be added, and PROJECT.md's "bearer token, not OAuth" Key Decision is invalidated.
2. **Hevy rate limits are undocumented.** Backoff parameters must be determined empirically during Phase 2.
3. **`mcp` 2.0.0 shipped 2026-07-28 — under one month old.** `FastMCP` was renamed to `MCPServer` with no alias or deprecation shim (`mcp.server.fastmcp` no longer exists), and it depends on `httpx2` rather than `httpx`. Nearly every tutorial and LLM-generated snippet you'll encounter targets v1. Pin explicitly. My recommendation is `mcp>=2.0,<3` (the stateless protocol is a real architectural simplification for a remote server, and starting on the maintenance-mode branch is a self-inflicted migration), but `mcp>=1.28,<2` is the conservative option if the v2 ecosystem proves too thin. This decision belongs in STACK.md, and the Phase 1.5 spike is the ideal place to settle it empirically.
4. **Use `httpx2` for the Hevy client**, not `httpx` — `httpx2` (Pydantic's continuation of httpx) is already a transitive dependency of `mcp` 2.x, so using `httpx` adds a second near-identical HTTP library to the environment.

---

## Sources

- MCP Python SDK — ASGI/FastAPI mounting, lifespan requirement, `streamable_http_path`, route ordering, `custom_route` auth bypass: https://py.sdk.modelcontextprotocol.io/run/asgi/ (HIGH)
- MCP Python SDK — what's new in v2, `FastMCP`→`MCPServer`, transport config moved to `run()`/app builders, statelessness, v1 maintenance mode, `mcp>=1.28,<2` pinning guidance: https://py.sdk.modelcontextprotocol.io/whats-new/ (HIGH)
- MCP Python SDK source — `TransportSecuritySettings`, `BearerAuthBackend`, `TokenVerifier`, `AuthSettings`, structured output/`output_schema`/`ToolAnnotations`: https://github.com/modelcontextprotocol/python-sdk (HIGH, via Context7)
- MCP spec 2026-07-28 — removal of `initialize` handshake and protocol sessions, horizontal scaling without sticky sessions, backward compatibility: https://blog.modelcontextprotocol.io/posts/sdk-betas-2026-07-28/ (HIGH)
- PyPI `mcp` 2.0.0 — released 2026-07-28, `requires_python >=3.10`, depends on `httpx2>=2.5.0`, `pydantic>=2.12`, `starlette`, `pyjwt[crypto]`: https://pypi.org/project/mcp/ (HIGH)
- PyPI `httpx2` — Pydantic-maintained continuation of httpx: https://pypi.org/project/httpx2/ (HIGH)
- Claude connectors — authentication types, `static_headers` beta status, OAuth DCR/CIMD requirements, 401 + `WWW-Authenticate` handshake, Anthropic egress range, endpoint latency limits: https://claude.com/docs/connectors/building/authentication (HIGH)
- Claude connectors — adding custom connectors on Free/Pro/Max vs Team/Enterprise, request-header auth UX and header allowlist, exact header value semantics: https://claude.com/docs/connectors/custom/remote-mcp (HIGH)
- Hevy API OpenAPI document — full endpoint list, `api-key` header, `page`/`pageSize` limits, `/v1/workouts/events` semantics, `ExerciseTemplate`, `MuscleGroup`, `EquipmentCategory`, `Set`, `BodyMeasurement` schemas: https://api.hevyapp.com/docs/ (HIGH, parsed from the live spec)
- Render free tier — Postgres 30-day expiry, 1 GB cap, no backups; web service 15-minute spin-down: https://render.com/docs/free (HIGH)
- Render pricing — Starter Web Service $7/mo, Cron Jobs from ~$1/mo per-minute billed: multiple 2026 pricing summaries (MEDIUM — corroborated across sources, not read from Render's own pricing page)
- BRETT blueprint.md §§2, 4, 5, 7–9, 16–26, 29–31, 37, 45–48 — validated and refined above
- .planning/PROJECT.md — v1 scope, provider isolation, read-only MCP, flat repo layout constraints

---
*Architecture research for: personal fitness data backend + remote MCP server (Hevy → PostgreSQL → analytics → MCP → Claude)*
*Researched: 2026-08-23*
