# Phase 4: Volume & Frequency Analytics - Research

**Researched:** 2026-08-30
**Domain:** Deterministic SQL-aggregate analytics over a normalized Postgres workout schema (SQLAlchemy 2.0 async + asyncpg), consumed later by MCP tools
**Confidence:** HIGH

> **How this research was done, and why that matters.** Almost every claim below was verified by
> executing it — against the *live* `brett-db-1` Postgres 18.6 container holding the real 327-workout
> sync from Phase 3, using this repo's own pinned SQLAlchemy 2.0.52 / asyncpg 0.31.0. Where a
> statement is marked `[VERIFIED: live db]` it was observed, not recalled. Three of the findings
> (Pitfalls 1, 3 and 5) are things that would each have shipped a silently-wrong number.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Tonnage Calculation**
- **D-01:** Tonnage is `weight_kg × reps` for every exercise, dumbbell included — **no
  per-dumbbell ×2 correction factor anywhere in this phase.** `docs/hevy-api-observations.md`
  confirmed `weight_kg` is per-dumbbell, not the combined pair, which raised the question of
  whether two-handed dumbbell tonnage should double it to reflect true total load. The user
  chose raw `weight_kg × reps` instead, explicitly to keep one number that also serves as the
  input to Phase 5's estimated-1RM formula (which models one limb's load, not a doubled one).
  Because no correction is applied, the curated single-arm/unilateral exception list that would
  otherwise be needed (mirroring `app/normalization/exercise_map.py`'s title-based deltoid-split
  pattern) is **not needed** — there is nothing to except from.

**Time Windows & Week Boundary**
- **D-02:** Weekly volume groups sets into **calendar weeks starting Monday**, computed in the
  user's **local timezone** (`users.timezone`, default `Asia/Jakarta` per FOUND-03) — never UTC.
  This matches `app/core/time.py::local_week_start()`, which already implements exactly this
  (Monday-start ISO week) — the decision confirms existing Phase 1 code rather than requiring
  new design.
- **D-03:** Training frequency (and any other windowed analytics query) takes an **arbitrary
  start/end date range** as its parameter, not a fixed preset list (7/14/30/90-day). Chosen
  because Phase 5's `CMP-01` period comparison and Phase 6's MCP tools will both need arbitrary
  ranges regardless — building the flexible shape once now avoids redoing it later.

**Muscle-Group Volume Shape**
- **D-04:** Per-muscle-group weekly volume reports **three numbers**: `direct_sets` and
  `indirect_sets` as raw, unweighted counts (matches blueprint §18's literal example), plus a
  `weighted_sets` total computed via the existing `app/normalization/resolver.py::apply_weights()`
  (default 1.0 direct / 0.5 indirect, from Phase 3 — not redecided here). Both the honest raw
  split VOL-02 asks for and the single blended "how undertrained is this muscle" number are
  present; neither is dropped in favor of the other.

**Insufficient-Data & Coverage Metadata**
- **D-05:** The `insufficient_data` flag (DQ-02) trips when **fewer than 2 sessions** touch the
  metric within the requested window. One session cannot support a "per week" rate or a trend
  claim; two is the minimum for that math to mean anything. One threshold, reused across both
  volume and frequency responses.
- **D-06:** Every analytics response's coverage/uncertainty metadata block includes exactly:
  `sessions_in_window` (count), `insufficient_data` (bool, derived per D-05), and
  `earliest_data_at` (timestamp of the user's oldest synced workout) — so Claude can tell "no
  training happened in this window" apart from "your synced history doesn't reach back that
  far." An option to also echo `requested_window` (start/end) back in the metadata was
  presented and **not selected** — omit it unless a later phase needs it.

### Claude's Discretion
- Exact Pydantic/dataclass shape of the analytics module's public return types (this phase
  lives outside MCP handlers; Phase 6 builds MCP tool schemas on top of whatever this phase
  returns — CLAUDE.md's "pandas/numpy" rejection already steers toward SQL aggregates +
  dataclasses/Pydantic, not a dataframe layer).
- Module location/naming under `backend/app/` (e.g. `app/analytics/`) — no analytics package
  exists yet.
- Golden fixture workout design (success criterion 5: warm-ups, dropsets, supersets, bodyweight
  exercises) — hand-authored synthetic fixtures vs. derived from the 327 real synced workouts
  already in the database from Phase 3's live sync.
- Which `sync_state.resource` row feeds a given response's freshness metadata (DQ-01) — almost
  certainly `RESOURCE_WORKOUTS` for volume/frequency, but confirm at plan/research time whether
  a response should report the single most-stale relevant resource or a per-resource breakdown.
- Whether a `local_week_bounds()` companion to `app/core/time.py::local_day_bounds()` gets added
  to that module (extending the established pattern) or lives inside the new analytics module.

### Deferred Ideas (OUT OF SCOPE)
- **`requested_window` echo in coverage metadata** — presented as an option for D-06's metadata
  block and not selected. Not lost — reconsider if Phase 6's MCP tool consumers turn out to
  need it.
- **Per-dumbbell ×2 tonnage correction and its unilateral-exercise exception list** — considered
  in depth (D-01) and explicitly rejected in favor of raw `weight_kg × reps` everywhere. If a
  future milestone wants "true total load" reporting, the curated-title-exception-list pattern
  from `app/normalization/exercise_map.py` is the template to reuse.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| **VOL-01** | Weekly training volume (hard sets, reps, and — where the exercise modality supports it — tonnage), excluding warm-up sets from all volume figures | Pattern 1 (weekly bucket query); **Live Data Ground Truth** table settles "where the modality supports it" empirically — 5 of 9 live `exercise_type` values cannot produce `weight × reps`; Pitfall 3 (`SUM` silently skips NULL products); Pitfall 6 (`dropset` is a hard set, `failure` never occurs) |
| **VOL-02** | Weekly per-muscle-group volume, broken out by direct and indirect sets | Pattern 2 (hybrid SQL-aggregate + `effective_muscles_bulk` fan-out) — verified to produce results *identical* to a pure-SQL equivalent while honoring the override replacement rule; Pitfall 4 (pure-SQL join bypasses `exercise_muscle_overrides`) |
| **VOL-03** | Training frequency per muscle group and per exercise (sessions/week) | Pattern 3 (session-grain query); **Pitfall 5** — the single most dangerous finding: summing per-template session counts inflates per-muscle frequency by up to 4× on real data |
| **DQ-01** | Freshness metadata (when underlying data was last synced) | Pattern 5; `get_sync_state()` signature verified; recommendation for the CONTEXT discretion item (per-resource breakdown, not a single resource) |
| **DQ-02** | Coverage/uncertainty metadata (sessions in window, insufficient-data flags) | Pattern 5; D-05/D-06 field list; Open Question 1 (response-level vs row-level grain) |
</phase_requirements>

## Summary

This phase needs **zero new dependencies**. Every library required — SQLAlchemy 2.0.52, asyncpg
0.31.0, Pydantic 2.13.4, pytest 9.1.1, pytest-asyncio 1.4.0, testcontainers 4.15.0, time-machine
3.4.0 — is already pinned in `pyproject.toml` and installed in `.venv` `[VERIFIED: importlib.metadata]`.
The work is entirely composition: four new modules under `backend/app/analytics/`, one small
addition to `backend/app/core/time.py`, and three test modules.

The central architectural question — *should the direct/indirect/weighted aggregation happen in
SQL or in Python?* — has a verified answer. I built both, ran them against 17 months of real
data, and they produce **byte-identical `Decimal` results**. Since correctness is a tie, the tie
is broken by two things that are not ties: (a) the pure-SQL version joins `exercise_muscles`
directly and therefore **silently ignores `exercise_muscle_overrides`**, breaking the resolver's
documented replacement rule — it happens to agree today only because the override table has 0
rows; and (b) the hybrid version's Python half is a pure function over plain rows, which is what
CLAUDE.md's "trivially unit-testable" demand actually means. The hybrid costs ~5ms on top of a
62ms query over all history. **Aggregate at the `(week, workout_id, template_id)` grain in SQL;
fan out to muscle groups in Python via `effective_muscles_bulk()` + `apply_weights()`.**

Three findings would each have shipped a wrong number. **(1)** `SUM(weight_kg * reps)` silently
drops sets where either operand is NULL — 543 of 7,719 non-warmup sets in the live database — so
an unguarded tonnage figure under-reports without any error. **(2)** Summing per-template session
counts to get per-muscle frequency inflates it by up to **4×** (hamstrings: 8 claimed vs 2 actual
in the week of 2026-08-24), because one workout containing three hamstring exercises is one
session, not three. **(3)** `date_trunc('week', ...)` returns a *naive* `datetime.datetime`, not a
`datetime.date`, so comparing it against `local_week_start()`'s return value fails silently in a
dict key and loudly in an assertion.

**Primary recommendation:** Build `backend/app/analytics/{volume,frequency,metadata,schemas}.py`
with functions shaped `async def f(session: AsyncSession, *, user_id: uuid.UUID, ...)` — the
repo-wide convention — aggregating in SQL at the `(week, workout_id, template_id)` grain with
`FILTER (WHERE ...)` clauses for modality-aware tonnage, then fanning out to muscle groups in
pure Python through the existing resolver.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Set/rep/tonnage rollup by week | Database (Postgres aggregate) | — | Row-count reduction belongs where the rows are; 7,984 sets collapse to 1,882 groups in 62 ms `[VERIFIED: live db]`. Fetching 7,984 rows into Python to count them is the anti-pattern CLAUDE.md's "SQL aggregates" line exists to prevent |
| Local-week bucketing | Database (`date_trunc` + `timezone()`) | Python (`app/core/time.py` for filter bounds) | `date_trunc('week', ts AT TIME ZONE tz)` is Monday-start and agrees with `local_week_start()` — already asserted by `backend/tests/test_time.py::test_python_and_sql_bucketing_agree`. Filter *bounds* must be computed in Python so the column stays bare and the index stays usable (Pitfall 2) |
| Muscle-group resolution (base vs override) | Python (`app/normalization/resolver.py`) | Database (2 batched selects inside the resolver) | The replacement rule ("ANY override replaces the base set entirely") is a Python conditional, not a join. Reimplementing it as SQL forks the rule into two places that will disagree (Pitfall 4) |
| Direct/indirect weighting | Python (`apply_weights()`) | — | NORM-03 requires the weight be a query-time *parameter*. `apply_weights()` is pure, synchronous, `Decimal`-typed, and its docstring explicitly anticipates being "called inside aggregation loops" by this phase |
| Freshness metadata | Database (`sync_state` row read) | Python (staleness derivation) | `get_sync_state()` already exists and is provider-neutral |
| Coverage/uncertainty derivation | Python | — | `insufficient_data` is a threshold comparison (D-05). Encoding a business threshold in SQL makes it untestable without a container |
| Public return shape | Python (Pydantic models) | — | Phase 6 builds MCP tool schemas on top; MCP v2 auto-generates `outputSchema` from a returned `BaseModel` (CLAUDE.md), so a Pydantic return type here is free wiring later |

## Project Constraints (from CLAUDE.md)

Directives extracted from `./CLAUDE.md` that the planner must not contradict:

| # | Directive | Consequence for this phase |
|---|-----------|----------------------------|
| C-1 | **No pandas / numpy for v1 analytics.** "Pushing weekly volume and per-muscle rollups into SQL + plain Python keeps them trivially unit-testable" | The Python half of Pattern 2 must be a plain function over plain rows. No dataframe, no `Series`, no vectorized ops |
| C-2 | **SQL aggregates + `dataclasses`/Pydantic models**, using `date_trunc`, window functions, `generate_series` | Recommended stack below uses exactly these. Note: no window function is actually *needed* for this phase's five requirements — see State of the Art |
| C-3 | **`testcontainers[postgres]`, never SQLite for tests** — "`date_trunc`, `generate_series`, window frames and `AT TIME ZONE` behave differently or not at all" | Every analytics query test carries `@pytest.mark.integration` |
| C-4 | **`Numeric`, never `Float`** for weights | Verified safe under asyncpg (Pitfall 8), but the declared precision is *cosmetic* — do not rely on it |
| C-5 | **`zoneinfo` only**, no third-party tz library; `ZoneInfo(user.timezone)` before `date_trunc` | Route every conversion through `app/core/time.py`, per that module's own docstring |
| C-6 | **MCP tools read-only in v1; never expose API keys, DB credentials, or internal tokens through MCP responses or logs** | Analytics return types must contain no `sync_state.last_error`, no DSN, no raw exception text |
| C-7 | **Ruff `select = ["E","F","I","UP","B","ASYNC","S","DTZ"]`, line-length 100, mypy `disallow_untyped_defs`** | `S608` bans f-string SQL — the timezone must be a **bound parameter**. `DTZ` bans naive `datetime` construction |
| C-8 | **GSD workflow enforcement** — no direct repo edits outside a GSD command | Research writes only `.planning/`; implementation happens in `/gsd-execute-phase` |

## Standard Stack

### Core — all already installed, nothing to add

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SQLAlchemy | 2.0.52 | Typed Core `select()` construction, async execution | Already the project ORM. `func.timezone()`, `func.count().filter()`, `cast(..., Date)` and `.column_valued()` all verified working on this exact version `[VERIFIED: live db]` |
| asyncpg | 0.31.0 | Postgres driver | Returns `NUMERIC` as native `decimal.Decimal` with **no result processing** — verified by reading `AsyncpgNumeric.result_processor` at `.venv/lib/python3.13/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:325-336` and empirically (Pitfall 8) |
| Pydantic | 2.13.4 | Public return types for the analytics functions | MCP v2 auto-generates `outputSchema` + `structured_content` from a returned `BaseModel` (CLAUDE.md), so Phase 6 gets its wire contract free |
| Python `decimal` | stdlib | All summed/compared magnitudes | Repo convention since Phase 3. Python `sum()` of `Decimal` and Postgres `SUM(numeric)` produce identical values *and identical string representations* `[VERIFIED: live db — 2457313.300 both ways]` |
| Python `zoneinfo` | stdlib | Local-week bucketing | C-5. `local_day_bounds()` already handles DST-nonexistent midnights correctly (see Pitfall 9) |

### Supporting — test-side, all already installed

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest | 9.1.1 | Runner. `asyncio_mode = "auto"` — no `@pytest.mark.asyncio` decorator needed | Every test |
| pytest-asyncio | 1.4.0 | Async test + fixture support | Every async test |
| testcontainers[postgres] | 4.15.0 | Real Postgres 18-alpine, migrated by a real `alembic upgrade head` subprocess | Every query test (C-3) |
| time-machine | 3.4.0 | Freeze the clock | Only where "now" leaks in — e.g. a default window end, or staleness-age derivation. Pass an **aware** datetime (`backend/tests/test_time.py:147-155` documents the `TypeError` otherwise) |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Hybrid SQL-aggregate + Python muscle fan-out (**recommended**) | Pure SQL: join `exercise_muscles` and a `VALUES('direct',1.0),('indirect',0.5)` weights CTE | Produces identical numbers today `[VERIFIED: live db, all 16 muscle groups matched exactly]`, and is one round trip instead of three. **Rejected** because it joins the base table directly and therefore ignores `exercise_muscle_overrides` — it agrees only because that table currently has 0 rows. It also forks the resolver's replacement rule into SQL, which CONTEXT.md forbids ("this phase consumes `resolver.py`, it doesn't modify it") |
| Aggregating at `(week, workout_id, template_id)` grain (**recommended**) | Aggregating at `(week, template_id)` grain | The coarser grain is 1,882 rows vs 2,239 — a 16% saving that costs you the ability to compute per-muscle session counts at all (Pitfall 5). Not worth it |
| `func.count().filter(cond)` for modality-aware tonnage | `func.sum(case((cond, 1), else_=0))` | `FILTER (WHERE ...)` is standard SQL, renders correctly through SQLAlchemy on asyncpg `[VERIFIED: live db]`, and reads closer to the requirement. `CASE` is the portability fallback; this project is Postgres-only |
| `func.generate_series(...).column_valued("week_start")` for a gap-free week spine | Python `itertools` week enumeration between the range bounds | Python enumeration is simpler, needs no SRF, and is trivially unit-testable without a container. **Prefer Python** unless the spine must be joined inside the aggregate query. If SQL is used, `.render_derived()` or `.column_valued()` is mandatory (Pitfall 7) |
| Pydantic `BaseModel` return types | frozen `dataclass` | `dataclass` is lighter and matches `EffectiveMuscle`/`MuscleAssignment` in `normalization/`. Pydantic wins on the Phase 6 hand-off (auto `outputSchema`). Either satisfies CONTEXT.md; Pydantic is the lower-total-work choice |

**Installation:**

```bash
# Nothing to install. Verified present in .venv on 2026-08-30:
#   sqlalchemy==2.0.52  asyncpg==0.31.0  pydantic==2.13.4  pytest==9.1.1
#   pytest-asyncio==1.4.0  testcontainers==4.15.0  time-machine==3.4.0
```

**Version verification:** performed with `importlib.metadata.version()` inside the project venv on
2026-08-30 rather than `npm view` (this is a Python project). Every version matches the `==` pins in
`pyproject.toml`. `[VERIFIED: local venv]`

## Live Data Ground Truth

> **Read this before designing any calculation.** These are counts from the actual
> `brett-db-1` database holding Phase 3's real sync, queried 2026-08-30. Several contradict what
> the blueprint and even this repo's own docstrings assume.

### Volumetrics

| Table | Rows |
|---|---|
| `workouts` | 327 (2025-04-01T08:10:27Z → 2026-08-29T08:23:58Z) |
| `workout_exercises` | 2,239 |
| `workout_sets` | 7,984 |
| `exercise_templates` | 463 |
| `exercise_muscles` | 1,147 |
| `exercise_muscle_overrides` | **0** |
| Distinct templates referenced by workouts | 119 all-time; 39 in a 2-month window |
| Muscle groups per template | 1 (149 templates) up to **9** (4 templates) |

`[VERIFIED: live db]`

### `set_type` — only three values exist

| `set_type` | Count | VOL-01 treatment |
|---|---|---|
| `normal` | 6,896 | Hard set |
| `dropset` | 823 | **Hard set** — VOL-01 excludes *only* `warmup` |
| `warmup` | 265 | Excluded from every figure |
| `failure` | **0** | Declared in `workout.py:154-156` but never emitted by this account. Code must still handle it (a future workout could use it); tests must not assume it appears |

`[VERIFIED: live db]`

### `exercise_type` — the modality table that decides where tonnage is meaningful

This is the empirical answer to VOL-01's "where the exercise modality supports it". Counts are
**sets actually logged**, not templates:

| `exercise_type` | Sets | `weight_kg` | `reps` | Tonnage = `weight × reps`? | Reps meaningful? |
|---|---|---|---|---|---|
| `weight_reps` | 7,167 | always present (35 are `0`) | always present | **Yes** | Yes |
| `reps_only` | 503 | **NULL in 503/503** | always present | **No** | Yes |
| `bodyweight_weighted` | 270 | always present (13 are `0`) | always present | **Yes** (added load only, per D-01) | Yes |
| `duration` | 24 | **NULL in 24/24** | **NULL in 24/24** | **No** | **No** — `duration_seconds` only |
| `short_distance_weight` | 16 | always present | **NULL in 16/16** | **No** | **No** — `distance_meters` only |
| `bodyweight_assisted` | 4 | always present | always present | Yes (negative/assist load) | Yes |
| `distance_duration` | 0 sets (14 templates) | — | — | No | No |
| `floors_duration` | 0 sets (1 template) | — | — | No | No |
| `steps_duration` | 0 sets (1 template) | — | — | No | No |

`[VERIFIED: live db]`

**⚠️ Docstring drift.** `backend/app/db/models/exercise.py:60-63` documents the vocabulary as
`weight_reps | reps_only | bodyweight_reps | bodyweight_assisted_reps | duration | weight_duration |
distance_duration | short_distance_weight`. Three of those strings (`bodyweight_reps`,
`bodyweight_assisted_reps`, `weight_duration`) appear in **zero** rows, and three strings that
*do* appear (`bodyweight_weighted`, `bodyweight_assisted`, `floors_duration`, `steps_duration`)
are absent from the docstring. **Do not hardcode a modality allow-list from that docstring.**
`[VERIFIED: live db]`

**Design consequence:** do not branch on `exercise_type` at all. Branch on **operand presence**
(`weight_kg IS NOT NULL AND reps IS NOT NULL`). That rule reproduces the table above exactly,
survives Hevy inventing a tenth modality, and needs no join to `exercise_templates`. The
`exercise_type` string is still worth *reporting* alongside a per-exercise breakdown so Claude
can explain *why* tonnage is absent — but it must not be the gate.

### Other structural facts

- **`supersets_id` is NULL on all 2,239 `workout_exercises` rows** — this account has never logged
  a superset `[VERIFIED: live db]`. Superset grouping therefore cannot affect any live figure.
  Success criterion 5 still requires a golden fixture covering supersets; see Pitfall 10 for what
  that fixture should actually assert.
- **48 non-warmup sets have `weight_kg = 0`** (35 `weight_reps`, 13 `bodyweight_weighted`). These
  are hard sets contributing 0 tonnage. `0` is *not* NULL and must not be filtered out
  `[VERIFIED: live db]`.
- **0 orphan templates** — every `workout_exercises.exercise_template_external_id` has a matching
  `exercise_templates` row, and every one has a muscle mapping. An `INNER JOIN` would be safe
  *today*; use `LEFT JOIN` (or resolve via the resolver, which returns `[]` for unmapped) anyway,
  because D-03 of Phase 3 says an unmapped template must not block anything `[VERIFIED: live db]`.
- **No two workouts share a local calendar day, and no workout repeats the same template twice**
  — currently. Both are accidents of this user's habits, not invariants. Code must not assume
  either `[VERIFIED: live db]`.
- `sync_state` holds three independent `last_synced_at` values (workouts 05:43:18Z, body_measurements
  05:43:23Z, exercise_templates 06:08:04Z on 2026-08-30) `[VERIFIED: live db]`.

## Architecture Patterns

### System Architecture Diagram

```
                         ┌──────────────────────────────────────┐
  caller (Phase 6 MCP    │  get_weekly_volume(session, *,        │
  tool / CLI / test) ───►│    user_id, start, end)               │
                         │  get_muscle_group_volume(...)         │
                         │  get_training_frequency(...)          │
                         └───────────────┬──────────────────────┘
                                         │
             ┌───────────────────────────┼───────────────────────────┐
             ▼                           ▼                           ▼
 ┌───────────────────────┐   ┌───────────────────────┐   ┌───────────────────────┐
 │ 1. RESOLVE WINDOW     │   │ 2. AGGREGATE          │   │ 5. ATTACH METADATA    │
 │ app/core/time.py      │   │ app/analytics/        │   │ app/analytics/        │
 │                       │   │   volume.py           │   │   metadata.py         │
 │ users.timezone ──►    │   │                       │   │                       │
 │ local_range_bounds(   │──►│ ONE SQL statement:    │   │ sync_state ──► DQ-01  │
 │   start_date,         │   │ GROUP BY              │   │   freshness           │
 │   end_date, tz)       │   │  (week, workout_id,   │   │ min(start_time) ──►   │
 │ ──► half-open UTC     │   │   template_id)        │   │   earliest_data_at    │
 │     [utc_lo, utc_hi)  │   │ + FILTER (WHERE ...)  │   │ sessions < 2 ──►      │
 │                       │   │   for tonnage         │   │   insufficient_data   │
 │ index-safe: the       │   │                       │   │                       │
 │ column stays bare     │   │ ix_workouts_user_id_  │   └───────────┬───────────┘
 └───────────────────────┘   │   start_time IS USED  │               │
                             └───────────┬───────────┘               │
                                         │ rows: (week, workout_id,  │
                                         │        template_id,       │
                                         │        hard_sets, reps,   │
                                         │        tonnage_sets,      │
                                         │        tonnage_kg)        │
                                         ▼                           │
                             ┌───────────────────────┐               │
                             │ 3. RESOLVE MUSCLES    │               │
                             │ app/normalization/    │               │
                             │   resolver.py         │               │
                             │                       │               │
                             │ effective_muscles_    │               │
                             │   bulk(session, ...)  │               │
                             │  = 2 queries total    │               │
                             │  override REPLACES    │               │
                             │  base (NORM-02)       │               │
                             │         │             │               │
                             │         ▼             │               │
                             │ apply_weights()       │               │
                             │  pure, sync, Decimal  │               │
                             └───────────┬───────────┘               │
                                         │ {template_id:             │
                                         │   {muscle: Decimal}}      │
                                         ▼                           │
                             ┌───────────────────────┐               │
                             │ 4. FAN OUT (pure fn)  │               │
                             │ app/analytics/        │               │
                             │   volume.py           │               │
                             │                       │               │
                             │ for row in rows:      │               │
                             │  for muscle in map:   │               │
                             │   direct_sets   +=    │               │
                             │   indirect_sets +=    │               │
                             │   weighted_sets +=    │               │
                             │   sessions.add(       │◄── SET, never │
                             │     workout_id)       │    a counter  │
                             └───────────┬───────────┘    (Pitfall 5)│
                                         │                           │
                                         └───────────┬───────────────┘
                                                     ▼
                                       ┌───────────────────────────┐
                                       │ Pydantic return model     │
                                       │ app/analytics/schemas.py  │
                                       │  weeks[] + coverage +     │
                                       │  freshness                │
                                       └───────────────────────────┘
```

**Trace of the primary use case** ("per-muscle weekly volume for the last 8 weeks"): caller passes
a date range → step 1 converts it to a half-open UTC pair using the user's stored timezone → step 2
runs one indexed aggregate returning ~2.2k rows → step 3 resolves the ~119 distinct templates to
muscle sets in two queries → step 4 folds rows into `(week, muscle)` buckets in pure Python,
accumulating sessions into a `set` → step 5 reads `sync_state` and derives coverage → a Pydantic
model is returned.

**Measured cost of that trace over all 17 months of live data:** aggregate query 62 ms /1,882 rows,
`effective_muscles_bulk` 4.5 ms /119 templates, Python fan-out 4.7 ms /1,050 `(week, muscle)`
buckets. `[VERIFIED: live db]`

### Recommended Project Structure

```
backend/app/analytics/
├── __init__.py          # package init only — mirrors app/normalization/__init__.py
├── schemas.py           # Pydantic return models (WeeklyVolume, MuscleGroupVolume,
│                        #   TrainingFrequency, CoverageMetadata, FreshnessMetadata)
├── metadata.py          # DQ-01 + DQ-02: freshness lookup, earliest_data_at,
│                        #   insufficient_data derivation. No SQL aggregation.
├── volume.py            # VOL-01 get_weekly_volume(), VOL-02 get_muscle_group_volume()
└── frequency.py         # VOL-03 get_training_frequency()

backend/app/core/time.py # MODIFIED: add local_range_bounds(start_date, end_date, tz)

backend/tests/
├── conftest.py                     # MODIFIED: add a golden-workout builder fixture
├── test_analytics_volume.py        # VOL-01, VOL-02
├── test_analytics_frequency.py     # VOL-03
└── test_analytics_metadata.py      # DQ-01, DQ-02
```

**Why this shape.** `app/analytics/` sits at the same architectural level as `app/normalization/`
and `app/core/` — provider-neutral domain logic that imports nothing from `app.integrations` and
nothing from `app.mcp`. That isolation is what CONTEXT.md means by "lives outside MCP handlers,"
and it is worth asserting with a static test in the style of
`backend/tests/test_hevy_isolation.py` (walk `app/analytics/*.py`, assert no `app.mcp` or
`app.integrations` import).

**Splitting `volume.py` from `frequency.py`** rather than one `analytics.py`: they share the
window-resolution and metadata helpers but nothing else, and `frequency.py` needs no tonnage
logic at all. One file per requirement cluster also lets the plan parallelize.

**`local_range_bounds()` belongs in `app/core/time.py`, not in analytics.** That module's own
docstring states the rule: *"Every day/week grouping in this project routes through this module."*
D-03 asks for arbitrary start/end ranges, which is a strict generalization of `local_day_bounds()`
— so add the general helper rather than a week-only one. This resolves the CONTEXT discretion item.

### Pattern 1: Weekly volume with modality-aware tonnage (VOL-01)

**What:** One aggregate that produces hard sets, reps and tonnage per local week, with tonnage
gated on operand presence rather than on `exercise_type`.

**When to use:** VOL-01. Also the base query Pattern 2 extends.

```python
# Source: verified by execution against PostgreSQL 18.6 with SQLAlchemy 2.0.52 + asyncpg 0.31.0
import datetime as dt
import uuid

import sqlalchemy as sa
from sqlalchemy import Date, and_, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workout import Workout, WorkoutExercise, WorkoutSet

WARMUP = "warmup"  # VOL-01 excludes exactly this set_type

async def weekly_volume_rows(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    tz: str,
    utc_start: dt.datetime,
    utc_end: dt.datetime,
) -> sa.Sequence[sa.Row[...]]:
    # `func.timezone(tz, col)` renders as `timezone('Asia/Jakarta', workouts.start_time)`,
    # which is exactly `ts AT TIME ZONE tz` — and `tz` is a BOUND PARAMETER, satisfying
    # Ruff S608. Never f-string the timezone into the SQL.
    #
    # The cast to Date is NOT cosmetic: date_trunc returns a NAIVE datetime.datetime.
    # Without it, the group key will never equal local_week_start()'s datetime.date.
    week = cast(func.date_trunc("week", func.timezone(tz, Workout.start_time)), Date)

    # Modality gate by OPERAND PRESENCE, not by exercise_type. Reproduces the live
    # modality table exactly and survives Hevy adding a new type.
    has_tonnage = and_(WorkoutSet.weight_kg.is_not(None), WorkoutSet.reps.is_not(None))

    stmt = (
        select(
            week.label("week_start"),
            Workout.id.label("workout_id"),
            WorkoutExercise.exercise_template_external_id.label("template_id"),
            func.count().label("hard_sets"),
            func.sum(WorkoutSet.reps).label("total_reps"),
            # How many sets actually CONTRIBUTED to tonnage. Without this the caller
            # cannot tell "0 kg" from "we couldn't compute it" (Pitfall 3).
            func.count().filter(has_tonnage).label("tonnage_sets"),
            func.sum(WorkoutSet.weight_kg * WorkoutSet.reps)
            .filter(has_tonnage)
            .label("tonnage_kg"),
        )
        .select_from(WorkoutSet)
        .join(WorkoutExercise, WorkoutExercise.id == WorkoutSet.workout_exercise_id)
        .join(Workout, Workout.id == WorkoutExercise.workout_id)
        .where(
            Workout.user_id == user_id,
            # Bare column on the left of both comparisons => the composite index
            # ix_workouts_user_id_start_time is used (Bitmap Index Scan, verified).
            Workout.start_time >= utc_start,
            Workout.start_time < utc_end,
            WorkoutSet.set_type != WARMUP,
        )
        .group_by(week, Workout.id, WorkoutExercise.exercise_template_external_id)
        .order_by(week)
    )
    return (await session.execute(stmt)).all()
```

Rendered SQL (verified):

```sql
SELECT CAST(date_trunc('week', timezone('Asia/Jakarta', workouts.start_time)) AS DATE) AS week_start,
       workouts.id AS workout_id,
       workout_exercises.exercise_template_external_id AS template_id,
       count(*) AS hard_sets,
       sum(workout_sets.reps) AS total_reps,
       count(*) FILTER (WHERE workout_sets.weight_kg IS NOT NULL AND workout_sets.reps IS NOT NULL) AS tonnage_sets,
       sum(workout_sets.weight_kg * workout_sets.reps)
         FILTER (WHERE workout_sets.weight_kg IS NOT NULL AND workout_sets.reps IS NOT NULL) AS tonnage_kg
FROM workout_sets
JOIN workout_exercises ON workout_exercises.id = workout_sets.workout_exercise_id
JOIN workouts ON workouts.id = workout_exercises.workout_id
WHERE workouts.user_id = $1 AND workouts.start_time >= $2 AND workouts.start_time < $3
  AND workout_sets.set_type != 'warmup'
GROUP BY 1, 2, 3 ORDER BY 1
```

Result types observed: `week_start` → `datetime.date`, `hard_sets`/`total_reps`/`tonnage_sets` →
`int`, `tonnage_kg` → `decimal.Decimal`. `[VERIFIED: live db]`

### Pattern 2: Per-muscle-group volume — hybrid fan-out (VOL-02)

**What:** Take Pattern 1's rows, resolve their templates through the *existing* resolver, and fold
into `(week, muscle_group)` buckets in pure Python.

**When to use:** VOL-02, and the muscle half of VOL-03.

```python
# Source: verified end-to-end against the live database; output matched a pure-SQL
# equivalent EXACTLY for all 16 muscle groups in the week of 2026-08-24.
from collections import defaultdict
from decimal import Decimal

from app.normalization.muscles import CanonicalMuscleGroup, MuscleRole
from app.normalization.resolver import apply_weights, effective_muscles_bulk


async def fold_by_muscle(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    rows,                                   # Pattern 1's rows
    weights: Mapping[MuscleRole, Decimal] | None = None,   # NORM-03: query-time
):
    template_ids = sorted({r.template_id for r in rows})
    # TWO queries total for every template in the window, not two per template.
    resolved = await effective_muscles_bulk(
        session, user_id=user_id, template_external_ids=template_ids
    )

    buckets: dict[tuple[dt.date, CanonicalMuscleGroup], dict] = defaultdict(
        lambda: {
            "direct_sets": 0,
            "indirect_sets": 0,
            "weighted_sets": Decimal(0),
            # A SET, not a counter. One workout with three chest exercises is ONE
            # chest session. Incrementing here inflates frequency up to 4x on real
            # data (Pitfall 5).
            "session_ids": set(),
        }
    )

    for row in rows:
        muscles = resolved.get(row.template_id, ())   # unmapped => contributes nothing (D-03)
        weight_by_muscle = apply_weights(muscles, weights)
        for muscle in muscles:
            b = buckets[(row.week_start, muscle.muscle_group)]
            if muscle.role is MuscleRole.DIRECT:
                b["direct_sets"] += row.hard_sets
            else:
                b["indirect_sets"] += row.hard_sets
            # Decimal * int stays exact. Never float.
            b["weighted_sets"] += weight_by_muscle[muscle.muscle_group] * row.hard_sets
            b["session_ids"].add(row.workout_id)

    return buckets
```

Verified output for the week of 2026-08-24 (hybrid, left) against the pure-SQL cross-check
(right) — identical to the last digit:

| muscle | direct | indirect | weighted (hybrid) | weighted (pure SQL) |
|---|---|---|---|---|
| hamstrings | 12 | 12 | `Decimal('18.0')` | `Decimal('18.0')` |
| biceps | 8 | 13 | `Decimal('14.5')` | `Decimal('14.5')` |
| upper_back | 6 | 13 | `Decimal('12.5')` | `Decimal('12.5')` |
| quads | 12 | 0 | `Decimal('12.0')` | `Decimal('12.0')` |

…and 12 more, all matching. `[VERIFIED: live db]`

### Pattern 3: Training frequency (VOL-03)

**What:** `sessions_per_week` for the whole user, per muscle group, and per exercise, over an
arbitrary range (D-03).

**Key insight:** frequency is a `COUNT(DISTINCT workout_id)` divided by the window length in
weeks. Pattern 2's `session_ids` set already carries the numerator for the muscle variant; the
per-exercise variant is the same fold keyed on `template_id` instead of `muscle_group`; the
overall variant is `COUNT(DISTINCT workouts.id)` in SQL.

```python
# Window length as an exact Decimal, so 10 days over 2 weeks is 5.0 and not 4.999...
days = (end_date - start_date).days + 1          # inclusive local-day span
weeks = Decimal(days) / Decimal(7)
sessions_per_week = (Decimal(len(session_ids)) / weeks).quantize(Decimal("0.01"))
```

**Do not** let raw division reach the caller: Postgres returned
`Decimal('3.1612903225806452')` for an unquantized `sessions_per_week` `[VERIFIED: live db]`.
Quantize at the boundary — blueprint §23's own example is `2.0x/week`, two significant figures.

**Anti-pattern to avoid:** `COUNT(DISTINCT ...)` *inside* the `(week, workout_id, template_id)`
grouped query is a no-op (each group already has exactly one workout). The distinct-ness must
happen after the muscle fan-out, in Python.

### Pattern 4: Index-safe window filtering

**What:** convert a local date range to a half-open UTC pair in Python, then compare the bare
column against those constants.

```python
# Add to backend/app/core/time.py, directly beside local_day_bounds().
def local_range_bounds(
    start_day: dt.date, end_day: dt.date, tz: str
) -> tuple[dt.datetime, dt.datetime]:
    """Half-open ``[start, end)`` UTC range covering an inclusive local date range.

    D-03: analytics windows are arbitrary start/end dates, so this generalizes
    ``local_day_bounds``. Same reason for existing: it compares the raw timestamp
    column against two constants, keeping ``ix_workouts_user_id_start_time`` usable.
    Wrapping the column in ``AT TIME ZONE`` instead forces a sequential scan --
    measured on the live database as Seq Scan / 299 rows removed by filter, versus
    a Bitmap Index Scan for this form.
    """
    if end_day < start_day:
        raise ValueError("end_day precedes start_day")
    start_utc, _ = local_day_bounds(start_day, tz)
    _, end_utc = local_day_bounds(end_day, tz)
    return start_utc, end_utc
```

Verified plans `[VERIFIED: live db]`:

```
-- bare column vs constants: INDEX USED
Bitmap Index Scan on ix_workouts_user_id_start_time
  Index Cond: ((user_id = ...) AND (start_time >= ...) AND (start_time < ...))

-- AT TIME ZONE applied to the column: INDEX BYPASSED
Seq Scan on workouts w
  Filter: (((start_time AT TIME ZONE 'Asia/Jakarta'))::date >= '2026-07-01'::date ...)
  Rows Removed by Filter: 299
```

### Pattern 5: Freshness + coverage metadata (DQ-01, DQ-02)

```python
# Source: signatures read from backend/app/db/repositories/sync_state.py
from app.db.repositories.sync_state import (
    PROVIDER_HEVY, RESOURCE_EXERCISE_TEMPLATES, RESOURCE_WORKOUTS, get_sync_state,
)

INSUFFICIENT_DATA_SESSION_THRESHOLD = 2   # D-05, one constant reused everywhere

async def build_freshness(session, *, user_id, resources: Sequence[str]):
    """DQ-01. Returns {resource: last_synced_at | None} plus the oldest of them."""
    out: dict[str, dt.datetime | None] = {}
    for resource in resources:
        state = await get_sync_state(
            session, user_id=user_id, provider=PROVIDER_HEVY, resource=resource
        )
        # NEVER surface state.last_error / state.status detail (C-6, MCP-06).
        out[resource] = state.last_synced_at if state else None
    return out
```

**Recommendation for the CONTEXT discretion item ("which `sync_state.resource` feeds freshness").**
Report a **per-resource breakdown, not one resource**, because the answer differs by endpoint:

| Analytics function | Resources it actually depends on |
|---|---|
| `get_weekly_volume` (VOL-01) | `workouts` only |
| `get_muscle_group_volume` (VOL-02) | `workouts` **and** `exercise_templates` — a stale template sync means a stale muscle mapping, which silently changes every per-muscle number |
| `get_training_frequency` per exercise (VOL-03) | `workouts` only |
| `get_training_frequency` per muscle group (VOL-03) | `workouts` **and** `exercise_templates` |

A single collapsed "oldest of the relevant resources" value is a lossy projection of this and can
be derived by Phase 6 in one line; the reverse is impossible. Live data confirms the two do drift
— `workouts` last synced 05:43:18Z and `exercise_templates` 06:08:04Z on 2026-08-30, a 25-minute
gap `[VERIFIED: live db]`.

### Anti-Patterns to Avoid

- **Joining `exercise_muscles` directly in the aggregate query.** It bypasses
  `exercise_muscle_overrides` and re-implements the resolver's replacement rule in SQL. It looks
  correct today only because the override table is empty (Pitfall 4).
- **Branching on `exercise_type` to decide tonnage.** The repo's own docstring lists three type
  strings that do not exist and omits four that do (see Live Data Ground Truth). Branch on
  operand presence.
- **Coercing `set_type` to an `is_warmup` boolean.** `workout.py:154-156` deliberately stores the
  string verbatim so Phase 5's PR detection can see `dropset`/`failure`. Filter with
  `set_type != 'warmup'`, do not derive a boolean.
- **Returning bare `float`.** Every summed/compared magnitude is `Decimal` (C-4). A `float` here
  makes two arithmetically identical weekly totals compare unequal.
- **Fetching sets into Python to count them.** 7,984 rows to produce ~1,050 buckets. SQL does the
  reduction; Python does the muscle fan-out and the business thresholds — that split is the whole
  design.
- **Accepting a raw timezone string into a query without `validate_timezone()`.** The tz comes
  from `users.timezone`, which carries no DB CHECK constraint; `core/time.py:43-54` exists
  precisely to reject a bad value at the boundary instead of inside an aggregate.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Resolving a template's muscle groups | A join to `exercise_muscles`, or a `COALESCE`/`FULL OUTER JOIN` between base and override | `app.normalization.resolver.effective_muscles_bulk()` | The rule is *replacement*, not merge — "if ANY override row exists, the override set REPLACES the base set entirely" (`resolver.py:1-18`). A join expresses merge. It also already batches to exactly 2 queries and raises loudly on out-of-taxonomy values |
| Direct/indirect weighting | A `VALUES('direct',1.0),('indirect',0.5)` CTE, or a `CASE WHEN role='direct' THEN 1.0 ELSE 0.5 END` | `app.normalization.resolver.apply_weights()` | NORM-03 requires the weights be a query-time *parameter*, not a literal. `apply_weights()` is pure, sync, `Decimal`-typed, and its docstring names this phase as its caller |
| Local-week / local-day boundaries | `datetime.timedelta(days=ts.weekday())` inline, or a bespoke week helper in the analytics module | `app.core.time.local_week_start()`, `local_day_bounds()`, and a new `local_range_bounds()` in the same module | That module's docstring makes it the single route for every day/week grouping. It also already handles the DST-nonexistent-midnight case correctly (Pitfall 9) and rejects naive datetimes with a guard |
| Freshness lookup | A direct `select(SyncState)` in analytics | `app.db.repositories.sync_state.get_sync_state()` + the `RESOURCE_*` constants | Provider-neutral, never commits, and the constants stop a typo'd resource string from returning `None` forever |
| Decimal summation | `float` accumulation with a rounding pass, or `math.fsum` | Postgres `SUM(numeric)` or Python `sum(..., Decimal(0))` | Verified identical, to the same string representation, across 7,176 real sets |
| Gap-free week series | A hand-rolled "fill in missing weeks" loop with date arithmetic bugs | Either `generate_series` with `.column_valued()` / `.render_derived()`, or a simple Python `while d <= end: d += timedelta(weeks=1)` between the already-computed bounds | Both are fine; the Python form needs no container to unit-test. What is *not* fine is inferring the spine from the returned rows — that silently drops zero-training weeks, which are the most diagnostically interesting ones |

**Key insight:** every hand-roll candidate in this phase is a piece of Phase 3 that already exists
and is already tested. This phase's job is composition, and its main correctness risk is
re-deriving something that has a subtler rule than it looks like — the override *replacement*
semantics above all.

## Common Pitfalls

### Pitfall 1: `date_trunc` returns a naive `datetime`, not a `date`

**What goes wrong:** `date_trunc('week', ts AT TIME ZONE tz)` comes back as
`datetime.datetime(2026, 8, 24, 0, 0)` with `tzinfo=None`. `local_week_start()` returns
`datetime.date(2026, 8, 24)`. These are not equal, do not hash alike, and will never match as a
dict key.

**Why it happens:** `AT TIME ZONE` on a `timestamptz` yields `timestamp without time zone`;
`date_trunc` preserves that type.

**How to avoid:** always `cast(..., Date)` (SQLAlchemy) or `::date` (raw SQL) on the week
expression, in both the `SELECT` list and the `GROUP BY`. Verified: with the cast the driver
returns `datetime.date` `[VERIFIED: live db]`.

**Warning signs:** a merge of SQL results with Python-computed week keys produces two entries per
week; or a test comparing a returned week to `local_week_start(...)` fails with two values that
*print* the same.

### Pitfall 2: `AT TIME ZONE` in the `WHERE` clause destroys the index

**What goes wrong:** filtering with `(start_time AT TIME ZONE 'Asia/Jakarta')::date >= :d` forces a
sequential scan of `workouts`, defeating `ix_workouts_user_id_start_time` — the index
`workout.py:88-89` was explicitly created for this phase.

**Why it happens:** wrapping a column in a function makes the predicate non-sargable; Postgres has
no expression index on that transform.

**How to avoid:** Pattern 4. Compute half-open UTC bounds in Python; leave the column bare in the
`WHERE`. Use the timezone expression only in the `SELECT`/`GROUP BY`, where it costs nothing.

**Warning signs:** `EXPLAIN` shows `Seq Scan on workouts` with `Rows Removed by Filter`.
`[VERIFIED: live db — 299 rows removed on a 327-row table]`

### Pitfall 3: `SUM(weight_kg * reps)` silently under-reports tonnage

**What goes wrong:** if either operand is NULL the product is NULL, and SQL `SUM` skips NULLs
without complaint. On the live database, **543 of 7,719 non-warmup sets (7%)** produce a NULL
product — every `reps_only`, `duration` and `short_distance_weight` set. The returned tonnage is a
real number computed over a silently smaller population.

**Why it happens:** three-valued logic plus aggregate NULL-skipping. There is no error and no
warning.

**How to avoid:** emit `tonnage_sets` (a `COUNT(*) FILTER (WHERE weight_kg IS NOT NULL AND reps IS
NOT NULL)`) beside every tonnage figure, and have the return model report tonnage as `None` — not
`0` — when `tonnage_sets == 0`. VOL-01's "where the exercise modality supports it" is exactly this
distinction. Blueprint §17's example output already omits the volume-load line for Back and Side
delts, which is the same idea.

**Warning signs:** a week where `hard_sets` is 86 but `tonnage_sets` is 83 — real, observed in the
week of 2026-06-29 `[VERIFIED: live db]`.

### Pitfall 4: A pure-SQL muscle join bypasses `exercise_muscle_overrides`

**What goes wrong:** `JOIN exercise_muscles em ON em.exercise_template_external_id = ...` returns
the *base* mapping. If the user ever corrects a mapping (NORM-02), per-muscle volume keeps
reporting the uncorrected numbers with no error.

**Why it happens:** it produces provably correct output *right now* — I verified all 16 muscle
groups match the resolver-based result exactly — because `exercise_muscle_overrides` has **0 rows**
`[VERIFIED: live db]`. A test written today passes. It breaks the first time someone uses the
override feature Phase 3 shipped.

**How to avoid:** always route through `effective_muscles_bulk()`. Guard it with a test that
inserts an override, flushes, and asserts the per-muscle result changes — that test is the only
thing standing between this phase and a latent wrong answer.

**Warning signs:** any `exercise_muscles` table name appearing in an `app/analytics/` module.

### Pitfall 5: Per-muscle session counts do not sum — they must be de-duplicated

**What goes wrong:** if you aggregate at `(week, template_id)` and then add up session counts per
muscle, a workout containing three hamstring exercises counts as three hamstring sessions.

**Measured impact on real data**, week of 2026-08-24 `[VERIFIED: live db]`:

| muscle | correct (DISTINCT workouts) | naive sum | inflation |
|---|---|---|---|
| hamstrings | 2 | 8 | **4.0×** |
| biceps | 2 | 7 | 3.5× |
| glutes | 2 | 6 | 3.0× |
| forearms | 2 | 6 | 3.0× |
| triceps | 2 | 5 | 2.5× |
| upper_back | 4 | 7 | 1.75× |

14 of 16 muscle groups were inflated. This turns VOL-03 — "sessions/week" — into fiction, and it
is the failure most likely to survive review because the numbers still look plausible.

**Why it happens:** the `(week, template)` grain has already discarded workout identity.

**How to avoid:** group at `(week, workout_id, template_id)` and accumulate `workout_id` into a
Python `set()`. The cost is 2,239 rows instead of 1,882 — 16% more — and 50 ms instead of 62 ms
(the finer grain was actually *faster* in measurement) `[VERIFIED: live db]`.

**Warning signs:** any `sum(r.sessions for r in rows)` in the fan-out.

### Pitfall 6: `dropset` is a hard set; `failure` is real but absent

**What goes wrong:** filtering `set_type == 'normal'` instead of `set_type != 'warmup'` discards
**823 dropset sets** — 10% of all sets and 12% of all hard sets `[VERIFIED: live db]`.

**Why it happens:** "hard sets" reads like "normal sets". VOL-01 says the opposite: exclude
warm-ups, count the rest.

**How to avoid:** express the filter as exclusion (`!= 'warmup'`), never as inclusion of an
allow-list. That also makes `failure` — declared in `workout.py:154-156`, present in **0** live
rows — count correctly the day it first appears, with no code change.

**Warning signs:** a hard-set total that is ~12% below a hand count.

### Pitfall 7: `func.generate_series(...).table_valued("x")` fails on Postgres without `.render_derived()`

**What goes wrong:**

```python
gs = func.generate_series(a, b, text("interval '1 week'")).table_valued("week_start")
select(gs.c.week_start)
# asyncpg.exceptions.UndefinedColumnError: column anon_1.week_start does not exist
```

SQLAlchemy renders `FROM generate_series(...) AS anon_1` — no column alias list — then references
`anon_1.week_start`. `[VERIFIED: live db]`

**How to avoid:** either

```python
func.generate_series(a, b, text("interval '1 week'")).table_valued("week_start").render_derived()
#   -> FROM generate_series(...) AS anon_1(week_start)          ✓ works
func.generate_series(a, b, text("interval '1 week'")).column_valued("week_start")
#   -> FROM generate_series(...) AS week_start                  ✓ works, simpler for 1 column
```

Both verified. SQLAlchemy's own docs state `render_derived` "is required by backends like
PostgreSQL" `[CITED: docs.sqlalchemy.org/en/20/core/functions.html]`.

**Simpler alternative:** for a week spine, enumerate in Python between the bounds. No SRF, no
container needed to test it.

### Pitfall 8: `Numeric(7, 3)` precision on an aggregate is cosmetic, not enforced

**What goes wrong (or rather, what doesn't):** `func.sum(WorkoutSet.weight_kg * WorkoutSet.reps)`
gets the SQLAlchemy result type `NUMERIC(7, 3)` inferred from the left operand — a type whose
maximum value is `9999.999`. The actual result was `Decimal('2534281.800')`, 10 significant digits,
returned intact `[VERIFIED: live db]`.

**Why it's safe here:** `AsyncpgNumeric.result_processor` returns `None` (no processing) for
Postgres `NUMERIC` when `asdecimal=True` — verified by reading
`.venv/lib/python3.13/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:325-336` and
confirmed empirically: a `1234567890.123456789` literal typed as `Numeric(7,3)` came back with all
19 digits.

**Why it still matters:** the safety comes from the *driver*, not the type declaration. The same
code path has a `_FLOAT_TYPES` branch that applies `_effective_decimal_return_scale` — i.e. it
*would* quantize to 3 dp — if the underlying column were a float type. Two rules follow: (a) never
change `weight_kg` to `Float`; (b) if a computed aggregate needs a documented precision, pass it
explicitly (`func.sum(expr, type_=Numeric(18, 3))`), which was verified to produce an identical
value while making the intent legible.

### Pitfall 9: Local-week bucket boundaries versus the requested window

**What goes wrong:** asking for a window starting 2026-07-01 produces a first bucket of
2026-06-29 — the Monday *before* the window `[VERIFIED: live db]`. That bucket contains only the
part of the week inside the window, so it is a **partial week** whose totals are not comparable to
a full week's.

**How to avoid:** either snap the requested range outward to whole local weeks before querying, or
return each bucket with enough information for the caller to detect partiality. Given D-03's
arbitrary ranges and D-06's fixed three-field metadata block, the cleanest resolution is to snap
weekly-volume windows to `local_week_start(start)` … `local_week_start(end) + 6 days`, and say so
in the docstring. Frequency (D-03) keeps the raw range, since it divides by the true window length.

**Related, verified fine:** `local_day_bounds()` handles timezones whose local midnight does not
exist on a DST transition day — `America/Santiago` 2026-09-06 yields a contiguous 23-hour
`[04:00Z, 03:00Z+1d)` range with no gap or overlap; `Asia/Beirut` 2026-03-29 likewise
`[VERIFIED: local execution]`. Asia/Jakarta has no DST at all, so this is future-proofing, not a
current bug.

### Pitfall 10: Supersets do not exist in the data, and do not affect volume anyway

**What goes wrong:** success criterion 5 names supersets, which invites building superset-grouping
logic. But `supersets_id` is NULL on all 2,239 live `workout_exercises` rows, and more
fundamentally, a superset is a *scheduling* relationship between exercises — it changes rest, not
set counts, reps or load.

**How to avoid:** the superset golden fixture's job is to prove a **negative**: that two exercises
sharing a `supersets_id` produce exactly the same hard-set, rep, tonnage and per-muscle numbers as
the same two exercises with `supersets_id = NULL`. That is a real, valuable regression test
against someone later "fixing" superset handling by collapsing them into one set group. Write the
assertion as an equality between two fixtures, not as a magic expected number.

### Pitfall 11: Per-muscle set totals legitimately exceed total sets

**What goes wrong:** one template maps to up to **9** muscle groups `[VERIFIED: live db]`, so a
single set contributes to 9 muscle buckets. Summing `direct_sets + indirect_sets` across muscle
groups yields a number several times larger than the week's actual hard-set count, and a reviewer
will read that as a bug.

**How to avoid:** never present a cross-muscle total. Name the fields so the grain is unambiguous
(`sets_reaching_this_muscle`, or document `direct_sets` as per-muscle in the model docstring), and
add a test asserting the *inequality* deliberately, so the property is recorded as intended rather
than discovered as a defect.

### Pitfall 12: `weight_kg = 0` is a hard set, not a missing value

**What goes wrong:** filtering `weight_kg > 0` to "clean" the tonnage input drops 48 real
non-warmup sets — 35 `weight_reps` and 13 `bodyweight_weighted` (the latter meaning "bodyweight
only, no added load") `[VERIFIED: live db]`.

**How to avoid:** the tonnage gate is `IS NOT NULL`, never `> 0`. A zero-weight set contributes 0
kg of tonnage *and* counts toward `tonnage_sets`, because the tonnage figure for it is known and
happens to be zero.

## Code Examples

### Golden-fixture builder (recommended test pattern)

```python
# Belongs in backend/tests/conftest.py — the repo rule is "shared FIXTURES belong in
# conftest.py; shared CONSTANTS get duplicated with a comment"
# (03-PATTERNS.md, from backend/tests/test_mcp_auth.py:76-82).
#
# The critical property: this NEVER COMMITS. It flushes, the analytics function under
# test reads through the SAME session and therefore sees the flushed rows, and the
# test's finally-block rollback leaves the shared session-scoped container untouched.
# This is strictly stronger than a compensating DELETE -- it survives an assertion
# failure mid-test (backend/tests/test_time.py:20-24 documents the rule).
#
# It also sidesteps test_migrations.py:45's `count(*) == 1` assertion on users, since
# an uncommitted fixture row is invisible to that test's separate connection.

@pytest_asyncio.fixture
async def golden_workout(session: AsyncSession):
    """Insert one synthetic workout with a known exact answer. Rolls back."""

    async def _build(
        *,
        start_time: dt.datetime,          # aware UTC; DTZ forbids naive
        exercises: Sequence[tuple[str, int | None, list[tuple[str, Decimal | None, int | None]]]],
    ) -> uuid.UUID:
        ...  # explicit Core inserts, mirroring app/integrations/hevy/workouts.py
        await session.flush()
        return workout_id

    try:
        yield _build
    finally:
        await session.rollback()
```

**Fixture coverage required by success criterion 5**, each with a hand-computed exact `Decimal`:

| Fixture | Contents | Asserts |
|---|---|---|
| `warmup_excluded` | 2 `warmup` + 3 `normal` sets, all `weight_reps` | hard_sets == 3; tonnage counts only the 3 |
| `dropset_counted` | 3 `normal` + 2 `dropset` | hard_sets == 5 (Pitfall 6) |
| `bodyweight_reps_only` | `reps_only` template, `weight_kg` NULL | reps counted; `tonnage_kg is None`, `tonnage_sets == 0` (Pitfall 3) |
| `bodyweight_zero_load` | `bodyweight_weighted`, `weight_kg = Decimal("0.000")` | counts as a tonnage set contributing `Decimal("0.000")` (Pitfall 12) |
| `duration_only` | `duration` template, weight and reps both NULL | hard_sets == N; `total_reps is None`; `tonnage_kg is None` |
| `superset_neutral` | Two exercises with a shared `supersets_id` **and** an identical pair without one | the two results are equal (Pitfall 10) |
| `multi_exercise_one_muscle` | One workout, 3 exercises all hitting hamstrings | per-muscle `sessions == 1`, not 3 (Pitfall 5) |
| `override_changes_answer` | Base mapping + an `exercise_muscle_overrides` row that removes a muscle | per-muscle result changes (Pitfall 4) |
| `week_boundary` | Workout at `2026-08-23T17:00:00Z` (= Jakarta Mon 2026-08-24 00:00) | lands in the 2026-08-24 bucket, not 2026-08-17 |
| `two_timezones` | Same workout, `users.timezone` flipped to `America/New_York` | bucket changes — proves tz is read, not hardcoded (mirrors `test_time.py::test_timezone_is_configurable`) |

### Function signature convention (repo-wide, non-negotiable)

```python
# Every session-taking function in backend/app/ uses this exact shape:
#   positional session, keyword-only everything else.
# Verified across resolver.py, sync_state.py, workouts.py, templates.py, body.py, events.py.
async def get_weekly_volume(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    start_day: dt.date,
    end_day: dt.date,
    weights: Mapping[MuscleRole, Decimal] | None = None,
) -> WeeklyVolumeResult: ...
```

**Taking `AsyncSession` and not `async_sessionmaker` is load-bearing**, for two reasons: it matches
every existing repository/service in the codebase, and it is what makes the flush-and-rollback
golden-fixture pattern above possible (a function that opens its own session would run in a
different transaction and see none of the fixture rows).

### Structured logging

```python
# backend/app/main.py:52, health.py, ping.py — module-level, always this name,
# snake_case event names (03-PATTERNS.md picked underscores over dots).
import structlog
log = structlog.get_logger()
```

Analytics is a read path with no credentials in scope; log sparingly. If a query is timed, log
`analytics_weekly_volume_completed` with `week_count` / `duration_ms` — never row contents (a
workout title is health data, per `test_hevy_end_to_end.py`'s `HEALTH_DATA_IN_FIXTURES` guard).

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `sum(CASE WHEN cond THEN 1 ELSE 0 END)` for conditional aggregates | `COUNT(*) FILTER (WHERE cond)` | SQL:2003; PostgreSQL 9.4 | Reads as the requirement; verified to render correctly through SQLAlchemy 2.0.52 on asyncpg |
| `Query`-style ORM (`session.query(...)`) | `select()` + `session.execute()` (2.0 style) | SQLAlchemy 2.0 (2023) | The repo already uses 2.0 style exclusively. Any 1.x-style example found online is wrong here |
| `column.op('AT TIME ZONE')(tz)` string operator | `func.timezone(tz, column)` | Long-standing; the function form is the documented equivalent | Renders `timezone('Asia/Jakarta', workouts.start_time)`; keeps `tz` a bound parameter, satisfying Ruff `S608` |
| `table_valued("x")` alone for SRFs | `.render_derived()` or `.column_valued("x")` | SQLAlchemy 1.4.0b2 introduced both | Without it, PostgreSQL raises `UndefinedColumnError` (Pitfall 7) |
| `freezegun` | `time-machine` | Already the project pin | Faster; requires an **aware** datetime argument |

**Deprecated/outdated in the surrounding docs, worth flagging to the planner:**

- **`backend/app/db/models/exercise.py:60-63`'s `exercise_type` vocabulary is stale** — three listed
  values do not occur and four occurring values are unlisted. A one-line docstring correction is a
  reasonable in-phase fix (it is the phase's first consumer of that column) but it is a `Phase 3
  artifact` edit, so the planner should make it an explicit task rather than an incidental change.
- **Window functions are in CLAUDE.md's toolkit but are not needed for this phase.** VOL-01/02/03
  are all plain `GROUP BY` aggregates. `generate_series` is optional (Python enumeration works).
  Reaching for `LAG`/`OVER` here would be complexity without a requirement — those belong in Phase
  5's trend and plateau detection.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | A `duration`-modality set (no reps, no weight) should still count as a **hard set** in VOL-01's set count | Live Data Ground Truth; Pitfall 3 | 24 live sets. If it should instead be excluded from set counts entirely (it is arguably not resistance volume), weekly hard-set totals are 24 too high across the history. Cheap to flip; needs a user call |
| A2 | `bodyweight_weighted` tonnage is the **added load only** (`weight_kg × reps`), not bodyweight + added load | Live Data Ground Truth | Follows directly from D-01's "raw `weight_kg × reps` for every exercise", and body weight is not available per-session anyway until BODY-01. Stated here because it makes 13 zero-load sets report 0 kg tonnage, which reads oddly |
| A3 | Weekly-volume windows should be **snapped outward to whole local weeks**, while frequency windows keep the raw range | Pitfall 9 | If not snapped, the first and last buckets are partial weeks whose totals invite false "volume dropped" conclusions. D-03 locks *arbitrary ranges* as the parameter shape but says nothing about bucket snapping |
| A4 | Per-muscle volume should report the **per-resource freshness breakdown** rather than a single `workouts` timestamp | Pattern 5 | This is CONTEXT.md's explicit open discretion item. If Phase 6 wants one scalar, the breakdown collapses trivially; the reverse does not |
| A5 | Coverage metadata is **response-level** (per D-06's exact three fields), with a per-row `sessions` count carried alongside for row-level confidence | Open Question 1 | D-05's "sessions that touch the metric" reads per-row for per-muscle results, but D-06's block is described as per-response. Ambiguous as written |
| A6 | `insufficient_data` counts **sessions**, not weeks — i.e. `< 2` distinct workouts in the window | D-05 restatement | D-05 says "fewer than 2 sessions touch the metric," which is unambiguous. Logged only because "2 sessions" and "2 weeks of data" are easy to conflate during implementation |

## Open Questions

1. **Is DQ-02's coverage metadata per-response or per-row?**
   - What we know: D-06 fixes exactly three fields (`sessions_in_window`, `insufficient_data`,
     `earliest_data_at`). D-05 says the flag trips when fewer than 2 sessions touch **the metric**.
   - What's unclear: for `get_muscle_group_volume` there are ~16 metrics per week. A single
     response-level `insufficient_data` cannot express "you have plenty of chest data but only one
     rear-delt session."
   - Recommendation: implement D-06's block verbatim at response level (it is a locked decision),
     **and** carry a plain `sessions: int` on each per-muscle row so Phase 6 can derive row-level
     confidence with the same threshold constant. This adds a field without contradicting D-06,
     which specifies the *metadata block*, not the row shape. Flag to the user at plan review.

2. **Should the `duration` modality contribute to the hard-set count?** (see A1)
   - What we know: 24 live sets, all `normal`, all with NULL reps and NULL weight.
   - What's unclear: whether a 60-second plank is "one hard set" for volume purposes.
   - Recommendation: count it (a set is a set) but make the modality visible in the per-exercise
     breakdown so Claude can discount it. Make this a one-line, one-constant decision so flipping
     it later is trivial.

3. **Does the `exercise_type` docstring correction belong in this phase?**
   - What we know: `exercise.py:60-63` lists three non-existent values and omits four real ones.
   - What's unclear: whether editing a Phase 3 file inside Phase 4 violates CONTEXT.md's "no change
     to the muscle-mapping or weighting engine" boundary (it does not — that boundary names
     `resolver.py`/`exercise_map.py`, not the model docstring).
   - Recommendation: fix it as an explicit, separately-listed plan task. It costs one line and it
     is the exact document a future implementer will trust.

4. **Where does the `weights` parameter come from at the MCP boundary?**
   - What we know: NORM-03 and D-04 require query-time configurability;
     `apply_weights(muscles, weights=None)` already accepts it.
   - What's unclear: nothing this phase must resolve — the parameter simply has to exist on the
     public signature.
   - Recommendation: expose `weights: Mapping[MuscleRole, Decimal] | None = None` and default to
     `DEFAULT_ROLE_WEIGHTS`. Phase 6 decides whether to surface it as a tool argument.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Docker daemon | `testcontainers` integration tests | ✓ | Server 29.4.2 | — |
| PostgreSQL (test) | Every analytics query test | ✓ | `postgres:18-alpine` pulled and running | — |
| PostgreSQL (dev, real data) | Manual verification against 327 real workouts | ✓ | 18.6, `brett-db-1` on `localhost:5432` | — |
| Python | Runtime | ✓ | 3.13 (`.python-version`) | — |
| SQLAlchemy / asyncpg / Pydantic | Analytics implementation | ✓ | 2.0.52 / 0.31.0 / 2.13.4 | — |
| pytest / pytest-asyncio / testcontainers / time-machine | Tests | ✓ | 9.1.1 / 1.4.0 / 4.15.0 / 3.4.0 | — |
| Alembic | Test-schema build (`upgrade head` subprocess) | ✓ | 1.19.1 | — |
| Ruff / mypy | Lint + type gates | ✓ | 0.16.4 / 2.3.1 | — |
| Hevy API | **Not needed** — this phase reads stored data only | n/a | — | — |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none.

**Notable:** this phase adds **zero** entries to `pyproject.toml`. If a plan proposes a new
dependency, that is a signal the design drifted from CLAUDE.md's "SQL aggregates + plain Python."

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 + pytest-asyncio 1.4.0 (`asyncio_mode = "auto"` — no decorator needed) |
| Config file | `pyproject.toml` → `[tool.pytest.ini_options]` (`testpaths = ["backend/tests"]`, `pythonpath = ["backend"]`, marker `integration`) |
| Quick run command | `.venv/bin/python -m pytest -q -m "not integration"` |
| Full suite command | `.venv/bin/python -m pytest -q` |
| Measured baseline | **177 passed, 114 deselected in 0.94 s** (fast suite, 2026-08-30) `[VERIFIED: local execution]` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| VOL-01 | Warm-up sets excluded from hard sets, reps and tonnage | integration | `pytest backend/tests/test_analytics_volume.py -k warmup -x` | ❌ Wave 0 |
| VOL-01 | `dropset` counts as a hard set; `!= 'warmup'` not `== 'normal'` | integration | `pytest backend/tests/test_analytics_volume.py -k dropset -x` | ❌ Wave 0 |
| VOL-01 | Tonnage is `None` (never `0`) where the modality has no `weight × reps`; `tonnage_sets` reports coverage | integration | `pytest backend/tests/test_analytics_volume.py -k modality -x` | ❌ Wave 0 |
| VOL-01 | `weight_kg = 0` counts as a tonnage set contributing `Decimal("0.000")` | integration | `pytest backend/tests/test_analytics_volume.py -k zero_load -x` | ❌ Wave 0 |
| VOL-01/D-02 | A `2026-08-23T17:00:00Z` workout buckets to local week `2026-08-24`; changing `users.timezone` changes the bucket | integration | `pytest backend/tests/test_analytics_volume.py -k week_boundary -x` | ❌ Wave 0 |
| VOL-02 | `direct_sets` / `indirect_sets` raw counts + `weighted_sets` exact `Decimal` at default 1.0/0.5 | integration | `pytest backend/tests/test_analytics_volume.py -k muscle_split -x` | ❌ Wave 0 |
| VOL-02/NORM-03 | Passing `{DIRECT: 0.8, INDIRECT: 0.3}` changes `weighted_sets` and leaves the raw counts untouched | integration | `pytest backend/tests/test_analytics_volume.py -k custom_weights -x` | ❌ Wave 0 |
| VOL-02/NORM-02 | An `exercise_muscle_overrides` row changes the per-muscle result (proves the resolver is used, not a raw join) | integration | `pytest backend/tests/test_analytics_volume.py -k override -x` | ❌ Wave 0 |
| VOL-03 | Per-muscle `sessions` de-duplicates workouts — 3 hamstring exercises in one workout is 1 session | integration | `pytest backend/tests/test_analytics_frequency.py -k dedup -x` | ❌ Wave 0 |
| VOL-03 | `sessions_per_week` over an arbitrary (non-multiple-of-7) range is exact and quantized | unit + integration | `pytest backend/tests/test_analytics_frequency.py -k per_week -x` | ❌ Wave 0 |
| VOL-03 | Per-exercise frequency reported alongside per-muscle | integration | `pytest backend/tests/test_analytics_frequency.py -k exercise -x` | ❌ Wave 0 |
| DQ-01 | Response carries `last_synced_at` from `sync_state`; per-muscle responses carry both `workouts` and `exercise_templates` | integration | `pytest backend/tests/test_analytics_metadata.py -k freshness -x` | ❌ Wave 0 |
| DQ-01 | No `sync_state.last_error`, status detail, DSN or credential appears in any return model | unit | `pytest backend/tests/test_analytics_metadata.py -k no_leak -x` | ❌ Wave 0 |
| DQ-02 | `insufficient_data` is `True` at 1 session, `False` at 2 (D-05 boundary, both sides) | integration | `pytest backend/tests/test_analytics_metadata.py -k insufficient -x` | ❌ Wave 0 |
| DQ-02 | `earliest_data_at` is the oldest synced workout, and is `None` with no data | integration | `pytest backend/tests/test_analytics_metadata.py -k earliest -x` | ❌ Wave 0 |
| Criterion 5 | Superset fixture produces numbers identical to the non-superset equivalent | integration | `pytest backend/tests/test_analytics_volume.py -k superset -x` | ❌ Wave 0 |
| Architecture | `app/analytics/` imports nothing from `app.mcp` or `app.integrations` | unit (static, **no** integration marker) | `pytest backend/tests/test_analytics_isolation.py -x` | ❌ Wave 0 |
| Regression | Fast suite stays green and fast | unit | `.venv/bin/python -m pytest -q -m "not integration"` | ✅ 177 passing |

### Sampling Rate

- **Per task commit:** `.venv/bin/python -m pytest -q -m "not integration"` (0.94 s baseline — new
  fast tests must not materially slow it)
- **Per wave merge:** `.venv/bin/python -m pytest -q` (full suite, container-backed)
- **Phase gate:** full suite green + `ruff check` + `mypy` before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `backend/tests/test_analytics_volume.py` — VOL-01, VOL-02
- [ ] `backend/tests/test_analytics_frequency.py` — VOL-03
- [ ] `backend/tests/test_analytics_metadata.py` — DQ-01, DQ-02
- [ ] `backend/tests/test_analytics_isolation.py` — architectural boundary (static, fast suite)
- [ ] `backend/tests/conftest.py` — `golden_workout` builder fixture (flush + rollback, never commit)
- [ ] Framework install: **none needed** — pytest, pytest-asyncio, testcontainers and time-machine
      are all installed and already used by 291 existing tests

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Handled at the MCP boundary (Phase 2, WorkOS AuthKit). Analytics functions are internal and never see a token |
| V3 Session Management | no | MCP v2 transport is stateless; no session state here |
| V4 Access Control | **yes** | **Every query must filter `Workout.user_id == user_id`, and the `exercise_muscles` lookup must be user-scoped.** `effective_muscles_bulk` already scopes by `user_id` internally (`resolver.py:133,147`). The schema is multi-user-ready, so an unscoped query is a cross-tenant data leak that a single-user test suite cannot detect. Add a test with two users' workouts asserting isolation |
| V5 Input Validation | **yes** | The timezone string reaches SQL. Validate with `app.core.time.validate_timezone()` and pass it as a **bound parameter** — Ruff `S608` blocks f-string SQL (C-7). Date ranges must reject `end < start` (guard in `local_range_bounds`). Reject or clamp absurd ranges so a Phase 6 tool cannot request 200 years of week buckets |
| V6 Cryptography | no | No crypto in this phase |
| V7 Error Handling & Logging | **yes** | An asyncpg exception can carry the DSN and driver internals (`test_mcp_tools.py:13-18`, T-02-09). Analytics must not return raw driver text to a caller. Workout titles are health data — never log row contents (`test_hevy_end_to_end.py` asserts none of `"Push Day"`, `"80.5"`, `"18.5"` reaches the log stream) |
| V8 Data Protection | **yes** | MCP-06 / C-6: the return models must contain no `sync_state.last_error`, no credentials, no internal IDs beyond what Phase 6 needs. Prefer `last_synced_at` over returning the whole `SyncState` row |

### Known Threat Patterns for Python + SQLAlchemy + asyncpg + Postgres

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection through a dynamically-interpolated timezone or date | Tampering | SQLAlchemy Core expressions with bound parameters; `func.timezone(tz, col)` keeps `tz` bound. Ruff `S608` enforces it at lint time |
| Cross-tenant data disclosure via a missing `user_id` predicate | Information Disclosure | Mandatory `user_id` filter in every statement; a two-user isolation test as the enforcement mechanism |
| Health-data leakage into logs (workout titles, body-composition values) | Information Disclosure | Three-layer redaction already in `app/logging.py`; analytics logs metrics only, never row contents |
| Credential/DSN leakage through an unhandled driver exception | Information Disclosure | Log with `log.exception(...)` (which routes through redaction) and return a coarse state, mirroring `health.py` / `ping.py` |
| Unbounded result set / resource exhaustion from a huge requested range | Denial of Service | Clamp or reject implausible ranges at the analytics boundary; MCP-03 already forbids unbounded result sets, and enforcing it here means Phase 6 inherits the guarantee |
| Silent wrong answers presented as confident data | Repudiation / integrity-of-advice | This is the phase's real security-adjacent risk. DQ-01 freshness + DQ-02 coverage exist for it; Pitfalls 3 and 5 are the two concrete cases where a plausible-looking number is wrong |

## Sources

### Primary (HIGH confidence)

- **Live execution against `brett-db-1`, PostgreSQL 18.6, 2026-08-30** — SQLAlchemy 2.0.52 +
  asyncpg 0.31.0 from this repo's `.venv`. Source of every `[VERIFIED: live db]` claim: row counts,
  `set_type` / `exercise_type` distributions, NULL and zero-value coverage, `EXPLAIN ANALYZE` index
  plans, `date_trunc` return types, `FILTER` clause rendering, `generate_series` alias failure and
  fixes, `Decimal` round-tripping, the hybrid-vs-pure-SQL equality check, and the per-muscle
  session-inflation measurement. **This is the strongest evidence in this document.**
- **Source read: `.venv/lib/python3.13/site-packages/sqlalchemy/dialects/postgresql/asyncpg.py:319-345`**
  — `AsyncpgNumeric.result_processor` returns `None` for `_DECIMAL_TYPES`/`_INT_TYPES` when
  `asdecimal=True`; the quantizing branch applies only to `_FLOAT_TYPES` (Pitfall 8)
- **Repo source, read in full this session:** `backend/app/normalization/resolver.py`,
  `backend/app/normalization/muscles.py`, `backend/app/core/time.py`,
  `backend/app/db/models/workout.py`, `backend/app/db/models/exercise.py`,
  `backend/app/db/models/user.py`, `backend/app/db/models/sync_state.py`,
  `backend/app/db/repositories/sync_state.py`, `backend/tests/conftest.py`,
  `backend/tests/test_time.py`, `pyproject.toml`
- **Context7 `/websites/sqlalchemy_en_20_core`** → https://docs.sqlalchemy.org/en/20/core/functions.html
  — `table_valued`, `column_valued`, `render_derived` ("required by backends like PostgreSQL"),
  `WITH ORDINALITY`
- **`importlib.metadata` in the project venv, 2026-08-30** — all installed versions
- **`.venv/bin/python -m pytest -q -m "not integration"`, 2026-08-30** — 177 passed / 114
  deselected / 0.94 s baseline
- **Local execution of `app.core.time.local_day_bounds`** across `America/Santiago`, `Asia/Beirut`
  and `Asia/Jakarta` DST edges (Pitfall 9)

### Secondary (MEDIUM confidence)

- `.planning/phases/04-volume-frequency-analytics/04-CONTEXT.md` — locked decisions D-01…D-06
- `.planning/phases/03-hevy-integration-normalization/03-PATTERNS.md` — repo conventions (module
  docstring style, structured-logging event naming, shared-container hygiene, dependency-pinning
  rules, test-marker discipline)
- `docs/hevy-api-observations.md` "Dumbbell weight semantics" — `weight_kg` is per-dumbbell,
  user-confirmed against the Hevy app 2026-08-30
- `BRETT blueprint.md` §17, §18, §23, §39, §40, §41 — scope and example output shapes
- `CLAUDE.md` — locked stack, "What NOT to Use", testing constraints
- `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md` Phase 4, `.planning/STATE.md`

### Tertiary (LOW confidence)

- None. Every claim in this document is grounded in local execution, a source read, or a project
  document. No unverified web search informed any recommendation.

## Metadata

**Confidence breakdown:**

- **Standard stack: HIGH** — nothing new is added; every library version confirmed installed and
  exercised against a real database in this session
- **Architecture: HIGH** — the recommended hybrid was built and run end-to-end over 17 months of
  real data and cross-checked to exact `Decimal` equality against the alternative design
- **Live data ground truth: HIGH** — direct queries against the production-shaped dev database
- **Pitfalls: HIGH** — 11 of 12 were reproduced by execution; Pitfall 8's safe-path reasoning was
  additionally confirmed by reading the SQLAlchemy dialect source
- **Open questions / assumptions: MEDIUM by construction** — these are genuine ambiguities in the
  locked decisions, surfaced rather than papered over. A5 and A3 in particular deserve a user
  confirmation at plan review

**Research date:** 2026-08-30
**Valid until:** 2026-09-29 (30 days — the stack is fully pinned and the schema is frozen by Phase
3; the only thing that can invalidate this is a Hevy sync introducing a new `exercise_type` or the
first `exercise_muscle_overrides` row, both of which the recommended design already tolerates)

---

*Phase: 04-volume-frequency-analytics*
*Researched: 2026-08-30*
