# Phase 9: Historical Apple Health Backfill - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-03
**Phase:** 9-historical-apple-health-backfill
**Areas discussed:** Execution environment, Dry-run/safety, Output & progress reporting, Error recovery

---

## Execution environment

| Option | Description | Selected |
|--------|-------------|----------|
| Local CLI, prod DB | Run on the user's machine, pointed at production Neon DB. export.xml already lives locally. | ✓ |
| One-off Cloud Run Job | Upload export.xml to Cloud Storage, run a temporary raised-memory Cloud Run Job. | |

**User's choice:** Local CLI, prod DB
**Notes:** No upload step, no extra Cloud Run Job resource to define/maintain for a command run once or twice.

| Option | Description | Selected |
|--------|-------------|----------|
| Env var override at invocation | e.g. `DATABASE_URL=<prod-url> uv run python -m app.cli ...` | ✓ |
| Separate `.env.production` file | A gitignored file loaded explicitly via a flag | |
| You decide / Claude's discretion | Not important enough to lock | |

**User's choice:** Env var override at invocation
**Notes:** No new config file; production credential doesn't linger on disk.

---

## Dry-run / safety

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, `--dry-run` required | Parse + aggregate + report, no writes | ✓ |
| No, just run it for real | Idempotent upsert makes re-runs safe anyway | |

**User's choice:** Yes, `--dry-run` required
**Notes:** Cheap insurance before committing 4.5 years of writes to production.

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, report workout/body-mass skip counts | One extra summary line, no new table | ✓ |
| No, not needed | Trust the already-tested exclusion logic | |

**User's choice:** Yes, report the count
**Notes:** Visual confirmation of success criterion #4 without a dedicated coverage cross-check table (consistent with Phase 8's D-02).

---

## Output & progress reporting

| Option | Description | Selected |
|--------|-------------|----------|
| Periodic heartbeat + final summary | A line every N thousand records, then full summary | ✓ |
| Silent until done, final summary only | Matches `sync-status`'s minimal style | |
| You decide / Claude's discretion | No strong preference | |

**User's choice:** Periodic heartbeat + final summary
**Notes:** Multi-minute streaming parse with zero output during the run was explicitly rejected — no signal the process hasn't hung.

---

## Error recovery

| Option | Description | Selected |
|--------|-------------|----------|
| Log, skip, continue | Same philosophy as Phase 8's D-04 | ✓ |
| Abort the whole run | Stricter, but risks losing all prior parse progress | |

**User's choice:** Log, skip, continue
**Notes:** Aborting mid-parse on a one-time multi-minute import would discard everything over a single bad `Record`.

---

## Claude's Discretion

- Heartbeat interval/granularity (record-count vs. time-based)
- Literal `HAEPayload` reuse vs. calling shared building blocks directly from an XML aggregator (constraint: byte-identical output rows either way)
- HealthKit type-identifier → `METRIC_REGISTRY` name mapping (research task)
- Per-row database-write failure handling during the write pass (reuse `ingest.py`'s SAVEPOINT-per-row pattern unless research says otherwise)
- Exact CLI flag/argument names and defaults
- Whether to warn-log unmapped HealthKit type identifiers or only count them silently

## Deferred Ideas

None — discussion stayed within phase scope.
