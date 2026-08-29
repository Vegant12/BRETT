# Phase 3: Hevy Integration & Normalization - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-08-29
**Phase:** 03-hevy-integration-normalization
**Areas discussed:** Muscle taxonomy & overrides, Body measurements sync, Sync resilience mechanics

---

## Gray Area Selection

Presented 4 candidate areas: Muscle taxonomy & overrides, Hevy credential storage, Body measurements sync, Sync resilience mechanics.

**Selected:** Muscle taxonomy & overrides, Body measurements sync, Sync resilience mechanics
**Not selected:** Hevy credential storage — captured as Claude's Discretion in CONTEXT.md rather than dropped.

---

## Muscle Taxonomy & Overrides

| Option | Description | Selected |
|--------|-------------|----------|
| Standard hypertrophy split (~14-16 groups incl. deltoid split) | Matches how lifters/coaches reason, supports NORM-01's deltoid split | ✓ |
| Coarser (major groups only, ~8) | Simpler but loses required deltoid split | |
| Finer (sub-muscle detail, 20+) | More precise, much more mapping work | |

**User's choice:** Standard hypertrophy split

| Option | Description | Selected |
|--------|-------------|----------|
| Curated Python/seed data in-repo | Hand-maintained, reviewed like code, seeded from Hevy metadata but not re-derived every sync | ✓ |
| Re-derive from Hevy's template metadata every sync | Less maintenance, risk of drift since Hevy's taxonomy lacks delt split | |
| External JSON/YAML fixture file | Reviewable but a second source of truth needing a load step | |

**User's choice:** Curated Python/seed data in-repo

| Option | Description | Selected |
|--------|-------------|----------|
| Sync it, flag as unmapped | Sync never blocks/corrupts on a mapping gap; excluded from analytics until mapped | ✓ |
| Best-effort fuzzy default | Fuzzy-name guess as fallback, flagged low-confidence | |
| Block until mapped | Simpler mental model, risks violating no-corruption guarantee | |

**User's choice:** Sync it, flag as unmapped

| Option | Description | Selected |
|--------|-------------|----------|
| Separate override table | Original mapping untouched; override applied at query time; clean audit trail | ✓ |
| Override columns alongside originals | Simpler query, but two parallel concepts on one table | |

**User's choice:** Separate override table

**Notes:** User selected the recommended option in all four questions — no follow-up needed, moved directly to next area.

---

## Body Measurements Sync

| Option | Description | Selected |
|--------|-------------|----------|
| Weight + whatever Hevy returns | Generic storage for all fields Hevy exposes, no migration needed as Hevy adds fields | ✓ |
| Weight + body fat % only | Narrower, just what BODY-01/02 need today | |
| Weight only | Minimum viable per PROJECT.md | |

**User's choice:** Weight + whatever Hevy returns

| Option | Description | Selected |
|--------|-------------|----------|
| One table, a `source` column | Single body_measurements table, source='hevy'\|'manual', one place to query trends | ✓ |
| Separate tables per source | Cleaner provider separation, doubles schema work later, complicates cross-source queries | |

**User's choice:** One table, a `source` column

| Option | Description | Selected |
|--------|-------------|----------|
| Hevy's own measurement ID if present | Same (user_id, source, external_id) pattern as workouts | ✓ |
| Key on (user_id, source, measured_at date, metric) | Fallback if Hevy has no stable per-entry ID | |

**User's choice:** Hevy's own measurement ID if present (with documented fallback)

**Notes:** User selected the recommended option in all three questions — no follow-up needed, moved directly to next area.

---

## Sync Resilience Mechanics

| Option | Description | Selected |
|--------|-------------|----------|
| Commit per page, track a sync checkpoint | Crash mid-sync leaves prior pages committed, resumes from checkpoint | ✓ |
| Commit per workout | Finer-grained, more DB round-trips | |
| One transaction for the whole sync | Simplest correctness, but restarts from page 1 on late-page failure | |

**User's choice:** Commit per page, track a sync checkpoint

| Option | Description | Selected |
|--------|-------------|----------|
| Events endpoint only | Matches blueprint §7's intended mechanism, simplest | ✓ |
| Events + periodic full reconciliation | Catches missed-event drift at the cost of extra full pulls | |

**User's choice:** Events endpoint only

| Option | Description | Selected |
|--------|-------------|----------|
| Reactive exponential backoff via tenacity | Retry on 429/5xx with jitter, no proactive throttle, pageSize=10 already bounds volume | ✓ |
| Proactive throttling + backoff | Adds deliberate delay between requests | |

**User's choice:** Reactive exponential backoff via tenacity

**Notes:** User selected the recommended option in all three questions. Confirmed ready for context after this area.

---

## Claude's Discretion

- Hevy credential storage (env var vs. encrypted `external_connections`) — area was presented but not selected for discussion; defaulted to keeping the existing env-var `HEVY_API_KEY` per the blueprint's explicit personal-deployment allowance.
- Exact `sync_runs`/checkpoint table shape
- Exact unmapped-exercise flag representation
- Curated mapping storage mechanism (Python module vs. Alembic-seeded rows)
- Whether dumbbell weight is per-dumbbell or combined — empirical, to be discovered during first real sync
- Exact tenacity retry parameters
- CLI/route mechanism for manually triggering sync in this phase

## Deferred Ideas

- Periodic full-reconciliation sweep for deletion detection
- Encrypted per-provider credential storage
- Manual body-measurement and nutrition entry (schema/endpoints)
