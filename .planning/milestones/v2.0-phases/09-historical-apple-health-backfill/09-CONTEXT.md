# Phase 9: Historical Apple Health Backfill - Context

**Gathered:** 2026-09-03
**Status:** Ready for planning

<domain>
## Phase Boundary

A one-time CLI command imports 4.5 years of Apple Health activity and nutrition history
(2022-03 through the export date) from the user's existing `export.xml` (191 MB), through the
same normalizer and upsert path Phase 8's live webhook uses — so a day covered by both the
backfill and the ongoing webhook holds exactly one value per metric, never two, and no
Hevy-originated workout or body-mass row from the export ever reaches BRETT.

This phase does NOT include: ongoing sync (Phase 8, already live), health/nutrition analytics
or MCP tools (Phase 13), max-weight strength signal, body-measurement history beyond what
Phase 8's schema already enables, or training programs. Those are separate phases.

</domain>

<decisions>
## Implementation Decisions

### Execution environment
- **D-01:** Run the backfill as a local CLI subcommand (`app/cli.py`, alongside `sync-hevy`),
  executed on the user's own machine directly against the production Neon database — not a
  one-off Cloud Run Job. `export.xml` already lives locally at the repo root (gitignored); a
  Cloud Run Job would require uploading it to Cloud Storage first for no real benefit on a
  command that runs once, maybe twice.
- **D-02:** The production `DATABASE_URL` is supplied via an environment variable override at
  invocation time (e.g. `DATABASE_URL=<prod-url> uv run python -m app.cli backfill-apple-health
  export.xml`), not a separate `.env.production` file. No new config file, no production
  credential lingering on disk longer than the shell session.

### Dry-run / safety
- **D-03:** The CLI supports a required `--dry-run` mode: parses and aggregates the entire file
  and prints the full summary (see D-05/D-06 below) without writing anything to the database.
  Cheap insurance before committing 4.5 years of writes to production on a command that has no
  practical rollback.
- **D-04:** Both dry-run and real-run summaries report a count of skipped `Workout` and
  `BodyMass` XML elements (e.g. "workouts skipped: 221, body-mass skipped: 79"), so success
  criterion #4 (no Hevy-originated workout/body-mass row enters BRETT) is visually confirmable
  without building a dedicated coverage cross-check table — consistent with Phase 8's D-02
  decision not to build one.

### Output & progress reporting
- **D-05:** While the file streams (likely several minutes for 191 MB), print a periodic
  heartbeat line (e.g. every N thousand XML records processed) so the run is visibly alive,
  not silent-until-done. Interval is Claude's discretion at planning time.
- **D-06:** On completion (dry-run or real), print one final summary block covering: rows
  written/would-write per metric, the date range actually covered, datapoints dropped and
  metrics-unrecognized counts (mirroring `NormalizeResult`'s existing counters), the
  Hevy-exclusion count (datapoints excluded via `is_hevy_sourced`), and the D-04 workout/
  body-mass skip counts. Style mirrors `sync-status`'s plain `print()`-based operator output,
  not a log line.

### Error recovery
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

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` §"Apple Health Integration" — HEALTH-10, this phase's sole
  requirement
- `.planning/ROADMAP.md` §"Phase 9: Historical Apple Health Backfill" — goal, success criteria
  (191 MB real-file memory budget, queryable 2022-03→export-date history, idempotent overlap
  with the live webhook, zero Hevy-originated workout/body-mass rows), and the three planning
  notes (streaming `iterparse`, CLI-not-HTTP, reuse Phase 8's normalizer/upsert verbatim)
- `.planning/PROJECT.md` §Active — "One-time historical Apple Health backfill from `export.xml`"
  bullet, and §Context — "User already has a manual Apple Health export (`export.xml`,
  `export_cda.xml`, gitignored/untracked at the repo root)"

### Research (2026-09-02) — read in full, not skimmed
- `.planning/research/PITFALLS.md` §"Pitfall 6: Parsing a 182 MB `export.xml` in-process OOMs
  the service" — the file's real measured size (182 MB per this doc, 191 MB per ROADMAP —
  confirm the live figure at research time), the `iterparse`+`elem.clear()` streaming
  requirement, the "run as `app.cli`, not through the web service" mandate, and the
  same-upsert-path idempotency requirement
- `.planning/research/PITFALLS.md` §"Pitfall 9" — the `_dedupe_by_day` source-precedence
  ordering constraint (Apple Health as the activator, not this phase's concern directly, but
  relevant background since this phase writes to `health_daily_metrics`, not
  `body_measurements`)
- `.planning/research/ARCHITECTURE.md` — `health_daily_metrics` schema detail (natural key
  including `source_name`), the Apple-Health-workouts exclusion rationale (D-02)
- `.planning/research/SUMMARY.md` — phase-ordering rationale, stack confirmation

### Existing code to reuse verbatim
- `backend/app/integrations/health_auto_export/normalize.py` — `normalize_payload`,
  `is_hevy_sourced`, `_HEVY_SOURCE_ALIASES`, `SOURCE_APPLE_HEALTH`, `UNKNOWN_SOURCE_NAME`; its
  own comment at line ~193-195 explicitly anticipates this phase feeding `to_canonical` from a
  raw string parsed out of XML
- `backend/app/integrations/health_auto_export/registry.py` — `METRIC_REGISTRY`, `MetricSpec`,
  `to_canonical` — the canonical-unit conversion this phase's XML values must also pass through
- `backend/app/integrations/health_auto_export/ingest.py` — `upsert_health_metric` (the exact
  `ON CONFLICT` replace-semantics upsert to reuse), `HealthIngestResult`, the
  SAVEPOINT-per-row pattern in `ingest_payload`
- `backend/app/integrations/health_auto_export/schemas.py` — `HAEPayload`, `HAEMetric`,
  `parse_hae_datetime` — the wire shapes this phase's XML-derived data must ultimately match or
  bypass consistently
- `backend/app/db/models/health.py` — `HealthDailyMetric` model and its natural key; no schema
  change is needed for this phase (table already exists from Phase 8)
- `backend/app/cli.py` — the existing subcommand pattern to extend (`build_parser`,
  bootstrap-order discipline: settings → `configure_logging` → engine, `sync-status`'s
  plain-`print()` operator-output style to mirror for this phase's summary output)
- `backend/app/db/repositories/sync_state.py` — `PROVIDER_APPLE_HEALTH`, `RESOURCE_ACTIVITY`,
  `RESOURCE_NUTRITION`, `complete_sync` — the same freshness bookkeeping the webhook advances,
  which this phase's backfill should also advance on completion

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- The entire Phase 8 ingest pipeline (`normalize.py`, `registry.py`, `ingest.py`) is designed to
  be fed from this phase — `normalize.py` even has a comment anticipating it. Building a
  separate, divergent XML normalizer would violate the ROADMAP's explicit warning about "two
  parsers produce two shapes."
- `cli.py`'s `sync-hevy`/`sync-status`/`mapping-gaps` subcommand pattern, including the
  bootstrap-order discipline (settings → logging → engine) and the plain-`print()` operator
  output style, is the direct template for a new `backfill-apple-health` subcommand.

### Established Patterns
- Provider isolation: Apple Health logic stays inside
  `integrations/health_auto_export/` — an XML-parsing module added for this phase belongs there
  too, not in `app/cli.py` itself (which should stay a thin dispatch layer, per the existing
  Hevy subcommands).
- SAVEPOINT-per-row + named-constraint `ON CONFLICT` upsert is the established idempotency
  mechanism for this table; this phase's write pass should use it unchanged.
- Freshness/sync-state bookkeeping (`sync_state` rows advanced in the same transaction as the
  rows they describe) is the established pattern this phase's completion should also follow.

### Integration Points
- New CLI subcommand in `backend/app/cli.py`, parallel to `sync-hevy`.
- New XML-parsing/aggregation module under
  `backend/app/integrations/health_auto_export/` (exact filename is planning's call).
  No new database table or migration — `health_daily_metrics` already exists.

</code_context>

<specifics>
## Specific Ideas

- The user favors keeping this operationally simple: run it once, locally, against production,
  with a safety net (`--dry-run`) rather than building out infrastructure (Cloud Run Job,
  Cloud Storage upload) for a command that exists to be run once or twice, ever.
- Visibility matters during the run — a multi-minute streaming parse with no output at all was
  explicitly rejected in favor of a heartbeat, and the final summary should be detailed enough
  (per-metric rows, date range, drop/exclusion counts, workout/body-mass skip counts) to serve
  as the user's own confidence check that the exclusion filter worked, given Phase 8 deliberately
  did not build a persisted coverage cross-check table.
- Robustness over strictness carries forward from Phase 8's D-04: never let one bad XML element
  cost the whole run.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope. No new capabilities were proposed; all four
discussed areas (execution environment, dry-run/safety, output/progress, error recovery) are
implementation choices within HEALTH-10's existing boundary.

</deferred>

---

*Phase: 09-historical-apple-health-backfill*
*Context gathered: 2026-09-03*
