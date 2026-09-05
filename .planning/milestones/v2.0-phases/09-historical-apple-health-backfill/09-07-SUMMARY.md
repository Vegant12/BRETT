---
plan: 09-07
phase: 09-historical-apple-health-backfill
status: complete
requirements-completed: [HEALTH-10]
---

# 09-07 Summary: Production Import and Verification

## What shipped

The one-time production backfill of 4.5 years of Apple Health activity and nutrition history ran
against the real Neon production database, and all four ROADMAP success criteria for Phase 9 are
confirmed against the live result — not a rehearsal, not a container, not a dry run.

## Checkpoint execution (Task 1 — human-action)

The operator (not an agent, per D-02) ran the full §10 procedure against production:

- **Pre-flight:** `alembic current` and `alembic heads` both printed `0005` — matched, no migration
  gap this time.
- **Operational incident, resolved live:** the first pass at post-write verification queries
  returned a stale before-state (`count: 23`, `2026-09-02 .. 2026-09-03`) immediately after a
  `--write` that had logged `rows_written=8077` with no errors. Root cause: the verification
  queries were run against the wrong `DATABASE_URL`, not the Neon connection string bound to the
  deployed service (Google Secret Manager secret `brett-database-url`). Resolved by retrieving the
  confirmed value with `gcloud secrets versions access latest --secret="brett-database-url"` and
  re-running the full sequence (pre-flight, dry run, write) against it. The write is idempotent by
  natural key, so repeating it cost nothing and produced no duplicate rows.
- **The real run (against the confirmed URL):** exit 0, wall clock ≈59 s
  (`hevy_cli_started` 11:19:12.863Z → `hevy_cli_stopped` 11:20:11.922Z). Printed summary matched
  every pinned figure from the 09-06 dry-run rehearsal exactly: 438,649 records total, 8,077 rows
  written, 0 skipped, date range 2022-03-10 .. 2026-08-26.
- **Four verification queries**, all passing:
  1. Before/after state: `apple_health` row count moved from 23 to 8,100 (23 + 8,077); date range
     widened to `2022-03-10 .. 2026-09-03` — **SC#1/SC#2**.
  2. Duplicate metric-day check: zero rows — **SC#3** (vacuously, per zero day-overlap — the
     overlapping case is proven by `test_backfill_idempotency.py`'s container tests).
  3. Hevy-sourced row check: `0` — **SC#4**.
  4. `sync_state`: `activity` and `nutrition` both `idle`, both `last_synced_at:
     2026-09-03 11:20:08.304243+00` (identical instant) — confirms `complete_sync` advanced both
     resources together in the same transaction as the rows (T-09-34).

## Task 2 (auto) — verification record and STATE.md closure

- `docs/health-auto-export-setup.md` §9 gained a fourth dated subsection,
  "2026-09-03 — historical backfill, production run", recording the command shape, the pre-flight
  match, the operational DATABASE_URL incident and its resolution, the before/after state, the full
  printed summary, and all four verification query results mapped explicitly onto the four ROADMAP
  success criteria. Grep-confirmed free of any real connection string.
- `.planning/STATE.md` Blockers/Concerns gained dated entries: A2 (day overlap) and A3 (device name
  unchanged) resolved with observed evidence; the `sample_count` divergence and the Gymverse/Zing
  ingestion decision recorded as open/accepted (both carried from RESEARCH, not new); a new entry
  for the DATABASE_URL incident as the third occurrence of an operator-shell-wrong-target risk this
  milestone, with the still-undone structural fix noted. Current Position and Session Continuity
  updated to reflect Phase 9 execution complete.
- `.planning/ROADMAP.md` was deliberately not touched in this task — phase completion is the
  orchestrator's job, not this plan's.

## Verification

- `uv run pytest -q` (full suite, including `realfile`): **899 passed**
- `uv run pre-commit run --files docs/health-auto-export-setup.md .planning/STATE.md`: all hooks
  passed, including `gitleaks`
- String-level checks (heading text, summary field labels, SC-mapping sentences, `A2`/`A3`/
  `sample_count`/`Gymverse` presence in STATE.md, zero connection-string leaks in either file): all
  passed

## Deviations

None from the plan's own tasks. The DATABASE_URL mixup during the checkpoint was an operator-side
incident within Task 1's human-action gate, not a deviation from the plan's instructions — the plan
already anticipated and gated against exactly this class of risk (T-09-31/T-09-32), and the
resolution path (confirm the value, re-run) was the correct one rather than a workaround.

## Requirements

HEALTH-10 is now complete: the historical Apple Health import has run against production and all
four success criteria are confirmed live, closing the gap the test-bed and rehearsal plans (09-01
through 09-06) deliberately left open.
