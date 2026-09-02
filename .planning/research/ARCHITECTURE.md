# Architecture Research

**Domain:** Personal fitness data platform — extending a shipped FastAPI/PostgreSQL/MCP backend with inbound webhook ingestion, a metric shift, report composition, and a first write path
**Researched:** 2026-09-02
**Confidence:** HIGH on existing architecture and Apple Health data availability (read from source and from the user's own export); MEDIUM on the Health Auto Export wire contract (vendor docs are thin and version-split)

---

## Executive Summary

Four of the five v2.0 capabilities fit the existing architecture without bending it. One does not, and one is riskier than it reads.

**Fits cleanly:** Apple Health ingestion is a new `integrations/` package plus a new FastAPI route — the same provider-isolation shape `integrations/hevy/` already has, just with the arrow reversed (inbound POST instead of outbound poll). Report tools are largely a new response-shaping layer over analytics functions that already exist and already compose (`fitness_get_training_summary` is proof the pattern works). Manual body-measurement entry is a write into a table whose `source='manual'` column and precedence rule were both built in v1.0 and are dead code today.

**Does not fit without deliberate change:** the confirm-gated write tool. `app/mcp/` read-only-ness is not a convention — it is enforced by a PostgreSQL `READ ONLY` transaction at runtime *and* by three static source-scanning tests that fail the fast suite on any write construct anywhere under `app/mcp/`. Adding one write tool means changing those guards, and the right change is a one-module allowlist (so "exactly one MCP module can write" stays machine-checked), not deletion.

**Riskier than it reads:** the max-weight strength shift. The data plumbing is trivial — `best_set_per_day` already computes `best_weight_kg` for every session, so it is a second projection of an existing fold, no new query. The risk is in the thresholds. The 2%-per-session plateau band and the 0.5%-per-week trend band are *derived from each other* on purpose, so the two verdicts cannot contradict each other by construction. Estimated 1RM is a continuous value where a 2% dead-band is meaningful. Max weight moves in discrete plate increments — 2% of a 60 kg lift is 1.2 kg, below the smallest plate you can add. Both bands must be re-derived against discrete increments while preserving their shared derivation, with live-data validation like the original calibration got.

**The finding that should reshape scope:** the user's Apple Health export contains **zero** heart-rate, HRV, VO2max, blood-oxygen or respiratory-rate records across 438,649 samples spanning 2022-03 to 2026-08. The types are absent entirely — there is no Apple Watch. Sleep is 2,411 rows of `InBed` only (no stages) and **stopped on 2024-11-30**. `appleExerciseTime` is 0 in all 1,443 ActivitySummary rows. And 218 of 221 Apple Health *workouts* originate from Hevy — data BRETT already owns at set-level detail. What Apple Health actually adds is steps, active/basal energy, walking distance and flights climbed, all current through 2026-08-26. "Recovery trends" has no data source and should be cut or explicitly deferred rather than built against nothing.

---

## Existing Architecture (fixed — establishing the baseline the new work attaches to)

### System Overview

```
┌───────────────────────────────────────────────────────────────────────┐
│                    Google Cloud Run (1 service, --max=2, 512Mi)       │
│                        --allow-unauthenticated, HTTP/1, :8080         │
├───────────────────────────────────────────────────────────────────────┤
│  RateLimitMiddleware   (pure ASGI, global token bucket 30/min,        │
│                         exempt: /health, /.well-known/)               │
│  CorrelationIdMiddleware                                              │
├───────────────────────────────────────────────────────────────────────┤
│  FastAPI router (matched first)     │  app.mount("/", mcp_app)        │
│   └── GET /health                   │   └── POST /mcp                 │
│                                     │   └── /.well-known/oauth-       │
│                                     │        protected-resource/mcp   │
│                                     │  WorkOS AuthKit RS256 JWT       │
│                                     │  (aud pinned to Resource Ind.)  │
├───────────────────────────────────────────────────────────────────────┤
│  app/mcp/tools/*  — 13 tools, one shared READ_ONLY ToolAnnotations    │
│                     read_only_session() → PG "READ ONLY" transaction  │
├───────────────────────────────────────────────────────────────────────┤
│  app/analytics/*  — pure, deterministic, Decimal-only, never writes   │
│    volume  frequency  progression  records  comparison  bodyweight    │
│    recomposition  rollup  estimates  metadata(freshness+coverage)     │
├───────────────────────────────────────────────────────────────────────┤
│  app/normalization/   app/db/repositories/   app/core/time            │
├───────────────────────────────────────────────────────────────────────┤
│  app/db/models/  →  Neon PostgreSQL (async, asyncpg)                  │
└───────────────────────────────────────────────────────────────────────┘
        ▲
        │  Cloud Run Job (6-hourly) — python -m app.cli sync-hevy
        │  app/integrations/hevy/  (outbound httpx2 → api.hevyapp.com)
```

### Boundaries that are statically enforced (not conventions)

These are asserted over committed source in the fast suite. Any v2.0 design that violates one fails on the commit that introduces it — which is exactly why they need naming up front.

| Guard | File | What it forbids |
|---|---|---|
| `test_analytics_does_not_import_integrations` | `test_analytics_isolation.py` | `app/analytics/` importing `app.integrations` |
| `test_analytics_does_not_import_mcp` | `test_analytics_isolation.py` | `app/analytics/` importing `app.mcp` |
| `test_analytics_never_writes` | `test_analytics_isolation.py` | `session.commit/flush/add` or `insert/update/delete` imports in analytics |
| `test_analytics_declares_no_float` | `test_analytics_isolation.py` | `float(`, `: float`, `-> float` in analytics |
| `test_analytics_uses_no_raw_sql_text` | `test_analytics_isolation.py` | `text(` in analytics |
| **`test_mcp_never_writes`** | `test_mcp_isolation.py` | Any write construct in **any** module under `app/mcp/` |
| **`test_every_tool_module_guards_its_public_tools`** | `test_mcp_isolation.py` | Undecorated tools; asserts a **literal count of 12** |
| `test_mcp_never_interpolates_an_exception` | `test_mcp_isolation.py` | `f"…{e}"` in anything MCP returns |
| **`test_every_tool_is_annotated_read_only`** | `test_mcp_tool_schemas.py` | Any tool not carrying `READ_ONLY` |
| `EXPECTED_TOOLS` frozenset | `test_mcp_tool_schemas.py` | The exact 13-name registry |
| `test_hevy_schemas_are_not_imported_outside_the_package` | `test_hevy_isolation.py` | Hevy wire schemas leaking out of `integrations/hevy/` |
| `test_httpx2_is_only_imported_inside_the_hevy_package` | `test_hevy_isolation.py` | HTTP client outside the provider package |
| `test_db_does_not_import_integrations` | `test_hevy_isolation.py` | `app/db/` importing `app.integrations` |

The three in bold are the ones capability 5 must change.

### Reusable idioms the new work should copy rather than reinvent

| Idiom | Where it lives | Why copy it |
|---|---|---|
| `pg_insert(...).on_conflict_do_update(constraint="uq_…")` bound **by name** | `integrations/hevy/body.py`, `db/repositories/sync_state.py` | A renamed constraint raises immediately instead of degrading into duplicate rows |
| SAVEPOINT per row (`session.begin_nested()`) | `integrations/hevy/body.py` | One bad row aborts the whole transaction otherwise |
| `format_sync_error` — class name only, never `str(exc)` | `db/repositories/sync_state.py` | `ValidationError.__str__` renders `input_value=…`, i.e. the health data |
| `secrets.compare_digest` on **bytes**, never `str` | `mcp/auth.py` | A non-ASCII header byte makes the `str` overload raise `TypeError` → 500 with traceback instead of a silent 401 |
| `local_day(ts, users.timezone)` — never the server's UTC date | `core/time.py`, used everywhere | At UTC+7, every instant 17:00–24:00Z belongs to the *next* local day |
| Freshness + coverage envelope on every analytics response | `analytics/metadata.py` | DQ-01/DQ-02; a stale-source answer must announce itself |
| `safe_tool(degraded=…)` on every MCP tool | `mcp/tools/_common.py` | `mcp 2.0.0` returns `str(exception)` to the model verbatim; asyncpg errors carry the DSN |
| Response caps in one named block | `mcp/tools/_common.py` | Every cap is a *context* budget, retunable in one place |

---

## Ground Truth: What Apple Health Actually Contains

Measured directly from the user's `export.xml` (191 MB, `ExportDate 2026-08-26 10:09:33 +0700`, 438,649 `<Record>` elements) and its derived `records.csv` / `workouts.csv` / `activity_summary.csv`. This is not an assumption about what HealthKit *can* hold — it is what this person's phone has recorded.

| Signal | Samples | Range | Verdict for v2.0 |
|---|---|---|---|
| StepCount | 48,261 | 2022-03-10 → **2026-08-26** | **Build on this** |
| ActiveEnergyBurned | 45,182 | 2022-09-13 → **2026-08-26** | **Build on this** (iPhone-estimated) |
| BasalEnergyBurned | 84,260 | 2022-09-13 → 2026-08-26 | Available; pairs with active for TDEE context |
| DistanceWalkingRunning | 48,125 | 2022-03-10 → 2026-08-26 | Available |
| FlightsClimbed | 3,936 | 2022-04-12 → 2026-08-26 | Available |
| Walking gait metrics (speed, step length, asymmetry, double-support) | 194,976 | current | **Noise for this domain** — 44% of all rows, zero coaching value |
| HeadphoneAudioExposure | 10,077 | current | Irrelevant |
| SleepAnalysis | 2,411 — **100% `InBed`**, source "Vegant's iPhone" | 2022-03-20 → **2024-11-30** | **Dead.** No stages, 21 months stale |
| **HeartRate / RestingHeartRate / HRV SDNN / VO2Max / OxygenSaturation / RespiratoryRate** | **0 — type absent from the file entirely** | — | **Does not exist. No Apple Watch.** |
| `appleExerciseTime` (ActivitySummary) | 0 in **all 1,443** rows | 2022-09-14 → 2026-08-26 | Zero. Rings need a Watch |
| BodyMass | 79 rows across 6 apps — **52 from Hevy** | → 2025-05-27 | Mostly duplicates of `body_measurements`; adds no recency |
| WaistCircumference | 8 | — | Too sparse to trend |
| Workouts | 221 — **218 from Hevy**, 221 `TraditionalStrengthTraining` | — | **A lossy mirror of data BRETT already owns** |
| Dietary (Foodvisor) | ~95 days | current-ish | Explicitly out of v2.0 scope |

**Three consequences the roadmap must absorb:**

1. **"Recovery trends" has no input.** PROJECT.md's active requirement says "resting heart rate, HRV where available". The answer is *not available, and not available later either* without hardware. Either cut recovery from the health-analytics slice or scope it to "sleep duration if the user resumes recording", and say so.
2. **Apple Health workouts must not enter training analytics.** 218/221 are Hevy re-exports. Ingesting them into anything `volume.py` or `frequency.py` reads would double-count every session. Store them with their `source` name preserved so Hevy-originated rows are excluded *by predicate*, not by hope.
3. **The useful surface is activity, not physiology.** Steps + active energy + distance + flights, at daily grain, current through today. That is a real and useful input to a recomposition verdict (energy expenditure context beside the weight trend). It is not a sleep/recovery coach.

### The Health Auto Export wire contract

| Fact | Detail | Confidence |
|---|---|---|
| Transport | HTTP POST to a user-configured URL, JSON or CSV | HIGH |
| Auth | **Arbitrary custom headers**, incl. `Authorization: Bearer <token>` and `X-API-Key`. No HMAC signing, no built-in shared secret | HIGH (vendor docs) |
| Envelope | `{"data": {"metrics": [], "workouts": [], "stateOfMind": [], "medications": [], "symptoms": [], "cycleTracking": [], "ecg": [], "heartRateNotifications": []}}` | HIGH |
| Metric shape | `{"name": …, "units": …, "data": [{"date": …, "qty"\|"avg"/"min"/"max": …, "source": …}]}` | MEDIUM |
| Workout shape | `id` (String, **stable**), `name`, `start`, `end`, `duration` (s), plus optional `{qty, units}` objects: `distance`, `activeEnergyBurned`, `intensity`, `heartRate*`, `elevationUp/Down`, `maxSpeed/avgSpeed`; time-series arrays `heartRateData`, `stepCount`, `route` | HIGH (vendor docs, Export Version 2) |
| **Date format** | `yyyy-MM-dd HH:mm:ss Z` (e.g. `2024-02-06 14:30:00 -0800`) — **not ISO 8601**. A third-party implementation reports seeing *both* this and `2024-01-01T12:00:00+00:00` depending on version/path | MEDIUM — treat as two formats, parse both |
| **Aggregation granularity** | **User-configurable, seconds → yearly** | MEDIUM-HIGH |
| Batch Requests | Toggle; splits one export across multiple POSTs. JSON only, not CSV | HIGH |
| Payload size | Vendor guidance: "ensure your backend is configured to handle payloads of possibly several hundred megabytes" | HIGH |
| Retry / delivery semantics | **Undocumented.** Activity Log surfaces "HTTP failures, timeouts" | LOW → **assume at-least-once with overlapping windows** |

**The date format matching is a gift.** `export.xml`, `records.csv` and the Health Auto Export JSON all use `yyyy-MM-dd HH:mm:ss Z` (`2025-04-08 19:54:16 +0700`). One parser serves both the webhook and the backfill. Do not write two.

---

## Recommended Architecture

### Target System Overview

```
┌───────────────────────────────────────────────────────────────────────┐
│                    Google Cloud Run (still ONE service)               │
├───────────────────────────────────────────────────────────────────────┤
│  RateLimitMiddleware                                                  │
│    ├── /health, /.well-known/       → exempt        (unchanged)       │
│    ├── /api/v1/ingest/*             → SEPARATE bucket   ★ MODIFIED    │
│    └── everything else (/mcp)       → existing 30/min bucket          │
│  CorrelationIdMiddleware                                              │
├───────────────────────────────────────────────────────────────────────┤
│  FastAPI router                     │  app.mount("/", mcp_app)        │
│   ├── GET  /health                  │   └── POST /mcp                 │
│   └── POST /api/v1/ingest/          │                                 │
│           health-auto-export  ★ NEW │  13 read tools + 1 read + 1 WRITE│
│           (Bearer shared secret)    │  READ_ONLY  |  ★ WRITE_CONFIRM  │
├─────────────────────────────────────┴─────────────────────────────────┤
│  app/integrations/                                                    │
│    hevy/                    (outbound poll — unchanged)               │
│    health_auto_export/  ★ NEW  (inbound push: schemas, normalize,     │
│                                 ingest, auth, xml_backfill)           │
├───────────────────────────────────────────────────────────────────────┤
│  app/analytics/    volume  frequency  records  comparison  rollup     │
│                    estimates  metadata          ← unchanged           │
│                    progression      ★ MODIFIED  (max weight primary)  │
│                    recomposition    ★ MODIFIED  (program thresholds)  │
│                    bodyweight       ★ MODIFIED  (circumference trend) │
│                    health.py    ★ NEW  (activity trends)              │
│                    reports.py   ★ NEW  (closed-period composition)    │
├───────────────────────────────────────────────────────────────────────┤
│  app/db/models/   user  workout  exercise  body  sync_state           │
│                   health.py   ★ NEW   program.py  ★ NEW               │
├───────────────────────────────────────────────────────────────────────┤
│  Neon PostgreSQL                                                      │
│    workouts, workout_exercises, sets, exercise_templates,             │
│    exercise_muscles, exercise_muscle_overrides, users,                │
│    body_measurements, sync_state          (unchanged)                 │
│    health_daily_metrics ★  health_workouts ★                          │
│    training_programs ★     user_program_history ★                     │
└───────────────────────────────────────────────────────────────────────┘
        ▲                                    ▲
        │ Cloud Run Job (6-hourly)           │ Health Auto Export (iOS)
        │ sync-hevy      (unchanged)         │ POST on a schedule  ★ NEW
        │
        │ CLI one-shot: backfill-apple-health --path export.xml  ★ NEW
        │ CLI: add-measurement / import-measurements             ★ NEW
```

### Component Responsibilities

| Component | New / Modified | Responsibility | Notes |
|---|---|---|---|
| `api/routes/health_ingest.py` | **NEW** | Terminate the webhook: verify shared secret, enforce a body-size cap, hand the parsed payload to the ingest service, return 202 | Must be registered **before** `app.mount("/", mcp_app)` — that mount is a catch-all |
| `integrations/health_auto_export/auth.py` | **NEW** | Constant-time bearer compare on **bytes** | Copy `mcp/auth.py::StaticTokenVerifier` exactly; do not reuse the MCP `TokenVerifier` protocol |
| `integrations/health_auto_export/schemas.py` | **NEW** | Pydantic wire models; both date formats | Must not be imported outside the package (mirror `test_hevy_isolation.py`'s guard) |
| `integrations/health_auto_export/normalize.py` | **NEW** | Wire → canonical rows: unit conversion at the boundary, `local_day(ts, users.timezone)` | **Shared by webhook and backfill.** Two parsers = two shapes = a historical trend that disagrees with the ongoing one |
| `integrations/health_auto_export/ingest.py` | **NEW** | Idempotent upsert + `sync_state` bookkeeping under `provider='apple_health'` | Copy `hevy/body.py`: SAVEPOINT per row, constraint-by-name conflict, counts-only logging |
| `integrations/health_auto_export/xml_backfill.py` | **NEW** | Streaming `iterparse` over `export.xml`, filtered to the ~6 useful types, through the same normalizer | 438,649 elements at 512 MiB — `ElementTree.parse()` will OOM; `iterparse` + `elem.clear()` will not |
| `db/models/health.py` | **NEW** | `health_daily_metrics`, `health_workouts` | See schema below |
| `db/models/program.py` | **NEW** | `training_programs`, `user_program_history` | Append-only history, not a mutable column |
| `db/repositories/programs.py` | **NEW** | Read active program; the one write | Never commits — caller owns the transaction (repo convention) |
| `analytics/health.py` | **NEW** | Daily/weekly activity aggregates from `health_daily_metrics`; freshness envelope | Pure, Decimal-only, no `float`, no `text()` — the static guards apply |
| `analytics/reports.py` | **NEW** | Closed-period composition over existing analytics functions | Owns no arithmetic; see capability 4 |
| `analytics/progression.py` | **MODIFIED** | Max-weight-primary trend + plateau; e1RM retained as secondary | Highest-risk change in the milestone |
| `analytics/recomposition.py` | **MODIFIED** | Thresholds become parameters read from the active program | Docstring already scopes this: "these five constants are the ones to revisit — and nothing else in the module" |
| `analytics/bodyweight.py` | **MODIFIED** | Extend beyond weight to circumference/composition trends | `_dedupe_by_day`'s `manual`-wins rule already exists and is untested against real data |
| `analytics/metadata.py` | **MODIFIED** | `build_freshness` must span two **providers**, not just resources | Today it takes one `provider` for all resources — a response reading both Hevy and Apple Health cannot express its own freshness |
| `mcp/tools/_common.py` | **MODIFIED** | Add `writable_session` beside `read_only_session`; add report caps | **Do not weaken `read_only_session`** — 13 tools depend on it |
| `mcp/tools/programs.py` | **NEW** | `fitness_get_active_program` (read) + `fitness_set_active_program` (write) | The **only** module in `app/mcp/` permitted to write |
| `mcp/tools/reports.py` | **NEW** | `fitness_get_weekly_report`, `fitness_get_monthly_report` | Response shaping over `analytics/reports.py` |
| `mcp/server.py` | **MODIFIED** | Add `WRITE_CONFIRM` annotations; register the write tool **outside** the `_TOOLS` loop | The loop's whole purpose is that read-only-ness is structurally true |
| `middleware.py` | **MODIFIED** | Second bucket for `/api/v1/ingest/*` | Otherwise a batched HAE run consumes Claude's 30/min budget |
| `config.py` | **MODIFIED** | `health_ingest_secret: SecretStr`, added to `_SECRET_FIELDS` | Layer 1 of the three-layer secret defence |
| `cli.py` | **MODIFIED** | `backfill-apple-health`, `add-measurement` | Existing operator-CLI pattern; no new auth surface |

---

## Data Model

### `health_daily_metrics` — day-grained, not sample-grained

```sql
CREATE TABLE health_daily_metrics (
    id            UUID PRIMARY KEY,
    user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source        VARCHAR(32)  NOT NULL,   -- 'health_auto_export' | 'apple_health_export'
    source_name   VARCHAR(64),             -- HAE's own `source` ("Vegant's iPhone", "Hevy")
    metric        VARCHAR(64)  NOT NULL,   -- canonical: 'step_count', 'active_energy'…
    local_day     DATE         NOT NULL,   -- computed at ingest from users.timezone
    qty           NUMERIC(14,4),
    avg_value     NUMERIC(14,4),
    min_value     NUMERIC(14,4),
    max_value     NUMERIC(14,4),
    units         VARCHAR(16)  NOT NULL,   -- canonical internal unit after conversion
    sample_count  INTEGER,
    created_at    TIMESTAMPTZ NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_health_daily_metrics_user_source_metric_day
        UNIQUE (user_id, source, metric, local_day)
);
CREATE INDEX ix_health_daily_metrics_user_metric_day
    ON health_daily_metrics (user_id, metric, local_day);
```

**Why daily and not raw samples.** 438,649 raw rows for one user, of which 44% are walking gait micro-metrics with zero coaching value. Every analytics function in `app/analytics/` already thinks in local days and Monday-anchored weeks (`snap_local_week_range`, `local_week_spine`). Storing sub-daily samples buys nothing the analytics layer can use, costs a ~100× row count, and creates an overlapping-sample de-duplication problem across sources that day-grain sidesteps. Health Auto Export's aggregation setting (seconds → yearly) means the *device* can do this aggregation for free — configure it to daily and the payload shrinks by two orders of magnitude at the same time.

**Why `local_day DATE` and not a timestamp.** Identical reasoning to `body_measurements.measured_on`, whose docstring already states it: a calendar date is not an instant, and inventing a time of day for a daily total is fabrication. Compute it at ingest with `core.time.local_day(ts, users.timezone)`, never from the server's UTC date — at UTC+7 that would misfile seven hours of every day.

**Why `(user_id, source, metric, local_day)` and not `(user_id, metric, local_day)`.** Same shape as `uq_body_measurements_user_source_measured_on`. It lets the backfill (`apple_health_export`) and the ongoing feed (`health_auto_export`) coexist on the same day without either clobbering the other, and it makes the historical cutover a query-time precedence decision rather than a destructive migration. It also makes re-POSTing an overlapping window a no-op UPSERT, which is required given HAE's delivery semantics are undocumented.

**Why `source_name` is separate from `source`.** HAE's per-datapoint `source` field is what distinguishes "Vegant's iPhone" from "Hevy" from "Foodvisor". The live export shows `ActiveEnergyBurned` arriving from four different apps. Without this column, excluding Hevy-originated energy from an activity total is impossible; with it, it is a `WHERE` clause. Note the export also shows two device names for the same phone ("Vegant's iPhone" and "V's iPhone") — a rename — so any source-based rule must tolerate that.

### `health_workouts` — stored, but quarantined from training analytics

```sql
CREATE TABLE health_workouts (
    id                  UUID PRIMARY KEY,
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source              VARCHAR(32) NOT NULL,
    source_name         VARCHAR(64),          -- 'Hevy' for 218 of 221 live rows
    external_id         VARCHAR(64) NOT NULL, -- HAE workouts carry a stable `id`
    activity_type       VARCHAR(64) NOT NULL,
    start_time          TIMESTAMPTZ NOT NULL,
    end_time            TIMESTAMPTZ NOT NULL,
    local_day           DATE NOT NULL,
    duration_seconds    INTEGER,
    distance_m          NUMERIC(12,3),
    active_energy_kcal  NUMERIC(10,2),
    created_at          TIMESTAMPTZ NOT NULL,
    updated_at          TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_health_workouts_user_source_external
        UNIQUE (user_id, source, external_id)
);
```

Route/GPS arrays are deliberately **not** stored: the user does 221 `TraditionalStrengthTraining` sessions and no outdoor cardio, so routes are pure payload weight. Excluding them also removes the single largest contributor to HAE payload size.

**The quarantine rule, stated as a rule so it can be tested:** no module under `app/analytics/` that computes volume, frequency, progression, records or plateaus may read `health_workouts`. Hevy is the authority for training. `health_workouts` is a *coverage cross-check* ("Apple recorded a session on a day Hevy has none") and the home for genuinely non-Hevy activity. This deserves a static guard in the same style as `test_analytics_never_names_the_muscle_tables_directly`.

### Relationship to `body_measurements` — do not add a third source

`body_measurements` already has every circumference and composition column and a `source` discriminator. The temptation is to route Apple `BodyMass` into it as `source='apple_health'`. **Don't**, on three pieces of evidence:

1. `bodyweight._dedupe_by_day` implements a **two-valued** precedence: `manual` wins, everything else is first-seen-by-`(measured_on, source)` ordering. Its docstring says the rule is "locked now so it cannot silently become a double-count the day manual entry ships". Adding a third source makes it three-valued and silently changes every historical average — the exact failure the docstring is guarding against.
2. **52 of the 79** Apple `BodyMass` rows originate from Hevy. They would land on the same `measured_on` as rows already present with `source='hevy'`, and the unique constraint `(user_id, source, measured_on)` permits both. `_dedupe_by_day` would then pick one arbitrarily.
3. Apple `BodyMass` stops at 2025-05-27. It adds no recency over the 125 body measurements the 6-hourly Hevy sync already imports.

If a third source is ever genuinely wanted, the correct move is to make the precedence explicit — a named ordered tuple `SOURCE_PRECEDENCE = ("manual", "hevy", "apple_health")` with a test per pair — not to add a source and hope the existing rule copes.

### `training_programs` + `user_program_history`

```sql
CREATE TABLE training_programs (
    id      UUID PRIMARY KEY,
    slug    VARCHAR(32) NOT NULL UNIQUE,     -- 'lean_bulk' | 'cut' | 'recomp'
    title   VARCHAR(64) NOT NULL,
    -- the five constants recomposition.py currently hardcodes
    weight_gain_too_fast_pct_per_week  NUMERIC(5,3) NOT NULL,
    weight_loss_too_fast_pct_per_week  NUMERIC(5,3) NOT NULL,
    weight_stable_band_pct_per_week    NUMERIC(5,3) NOT NULL,
    recomp_progression_net_band        NUMERIC(5,3) NOT NULL,
    recomp_min_classified_exercises    INTEGER      NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE user_program_history (
    id          UUID PRIMARY KEY,
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    program_id  UUID NOT NULL REFERENCES training_programs(id),
    started_at  TIMESTAMPTZ NOT NULL,
    ended_at    TIMESTAMPTZ,                 -- NULL = active
    created_at  TIMESTAMPTZ NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL
);
CREATE UNIQUE INDEX uq_user_program_history_one_active
    ON user_program_history (user_id) WHERE ended_at IS NULL;
```

**Append-only history, not a `users.active_program_id` column.** Three reasons, and the third is the strongest:

1. It makes `destructive_hint=False` on the write tool *truthful*. A mutable column loses the previous value; an append-only history destroys nothing.
2. It gives "you switched to Cut three weeks ago" for free.
3. **The recomposition verdict genuinely needs it.** `get_recomposition_status` classifies a smoothed four-week weight rate against program thresholds. If the user switched programs eight days ago, that rate spans two programs and judging it against the new one is a wrong judgement delivered confidently. The history table is what lets the verdict say "your program changed mid-window" instead of guessing. The partial unique index enforces "at most one active" at the database, not in application code.

Seed the three programs in the migration, alongside `0002_seed_default_user.py`'s precedent.

---

## Capability-by-Capability Integration

### 1 & 2. Apple Health ingestion + schema

**Data flow — ongoing (new, inbound):**

```
Health Auto Export (iOS, background, user-set interval)
    │  POST https://brett-…run.app/api/v1/ingest/health-auto-export
    │  Authorization: Bearer <HEALTH_INGEST_SECRET>
    │  {"data": {"metrics": [...], "workouts": [...]}}
    ▼
RateLimitMiddleware  (dedicated /ingest bucket)  ★
    ▼
CorrelationIdMiddleware
    ▼
api/routes/health_ingest.py
    ├─ body-size cap → 413 before parse           ★ prevents OOM at 512Mi
    ├─ secrets.compare_digest(bytes)  → 401 silent, nothing logged
    ▼
integrations/health_auto_export/schemas.py   Pydantic wire model
    ▼
integrations/health_auto_export/normalize.py
    ├─ parse "yyyy-MM-dd HH:mm:ss Z"  AND  ISO-8601-with-T
    ├─ units → kg / m / kcal / s / cm  (boundary conversion only)
    ├─ metric name → canonical vocabulary
    └─ local_day(ts, users.timezone)
    ▼
integrations/health_auto_export/ingest.py
    ├─ SAVEPOINT per row
    ├─ pg_insert(...).on_conflict_do_update(constraint="uq_health_daily_metrics_…")
    └─ sync_state: provider='apple_health', resource='health_metrics' | 'health_workouts'
    ▼
health_daily_metrics · health_workouts        →  202 Accepted {counts only}
```

**Data flow — backfill (new, one-shot, offline):**

```
export.xml  (191 MB, 438,649 <Record>, ExportDate 2026-08-26)
    │  PYTHONPATH=backend uv run python -m app.cli backfill-apple-health --path export.xml
    ▼
xml.etree.ElementTree.iterparse(…, events=("end",))   +  elem.clear()  after each
    │  filter to: StepCount, ActiveEnergyBurned, BasalEnergyBurned,
    │             DistanceWalkingRunning, FlightsClimbed, SleepAnalysis
    │  (skip the 194,976 walking-gait rows and 10,077 audio-exposure rows)
    ▼
THE SAME normalize.py  →  THE SAME ingest upsert  →  THE SAME tables
    source='apple_health_export'
```

Running the backfill through the ingest normalizer is the load-bearing decision. Two parsers producing two shapes for the same metric is how the historical trend and the ongoing trend end up disagreeing — and nothing would surface it, because both would look plausible. It is also the cheapest correctness test the normalizer will ever get: 4.5 years of real data against a fresh parser.

**Auth.** Health Auto Export supports arbitrary custom headers, so `Authorization: Bearer <secret>` works and is the right choice. It is the same shape as the `MCP_AUTH_MODE=static` path that already exists and is already proven for the Claude Code CLI, so the rotation runbook (`docs/runbook-secret-rotation.md`) extends rather than needing invention. Do **not** put the token in the URL — same prohibition as the MCP one, plus it lands in Cloud Run access logs. Do **not** try to put the webhook behind WorkOS OAuth: a background iOS app has no browser and no consent flow available to it.

**The size problem is real and has a specific ceiling.** Cloud Run rejects HTTP/1 requests above **32 MiB**, and the service runs at `--memory=512Mi`. HAE's own guidance says payloads can reach "several hundred megabytes". A 32 MiB JSON body parsed into Python objects expands roughly 5–10× in memory — an OOM kill, which on Cloud Run looks like a 503 with no application log line. Mitigations in priority order:

1. **Configure HAE aggregation to daily.** A year of step data goes from ~48k samples to ~365 points. This is a device-side setting and costs nothing.
2. **Select only the needed metrics** in the automation — exclude walking gait, audio exposure, and workout routes.
3. **Enable HAE Batch Requests** so one export splits across several POSTs.
4. **Cap the body server-side and return 413** before parsing. An explicit 413 is a diagnosable failure; an OOM kill is not.
5. Do **not** reach for `--use-http2` as the primary fix. It lifts the 32 MiB cap, at which point the 512 MiB memory ceiling becomes the binding constraint and the failure mode gets worse.

**Rate limiting needs a carve-out.** The current limiter is one global token bucket at 30/min with 30 burst, exempting only `/health` and `/.well-known/`. With Batch Requests on, a single HAE export can fire a burst of POSTs — which would consume the same budget Claude's connector uses and surface as a mid-conversation 429, the exact failure the current generous limits were tuned to avoid. Give `/api/v1/ingest/*` its own bucket. Do **not** exempt it: it is publicly reachable on an `--allow-unauthenticated` service.

**Freshness envelope needs a signature change.** `analytics/metadata.build_freshness(session, *, user_id, resources, provider=PROVIDER_HEVY)` takes **one** provider for all requested resources. A recomposition verdict that reads Hevy workouts *and* Apple Health activity cannot express its own freshness under that signature. Change it to take `(provider, resource)` pairs, and add `FRESHNESS_RESOURCES_HEALTH`. This is small but it is on the critical path for every health-aware analytics response — do it in the ingest phase, not later.

**Manual body-measurement entry** is a separate, much smaller write path. `body_measurements.source='manual'` and `bodyweight._dedupe_by_day`'s manual-wins precedence were both built in v1.0 and have zero rows behind them. The options:

| Option | Cost | Verdict |
|---|---|---|
| CLI (`python -m app.cli add-measurement` + a bulk CSV import) | Lowest — no new auth surface, fits the existing operator-CLI pattern | **Recommended** |
| Authenticated FastAPI route | Requires inventing a non-MCP authenticated API surface with no client for it | Defer |
| A second MCP write tool | Explicitly out of scope: "Write/delete MCP tools beyond the one confirm-gated program-switch tool" | **Excluded** |

### 3. Max-weight-lifted as primary strength signal

**What is already there.** `progression.best_set_per_day` folds `qualifying_set_rows` into one `SessionBest` per `(template, local_day)` and populates `best_weight_kg` on **every** entry — including the 16.8% of exercise-sessions (376 of 2,239 on live data) that have no e1RM-qualifying set at all. The max-weight series therefore needs **no new query and no new fold**. It is a second projection of a map that is already built.

`records.py` already has `PersonalRecordType.MAX_WEIGHT`, ungated.

**What changes, precisely:**

| Function | Change |
|---|---|
| `weekly_e1rm_points` | Add a sibling `weekly_max_weight_points` — same signature, `y` = week's max `best_weight_kg` instead of max `best_e1rm_kg` |
| `classify_trend` | Take the points and the band as arguments; run OLS unchanged |
| `get_exercise_trends` | Classify off max-weight; report the e1RM rate as a new **secondary** field on `ExerciseTrend`, not a replacement |
| `scan_plateau` | Parameterize the series value (`best_weight_kg` vs `best_e1rm_kg`) |
| `get_plateaus` | Seed `historical_best` from max weight |
| `mcp/tools/schemas.py`, `mcp/tools/progression.py` | Carry both signals |
| `recomposition.py` | **No structural change** — it consumes verdicts, not values |
| `estimates.py`, `records.py`, `volume.py`, `frequency.py`, `comparison.py`, `rollup.py` | **Unchanged** |

**Two calibration hazards that are the actual work.**

*Hazard 1 — the shared band derivation breaks under discrete increments.* `TREND_STABLE_BAND_PERCENT_PER_WEEK = 0.5` is documented as **derived**: `PLATEAU_IMPROVEMENT_TOLERANCE (2%) ÷ MIN_TREND_WEEKS (4) = 0.5%/week`, and the comment says why — "sharing one underlying number means PROG-02 and PROG-03 cannot contradict each other by construction". Estimated 1RM is continuous (Epley maps 60×10 → 80.000 and 70×5 → 81.667), so a 2% band is a real dead-band. **Max weight is quantized to plate and stack increments.** 2% of a 60 kg lift is 1.2 kg — smaller than the smallest plate that can be added. The band is therefore either inert (no session ever clears it) or trivially cleared by a single increment. Both bands must be re-derived against discrete increments, *and the re-derivation must preserve the shared relationship* or the trend verdict and the plateau verdict will start contradicting each other on the same exercise. This deserves its own plan with live-data validation, exactly as D-18's original calibration got ("9 improving / 9 stable / 10 declining across 28 classified exercises — the band lands between real clusters rather than splitting one").

*Hazard 2 — D-07a's skip semantics evaporate.* Under e1RM, 16.8% of sessions have `best_e1rm_kg is None` and `scan_plateau` skips them entirely — they neither extend nor break a streak. Under max weight, `best_weight_kg` is populated for essentially every set-based session, so **every** session enters the streak. Consequences: streak session-counts rise, `PLATEAU_MIN_QUALIFYING_SESSIONS = 4` was calibrated against the *sparser* e1RM population, and `_plateau_confidence`'s 4-5/6-9/10+ buckets shift upward. Note also that 48 live non-warm-up sets carry a genuine `Decimal("0.000")` weight (bodyweight exercises with no added load) — those must not read as "no data" *or* as a legitimate ceiling. `_NO_WEIGHT_RANK = Decimal(-1)` already anticipates this for ranking; the plateau scanner needs the same care.

*Downstream, and this is a build-order dependency:* `recomposition.aggregate_progression` consumes the PROG-02 verdict distribution. Change the classifier and that distribution shifts, which shifts `RECOMP_PROGRESSION_NET_BAND`'s meaning and therefore the recomposition status. Re-validate against live data; do not redesign.

### 4. Weekly/monthly report tools

**Verdict: ~80% response-shaping, ~20% genuinely new analytics.** The 20% is specific and worth naming.

Already exists and composes directly — `get_weekly_volume`, `get_muscle_group_volume`, `get_training_frequency`, `get_recomposition_status`, `get_body_weight_trend`, `get_exercise_trends`, `get_plateaus`, `get_personal_records`, `compare_periods`. And `fitness_get_training_summary` is already a composition tool doing exactly this shape at a 4-week default: four analytics calls in one read-only transaction, projected down to fit a 16 KB budget. A weekly report is largely that at `weeks=1` plus PRs plus a period comparison.

**The genuinely new part: closed-period anchoring.** Every existing entry point is anchored on the user's local *today*. `get_body_weight_trend`, `get_recomposition_status` and `get_plateaus` take **no start date at all**, and their docstrings argue against one — "a caller-supplied end date would let a stale anchor produce a confident-looking rate from a window that has since been superseded". But a weekly report delivered Monday morning is about the *completed* week Mon–Sun, not the trailing seven days. `comparison.py` (CMP-01) is the only existing function taking two explicit periods and is the right precedent.

This forces one decision that should be made in the phase context, not in a plan:

| Option | Cost | Honesty |
|---|---|---|
| **(a)** Report closed-period volume/frequency/PRs, and carry the *anchored-on-today* recomposition verdict beside them, clearly labelled | Cheap; no signature changes | Honest, and arguably more useful — "where you stand now" is what a coach wants |
| **(b)** Give `get_body_weight_trend` and `get_recomposition_status` an optional `anchor_day` | A real change to two functions whose docstrings currently forbid it, plus new tests for the stale-anchor failure mode | Also honest, but pays for a capability nothing else needs |

**Recommend (a).**

**Two constraints inherited from `summary.py`, both measured rather than assumed:**

- *Budget.* `fitness_get_training_summary` measures ~9.5 KB on the wire at its 4-week default against a 16 KB budget, and it **deliberately excludes** PRs, plateaus, the per-week × per-muscle grid, and per-exercise frequency purely for size. A report that adds PRs + plateaus + measurements + a period comparison will exceed that. New `MAX_REPORT_*` caps belong in `_common.py`'s existing per-tool budget block, and the report's size must be **measured**, not estimated.
- *Cost.* The summary already issues ~7 aggregate queries and is documented as "the most expensive call in the phase" against Claude's 30 s per-call budget — `get_recomposition_status` alone internally runs three analytics functions. A report is strictly more, plus a program lookup. Measure it; a slow scheduled report that times out is indistinguishable from a broken connector.

**Scheduled delivery needs nothing server-side.** Verified: a Claude scheduled task is a fresh session issuing ordinary MCP tool calls. No push channel, no callback registration, no server-side scheduler. The existing 6-hourly Cloud Run Job stays a *data* sync and gains no reporting role.

**But there is a documented client-side reliability risk.** `anthropics/claude-code#43397` (closed as a duplicate of `#35899`; see also `#36327`, `#40835`, `#40669`) reports that scheduled-task sessions complete the MCP handshake — a server operator's logs show `initialize`, `notifications/initialized` and `tools/list` all succeeding with valid schemas returned — but the tool schemas are **never injected into the agent's tool registry**, so the agent concludes no tools exist and stops. A single user message into the same session makes them appear instantly. Community workaround: begin the scheduled prompt with an instruction to delegate to a subagent ("DO NOT DO ANY WORK. ASSIGN THIS TASK TO AN AGENT."), which initializes MCP tools correctly. **Server-side implication: none.** Operational implication: the report tools must be verified from a real scheduled task and not only from an interactive session, and `docs/coaching-instructions.md` may need to carry the subagent preamble.

**Program-awareness is a build-order dependency.** A report that says "you are on target for your Lean Bulk" needs the program to exist as data. Build programs first, or ship the reports against today's hardcoded thresholds and change them again.

### 5. The confirm-gated write tool

**Data flow:**

```
Claude: "switch me to Cut"
    │
    ├─ CALL 1  fitness_set_active_program(program="cut")
    │     read_only_session   ← structurally read-only, same as all 13 tools
    │       current program, when it started, which thresholds change
    │     → { confirmation_required: true, current: …, proposed: …, changes: [...] }
    │       NOTHING IS WRITTEN
    │
    └─ CALL 2  fitness_set_active_program(program="cut", confirm=true)
          writable_session — ONE transaction
            UPDATE user_program_history SET ended_at = now()
                   WHERE user_id = :u AND ended_at IS NULL
            INSERT INTO user_program_history (…, started_at = now())
          COMMIT
          → { switched: true, from: "lean_bulk", to: "cut", effective_from: … }
```

**Annotation.** The `_TOOLS` loop applies one shared `READ_ONLY` object to twelve tools precisely so read-only-ness is *structurally* true rather than twelve chances to forget a flag. The write tool must be registered **outside** that loop — the same way `fitness_ping` already is — with its own object:

```python
WRITE_CONFIRM = ToolAnnotations(
    read_only_hint=False,    # it writes
    destructive_hint=False,  # append-only history; nothing is destroyed
    idempotent_hint=True,    # switching to the program you are already on is a no-op
    open_world_hint=False,   # closed domain, like every other tool here
)
```

Verified against `mcp 2.0.0`'s `ToolAnnotations`: the spec defaults are `destructive_hint=True` and `open_world_hint=True`, so **leaving them unset advertises a destructive open-world tool**. Set all four explicitly, exactly as `READ_ONLY` does. Note `destructive_hint=False` is only truthful under the append-only history design — if the switch mutates a column in place and loses the prior value, the honest annotation is `True`, which is a further argument for the history table.

**Static guards must change — this is why it is a phase, not a task.** Three tests currently make a write tool impossible:

| Guard | Correct change | Wrong change |
|---|---|---|
| `test_mcp_never_writes` — `_SESSION_WRITE` / `_WRITE_IMPORT` regexes over **every** module under `app/mcp/` | **Explicit single-module allowlist** (`app/mcp/tools/programs.py`), so "exactly one MCP module can write" stays machine-checked — which *is* the PROJECT.md constraint | Deleting or relaxing the regex |
| `test_every_tool_module_guards_its_public_tools` — asserts a **literal count of 12** | Bump the literal; the comment already explains the literal is the point | Making the count dynamic |
| `test_every_tool_is_annotated_read_only` + `EXPECTED_TOOLS` frozenset | "Every tool except the named write tool"; add the new names to `EXPECTED_TOOLS` | Dropping the assertion |

**`read_only_session` must not be weakened.** Add a `writable_session` sibling in `_common.py`. Thirteen tools depend on the PostgreSQL `READ ONLY` transaction being the *actual* control — `test_mcp_readonly.py` drives a real write through a tool session and asserts `ReadOnlySQLTransactionError`, precisely because annotations "should not be relied upon for security enforcement". Also verified there: the `postgresql_readonly` option does **not** leak back into the pooled connection, so a writable session in the same process is safe.

**`required_scopes` — the code already flags this moment.** `mcp/server.py`'s `AuthSettings(required_scopes=None)` carries the comment: *"Revisit when the first write tool ships."* It also names the cost: a required scope would force re-consent on the connector that already works, and `AuthSettings.required_scopes` applies to the **whole server**, so it would gate the thirteen read tools too. **Recommend keeping `required_scopes=None`.** For a single-user server the two-call confirm *is* the control, and a scope the server never varies its behaviour on is a claim, not a control — which is the argument the existing comment already makes.

**Two-call vs elicitation — verified, and stick with two-call.** `mcp 2.0.0` ships a genuine alternative: `Elicit` + `Annotated[ElicitationResult[T], Resolve(fn)]`, matched against `AcceptedElicitation` / `DeclinedElicitation` / `CancelledElicitation`. It produces a real *client-rendered* confirmation rather than a modelled one. Three reasons to keep the two-call design anyway:

1. Elicitation requires the **client** to advertise the capability. Claude's custom-connector support for it is unverified, and BRETT is a resource server talking to a client it does not control.
2. `Resolve`-injected parameters are **hidden from the tool's input schema**, so a client that silently lacks the capability gives no signal at discovery — it fails at call time, mid-conversation.
3. The two-call contract is enforced **server-side**, so it works identically on the Claude Desktop/Web/mobile connector *and* the Claude Code CLI static-bearer path, which is a rollback route that must keep working.

Record elicitation as the known upgrade path once client support is confirmed.

**Transaction boundary.** Two statements, one transaction, one commit. Do **not** call analytics inside the write transaction — the "here's what this changes" preview that call 1 returns is a *read* and belongs in `read_only_session`. That keeps call 1 structurally read-only and makes call 2 the only path in the entire MCP layer that can write.

---

## Suggested Build Order

### Dependency graph

```
  ┌─ Health tables + normalizer + webhook ─┐
  │              (1)                        │
  │               ↓                         │
  │        export.xml backfill              │
  │              (2)                        │
  └───────────────┬─────────────────────────┘
                  │
   Max-weight strength signal (3)  ── independent of 1 & 2 ──┐
                  │                                          │
                  ↓                                          │
        Training programs (4)                                │
        · schema + seed                                      │
        · program-aware recomposition thresholds             │
        · read tool                                          │
        · confirm-gated WRITE tool + static-guard changes     │
                  │                                          │
                  ↓                                          ↓
        ┌───────────────────────────────────────────────────────┐
        │  Health analytics + period-anchored reports (5)       │
        │  needs: health data (1,2) + settled strength verdict   │
        │         (3) + programs for program-aware reports (4)   │
        └───────────────────────────────────────────────────────┘
```

### Recommended sequence

| # | Phase | Why here | Ends when |
|---|---|---|---|
| **1** | **Apple Health ingest foundation** — `health_daily_metrics` + `health_workouts` + migration; `integrations/health_auto_export/` (schemas, normalize, ingest, auth); the FastAPI route; `sync_state` extension for `provider='apple_health'`; `build_freshness` multi-provider signature; rate-limit carve-out; body-size cap; secret + deploy wiring | Longest external lead time — the phone must be configured and then data accumulates while later phases run. It also *defines the canonical metric shape* everything downstream reads | Real data from the phone lands in `health_daily_metrics`, verified in production |
| **2** | **Historical backfill** — `backfill-apple-health` CLI, streaming `iterparse`, filtered to the ~6 useful types, through the **same** normalizer | Separate from 1 so the live webhook is proven before a 438k-element import runs. It is also the cheapest correctness test the normalizer will get: 4.5 years of real data | 2022-03 → 2026-08 present in the tables, no duplicate days against the webhook feed |
| **3** | **Max-weight strength signal** — `progression.py` max-weight primary, band re-derivation with live-data validation, e1RM demoted to secondary, `recomposition.py` re-validated | Highest-risk analytics work; **no new I/O and no schema dependency**. Must land before reports, because it changes what `fitness_get_training_summary` and `fitness_get_recomposition_status` return | Trend + plateau verdicts re-validated against live data with a stated distribution, both bands re-derived and still sharing one number |
| **4** | **Training programs** — schema + seed; `recomposition.py` thresholds become program parameters; `fitness_get_active_program`; the confirm-gated write tool; the three static-guard changes | Must precede reports if reports are to be program-aware. Groups the write-path risk into one phase | A program switch round-trips through Claude with a real confirmation step, and "exactly one MCP module can write" is still machine-checked |
| **5** | **Health analytics + reports + coaching style** — `analytics/health.py`; health inputs into recomposition; `analytics/reports.py` closed-period composition; `fitness_get_weekly_report` / `fitness_get_monthly_report`; tighten `docs/coaching-instructions.md` | Composes everything above. Last by construction | A real Claude scheduled task delivers a report from real data, verified as a *scheduled* run and not only interactively |

**Floaters** — schedule where cheapest, no hard dependencies:
- **Manual body-measurement entry + bulk CSV import** (CLI). Natural fit with phase 4 (body/program data-model thinking) or phase 1 (already touching the CLI). `_dedupe_by_day`'s manual precedence already exists, so this is small — but it is the first time that rule sees real data, so it needs its own tests.
- **Circumference/composition trend analytics** (`bodyweight.py` beyond weight-only). Independent of the health tables. Note the data is thin: `fat_percent` and `lean_mass_kg` are 0 of 123 live rows, `waist_cm` is 15 of 123 with a three-month gap. The `DQ-02` coverage floors (`MEASURED_DAY_FLOORS`) will need per-metric equivalents, or most windows will honestly return `insufficient_data`.

### The one ordering argument worth surfacing

**Phase 3 could move to first.** It touches no I/O, has no external dependency, and directly sharpens the Core Value path that already works in production. Doing the pure-analytics change while the schema is still stable is the lower-risk sequencing. The argument against is that Apple Health has the longest lead time and starting it early lets data accumulate. **Recommend 1 → 2 → 3 → 4 → 5, but treat 3 as movable** — if phase 1 stalls on a Health Auto Export configuration problem, phase 3 is the right thing to run instead of waiting.

---

## Anti-Patterns

**1. Storing raw Apple Health samples.**
*The mistake:* mirror HealthKit's sample grain into `health_samples`.
*Why wrong:* 438,649 rows for one user, 44% of them walking gait micro-metrics with zero coaching value. Every consumer in `app/analytics/` aggregates to local days anyway, so the extra grain is pure cost plus a cross-source de-duplication problem.
*Instead:* day-grained `health_daily_metrics`, and configure HAE's aggregation setting to daily so the device does the work.

**2. Feeding Apple Health workouts into training analytics.**
*The mistake:* treat `health_workouts` as another training source.
*Why wrong:* 218 of 221 live Apple workouts originate from Hevy. Every session would be counted twice, and the numbers would look plausible.
*Instead:* Hevy is the authority for training. `health_workouts` is a coverage cross-check and the home for non-Hevy activity. Add a static guard in the style of `test_analytics_never_names_the_muscle_tables_directly`.

**3. Adding `apple_health` as a third `body_measurements.source`.**
*The mistake:* it looks free — the column exists.
*Why wrong:* `_dedupe_by_day` is two-valued (`manual` wins) and its docstring says it is "locked now so it cannot silently become a double-count". 52 of 79 Apple `BodyMass` rows are Hevy re-exports landing on the same `measured_on`, and the data stops in May 2025 anyway.
*Instead:* leave `body_measurements` to Hevy + manual. If a third source is ever needed, make the precedence an explicit ordered tuple with a test per pair.

**4. Building recovery analytics on RHR/HRV.**
*The mistake:* PROJECT.md says "resting heart rate, HRV where available", so build the code path.
*Why wrong:* zero samples across 4.5 years — the HealthKit types are absent from the export entirely. There is no Apple Watch. Sleep is `InBed`-only and stopped 2024-11-30.
*Instead:* scope health analytics to activity (steps, active/basal energy, distance, flights) and say explicitly that recovery is deferred pending hardware.

**5. Deleting the read-only static guards to land the write tool.**
*The mistake:* `test_mcp_never_writes` blocks the commit, so relax the regex.
*Why wrong:* it converts a machine-checked constraint into a code-review convention, and "MCP is read-only except one narrow tool" is a stated PROJECT.md constraint.
*Instead:* an explicit single-module allowlist, so the constraint stays enforced *and* self-documents which module is the exception.

**6. Putting the webhook behind the MCP OAuth flow.**
*The mistake:* one auth mechanism for the whole service.
*Why wrong:* Health Auto Export is a background iOS app. It has no browser, no consent flow, and can only attach static headers.
*Instead:* a separate shared-secret bearer on the ingest route, using the same constant-time-bytes comparison as `StaticTokenVerifier`.

**7. A token in the webhook URL query string.**
*Why wrong:* same prohibition as the MCP one, plus it lands in Cloud Run request logs and in the HAE app's own activity log.
*Instead:* the `Authorization` header, which HAE explicitly supports.

**8. Sharing the MCP rate-limit bucket with the webhook.**
*Why wrong:* one global 30/min bucket. A batched HAE export fires a burst, and Claude gets a 429 mid-conversation — the exact failure the current generous limits were tuned to avoid.
*Instead:* a dedicated bucket for `/api/v1/ingest/*`. Not an exemption — the service is `--allow-unauthenticated`.

**9. Making report tools a fourth copy of the analytics arithmetic.**
*Why wrong:* the codebase's most repeated rule is "one computation, two consumers" — `get_exercise_trends` is deliberately public rather than private to `recomposition.py` for exactly this reason. A report with its own volume sum is how the report and the summary end up disagreeing about the same week.
*Instead:* `analytics/reports.py` owns composition and windowing, never arithmetic. `summary.py` is the model to copy.

**10. Re-deriving max weight in a second place.**
*Why wrong:* `best_set_per_day` already computes `best_weight_kg` per `(template, local_day)` with a stated tie-break. A second "best set" rule is how the progression series and the plateau verdict end up disagreeing about the same day — the failure `best_set_per_day`'s docstring is explicitly written to prevent.
*Instead:* a second *projection* of the same fold.

**11. Removing estimated 1RM.**
*Why wrong:* it is the only signal that distinguishes progression-by-adding-reps from a stall — 60 kg × 10 and 70 kg × 5 are the same max weight and different strength. PROJECT.md says secondary, not removed.
*Instead:* demote it to a reported field beside the max-weight verdict.

**12. Mutating an `active_program` column in place.**
*Why wrong:* it makes `destructive_hint=False` a lie, loses "when did I switch", and leaves the recomposition verdict unable to notice that its four-week window straddles two programs.
*Instead:* append-only `user_program_history` with a partial unique index enforcing at most one active row.

---

## Scaling Considerations

This is a single-user personal platform. Framing scaling by user count would be theatre — the real limits are row counts, payload sizes and a per-tool-call latency budget.

| Dimension | Today | After v2.0 | First thing that breaks |
|---|---|---|---|
| Workout sets | ~8k | ~8k + growth | Nothing. Core aggregate measured at ~50 ms |
| `body_measurements` | 125 rows | +manual entries | Nothing |
| `health_daily_metrics` | 0 | ~6 metrics × ~1,630 days × 2 sources ≈ **20k rows** | Nothing. Trivial for PostgreSQL |
| `health_workouts` | 0 | ~221 + growth | Nothing |
| Webhook payload | — | **32 MiB HTTP/1 hard cap; 512 MiB container** | **This is the real limit.** Daily aggregation + metric selection + batching keeps it in the low hundreds of KB |
| Backfill peak memory | — | 438,649 elements at 512 MiB | `ElementTree.parse()` OOMs. `iterparse` + `elem.clear()` does not |
| MCP tool latency | `fitness_get_training_summary` ≈ 7 aggregates, "most expensive call in the phase" | Reports are strictly more | **Claude's 30 s per-call budget.** Measure the report tool; do not assume |
| MCP response size | Summary ≈ 9.5 KB on the wire vs a 16 KB budget | Reports carry more | Context budget, not bandwidth. New `MAX_REPORT_*` caps required |
| Rate limit | 30/min global, ×2 instances | Webhook competes with Claude | Mid-conversation 429. Fixed by a separate bucket |

**Priority order if something has to be optimized:** (1) webhook payload size — it is a hard cap with an ugly failure mode; (2) report tool latency against the 30 s budget; (3) report response size against the context budget. Everything else has headroom measured in orders of magnitude.

---

## Integration Points

### External services

| Service | Pattern | Gotchas |
|---|---|---|
| **Health Auto Export** (iOS) | Inbound POST, JSON, user-configured interval, `Authorization: Bearer` custom header | Date format is `yyyy-MM-dd HH:mm:ss Z`, **not** ISO 8601 — and at least one third-party implementation reports seeing both. Retry/delivery semantics undocumented → **assume at-least-once with overlapping windows** and make every write an idempotent UPSERT. Payloads can reach "several hundred MB" per vendor guidance. Aggregation granularity is configurable seconds→yearly — **set it to daily**. Batch Requests is JSON-only |
| **Apple Health `export.xml`** | One-shot offline file | 191 MB / 438,649 `<Record>` elements. Naive `.parse()` OOMs at 512 MiB. Naive comma-splitting of the derived CSV also breaks — the `device` column contains embedded commas. Same date format as HAE, so one parser serves both |
| **Claude connector** (Desktop/Web/mobile) | WorkOS AuthKit OAuth 2.1, RS256 JWT, `aud` pinned to the Resource Indicator | Unchanged. `required_scopes=None` should stay — it is server-wide and would force re-consent |
| **Claude scheduled tasks** | Fresh session issuing ordinary tool calls. **Nothing server-side** | `anthropics/claude-code#43397` / `#35899`: handshake succeeds (`initialize`, `tools/list` all logged server-side) but tool schemas are never injected into the agent's registry, so it reports no tools. Workaround: prompt the task to delegate to a subagent. **Verify reports from a real scheduled run, not only interactively** |
| **Google Cloud Run** | 1 service, `--allow-unauthenticated`, HTTP/1, `--memory=512Mi`, `--timeout=300`, `--max=2` | 32 MiB request cap. `--use-http2` lifts it but makes memory the binding constraint — prefer smaller payloads |
| **Google Secret Manager** | `--set-secrets` in `scripts/deploy-cloud-run.sh` | Add `HEALTH_INGEST_SECRET`. A name bound in both `--set-secrets` and `--env-vars-file` is rejected by Cloud Run |
| **Hevy API** | Outbound poll, 6-hourly Cloud Run Job | Unchanged. Remains the **authority for training data** — Apple Health workouts do not compete with it |

### Internal boundaries

| Boundary | Direction | Notes |
|---|---|---|
| `api/routes/health_ingest` → `integrations/health_auto_export/` | Direct call | Route owns HTTP concerns only. Wire schemas must not escape the package |
| `integrations/health_auto_export/` → `db/models/health` | Direct | Mirrors `hevy/body.py` → `db/models/body`. `db/` must not import `integrations` (statically enforced) |
| `cli.backfill-apple-health` → the **same** normalizer + ingest | Direct | Non-negotiable. Two parsers = two shapes = disagreeing trends |
| `analytics/health.py` → `db/models/health` | Direct read | Must obey all analytics guards: no `float`, no `text()`, no writes, no `app.integrations` import, no `app.mcp` import |
| `analytics/reports.py` → other `analytics/*` | Direct call | Composition only. Precedent: `recomposition.py` calls `bodyweight` + `progression` + `volume` and owns no arithmetic |
| `analytics/recomposition.py` → `db/repositories/programs` | Direct read | New dependency. Thresholds become parameters; `_LABEL_MATRIX` stays program-independent |
| `mcp/tools/programs.py` → `db/repositories/programs` | Direct write | **The only** write path in `app/mcp/`. Allowlisted in `test_mcp_never_writes` |
| `mcp/tools/reports.py` → `analytics/reports.py` | Direct | Same shape as every existing tool |
| `analytics/metadata.build_freshness` | **Signature change** | Must span `(provider, resource)` pairs, not one provider for all resources |
| `middleware.RateLimitMiddleware` | **Path-aware** | Third branch: exempt / ingest bucket / default bucket |

### One design decision to make explicitly, not by default

`recomposition._MATRIX_ROWS` maps `(weight_bucket, progression_signal) → RecompositionStatus` across 24 combinations, and its docstring says the seven-member enum is a fixed contract: *"there is no eighth, and adding one would change the contract Phase 6 codes against."* But the matrix encodes lean-bulk assumptions in its *labels*: `TOO_FAST_GAIN` yields `WEIGHT_GAIN_TOO_FAST` for all four signals because a fast gain is a safety signal *during a bulk*; `LOSING` + positive signal yields `LIKELY_RECOMP_PROGRESSING`. Under a **Cut**, gaining at all is off-program and `LIKELY_FAT_LOSS` is on-program rather than incidental.

**Recommend: keep the enum and the matrix program-independent; move only the thresholds.** The enum is what `docs/coaching-instructions.md` is written against, and a per-program matrix triples the tested surface (72 combinations) for a nuance the thresholds already carry — under a Cut, `LOSING` simply becomes the expected bucket rather than a different label. But make this call deliberately in the phase context, because it is the difference between a one-day change and a three-day one.

---

## Confidence Assessment

| Area | Confidence | Basis |
|---|---|---|
| Existing architecture, boundaries, static guards | **HIGH** | Read from committed source: `main.py`, `mcp/server.py`, `mcp/auth.py`, `mcp/context.py`, `mcp/tools/_common.py`, `mcp/tools/summary.py`, `mcp/tools/body.py`, `analytics/{progression,recomposition,bodyweight,metadata}.py`, `db/models/*`, `integrations/hevy/{sync,body}.py`, `middleware.py`, `config.py`, and the isolation/read-only test suites |
| Apple Health data availability | **HIGH** | Measured directly from the user's `export.xml` (438,649 `<Record>` elements) and its derived CSVs. The heart-rate absence was verified against the raw XML, not only the CSV |
| Installed stack versions | **HIGH** | `importlib.metadata` against the project venv: `mcp 2.0.0`, `mcp-types 2.0.0`, `fastapi 0.141.1`, `starlette 1.6.0`, `sqlalchemy 2.0.52`, `pydantic 2.13.4`, `httpx2 2.12.0`, `asyncpg 0.31.0` |
| `MCPServer.add_tool` per-tool annotations | **HIGH** | `inspect.signature` against the installed SDK |
| MCP `ToolAnnotations` semantics + defaults | **HIGH** | Context7 `/websites/py_sdk_modelcontextprotocol_io_v2` (verbatim class source) + the MCP blog's annotations post |
| Elicitation exists in `mcp 2.0.0` | **HIGH** | Context7 returned a complete working `Elicit` / `Resolve` / `AcceptedElicitation` example |
| **Claude connector elicitation support** | **LOW** | Not found in Anthropic's connector docs. This is why the two-call design is recommended |
| Health Auto Export auth (custom headers, Bearer) | **HIGH** | Vendor help centre, two independent pages |
| HAE payload schema (envelope, workouts) | **MEDIUM-HIGH** | Vendor help centre. The workouts page is detailed; the metrics page 404'd and was reconstructed from search excerpts + a third-party implementation |
| HAE date format | **MEDIUM** | Vendor docs say `yyyy-MM-dd HH:mm:ss Z`; a third-party implementer reports seeing both that and ISO-8601-with-T. **Parse both** |
| HAE retry/delivery semantics | **LOW** | Undocumented. Design for at-least-once regardless |
| Cloud Run 32 MiB HTTP/1 request cap | **HIGH** | Multiple independent sources incl. the Cloud Run FAQ |
| Scheduled tasks need nothing server-side | **HIGH** | Anthropic docs + the GitHub issue's own server-side protocol logs |
| Scheduled-task MCP registry bug | **MEDIUM-HIGH** | `anthropics/claude-code#43397` with server-log evidence from an independent reporter, plus four linked duplicates; closed as a duplicate of `#35899`, resolution status unclear |
| Band re-derivation under discrete increments | **MEDIUM** | The *problem* is HIGH confidence (read from the derivation comment and the data). The *right new values* are unknown until validated against live data — flagged as needing its own plan |

## Open Questions for the Roadmap

1. **Does Health Auto Export re-send overlapping windows?** Undocumented. Assume yes and make every write an idempotent UPSERT — but a single observed run in phase 1 settles it and may allow a cheaper cursor.
2. **Which HAE Export Version does the installed app emit?** V1 and V2 differ in workout shape and possibly date format. Capture one real payload verbatim as a test fixture before writing the parser.
3. **Closed-period reports: option (a) or (b)?** Whether `get_body_weight_trend` / `get_recomposition_status` grow an optional `anchor_day`. Recommend (a); decide in the phase context.
4. **Program-dependent label matrix or program-independent?** Recommend independent; decide explicitly.
5. **What are the re-derived max-weight bands?** Requires the same live-data calibration D-18 got. Cannot be answered on paper.
6. **Does the user intend to resume sleep tracking?** Sleep stopped 2024-11-30. If not, cut sleep from the health-analytics slice entirely rather than shipping a tool that always returns `insufficient_data`.
7. **Is the Apple Health backfill worth its cost given the overlap?** The genuinely new signal is activity (steps/energy/distance/flights) from 2022. Weight and workouts are largely Hevy duplicates. Confirm the activity history is actually wanted before spending a phase on a 438k-element import.

---

## Sources

- Project source, read directly (`backend/app/**`, `backend/tests/test_*_isolation.py`, `test_mcp_readonly.py`, `test_mcp_tool_schemas.py`, `deploy/cloud-run.env.yaml`, `scripts/deploy-cloud-run.sh`) — **HIGH**
- The user's own `export.xml` (191 MB, ExportDate 2026-08-26), `records.csv`, `workouts.csv`, `activity_summary.csv`, analysed with `grep` and a real CSV parser — **HIGH**
- Installed venv introspection: `importlib.metadata` versions + `inspect.signature(MCPServer.add_tool)` — **HIGH**
- Context7 `/websites/py_sdk_modelcontextprotocol_io_v2` — `ToolAnnotations` class source, elicitation `Resolve`/`Elicit` example — **HIGH**
- https://blog.modelcontextprotocol.io/posts/2026-03-16-tool-annotations/ — annotation semantics, cautious defaults, confirmation patterns — **HIGH**
- https://help.healthyapps.dev/en/health-auto-export/automations/rest-api/ — custom headers, `Authorization: Bearer`, batch requests, payload-size warning — **HIGH**
- https://help.healthyapps.dev/en/health-auto-export/export-format/ — top-level envelope, `yyyy-MM-dd HH:mm:ss Z` date format — **HIGH**
- https://help.healthyapps.dev/en/health-auto-export/export-format/workouts/ — workout field list, units, `id` stability — **HIGH**
- https://github.com/Lybron/health-auto-export — repo + wiki pointer (JSON-format wiki page has been moved to the help centre) — **MEDIUM**
- https://ladvien.com/syncing-apple-health-kit-data-postgres/ — third-party FastAPI + PostgreSQL implementation; daily-aggregate observation, date-format inconsistency, payload-size experience — **MEDIUM**
- https://github.com/anthropics/claude-code/issues/43397 (+ linked `#35899`, `#36327`, `#40835`, `#40669`) — scheduled-task MCP tool-registry bug, with independent server-side protocol logs and the subagent workaround — **MEDIUM-HIGH**
- https://support.claude.com/en/articles/13854387-schedule-recurring-tasks-in-claude-cowork — scheduled tasks are fresh sessions with connector access; nothing server-side — **HIGH**
- https://github.com/ahmetb/cloud-run-faq + corroborating issue threads — 32 MiB HTTP/1 request limit, HTTP/2 workaround — **HIGH**

---
*Architecture research for: BRETT v2.0 — Apple Health, Strength Tracking & Coaching Programs*
*Researched: 2026-09-02*
