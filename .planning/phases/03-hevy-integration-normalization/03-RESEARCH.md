# Phase 3: Hevy Integration & Normalization - Research

**Researched:** 2026-08-29
**Domain:** Third-party REST sync (Hevy API) → idempotent PostgreSQL persistence → curated muscle-group normalization
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Muscle Taxonomy & Mapping**
- **D-01:** Canonical muscle-group list uses the **standard hypertrophy split** (~14-16 groups): chest, lats, traps, front delts, side delts, rear delts, biceps, triceps, forearms, quads, hamstrings, glutes, calves, abs, obliques, lower back. This satisfies NORM-01's explicit front/side/rear deltoid split requirement, which Hevy's own taxonomy does not provide.
- **D-02:** The exercise→muscle mapping is **curated, in-repo data** (Python dict or migration-seeded rows, keyed by Hevy `exercise_template_id`), not re-derived from Hevy's own template metadata on every sync. Hevy's muscle-group fields (if present in the live template payload) may seed the initial curation but the canonical mapping is authored/reviewed like code, so it doesn't silently drift if Hevy changes categorization.
- **D-03:** An exercise with no established mapping (custom Hevy exercise, or a new template not yet curated) **still syncs fully** — workout/exercise/sets persist correctly — with its muscle group(s) left null/flagged "unmapped." Sync must never block or corrupt on a mapping gap (matches HEVY-08's "failed sync must not corrupt data" spirit, extended to mapping gaps). Muscle-volume analytics (Phase 4) simply excludes unmapped exercises until curated.
- **D-04:** Manual overrides live in a **separate table** (e.g. `exercise_muscle_overrides`), not columns bolted onto `exercise_templates`. The original synced/curated mapping is never mutated; the effective mapping is computed at query time (override row present → override wins), giving NORM-02's "auditable against the original source mapping" for free.

**Body Measurements**
- **D-05:** Sync **weight plus whatever other fields Hevy's `/v1/body_measurements` actually returns** (body fat %, waist, chest, arm, thigh, etc. — verify exact field set against the live API at research/plan time, not the blueprint's assumed shape). Matches REQUIREMENTS.md HEVY-07 ("weight, body fat %, waist, and other available fields").
- **D-06:** **One `body_measurements` table**, not per-source tables — columns per metric plus a `source` discriminator (`'hevy' | 'manual'`, manual entry itself is a later phase) and a nullable `external_id` (Hevy's ID when `source='hevy'`). One place to query weight/composition trends from regardless of origin.
- **D-07:** Idempotency keys on **Hevy's own measurement ID when the API provides one** — same `(user_id, source, external_id)` pattern as workouts. If research confirms Hevy has no stable per-entry ID, fall back to `(user_id, source, measured_at date, metric)` (at-most-one Hevy value per metric per calendar day, re-sync upserts). Confirm which case applies during Phase 3 research, not planning-by-assumption.

**Sync Resilience**
- **D-08:** Full sync commits **per page**, with a sync-run/checkpoint record (e.g. `last_hevy_sync_cursor` per blueprint §7, or a dedicated `sync_runs` table) advancing after each successful page. A crash mid-sync leaves all prior pages committed; the next run resumes from the last checkpoint instead of restarting from page 1 — important given the pageSize=10 cap makes a full historical sync dozens-to-hundreds of requests.
- **D-09:** Deletion detection relies on the **`/v1/workouts/events` endpoint only** (blueprint §7's intended mechanism) — no periodic full-reconciliation sweep in v1. Accepted risk: an event missed due to a sync gap longer than Hevy retains events for could leave a deleted workout lingering locally; not building reconciliation now, but note it as a candidate follow-up if drift is ever observed in practice.
- **D-10:** Rate-limit handling is **reactive exponential backoff via tenacity** (already in the stack per CLAUDE.md) on 429/5xx responses, with jitter. No proactive throttling delay added upfront — the pageSize=10 cap already bounds request volume per page, and Hevy's actual limits are undocumented (STATE.md open item); whatever rate-limit headers Hevy returns during the first real sync should be logged/recorded so the real behavior gets documented empirically rather than guessed.

### Claude's Discretion
- **Hevy credential storage** (raised as a gray area, not discussed in depth): the blueprint explicitly permits an env-var secret for a single-user personal deployment ("environment secrets are acceptable for the Hevy key... structure the system so per-user credentials can be supported later"), and `Settings.hevy_api_key` already works that way since Phase 1. Default to **keeping `HEVY_API_KEY` as the env-var secret** rather than building encrypted `external_connections.encrypted_credentials` storage now — build `external_connections` (or equivalent) only as far as needed for `last_synced_at`/status bookkeeping (HEVY-09), not as a credential store, unless research surfaces a concrete reason multi-credential storage is needed sooner. This is Claude's call at research/plan time, not a locked decision — flag it back to the user if the bookkeeping-only approach turns out insufficient.
- Exact `sync_runs`/checkpoint table shape (dedicated table vs. columns on `external_connections`)
- Exact fuzzy/unmapped exercise flag representation (nullable muscle columns vs. an explicit `mapping_status` enum)
- Whether the curated exercise→muscle mapping ships as Python module data or Alembic-seeded rows (both satisfy D-02 "in-repo, curated")
- Whether dumbbell weight is per-dumbbell or combined (STATE.md open item — must be discovered empirically during the first real sync and recorded, not assumed)
- Exact tenacity retry parameters (max attempts, backoff base/cap)
- CLI/route mechanism for manually triggering a sync run in this phase (production scheduling is Phase 7; this phase just needs *a* way to invoke `HevySyncService` for verification/testing)

### Deferred Ideas (OUT OF SCOPE)
- **Periodic full-reconciliation sweep for deletion detection** (D-09) — not built in v1; noted as a candidate follow-up only if event-based deletion detection is ever observed to drift in practice.
- **Encrypted per-provider credential storage** (`external_connections.encrypted_credentials`) — deferred again past this phase by default (see Claude's Discretion), since the blueprint explicitly allows an env-var secret for a single-user personal deployment. Revisit if/when the project moves toward multi-user or per-user credentials.
- Manual body-measurement and nutrition entry (schema/endpoints) — explicitly out of this phase's scope; this phase only ships the Hevy-sourced side of `body_measurements` (D-06's `source` column anticipates the later manual-entry rows).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| HEVY-01 | Initial full sync of historical workouts via paginated API calls (pageSize cap 10) | Live OpenAPI verified: `GET /v1/workouts`, `page`/`pageSize` (default 5, **max 10**), response `{page, page_count, workouts[]}`. `GET /v1/workouts/count` gives the total up front — use it as a cheap reconciliation check. See *Hevy API Ground Truth*, *Pattern 1*. |
| HEVY-02 | Incremental sync via workout-events endpoint, drain newest-to-oldest then apply oldest-first | `GET /v1/workouts/events?since=&page=&pageSize=` verified; events are `oneOf[UpdatedWorkout, DeletedWorkout]`, ordered newest→oldest. **Simulation in *Pitfall 1* proves the naive algorithm applied 2 of 8 events and produced wrong state.** Correct algorithm given in *Pattern 2*. |
| HEVY-03 | Idempotent sync — no duplicate workouts/exercises/sets; children keyed by workout and reinserted transactionally | Verified against real Postgres 18: `ON CONFLICT (user_id, provider, external_id) DO UPDATE` on the parent + delete-and-reinsert children. Three consecutive syncs held counts at (1,1,2). Confirmed Hevy child objects carry **only `index`, no `id`**. See *Pattern 3*. |
| HEVY-04 | Deleted Hevy workouts reflected locally without corrupting other data | `DeletedWorkout {type, id, deleted_at}` from the events feed. Verified: `ondelete="CASCADE"` FKs remove the workout's exercises/sets and leave every sibling row untouched. See *Pattern 4*. |
| HEVY-05 | Hevy request/response logic isolated in `backend/app/integrations/hevy/` | Directory does not yet exist. Module layout and the boundary rule (Pydantic Hevy schemas never cross into `db/models` or analytics) in *Recommended Project Structure*. |
| HEVY-06 | Sync exercise templates with primary and secondary muscle groups | `GET /v1/exercise_templates` — **pageSize max is 100, not 10**. `ExerciseTemplate {id, title, type, primary_muscle_group, secondary_muscle_groups[], equipment_category, is_custom}`. Full `MuscleGroup` enum (20 values) in *Muscle Taxonomy*. |
| HEVY-07 | Sync body measurements (weight, body fat %, waist, other available fields) | Exact 17-field live schema captured verbatim in *Hevy API Ground Truth*. Includes `weight_kg`, `fat_percent`, `lean_mass_kg`, `waist`, and 13 more. |
| HEVY-08 | Sync failure does not corrupt previously-synced data | Verified: per-page commit + rollback preserved page 1 after a simulated mid-page failure; `begin_nested()` SAVEPOINT isolated one malformed workout and left the session usable. See *Pattern 5*, *Pattern 6*. |
| HEVY-09 | Each data source exposes a `last_synced_at` | Three independent resources need independent bookkeeping (workouts, exercise_templates, body_measurements). Schema in *Pattern 7*. |
| NORM-01 | Every exercise mapped to canonical muscle groups incl. front/side/rear delt split | **Decisive finding:** Hevy's enum has a single `shoulders` value, and the largest public exercise dataset (`free-exercise-db`, 873 exercises) uses the *same* flat taxonomy. No public dataset provides the delt split — it must be hand-curated, exactly as D-02 assumes. Bounded scope analysis in *Muscle Taxonomy*. |
| NORM-02 | Mappings manually overridable, auditable against the original source mapping | Two-table design (curated base + override) with a per-template replacement rule. The subtle failure mode (per-row merge makes muscle *removal* impossible) is documented in *Pattern 8*. |
| NORM-03 | Direct vs indirect involvement with configurable weighting (default 1.0/0.5) applied at query time | Store the **role** (`direct`/`indirect`), never the weight. Weight is a query-time parameter. Blueprint §18 agrees ("Make this configurable rather than hard-coded"). See *Pattern 8*. |
</phase_requirements>

## Summary

Everything in this phase hinges on facts about the live Hevy API that the blueprint gets wrong in
several places. I pulled and parsed Hevy's live OpenAPI 3.0.0 document
(`https://api.hevyapp.com/docs/swagger-ui-init.js`) and reconstructed every schema this phase
touches. The headline corrections: `exercise_templates` pages at **100**, not 10 (so template sync
is ~5 requests, not 50); body measurements have **no ID at all** — the calendar date *is* the
primary key, and one row carries all 17 metrics; and `sets` carry **`rpe` but not `rir`**, and no
`weight_unit` because Hevy already normalizes to `weight_kg`. Workout exercises and sets have only
an `index`, never an `id`, which is precisely why HEVY-03 mandates delete-and-reinsert rather than
per-child upsert.

The three genuinely hard problems are the incremental-events algorithm, transactional resilience,
and the deltoid split. For the first, I wrote a simulation of Hevy's newest-to-oldest event feed:
the naive "advance the cursor as you page" approach applied **2 of 8 events and silently dropped an
entire workout**, while the correct approach (freeze `since` for the whole drain, collect every
page, reverse to oldest-first, then apply, then advance the cursor once) reproduced the true state
exactly. For the second, I ran six persistence patterns against a real PostgreSQL 18 container and
confirmed all of them, including the non-obvious ones: `begin_nested()` SAVEPOINTs are *required*
to quarantine one malformed workout without poisoning the surrounding transaction, and a
`where=`-guarded `ON CONFLICT` returns no row, which breaks the "get the id back, then write the
children" flow. For the third, I checked the largest public exercise dataset and found it uses the
same flat `shoulders` bucket Hevy does — so there is no dataset to import, and curation is
unavoidable. The good news is that curation is far smaller than it looks: of Hevy's 20 muscle-group
values, **17 translate to canonical groups by mechanical rename**, and only `shoulders` (→ three
delt heads) and `abdominals` (→ abs/obliques) actually require human judgement.

Two live-fire corrections to project documents. `pytest-httpx2` is authored by the maintainer of
`respx` and **does** intercept `httpx2` — CLAUDE.md's claim that "respx cannot see httpx2" is
outdated. But it has a sharp edge I hit and verified: routes must be fed **`httpx.Response`
(0.x) objects**; passing an `httpx2.Response` into `side_effect` fails with an opaque
`assert isinstance(resolved.response, httpx.Response)`. Separately, `app/logging.py`'s `DENY_KEYS`
contains `api_key`, `apikey` and `x-api-key` but **not `api-key`** — which is the literal header
name Hevy requires.

**Primary recommendation:** Build `HevyClient` as a thin, retry-wrapped, Pydantic-validated
transport over the six GET endpoints this phase needs, and put every stateful decision in
`HevySyncService`: per-page commit with a per-resource checkpoint row, parent upsert +
child delete/reinsert for idempotency, a frozen-cursor event drain applied oldest-first, and a
curated `template_id → (muscle_group, role)` overlay that only has to disambiguate `shoulders` and
`abdominals`. Treat unmapped exercises as first-class (D-03) so the mapping never gates the sync.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Hevy HTTP transport, auth header, retry/backoff | Integration (`integrations/hevy/client.py`) | — | HEVY-05 requires all Hevy request/response code confined here. The client owns *transport* concerns only; it never touches the DB. |
| Hevy response validation / DTO shape | Integration (`integrations/hevy/schemas.py`) | — | Pydantic models mirror Hevy's wire format exactly. They are the quarantine boundary: an upstream field rename breaks here, loudly, not in analytics. |
| Sync orchestration, pagination, checkpointing, transaction boundaries | Service (`integrations/hevy/sync.py`) | Database | Only tier that decides what commits and when. Owns HEVY-01/02/03/08. |
| Canonical persistence (workouts / exercises / sets) | Database (`db/models/`) | — | Provider-neutral schema. A second provider later writes the same tables with a different `provider` discriminator. |
| Idempotency enforcement | Database (unique constraints) | Service | Verified: `UNIQUE(user_id, provider, external_id)` makes duplicates structurally impossible, not merely unlikely. Service-only dedup would be a race. |
| Deletion propagation | Database (`ON DELETE CASCADE`) | Service | Verified that FK cascade removes children atomically and leaves siblings untouched (HEVY-04). |
| Exercise → canonical muscle mapping (curated data) | Application data (`normalization/`) | Database | D-02: authored and reviewed like code, not re-derived per sync. Provider-neutral — lives *outside* `integrations/hevy/`. |
| Manual override + effective-mapping resolution | Database (query time) | Application | D-04/NORM-02: overrides never mutate the source mapping; effective mapping is computed, giving auditability for free. |
| Direct/indirect weighting (1.0 / 0.5) | Query time (Phase 4 analytics) | Config | NORM-03 + blueprint §18 both say configurable. Storing the weight in a column would hard-code it. |
| Sync freshness bookkeeping (`last_synced_at`) | Database (`sync_state`) | Service | HEVY-09. Also carries the D-08 resume cursor — one row per (user, provider, resource). |
| Sync trigger (CLI) | Application (`app/cli.py`) | — | Phase 3 needs only *a* way to invoke the service. Production scheduling is Phase 7. |

## Project Constraints (from CLAUDE.md)

Directives extracted from `./CLAUDE.md` that constrain this phase. Treat with the same authority as
locked decisions.

| Constraint | Applies to this phase as |
|---|---|
| Tech stack: Python 3.13, FastAPI, PostgreSQL, SQLAlchemy 2.x, Alembic, Pydantic, pytest, Ruff, mypy | No new frameworks. `tenacity` is already sanctioned by the stack table; it is the only new runtime dependency this phase should need. |
| Repo layout flat at BRETT root (`backend/`, `docs/`) | New code goes under `backend/app/`, migrations under `backend/migrations/versions/`. |
| Security: never expose API keys/DB credentials in responses or logs; secrets from environment only | The Hevy `api-key` header value must never reach a log line. **See Pitfall 9 — `DENY_KEYS` has a real gap here.** |
| Data integrity: Hevy sync must be idempotent and must never corrupt existing data on partial/failed sync | HEVY-03 and HEVY-08. Patterns 3, 5 and 6 are the verified mechanisms. |
| Provider isolation: Hevy logic confined to `backend/app/integrations/hevy/` | HEVY-05. The curated muscle mapping is *not* Hevy-specific and belongs outside that directory. |
| Use `httpx2`, **not** `httpx` | `httpx2==2.12.0` is already installed and is the only HTTP client in the runtime tree. |
| Use `pytest-httpx2` or `httpx2.MockTransport`, **not** `respx`/`pytest-httpx` directly | Partially superseded — see *State of the Art*. `pytest-httpx2` is a respx wrapper and works; the direct-`respx` prohibition still stands. |
| **Never** SQLite for tests — use `testcontainers[postgres]` | Already the established pattern in `backend/tests/conftest.py`. |
| No pandas/numpy | Not needed here; nothing in this phase does array math. |
| `pyproject.toml` + `uv.lock`, never `requirements.txt` | Add `tenacity` and `pytest-httpx2` via `uv add` so `uv.lock` stays authoritative. |
| Ruff lint set `E,F,I,UP,B,ASYNC,S,DTZ`; mypy `disallow_untyped_defs` | `DTZ` bans naive datetimes — relevant when parsing Hevy's date-only `body_measurements.date`. `S` (bandit) is active on application code. |
| GSD workflow enforcement — no direct repo edits outside a GSD command | Execution happens under `/gsd-execute-phase`. |

## Hevy API Ground Truth

**Source:** live OpenAPI 3.0.0 document at `https://api.hevyapp.com/docs/` (`swagger-ui-init.js`),
fetched and parsed 2026-08-29. `info.version` is `0.0.1`.
`[VERIFIED: api.hevyapp.com live OpenAPI, parsed 2026-08-29]`

Hevy's own preamble is worth quoting, because it sets the engineering posture for this whole phase:

> "we make no guarantees that we won't completely change the structure or abandon the project
> entirely so use it at your own risk. Currently, this API is only available to Hevy Pro users."

That is the justification for HEVY-05's isolation rule and for validating every response through
Pydantic rather than reaching into raw dicts.

### Authentication

Header **`api-key`** (lowercase, hyphen), declared `required: true` with `format: uuid`, on every
endpoint. There is **no** `securitySchemes` block and no top-level `security` — auth is expressed
as an ordinary header parameter. `[VERIFIED]`

### Endpoints this phase needs (all GET)

| Endpoint | Params | pageSize default / **max** | Notes |
|---|---|---|---|
| `/v1/workouts` | `page`, `pageSize` | 5 / **10** | Returns `{page, page_count, workouts[]}`. Responses documented: 200, 400. |
| `/v1/workouts/count` | — | — | `{workout_count: int}`. One request. Ideal cheap reconciliation check. |
| `/v1/workouts/events` | `page`, `pageSize`, `since` | 5 / **10** | `since` default `1970-01-01T00:00:00Z`. Responses: 200, **500**. Events **newest→oldest**. |
| `/v1/exercise_templates` | `page`, `pageSize` | 5 / **100** | ⚠️ **max 100, not 10.** ~400+ templates ⇒ ~5 requests. Responses: 200, 400. |
| `/v1/body_measurements` | `page`, `pageSize` | 10 / **10** | Responses: 200, 400, **404 "Page not found"**. |
| `/v1/workouts/{workoutId}` | — | — | Single workout. Useful for targeted repair; not required. |

Hevy's own description of the events endpoint states the design intent explicitly:

> "Retrieve a paged list of workout events (updates or deletes) since a given date. Events are
> ordered from newest to oldest. The intention is to allow clients to keep their local cache of
> workouts up to date without having to fetch the entire list of workouts."

### `Workout` schema (verbatim field set) `[VERIFIED]`

```
Workout:  id, title, routine_id, description, start_time, end_time, updated_at, created_at, exercises[]
  exercises[]:  index, title, notes, exercise_template_id, supersets_id (nullable), sets[]
    sets[]:  index, type, weight_kg (nullable), reps (nullable), distance_meters (nullable),
             duration_seconds (nullable), rpe (nullable), custom_metric (nullable)
```

Corrections to blueprint §8, all confirming STATE.md's warning:

| Blueprint §8 assumed | Live API reality |
|---|---|
| `rir` | **Does not exist.** `rpe` does (nullable number, e.g. `9.5`). |
| `weight_unit` | **Does not exist.** Field is `weight_kg` — Hevy normalizes to kg upstream, which satisfies blueprint §41 for free. |
| `weight` | `weight_kg` |
| `distance` / `duration` | `distance_meters` / `duration_seconds` (already blueprint §41 units) |
| exercises/sets have `id` | **They do not.** Only `index`. This is the entire reason for HEVY-03's delete-and-reinsert rule. |
| — (not anticipated) | `supersets_id`, `custom_metric`, `routine_id`, `notes` exist and are worth preserving per blueprint §8 ("Do not throw away useful source metadata"). |

`set.type` is documented as one of `normal`, `warmup`, `dropset`, `failure`. **`warmup` is the value
Phase 4's VOL-01 must exclude from volume**, so store it verbatim rather than coercing to a boolean.

### `ExerciseTemplate` schema `[VERIFIED]`

```
ExerciseTemplate: id, title, type, primary_muscle_group, secondary_muscle_groups[],
                  equipment_category, is_custom
```

`id` format is inconsistent and both forms must be accommodated by a single `String` column:
built-in templates use 8-char uppercase hex (`"05293BCA"`, `"D04AC939"` — seen in the `Workout` and
`ExerciseHistoryEntry` examples), while the `ExerciseTemplate.id` example is a full UUID
(`"b459cba5-cd6d-463c-abd6-54f8eafcadcb"`), consistent with custom exercises. Use `String(64)`; do
**not** use a `UUID` column type. `[VERIFIED — both formats appear in the same spec]`

`type` enum (`CustomExerciseType`): `weight_reps`, `reps_only`, `bodyweight_reps`,
`bodyweight_assisted_reps`, `duration`, `weight_duration`, `distance_duration`,
`short_distance_weight`. This is exactly the modality signal PROG-01 (Phase 5) needs to decide
whether an estimated 1RM is meaningful — **persist it now**.

`equipment_category` enum: `none`, `barbell`, `dumbbell`, `kettlebell`, `machine`, `plate`,
`resistance_band`, `suspension`, `other`. Note `dumbbell` is the discriminator needed to
investigate the per-dumbbell-vs-combined weight question.

### `BodyMeasurement` schema — 17 fields, **no `id`** `[VERIFIED]`

```
BodyMeasurement:  date (format: date, REQUIRED — the only required field)
  weight_kg, lean_mass_kg, fat_percent,
  neck_cm, shoulder_cm, chest_cm,
  left_bicep_cm, right_bicep_cm, left_forearm_cm, right_forearm_cm,
  abdomen, waist, hips, left_thigh, right_thigh, left_calf, right_calf
```

All metric fields are `nullable: true`. Three findings that settle D-05, D-06 and D-07:

1. **There is no `id` field.** The date *is* the identity. Corroborated by the sibling endpoints:
   `GET /v1/body_measurements/{date}`, `PUT /v1/body_measurements/{date}`, and
   `POST /v1/body_measurements` which "Returns 409 if an entry already exists for that date."
   `[VERIFIED]`
2. **One row carries all metrics for a date** — it is not one row per metric.
3. **Naming is inconsistent about units.** Seven fields carry an explicit `_cm` suffix; seven
   (`abdomen`, `waist`, `hips`, `left_thigh`, `right_thigh`, `left_calf`, `right_calf`) do not.

**⚠️ D-07 needs a correction.** Its fallback was `(user_id, source, measured_at date, metric)` — a
per-metric key. That is the wrong granularity for the actual payload. The correct key is
**`(user_id, source, measured_on)`** for the whole row. See *Pattern 9*.

`PUT /v1/body_measurements/{date}` is documented as "All fields are overwritten; omitted fields are
set to null." Read-only in v1 so this does not bite, but it confirms the row-replacement semantics
that the local upsert should mirror.

### What is *not* in the spec `[VERIFIED — absence confirmed by exhaustive keyword scan]`

I scanned the entire parsed document for `rate limit`, `ratelimit`, `429`, `throttl`, `quota` and
`retry-after`. **Zero matches.** No documented rate limits, no `429` response on any endpoint, and
no `401`/`403` documented on the GET endpoints either — though a third-party Hevy client's
troubleshooting docs state "Hevy API returns 401: the key is invalid, expired, revoked, or
misconfigured" `[CITED: github.com/chrisdoc/hevy-mcp]`, so 401 does occur in practice.

Consequences the plan must absorb:
- The client must handle 429 and 401/403 **even though neither is documented**.
- STATE.md's "rate limits undocumented" item is **confirmed, not merely suspected**. D-10's
  reactive-backoff choice is correct, and logging observed rate-limit headers on the first real sync
  is the only way to learn the true limit.

## Standard Stack

### Core — already installed, no action needed

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| httpx2 | 2.12.0 | Hevy HTTP client | Already the only HTTP client in the tree. `AsyncClient`, `base_url`, `headers`, `Timeout`, `MockTransport`. `[VERIFIED: installed in .venv]` |
| SQLAlchemy | 2.0.52 | ORM + Core | `postgresql.insert().on_conflict_do_update()` is the idempotency primitive. `[VERIFIED: installed]` |
| asyncpg | 0.31.0 | Async driver | Existing. |
| Alembic | 1.19.1 | Migrations | Existing pattern in `backend/migrations/versions/`. |
| Pydantic | 2.13.4 | Hevy response validation | The HEVY-05 quarantine boundary. |
| structlog | 26.1.0 | Sync lifecycle logging | Blueprint §44. Redaction pipeline already built. |

### Supporting — to add

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **tenacity** | **9.1.4** (released 2026-02-07, `requires_python >=3.10`, **zero dependencies**) | Retry with exponential backoff + jitter | D-10. Use `AsyncRetrying` in an `async for` loop, or the `@retry` decorator. `[VERIFIED: PyPI JSON API 2026-08-29 + live install + 5 passing behavioural tests]` |
| **pytest-httpx2** | **1.0.0** (released 2026-05-20) | Mock Hevy in tests (dev group only) | Blueprint §42 requires pagination/failure/rate-limit tests. **Verified it genuinely intercepts httpx2.** `[VERIFIED: live install + passing tests]` |

**Installation:**
```bash
uv add tenacity==9.1.4
uv add --group dev pytest-httpx2==1.0.0
```

**⚠️ Verified dependency consequence.** `pytest-httpx2` depends on `respx`, which depends on
`httpx>=0.25`. A real `uv lock` resolution pulls **`respx 0.23.1`, `httpx 0.28.1`, `httpcore 1.0.9`,
`certifi`, `h11`** into the tree. `[VERIFIED: uv lock in a clean project, 2026-08-29]`
This is acceptable **only** because `pyproject.toml` sets `default-groups = []`, so the dev group is
excluded from the production image — the comment in `pyproject.toml` documents exactly this
guarantee. If the planner would rather keep httpx 0.x out of the lockfile entirely,
`httpx2.MockTransport` needs no dependency at all and is verified working (*Alternatives*).

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `pytest-httpx2` | `httpx2.MockTransport` | Zero new dependencies, pure httpx2 types (no `httpx.Response` conversion gotcha), and **verified working for sequenced 429→200 responses**. Costs: you hand-roll request recording and URL matching. Reasonable if the team wants httpx 0.x out of `uv.lock`. |
| `tenacity` | `stamina` 26.1.0 | Thinner wrapper with better defaults — but it *depends on* tenacity, so it adds a layer rather than replacing one. `[VERIFIED: PyPI requires_dist]` |
| `tenacity` | Hand-rolled `asyncio.sleep` loop | Don't — see *Don't Hand-Roll*. |
| Per-page commit (D-08) | One transaction for the whole sync | Rejected by D-08 and by HEVY-08: a single transaction means a failure on page 40 discards 39 pages of work. |
| `Numeric` for weights | `Float` | **Use `Numeric`.** Verified `Numeric(7,3)` round-trips as exact `Decimal('102.500')`; `Float` gives 102.5 and `0.1+0.2 != 0.3`. Phase 4 sums thousands of these into tonnage. |

## Muscle Taxonomy — the NORM-01 core problem

### The finding that shapes the whole task

Hevy's `MuscleGroup` enum, verbatim from the live spec (20 values) `[VERIFIED]`:

```
abdominals, shoulders, biceps, triceps, forearms, quadriceps, hamstrings, calves,
glutes, abductors, adductors, lats, upper_back, traps, lower_back, chest,
cardio, neck, full_body, other
```

`shoulders` is a **single bucket**. NORM-01's premise is confirmed exactly.

I then checked whether an existing dataset could supply the split. `free-exercise-db`
(`yuhonas/free-exercise-db`, 873 exercises, public domain) uses a **near-identical flat taxonomy**
`[VERIFIED: downloaded and analysed dist/exercises.json, 2026-08-29]`:

```
abdominals, abductors, adductors, biceps, calves, chest, forearms, glutes, hamstrings,
lats, lower back, middle back, neck, quadriceps, shoulders, traps, triceps
```

**No delt split there either.** Both its `primaryMuscles` and `secondaryMuscles` vocabularies are
identical and both use flat `shoulders`.

> **Planner: do not create a task to import a public dataset for the deltoid split. It does not
> exist.** D-02's "curated, in-repo" decision is not merely a preference — it is the only option.

### But the curation job is much smaller than it looks

Mapping Hevy's 20 enum values to canonical groups, **17 of 20 are a mechanical rename**:

| Hevy value | Canonical | Kind |
|---|---|---|
| `chest` | `chest` | identity |
| `lats` | `lats` | identity |
| `upper_back` | `upper_back` | identity |
| `traps` | `traps` | identity |
| `lower_back` | `lower_back` | identity |
| `biceps` | `biceps` | identity |
| `triceps` | `triceps` | identity |
| `forearms` | `forearms` | identity |
| `hamstrings` | `hamstrings` | identity |
| `glutes` | `glutes` | identity |
| `calves` | `calves` | identity |
| `abductors` | `abductors` | identity |
| `adductors` | `adductors` | identity |
| `neck` | `neck` | identity |
| `quadriceps` | `quads` | rename |
| `abdominals` | `abs` **+ possibly `obliques`** | ⚠️ **needs curation** |
| `shoulders` | `front_delts` / `side_delts` / `rear_delts` | ⚠️ **needs curation** |
| `cardio` | — | non-hypertrophy; exclude from volume |
| `full_body` | — | non-specific; exclude from volume |
| `other` | — | treat as unmapped (D-03) |

**Only two enum values require human judgement.** For scale: in `free-exercise-db`,
shoulders-primary exercises are **127 of 873 (15%)** `[VERIFIED: computed]`. Applied to Hevy's
"400+ high-quality exercises" `[CITED: hevyapp.com/features/exercise-library]` that is roughly
50-70 exercises — and the practical number is far lower, because curation only needs to cover
templates that appear in *this user's* history. D-03 explicitly permits everything else to remain
unmapped.

A useful accelerator: many shoulder exercise titles name the head directly (`Rear Delt Row`,
`Bent Over ... Rear Delt Raise`, `Bent Over Low-Pulley Side Lateral`, `Front Raise`,
`Lateral Raise`). A title-keyword pass is a legitimate way to *seed* the curated file, but D-02
requires the result be reviewed like code before it is committed — do not wire the heuristic into
the sync path.

### Reconciling D-01 with blueprint §18

The two authoritative lists disagree and the planner must resolve it:

| Group | D-01 (CONTEXT) | Blueprint §18 | Hevy source available? |
|---|---|---|---|
| chest, lats, biceps, triceps, quads, hamstrings, glutes, calves, abs | ✅ | ✅ | ✅ |
| front_delts, side_delts, rear_delts | ✅ | ✅ | ❌ curated from `shoulders` |
| `upper_back` | ❌ absent | ✅ present | ✅ |
| `traps` | ✅ present | ❌ absent | ✅ |
| `forearms`, `lower_back` | ✅ | ❌ | ✅ |
| `obliques` | ✅ | ❌ | ❌ curated from `abdominals` |
| `abductors`, `adductors`, `neck` | ❌ | ❌ | ✅ |

**Recommendation — canonical list of 19** (the union of D-01 and §18, plus the Hevy values that
arrive free): `chest, lats, upper_back, traps, lower_back, front_delts, side_delts, rear_delts,
biceps, triceps, forearms, abs, obliques, quads, hamstrings, glutes, calves, abductors, adductors`.

Rationale: D-01 says "~14-16 groups" and lists 16, so it is explicitly not a closed set; adding
`upper_back` honours blueprint §18; `abductors`/`adductors` cost nothing because Hevy supplies them
directly, and dropping them would silently discard real data. `neck`, `cardio`, `full_body` and
`other` map to no canonical group and should be handled by the unmapped path (D-03).
`[ASSUMED — this reconciliation is my recommendation, not a user decision; flag for confirmation]`

## Architecture Patterns

### System Architecture Diagram

```
                    ┌──────────────────────────────────────────────┐
   Hevy Cloud       │  CLI trigger  `python -m app.cli sync-hevy`   │
   api.hevyapp.com  │  (Phase 7 replaces with a scheduled trigger)  │
        │           └──────────────────────┬───────────────────────┘
        │                                  │
        │                                  ▼
        │                    ┌─────────────────────────────┐
        │                    │      HevySyncService        │
        │                    │  (orchestration + txn)      │
        │                    └──────────────┬──────────────┘
        │                                   │
        │            ┌──────────────────────┼──────────────────────┐
        │            │                      │                      │
        │            ▼                      ▼                      ▼
        │   ┌────────────────┐   ┌──────────────────┐   ┌──────────────────┐
        │   │ read checkpoint│   │  decide mode     │   │ write checkpoint │
        │   │  sync_state    │──▶│ full vs incr.    │   │  + last_synced_at│
        │   └────────────────┘   └────────┬─────────┘   └────────▲─────────┘
        │                                 │                      │
        │        ┌────────────────────────┼──────────────────┐   │
        │        │                        │                  │   │
        │        ▼                        ▼                  ▼   │
        │  ╔═══════════╗          ╔═══════════════╗   ╔═══════════════╗
        │  ║ FULL SYNC ║          ║ INCREMENTAL   ║   ║ TEMPLATES +   ║
        │  ║ /workouts ║          ║ /events       ║   ║ /body_meas.   ║
        │  ║ page 1..N ║          ║ since=frozen  ║   ╚═══════╤═══════╝
        │  ╚═════╤═════╝          ╚═══════╤═══════╝           │
        │        │                        │                   │
        │        │                        ▼                   │
        │        │            ┌───────────────────────┐       │
        │        │            │ drain ALL pages first │       │
        │        │            │ (newest→oldest)       │       │
        │        │            └───────────┬───────────┘       │
        │        │                        ▼                   │
        │        │            ┌───────────────────────┐       │
        │        │            │ REVERSE to oldest-1st │       │
        │        │            └───────────┬───────────┘       │
        │        │                        │                   │
        │        └────────────┬───────────┴───────────────────┘
        │                     ▼
        │      ┌──────────────────────────────┐
        └─────▶│      HevyClient (httpx2)     │
   api-key hdr │  tenacity retry: 429/5xx/net │
               │  NO retry: 401/403/400/404   │
               └──────────────┬───────────────┘
                              ▼
               ┌──────────────────────────────┐
               │  Pydantic schemas (quarantine)│
               │  upstream shape stops HERE    │
               └──────────────┬───────────────┘
                              ▼
        ┌─────────────────────────────────────────────────┐
        │        PER-PAGE TRANSACTION  (D-08)              │
        │  ┌───────────────────────────────────────────┐  │
        │  │ SAVEPOINT per workout (begin_nested)      │  │
        │  │   upsert workout  ON CONFLICT DO UPDATE   │  │
        │  │   DELETE children → executemany reinsert  │  │
        │  │   malformed one → rollback SAVEPOINT only │  │
        │  └───────────────────────────────────────────┘  │
        │            COMMIT ── checkpoint advances         │
        └────────────────────────┬────────────────────────┘
                                 ▼
     ┌──────────────────────────────────────────────────────────┐
     │                      PostgreSQL                          │
     │  workouts ──1:N──▶ workout_exercises ──1:N──▶ sets       │
     │      ▲ CASCADE            ▲ CASCADE                      │
     │  exercise_templates    body_measurements    sync_state   │
     └──────────────────────────┬───────────────────────────────┘
                                │  (read-only, query time)
                                ▼
     ┌──────────────────────────────────────────────────────────┐
     │            EFFECTIVE MUSCLE MAPPING (computed)           │
     │  curated base  ⟵overridden per-template by⟶  overrides   │
     │  → (muscle_group, role ∈ {direct, indirect})             │
     │  weight 1.0/0.5 applied HERE, by Phase 4 — never stored  │
     └──────────────────────────────────────────────────────────┘
```

### Recommended Project Structure

```
backend/app/
├── integrations/
│   ├── __init__.py
│   └── hevy/                       # HEVY-05 boundary — nothing Hevy-shaped escapes
│       ├── __init__.py
│       ├── client.py               # HevyClient: httpx2 + api-key header + tenacity
│       ├── schemas.py              # Pydantic mirrors of the live wire format
│       ├── sync.py                 # HevySyncService: pagination, txn, checkpoints
│       └── errors.py               # HevyAuthError / HevyRateLimited / HevyServerError
├── normalization/                  # NOT Hevy-specific — provider-neutral
│   ├── __init__.py
│   ├── muscles.py                  # canonical MuscleGroup enum + Hevy enum translation
│   └── exercise_map.py             # curated template_id → [(group, role)] (D-02)
├── db/models/
│   ├── workout.py                  # Workout, WorkoutExercise, WorkoutSet
│   ├── exercise.py                 # ExerciseTemplate, ExerciseMuscle, ExerciseMuscleOverride
│   ├── body.py                     # BodyMeasurement
│   └── sync_state.py               # per-resource cursor + last_synced_at (HEVY-09)
└── cli.py                          # `python -m app.cli sync-hevy` trigger
```

**The boundary rule:** `integrations/hevy/schemas.py` types may be imported by `sync.py` and by
nothing else. If a Pydantic Hevy model ever appears in `db/`, `normalization/` or (later)
`analytics/`, HEVY-05 has been violated. This is worth a test.

### Pattern 1: Paginated full sync with reconciliation

```python
# Verified against the live OpenAPI: {page, page_count, workouts[]}, pageSize max 10.
async def iter_workout_pages(client: HevyClient, start_page: int = 1):
    page = start_page
    while True:
        payload = await client.get_workouts(page=page, page_size=10)  # max 10
        yield page, payload.workouts
        if page >= payload.page_count or not payload.workouts:
            return
        page += 1
```

Use `GET /v1/workouts/count` before and after a full sync. It is a single request and turns
"did the sync actually get everything?" into an assertion instead of a hope — a cheap partial
mitigation for D-09's accepted deletion-drift risk.

**Page-shift analysis under concurrent writes** (offset pagination over mutating data):
- If Hevy orders newest-first, a workout logged mid-sync shifts items toward *later* pages, so an
  item can be seen twice. Duplicates are harmless — the upsert is idempotent.
- If ordering is oldest-first, new items append and nothing shifts.
- Either way, **additions cannot cause a skip**; only a *deletion* mid-sync can, and the events
  feed is the designated mechanism for deletions anyway.

Ordering direction is not documented. `[ASSUMED — verify empirically on the first real sync]`

### Pattern 2: The correct incremental-events algorithm (HEVY-02)

```python
async def drain_events(client: HevyClient, since: datetime) -> tuple[list[Event], datetime]:
    """Freeze `since`, collect EVERY page, then reverse to oldest-first.

    Three rules, each of which the simulation in Pitfall 1 shows is load-bearing:
      1. `since` MUST NOT change while paging. Advancing it mid-drain re-windows the
         query and silently discards the older pages you have not fetched yet.
      2. Collect all pages BEFORE applying anything.
      3. Apply oldest-first, so two updates to the same workout land in causal order
         and the newest payload wins.
    """
    collected: list[Event] = []
    page = 1
    while True:
        payload = await client.get_workout_events(since=since, page=page, page_size=10)
        collected.extend(payload.events)
        if page >= payload.page_count or not payload.events:
            break
        page += 1

    collected.sort(key=event_timestamp)          # newest→oldest  ==>  oldest→newest
    new_cursor = max((event_timestamp(e) for e in collected), default=since)
    return collected, new_cursor


def event_timestamp(e: Event) -> datetime:
    # The two event variants carry the timestamp in DIFFERENT fields.
    # UpdatedWorkout -> .workout.updated_at ;  DeletedWorkout -> .deleted_at
    return e.deleted_at if e.type == "deleted" else e.workout.updated_at
```

Advance the checkpoint **once**, after the whole drain commits. When in doubt choose an *earlier*
cursor: overlap is free (upserts are idempotent), a gap is unrecoverable.

Discriminating the union: `UpdatedWorkout` and `DeletedWorkout` are a `oneOf` distinguished by the
`type` string (`"updated"` / `"deleted"`). Model it as a Pydantic discriminated union on `type` so
an unknown future event type fails validation loudly instead of being silently ignored.

### Pattern 3: Idempotent upsert — parent upsert + child replace (HEVY-03)

**Verified against PostgreSQL 18.** Three consecutive syncs of the same workout held counts at
`(workouts=1, exercises=1, sets=2)`; re-syncing an edited workout with fewer sets correctly shrank
to `(1, 1, 1)` and updated the title.

```python
from sqlalchemy.dialects.postgresql import insert as pg_insert

async def upsert_workout(session, user_id, w: HevyWorkout) -> uuid.UUID:
    stmt = pg_insert(Workout).values(
        id=uuid.uuid4(), user_id=user_id, provider="hevy", external_id=w.id,
        title=w.title, description=w.description,
        start_time=w.start_time, end_time=w.end_time,
        provider_updated_at=w.updated_at,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Workout.user_id, Workout.provider, Workout.external_id],
        set_={
            "title": stmt.excluded.title,
            "description": stmt.excluded.description,
            "start_time": stmt.excluded.start_time,
            "end_time": stmt.excluded.end_time,
            "provider_updated_at": stmt.excluded.provider_updated_at,
        },
    ).returning(Workout.id)
    workout_id = (await session.execute(stmt)).scalar_one()

    # Children have NO stable upstream id (only `index`), so they cannot be
    # upserted individually. Replace the whole set. ON DELETE CASCADE removes sets.
    await session.execute(
        delete(WorkoutExercise).where(WorkoutExercise.workout_id == workout_id)
    )
    for ex in w.exercises:
        ex_id = uuid.uuid4()
        await session.execute(insert(WorkoutExercise).values(
            id=ex_id, workout_id=workout_id, exercise_index=ex.index,
            title=ex.title, notes=ex.notes,
            exercise_template_external_id=ex.exercise_template_id,
            supersets_id=ex.supersets_id,
        ))
        if ex.sets:
            # executemany — verified 44x faster than row-by-row (see Pattern 10)
            await session.execute(insert(WorkoutSet), [
                {"id": uuid.uuid4(), "workout_exercise_id": ex_id,
                 "set_index": s.index, "set_type": s.type,
                 "weight_kg": s.weight_kg, "reps": s.reps,
                 "distance_meters": s.distance_meters,
                 "duration_seconds": s.duration_seconds,
                 "rpe": s.rpe, "custom_metric": s.custom_metric}
                for s in ex.sets
            ])
    return workout_id
```

Required constraint: `UNIQUE(user_id, provider, external_id)` on `workouts`. `ON CONFLICT` needs a
real unique index — without it Postgres raises
`there is no unique or exclusion constraint matching the ON CONFLICT specification`.

### Pattern 4: Deletion via cascade (HEVY-04)

**Verified:** deleting one workout took the DB from `(2, 2, 3)` to `(1, 1, 2)` — its own children
went, the sibling workout was untouched.

```python
WorkoutExercise.workout_id  -> ForeignKey("workouts.id", ondelete="CASCADE")
WorkoutSet.workout_exercise_id -> ForeignKey("workout_exercises.id", ondelete="CASCADE")
```

Deleting a workout that was never synced is a no-op, not an error — required, because the events
feed can report a deletion for a workout created and deleted between two syncs.

### Pattern 5: Per-page commit (D-08 + HEVY-08)

**Verified:** page 1 committed, page 2 raised mid-write, rollback → page 1's rows all survived and
page 2's were entirely absent.

```python
async for page_num, workouts in iter_workout_pages(client, start_page=checkpoint.page):
    async with sessionmaker() as session:
        for w in workouts:
            await upsert_workout(session, user_id, w)
        await advance_checkpoint(session, resource="workouts", page=page_num + 1)
        await session.commit()          # page + checkpoint commit atomically
```

Commit the checkpoint **in the same transaction** as the page's rows. Two transactions can
interleave into a checkpoint that claims work that was rolled back.

### Pattern 6: SAVEPOINT to quarantine one malformed record

**Verified:** of three workouts where the middle one raised, 2 persisted, 1 was skipped, and the
session stayed usable for the commit. Without a savepoint, PostgreSQL aborts the whole transaction
and every later statement fails with `current transaction is aborted`.

```python
skipped = []
for w in workouts:
    try:
        async with session.begin_nested():        # SAVEPOINT
            await upsert_workout(session, user_id, w)
    except (ValidationError, DataError) as exc:
        skipped.append(w.id)
        log.warning("hevy.workout.skipped", workout_id=w.id, reason=type(exc).__name__)
await session.commit()
```

This is what makes "malformed responses" (blueprint §7) survivable rather than fatal, and it is the
mechanism behind success criterion 3.

### Pattern 7: Per-resource sync bookkeeping (HEVY-09 + D-08)

HEVY-09 requires each *data source* to report `last_synced_at`, and this phase has three
independent ones with independent cursors. One row per `(user_id, provider, resource)`:

```python
class SyncState(Base, TimestampMixin):
    __tablename__ = "sync_state"
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(32))          # 'hevy'
    resource: Mapped[str] = mapped_column(String(32))          # 'workouts'|'exercise_templates'|'body_measurements'
    last_synced_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    cursor_timestamp: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))  # events `since`
    cursor_page: Mapped[int | None] = mapped_column(Integer)   # D-08 full-sync resume
    status: Mapped[str] = mapped_column(String(16), server_default="idle")  # idle|running|error
    last_error: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("user_id", "provider", "resource",
                                       name="uq_sync_state_user_provider_resource"),)
```

**On the credential-storage discretion — recommendation: confirm the bookkeeping-only approach.**
Nothing found in this research argues for encrypted credential storage now. Hevy uses a single
static `api-key` header, `Settings.hevy_api_key` already exists as a `SecretStr` and is already
wired into all three redaction layers, and the blueprint explicitly sanctions an env-var secret for
a personal deployment. Adding an `encrypted_credentials` column would introduce key-management
surface for zero v1 benefit and would put a decryptable secret one SQL query away from the MCP
server. **Name the table `sync_state`, not `external_connections`** — the blueprint's name implies
credential storage this table deliberately does not do. `last_error` should store an exception
*class name and message*, never a response body, since a Hevy error body could echo the request.

### Pattern 8: Effective muscle mapping with auditable override (NORM-02, NORM-03)

```python
class ExerciseMuscle(Base):            # curated base — D-02, seeded from normalization/
    __tablename__ = "exercise_muscles"
    exercise_template_external_id: Mapped[str] = mapped_column(String(64))
    muscle_group: Mapped[str] = mapped_column(String(32))     # canonical, 19 values
    role: Mapped[str] = mapped_column(String(16))             # 'direct' | 'indirect'
    source: Mapped[str] = mapped_column(String(16))           # 'hevy' | 'curated'

class ExerciseMuscleOverride(Base, TimestampMixin):   # D-04 — base is NEVER mutated
    __tablename__ = "exercise_muscle_overrides"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    exercise_template_external_id: Mapped[str] = mapped_column(String(64))
    muscle_group: Mapped[str] = mapped_column(String(32))
    role: Mapped[str] = mapped_column(String(16))
    note: Mapped[str | None] = mapped_column(Text)            # why the override exists
```

**⚠️ The subtle design decision the planner must get right.** Resolve the override
**per-template, not per-muscle-row**:

> If *any* override row exists for a template, the override set **replaces** the base set entirely.
> If none exists, the base set applies.

A per-row merge would let you *add* or *modify* a muscle but never **remove** one — so the common
correction "this exercise does not actually work rear delts" would be unexpressible. Replacement
semantics also keep NORM-02's audit trivial: both sets are intact and diffable side by side.

**NORM-03: store the role, never the weight.** The 1.0/0.5 weighting is a query-time parameter
(Phase 4), per both NORM-03 ("configurable weighting applied at query time") and blueprint §18
("Make this configurable rather than hard-coded"). A `weight` column would freeze it into the data.

**D-03 unmapped handling:** a template with no rows in either table is simply unmapped. Prefer that
natural absence over a `mapping_status` enum that has to be kept in sync — "unmapped" then cannot
drift from reality. Expose it as a view/query (`templates with no effective mapping`) so curation
gaps are visible without blocking any sync.

### Pattern 9: Body measurements keyed by date (HEVY-07, corrects D-07)

```python
class BodyMeasurement(Base, TimestampMixin):
    __tablename__ = "body_measurements"
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(16))       # D-06: 'hevy' | 'manual'
    measured_on: Mapped[dt.date] = mapped_column(Date)    # calendar date — NOT a timestamp
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    lean_mass_kg: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    fat_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    # ... 14 circumference columns, all Numeric(6,2), all nullable
    __table_args__ = (UniqueConstraint("user_id", "source", "measured_on",
                                       name="uq_body_measurements_user_source_date"),)
```

Key points:
- **The unique key is `(user_id, source, measured_on)` — the whole row, not per-metric.** This
  corrects D-07's fallback, which assumed a per-metric key. Hevy returns one row per date carrying
  all 17 metrics.
- **No `external_id` column is meaningful for Hevy** — the API has no ID. D-06's nullable
  `external_id` can stay for future providers but will always be NULL for `source='hevy'`.
- **`measured_on` is a `Date`, not a `TIMESTAMPTZ`.** Hevy's field is `format: date`. Storing a
  timestamp would require inventing a time-of-day. This does not violate FOUND-04: a calendar date
  is not an instant. Parse with `datetime.date.fromisoformat(...)` — verified that
  `datetime.datetime.fromisoformat("2024-08-14")` returns a **naive datetime**, which Ruff's `DTZ`
  rules and `app.core.time._require_aware` both correctly reject.
- **Unit normalisation:** rename Hevy's seven unsuffixed fields (`abdomen`, `waist`, `hips`,
  `left_thigh`, `right_thigh`, `left_calf`, `right_calf`) to `*_cm` locally for consistency with
  the other seven and with blueprint §41. `[ASSUMED: these are centimetres — Hevy does not declare
  the unit for them; highly likely given the sibling `_cm` fields and Hevy's metric-normalised
  API, but confirm against real data on the first sync]`

### Pattern 10: Bulk insert for the full-sync write path

**Verified benchmark on PostgreSQL 18** (12,000 set rows — roughly 500 workouts × 6 exercises × 4 sets):

| Approach | Time |
|---|---|
| row-by-row `insert().values(**row)` | ~2.7 s (extrapolated from 1,000 rows in 0.221 s) |
| `session.execute(insert(table), [dict, ...])` | **0.061 s — 44× faster** |

Pass a list of dicts as the second argument to `session.execute()` to get executemany. Worth doing
for `sets`, which is by far the highest-cardinality table.

### Anti-Patterns to Avoid

- **Upserting exercises/sets individually by `(workout_id, index)`.** Looks reasonable, but if an
  edited workout has *fewer* sets than before, the surplus old rows survive and inflate every volume
  figure downstream. Delete-and-reinsert is the only correct shape given no stable child IDs.
- **Advancing the events cursor while paging.** Silently loses data. See Pitfall 1.
- **One transaction for the entire full sync.** Violates D-08 and turns a transient network blip on
  page 40 into 39 pages of discarded work.
- **`Float` for weight/tonnage.** Verified `0.1 + 0.2 != 0.3`; use `Numeric`.
- **A hard FK from `workout_exercises` to `exercise_templates`.** A workout can reference a template
  that is missing locally (custom template deleted upstream, or templates not yet synced). Store the
  external id as a plain string; resolve to a template row via a **nullable** association. This is
  what makes D-03 structurally true rather than aspirational.
- **Retrying 401/403/400.** Verified that these must bypass the retry predicate — retrying an auth
  failure burns the backoff budget and delays a clear error into an opaque timeout.
- **Storing the direct/indirect weight in a column.** Violates NORM-03 and blueprint §18.
- **Letting a Pydantic Hevy schema leak past `integrations/hevy/`.** Violates HEVY-05.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Retry with backoff + jitter | `for i in range(3): await asyncio.sleep(2**i)` | `tenacity.AsyncRetrying` | Jitter, per-exception predicates, `reraise`, attempt introspection, `before_sleep` hooks. Verified working with httpx2 across 5 scenarios. |
| Idempotent insert | `SELECT` then `INSERT`/`UPDATE` | `ON CONFLICT DO UPDATE` | The read-then-write is a race and needs two round trips. The DB does it atomically in one. |
| Cascading deletes | Manual child deletes in Python | `ondelete="CASCADE"` | Verified atomic; cannot half-delete. Python-side ordering bugs leave orphan sets. |
| Partial-failure isolation | Try/except around a plain statement | `session.begin_nested()` SAVEPOINT | In PostgreSQL a failed statement poisons the whole transaction; only a SAVEPOINT rolls back just the bad record. |
| Mocking the Hevy API | A hand-written fake `AsyncClient` | `pytest-httpx2` or `httpx2.MockTransport` | A hand-rolled fake tests your fake, not your client's real header/timeout/retry behaviour. |
| ISO 8601 parsing | `strptime` with a format string | `datetime.fromisoformat` | Verified py3.13 handles `Z`, `+00:00` and fractional seconds. `strptime("%Y-%m-%dT%H:%M:%SZ")` returns a **naive** datetime and drops fractional seconds. |
| Timezone bucketing | New tz helpers | `app.core.time` | Already exists, already enforces awareness, already tested. |
| Secret redaction in logs | Ad-hoc masking at call sites | `app.logging` pipeline | Three verified layers already in place — but add `api-key` to `DENY_KEYS` (Pitfall 9). |
| Exact decimal arithmetic | `round(float, 2)` | `Numeric` / `Decimal` | Verified `Numeric(7,3)` round-trips exactly; float does not. |

**Key insight:** every one of this phase's genuinely hard problems — atomic idempotency, partial
failure isolation, cascading deletion, backoff — is a solved problem in PostgreSQL or tenacity. The
code that deserves real thought is the *event-drain ordering* and the *muscle-mapping resolution
rule*, because those are domain logic no library can supply.

## Common Pitfalls

### Pitfall 1: Advancing the events cursor mid-drain silently destroys data
**What goes wrong:** The sync reports success, imports a handful of events, and permanently loses
the rest. No error anywhere.
**Why it happens:** `/v1/workouts/events` returns newest→oldest and re-windows on every call. Moving
`since` forward after page 1 means pages 2..N — which hold *older* events — fall outside the new
window and are never fetched.
**Verified by simulation** `[VERIFIED: 8-event fixture, 2026-08-29]`:

```
total events on server : 8
expected final state   : {'w0': 6, 'w2': 5}
NAIVE   -> events applied= 2  state={'w0': 6}              MATCH=False
CORRECT -> events applied= 8  state={'w0': 6, 'w2': 5}     MATCH=True
```

The naive run applied 2 of 8 events and dropped workout `w2` **entirely**.
**How to avoid:** Pattern 2 — freeze `since`, drain every page, sort oldest-first, apply, then
advance the cursor once.
**Warning signs:** Event count applied is suspiciously close to `pageSize`. A workout edited in
Hevy long ago never updates locally.

### Pitfall 2: Applying events newest-first corrupts multiply-updated workouts
**What goes wrong:** A workout edited twice since the last sync ends up holding the *older* payload.
**Why it happens:** Each `UpdatedWorkout` event carries a full workout snapshot. Applying in arrival
order (newest first) means the older snapshot lands last and wins.
**How to avoid:** Sort by event timestamp ascending before applying — the second half of Pattern 2.
**Warning signs:** Local workout content matches a stale version despite a "successful" sync.

### Pitfall 3: `pytest-httpx2` rejects `httpx2.Response` objects
**What goes wrong:** A retry test dies with an opaque
`AssertionError: assert isinstance(resolved.response, httpx.Response)` pointing into
`respx/router.py`, with no hint that the *type* is the problem.
**Why it happens:** `pytest-httpx2` is a thin adapter over `respx`, and respx internally asserts on
`httpx` **0.x** `Response` objects while the client receives `httpx2` ones.
**Verified — this fails:**
```python
route.side_effect = [httpx2.Response(429), httpx2.Response(200)]   # AssertionError
```
**Verified — these all work:**
```python
import httpx          # the 0.x package, dev-only, pulled in transitively by respx
route.side_effect = [httpx.Response(429), httpx.Response(200, json={"ok": True})]
httpx2_mock.get(URL).mock(side_effect=[httpx.Response(500), httpx.Response(200)])
httpx2_mock.get(URL).mock(side_effect=httpx2.ConnectError("drop"))   # exceptions use httpx2 types
httpx2_mock.get(URL, params={"page": 1}).respond(json={...})         # param matching works
```
**The rule:** **responses** use `httpx.Response`; **exceptions** use `httpx2` exception types.
**How to avoid:** Put this in a comment in `conftest.py`. Or sidestep entirely with
`httpx2.MockTransport`, verified working with pure httpx2 types throughout.

### Pitfall 4: `ON CONFLICT ... where=` returns no row, breaking the child write
**What goes wrong:** `scalar_one()` raises `NoResultFound` on workouts that were skipped as stale.
**Why it happens:** A `where=` guard (e.g. only update when `excluded.provider_updated_at` is newer)
suppresses the update, so `RETURNING` emits nothing.
**Verified:** with the guard active, `RETURNING` produced `None` and the existing title was
preserved — correct behaviour, but the caller must expect it.
**How to avoid:** If you add a staleness guard, use `scalar_one_or_none()` and re-`SELECT` the id
when it is `None`. Simplest for v1: **omit the guard** — Hevy is the source of truth and an
unconditional update is always correct here.

### Pitfall 5: `/v1/body_measurements` returns 404 for an out-of-range page
**What goes wrong:** A `while True: page += 1` loop treats the 404 as a fatal error and the sync run
is marked failed even though it fetched everything.
**Why it happens:** Unlike `/v1/workouts` (which returns `400` for a bad page), the body-measurements
endpoint documents **`404 "Page not found"`**. `[VERIFIED: live OpenAPI]`
**How to avoid:** Loop on `page < page_count`, and treat a 404 from this endpoint as a normal
terminator, never as a retryable failure.

### Pitfall 6: Assuming `pageSize=10` everywhere
**What goes wrong:** Exercise-template sync makes ~40+ requests instead of ~5, needlessly burning
against an unknown rate limit.
**Why it happens:** `/v1/workouts`, `/v1/workouts/events` and `/v1/body_measurements` cap at 10, but
**`/v1/exercise_templates` caps at 100.** `[VERIFIED: live OpenAPI]`
**How to avoid:** Per-endpoint page-size constants, not one module-level `PAGE_SIZE = 10`.

### Pitfall 7: Retrying 401/403 as if transient
**What goes wrong:** A revoked API key produces a long backoff sequence and then an opaque timeout
instead of an immediate, obvious auth error.
**Why it happens:** A naive predicate like "retry on any non-2xx".
**Verified:** with a correct predicate, a 401 consumed exactly **1** call and raised immediately,
while 429/500/`ConnectError` were retried and recovered.
**How to avoid:** Map status → exception in the client, and scope `retry_if_exception_type` to
`(HevyRateLimited, HevyServerError, httpx2.TransportError)` only.

### Pitfall 8: New models absent from `app/db/models/__init__.py`
**What goes wrong:** `alembic revision --autogenerate` emits an **empty migration with no error**.
**Why it happens:** `migrations/env.py` imports `app.db.models` to populate `Base.metadata`; a model
not re-exported there is invisible. Both files already warn about this in their docstrings.
**How to avoid:** Add every new model to `app/db/models/__init__.py` and `__all__`. The existing
integration test `test_no_pending_model_drift` (which runs `alembic check`) catches it — but only in
the Docker-backed suite.

### Pitfall 9: The Hevy `api-key` header name is not on the log deny-list
**What goes wrong:** A log line or `httpx2` debug record that includes the literal key
`"api-key"` is not censored by Layer 2.
**Verified** `[VERIFIED: imported app.logging.DENY_KEYS, 2026-08-29]`:

| Key | In `DENY_KEYS`? |
|---|---|
| `api_key` | ✅ |
| `apikey` | ✅ |
| `x-api-key` | ✅ |
| **`api-key`** | ❌ **missing — and this is exactly the header Hevy requires** |

Layer 3 (the value scrubber) still catches it because `hevy_api_key` is in `_SECRET_FIELDS`, so this
is defence-in-depth rather than an open leak — but the deny-list exists precisely so a single layer
is never load-bearing.
**How to avoid:** Add `"api-key"` to `DENY_KEYS` and assert it in `test_secret_redaction.py`.

### Pitfall 10: `test_metadata_contains_only_users_table` will fail
**What goes wrong:** A currently-passing unit test breaks the moment the first new model lands.
**Why it happens:** `backend/tests/test_db_models.py` asserts
`set(Base.metadata.tables) == {"users"}`, documented as "D-07: `external_connections` is deferred to
Phase 3". This phase is that phase.
**How to avoid:** Plan the edit deliberately — update the assertion to the new expected table set so
it keeps guarding against accidental tables, rather than deleting the test.

### Pitfall 11: A failed statement without a SAVEPOINT poisons the transaction
**What goes wrong:** One malformed workout makes every subsequent statement in the page fail with
`current transaction is aborted, commands ignored until end of transaction block`.
**Why it happens:** PostgreSQL semantics — try/except in Python does not undo the server-side abort.
**Verified:** with `begin_nested()`, 2 of 3 workouts persisted and the session committed cleanly.
**How to avoid:** Pattern 6.

### Pitfall 12: Dumbbell weight semantics are unverified
**What goes wrong:** Every tonnage and 1RM figure for dumbbell work is off by exactly 2×.
**Why it happens:** Hevy's `weight_kg` does not document whether a dumbbell set records per-dumbbell
or combined load. Not resolvable from the spec. Carried as an open item in STATE.md.
**How to avoid:** During the first real sync, pick a known dumbbell session, compare `weight_kg`
against what the Hevy UI displays, and record the finding in STATE.md. `equipment_category ==
'dumbbell'` on the template is the discriminator if a correction factor is ever needed. **Do not
apply any factor speculatively** — store Hevy's raw value and document the semantics.

## Code Examples

### HevyClient — auth, timeouts, status mapping

```python
# Header name and format verified from the live OpenAPI: `api-key`, required, format uuid.
class HevyClient:
    BASE_URL = "https://api.hevyapp.com"
    PAGE_SIZE_WORKOUTS = 10       # verified max
    PAGE_SIZE_EVENTS = 10         # verified max
    PAGE_SIZE_BODY = 10           # verified max
    PAGE_SIZE_TEMPLATES = 100     # verified max — NOT 10

    def __init__(self, api_key: SecretStr) -> None:
        self._client = httpx2.AsyncClient(
            base_url=self.BASE_URL,
            headers={"api-key": api_key.get_secret_value()},
            timeout=httpx2.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0),
        )

    async def _get(self, path: str, **params) -> dict:
        response = await self._client.get(path, params=params)
        if response.status_code == 429:
            raise HevyRateLimited(retry_after=response.headers.get("retry-after"))
        if response.status_code in (401, 403):
            raise HevyAuthError("Hevy rejected the API key")     # never retried, never logs the key
        if response.status_code >= 500:
            raise HevyServerError(response.status_code)
        response.raise_for_status()
        return response.json()
```

Log `response.headers` keys matching `ratelimit`/`retry-after` on the first real sync — that is the
only way to resolve D-10's open question about Hevy's true limits.

### Retry wrapper — verified semantics

```python
from tenacity import (AsyncRetrying, retry_if_exception_type,
                      stop_after_attempt, wait_exponential_jitter)

RETRYABLE = (HevyRateLimited, HevyServerError, httpx2.TransportError)

async def with_retry(fn, *args, attempts: int = 5, **kwargs):
    async for attempt in AsyncRetrying(
        retry=retry_if_exception_type(RETRYABLE),
        stop=stop_after_attempt(attempts),
        wait=wait_exponential_jitter(initial=1, max=60, jitter=2),
        reraise=True,                       # surface the real error, not RetryError
    ):
        with attempt:
            return await fn(*args, **kwargs)
```

`httpx2.TransportError` is the right base class — verified that `ConnectError`, `ReadError`
(via `NetworkError`), `ConnectTimeout` and `ReadTimeout` (via `TimeoutException`) all descend from
it, while `HTTPStatusError` does **not**.

### Test — pagination, using the verified mocking rules

```python
import httpx          # 0.x — respx requires its Response type (Pitfall 3)
import httpx2         # 2.x — the client under test, and the exception types

async def test_full_sync_paginates_and_is_idempotent(httpx2_mock, session):
    httpx2_mock.get(URL, params={"page": 1}).respond(
        json={"page": 1, "page_count": 2, "workouts": [WORKOUT_A]})
    httpx2_mock.get(URL, params={"page": 2}).respond(
        json={"page": 2, "page_count": 2, "workouts": [WORKOUT_B]})
    ...

async def test_rate_limit_is_retried_then_succeeds(httpx2_mock):
    httpx2_mock.get(URL).mock(side_effect=[
        httpx.Response(429),
        httpx.Response(200, json={"page": 1, "page_count": 1, "workouts": []}),
    ])
    ...

async def test_auth_error_is_not_retried(httpx2_mock):
    route = httpx2_mock.get(URL).mock(side_effect=[httpx.Response(401), httpx.Response(200)])
    with pytest.raises(HevyAuthError):
        await client.get_workouts(page=1)
    assert route.call_count == 1        # verified: 401 consumes no retry budget
```

## Runtime State Inventory

Not applicable in full — this is a greenfield feature phase, not a rename/refactor. Recorded for
completeness because the phase does introduce persistent state and touches an existing test suite:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None pre-existing. Phase 1 seeded exactly one row: `users` id `00000000-0000-0000-0000-000000000001` (migration `0002`). New tables FK to it. | No migration of existing data. |
| Live service config | None — Verified: no scheduler, cron, or external workflow exists yet. Production sync triggering is explicitly Phase 7. | None this phase. |
| OS-registered state | None — Verified: no Task Scheduler / launchd / systemd / pm2 artefacts in the repo. | None. |
| Secrets/env vars | `HEVY_API_KEY` already declared in `Settings` (`SecretStr | None`) and in `_SECRET_FIELDS`; present in `.env.example`. **Currently unset in the working environment and no `.env` exists.** | Set `HEVY_API_KEY` before any live-sync verification. No new secret needed. |
| Build artifacts | None — no compiled artefacts or packaged distributions. `uv.lock` must be regenerated when `tenacity`/`pytest-httpx2` are added. | `uv sync` after `uv add`. |
| **Existing tests that will break** | `backend/tests/test_db_models.py::test_metadata_contains_only_users_table` asserts `set(Base.metadata.tables) == {"users"}`. | Update deliberately (Pitfall 10). |

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | Runtime | ✓ | 3.13.9 (pinned via `.python-version`) | — |
| uv | Dependency management | ✓ | 0.12.1 (meets `required-version >=0.12.1`) | — |
| Docker daemon | `testcontainers` integration suite | ✓ | 29.4.2, daemon confirmed running | — |
| PostgreSQL | Source of truth | ✓ | server 18-alpine pulled and exercised; `psql` client 18.6 | — |
| `httpx2` | Hevy client | ✓ | 2.12.0 installed | — |
| `sqlalchemy` / `mcp` / `pytest` / `testcontainers` | Existing stack | ✓ | 2.0.52 / 2.0.0 / 9.1.1 / 4.15.0 | — |
| `tenacity` | Retry (D-10) | ✗ | — | Must be added (`uv add tenacity==9.1.4`). No fallback needed — it is on PyPI, pure-Python, zero deps. |
| `pytest-httpx2` | Hevy mocking in tests | ✗ | — | `httpx2.MockTransport` (stdlib-only, verified working). |
| `gcloud` | Deployment (Phase 2 artefact) | ✓ | 578.0.0 | — |
| **Hevy API key** | Live-sync verification, empirical answers to D-10 / dumbbell-weight | **✗** | — | **No fallback for live verification.** All *automated* tests run against mocks and need no key. |
| Hevy **Pro** subscription | API access at all | **Unknown** | — | None — the API is Pro-only per Hevy's own docs. |

**Missing dependencies with no fallback:**
- `HEVY_API_KEY` is not set and no `.env` file exists. Every automated test in this phase can and
  should run against mocked responses, so this does **not** block implementation — but it *does*
  block the three questions only real data can answer: Hevy's actual rate limits (D-10),
  per-dumbbell vs combined weight (Pitfall 12), and `/v1/workouts` page ordering (Pattern 1).
  The plan should isolate these into an explicitly-manual verification step rather than letting
  them block automated tasks.
- Hevy API access requires a **Pro** subscription. If the user does not have one, this phase cannot
  be verified against live data at all. Worth confirming before execution starts.

**Missing dependencies with fallback:**
- `tenacity`, `pytest-httpx2` — both trivially installable; `pytest-httpx2` has a verified
  zero-dependency alternative.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 + pytest-asyncio 1.4.0 (`asyncio_mode = "auto"`) + pytest-cov 7.1.0 |
| Config file | `pyproject.toml` → `[tool.pytest.ini_options]` (`testpaths = ["backend/tests"]`, `pythonpath = ["backend"]`) |
| Quick run command | `uv run pytest backend/tests -x -q -m "not integration"` |
| Full suite command | `uv run pytest backend/tests -q --cov=backend/app` (Docker required) |
| Baseline (verified 2026-08-29) | **72 passed, 28 deselected in 0.75s** for the quick suite |
| Integration marker | `@pytest.mark.integration` — anything touching the Postgres container |
| Existing fixtures | `postgres_url` (session, migrated to head), `engine`, `session`, `alembic`, `restore_schema`, `client` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| HEVY-01 | Full sync pages through `/v1/workouts` until `page_count` | unit (mock) | `pytest backend/tests/test_hevy_sync.py::test_full_sync_paginates -x` | ❌ Wave 0 |
| HEVY-01 | Local workout count matches `/v1/workouts/count` | integration | `pytest backend/tests/test_hevy_sync.py::test_full_sync_reconciles_count -x` | ❌ Wave 0 |
| HEVY-02 | Event drain collects all pages before applying | unit | `pytest backend/tests/test_hevy_events.py::test_drain_collects_all_pages -x` | ❌ Wave 0 |
| HEVY-02 | **Events applied oldest-first; naive ordering is rejected** | unit | `pytest backend/tests/test_hevy_events.py::test_multiply_updated_workout_keeps_newest -x` | ❌ Wave 0 |
| HEVY-02 | Cursor advances only after the full drain | unit | `pytest backend/tests/test_hevy_events.py::test_cursor_advances_once -x` | ❌ Wave 0 |
| HEVY-03 | Three consecutive syncs produce identical row counts | integration | `pytest backend/tests/test_hevy_sync.py::test_sync_is_idempotent -x` | ❌ Wave 0 |
| HEVY-03 | Edited workout with fewer sets shrinks (no orphans) | integration | `pytest backend/tests/test_hevy_sync.py::test_edited_workout_replaces_children -x` | ❌ Wave 0 |
| HEVY-04 | Delete event removes workout + children, siblings intact | integration | `pytest backend/tests/test_hevy_sync.py::test_deleted_workout_cascades -x` | ❌ Wave 0 |
| HEVY-04 | Delete event for an unknown workout is a no-op | integration | `pytest backend/tests/test_hevy_sync.py::test_delete_unknown_is_noop -x` | ❌ Wave 0 |
| HEVY-05 | No Hevy schema type imported outside `integrations/hevy/` | unit | `pytest backend/tests/test_hevy_isolation.py -x` | ❌ Wave 0 |
| HEVY-06 | Templates sync with primary + secondary muscle groups | integration | `pytest backend/tests/test_hevy_templates.py::test_templates_sync -x` | ❌ Wave 0 |
| HEVY-06 | Template sync uses pageSize=100 | unit | `pytest backend/tests/test_hevy_client.py::test_template_page_size -x` | ❌ Wave 0 |
| HEVY-07 | All 17 body-measurement fields persist; nulls preserved | integration | `pytest backend/tests/test_hevy_body.py::test_body_measurements_sync -x` | ❌ Wave 0 |
| HEVY-07 | Re-sync upserts on `(user, source, measured_on)` | integration | `pytest backend/tests/test_hevy_body.py::test_body_measurement_idempotent -x` | ❌ Wave 0 |
| HEVY-07 | 404 on an out-of-range page terminates cleanly | unit | `pytest backend/tests/test_hevy_body.py::test_404_terminates_pagination -x` | ❌ Wave 0 |
| HEVY-08 | Mid-sync failure preserves prior committed pages | integration | `pytest backend/tests/test_hevy_resilience.py::test_partial_sync_preserves_data -x` | ❌ Wave 0 |
| HEVY-08 | Malformed workout is skipped; the rest of the page commits | integration | `pytest backend/tests/test_hevy_resilience.py::test_malformed_workout_quarantined -x` | ❌ Wave 0 |
| HEVY-08 | 429/5xx retried; 401 not retried | unit | `pytest backend/tests/test_hevy_client.py::test_retry_policy -x` | ❌ Wave 0 |
| HEVY-08 | Sync resumes from the checkpoint page | integration | `pytest backend/tests/test_hevy_resilience.py::test_resume_from_checkpoint -x` | ❌ Wave 0 |
| HEVY-09 | Each of the 3 resources reports its own `last_synced_at` | integration | `pytest backend/tests/test_sync_state.py::test_last_synced_at_per_resource -x` | ❌ Wave 0 |
| NORM-01 | Every canonical group resolvable; delt split present | unit | `pytest backend/tests/test_normalization.py::test_deltoid_split -x` | ❌ Wave 0 |
| NORM-01 | Hevy's 20 enum values all translate or are explicitly unmapped | unit | `pytest backend/tests/test_normalization.py::test_hevy_enum_coverage -x` | ❌ Wave 0 |
| NORM-02 | Override replaces base mapping; base row unchanged | integration | `pytest backend/tests/test_normalization.py::test_override_wins_and_base_preserved -x` | ❌ Wave 0 |
| NORM-02 | Override can **remove** a muscle from the effective set | integration | `pytest backend/tests/test_normalization.py::test_override_can_remove_muscle -x` | ❌ Wave 0 |
| NORM-03 | direct/indirect roles stored; 1.0/0.5 applied at query time | unit | `pytest backend/tests/test_normalization.py::test_direct_indirect_weighting -x` | ❌ Wave 0 |
| D-03 | Unmapped exercise still syncs fully | integration | `pytest backend/tests/test_normalization.py::test_unmapped_exercise_still_syncs -x` | ❌ Wave 0 |
| FOUND-05 | `api-key` never appears in any log record | unit | `pytest backend/tests/test_secret_redaction.py -x` | ✅ exists — extend |

### Sampling Rate

- **Per task commit:** `uv run pytest backend/tests -x -q -m "not integration"` (baseline 0.75 s)
- **Per wave merge:** `uv run pytest backend/tests -q` (full suite, Docker required)
- **Phase gate:** full suite green + `uv run ruff check .` + `uv run mypy backend/app` before
  `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `uv add tenacity==9.1.4` and `uv add --group dev pytest-httpx2==1.0.0`
- [ ] `backend/tests/fixtures/hevy/` — canned response fixtures built from the **verified** live
      schemas in this document (workout page, events page with both event variants, template page,
      body-measurement page). Do **not** hand-write these from the blueprint; it is wrong about
      `rir`/`weight_unit`/child IDs.
- [ ] `backend/tests/conftest.py` — add a `hevy_client` fixture, and a comment recording the
      Pitfall 3 rule (`httpx.Response` for responses, `httpx2` types for exceptions)
- [ ] `backend/tests/test_hevy_client.py` — client transport, headers, page sizes, retry policy
- [ ] `backend/tests/test_hevy_sync.py` — HEVY-01, HEVY-03, HEVY-04
- [ ] `backend/tests/test_hevy_events.py` — HEVY-02 (the highest-risk logic in the phase)
- [ ] `backend/tests/test_hevy_templates.py` — HEVY-06
- [ ] `backend/tests/test_hevy_body.py` — HEVY-07
- [ ] `backend/tests/test_hevy_resilience.py` — HEVY-08
- [ ] `backend/tests/test_hevy_isolation.py` — HEVY-05 boundary assertion
- [ ] `backend/tests/test_normalization.py` — NORM-01/02/03, D-03
- [ ] `backend/tests/test_sync_state.py` — HEVY-09
- [ ] Update `backend/tests/test_db_models.py::test_metadata_contains_only_users_table` (Pitfall 10)
- [ ] Extend `backend/tests/test_secret_redaction.py` for the `api-key` header (Pitfall 9)

Framework install: none needed — pytest, pytest-asyncio, pytest-cov and testcontainers are all
present and the suite is green.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no (inbound) / **yes (outbound)** | This phase adds no inbound auth. It adds an **outbound** credential: the Hevy `api-key` header. Sourced from `Settings.hevy_api_key` (`SecretStr`), never a literal. |
| V3 Session Management | no | No sessions introduced. Sync is a batch process. |
| V4 Access Control | yes (data scoping) | Every new table carries `user_id` and every query filters on it. A missing filter would cross-scope data the moment a second user exists. |
| V5 Input Validation | **yes** | All Hevy responses validated through Pydantic before touching the DB. This is the primary defence against malformed upstream data (blueprint §7). |
| V6 Cryptography | no | **Recommendation: keep it that way.** Declining `encrypted_credentials` (Pattern 7) avoids introducing key management with no v1 benefit. |
| V7 Error Handling & Logging | **yes** | Sync lifecycle logging via structlog (blueprint §44). `last_error` stores an exception class + message, never a response body. **`api-key` must be added to `DENY_KEYS`** (Pitfall 9). |
| V8 Data Protection | yes | Workout and body-composition data is personal health data. It must never leave via a log line; the existing three-layer pipeline covers this once Pitfall 9 is fixed. |
| V13 API & Web Service | yes (as client) | TLS to `https://api.hevyapp.com`; explicit timeouts on every request (an unbounded read hangs a sync run forever). |

### Known Threat Patterns for Python / async HTTP client → PostgreSQL

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| API key leaked into logs or an error payload | Information Disclosure | `SecretStr` + `DENY_KEYS` (add `api-key`) + value scrubber. Never interpolate the key into a message. |
| SQL injection via workout title / exercise notes | Tampering | SQLAlchemy Core/ORM parameter binding throughout. Never f-string a Hevy value into `text()`. |
| Malformed upstream response corrupting the DB | Tampering | Pydantic validation + SAVEPOINT quarantine (Pattern 6). |
| Unbounded response body exhausting memory | Denial of Service | pageSize is capped by the API (10/100); set explicit `httpx2.Timeout` and do not stream unbounded. |
| Retry storm amplifying a Hevy outage | Denial of Service | `wait_exponential_jitter` + `stop_after_attempt`; jitter avoids synchronised retries. |
| Unicode/emoji in titles (Hevy's own example is `"Morning Workout 💪"`) | Tampering / availability | UTF-8 end to end; `String` columns sized generously. Verified Postgres handles it, but do not truncate blindly. |
| Cross-user data exposure once multi-user exists | Information Disclosure | `user_id` on every table and in every unique constraint from day one. |
| Health data reaching an MCP response | Information Disclosure | Out of scope this phase (Phase 6), but the schema should not embed secrets anywhere a tool could read them — another argument against a credentials column. |

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Blueprint §8's `rir` / `weight_unit` / `weight` set fields | Live API has `rpe`, `weight_kg`, no `rir`, no `weight_unit` | Blueprint predates the live spec | Model the live schema. RPE is free and unlocks AN-V1X-03 later. |
| Blueprint §6: "Hevy currently exposes `/v1/workouts`, `/v1/workouts/count`, `/v1/workouts/events`" | 22 operations across workouts, routines, exercise templates, routine folders, exercise history and body measurements | Hevy expanded the API | `/v1/exercise_templates` and `/v1/body_measurements` — both required by this phase — are not in the blueprint's list at all. |
| CLAUDE.md: "`respx`/`pytest-httpx` cannot intercept `httpx2`" | `pytest-httpx2` 1.0.0 (May 2026), authored by respx's own maintainer, **does** intercept httpx2 | 2026-05-20 | Verified working. Direct `respx`/`pytest-httpx` use is still wrong; the wrapper is correct. Note the `httpx.Response` type requirement (Pitfall 3). |
| "All Hevy endpoints cap pageSize at 10" | `/v1/exercise_templates` caps at **100** | — | ~8× fewer requests for template sync. |
| D-07's assumed per-metric body-measurement key | Actual key is the **calendar date**, one row, 17 metrics, no ID | — | Corrects the unique constraint to `(user_id, source, measured_on)`. |

**Deprecated/outdated:**
- `BRETT blueprint.md` §8 as a schema source — superseded by the live OpenAPI captured above.
- CLAUDE.md's respx/httpx2 rationale — the conclusion still holds, the reasoning does not.
- `httpx` 0.x as a *runtime* dependency — it appears only transitively in the dev group.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The 19-group canonical muscle list (D-01 ∪ blueprint §18 ∪ Hevy's abductors/adductors) is the right reconciliation | Muscle Taxonomy | Medium — changing the enum later means a data migration of `exercise_muscles`. **Cheap to confirm with the user before implementation.** |
| A2 | Hevy's seven unsuffixed body-measurement fields (`waist`, `hips`, `abdomen`, thighs, calves) are centimetres | Pattern 9 | Low-Medium — all body-circumference trends would be wrongly scaled. Confirm on the first real sync. |
| A3 | `/v1/workouts` returns newest-first | Pattern 1 | Low — analysis shows additions cannot cause a skip in either ordering; only affects resume-page stability. Verify empirically. |
| A4 | Hevy returns HTTP 429 (not 403 or a 200 with an error body) when rate limiting | HevyClient, D-10 | Medium — a wrong status mapping means no backoff. Mitigate by treating *any* unexpected 4xx≥429 as retryable-once and logging the raw status + headers on the first live sync. |
| A5 | The events feed retains history long enough for realistic sync gaps | D-09 (user-accepted) | Medium — a long outage could leave a deleted workout lingering. Already an accepted risk; `/v1/workouts/count` is a cheap detector. |
| A6 | Hevy `updated_at` on a workout changes on every edit | Pattern 2 | Low — if it did not, the events feed itself would not work. |
| A7 | The user holds a Hevy **Pro** subscription (API access is Pro-only) | Environment Availability | **High if wrong — the phase cannot be verified against live data at all.** Confirm before execution. |
| A8 | `HEVY_API_KEY` will be available for manual verification | Environment Availability | Medium — automated tests are fully mocked and unaffected; only the live-data checks are blocked. |

## Open Questions

1. **What are Hevy's real rate limits?**
   - What we know: nothing is documented — verified by exhaustive keyword scan of the live spec.
   - What's unclear: requests/minute, whether `429` is even the status used, whether `Retry-After`
     or `RateLimit-*` headers are returned.
   - Recommendation: proceed with D-10's reactive backoff. Log every response header matching
     `ratelimit|retry-after` during the first full sync and record the finding in STATE.md. Do not
     add proactive throttling on a guess.

2. **Is dumbbell `weight_kg` per-dumbbell or combined?**
   - What we know: `equipment_category: 'dumbbell'` exists on the template; `weight_kg` is
     undocumented as to semantics.
   - What's unclear: the factor.
   - Recommendation: store Hevy's raw value unmodified. Compare one known session against the Hevy
     UI during first-sync verification and document the answer. **Never apply a speculative 2×.**

3. **Should the canonical list include `upper_back`, `abductors`, `adductors` (A1)?**
   - What we know: blueprint §18 wants `upper_back`; D-01 omits it; Hevy supplies all three free.
   - What's unclear: whether the user wants them in muscle-volume output.
   - Recommendation: include them (recommended 19-group list). Worth a one-line confirmation during
     planning, since the enum is expensive to change after data exists.

4. **Does the user have Hevy Pro (A7)?**
   - Recommendation: confirm before execution. If not, the phase can still be *built and fully
     tested* against mocks, but success criteria 1-3 cannot be demonstrated on real data.

5. **How should `full_body` / `cardio` templates be treated?**
   - What we know: both are valid Hevy `MuscleGroup` values that map to no canonical group.
   - Recommendation: treat as unmapped (D-03) rather than fanning `full_body` out to every muscle —
     fan-out would silently inflate every volume figure. Flag for the user if they log cardio in Hevy.

## Sources

### Primary (HIGH confidence)
- **`https://api.hevyapp.com/docs/` live OpenAPI 3.0.0** (`swagger-ui-init.js`, downloaded and
  JSON-parsed 2026-08-29) — all 22 operations, `api-key` header auth, per-endpoint page-size caps,
  and verbatim `Workout` / `Set` / `Exercise` / `ExerciseTemplate` / `BodyMeasurement` /
  `PaginatedWorkoutEvents` / `UpdatedWorkout` / `DeletedWorkout` / `MuscleGroup` /
  `EquipmentCategory` / `CustomExerciseType` schemas. **The single strongest source in this document.**
- **Live PostgreSQL 18-alpine container** (2026-08-29) — six persistence patterns executed and
  asserted: repeated-sync idempotency, child-shrink on edit, cascade delete isolation, per-page
  commit survival, SAVEPOINT quarantine, and `where=`-guarded `ON CONFLICT` returning no row.
  Plus a 12,000-row executemany benchmark and `Numeric` vs `Float` round-trip comparison.
- **Live `uv lock` + pytest runs in a clean project** (2026-08-29) — `pytest-httpx2` genuinely
  intercepts `httpx2`; the `httpx.Response`-vs-`httpx2.Response` constraint; 5 tenacity retry
  scenarios (429→200, 500→200, ConnectError→200, 401 not retried, exhaustion reraises); the exact
  14-package resolution pulling httpx 0.28.1 transitively.
- **Event-drain simulation** (2026-08-29) — naive vs correct algorithm over an 8-event
  newest-to-oldest feed; naive applied 2/8 and lost a workout.
- **PyPI JSON API** (2026-08-29) — `tenacity` 9.1.4, `pytest-httpx2` 1.0.0, `httpx2` 2.12.0,
  `respx` 0.23.1, `stamina` 26.1.0: versions, upload dates, `requires_python`, `requires_dist`.
- **`yuhonas/free-exercise-db`** `dist/exercises.json` (downloaded 2026-08-29) — 873 exercises;
  17-value flat muscle vocabulary with no deltoid split; 127 shoulders-primary (15%).
- **Context7 `/websites/sqlalchemy_en_20`** — `on_conflict_do_update` / `excluded` / `where` /
  `RETURNING` API reference, corroborating the empirical results.
- **Local codebase** (read 2026-08-29) — `app/config.py`, `app/db/base.py`, `app/db/session.py`,
  `app/db/models/__init__.py`, `app/logging.py` (`DENY_KEYS` gap verified by import),
  `app/core/time.py`, `migrations/env.py`, `migrations/versions/0001_initial_schema.py`,
  `tests/conftest.py`, `tests/test_db_models.py`, `pyproject.toml`, `README.md`,
  `.pre-commit-config.yaml`. Test baseline: 72 passed / 28 deselected in 0.75 s.
- **`BRETT blueprint.md`** §5.2, §6, §7, §8, §9, §18, §41, §42, §43.

### Secondary (MEDIUM confidence)
- `github.com/chrisdoc/hevy-mcp` — third-party Hevy client; "Hevy API returns 401: the key is
  invalid, expired, revoked, or misconfigured" and "no delete endpoints" (both consistent with the
  live spec, but not spec-documented).
- `hevyapp.com/features/exercise-library` — "400+ high-quality exercises" (marketing copy; used
  only to size the curation estimate).

### Tertiary (LOW confidence)
- General web search for Hevy rate limits — returned **no** Hevy-specific results. Recorded as
  corroboration that the limits are genuinely undocumented, not as a positive finding.

## Metadata

**Confidence breakdown:**
- Hevy API schemas / endpoints / page-size caps: **HIGH** — parsed from the live OpenAPI document,
  not from training data or the blueprint.
- Persistence patterns (idempotency, cascade, savepoint, per-page commit): **HIGH** — every pattern
  executed and asserted against real PostgreSQL 18.
- Events algorithm: **HIGH** — the failure mode was reproduced in simulation, not merely reasoned about.
- Retry / mocking stack: **HIGH** — installed and exercised; the `httpx.Response` gotcha was found
  by hitting it.
- Muscle taxonomy (no public delt split; only 2 of 20 enum values need curation): **HIGH** on the
  facts, **MEDIUM** on the recommended 19-group reconciliation (A1 — a judgement call, not a finding).
- Rate limits, dumbbell semantics, page ordering: **LOW** — undocumented by design; flagged as
  empirical-verification tasks rather than guessed.

**Research date:** 2026-08-29
**Valid until:** 2026-09-28 (30 days). Shorten to 7 days for the Hevy API specifically — its own
docs warn the structure may change without notice, and `info.version` is still `0.0.1`.
