# Phase 8: Apple Health & Nutrition Ingest - Research

**Researched:** 2026-09-02
**Domain:** Inbound webhook ingestion of Apple Health activity + nutrition data into an existing FastAPI/PostgreSQL/MCP backend
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-01 — Apple Health body-mass scope.** Exclude ALL Apple Health body-mass records from ingestion in
Phase 8, not just Hevy-sourced ones. `body_measurements` stays a two-source table (`hevy`, `manual`)
exactly as it is today — no `apple_health` source is added to it. Rationale: the user's real export shows
52/79 Apple BodyMass rows are Hevy duplicates and the data stops in May 2025 (no recency value); adding a
third source would make `bodyweight._dedupe_by_day`'s precedence three-valued, which the research flags as
a real correctness risk that belongs in Phase 11's `_dedupe_by_day` fix, not bolted on here. This is
narrower than PROJECT.md's literal "body weight/composition where not already Hevy-sourced" phrasing — a
deliberate scope tightening the user confirmed during discussion, not an oversight.

**D-02 — Apple Health workouts scope.** Do not build a `health_workouts` table in Phase 8. Apple Health
workouts are excluded from ingestion entirely (the ingest's metric/type allowlist simply never admits the
`workouts` array) — no quarantined "coverage cross-check" table. Rationale: 218/221 of the user's real
Apple Health workouts are Hevy re-exports; the 3 non-Hevy ones add negligible value against the cost of a
new table + a static guard test to keep it out of training analytics forever. If a coverage cross-check is
ever wanted, it's a future-phase addition, not part of Phase 8's success criteria.

**D-03 — Freshness / sync-state granularity.** Track activity and nutrition freshness as two **separate**
`sync_state` resources under `provider='apple_health'` — e.g. `resource='activity'` and
`resource='nutrition'` — each with its own `last_synced_at`. Do not collapse them into one combined
`apple_health` resource. Rationale: both come through the same webhook POST, but they can go stale
independently (nutrition-logging app stops writing to HealthKit while steps keep flowing, or vice versa) —
a combined resource would report "fresh" on a partial failure. Directly implements Pitfall 7's fix and
satisfies HEALTH-11/NUTR-05 for each data kind independently. `analytics/metadata.build_freshness` must
gain the `(provider, resource)` pairs signature change either way (Pitfall 7); this decision fixes what the
resource names actually are.

**D-04 — Unlisted / unexpected metric handling.** When a payload includes a metric name outside the
ingest's fixed allowlist (e.g. the user toggles on a new Apple Health data type in the automation),
silently drop that metric and continue processing the rest of the payload normally — do not reject the
whole request. Rationale: Health Auto Export has no documented retry; rejecting an entire batch over one
unrecognized metric would lose the *entire* window's activity AND nutrition data, not just the unexpected
part. Matches the vendor's own guidance that "ingest everything" is what breaks the automation. A follow-up
decision for planning: emit a structured log line (e.g. `health_ingest_unrecognized_metric`) when this
happens, so a phone-side misconfiguration is discoverable in logs rather than silently invisible forever —
this is Claude's discretion on implementation, but the *behavior* (log, don't reject) is locked.

**D-05 — Nutrition wire format, explicit research gap.** The project's existing v2.0 research was written
when nutrition was still Out of Scope for v2.0. `gsd-phase-researcher` must resolve the exact HAE metric
names, units, Hevy-nutrition question, and pipeline-reuse question before planning writes concrete
schemas/normalizer code. **→ RESOLVED IN THIS DOCUMENT, see "D-05 Resolution" below.**

### Claude's Discretion

- Webhook auth header scheme: use `Authorization: Bearer <token>` with `secrets.compare_digest` on bytes,
  copying `mcp/auth.py::StaticTokenVerifier` exactly (established pattern, not re-litigated).
- Exact log field names/shapes for the `health_ingest_unrecognized_metric` warning event (D-04).
- Rate-limit bucket capacity/refill values for the new `/api/v1/ingest/*` path (separate bucket per
  Pitfall 2 is locked; the specific numbers are a planning-time tuning decision).
- Whether the ingest route lives at `/api/v1/ingest/health-auto-export` or another specific path, as long
  as it's registered above `app.mount("/", mcp_app)` in `main.py` (Pitfall 1).
- `body_measurements.source` for `hevy`/`manual` is unaffected by this phase (D-01 means no new source is
  added there); if a future phase does add `apple_health` as a third source, use `'apple_health'` (12
  chars) per Pitfall 8, never `'health_auto_export'` (18 chars, exceeds the current `VARCHAR(16)`).

### Deferred Ideas (OUT OF SCOPE)

- **`health_workouts` coverage cross-check table** — explicitly deferred, not built in Phase 8 (D-02). If
  ever wanted, it's a future-phase addition; the design already exists in `ARCHITECTURE.md` if picked up
  later.
- **Apple Health as a third `body_measurements` source** — explicitly deferred (D-01). If ever revisited,
  it must ship together with an explicit `MappingProxyType` source-precedence map and per-pair regression
  tests (Pitfall 9's fix), which is Phase 11's territory (`_dedupe_by_day`), not this phase's.
- **HAE automation configuration specifics** (Batch Requests toggle, aggregation interval, exact
  scheduling/trigger) — this is a device-side setup task the user does themselves once the webhook exists;
  it belongs in a setup doc written during or after implementation, not a Phase 8 code decision.
  **⚠️ See Pitfall N-2 below: this research finds the aggregation-interval setting is a *correctness*
  prerequisite, not only a convenience — it needs a documented required value even though the phase does
  not own the device.**
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| HEALTH-06 | Apple Health activity data (steps, active energy, basal energy, distance, flights climbed) syncs via a Health Auto Export webhook receiver | Metric names + units verified against 5 real captured payloads and the vendor's own reference server (§D-05 Resolution, Metric Registry) |
| HEALTH-07 | Webhook authenticates inbound requests via a shared-secret bearer token, rejecting unauthenticated/mis-authenticated payloads | `StaticTokenVerifier` bytes-compare pattern read from `backend/app/mcp/auth.py:37-52`; Security Domain §V2 |
| HEALTH-08 | Sync excludes Apple Health workouts and body-mass records originating from Hevy's HealthKit write-back | D-01/D-02 cover workouts + body-mass. **NEW: Finding A proves Hevy also writes `ActiveEnergyBurned` — 70–88% of daily active-energy on 209 training days. Requires a source-level filter, not just a metric allowlist.** |
| HEALTH-09 | Sync is idempotent — reprocessing an overlapping export window creates no duplicates | Upsert pattern read from `integrations/hevy/body.py:85-120`; **aggregation↔idempotency interaction is the sharpest risk — Pitfall N-2** |
| HEALTH-11 | Apple Health freshness surfaced through the existing freshness/coverage envelope | `build_freshness` signature read from `analytics/metadata.py:137-161`; D-03 fixes resource names |
| NUTR-02 | Nutrition (calories, protein, carbs, fat, fiber, sugar, sodium) syncs via the same HAE webhook | **§D-05 Resolution — all 7 metric names and units resolved HIGH confidence** |
| NUTR-03 | Nutrition sync is idempotent, same guarantees as activity/body | Same upsert path; **Finding B: nutrition arrives per-meal, so daily aggregation is mandatory** |
| NUTR-05 | Nutrition freshness surfaced through the same envelope | D-03's `resource='nutrition'` |
</phase_requirements>

---

## Summary

The phase's declared blind spot (D-05) is now closed with HIGH confidence. Health Auto Export's nutrition
wire format is **identical in shape to its activity format** — the same `{"name", "units", "data":[{"qty",
"date", "source"}]}` envelope, the same plain-`qty` datapoint branch — so one allowlist and one normalizer
serve both, exactly as CONTEXT.md hoped. The seven metric names and their units were verified three ways:
against the vendor's own reference-server enum, against five real captured device payloads, and against the
user's own 191 MB `export.xml`. Sodium is **milligrams**; the other five macros are **grams**; energy is
**kcal but user-configurable to kJ**. The `weight_body_mass` vs `weight_&_body_mass` ambiguity is settled in
favour of `weight_body_mass` (623 GitHub repos to 6, plus the vendor's enum).

Three findings that the prior v2.0 research did not surface change the phase's scope, and all three come
from measuring the user's real data rather than reading docs. **First and most important: Hevy writes
`ActiveEnergyBurned` into Apple Health — 209 records, and on training days Hevy's single lump record is
70–88% of that day's entire active-energy total.** `active_energy` is inside this phase's allowlist, so
HEALTH-08's "exclude Hevy-originated data" requirement is not satisfied by D-01 and D-02 alone; it needs a
source-level exclusion filter on activity metrics. Second, the user's nutrition app writes **per-meal**
(1–4 records/day), and real activity payloads carry **189 datapoints for a single day** of one metric — so
the day-grained table forces an aggregation step whose interaction with idempotent upsert is the phase's
sharpest correctness risk. Third, `count`-unit metrics arrive as **fractions** (`flights_climbed` =
`0.2016…`), so any integer column or `int()` cast silently discards most of the data.

**Primary recommendation:** Build one table-driven metric registry (name → canonical unit → aggregation
function → data-kind) shared by activity and nutrition; key `health_daily_metrics` on `(user_id, source,
metric, source_name, local_day)` with a non-null `source_name` sentinel so Hevy-originated `active_energy`
stays a separately-excludable row; aggregate the *whole incoming payload* per key before a single
replace-semantics upsert; and treat HAE's daily aggregation interval as a documented deploy prerequisite
rather than a user preference.

---

## D-05 Resolution — The Nutrition Wire Format

This section answers CONTEXT.md D-05 point by point. Every claim carries its evidence class.

### 1. Exact HAE metric names — RESOLVED

| BRETT concept | **HAE metric name** | Evidence |
|---|---|---|
| Calories | **`dietary_energy`** | `[VERIFIED: vendor reference server + 5 real payloads + independent Go impl]` |
| Protein | **`protein`** | `[VERIFIED: same]` |
| Carbohydrates | **`carbohydrates`** | `[VERIFIED: same]` |
| Fat | **`total_fat`** | `[VERIFIED: same]` |
| Fiber | **`fiber`** | `[VERIFIED: same]` |
| Sugar | **`dietary_sugar`** | `[VERIFIED: same]` |
| Sodium | **`sodium`** | `[VERIFIED: same]` |

Sources, in descending authority:
- `[VERIFIED: HealthyApps/health-auto-export-server → server/src/models/MetricName.ts]` — the **vendor's
  own** reference server. Fetched and read in full this session. Lines 89–127 are its `// Nutrition` block.
- `[VERIFIED: 5 real captured HAE payloads]` from `bunya-gap/health-management-free/health_api_data/` —
  actual device output containing live nutrition data, all five agreeing.
- `[VERIFIED: joeecarter/health-import-server → request/metric-type.go]` — an independent third-party HAE
  receiver, agreeing on all seven names and classifying every one as `MetricTypeQty`.

> ### ⚠️ The naming trap — the single highest-risk detail in this section
>
> **The `dietary_` prefix is inconsistent, and guessing it wrong yields silence, not an error.**
>
> | Carries the prefix | Does NOT carry the prefix |
> |---|---|
> | `dietary_energy`, `dietary_water`, `dietary_sugar` | `protein`, `carbohydrates`, `total_fat`, `fiber`, `sodium` |
>
> The vendor's TypeScript **enum keys** are uniformly `DIETARY_*` (`DIETARY_PROTEIN`,
> `DIETARY_CARBOHYDRATES`, `DIETARY_TOTAL_FAT`…) while the **wire values** are not. Anyone reading the enum
> keys, or generalising from `dietary_energy`, writes `dietary_protein` — and under D-04's
> silently-drop-unlisted rule that metric is dropped with a log line and **no test failure**. A real
> third-party fixture found in this session (`jare0014/obsidian-health-connect`) does exactly this and uses
> `dietary_protein`; it is a hand-written sample, not device output, and is wrong.
>
> Two further traps in the same family: it is **`total_fat`, never `fat`**, and **`dietary_sugar`, never
> `sugar`**. `[VERIFIED: vendor enum + real payloads]`

### 2. Units per macro — RESOLVED (sodium is milligrams)

| HAE metric | Unit string observed | Recommended BRETT canonical unit |
|---|---|---|
| `dietary_energy` | `kcal` — **`kJ` also possible** | `kcal` (convert: `kJ ÷ 4.184`) |
| `protein` | `g` | `g` |
| `carbohydrates` | `g` | `g` |
| `total_fat` | `g` | `g` |
| `fiber` | `g` | `g` |
| `dietary_sugar` | `g` | `g` |
| **`sodium`** | **`mg`** | **`mg`** |

`[VERIFIED: 5 real HAE payloads — all five identical]` and independently
`[VERIFIED: the user's own records.csv — DietarySodium unit=mg, DietaryEnergyConsumed unit=kcal, all
macros unit=g, across 2022-07-10 → 2026-08-26]`. The user's own historical data and the third-party live
payloads agree exactly, which is the strongest corroboration available without a capture from this phone.

**But do not hard-code these.** `[CITED: help.healthyapps.dev/en/health-auto-export/getting-started/unit-preferences/]`
states that units are a **user preference inside the HAE app**, applied per-metric, and that "unit
conversions are performed automatically when exporting data". A settings change silently changes the wire
units on the next export. A synthetic-but-well-formed fixture found this session
(`Slaymish/HealthAgent`) shows `dietary_energy` in `kJ`, and an independent production normalizer
(`d3mocide/Luma`) documents *"HAE exports weight in whatever unit Apple Health uses natively on the device
(controlled by iOS Language & Region, not the HAE metric toggle). US-locale iPhones send lb even when HAE
is set to metric."* `[CITED: github.com/d3mocide/Luma/backend/luma/services/hae_normalizer.py]`

**Therefore:** read `units` from the payload, convert via an explicit per-metric table, and treat an
**unknown unit string as a rejected datapoint with a loud structured log** — never as a silently-accepted
raw number. See the Code Examples section.

### 3. Does Hevy write anything nutrition-adjacent to Apple Health? — NO, definitively

`[VERIFIED: the user's own records.csv, 4.5 years, 438,649 records, queried directly this session]`

Every record type Hevy has ever written to this user's Apple Health:

| Type Hevy writes | Count |
|---|---|
| `HKQuantityTypeIdentifierActiveEnergyBurned` | 209 |
| `HKQuantityTypeIdentifierBodyMass` | 52 |
| `HKQuantityTypeIdentifierWaistCircumference` | 8 |

**Zero nutrition records. Zero dietary records of any kind.** The only nutrition sources in the entire
export are `Foodvisor` (1,066 records) and `Built With Science` (54 records). Confirmed rather than assumed,
as CONTEXT.md required.

**However — this same query produced Finding A, which is the most consequential result in this document.
See below.**

### 4. Does the activity pipeline extend to nutrition? — YES, one normalizer

Nutrition needs **no separate normalizer function**. The vendor's own `mapMetric` dispatches on metric name
and routes everything except `blood_pressure`, `heart_rate` and `sleep_analysis` — i.e. **all seven
nutrition metrics and all five activity metrics** — into the identical `BaseMetric` `{qty, date, source}`
branch. `[VERIFIED: HealthyApps/health-auto-export-server → server/src/models/Metric.ts, read in full]`
The independent Go receiver classifies the same twelve as `MetricTypeQty`.
`[VERIFIED: joeecarter/health-import-server]`

What differs between an activity metric and a nutrition metric is **data, not code**: the canonical unit,
the conversion factor, the aggregation function, and which `sync_state` resource it advances (D-03). All
four belong in one table-driven registry. See "Pattern 1: The Metric Registry".

**Two shape details that the vendor's TypeScript interface gets wrong relative to real payloads:**

1. `BaseMetric` declares `units` on **each datapoint**. **No real payload contains it** — `units` appears
   only at the metric level. The vendor's own `mapMetric` reads `metric.units`, not `measurement.units`.
   Read the metric-level field. `[VERIFIED: 5 real payloads + vendor mapMetric]`
2. `BaseMetric` declares `source` as **required**. **It is absent entirely** for some metrics — in the real
   payloads, all 105 `walking_speed`, 105 `walking_step_length`, 95 `walking_double_support_percentage` and
   49 `walking_asymmetry_percentage` datapoints have **no `source` key at all**. A Pydantic model with
   `source: str` raises `ValidationError` and, under a whole-payload validation, loses the entire window.
   Use `source: str | None = None`. `[VERIFIED: 5 real payloads]`

### 5. `weight_body_mass` vs `weight_&_body_mass` — RESOLVED: `weight_body_mass`

| Evidence | Verdict |
|---|---|
| Vendor reference server enum: `WEIGHT_BODY_MASS = 'weight_body_mass'` | `weight_body_mass` |
| Independent Go receiver: `"weight_body_mass": MetricTypeQty` | `weight_body_mass` |
| GitHub code search, `"weight_body_mass"` | **623 results** |
| GitHub code search, `"weight_&_body_mass"` | **6 results** |
| Help Center prose ("Common Health Metrics" list) | `weight_&_body_mass` |

`[VERIFIED: vendor source + GitHub code search, run this session]`

The Help Center string appears to be a **UI display name** ("Weight & Body Mass" is the Apple Health
category label), not the wire identifier. Of the six repos using the ampersand spelling, one
(`d3mocide/Luma`) maps **both** spellings plus `weight` and `body_mass` to a single internal name —
defensive aliasing by someone who evidently hit the ambiguity in production.

**Does this block Phase 8?** **No.** D-01 excludes body-mass from ingestion entirely, so this metric never
enters the Phase 8 allowlist. Recorded for completeness as CONTEXT.md asked, and it matters for **Phase 9**
(the `export.xml` backfill, where the equivalent identifier is `HKQuantityTypeIdentifierBodyMass`) and for
any future phase that revisits D-01. **Recommendation when that day comes:** accept an alias *set*
`{"weight_body_mass", "weight_&_body_mass"}` rather than a single string — the cost is one frozenset and it
removes the only remaining ambiguity.

---

## Findings the Prior Research Did Not Surface

All four come from measuring the user's real `export.xml`/`records.csv` (present at the repo root) and real
captured HAE payloads, not from documentation.

### Finding A — Hevy writes `ActiveEnergyBurned`, and it dominates training days ★ SCOPE-CHANGING

`[VERIFIED: the user's records.csv, queried this session]`

`active_energy` is in this phase's activity allowlist. Hevy writes to it. Measured:

| Fact | Value |
|---|---|
| Hevy `ActiveEnergyBurned` records | **209** |
| Days carrying a Hevy `ActiveEnergyBurned` record | **209** (one lump record per training day) |
| Hevy's share of that day's total active energy | **70 – 88 %** |

Representative measured days (kcal):

| Day | Hevy | `Vegant's iPhone` | Total | Hevy share |
|---|---|---|---|---|
| 2025-12-19 | 494.3 (1 rec) | 85.8 (22 recs) | 580.1 | **85 %** |
| 2026-01-02 | 666.5 (1 rec) | 94.2 (16 recs) | 760.7 | **88 %** |
| 2026-01-06 | 653.8 (1 rec) | 277.6 (27 recs) | 931.4 | **70 %** |

**Why this matters.** HEALTH-08 requires excluding "Apple Health workouts and body-mass records that
originate from Hevy's own HealthKit write-back, preventing double-counting of data BRETT already holds at
higher fidelity." D-01 and D-02 close the body-mass and workouts routes. **Nobody checked `active_energy`,
because nobody knew Hevy wrote it.** The iPhone independently records active energy across the same workout
window, so summing both counts the same physical activity twice — and the resulting daily figure is 70–88 %
Hevy's own estimate of a session BRETT already owns at set-level detail.

**Consequence for planning: a metric-name allowlist is not sufficient to satisfy HEALTH-08.** The ingest
needs a **source-level exclusion predicate** on activity metrics. This is a real scope item that is not
currently in the phase's decision set, and it is the single most important thing this research adds.

Note this is *also* the strongest argument for the schema recommendation in Pitfall N-1: you cannot filter
out Hevy's contribution after you have already summed it into one row per day.

### Finding B — Nutrition arrives per-meal, and activity arrives per-minute

`[VERIFIED: user's records.csv + 5 real HAE payloads]`

| Source | Granularity observed |
|---|---|
| User's `Foodvisor` (real export) | **1–4 records per day**, at meal timestamps (12:35, 15:54, 18:23…) |
| Real HAE payload, `walking_running_distance` | **189 datapoints for a single day** (1-minute buckets) |
| Real HAE payload, `flights_climbed` | **59 datapoints for a single day** |
| Real HAE payload, nutrition | **1 datapoint per day**, anchored at `00:00:00` (that user's app writes daily totals) |

Two things follow. (1) The day-grained `health_daily_metrics` table **requires** an aggregation step — many
datapoints collapse into one row, always, for both data kinds. (2) The aggregation function is
metric-dependent: `sum` for cumulative quantities (steps, energy, distance, flights, every macro), `avg`
for rates (`walking_speed`) — though no rate metric is in this phase's allowlist, the registry should carry
the field so Phase 13 does not have to reopen the schema.

Note the two nutrition granularities are both real and both must work: the user's Foodvisor writes
per-meal, the reference payload's app writes a daily total. Summing handles both.

### Finding C — `count` metrics are fractional; `int()` silently destroys them

`[VERIFIED: real HAE payload]`

```json
{"name": "flights_climbed", "units": "count",
 "data": [{"date": "2025-08-15 08:02:00 +0900", "source": "iPhone",
           "qty": 0.20163697817574894}]}
```

HAE **prorates** samples across aggregation-interval buckets, so a `count`-unit metric arrives as a float
with a long mantissa. An `INTEGER` column, or an `int()`/`round()` cast, truncates `0.2016…` to `0` — and
because 59 such fragments make up the real day's total, the day reads as `0` flights with no error. The same
applies to `step_count`.

`sodium` shows the same effect from unit conversion: an observed `qty` of `3177.165354330709`.

**Therefore:** `NUMERIC`/`Decimal` end to end (ARCHITECTURE.md's `NUMERIC(14,4)` is correct), and convert
via `Decimal(str(value))` — never `Decimal(float)`, which imports the binary representation error. This also
keeps the phase inside `test_analytics_declares_no_float`'s existing discipline.

### Finding D — A second nutrition source exists, and the two overlap on a real day

`[VERIFIED: user's records.csv]`

The user's nutrition data comes from **two** apps, not one:

| Source | Dietary records | Notable |
|---|---|---|
| `Foodvisor` | 1,066 | The primary logger; 2022-07-10 → 2026-08-26 |
| `Built With Science` | 54 | Wrote 20 distinct dietary types on **2026-08-23** — a day Foodvisor also has 3 energy records |

On 2026-08-23 both sources wrote `DietaryEnergyConsumed`: Foodvisor `1040 + 504 + 670`, Built With Science
`105 + 295.62`. Blindly summing all sources yields 2,614.62 kcal, which is right only if the two apps logged
disjoint food. **Multi-source-per-day nutrition is real in this user's data, not hypothetical**, and the
schema must be able to express it rather than silently blending it. This reinforces the same schema
recommendation as Finding A.

Also worth carrying forward to Phase 13 (NUTR-04 trends): dietary energy exists on only **53 distinct days**
across 4.5 years, though it is **current** (through the 2026-08-26 export date, with 6 consecutive recent
days logged). Nutrition has genuine recency value — unlike body mass, which died in May 2025 — but per-metric
coverage floors will be needed before trend claims.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|---|---|---|---|
| Metric selection, aggregation interval, batching | **iOS device (HAE app)** | — | Device-side settings; BRETT cannot control them but *depends* on them (Pitfall N-2). Must be documented, not assumed |
| Rate limiting the ingest path | **Cloud Run edge / ASGI middleware** | — | `RateLimitMiddleware` runs outside the router (`main.py`), before routing — the only place an unauthenticated flood can be bounded |
| Body-size rejection (413 before parse) | **ASGI middleware / route** | — | Must precede JSON parse or the 1Gi instance OOMs instead of answering (Pitfall 5) |
| Shared-secret authentication | **FastAPI route** | — | The MCP sub-app's `RequireAuthMiddleware` wraps only `mcp_app`; a FastAPI route inherits **zero** auth (Pitfall 3) |
| Wire parsing, unit conversion, metric allowlist | **`integrations/health_auto_export/`** | — | Provider isolation, mirroring `integrations/hevy/`. Wire schemas must not leak out of the package |
| Local-day resolution | **`app/core/time`** | integrations | `local_day(ts, users.timezone)` already exists and is the only correct source |
| Daily aggregation | **integrations (ingest)** | — | Must happen *before* the upsert, over the whole payload — not in SQL, not at read time (Pitfall N-2) |
| Idempotent persistence | **`integrations/.../ingest.py`** | `db/models/health.py` | Copy `hevy/body.py`'s constraint-by-name `on_conflict_do_update` |
| Hevy-source exclusion | **integrations (ingest) + analytics (read)** | — | See Open Question 1 — write-time vs read-time filtering is a genuine decision |
| Freshness bookkeeping | **`db/repositories/sync_state`** | `analytics/metadata` | Two resources per D-03 |
| Secret storage | **Google Secret Manager** | `app/config.py` | Same path as `MCP_AUTH_SECRET` |

---

## Standard Stack

**Zero new runtime dependencies.** `[VERIFIED: pyproject.toml read this session]` — every capability this
phase needs is already installed. This confirms `.planning/research/STACK.md`'s conclusion; nothing found in
this session changes it.

### Core (all already in `pyproject.toml`)

| Library | Version | Purpose | Why standard here |
|---|---|---|---|
| FastAPI | 0.141.1 | The ingest route | Already the app; route must sit above the catch-all mount |
| Pydantic | 2.13.4 | HAE wire models | `Decimal` field type handles Finding C correctly; `BeforeValidator` handles the non-ISO date |
| SQLAlchemy | 2.0.52 | `health_daily_metrics` model + `pg_insert` upsert | `on_conflict_do_update(constraint=…)` is the established idempotency mechanism |
| asyncpg | 0.31.0 | Driver | Unchanged |
| Alembic | 1.19.1 | The new-table migration | Unchanged |
| structlog | 26.1.0 | `health_ingest_unrecognized_metric` (D-04) and rejection events | Redaction is a processor, not a discipline |

### Supporting (stdlib only)

| Module | Purpose | When |
|---|---|---|
| `secrets.compare_digest` | Bearer-token check on **bytes** | HEALTH-07 — copy `mcp/auth.py:37-52` verbatim |
| `decimal.Decimal` | All quantities | Finding C — via `Decimal(str(x))` |
| `datetime.strptime` | `yyyy-MM-dd HH:mm:ss Z` parsing | Pydantic rejects this format natively |
| `zoneinfo` (via `core/time`) | `local_day` | FOUND-03, already in use |
| `types.MappingProxyType` | The immutable metric registry | Matches `recomposition._LABEL_MATRIX` / `exercise_map.py` discipline |

### Alternatives Considered

| Instead of | Could use | Tradeoff |
|---|---|---|
| stdlib `strptime` list | `dateutil` / `pendulum` | New dependency for two known formats; rejected |
| `Decimal` | `float` | Banned by `test_analytics_declares_no_float`, and Finding C makes precision load-bearing |
| Aggregate-in-Python | Aggregate in SQL on read | Contradicts ARCHITECTURE.md's day-grain decision and multiplies row count ~100× |
| Table-driven registry | Per-metric `if/elif` | Twelve metrics now, more in Phase 13; a table is testable as data |

**Installation:** none required.

**Version verification:** no new packages, so no registry lookups were needed. Installed versions read
directly from `pyproject.toml` this session. `[VERIFIED: pyproject.toml]`

---

## Architecture Patterns

### System Architecture Diagram — the ingest data flow

```
  iPhone: Health Auto Export automation
  (metric selection + aggregation interval + batching are DEVICE-side settings)
        │
        │  POST /api/v1/ingest/health-auto-export
        │  Authorization: Bearer <HEALTH_INGEST_SECRET>
        │  {"data": {"metrics": [ {name, units, data[]}, ... ]}}
        ▼
  ┌─────────────────────────────────────────────────────────────┐
  │ RateLimitMiddleware  — DEDICATED ingest bucket (not exempt) │
  │   over-limit ──────────────────────────────► 429/503 + log  │
  └─────────────────────────────────────────────────────────────┘
        ▼
  ┌─────────────────────────────────────────────────────────────┐
  │ Body-size guard — reject BEFORE parse                       │
  │   oversized ───────────────────────────────► 413            │
  └─────────────────────────────────────────────────────────────┘
        ▼
  ┌─────────────────────────────────────────────────────────────┐
  │ CorrelationIdMiddleware                                     │
  └─────────────────────────────────────────────────────────────┘
        ▼
  ┌─────────────────────────────────────────────────────────────┐
  │ FastAPI route  (registered ABOVE app.mount("/", mcp_app))   │
  │   secrets.compare_digest(bytes)                             │
  │     mismatch/absent ───────────────────────► 401 bare, silent│
  └─────────────────────────────────────────────────────────────┘
        ▼
  ┌─────────────────────────────────────────────────────────────┐
  │ schemas.py — Pydantic wire model                            │
  │   source: str|None  (absent for gait metrics — Finding §4.2)│
  │   units read at METRIC level, not datapoint level           │
  └─────────────────────────────────────────────────────────────┘
        ▼
  ┌─────────────────────────────────────────────────────────────┐
  │ normalize.py                                                │
  │   ├─ METRIC REGISTRY lookup (name → canonical unit, agg fn, │
  │   │    data-kind)                                           │
  │   │      unlisted ──► drop + log (D-04), CONTINUE           │
  │   ├─ unit conversion  (kJ→kcal, mg, g…)                     │
  │   │      unknown unit ──► drop datapoint + log LOUDLY       │
  │   ├─ parse "yyyy-MM-dd HH:mm:ss Z"  (NOT ISO-8601)          │
  │   ├─ HEVY SOURCE EXCLUSION  ◄── Finding A, HEALTH-08        │
  │   └─ local_day(ts, users.timezone)                          │
  └─────────────────────────────────────────────────────────────┘
        ▼
  ┌─────────────────────────────────────────────────────────────┐
  │ AGGREGATE the WHOLE payload                                 │
  │   group by (metric, source_name, local_day) → sum / avg     │
  │   ⚠ must precede the upsert — Pitfall N-2                   │
  └─────────────────────────────────────────────────────────────┘
        ▼
  ┌─────────────────────────────────────────────────────────────┐
  │ ingest.py — one transaction                                 │
  │   SAVEPOINT per row                                         │
  │   pg_insert(...).on_conflict_do_update(constraint="uq_...") │
  │   REPLACE semantics, never additive                         │
  │   sync_state: provider='apple_health',                      │
  │               resource ∈ {'activity','nutrition'}   (D-03)  │
  └─────────────────────────────────────────────────────────────┘
        ▼
  health_daily_metrics ───► 202 Accepted {counts only, no data}
```

### Recommended Project Structure

```
backend/app/
├── api/routes/
│   └── health_ingest.py          # NEW — terminates the webhook, auth, size cap
├── integrations/
│   ├── hevy/                     # unchanged
│   └── health_auto_export/       # NEW — mirrors hevy/'s provider isolation
│       ├── __init__.py
│       ├── auth.py               # bytes compare_digest
│       ├── errors.py             # mirrors hevy/errors.py
│       ├── registry.py           # THE METRIC REGISTRY (see Pattern 1)
│       ├── schemas.py            # Pydantic wire models — must not leak out
│       ├── normalize.py          # wire → canonical rows (shared with Phase 9)
│       └── ingest.py             # aggregate + idempotent upsert + sync_state
└── db/models/
    └── health.py                 # NEW — health_daily_metrics only (D-02)
```

### Pattern 1: The Metric Registry — one table, two data kinds

The core recommendation of this research. Everything that differs between an activity metric and a
nutrition metric is *data*; nothing is control flow.

```python
# integrations/health_auto_export/registry.py
from decimal import Decimal
from types import MappingProxyType
from typing import Literal, NamedTuple

Agg = Literal["sum", "avg"]
Kind = Literal["activity", "nutrition"]      # maps to D-03's sync_state resources


class MetricSpec(NamedTuple):
    canonical_unit: str
    accepted_units: frozenset[str]           # every unit HAE is known to emit
    aggregation: Agg
    kind: Kind


# The ONLY place a metric name appears. `MappingProxyType` so a caller cannot
# retune ingestion at runtime -- same discipline as recomposition._LABEL_MATRIX.
METRIC_REGISTRY = MappingProxyType({
    # --- Activity (HEALTH-06) ---
    "step_count":               MetricSpec("count", frozenset({"count"}),        "sum", "activity"),
    "active_energy":            MetricSpec("kcal",  frozenset({"kcal", "kJ"}),   "sum", "activity"),
    "basal_energy_burned":      MetricSpec("kcal",  frozenset({"kcal", "kJ"}),   "sum", "activity"),
    "walking_running_distance": MetricSpec("km",    frozenset({"km", "mi"}),     "sum", "activity"),
    "flights_climbed":          MetricSpec("count", frozenset({"count"}),        "sum", "activity"),

    # --- Nutrition (NUTR-02) --- names VERIFIED, see D-05 Resolution §1.
    # NOTE the inconsistent `dietary_` prefix: it is `total_fat` not `fat`,
    # `dietary_sugar` not `sugar`, but plain `protein`/`carbohydrates`/`fiber`/`sodium`.
    "dietary_energy":           MetricSpec("kcal",  frozenset({"kcal", "kJ"}),   "sum", "nutrition"),
    "protein":                  MetricSpec("g",     frozenset({"g"}),            "sum", "nutrition"),
    "carbohydrates":            MetricSpec("g",     frozenset({"g"}),            "sum", "nutrition"),
    "total_fat":                MetricSpec("g",     frozenset({"g"}),            "sum", "nutrition"),
    "fiber":                    MetricSpec("g",     frozenset({"g"}),            "sum", "nutrition"),
    "dietary_sugar":            MetricSpec("g",     frozenset({"g"}),            "sum", "nutrition"),
    "sodium":                   MetricSpec("mg",    frozenset({"mg", "g"}),      "sum", "nutrition"),
})

_KJ_PER_KCAL = Decimal("4.184")
_KM_PER_MILE = Decimal("1.609344")
```

**Why a registry rather than two normalizers:** D-05 asked whether nutrition needs its own normalizer. It
does not — but the reason it does not is that the *only* per-metric variation is captured here. Adding
Phase 13's metrics is a table edit with no code change, and `set(METRIC_REGISTRY) == EXPECTED_METRICS` is a
one-line drift guard in the style of `test_mcp_tool_schemas.py`'s `EXPECTED_TOOLS` frozenset.

### Pattern 2: Unit conversion that fails loudly

```python
def to_canonical(qty: Decimal, wire_unit: str, spec: MetricSpec) -> Decimal:
    """Convert at the boundary. An UNKNOWN unit is a rejected datapoint, never a raw number.

    HAE units are a user preference inside the app and are converted on-device at
    export time, so a settings change silently alters the wire units on the next
    export. Storing an unconverted value would be a plausible number that is
    quietly wrong -- this project's stated primary risk.
    """
    if wire_unit not in spec.accepted_units:
        raise UnknownUnitError(unit=wire_unit)          # caller logs + drops the datapoint
    if wire_unit == spec.canonical_unit:
        return qty
    if spec.canonical_unit == "kcal" and wire_unit == "kJ":
        return qty / _KJ_PER_KCAL
    if spec.canonical_unit == "km" and wire_unit == "mi":
        return qty * _KM_PER_MILE
    if spec.canonical_unit == "mg" and wire_unit == "g":
        return qty * 1000
    raise UnknownUnitError(unit=wire_unit)
```

Note this deliberately **rejects the datapoint rather than the payload** — consistent with D-04's principle
that one bad element must never cost the whole window.

### Pattern 3: Aggregate the whole payload, then upsert once

```python
# Group the ENTIRE payload before touching the database. Real payloads carry
# 189 datapoints for one metric-day (Finding B), and the table holds one row.
buckets: dict[tuple[str, str, date], list[Decimal]] = defaultdict(list)
for metric in payload.data.metrics:
    spec = METRIC_REGISTRY.get(metric.name)
    if spec is None:
        log.warning("health_ingest_unrecognized_metric", metric=metric.name)  # D-04
        continue
    for point in metric.data:
        if is_hevy_sourced(point.source):        # Finding A / HEALTH-08
            continue
        value = to_canonical(Decimal(str(point.qty)), metric.units, spec)
        day = local_day(parse_hae_date(point.date), user_timezone)
        buckets[(metric.name, point.source or UNKNOWN_SOURCE, day)].append(value)

# One row per key, REPLACE semantics -- re-sending the same window is a no-op.
for (name, source_name, day), values in buckets.items():
    write_row(name, source_name, day, aggregate(values, METRIC_REGISTRY[name].aggregation))
```

### Pattern 4: The date parser — two formats, neither ISO-8601 by default

```python
# Real payloads: "2025-08-15 00:00:00 +0900"  -- NOT ISO 8601.
# Pydantic's `datetime` field type rejects this outright.
# A third-party implementation reports also seeing "2024-01-01T12:00:00+00:00".
_HAE_DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S %z",
    "%Y-%m-%d %I:%M:%S %p %z",     # 12-hour locales
)
```
`[VERIFIED: 5 real payloads all use "%Y-%m-%d %H:%M:%S %z"]`
`[CITED: .planning/research/ARCHITECTURE.md — the U+202F narrow-no-break-space variant newer iOS inserts
before AM/PM]`

**The same parser serves Phase 9.** `export.xml`, `records.csv` and the HAE JSON all use this format —
verified again this session against the user's own `records.csv` (`2026-08-21 12:35:53 +0700`). Do not
write two.

### Anti-Patterns to Avoid

- **Deriving nutrition metric names from the vendor's enum *keys*.** The keys are all `DIETARY_*`; the wire
  values mostly are not. Yields `dietary_protein`, which D-04 silently drops.
- **Requiring `source` in the Pydantic model.** Absent for gait metrics in every real payload; under
  whole-payload validation this loses the entire window.
- **`INTEGER` columns or `int()` casts for `count` metrics.** Finding C — real values are fractions.
- **Additive upsert (`qty = qty + excluded.qty`).** Not idempotent; fails success criterion #3 directly.
- **A metric-name allowlist as the whole of HEALTH-08.** Finding A — `active_energy` is allowlisted *and*
  Hevy-written.
- **Reading the datapoint-level `units` field.** It does not exist in real payloads; the vendor's own
  server reads the metric-level one.
- **Adding the ingest path to `EXEMPT_PREFIXES`.** Would make an internet-reachable write path the one
  unbounded surface on an `--allow-unauthenticated` service (Pitfall 2).

---

## Don't Hand-Roll

| Problem | Don't build | Use instead | Why |
|---|---|---|---|
| Constant-time secret compare | A `==` check, or a `str` `compare_digest` | `secrets.compare_digest` on **bytes**, copying `mcp/auth.py:37-52` | `==` leaks the secret a byte at a time; the `str` overload raises `TypeError` on a non-ASCII header byte → 500 with traceback instead of a silent 401 |
| Idempotent write | `SELECT`-then-`INSERT`/`UPDATE` | `pg_insert(...).on_conflict_do_update(constraint="uq_…")` from `hevy/body.py:97-120` | Race-free in one statement; binding **by name** raises immediately if the constraint is renamed instead of degrading into duplicate rows |
| Per-row error isolation | try/except around the batch | `session.begin_nested()` SAVEPOINT per row (`hevy/body.py`) | One bad row otherwise aborts the whole transaction |
| Local-day resolution | `ts.date()` or server UTC date | `core.time.local_day(ts, users.timezone)` | At UTC+7 every instant 17:00–24:00Z belongs to the *next* local day |
| Secret redaction in logs | Manual scrubbing at call sites | Add `health_ingest_secret` to `config._SECRET_FIELDS` | The `configure_logging` value scrubber then redacts it everywhere, automatically |
| Rate limiting | New middleware | Second `TokenBucket` on the existing `RateLimitMiddleware` via `app.state` | The middleware already supports per-path bucket selection; this is additive wiring |
| Date parsing | A regex | `datetime.strptime` with an ordered format list | Handles the `+0900` offset correctly; a regex will not survive the 12-hour variant |
| Wire→DB decimal | `Decimal(float_value)` | `Decimal(str(float_value))` | Direct float→Decimal imports binary representation error into stored health data |

**Key insight:** every mechanism this phase needs already exists in this repo, proven against production
traffic. The phase's genuine novelty is entirely in the *metric registry* and the *aggregation step* —
which is exactly where the research effort and the review attention should go.

---

## Runtime State Inventory

Phase 8 is additive rather than a rename, but it does change state that lives outside the repository. Each
category is answered explicitly.

| Category | Items found | Action required |
|---|---|---|
| **Stored data** | `health_daily_metrics` is a **new** table — no existing rows to migrate. `sync_state` gains two rows (`provider='apple_health'`, `resource ∈ {activity, nutrition}`) created lazily by `ensure_sync_state`. `SyncState.provider` is `String(32)` and `resource` is `String(32)` — `apple_health` (12), `activity` (8), `nutrition` (9) all fit. `[VERIFIED: db/models/sync_state.py]` | Alembic migration for the new table; no data migration |
| **Live service config** | Cloud Run service flags in `scripts/deploy-cloud-run.sh`: currently `--memory=512Mi` (line 37) and `--set-secrets="DATABASE_URL=…,MCP_AUTH_SECRET=…"` (line 40). Both must change. `[VERIFIED: read this session]` | Raise to `--memory=1Gi`; append `HEALTH_INGEST_SECRET=brett-health-ingest-secret:latest` |
| **OS-registered / device state** | **The iPhone's Health Auto Export automation** — metric selection, aggregation interval, Batch Requests toggle, destination URL and custom header. Lives only on the device; BRETT cannot read or enforce it. **This is the only piece of Phase 8 state that is not under version control, and Pitfall N-2 shows it is correctness-relevant, not cosmetic.** | Write a setup doc specifying the **required** aggregation interval; verify with a captured payload before declaring the phase done |
| **Secrets / env vars** | New `HEALTH_INGEST_SECRET` in Google Secret Manager, mirroring `brett-mcp-auth-secret`. New `health_ingest_secret: SecretStr` field in `Settings` and a new entry in `_SECRET_FIELDS`, which is currently `("database_url", "hevy_api_key", "mcp_auth_secret")`. `[VERIFIED: config.py:25]` | Create the secret; add the field; extend `_SECRET_FIELDS` (a `test_secret_redaction.py` case comes free) |
| **Build artifacts** | None — no package rename, no compiled artifacts, no `egg-info`. Verified: the phase adds modules and a migration only. | None |

---

## Common Pitfalls

Pitfalls 1–9 in `.planning/research/PITFALLS.md` remain accurate and are **not** repeated here; they were
re-read this session and every file/line reference still resolves. The pitfalls below are **new**, and all
arise from findings in this session.

### Pitfall N-1: A day-grained row that blends sources makes HEALTH-08 unenforceable

**What goes wrong.** `ARCHITECTURE.md` proposes the natural key `(user_id, source, metric, local_day)` with
`source_name` as a **non-key, nullable column**. Under that key, one day of `active_energy` is a single row
— so the iPhone's 22 records and Hevy's 1 record collapse together, and `source_name` becomes ambiguous
(which of the two does it hold?). **Once summed, Hevy's 70–88 % contribution can never be filtered out**
(Finding A). ARCHITECTURE.md's own stated intent — *"excluding Hevy-originated energy from an activity total
is impossible \[without `source_name`]; with it, it is a `WHERE` clause"* — is defeated by its own key
choice. Finding D makes the same problem real for nutrition on 2026-08-23.

**Why it happens.** `source_name` was added for exactly this purpose, but keeping it out of the unique key
looked like a harmless normalisation choice when the only known multi-source metric was assumed benign.

**How to avoid.** Include `source_name` in the natural key:
`(user_id, source, metric, source_name, local_day)`. Then Hevy's `active_energy` is its own row, excluded
by predicate at read time (or at write time — Open Question 1), and Foodvisor vs Built With Science stay
distinguishable.

**⚠ Sub-trap:** `source_name` is **nullable** and PostgreSQL treats `NULL`s as distinct in a unique
constraint, so nullable-in-key silently permits duplicate rows. Real payloads *do* omit `source` (§4.2).
Either declare `source_name NOT NULL` with an explicit sentinel (`'unknown'`) written at normalize time —
**recommended, works on every PostgreSQL version** — or use `UNIQUE NULLS NOT DISTINCT`, which requires
PostgreSQL ≥ 15 and has not been verified against this Neon instance.

**Warning signs.** A daily active-energy figure ~4× the iPhone's own reading on training days. A
`SELECT DISTINCT source_name` returning fewer values than the payload contained.

---

### Pitfall N-2: Aggregation and idempotency are coupled, and HAE's Batch Requests toggle can break both ★

**The sharpest correctness risk in the phase.**

**What goes wrong.** Real payloads carry **189 datapoints for one metric-day** (Finding B) and the table
holds one row, so the ingest must aggregate. That forces a choice of conflict semantics, and both obvious
options are wrong in one direction:

| Conflict clause | Re-sending an overlapping window | A day split across two batched POSTs |
|---|---|---|
| `SET qty = qty + excluded.qty` (additive) | **Double-counts** — fails success criterion #3 | Correct |
| `SET qty = excluded.qty` (replace) | Correct — a no-op | **Silently loses the first batch** |

HAE's **Batch Requests** toggle "splits one export across multiple POSTs"
`[CITED: help.healthyapps.dev — automations/rest-api]`, and `PITFALLS.md` Pitfall 5 *recommends turning it
on* to manage payload size. Nothing in the vendor docs guarantees a batch boundary never falls inside a day.

**Why it happens.** Aggregation reads as a performance concern and idempotency as a correctness concern, so
they get designed separately. `ARCHITECTURE.md` frames the HAE aggregation-interval setting purely as a
payload-size optimisation ("costs nothing", "device-side setting"), which invites treating it as optional.

**How to avoid.** Resolve it at the *device* configuration layer and make that configuration a stated
prerequisite:

1. **Set the HAE aggregation interval to daily.** Each metric then emits **one datapoint per day**, so a
   batch boundary can only fall *between* days. Replace-semantics becomes unambiguously correct, and the
   payload shrinks by roughly two orders of magnitude — which independently resolves Pitfall 5. This
   promotes the setting from a preference to a **documented deploy prerequisite**.
2. Use **replace** semantics (`SET qty = excluded.qty`), matching `hevy/body.py`'s row-replacement
   reasoning.
3. Aggregate over the **whole payload** before the first write (Pattern 3), so within-payload duplicates
   are handled regardless.
4. Add a guard: log `health_ingest_multi_point_day` when a payload yields >1 datapoint for a
   `(metric, source_name, local_day)` key. Under a correct device configuration this never fires; when it
   does, the device setting has drifted and replace-semantics is now lossy. **This turns a silent data-loss
   mode into an observable one.**

**Warning signs.** Daily step totals that fall after a re-sync. A day whose value drops when a later
overlapping window arrives. `flights_climbed` totals that vary between identical re-sends.

---

### Pitfall N-3: The webhook's `source` strings differ from `export.xml`'s, and one carries a curly apostrophe

**What goes wrong.** Two source vocabularies exist and they are not the same:

| Path | Field | Observed values |
|---|---|---|
| Webhook (real HAE payloads) | `source` | `"iPhone"`, `"カロミル"` |
| `export.xml` / `records.csv` (user's own) | `sourceName` | `"Vegant's iPhone"`, `"V's iPhone"`, `"Hevy"`, `"Foodvisor"`, `"Built With Science"` |

`[VERIFIED: 5 real payloads + user's records.csv, both queried this session]`

Two distinct hazards. (a) A Hevy-exclusion predicate written against `export.xml`'s vocabulary may not match
what the webhook sends — and Finding A makes that predicate load-bearing for HEALTH-08. (b) The device names
contain **U+2019 RIGHT SINGLE QUOTATION MARK**, not an ASCII apostrophe: `Vegant’s iPhone`. Any hardcoded
`"Vegant's iPhone"` comparison fails silently. The device was also **renamed** mid-history (366,339 records
under one name, 70,900 under the other), so device-name matching is unstable regardless.

**How to avoid.** Match on the **app name** (`"Hevy"`), never on the device name — the app name is what
HEALTH-08 actually cares about and it is stable across device renames. Define it as a module constant beside
`hevy.body.SOURCE_HEVY`, never an inline literal. Treat matching as case-insensitive and
whitespace-stripped. **Verify the exact webhook spelling against a captured payload before the predicate is
trusted** — this is the one part of Finding A that a third-party payload cannot settle, because those users
do not have Hevy installed.

**Warning signs.** A source-exclusion filter that never excludes anything. `SELECT DISTINCT source_name`
showing a device name the code compares against but never matches.

---

### Pitfall N-4: Midnight-anchored daily totals shift a day if the device timezone ≠ `users.timezone`

**What goes wrong.** Nutrition apps that write a daily total anchor it at local midnight — real payload:
`"2025-08-15 00:00:00 +0900"`. `local_day(ts, users.timezone)` re-resolves that instant in the *user's*
configured zone. If the two disagree by any positive offset, midnight lands on the **previous** day: the
same instant read at `Asia/Jakarta` (+07:00) is `2025-08-14 22:00`, i.e. day `2025-08-14`.

**Why it happens.** `local_day` is the correct, project-wide rule (FOUND-03) and applying it uniformly is
the right instinct. The failure needs a timezone mismatch to appear, which will not happen in local testing.

**How to avoid.** Today the user is `Asia/Jakarta` and the phone emits `+0700`, so the two agree and this is
dormant — but it activates on travel or a mis-set `users.timezone`. Add a regression test that feeds a
midnight-anchored datapoint whose offset differs from `users.timezone` and asserts the intended day. Then
make the choice explicit in the plan rather than by default: either keep `local_day` (consistent, and a
travelling user's nutrition genuinely belongs to the local day they ate it) or trust the payload's own date
part for daily-aggregate metrics. **Recommend `local_day`** for consistency with every other table, with
the test documenting the known behaviour.

**Warning signs.** A nutrition day whose calories are zero next to a neighbouring day with double.

---

### Pitfall N-5: `test_hevy_isolation.py`'s guards do not automatically cover the new package

**What goes wrong.** `test_hevy_isolation.py` enforces provider isolation with a walk scoped to
`HEVY_PKG = APP / "integrations" / "hevy"` `[VERIFIED: read this session]`. A new
`integrations/health_auto_export/` package inherits **none** of it. Its wire schemas can leak into
`app/db/` or `app/analytics/` and every existing isolation test still passes green.

**How to avoid.** Add the parallel guard in the same file/style — CONTEXT.md already calls for this
("The new `integrations/health_auto_export/` package must get the equivalent guard"). Note the `httpx2`
guard does **not** transfer: this integration is inbound and must never make an HTTP call at all, so the
correct assertion is the stronger one — that **no** HTTP client is imported anywhere in the package.

---

## Code Examples

### Real HAE nutrition payload (verbatim from a captured device export)

```json
{"data": {"metrics": [
  {"name": "dietary_energy", "units": "kcal",
   "data": [{"qty": 1857, "source": "カロミル", "date": "2025-08-15 00:00:00 +0900"}]},
  {"name": "protein", "units": "g",
   "data": [{"qty": 155.7, "date": "2025-08-15 00:00:00 +0900", "source": "カロミル"}]},
  {"name": "carbohydrates", "units": "g",
   "data": [{"qty": 67.6, "source": "カロミル", "date": "2025-08-15 00:00:00 +0900"}]},
  {"name": "total_fat", "units": "g",
   "data": [{"source": "カロミル", "qty": 104.6, "date": "2025-08-15 00:00:00 +0900"}]},
  {"name": "fiber", "units": "g",
   "data": [{"qty": 13, "date": "2025-08-15 00:00:00 +0900", "source": "カロミル"}]},
  {"name": "dietary_sugar", "units": "g",
   "data": [{"date": "2025-08-15 00:00:00 +0900", "source": "カロミル", "qty": 53.9}]},
  {"name": "sodium", "units": "mg",
   "data": [{"qty": 3177.165354330709, "source": "カロミル",
             "date": "2025-08-15 00:00:00 +0900"}]},

  {"name": "flights_climbed", "units": "count",
   "data": [{"date": "2025-08-15 08:02:00 +0900", "source": "iPhone",
             "qty": 0.20163697817574894}]},

  {"name": "walking_speed", "units": "km/hr",
   "data": [{"qty": 4.68, "date": "2025-08-15 07:30:00 +0900"}]}
]}}
```
`[VERIFIED: github.com/bunya-gap/health-management-free — health_api_data/health_data_2025-08-15T*.json;
5 files fetched and parsed this session]`

Four things this single example proves, all load-bearing: nutrition and activity share one envelope;
`units` sits at the metric level only; `flights_climbed` is **fractional** despite `units: "count"`; and
`walking_speed` has **no `source` key at all**. Note also that key order inside each datapoint object varies
between entries — irrelevant to JSON parsing, but a fixture comparison must not assume ordering.

**Recommended fixture strategy.** CONTEXT.md and STATE.md both ask for "one real payload captured before
writing the normalizer." That remains the right call for the Hevy-source question (Pitfall N-3), which only
this user's phone can answer. For everything else, the payload above plus the four sibling files are already
real device output and can seed `backend/tests/fixtures/` immediately — following the existing
`hevy_fixture()` convention in `conftest.py:125`. This unblocks normalizer work now rather than gating it on
a device capture.

### The auth check — copy this verbatim

```python
# integrations/health_auto_export/auth.py
# Copied from app/mcp/auth.py:37-52. Compared as BYTES, never `str`:
# secrets.compare_digest raises TypeError on a str holding non-ASCII characters,
# and the ASGI server latin-1 decodes header bytes -- so one arbitrary byte in the
# Authorization header escapes as an unhandled 500 with a traceback rather than a
# silent 401, breaking the fail-closed contract.
def verify(presented: str, secret: str) -> bool:
    return secrets.compare_digest(presented.encode("utf-8"), secret.encode("utf-8"))
```
`[VERIFIED: backend/app/mcp/auth.py, read this session]`

### The idempotent upsert — the shape to mirror

```python
# Mirrors integrations/hevy/body.py:97-120.
stmt = pg_insert(HealthDailyMetric).values(...)
stmt = stmt.on_conflict_do_update(
    # Bound BY NAME, not by column list: renaming the constraint then raises
    # immediately instead of silently degrading into duplicate-row inserts.
    constraint="uq_health_daily_metrics_user_source_metric_sourcename_day",
    set_={"value": stmt.excluded.value, "units": stmt.excluded.units,
          "sample_count": stmt.excluded.sample_count},
)
```
`[VERIFIED: backend/app/integrations/hevy/body.py, read this session]`

---

## State of the Art

| Old understanding | Current, verified understanding | Impact |
|---|---|---|
| Nutrition wire format unknown (CONTEXT.md D-05) | All 7 names + units verified three independent ways | Planning can write concrete schemas now |
| `weight_body_mass` vs `weight_&_body_mass` unsettled (STATE.md blocker) | `weight_body_mass`, 623:6 plus the vendor's enum | STATE.md's Phase 8 open question can be **closed** |
| HEALTH-08 = exclude workouts + body-mass | Hevy also writes `active_energy` (70–88 % of training days) | **New scope item** — source-level filter required |
| HAE aggregation interval = payload-size tuning | It is a **correctness** prerequisite (Pitfall N-2) | Must be documented + guarded, not left to preference |
| `source_name` a non-key column | Must be in the natural key or HEALTH-08 is unenforceable | Schema change vs ARCHITECTURE.md |
| One nutrition source (Foodvisor) | Two — `Built With Science` overlaps on 2026-08-23 | Multi-source-per-day is real |
| `count` metrics are integers | Fractional (`0.2016…`) | `NUMERIC`/`Decimal` mandatory |

**Deprecated / superseded:**
- `ARCHITECTURE.md`'s allowlist row *"`weight_body_mass`, `sleep_analysis` as `inBed` only"* — both are out
  of scope for Phase 8 under D-01 and the v2.0 sleep cut. The activity five plus the nutrition seven are the
  complete Phase 8 allowlist.
- `ARCHITECTURE.md`'s `sync_state` resource names `'health_metrics' | 'health_workouts'` — superseded by
  D-03's `'activity' | 'nutrition'`.
- `PITFALLS.md` Pitfall 4's natural key `(user_id, source, metric_name, measured_at)` — sample-grained;
  superseded by the day-grained key, which Pitfall N-1 further amends.

---

## Assumptions Log

| # | Claim | Section | Risk if wrong |
|---|---|---|---|
| A1 | HAE emits `source: "Hevy"` (app name) over the webhook, matching `export.xml`'s `sourceName` | Pitfall N-3, Finding A | **HIGH** — the HEALTH-08 exclusion predicate never matches and Hevy's active-energy is ingested silently. Third-party payloads cannot settle this (those users lack Hevy). **Verify with one captured payload from a training day.** |
| A2 | HAE's daily aggregation interval emits exactly one datapoint per metric per day | Pitfall N-2 | **HIGH** — replace-semantics becomes lossy under batching. Mitigated by the `health_ingest_multi_point_day` guard log, which converts it to an observable failure |
| A3 | The Neon PostgreSQL instance is ≥ 15 (for `NULLS NOT DISTINCT`) | Pitfall N-1 | LOW — the recommended `NOT NULL` + `'unknown'` sentinel avoids the dependency entirely |
| A4 | This user's HAE build emits 24-hour timestamps | Pattern 4 | LOW — the format list handles both; carried forward from prior research |
| A5 | `sodium` is never emitted in `g` | Registry | LOW — the registry accepts both and converts; a wrong guess is caught by `UnknownUnitError`, not silently stored |
| A6 | Nutrition freshness should advance only when a nutrition metric is present in the payload | D-03 | MEDIUM — advancing both resources on every delivery would report nutrition "fresh" when the logging app has stopped, defeating D-03's stated purpose. See Open Question 2 |

Everything in "D-05 Resolution" §1–5 and in Findings A–D is `[VERIFIED]` and carries **no** assumption.

---

## Open Questions

1. **Should the Hevy-source exclusion happen at write time or read time?**
   - *What we know:* Finding A proves the filter is required. The schema in Pitfall N-1 supports either.
   - *What's unclear:* Dropping at ingest is simpler and keeps the table clean, but discards evidence and is
     irreversible without a Phase 9 re-run. Keeping the row and filtering in analytics preserves the
     coverage cross-check D-02 declined to build, at the cost of a rule every future analytics function
     must remember — the same trap `PITFALLS.md` Pitfall 9 describes for `_dedupe_by_day`.
   - *Recommendation:* **Filter at write time for Phase 8.** It makes success criterion #4 ("volume,
     frequency and body-weight numbers identical before and after Apple Health data exists") provable by a
     row-count assertion rather than by auditing every downstream reader, and it matches D-02's stated
     preference for exclusion over quarantine. Record the decision in the plan so a later phase can revisit
     it deliberately.

2. **Should `resource='nutrition'` advance when a payload contains no nutrition metrics?**
   - *What we know:* D-03 splits the resources precisely so a partial failure is visible. Both kinds arrive
     in one POST.
   - *What's unclear:* If both resources advance on every successful delivery, a nutrition-logging app that
     stopped writing to HealthKit still reports fresh — exactly the blind spot D-03 exists to remove.
   - *Recommendation:* Advance each resource **only when that payload contained ≥1 accepted metric of that
     kind.** The `kind` field in the metric registry makes this a one-line derivation. (Assumption A6.)

3. **Does a `sample_count` of aggregated datapoints belong on the row?**
   - *What we know:* `ARCHITECTURE.md` includes `sample_count`; Finding B makes it meaningful (189 vs 1).
   - *Recommendation:* Keep it. It is the cheapest available diagnostic for Pitfall N-2 — a day whose
     `sample_count` falls on a re-sync is a batch-split data loss, visible in one query.

4. **How thin is nutrition for Phase 13's trend work?** *(forward-looking, not Phase 8 scope)*
   - 53 distinct days of dietary energy across 4.5 years, but current and recently consistent. Flagged now
     so NUTR-04's coverage floors are designed rather than discovered.

---

## Environment Availability

| Dependency | Required by | Available | Version | Fallback |
|---|---|---|---|---|
| Python | Everything | ✓ | 3.13.9 (`.python-version` = 3.13) | — |
| uv | Build/test | ✓ | 0.12.1 | — |
| Docker | `testcontainers` Postgres (integration tests) | ✓ | 29.4.2, running | — |
| `gcloud` | Cloud Run deploy + Secret Manager | ✓ | 578.0.0 | — |
| PostgreSQL (test) | `testcontainers[postgres]` 4.15.0 | ✓ via Docker | — | — |
| pytest + asyncio + cov | Test suite | ✓ | 9.1.1 / 1.4.0 / 7.1.0 | — |
| `time-machine` | Clock-dependent tests | ✓ | 3.4.0 | — |
| User's `export.xml` / `records.csv` | Ground-truth verification | ✓ | 191 MB, at repo root, git-ignored | — |
| **A captured HAE payload from the user's phone** | Assumption A1 (Hevy `source` spelling) | **✗** | — | Third-party real payloads seed fixtures; A1 still needs one device capture |
| **`HEALTH_INGEST_SECRET` in Secret Manager** | HEALTH-07 | **✗** | — | Created during the phase; no fallback |
| **Cloud Run `--memory=1Gi`** | Pitfall 5 | **✗** (currently 512Mi) | — | Deploy-script change; no fallback |

**Missing with no fallback:** the Secret Manager entry and the memory flag — both are ordinary phase work,
already called out in the roadmap notes.
**Missing with fallback:** the device payload capture — normalizer development can proceed on the verified
third-party payloads; only assumption A1 blocks on it, and only for the Hevy-exclusion predicate.

---

## Validation Architecture

### Test Framework

| Property | Value |
|---|---|
| Framework | pytest 9.1.1 + pytest-asyncio 1.4.0 (`asyncio_mode = "auto"`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths = ["backend/tests"]`, `pythonpath = ["backend"]`) |
| Quick run command | `uv run pytest -m "not integration"` |
| Full suite command | `uv run pytest` |
| Postgres for integration | `testcontainers[postgres]` 4.15.0 via the `integration` marker; Docker verified running |

`[VERIFIED: pyproject.toml + backend/tests/conftest.py read this session]`

### Phase Requirements → Test Map

| Req | Behavior | Type | Automated command | File exists? |
|---|---|---|---|---|
| HEALTH-06 | Activity metrics normalize to canonical units/day | unit | `uv run pytest backend/tests/test_health_auto_export_normalize.py -x` | ❌ Wave 0 |
| HEALTH-06 | Route resolves to FastAPI, **not** the MCP mount | integration | `uv run pytest backend/tests/test_health_ingest_route.py -x -m integration` | ❌ Wave 0 |
| HEALTH-07 | No credential → 401, writes nothing, no detail | integration | `uv run pytest backend/tests/test_health_ingest_auth.py -x -m integration` | ❌ Wave 0 |
| HEALTH-07 | Wrong credential → 401, identical response shape | integration | same file | ❌ Wave 0 |
| **HEALTH-08** | **Hevy-sourced `active_energy` never lands (Finding A)** | unit | `uv run pytest backend/tests/test_health_auto_export_normalize.py -k hevy -x` | ❌ Wave 0 |
| HEALTH-08 | Volume/frequency/body-weight identical before & after ingest | integration | `uv run pytest backend/tests/test_health_ingest_isolation.py -x -m integration` | ❌ Wave 0 |
| HEALTH-09 | Identical payload twice → row counts + every value unchanged | integration | `uv run pytest backend/tests/test_health_ingest_idempotency.py -x -m integration` | ❌ Wave 0 |
| HEALTH-09 | Overlapping (not identical) window → still unchanged | integration | same file | ❌ Wave 0 |
| HEALTH-11 | `sync_state` advances for `('apple_health','activity')` | integration | `uv run pytest backend/tests/test_sync_state.py -k apple_health -x -m integration` | ⚠️ extend existing |
| HEALTH-11 | `build_freshness` accepts `(provider, resource)` pairs | unit | `uv run pytest backend/tests/test_analytics_metadata.py -x` | ⚠️ extend existing |
| NUTR-02 | All 7 nutrition names parse; `dietary_sugar`/`total_fat` spelled right | unit | `uv run pytest backend/tests/test_health_auto_export_normalize.py -k nutrition -x` | ❌ Wave 0 |
| NUTR-02 | `sodium` mg preserved; `kJ` → kcal converts | unit | same file | ❌ Wave 0 |
| NUTR-03 | Nutrition idempotent under re-send | integration | `uv run pytest backend/tests/test_health_ingest_idempotency.py -k nutrition -x -m integration` | ❌ Wave 0 |
| NUTR-05 | `sync_state` advances for `('apple_health','nutrition')` independently | integration | `uv run pytest backend/tests/test_sync_state.py -k nutrition -x -m integration` | ⚠️ extend existing |
| D-04 | Unlisted metric dropped, rest of payload still ingested | unit | `uv run pytest backend/tests/test_health_auto_export_normalize.py -k unrecognized -x` | ❌ Wave 0 |
| Finding C | Fractional `count` values survive (no truncation to 0) | unit | same file | ❌ Wave 0 |
| §4.2 | Datapoint with **no** `source` key validates | unit | `uv run pytest backend/tests/test_health_auto_export_schema.py -x` | ❌ Wave 0 |
| Pitfall N-4 | Midnight-anchored point, offset ≠ user tz → intended day | unit | `uv run pytest backend/tests/test_health_auto_export_normalize.py -k timezone -x` | ❌ Wave 0 |
| Pitfall N-5 | HAE wire schemas do not leak; no HTTP client in the package | unit | `uv run pytest backend/tests/test_health_auto_export_isolation.py -x` | ❌ Wave 0 |
| Pitfall 2 | Ingest burst does not drain the `/mcp` bucket | unit | `uv run pytest backend/tests/test_rate_limit.py -k ingest -x` | ⚠️ extend existing |
| Pitfall 5 | Oversized body → 413 **before** parse | integration | `uv run pytest backend/tests/test_health_ingest_route.py -k oversized -x -m integration` | ❌ Wave 0 |
| Runtime state | `health_ingest_secret` redacted from logs | unit | `uv run pytest backend/tests/test_secret_redaction.py -x` | ⚠️ extend existing |
| Runtime state | Deploy script sets `--memory=1Gi` + the new secret | unit | `uv run pytest backend/tests/test_cloud_run_deploy.py -x` | ⚠️ extend existing |

### Sampling Rate

- **Per task commit:** `uv run pytest -m "not integration"`
- **Per wave merge:** `uv run pytest`
- **Phase gate:** full suite green before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `backend/tests/fixtures/hae_*.json` — real captured payloads (seed from the verified third-party files; see Code Examples), covering NUTR-02, HEALTH-06
- [ ] `backend/tests/test_health_auto_export_schema.py` — wire-model shape, optional `source`
- [ ] `backend/tests/test_health_auto_export_normalize.py` — registry, units, dates, Hevy filter, D-04
- [ ] `backend/tests/test_health_auto_export_isolation.py` — the Pitfall N-5 guard
- [ ] `backend/tests/test_health_ingest_route.py` — mount-order + size cap
- [ ] `backend/tests/test_health_ingest_auth.py` — HEALTH-07 negatives
- [ ] `backend/tests/test_health_ingest_idempotency.py` — HEALTH-09 / NUTR-03
- [ ] `backend/tests/test_health_ingest_isolation.py` — success criterion #4
- [ ] No framework install needed — pytest, testcontainers, time-machine all present

---

## Security Domain

### Applicable ASVS Categories

| ASVS category | Applies | Standard control |
|---|---|---|
| **V2 Authentication** | **yes** | `secrets.compare_digest` on **bytes**, copying `mcp/auth.py:37-52`. Fail **closed** and **silent**: bare 401, no body detail, nothing logged about the presented credential. Success criterion #2 requires exactly this |
| V3 Session Management | no | Stateless webhook; no session is created |
| **V4 Access Control** | **yes** | Single-user service; `user_id` resolved server-side from `DEFAULT_USER_ID`, **never** from the payload. HAE cannot supply one and must not be able to |
| **V5 Input Validation** | **yes** | Pydantic 2.13.4 wire models + the metric allowlist (D-04) + `UnknownUnitError`. Body-size cap **before** parse. Every quantity through `Decimal(str(...))` |
| V6 Cryptography | partial | No custom crypto. Secret generated with `secrets.token_urlsafe(48)`, stored in Google Secret Manager, never committed |
| **V7 Error Handling / Logging** | **yes** | `health_ingest_secret` added to `config._SECRET_FIELDS` so the value scrubber redacts it automatically. Never log a `qty` — a calorie count is personal health data. Follow `format_sync_error`: class name only, never `str(exc)` (a Pydantic `ValidationError.__str__` renders `input_value=…`, i.e. the health data itself) |
| **V8 Data Protection** | **yes** | 202 response carries **counts only**, never values. HTTPS enforced by Cloud Run |
| **V13 API / Web Service** | **yes** | Dedicated rate-limit bucket (never `EXEMPT_PREFIXES`). No CORS — the caller is an iOS app, not a browser |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard mitigation |
|---|---|---|
| Unauthenticated public write path on `--allow-unauthenticated` Cloud Run | Tampering / Elevation | Explicit bearer check in the route; a static guard asserting every FastAPI route except `/health` carries auth (PITFALLS.md #3) |
| Timing attack on the shared secret | Information Disclosure | `compare_digest`, never `==` |
| Non-ASCII byte in the `Authorization` header | Denial of Service | Compare as **bytes**; the `str` overload raises `TypeError` → 500 + traceback |
| Payload-size OOM (503 with no log line) | Denial of Service | 413 before parse **and** `--memory=1Gi` |
| Ingest burst starving the `/mcp` bucket | Denial of Service | Dedicated bucket (Pitfall 2) |
| Health values leaking into logs or the 202 body | Information Disclosure | Counts-only responses; deny-list logging; never `str(exc)` |
| Credential in the URL query string | Information Disclosure | Header only — a query token lands in Cloud Run access logs |
| Poisoned `source` field steering the Hevy filter | Tampering | Filter is an allow/deny on a fixed constant; `source` is never used to build SQL |

---

## Sources

### Primary (HIGH confidence)
- **`HealthyApps/health-auto-export-server`** — the **vendor's own** reference server, fetched and read in
  full this session: `server/src/models/MetricName.ts` (the complete metric enum, incl. the `// Nutrition`
  block), `server/src/models/Metric.ts` (`MetricData`/`BaseMetric` shapes and `mapMetric`'s dispatch),
  `server/src/models/IngestData.ts`, `server/src/controllers/ingester.ts`
- **5 real captured HAE payloads** — `bunya-gap/health-management-free/health_api_data/health_data_2025-08-15T*.json`
  — live device output with nutrition; parsed directly. The strongest wire-format evidence available
- **The user's own `records.csv` / `export.xml`** (191 MB, at the repo root) — queried directly this session
  for dietary types/sources/units, Hevy's complete write set, and the `ActiveEnergyBurned` per-source
  breakdown. The basis for Findings A, B and D
- **BRETT source, read directly** — `app/main.py`, `app/middleware.py`, `app/mcp/auth.py`, `app/config.py`,
  `app/analytics/metadata.py`, `app/integrations/hevy/body.py`, `app/db/models/sync_state.py`,
  `app/core/time.py`, `backend/tests/test_hevy_isolation.py`, `backend/tests/conftest.py`,
  `scripts/deploy-cloud-run.sh`, `pyproject.toml`, `.planning/config.json`
- `joeecarter/health-import-server` → `request/metric-type.go` — independent third-party HAE receiver;
  corroborates all 7 nutrition names, `total_fat`, and `weight_body_mass`
- https://help.healthyapps.dev/en/health-auto-export/getting-started/supported-data/ — the supported dietary
  type list
- https://help.healthyapps.dev/en/health-auto-export/getting-started/unit-preferences/ — units are a
  user preference, converted on-device at export
- Prior project research, re-read and cited rather than duplicated: `.planning/research/SUMMARY.md`,
  `ARCHITECTURE.md`, `PITFALLS.md` (1–9), `FEATURES.md`, `STACK.md`

### Secondary (MEDIUM confidence)
- GitHub code search, run this session: `"weight_body_mass"` → 623 results vs `"weight_&_body_mass"` → 6
- `d3mocide/Luma` → `backend/luma/services/hae_normalizer.py` — a production HAE normalizer that aliases
  both weight spellings and documents the locale-vs-app-setting unit hazard
- https://vitalina.app/export/format-reference and `/export/nutrition` — third-party metric/unit reference
  (a *different* app; used only as corroboration for units, which the real payloads independently confirm)
- https://help.healthyapps.dev/en/health-auto-export/export-format/health-metrics — lists
  `weight_&_body_mass`; treated as a UI display name and **overruled** by the vendor's own code

### Tertiary (LOW confidence — flagged, not relied upon)
- `Slaymish/HealthAgent` → `healthAutoExport.sample.json` — hand-written fixture; correct envelope and
  correct names, but round numbers. Used only to show `dietary_energy` in `kJ` is plausible
- `jare0014/obsidian-health-connect` → `health_auto_export_samples.json` — hand-written, **wrong** envelope
  and **wrong** names (`dietary_protein`). Cited only as evidence that the `dietary_` prefix trap is real
  and that practitioners do fall into it

---

## Metadata

**Confidence breakdown:**

| Area | Level | Reason |
|---|---|---|
| Nutrition metric names (D-05 §1) | **HIGH** | Vendor's own enum + 5 real payloads + an independent implementation, all agreeing |
| Nutrition units (D-05 §2) | **HIGH** | 5 real payloads + the user's own 4.5-year export, agreeing exactly |
| Nutrition shape / pipeline reuse (D-05 §3–4) | **HIGH** | Vendor's `mapMetric` dispatch read directly; corroborated by real payloads |
| Hevy writes no nutrition (D-05 §3) | **HIGH** | Exhaustive query of the user's own 438,649-record export |
| `weight_body_mass` spelling (D-05 §5) | **HIGH** | Vendor enum + 623:6 code search + independent implementation |
| Finding A (Hevy `active_energy`) | **HIGH** | Measured directly from the user's own data; 209 days quantified |
| Findings B, C, D | **HIGH** | Measured from real payloads and the user's own export |
| Webhook `source` spelling for Hevy | **MEDIUM** | Assumption A1 — needs one device capture; third-party payloads cannot settle it |
| Existing repo patterns | **HIGH** | Every file re-read this session; all line references verified current |
| Pitfalls 1–9 (prior research) | **HIGH** | Re-read; all file/line references still resolve |

**Research date:** 2026-09-02
**Valid until:** 2026-10-02 (30 days). The vendor's metric enum is stable, but HAE ships frequently —
re-check `MetricName.ts` if planning slips past this window. The Findings, which come from the user's own
data and BRETT's own source, do not expire.
