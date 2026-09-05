# Phase 9: Historical Apple Health Backfill - Research

**Researched:** 2026-09-03
**Domain:** Streaming XML ingest of Apple Health `export.xml` into an existing normalize/upsert pipeline
**Confidence:** HIGH

> **Provenance note.** This phase is unusual: the primary source — the real `export.xml` — is on
> disk and was measured directly in this research pass. Almost every number below is
> `[VERIFIED: export.xml]` (a command run against the actual 191 MB file) or
> `[VERIFIED: measured]` (a probe script executed against the real file / real Postgres / real
> Phase 8 modules), not `[ASSUMED]`. The Assumptions Log is correspondingly short.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Execution environment**
- **D-01:** Run the backfill as a local CLI subcommand (`app/cli.py`, alongside `sync-hevy`),
  executed on the user's own machine directly against the production Neon database — not a
  one-off Cloud Run Job. `export.xml` already lives locally at the repo root (gitignored); a
  Cloud Run Job would require uploading it to Cloud Storage first for no real benefit on a
  command that runs once, maybe twice.
- **D-02:** The production `DATABASE_URL` is supplied via an environment variable override at
  invocation time (e.g. `DATABASE_URL=<prod-url> uv run python -m app.cli backfill-apple-health
  export.xml`), not a separate `.env.production` file. No new config file, no production
  credential lingering on disk longer than the shell session.

**Dry-run / safety**
- **D-03:** The CLI supports a required `--dry-run` mode: parses and aggregates the entire file
  and prints the full summary (see D-05/D-06 below) without writing anything to the database.
  Cheap insurance before committing 4.5 years of writes to production on a command that has no
  practical rollback.
- **D-04:** Both dry-run and real-run summaries report a count of skipped `Workout` and
  `BodyMass` XML elements (e.g. "workouts skipped: 221, body-mass skipped: 79"), so success
  criterion #4 (no Hevy-originated workout/body-mass row enters BRETT) is visually confirmable
  without building a dedicated coverage cross-check table — consistent with Phase 8's D-02
  decision not to build one.

**Output & progress reporting**
- **D-05:** While the file streams (likely several minutes for 191 MB), print a periodic
  heartbeat line (e.g. every N thousand XML records processed) so the run is visibly alive,
  not silent-until-done. Interval is Claude's discretion at planning time.
- **D-06:** On completion (dry-run or real), print one final summary block covering: rows
  written/would-write per metric, the date range actually covered, datapoints dropped and
  metrics-unrecognized counts (mirroring `NormalizeResult`'s existing counters), the
  Hevy-exclusion count (datapoints excluded via `is_hevy_sourced`), and the D-04 workout/
  body-mass skip counts. Style mirrors `sync-status`'s plain `print()`-based operator output,
  not a log line.

**Error recovery**
- **D-07:** A malformed or unexpected XML element encountered mid-stream is logged and skipped;
  the run continues to the end. It is never allowed to abort the whole backfill — this is the
  same log-and-continue philosophy as Phase 8's D-04, applied here because aborting mid-parse on
  a one-time, multi-minute import would discard all prior progress over a single bad `Record`.

### Claude's Discretion
- Heartbeat interval/granularity for D-05 (record count vs. time-based).
- Whether the historical path reuses `normalize.normalize_payload`/`HAEPayload` literally (by
  constructing synthetic wire-shaped batches from XML) or calls the same underlying
  building blocks (`to_canonical`, `is_hevy_sourced`, `METRIC_REGISTRY`, `upsert_health_metric`)
  from a purpose-built XML aggregator — the constraint that is NOT discretionary is that both
  paths must produce byte-identical rows for the same logical datapoint (ROADMAP: "two parsers
  produce two shapes and the historical trend silently disagrees with the ongoing one").
  `normalize.py:190-195`'s own comment already anticipates this phase feeding `to_canonical`
  from a raw string.
- Mapping from `export.xml`'s HealthKit type identifiers (e.g.
  `HKQuantityTypeIdentifierStepCount`) to Phase 8's wire metric names (e.g. `step_count`) in
  `METRIC_REGISTRY` — a research/implementation task, not a user decision, since the target
  registry and its 12 metrics are already fixed by Phase 8.
  `HKQuantityTypeIdentifierActiveEnergyBurned` in particular carries the Hevy-contamination
  finding, so its mapping and exclusion path deserve extra research scrutiny.
- Per-row database-write failure handling during the actual write pass (e.g. a single
  malformed/out-of-range value that parses fine as XML but fails the upsert) — reuse the
  existing SAVEPOINT-per-row skip-and-continue pattern from `ingest.py::ingest_payload` verbatim
  unless research surfaces a reason not to; not re-litigated as a separate user decision since it
  directly extends D-07's "never lose the whole run over one bad element" principle to the write
  side.
- Exact CLI flag/argument names and defaults (e.g. whether the file path defaults to
  `export.xml` at the repo root or must always be passed explicitly).
- Whether to log a warning (mirroring `health_ingest_unrecognized_metric`) for any HealthKit
  type identifier in the file that isn't in the allowlist mapping, vs. only counting it silently
  — implementation detail, not a locked behavior.

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope. No new capabilities were proposed; all four
discussed areas (execution environment, dry-run/safety, output/progress, error recovery) are
implementation choices within HEALTH-10's existing boundary.

> **Research note on the discretion item that research CAN now settle:** the "literal
> `HAEPayload` reuse vs. purpose-built aggregator" choice was measured both ways against the
> real file. Both produce **byte-identical output** (8,077 rows, identical counters). See
> [Decision D-A](#decision-d-a-which-reuse-shape) — research recommends the literal-reuse
> variant, on correctness-by-construction grounds, with one required mitigation.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| **HEALTH-10** | A one-time historical backfill imports the user's existing `export.xml` Apple Health export, applying the same Hevy-exclusion filter as ongoing sync | §[HealthKit → wire mapping](#the-healthkit--wire-metric-mapping-complete-and-verified) gives the complete 12-metric mapping, verified against the real file; §[Hevy exclusion](#hevy-contamination-fully-enumerated) proves `is_hevy_sourced` catches 100% of Hevy records with no code change; §[Architecture Patterns](#architecture-patterns) gives the exact call sequence reusing Phase 8's normalizer and upsert verbatim |

### Roadmap success criteria → evidence

| # | Criterion | Status from this research |
|---|-----------|---------------------------|
| 1 | Real 191 MB `export.xml` imports within memory budget, tested against the actual file | **Measured: 66.8 MB peak, 3.5 s** for a full end-to-end simulation using the real Phase 8 modules. Streaming parse alone is 16.2 MB. `[VERIFIED: measured]` |
| 2 | Activity + nutrition history from 2022-03 through export date queryable | **Measured: 2022-03-10 → 2026-08-26, 1,631 distinct local days, 8,077 rows.** `[VERIFIED: measured]` |
| 3 | Days covered by both backfill and webhook hold one value per metric per day | **Satisfied by the natural key** — and only because the backfill writes the *same* `source_name` string the webhook writes. This is the subtlest finding in this research; see [Pitfall 2](#pitfall-2-source_name-is-in-the-natural-key--criterion-3-lives-or-dies-on-it). `[VERIFIED: measured]` |
| 4 | No Hevy-originated workout or body-mass row enters BRETT | **Guaranteed twice over**: `Workout`/`ActivitySummary` are not `Record` elements and are never mapped; `BodyMass` is absent from `METRIC_REGISTRY`. Hevy `Record`s are additionally caught by `is_hevy_sourced` (269 of 269). `[VERIFIED: measured]` |
</phase_requirements>

## Summary

**The good news dominates: this phase is far smaller and far safer than the roadmap assumed.**
The real `export.xml` was measured directly rather than reasoned about. A complete end-to-end
simulation — streaming the real 191 MB file through the real Phase 8 `METRIC_REGISTRY`,
`to_canonical`, `is_hevy_sourced`, `parse_hae_datetime` and `local_day` — runs in **3.5 seconds
at 66.8 MB peak RSS** and produces **8,077 database rows** covering 2022-03-10 → 2026-08-26.
There were **zero parse failures** across all 230,395 in-scope records: no malformed value, no
unparseable date, no missing `sourceName`, no negative number, no unit outside
`MetricSpec.accepted_units`. `to_canonical` is a pass-through for every single in-scope record in
this file — not one unit conversion is needed.

Three roadmap/prior-research claims turned out to be wrong or misleading and should not be
carried into the plan. (1) `ElementTree.parse()` builds a **316 MB** DOM, not the "1.5–2 GB"
PITFALLS #6 asserts — the CLI-not-web-service decision is still right, but on the 32 MiB HTTP
cap and separation-of-concerns grounds, not on an OOM that would not actually happen. (2) The
parse is **not** "likely several minutes"; it is under 4 seconds. The genuinely slow phase is the
**network write** — the Phase 8 SAVEPOINT-per-row pattern costs a measured **3.0 round trips per
row**, i.e. **24,231 round trips** for 8,077 rows, which is ~12 minutes to a Singapore Neon and
~90 minutes to a US one. D-05's heartbeat belongs on the *write* loop, not (only) the parse.
(3) `normalize.py`'s docstring claims the webhook sends `sourceName="iPhone"` while `export.xml`
says `"Vegant's iPhone"` — that is **stale**. The live-verified `device_capture.json` (2026-09-03)
shows the webhook sends **`V's iPhone`**, the identical string `export.xml` uses for the current
phone. That coincidence is what makes success criterion #3 work at all, and it is fragile enough
to deserve a test.

The one real correctness hazard is that `source_name` sits **inside** the natural key. Success
criterion #3 ("one value per metric per day, not two") is satisfied only because the backfill and
the webhook independently produce the same `source_name` string. They currently do, verified on
both sides. A separate, *intended* consequence of the same design: the export contains two
physical phones (`hardware:iPhone14` as `Vegant's iPhone`, `hardware:iPhone18` as `V's iPhone`)
whose records overlap on **343 metric-days** between 2026-01-09 and 2026-08-11. Those legitimately
become two rows per metric-day, which is exactly what Phase 8's schema docstring says it wants —
but any Phase 13 analytics reader that sums `health_daily_metrics` without thinking about
`source_name` will silently double-count that window.

**Primary recommendation:** Add one module,
`backend/app/integrations/health_auto_export/backfill.py`, that streams the file with
`ET.iterparse` + `elem.clear()` + `root.clear()`, assembles the 12 allowlisted metrics into a
literal `HAEPayload`, calls `normalize_payload` **once for the whole file**, and writes the
resulting 8,077 rows with a **chunked multi-row upsert plus per-row SAVEPOINT fallback**. Put it
inside the HAE package — `test_health_auto_export_isolation.py` forbids `app/cli.py` from
importing `registry` or `schemas` at all — and keep `cli.py` a thin dispatcher.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Read + stream 191 MB XML from local disk | Local CLI process | — | D-01: the file is on the user's machine, gitignored. Never crosses HTTP (32 MiB Cloud Run cap). |
| HealthKit type → wire metric mapping | `integrations/health_auto_export/` | — | HealthKit identifiers are provider vocabulary. CLAUDE.md provider-isolation constraint + enforced isolation test. |
| Unit conversion, Hevy exclusion, day bucketing, aggregation | `integrations/health_auto_export/normalize.py` + `registry.py` (**unchanged**) | — | ROADMAP: "must reuse Phase 8's normalizer verbatim". Reuse is literal, not parallel reimplementation. |
| Idempotent write to `health_daily_metrics` | `integrations/health_auto_export/` (new batched writer) | `ingest.py::upsert_health_metric` (fallback path) | Same table, same named constraint, same replace semantics as the webhook. |
| Freshness bookkeeping (`sync_state`) | `db/repositories/sync_state.py` (**unchanged**) | — | Provider-neutral helpers already take `provider`/`resource` as arguments. |
| Argument parsing, operator output, exit code | `app/cli.py` | — | Existing `sync-hevy`/`sync-status`/`mapping-gaps` pattern. Thin dispatch only. |
| Timezone → local day | `app/core/time.py` (**unchanged**) | — | FOUND-03. `local_day(ts, tz)`, `tz` read from `users.timezone`, never a constant. |

**No new tier, no new table, no migration.** `health_daily_metrics` already exists (migration
`0005_health_daily_metrics`). `[VERIFIED: codebase]`

## Project Constraints (from CLAUDE.md)

| Directive | How this phase complies |
|-----------|-------------------------|
| Python 3.12+/3.13, stdlib-first, uv + `uv.lock` | Uses only stdlib `xml.etree.ElementTree`. **No new runtime dependency required** (see [Standard Stack](#standard-stack)). |
| Provider isolation: Hevy logic confined to `integrations/hevy/` | Symmetrically: all HealthKit/HAE vocabulary stays in `integrations/health_auto_export/`. **Enforced by test, not convention** — see [Pitfall 1](#pitfall-1-clipy-cannot-import-registry-or-schemas--the-isolation-test-forbids-it). |
| MCP tools read-only in v1 | This phase adds no MCP surface. |
| Never expose API keys / DB credentials in logs | D-02 passes `DATABASE_URL` as an env var for one shell session. Summary output is counts and metric names only — **never a measured quantity** (Phase 8's logging rule). |
| Data integrity: sync idempotent, never corrupts on partial failure | Replace-semantics upsert bound to the named constraint; whole-file aggregation before the first write; per-chunk fallback so one bad row cannot abort the run. |
| Secrets never committed | `export.xml`/`export_cda.xml` are already gitignored; no fixture derived from them may contain real quantities (see [Validation Architecture](#validation-architecture)). |
| Ruff `E,F,I,UP,B,ASYNC,S` + mypy `disallow_untyped_defs` | **`S314` fires on `ET.iterparse`** — a hard gate. Resolution in [Pitfall 6](#pitfall-6-ruff-s314-blocks-etiterparse--and-the-recommended-fix-is-worse). |

## Standard Stack

### Core — nothing new is needed

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `xml.etree.ElementTree` | stdlib (Python 3.13) | Streaming XML parse via `iterparse` | Handles the real file at **16.2 MB / 2.5 s**. The DOCTYPE internal subset parses without complaint. No third-party parser is justified. `[VERIFIED: measured]` |
| `sqlalchemy[asyncio]` | 2.0.52 (already pinned) | Batched + per-row upsert | Already in `pyproject.toml`. `pg_insert(...).on_conflict_do_update(constraint=...)` accepts a list of value dicts for multi-row insert. `[VERIFIED: measured]` |
| `structlog` | 26.1.0 (already pinned) | Log-and-continue diagnostics (D-07) | Already the project's logger; redaction processors already configured. |
| `argparse` | stdlib | New `backfill-apple-health` subcommand | Matches the existing `build_parser()` pattern exactly. `[VERIFIED: codebase]` |

**Installation:** none. `[VERIFIED: measured]` — the full simulation ran on the existing `.venv`
with no additional package.

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| stdlib `ET.iterparse` | `defusedxml==0.7.1` | **Verified working** on the real file: 2.8 s / 16.6 MB, all 438,649 records — the DOCTYPE does *not* trip it (`forbid_dtd=False` is the default and the internal subset declares no `ENTITY`). It silences `S314` without a `noqa`. **But** its last release is **2021-03-08**, older than the staleness for which this project already rejected `python-jose` (CLAUDE.md: "Effectively unmaintained (last release May 2025)"). Recommending it would contradict the project's own dependency standard for zero real protection on a local, user-owned file. `[VERIFIED: measured]` + `[VERIFIED: pypi.org/pypi/defusedxml/json]` |
| stdlib `ET.iterparse` | `lxml.etree.iterparse` | Offers the real `getparent()` the phase brief asked about, and `iterparse(tag=...)` filtering. Not justified: stdlib already hits 16 MB, and lxml is a C-extension dependency this project does not have. |
| `iterparse` | `ET.parse()` full DOM | 316 MB, 2.7 s. Would actually *work* on a 1 GiB local process — but it scales with file size, and the streaming version is no harder to write. `[VERIFIED: measured]` |
| Reading `export.xml` | Reading `records.csv` (136 MB, already at repo root) | The CSV is a derived convenience export. `export.xml` is the source of truth and the only one carrying `Workout`/`ActivitySummary` structure. Stay on the XML. |

## Architecture Patterns

### System architecture — data flow

```
  export.xml (191,257,897 bytes, on local disk, gitignored)
        │
        │  ET.iterparse(path, events=("start","end"))
        │  capture root on first event
        ▼
  ┌─────────────────────────────────────────────────────────┐
  │  STREAM LOOP  — one pass, bounded memory                │
  │                                                          │
  │   element ──┬── tag == "Record" ──► type in HK_TO_WIRE?  │
  │             │        │                   │               │
  │             │        │       yes ────────┴──► append     │
  │             │        │                        {qty,date, │
  │             │        │                         source}   │
  │             │        │                        to metric  │
  │             │        │       no  ──► count as            │
  │             │        │               unrecognized        │
  │             │        │               (+ BodyMass counter)│
  │             │        │                                   │
  │             ├── tag == "Workout"         ──► skip, count │
  │             ├── tag == "ActivitySummary" ──► skip, count │
  │             └── anything else            ──► skip        │
  │                                                          │
  │   ALWAYS: elem.clear(); root.clear()   ◄── both required │
  └─────────────────────────────────────────────────────────┘
        │  12 metric buckets, 230,395 raw datapoints
        ▼
  HAEPayload.model_validate({...})          ── Phase 8 wire model, unchanged
        │
        ▼
  normalize_payload(payload, tz=users.timezone)   ── Phase 8, UNCHANGED
        │   • METRIC_REGISTRY allowlist    • to_canonical (unit conversion)
        │   • is_hevy_sourced  (HEALTH-08) • local_day  (FOUND-03)
        │   • sum per (metric, source_name, local_day)
        ▼
  NormalizeResult: 8,077 NormalizedRow  +  counters  +  kinds_present
        │
        ├──► --dry-run ──► print summary (D-03/D-06) ──► exit 0, NO writes
        │
        ▼  real run
  ┌─────────────────────────────────────────────────────────┐
  │  WRITE PASS — ONE transaction                            │
  │   chunk rows (500) ──► multi-row INSERT ... ON CONFLICT  │
  │        │                DO UPDATE  (replace semantics)   │
  │        └── on SQLAlchemyError ──► retry that chunk       │
  │                                   row-by-row inside      │
  │                                   SAVEPOINT, skip+log    │
  │                                   the offender (D-07)    │
  │                                                          │
  │   then, SAME transaction:                                │
  │     complete_sync(provider='apple_health',               │
  │                   resource='activity' | 'nutrition')     │
  │   commit()                                               │
  └─────────────────────────────────────────────────────────┘
        │
        ▼
  print final summary block (D-06)  ──►  exit 0
```

### Recommended file layout

```
backend/app/
├── cli.py                                    # + backfill-apple-health subcommand (thin dispatch)
└── integrations/health_auto_export/
    ├── backfill.py                           # NEW — the only new module
    ├── normalize.py                          #  unchanged
    ├── registry.py                           #  unchanged
    ├── ingest.py                             #  unchanged (or + one batched writer)
    ├── schemas.py                            #  unchanged
    └── errors.py                             #  unchanged
backend/tests/
├── test_health_auto_export_backfill.py       # NEW — unit, no container
├── test_backfill_real_export.py              # NEW — opt-in, real 191 MB file
└── fixtures/hae/export_sample.xml            # NEW — small, synthetic quantities
```

### Pattern 1: the two-line memory discipline

**What:** `elem.clear()` alone is *not* enough. It empties the element but leaves it attached to
the root, so `HealthData` accumulates 438,649 empty `Element` objects.

**Measured on the real file** `[VERIFIED: measured]`:

| Strategy | Time | Peak RSS |
|----------|------|----------|
| `iterparse` + `elem.clear()` + `root.clear()` | 2.5 s | **16.2 MB** |
| `iterparse` + `elem.clear()` only | 2.6 s | 53.5 MB |
| `iterparse`, no clear at all | 3.2 s | 385.2 MB |
| `ET.parse()` full DOM | 2.7 s | 316.5 MB |

Stdlib `Element` has **no `getparent()`** (the phase brief flagged this correctly). The
workaround is not a parent stack — it is simply capturing the root from the first `start` event
and calling `root.clear()`, which is safe here because every `Record` is a direct child of
`HealthData` and is fully consumed at its `end` event.

```python
# Source: verified against export.xml, 2026-09-03
it = ET.iterparse(path, events=("start", "end"))  # noqa: S314 — see Pitfall 6
_, root = next(it)                                 # first event is start of <HealthData>
for event, elem in it:
    if event != "end":
        continue
    ...                       # handle elem
    elem.clear()
    root.clear()              # ← without this, 53.5 MB instead of 16.2 MB
```

### Pattern 2: aggregate the WHOLE file, then write — never chunk the parse

**What:** the replace-semantics upsert is only correct because `normalize_payload` sums every
datapoint for a key *before* the first write. `ingest.py`'s module docstring is explicit:
"A **replace** clause … a day split across two batches silently **loses** the first of them."

**Why chunking the parse would be a data-loss bug here:** `export.xml` is grouped **by record
type**, then chronologically within each type. `[VERIFIED: export.xml]`

| First line of each type | Type |
|---|---|
| 88 | `HKQuantityTypeIdentifierStepCount` |
| 48,349 | `HKQuantityTypeIdentifierDistanceWalkingRunning` |
| 96,474 | `HKQuantityTypeIdentifierBasalEnergyBurned` |
| 180,734 | `HKQuantityTypeIdentifierActiveEnergyBurned` |
| 229,852 | `HKQuantityTypeIdentifierDietaryFatTotal` |

A single local day's records are therefore scattered across the entire file. Any positional
chunking splits days across batches and replace semantics silently drops the earlier half.

**This is a non-issue in practice** because the aggregate is tiny: **8,077 rows** for 4.5 years.
Hold the whole thing in memory. `[VERIFIED: measured]`

### Pattern 3: batched upsert with per-row fallback

**Measured against real Postgres 18** `[VERIFIED: measured]`:

| Approach | Round trips / row | 400 rows (localhost) | Extrapolated: 8,077 rows |
|---|---|---|---|
| SAVEPOINT-per-row (Phase 8's `ingest_payload`) | **3.0** (`SAVEPOINT` + `INSERT` + `RELEASE`) | 0.66 s | 24,231 round trips → **~12 min @ 30 ms RTT, ~90 min @ 230 ms** |
| Multi-row insert, chunk = 500 | 0.0025 | 0.06 s | ~17 statements → **seconds, any region** |

Phase 8's per-row pattern is correct for a 23-row webhook delivery and is a poor fit for 8,077
rows over the public internet. The hybrid preserves D-07's guarantee at ~1/1400 the round trips:

```python
# Source: pattern derived from ingest.py::ingest_payload, benchmarked 2026-09-03
CHUNK = 500
for start in range(0, len(rows), CHUNK):
    chunk = rows[start:start + CHUNK]
    try:
        async with session.begin_nested():
            await _upsert_many(session, user_id=user_id, rows=chunk)
    except SQLAlchemyError:
        # Fall back to Phase 8's exact per-row path for THIS chunk only, so one bad
        # row costs 500 fast rows' worth of retries and never the whole run (D-07).
        for row in chunk:
            try:
                async with session.begin_nested():
                    await upsert_health_metric(session, user_id=user_id, row=row)
            except SQLAlchemyError as exc:
                rows_skipped += 1
                log.warning(
                    "health_backfill_row_skipped",
                    metric=row.metric,
                    local_day=row.local_day.isoformat(),
                    source_name=row.source_name,
                    reason=type(exc).__name__,   # class name only — never str(exc)
                )
```

`_upsert_many` must set **exactly** the same columns Phase 8's `upsert_health_metric` sets on
conflict — `value`, `units`, `sample_count`, `updated_at` — or the two paths diverge.

**Realistically the fallback will never fire:** the value audit found zero malformed values in the
entire file. It exists for D-07's guarantee, not for expected traffic.

### Anti-Patterns to Avoid

- **A second XML-specific normalizer.** The ROADMAP's stated failure mode. `normalize_payload`
  already handles allowlisting, unit conversion, Hevy exclusion, day bucketing and aggregation.
  Reimplementing any of those for XML guarantees eventual divergence.
- **Matching `type=` without checking the element tag.** `<WorkoutStatistics type="HKQuantityTypeIdentifierActiveEnergyBurned" … sum="228" unit="kcal"/>` is a **child of `<Workout>`** in this file (224 of them). It carries the same `type=` string as a real `Record`, uses `sum=` instead of `value=`, and has **no `sourceName` of its own** — so `is_hevy_sourced` would return `False` and let Hevy's own workout energy in through the back door. Filter on `elem.tag == "Record"` first, always. `[VERIFIED: export.xml]`
- **Running the backfill through the web service.** 32 MiB Cloud Run request cap; D-01 settles it.
- **Positional chunking of the parse.** See Pattern 2.
- **`print()`ing a measured quantity in the summary.** D-06's summary is counts, metric names, dates and units only — Phase 8's logging rule applies to stdout as well as to logs.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HealthKit timestamp parsing | A `strptime` call in the new module | `schemas.parse_hae_datetime` | All 230,395 in-scope `startDate` values are exactly 25 chars in `%Y-%m-%d %H:%M:%S %z` — the existing parser's first format. Its own docstring says "THIS PARSER IS SHARED WITH PHASE 9. Do not write a second one." `[VERIFIED: measured]` |
| Unit conversion | A `kJ`/`mi`/`g` conversion table | `registry.to_canonical` | Every in-scope record in this file is already in its canonical unit — but hardcoding that assumption breaks on the next export if the user changes an app setting. |
| Hevy exclusion | A `sourceName == "Hevy"` string compare | `normalize.is_hevy_sourced` | Case-folds and strips. Catches 269/269 Hevy `Record`s in this file with no change. |
| Day bucketing | `datetime.date()` on the parsed timestamp | `core.time.local_day(ts, tz)` | At UTC+7 every instant from 17:00Z onward belongs to the next local day. |
| Per-metric aggregation | A `defaultdict` sum in the new module | `normalize.normalize_payload` | Also produces `kinds_present`, the drop counters, the deterministic row ordering, and the multi-point warning. |
| Idempotent write | A `SELECT`-then-`INSERT`/`UPDATE` | `pg_insert(...).on_conflict_do_update(constraint=...)` | Read-then-write is a race. Binding by constraint **name** raises loudly if the constraint is renamed instead of degrading into duplicate rows. |
| Freshness bookkeeping | A direct `sync_state` UPDATE | `sync_state.complete_sync(...)` | Rejects naive datetimes; leaves cursors alone; already provider-neutral. |

**Key insight:** the entire Phase 8 pipeline was written anticipating this phase —
`normalize.py:190-195` literally says "Phase 9's XML path will feed this same function from a raw
string." The correct amount of new domain logic in this phase is **the XML tag walk and the
12-entry identifier mapping, and nothing else**.

## Runtime State Inventory

This is a one-time data-migration phase. Explicit answers per category:

| Category | Items Found | Action Required |
|----------|-------------|-----------------|
| **Stored data** | `health_daily_metrics` in production Neon already holds live webhook rows from ~2026-09-02 onward (Phase 8 plan 08-08 landed 23 rows / 23 samples). The backfill writes **8,077** more rows into the same table. Overlap with existing rows is expected to be **zero days** (export ends 2026-08-26; webhook data starts 2026-09-02) but must be handled correctly regardless. | Data migration (this phase's whole purpose). Verify overlap empirically with `--dry-run` + a `SELECT min(local_day), max(local_day)` before the real run. |
| **Live service config** | None. No n8n, no Datadog, no external dashboard references this phase's data. The Cloud Run service is untouched — the backfill never deploys. | None — verified: this phase adds no route, no env var, no deploy artifact. |
| **OS-registered state** | None. No scheduler entry: D-01 makes this a manual, run-once-or-twice local command. Explicitly **not** a Cloud Run Job or cron. | None — verified against D-01. |
| **Secrets / env vars** | `DATABASE_URL` is overridden inline for one shell session (D-02). **No new secret, no new env var, no `.env.production` file.** `HEVY_API_KEY` is *not* needed — but note `get_settings()` may require it; see [Open Question 3](#3-does-get_settings-demand-hevy_api_key-for-a-command-that-never-calls-hevy). | Verify the CLI can bootstrap without `HEVY_API_KEY`, as `sync-status` and `mapping-gaps` already do. |
| **Build artifacts** | None. No package rename, no `pyproject.toml` change (no new dependency), no compiled artifact. | None — verified: stdlib-only. |

**One migration-adjacent side effect worth planning for:** after the backfill, `sample_count` on
backfilled days holds the raw-sample count (median > 1; 91.7% of rows aggregate multiple samples),
whereas the webhook writes `sample_count = 1` for its daily aggregate. Phase 8 documented a
falling `sample_count` as "the cheapest available detector for a batch-split data loss". On any
day covered by both, that detector now produces a **false positive**. See
[Open Question 2](#2-sample_count-semantics-diverge-between-the-two-paths).

## The HealthKit → wire metric mapping (complete and verified)

All twelve `METRIC_REGISTRY` entries map 1:1 to a HealthKit identifier present in the file. The
mapping is total in both directions — no registry entry is unreachable, no in-scope identifier is
unmapped. `[VERIFIED: export.xml]` `[VERIFIED: measured]`

| HealthKit `Record type=` | → wire metric | kind | Records | `unit=` in file | `accepted_units` | Conversion |
|---|---|---|---:|---|---|---|
| `HKQuantityTypeIdentifierStepCount` | `step_count` | activity | 48,261 | `count` | `{count}` | none |
| `HKQuantityTypeIdentifierActiveEnergyBurned` | `active_energy` | activity | 45,182 | `kcal` | `{kcal, kJ}` | none |
| `HKQuantityTypeIdentifierBasalEnergyBurned` | `basal_energy_burned` | activity | 84,260 | `kcal` | `{kcal, kJ}` | none |
| `HKQuantityTypeIdentifierDistanceWalkingRunning` | `walking_running_distance` | activity | 48,125 | `km` | `{km, mi}` | none |
| `HKQuantityTypeIdentifierFlightsClimbed` | `flights_climbed` | activity | 3,936 | `count` | `{count}` | none |
| `HKQuantityTypeIdentifierDietaryEnergyConsumed` | `dietary_energy` | nutrition | 95 | `kcal` | `{kcal, kJ}` | none |
| `HKQuantityTypeIdentifierDietaryProtein` | `protein` | nutrition | 94 | `g` | `{g}` | none |
| `HKQuantityTypeIdentifierDietaryCarbohydrates` | `carbohydrates` | nutrition | 94 | `g` | `{g}` | none |
| `HKQuantityTypeIdentifierDietaryFatTotal` | `total_fat` | nutrition | 94 | `g` | `{g}` | none |
| `HKQuantityTypeIdentifierDietaryFiber` | `fiber` | nutrition | 93 | `g` | `{g}` | none |
| `HKQuantityTypeIdentifierDietarySugar` | `dietary_sugar` | nutrition | 90 | `g` | `{g}` | none |
| `HKQuantityTypeIdentifierDietarySodium` | `sodium` | nutrition | 71 | `mg` | `{mg, g}` | none |

**Every in-scope metric has exactly one unit string in the entire file, and every one is already
accepted.** `to_canonical` performs zero conversions on this file — but it must still be called,
because the unit is a per-app user preference that can change on the next export.

**Naming traps confirmed present in the real data** (these are the pairs a hand-written mapping
gets wrong):
- `DietaryFatTotal` → `total_fat` (not `fat`, not `dietary_fat`)
- `DietarySugar` → `dietary_sugar` (**keeps** the prefix)
- `DietaryProtein` → `protein` (**drops** the prefix)
- `DietaryEnergyConsumed` → `dietary_energy` (keeps prefix, drops `Consumed`)
- `DistanceWalkingRunning` → `walking_running_distance` (word order reverses)

A `mypy`-visible total mapping plus an assertion that
`set(HK_TO_WIRE.values()) == set(METRIC_REGISTRY)` catches all five at import time. That assertion
passed in this research's simulation.

### Deliberately unmapped (dropped by the allowlist)

208,175 `Record` elements — 47.5% of the file — carry types with no registry entry and are
correctly dropped. Largest: `WalkingSpeed` (57,364), `WalkingStepLength` (57,363),
`WalkingDoubleSupportPercentage` (50,031), `WalkingAsymmetryPercentage` (30,218),
`HeadphoneAudioExposure` (10,077), `SleepAnalysis` (2,411 — cut from v2.0 per REQUIREMENTS),
plus 16 micronutrient types (1–63 records each, explicitly out of scope) and
`WaistCircumference` (8) / `Height` (8).

**Planning note (D-05/D-06 output design):** logging one line per unrecognized type is fine
(≈35 lines); one line per unrecognized *record* would be 208,175 lines. The existing
`health_ingest_unrecognized_metric` warning fires once per *metric*, which is the right
granularity — but only if the backfill groups by type before calling `normalize_payload`, which
the recommended design does naturally.

## Hevy contamination — fully enumerated

`_HEVY_SOURCE_ALIASES = frozenset({"hevy"})` with case-folded, whitespace-stripped matching
catches **100%** of Hevy-sourced elements in this file. `sourceName="Hevy"` is the only spelling
present. **No change to `_HEVY_SOURCE_ALIASES` is needed.** `[VERIFIED: export.xml]`

| Element | `sourceName="Hevy"` | Total | Reaches `is_hevy_sourced`? | Outcome |
|---|---:|---:|---|---|
| `Record` / `ActiveEnergyBurned` | **209** | 45,182 | Yes — `active_energy` is allowlisted | **Excluded by predicate.** This is the one that matters. |
| `Record` / `BodyMass` | 52 | 79 | No — `weight_body_mass` absent from registry | Dropped by allowlist before the predicate. |
| `Record` / `WaistCircumference` | 8 | 8 | No — absent from registry | Dropped by allowlist. |
| `Workout` | 218 | 224 | No — not a `Record` | Never mapped. Counted for D-04. |
| **Total** | **487** | | | |

The **209** figure independently reproduces `normalize.py`'s docstring claim ("209 records across
209 training days") from the file itself. The Phase 8 research finding is confirmed, not merely
inherited.

### All `sourceName` values in the file

| `sourceName` | Occurrences | Notes |
|---|---:|---|
| `Vegant’s iPhone` | 366,339 | Old phone, `hardware:iPhone14`. **U+2019**, not ASCII `'`. |
| `V’s iPhone` | 70,900 | Current phone, `hardware:iPhone18`. **U+2019.** Matches the live webhook exactly. |
| `Foodvisor` | 1,069 | Nutrition. Matches the live webhook exactly. |
| `Hevy` | 487 | Excluded — see above. |
| `Built With Science` | 54 | Second nutrition app; 2 records per macro. Legitimately ingested. |
| `Gymverse` | 17 | Includes 2 `ActiveEnergyBurned`. See [Open Question 1](#1-gymverse-and-zing-write-active-energy-too-3-records). |
| `Zing` | 3 | Includes 1 `ActiveEnergyBurned`. |
| `Cal AI` | 3 | All `BodyMass` — dropped by allowlist. |
| `Health` | 1 | Manual Health-app entry. |

## Common Pitfalls

### Pitfall 1: `cli.py` cannot import `registry` or `schemas` — the isolation test forbids it

**What goes wrong:** the obvious implementation puts the identifier mapping and the
`HAEPayload` construction in `app/cli.py`. The test suite fails immediately.

**Why:** `backend/tests/test_health_auto_export_isolation.py` walks **every** `.py` file under
`app/` that is not inside the HAE package (via `rglob`, so `cli.py` is included) and asserts the
literal strings `from app.integrations.health_auto_export.registry` and
`…health_auto_export.schemas` are absent. `[VERIFIED: codebase]`

**How to avoid:** put everything in `backend/app/integrations/health_auto_export/backfill.py` and
expose one high-level entry point. `cli.py` imports only that — mirroring how
`api/routes/health_ingest.py` imports only `ingest.parse_payload` / `ingest.ingest_payload` and
never names `HAEPayload`. `[VERIFIED: codebase]`

**Warning sign:** any `METRIC_REGISTRY` or `HAEPayload` reference outside the HAE package.

### Pitfall 2: `source_name` is in the natural key — criterion #3 lives or dies on it

**What goes wrong:** the backfill writes `source_name` values from `export.xml`; the webhook
writes values from its JSON payload. If those strings differ by even one character, the natural
key `(user_id, source, metric, source_name, local_day)` differs, the upsert **inserts instead of
updating**, and an overlapping day holds **two rows** — precisely what success criterion #3
forbids, and invisible without a targeted query.

**Why it nearly happened:** `normalize.py`'s module docstring states — as a documented
"Pitfall N-3" — that *"The webhook sends `"iPhone"`; `export.xml` says `"Vegant's iPhone"`."*
Taken at face value, that means the two paths **can never** collide and criterion #3 is
unachievable without a source-name mapping layer.

**That claim is stale.** `backend/tests/fixtures/hae/device_capture.json` — added at the 08-08
live-deployment checkpoint on 2026-09-03 and described in `conftest.py` as confirmed "live
against the deployed service and the resulting database rows in the same session" — shows the
webhook actually sends: `[VERIFIED: codebase]`

| Metric group | Webhook `source` | `export.xml` `sourceName` (current phone) | Match? |
|---|---|---|---|
| all 5 activity metrics | `V’s iPhone` | `V’s iPhone` | **exact, incl. U+2019** |
| all 7 nutrition metrics | `Foodvisor` | `Foodvisor` | **exact** |

**How to avoid:**
1. Do **not** normalize, ASCII-fold, or rewrite `source_name` in the backfill. Pass it through
   exactly as `normalize.py` already does (`.strip()` only, case and non-ASCII preserved).
2. Add a test that pins the equality — assert the `source` strings in `device_capture.json` are a
   subset of the `sourceName` values the backfill produces from a fixture. Today's correctness is
   a coincidence of the user not renaming their phone; a test turns it into a guarantee.
3. Correct `normalize.py`'s stale docstring in passing, or the next reader re-derives the wrong
   conclusion.

**Warning sign:** `SELECT metric, local_day, count(*) FROM health_daily_metrics GROUP BY 1,2 HAVING count(*) > 1` returning rows whose `source_name`s differ only cosmetically.

### Pitfall 3: `<WorkoutStatistics>` masquerades as an `ActiveEnergyBurned` record

**What goes wrong:** a parser keyed on the `type=` attribute rather than the element tag ingests
Hevy's own workout energy — the exact double-count HEALTH-08 exists to prevent — while the D-04
skip counter still cheerfully reports "224 workouts skipped".

**Why:** `export.xml` nests `<WorkoutStatistics type="HKQuantityTypeIdentifierActiveEnergyBurned"
startDate="…" endDate="…" sum="228" unit="kcal"/>` inside `<Workout>`. 224 such elements exist.
They use `sum=` not `value=`, and carry **no `sourceName`** — so `is_hevy_sourced(None)` returns
`False` by design (the gait-metric case) and would **not** filter them. `[VERIFIED: export.xml]`

**How to avoid:** branch on `elem.tag == "Record"` before reading `type=`. Never match on `type=`
alone.

**Warning sign:** exactly 224 more `active_energy` datapoints than expected, or `active_energy`
rows with `source_name = 'unknown'`.

### Pitfall 4: `health_ingest_multi_point_day` fires 7,403 times

**What goes wrong:** `normalize_payload` warns whenever a `(metric, source_name, local_day)` key
aggregates more than one datapoint, because for the *webhook* that means the device's daily
aggregation setting has drifted and replace semantics has become lossy. For the *backfill* it is
completely normal — raw HealthKit samples are per-event, not per-day.

**Measured: 7,403 of 8,077 rows (91.7%) aggregate more than one datapoint.** `[VERIFIED: measured]`

**Why it matters:** 7,403 structlog warnings is noise that buries the genuinely interesting lines
(the Hevy exclusions, the skipped rows), and it inverts the warning's documented meaning —
Phase 8 says "Under a correct device configuration that warning never fires."

**How to avoid:** the backfill is safe *because* it aggregates the whole file before writing, so
the condition the warning detects cannot occur. Suppress or contextualize it for this path —
e.g. bind a `structlog` filter for the duration of the backfill's `normalize_payload` call, or
report the count once in the D-06 summary instead. Do **not** change `normalize.py`'s behavior
for the webhook path.

**Warning sign:** a backfill run producing more log lines than database rows.

### Pitfall 5: batched upsert dies on duplicate conflict keys within one statement

**What goes wrong:** a multi-row `INSERT … ON CONFLICT DO UPDATE` containing two rows with the
same conflict key raises
`asyncpg.exceptions.CardinalityViolationError: ON CONFLICT DO UPDATE command cannot affect row a
second time`. `[VERIFIED: measured]` — reproduced against real Postgres 18.

**Why it cannot happen here, and why that is load-bearing:** `normalize_payload` returns rows
keyed by a dict on `(metric, source_name, local_day)`, so duplicates are structurally impossible.
This is a second, independent reason the whole-file aggregation in Pattern 2 is mandatory rather
than an optimization.

**How to avoid:** never build the chunk list from anything but `NormalizeResult.rows`. If a future
edit ever concatenates two `NormalizeResult`s before writing, this error is the symptom.

### Pitfall 6: ruff `S314` blocks `ET.iterparse` — and the recommended fix is worse

**What goes wrong:** `pyproject.toml` selects ruff rule set `S` (bandit). Confirmed by running
ruff against a probe file: `[VERIFIED: measured]`

```
S314 Using `xml` to parse untrusted data is known to be vulnerable to XML attacks;
     use `defusedxml` equivalents
 --> backend/app/integrations/health_auto_export/_probe_ruff.py:7:10
```

Pre-commit runs ruff, so this blocks the commit.

**Why the suggested fix is a poor trade:** `defusedxml` **does** work here (measured: 2.8 s,
16.6 MB, all 438,649 records — the DOCTYPE does not trip it). But its last release is
**2021-03-08**, and CLAUDE.md's "What NOT to Use" table rejects `python-jose` explicitly for being
"effectively unmaintained (last release May 2025)". Adding a five-year-stale dependency to protect
against XML-bomb attacks on **a file the user exported from their own phone and stores locally**
inverts the project's own stated standard for no security benefit.

**Recommended:** stdlib `ET.iterparse` with a scoped `# noqa: S314` carrying a threat-model
justification in the codebase's established comment style — the input is a local, user-supplied
file, never network input, and the parse never resolves external entities. Document that a
network-sourced XML path would require revisiting this.

**Alternative, if the planner prefers zero `noqa`:** `defusedxml==0.7.1` is verified working —
record the staleness trade explicitly in the plan.

### Pitfall 7: `Numeric(14, 4)` silently rounds 9-decimal-place values

**What goes wrong:** raw HealthKit values carry up to **9 decimal places** (e.g. prorated
`flights_climbed` fragments). `HealthDailyMetric.value` is `Numeric(14, 4)`. `[VERIFIED: measured]`

**Why it is acceptable:** the webhook path already rounds identically, so the two paths stay
consistent — which is the actual requirement. Overflow is not a risk: the largest aggregated daily
value in the whole file is `basal_energy_burned = 4,787.73`, against a column limit of
9,999,999,999.9999. `[VERIFIED: measured]`

**Action:** none. Documented so it is not rediscovered as a bug.

## Code Examples

### The stream loop (verified shape)

```python
# Source: probe script run against the real export.xml, 2026-09-03.
# Measured: 3.5 s, 66.8 MB peak RSS, 230,395 in-scope datapoints, 8,077 rows.
from xml.etree import ElementTree as ET

RECORD = "Record"
SKIP_AND_COUNT = {"Workout", "ActivitySummary"}

it = ET.iterparse(path, events=("start", "end"))  # noqa: S314 — local user file, no entities
_, root = next(it)

for event, elem in it:
    if event != "end":
        continue
    tag = elem.tag
    if tag == RECORD:
        hk_type = elem.get("type", "")
        if hk_type == HK_BODY_MASS:
            skipped_body_mass += 1
        elif (wire := HK_TO_WIRE.get(hk_type)) is not None:
            bucket = by_metric[wire]
            bucket["units"] = elem.get("unit", "")
            bucket["data"].append({
                "qty": elem.get("value"),        # raw str -> Decimal by the wire model
                "date": elem.get("startDate"),   # raw str -> parse_hae_datetime downstream
                "source": elem.get("sourceName"),
            })
        else:
            unrecognized_types[hk_type] += 1
    elif tag in SKIP_AND_COUNT:
        skipped[tag] += 1
    elem.clear()
    root.clear()      # BOTH clears — see Pattern 1
```

### Handing off to Phase 8, unchanged

```python
# Source: verified end-to-end against the real file. Produces byte-identical rows
# to the webhook path because it IS the webhook path.
payload = HAEPayload.model_validate({
    "data": {
        "metrics": [
            {"name": name, "units": b["units"], "data": b["data"]}
            for name, b in by_metric.items()
        ]
    }
})
result = normalize_payload(payload, tz=tz)   # tz from users.timezone, never a constant
# result.rows           -> 8,077 NormalizedRow
# result.datapoints_seen    -> 230,395
# result.datapoints_dropped -> 209   (all Hevy active_energy)
# result.kinds_present      -> {'activity', 'nutrition'}
```

### Advancing freshness (D-06 completion, same transaction as the rows)

```python
# Source: ingest.py::ingest_payload lines 271-287, reused verbatim.
now = utc_now()
for kind in sorted(result.kinds_present):
    resource = _KIND_TO_RESOURCE[kind]   # 'activity' | 'nutrition'
    await ensure_sync_state(
        session, user_id=user_id, provider=PROVIDER_APPLE_HEALTH, resource=resource
    )
    await complete_sync(
        session, user_id=user_id, provider=PROVIDER_APPLE_HEALTH,
        resource=resource, last_synced_at=now,
    )
await session.commit()
```

**Both** resources will be advanced — the file contains accepted metrics of both kinds
(`kinds_present == {'activity', 'nutrition'}`, verified). `[VERIFIED: measured]`

**One judgement call for the planner:** `complete_sync` sets `last_synced_at = now`, which after
the backfill claims Apple Health is fresh as of *the backfill run*, even though the newest
imported day is 2026-08-26. If the webhook is already live and more recent, advancing is harmless.
If the backfill runs before the webhook has delivered anything, this would report stale data as
fresh. Recommend advancing only when the run actually wrote rows, and consider whether a
dry-run must never advance it (it must not).

## Measured facts about the real file

`[VERIFIED: export.xml]` — all figures produced by commands run against
`/Volumes/…/BRETT/export.xml` on 2026-09-03.

| Property | Value |
|---|---|
| Size | **191,257,897 bytes** = 191.3 MB (decimal) = **182.4 MiB** |
| `HealthKit Export Version` | 14 |
| `locale` | `en_ID` |
| `ExportDate` | `2026-08-26 10:09:33 +0700` |
| Root element | `<HealthData locale="en_ID">` with an internal DTD subset (`<!DOCTYPE HealthData [ … ]>`) |
| `<Record>` | 438,649 |
| `<MetadataEntry>` | 34,860 (children of `Record`/`Workout`) |
| `<ActivitySummary>` | 1,443 |
| `<Workout>` | 224 (218 `sourceName="Hevy"`) |
| `<WorkoutStatistics>` | 224 (children of `Workout`) |
| `<Correlation>`, `<ClinicalRecord>`, `<Audiogram>`, `<VisionPrescription>`, `<WorkoutRoute>` | **0** — declared in the DTD, absent from the data |
| `Record` attribute order | `type`, `sourceName`, `sourceVersion`, `device`(opt), `unit`, `creationDate`, `startDate`, `endDate`, `value` |
| `startDate` format | `%Y-%m-%d %H:%M:%S %z` — **all 230,395 in-scope values exactly 25 chars**, 100% parsed by `parse_hae_datetime` |

**The 182-vs-191 MB discrepancy is resolved:** both are correct. PITFALLS.md says 182 (MiB);
ROADMAP says 191 (MB decimal). Same file.

### Simulation output (real modules, real file)

```
elapsed=3.5s  peak_rss=66.8 MB
seen=230395 dropped=209 (hevy=209) unrecognized_records=208175
skipped: Workout=224 BodyMass=79 ActivitySummary=1443
ROWS TO WRITE = 8077   (samples aggregated = 230186)
accounting identity holds: True
date range: 2022-03-10 .. 2026-08-26  (1631 distinct local days)
```

Note the accounting identity `sum(sample_count) == datapoints_seen - datapoints_dropped` — the
invariant Phase 8 pins with a test — **holds on the real file**.

| Metric | Rows | | Metric | Rows |
|---|---:|---|---|---:|
| `step_count` | 1,699 | | `dietary_energy` | 54 |
| `walking_running_distance` | 1,699 | | `protein` | 54 |
| `basal_energy_burned` | 1,592 | | `total_fat` | 54 |
| `active_energy` | 1,501 | | `dietary_sugar` | 54 |
| `flights_climbed` | 1,211 | | `carbohydrates` | 53 |
| | | | `fiber` | 53 |
| | | | `sodium` | 53 |

Nutrition is genuinely sparse: **631 records across ~54 days**, 2022-07-10 → 2026-08-26. The user
logged food on roughly 54 days in 4.5 years. Worth flagging to the planner so a Phase 13 nutrition
trend is not built expecting dense history.

| Rows by `source_name` | |
|---|---:|
| `Vegant’s iPhone` | 6,561 |
| `V’s iPhone` | 1,138 |
| `Foodvisor` | 368 |
| `Built With Science` | 7 |
| `Gymverse` | 2 |
| `Zing` | 1 |

### Data quality audit — clean

```
parse failures: bad_value=0 bad_date=0 missing_value=0 missing_sourceName=0
negative values: 0    max decimal places in a raw value: 9
distinct startDate string lengths: {25: 230395}
```

Zero defects across 230,395 in-scope records. D-07's log-and-continue path and the per-row write
fallback are insurance, not expected traffic. `[VERIFIED: measured]`

## Decision D-A: which reuse shape

The CONTEXT left this to Claude's discretion. Both variants were built and measured against the
real file. `[VERIFIED: measured]`

| | Literal `HAEPayload` + `normalize_payload` | Purpose-built streaming aggregator |
|---|---|---|
| Rows produced | **8,077** | **8,077** |
| `datapoints_seen` / `dropped` | 230,395 / 209 | 230,395 / 209 |
| Wall time | 4.5 s | 3.5 s |
| Peak RSS | **310.9 MB** | **66.8 MB** |
| Divergence risk vs. webhook | **zero — same function** | must re-derive allowlist, conversion, exclusion, bucketing, aggregation |
| `multi_point_day` warnings | 7,403 | 7,403 (if the same warning is reproduced) |

**Output is identical.** The choice is memory-vs-guarantee.

**Recommendation: the literal `HAEPayload` variant.** 311 MB on a local developer machine is
irrelevant (D-01 puts this on the user's own laptop, not on Cloud Run), and it buys
correctness-by-construction for the one constraint CONTEXT explicitly marked non-negotiable —
"both paths must produce byte-identical rows." The aggregator variant re-implements five pieces of
Phase 8 logic and would need five new tests to prove equivalence that the literal variant gets for
free.

**Required mitigation:** suppress/contextualize the 7,403 `multi_point_day` warnings (Pitfall 4).

**Reconsider only if** peak RSS becomes a real constraint (it is not, under D-01) — in which case
the aggregator variant must be accompanied by a differential test asserting both paths produce
identical `NormalizedRow` sets for a shared fixture.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `export.xml` | The entire phase | ✓ | 191,257,897 bytes, ExportDate 2026-08-26 | none needed |
| Python | CLI runtime | ✓ | 3.13 (`.python-version`), `.venv` present | — |
| `xml.etree.ElementTree` | Streaming parse | ✓ | stdlib | `defusedxml` (verified working) |
| Existing `.venv` with project deps | Running the CLI | ✓ | verified: real modules imported and ran | `uv sync --group dev` |
| Local Postgres (tests) | Integration tests | ✓ | `brett-db-1`, postgres:18-alpine, healthy, :5432 | `testcontainers[postgres]` already a dev dep |
| Production Neon `DATABASE_URL` | The real run (D-02) | ⚠ not verified in this session | — | Supplied by the user at invocation; local `.env` points at localhost by design |
| `ruff` / `mypy` / `pytest` | Gates | ✓ | ruff 0.16.4, mypy 2.3.1, pytest 9.1.1 | — |

**Missing dependencies with no fallback:** none.

**Not verified in this session:** the production Neon connection and its network latency. This
directly drives the write-phase runtime estimate (12 min vs. 90 min) and therefore D-05's
heartbeat design. Recommend the plan's first task measure it (`SELECT 1` round-trip timing) rather
than assume.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 + pytest-asyncio 1.4.0 (`asyncio_mode = "auto"`) |
| Config file | `pyproject.toml` → `[tool.pytest.ini_options]`, `testpaths = ["backend/tests"]`, `pythonpath = ["backend"]` |
| Quick run command | `uv run pytest -m 'not integration' -q` |
| Full suite command | `uv run pytest -q` |
| Integration marker | `integration: test requires a live Postgres container` |

### Phase Requirements → Test Map

| Req | Behavior | Test Type | Automated Command | File Exists? |
|---|---|---|---|---|
| HEALTH-10 | Every `METRIC_REGISTRY` key is reachable from exactly one HealthKit identifier, and vice versa | unit | `pytest backend/tests/test_health_auto_export_backfill.py::test_mapping_is_total -x` | ❌ Wave 0 |
| HEALTH-10 | The 5 naming traps map correctly (`DietaryFatTotal`→`total_fat`, `DietaryProtein`→`protein`, `DietarySugar`→`dietary_sugar`, `DietaryEnergyConsumed`→`dietary_energy`, `DistanceWalkingRunning`→`walking_running_distance`) | unit | `…::test_naming_traps -x` | ❌ Wave 0 |
| HEALTH-10 / SC#4 | `Workout`, `WorkoutStatistics`, `ActivitySummary`, `BodyMass` never produce a row | unit | `…::test_non_record_elements_never_ingested -x` | ❌ Wave 0 |
| HEALTH-10 / SC#4 | `sourceName="Hevy"` `ActiveEnergyBurned` is excluded and counted | unit | `…::test_hevy_active_energy_excluded -x` | ❌ Wave 0 |
| SC#3 | Backfill `source_name` matches the live webhook's `source` for the same device (guards Pitfall 2) | unit | `…::test_source_name_matches_device_capture -x` | ❌ Wave 0 |
| SC#3 | Backfill then webhook on the same day → exactly one row; value replaced not summed | integration | `pytest -m integration backend/tests/test_backfill_idempotency.py -x` | ❌ Wave 0 |
| SC#1 | Real 191 MB file parses within a memory ceiling | integration (opt-in) | `pytest -m realfile backend/tests/test_backfill_real_export.py -x` | ❌ Wave 0 |
| D-03 | `--dry-run` writes zero rows and still prints the full summary | unit + integration | `…::test_dry_run_writes_nothing -x` | ❌ Wave 0 |
| D-07 | A malformed `Record` is skipped, the run completes, the counter increments | unit | `…::test_malformed_record_does_not_abort -x` | ❌ Wave 0 |
| CLAUDE.md | `cli.py` still does not import `registry`/`schemas` | unit (existing) | `pytest backend/tests/test_health_auto_export_isolation.py -x` | ✅ exists |
| CLAUDE.md | `configure_logging` still precedes every log/engine in `cli.py` | unit (existing) | `pytest backend/tests/test_cli.py::test_configure_logging_precedes_every_log_call -x` | ✅ exists |

### Sampling Rate

- **Per task commit:** `uv run pytest -m 'not integration' -q` (fast, no container)
- **Per wave merge:** `uv run pytest -q` (includes testcontainers Postgres)
- **Phase gate:** full suite green **plus** one `--dry-run` against the real `export.xml`, whose
  printed summary is compared against this document's measured figures (8,077 rows; 209 Hevy
  exclusions; 224 workouts / 79 body-mass skipped; 2022-03-10 → 2026-08-26).

### Wave 0 Gaps

- [ ] `backend/tests/test_health_auto_export_backfill.py` — unit coverage for the mapping, the
      element filter, the Hevy exclusion, dry-run, and D-07 (HEALTH-10, SC#3, SC#4)
- [ ] `backend/tests/fixtures/hae/export_sample.xml` — a small synthetic Apple Health XML fixture.
      **Must include** the DOCTYPE, a `<Workout>` with a nested `<WorkoutStatistics
      type="HKQuantityTypeIdentifierActiveEnergyBurned">` (Pitfall 3), a Hevy-sourced
      `ActiveEnergyBurned` `Record`, a `BodyMass` `Record`, both U+2019 device names, and an
      unrecognized type. **Synthetic quantities only** — the real file is gitignored health data
      and no real measured value may be committed (Phase 8 fixture precedent).
- [ ] `backend/tests/test_backfill_idempotency.py` — integration, marked `integration`; the
      backfill-then-webhook-same-day case that proves SC#3
- [ ] `backend/tests/test_backfill_real_export.py` — opt-in, skipped unless `export.xml` is
      present; asserts SC#1 against the actual file. Needs a new `realfile` marker registered in
      `pyproject.toml`, since the file is gitignored and CI will not have it.

## Security Domain

`security_enforcement` is not disabled in `.planning/config.json`, so this section applies.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|------------------|
| V2 Authentication | no | Local CLI, no network listener. Auth is the OS session + the DB credential. |
| V3 Session Management | no | No sessions. |
| V4 Access Control | **yes** | `user_id` keyword-only with no default on every write, exactly as `upsert_health_metric` already enforces. Never read from the file — `export.xml` cannot supply one and must not be able to. |
| V5 Input Validation | **yes** | `HAEPayload`/`HAEDataPoint` pydantic models (`hide_input_in_errors=True`); `to_canonical` rejects unknown units per-datapoint; `parse_hae_datetime` rejects naive/unknown timestamps; element-tag allowlist. |
| V6 Cryptography | no | No crypto in this path. TLS to Neon is handled by the driver/connection string. |
| V7 Error Handling & Logging | **yes** | Phase 8's rule extends verbatim: metric name, unit, `local_day`, `source_name`, counts and exception **class names** are loggable; a measured quantity never is. `str(exc)` is banned in `cli.py` by an existing test. |
| V12 Files & Resources | **yes** | XML external-entity handling — see below. Path comes from an operator argument, not from network input. |
| V14 Configuration | **yes** | D-02: production `DATABASE_URL` via inline env var for one shell session. No new secret, no `.env.production` on disk. |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation | Applies here? |
|---|---|---|---|
| XXE / external entity expansion | Information Disclosure | `defusedxml`, or established trust in the input | **Low risk, documented.** The file is user-exported and local. Its DTD declares only `ELEMENT`/`ATTLIST` — **zero `ENTITY` declarations** `[VERIFIED: export.xml]`. Python's expat does not resolve external entities by default. Mitigation = documented `noqa` (Pitfall 6). |
| Billion-laughs / quadratic blowup | DoS | Entity limits | Not applicable — no entities, and a self-inflicted DoS on a manual local command is not a threat. |
| Health data in logs / stdout | Information Disclosure | Counts-and-names-only logging rule | **Applies.** D-06's summary must report counts, metric names, units and dates — never a measured quantity. |
| Production credential persisted to disk | Information Disclosure | Inline env var, one shell session | **Applies** — already resolved by D-02. |
| Cross-tenant write | Elevation of Privilege | Server-resolved `user_id`, keyword-only, no default | **Applies.** Reuse Phase 8's signature exactly. |
| Partial-write corruption | Tampering | Single transaction + replace-semantics upsert + per-row fallback | **Applies** — CLAUDE.md data-integrity constraint. |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|---|---|---|
| A1 | Production Neon round-trip latency is 30–230 ms, making the SAVEPOINT-per-row path 12–90 min for 8,077 rows | Pattern 3 | If latency is very low, the batched writer is an unneeded optimization (still harmless). If very high, even the batched path needs a progress indicator. **Measure before planning the heartbeat.** |
| A2 | The production `health_daily_metrics` currently holds only ~2026-09-02-onward webhook rows, so backfill/webhook day overlap is ≈ 0 | Runtime State Inventory | If Health Auto Export backfilled historical days on first connect, overlap is larger and SC#3 gets exercised for real rather than vacuously. `--dry-run` plus one `SELECT min/max(local_day)` settles it before the real run. |
| A3 | The user will not rename their phone between now and the backfill run | Pitfall 2 | A rename desynchronizes backfill and webhook `source_name`, silently producing two rows per overlapping metric-day. The recommended pinning test detects it; nothing else would. |
| A4 | `chunk = 500` is a reasonable multi-row upsert size | Pattern 3 | Purely a tuning constant; 8,077 rows is small enough that anything from 100 to 2,000 works. No correctness impact. |

Everything else in this document is `[VERIFIED: export.xml]`, `[VERIFIED: measured]`,
`[VERIFIED: codebase]`, or `[VERIFIED: pypi.org]`.

## Open Questions

### 1. `Gymverse` and `Zing` write active energy too (3 records)

- **What we know:** `ActiveEnergyBurned` arrives from `Gymverse` (2 records) and `Zing` (1
  record) in addition to Hevy. `[VERIFIED: export.xml]` These are fitness apps of the same class
  as Hevy — apps that write a workout's estimated energy back into HealthKit.
- **What's unclear:** whether they should be excluded. HEALTH-08 names Hevy specifically, and its
  rationale is "BRETT already holds this data at higher fidelity" — which is true of Hevy and
  **false** of Gymverse/Zing, whose workouts BRETT does not hold at all.
- **Recommendation:** **ingest them.** They represent real energy expenditure not otherwise
  recorded, the volume is negligible (3 of 45,182 records), and widening `_HEVY_SOURCE_ALIASES`
  beyond Hevy would break the constant's documented meaning and its Phase 8 tests. Note it in the
  plan so it is a decision rather than an oversight.

### 2. `sample_count` semantics diverge between the two paths

- **What we know:** the backfill writes `sample_count` = number of raw HealthKit samples (>1 for
  91.7% of rows); the webhook writes `sample_count = 1` (HAE daily aggregation, confirmed in
  `device_capture.json` — one datapoint per metric per day). `[VERIFIED: measured]`
- **What's unclear:** Phase 8 documented a *falling* `sample_count` on re-sync as "the cheapest
  available detector for a batch-split data loss". After the backfill, a webhook delivery covering
  a backfilled day drops `sample_count` from N to 1 — a false positive for that detector.
- **Recommendation:** accept it and document it. `sample_count` is diagnostic-only, feeds no
  analytics, and the alternative (making the backfill lie about its sample count) is worse. Add a
  note to `docs/health-auto-export-setup.md`'s diagnostics section so the false positive does not
  cost a future debugging session.

### 3. Does `get_settings()` demand `HEVY_API_KEY` for a command that never calls Hevy?

- **What we know:** `cli.py::main` calls `get_settings()` before dispatch, and `Settings` is
  documented as failing fast on missing configuration. `sync-status` and `mapping-gaps` are
  explicitly described as working without `HEVY_API_KEY` — but they take the same bootstrap path.
  `[VERIFIED: codebase]`
- **What's unclear:** not read in this pass — `app/config.py` was not inspected in full.
- **Recommendation:** the planner should confirm in one read of `app/config.py` that
  `backfill-apple-health` can bootstrap with only `DATABASE_URL` set. If `HEVY_API_KEY` is
  mandatory at settings level, D-02's clean one-liner becomes a two-variable invocation — a
  documentation detail, not a design change.

### 4. Should `complete_sync` advance on a backfill that imports only historical days?

- **What we know:** `complete_sync(last_synced_at=utc_now())` marks the resource fresh as of the
  run, not as of the newest imported day (2026-08-26).
- **What's unclear:** whether that is desirable when the backfill runs before any webhook delivery.
- **Recommendation:** advance only on a real run that wrote ≥1 row of that kind; **never** on
  `--dry-run`. If the webhook is already live (it is), its own more recent timestamp makes this
  moot in practice.

## State of the Art — corrections to prior BRETT research

| Prior claim | Source | Corrected finding | Impact |
|---|---|---|---|
| "`ElementTree.parse()` … routinely 1.5–2 GB of Python objects" | PITFALLS.md #6; ROADMAP planning note | **Measured 316.5 MB** for the full DOM on this file `[VERIFIED: measured]` | The CLI-not-web-service decision (D-01) is still right — 32 MiB HTTP cap, separation of concerns — but not because of a 2 GB OOM. Do not repeat the figure in the plan. |
| "the file streams (likely several minutes for 191 MB)" | CONTEXT D-05 | **Parse + normalize = 3.5–4.5 s.** The slow phase is the network write (~24,231 round trips unbatched) `[VERIFIED: measured]` | **D-05's heartbeat belongs on the write loop.** A parse heartbeat would print once. Recommend: heartbeat every ~500 written rows (≈16 lines), plus one line at parse completion. |
| "The webhook sends `"iPhone"`; `export.xml` says `"Vegant's iPhone"`" | `normalize.py` module docstring, Pitfall N-3 | **Stale.** Live-verified `device_capture.json` (2026-09-03) shows the webhook sends **`V's iPhone`** — byte-identical to `export.xml`'s current-phone value `[VERIFIED: codebase]` | This is what makes SC#3 achievable. Worth correcting the docstring and pinning with a test. |
| "218 of 221 [workouts] are Hevy re-exports" | REQUIREMENTS.md, `health.py` docstring | **218 of 224.** 221 is the count of `HKWorkoutActivityTypeTraditionalStrengthTraining` specifically; 3 more are `HKWorkoutActivityTypeOther` `[VERIFIED: export.xml]` | D-04's example summary text ("workouts skipped: 221") should say **224**. |
| "`export.xml` is 182 MB" vs. "the real 191 MB `export.xml`" | PITFALLS.md #6 vs. ROADMAP | Both correct: **191,257,897 bytes** = 191.3 MB decimal = 182.4 MiB `[VERIFIED: export.xml]` | Cosmetic; use one unit consistently in the plan. |
| Hevy body-mass write-back "stops in May 2025", suggesting Hevy stopped writing to HealthKit generally | STATE.md, 2026-09-03 resolution note | Consistent with the file: all 209 Hevy `ActiveEnergyBurned` records exist, and the exclusion predicate remains necessary for exactly the pre-2025 period this phase imports `[VERIFIED: export.xml]` | Confirms STATE.md's reasoning. `_HEVY_SOURCE_ALIASES` needs no change. |

**Also confirmed unchanged (no correction needed):** the 209 Hevy `ActiveEnergyBurned` records;
52 of 79 Hevy `BodyMass`; 8 of 8 Hevy `WaistCircumference`; the U+2019 apostrophe in both device
names; the 366,339 / 70,900 device-name split; `sourceName` vocabulary; `date_trunc`-free Python
day bucketing.

**Newly discovered, not in any prior research:** `<WorkoutStatistics>` nested inside `<Workout>`
carrying `type="HKQuantityTypeIdentifierActiveEnergyBurned"` (Pitfall 3); the 343 dual-phone
metric-day overlaps; ruff `S314` blocking `ET.iterparse` (Pitfall 6); the 3.0-round-trips-per-row
write cost; the 7,403 spurious `multi_point_day` warnings (Pitfall 4).

## Sources

### Primary (HIGH confidence)

- **`/Volumes/…/BRETT/export.xml`** — the actual 191,257,897-byte file, queried directly on
  2026-09-03 with `grep`/`awk`/`sed`. Source of every element count, type/unit pair, `sourceName`
  distribution, attribute order, date format, and file-ordering finding.
- **Probe scripts executed against the real file and the real Phase 8 modules** (2026-09-03) —
  `iterparse` memory variants, `ET.parse` DOM size, full end-to-end simulation importing
  `app.integrations.health_auto_export.{normalize,registry,schemas}` and `app.core.time`, value
  range/parse-failure audit, `HAEPayload` reuse comparison.
- **Benchmarks against live PostgreSQL 18** (`brett-db-1`, docker compose) — SAVEPOINT-per-row vs.
  batched upsert round-trip counts; `CardinalityViolationError` reproduction.
- **Codebase, read in full** — `normalize.py`, `registry.py`, `ingest.py`, `schemas.py`,
  `errors.py`, `__init__.py`, `cli.py`, `db/models/health.py`, `db/repositories/sync_state.py`,
  `core/time.py`, `api/routes/health_ingest.py`, `tests/conftest.py`,
  `tests/test_health_auto_export_isolation.py`, `tests/test_cli.py`, `pyproject.toml`,
  `docker-compose.yml`.
- **`backend/tests/fixtures/hae/device_capture.json`** — the 2026-09-03 live-verified webhook
  source vocabulary. Decisive for Pitfall 2.
- **`ruff 0.16.4` run against a probe module** — `S314` confirmation with exact message.
- **PyPI JSON API** (`pypi.org/pypi/defusedxml/json`, queried 2026-09-03) — defusedxml 0.7.1,
  uploaded 2021-03-08, Development Status 5.

### Secondary (MEDIUM confidence)

- `.planning/research/PITFALLS.md` §6 and §9 — §6's streaming/CLI guidance confirmed; its
  1.5–2 GB figure corrected. §9 confirmed as **not** this phase's concern (this phase writes only
  to `health_daily_metrics` and deliberately keeps `apple_health` out of `body_measurements`,
  which keeps Pitfall 9's alphabetical-precedence bug latent).
- `.planning/research/ARCHITECTURE.md`, `FEATURES.md`, `STACK.md`, `SUMMARY.md` — element counts
  and the two-device-name warning independently reproduced against the file.
- `.planning/ROADMAP.md`, `.planning/REQUIREMENTS.md`, `.planning/STATE.md`, `CLAUDE.md`.

### Tertiary (LOW confidence)

- None. No claim in this document rests on an unverified web search. Apple's HealthKit export
  schema was read from the **file's own embedded DTD** rather than from third-party documentation.

## Metadata

**Confidence breakdown:**

| Area | Level | Reason |
|------|-------|--------|
| Standard stack | **HIGH** | Stdlib-only; both candidate parsers executed against the real file. |
| HealthKit → wire mapping | **HIGH** | All 12 entries verified against the real file, with unit strings; totality asserted programmatically. |
| Memory / performance | **HIGH** | Four parse strategies and a full pipeline simulation measured on the actual 191 MB file. |
| Hevy exclusion (SC#4) | **HIGH** | 269/269 `Record`s and 218/224 `Workout`s enumerated; `is_hevy_sourced` verified sufficient unchanged. |
| Idempotency / SC#3 | **MEDIUM-HIGH** | Natural-key logic verified and both source vocabularies confirmed matching. Downgraded from HIGH only because the production table's current contents were not read (A2) and the match depends on the phone not being renamed (A3). |
| Write-path performance | **MEDIUM** | Round trips per row measured exactly (3.0); the wall-clock extrapolation depends on unmeasured Neon latency (A1). |
| Pitfalls | **HIGH** | Each reproduced: `S314` from ruff, `CardinalityViolationError` from Postgres, `WorkoutStatistics` from the file, 7,403 warnings from the simulation. |
| Test strategy | **MEDIUM-HIGH** | Framework and existing guards read directly; the proposed new tests are designed, not yet written. |

**Research date:** 2026-09-03
**Valid until:** 2026-12-03 (90 days). Unusually long because the primary source is a static
local file and the dependencies are stdlib. **Invalidate early if:** the user re-exports
`export.xml` (every count changes), renames their phone (Pitfall 2 / A3), or Phase 8's
`normalize.py` / `registry.py` / `health_daily_metrics` schema changes.
