---
phase: 07-production-hardening-coaching-layer
verified: 2026-09-01T13:09:34Z
status: pending
score: 0/4 criteria verified
overrides_applied: 0
---

# Phase 7: Coaching Layer UAT (D-09)

Verifies ROADMAP Phase 7 success criterion #4: "The coaching system-prompt/instructions document
exists, and with it loaded Claude answers 'Am I progressing?' and 'Which muscles are
undertrained?' from real synced data, correctly flagging stale or sparse data when present."

**This is a human-verified checkpoint, not a claim inferred from code.** No automated test in
this repo can observe a Claude Project's behaviour; the automatable half of COACH-01 is
`backend/tests/test_coaching_doc.py`, which proves only that the document names real tools.

**Redaction rule for this file:** no credential value, no connection string and no
`Authorization` header value is ever recorded. Transcript excerpts are quoted for their tool
choices and their metadata handling, not for the training data they contain.

**Status:** `pending`. Task 1 (preconditions) is complete and recorded below. Task 2 — the UAT
itself — is a `checkpoint:human-verify` and has not yet run. Every section from *Setup* onward is
a deliberately empty skeleton awaiting the developer's report. `status`, `score` and the
Observable Truths table are filled only after that report arrives.

## Preconditions (verified 2026-09-01)

Every row was run against the live system on 2026-09-01, between 13:05Z and 13:09Z. Nothing here
is quoted from a prior plan's record: the earlier plans' claims are what these commands were run
to re-confirm, per the plan's "confirm each, do not assume".

| # | Precondition | Command | Observed | Pass/Fail |
|---|---|---|---|---|
| 1 | `MCP_AUTH_MODE` is `authkit` | `gcloud run services describe brett --region=us-central1 --format='json(spec.template.spec.containers[0].env)'` | `MCP_AUTH_MODE = authkit`. Both secret bindings intact — `DATABASE_URL` ← `brett-database-url:latest`, `MCP_AUTH_SECRET` ← `brett-mcp-auth-secret:latest` (names only, no values read). `MCP_RESOURCE_URL = https://brett-792870654598.us-central1.run.app/mcp`, `MCP_ALLOWED_HOSTS` names both assigned hostnames, `RATE_LIMIT_PER_MINUTE=30`, `RATE_LIMIT_BURST=30` | **PASS** |
| 2 | Live revision | `gcloud run services describe brett --region=us-central1 --format='value(status.latestReadyRevisionName,status.url)'` plus `--format='json(status.traffic)'` | **`brett-00009-fsm`**, `latestRevision: true`, **100%** of traffic. This is 07-09's flip-back revision, so the UAT tests the post-rotation service, not the pre-rotation one | **PASS** |
| 3 | Last sync execution succeeded, timestamp | `gcloud run jobs executions list --job=brett-sync-hevy --region=us-central1 --limit=1 --format='value(metadata.name,metadata.creationTimestamp,status.succeededCount)'` | `brett-sync-hevy-6vl4w` · `2026-09-01T11:23:41.953676Z` · `succeededCount 1`. Read at `2026-09-01T13:05:35Z` → **1 h 42 min old**, well inside the 12-hour bound | **PASS** |
| 4 | Scheduler `ENABLED`, `0 */6 * * *`, `Asia/Jakarta` | `gcloud scheduler jobs describe brett-sync-hevy-6h --location=us-central1 --format='value(schedule,timeZone,state)'` | `0 */6 * * *` · `Asia/Jakarta` · **`ENABLED`** — all three exactly as specified | **PASS** |
| 5 | `test_coaching_doc.py` green | `uv run pytest backend/tests/test_coaching_doc.py -x -q` | `4 passed in 0.49s`, exit `0`. The document still names only tools that exist in the live registry | **PASS** |
| 6 | Full suite green | `uv run pytest backend/tests -q` | **`687 passed in 34.29s`**, exit `0` (`FULL_SUITE_EXIT=0` captured explicitly). Up from the 683 recorded in `07-DEPLOY-RECORD.md`, consistent with the test modules added by plans 07-07 through 07-09 | **PASS** |

**All six PASS, so the plan proceeds.** Any FAIL here would have stopped it: a UAT run against a
stale revision or an unsynced database proves nothing.

### Two supporting facts, confirmed rather than assumed

- **Production holds real data.** `07-06-DEPLOY-RECORD.md` recorded `data_available: false` as an
  honest FAIL and named this plan as the second, unskippable gate on that fact. Plan 07-07 closed
  it: **327 workouts, 463 exercise templates, 125 body measurements** are in production Postgres
  (`hevy_sync_all_completed mode=full workouts=327 templates=463 body=125`). The workout and
  template counts match `docs/hevy-api-observations.md` exactly. The UAT is therefore being asked
  to read a populated database, which is the precondition that made 07-06's checkpoint fail.
- **The endpoint answers anonymously right now.** `GET /health` → `200`
  `{"status":"ok","database":"connected"}`; `GET /.well-known/oauth-protected-resource/mcp` → `200`
  with `resource` byte-identical to `MCP_RESOURCE_URL` and a single `authorization_servers` entry
  naming the real AuthKit tenant. Both anonymous, so neither required reading a secret.

### BLOCKER FOUND IN TASK 1 — `minScale` has regressed to `0` again

**This must be resolved before Task 2 runs, and it is not a theoretical risk.**

The service annotations on `brett-00009-fsm` read:

```
run.googleapis.com/maxScale: "2"
run.googleapis.com/minScale: (absent — i.e. 0)
```

This is the exact regression `07-06-DEPLOY-RECORD.md` § *Deviations* predicted:
`scripts/deploy-cloud-run.sh` passes `--min="${BRETT_MIN_INSTANCES:-0}"` unconditionally, so
plan 07-09's flip-back deploy silently cleared the `--min=1` that had been restored by hand after
the 07-06 deploy. The follow-up to fix the script was deferred, so the regression recurred exactly
as predicted.

**Measured evidence, not inference.** The first anonymous `GET /health` of this session took:

```
[HTTP 200 in 16.213946s]     <- cold start
[HTTP 200 in 0.442104s]      <- warm, immediately after
```

**16.2 seconds against Claude's documented 10-second discovery budget.** `02-DEPLOY-LOG.md`
measured a 7.53 s cold start and concluded on that basis alone that `--min=1` is "a **hard
prerequisite** for any Claude connector test". Task 2 *is* a Claude connector test, and the
observed cold start is now more than twice the budget. At `--min=0`, if the service scales to zero
before the developer opens Claude, the connector will present as "Couldn't reach the MCP server"
for reasons that have nothing to do with the coaching document — and a failed UAT would be
attributed to the wrong cause.

**Attempted fix, and its outcome.** The restoring command needs no rebuild and was pre-authorised
by the developer on 2026-08-27 (recorded twice in `02-DEPLOY-LOG.md`):

```bash
gcloud run services update brett --project=brett-fitness --region=us-central1 --min=1
```

**BLOCKED** — denied by this session's permission classifier, the same denial
`07-06-DEPLOY-RECORD.md` records against the identical command. The denial was respected rather
than worked around. **The developer must run it before starting Task 2**, then confirm:

```bash
gcloud run services describe brett --project=brett-fitness --region=us-central1 \
  --format='json(metadata.annotations)'
#   expect: "run.googleapis.com/minScale": "1"
#           "run.googleapis.com/maxScale": "2"
```

Only `--min` may appear on that `update` command line: `gcloud run services update` removes any
env or secret flag it does not list, which would drop `DATABASE_URL` and `500` the next request
(T-02-18).

### Note on step 5's premise — record what actually happens, do not assume the setup

The plan's step 5 forces the staleness/sparsity case by asking for a **52-week** window, on the
stated premise that "history does NOT stretch back 52 weeks". **That premise was not verifiable
from the artifacts in this repo during Task 1** — `docs/hevy-api-observations.md` records no
earliest-workout date, and 327 workouts at a typical 4-sessions-per-week cadence would span
roughly 80 weeks, which would *exceed* 52.

This is recorded as an open question rather than resolved in either direction, and it changes
nothing about how step 5 is run — it only changes how its result is read:

- If the 52-week question **does** trip `coverage.earliest_data_at` / `coverage.insufficient_data`,
  Truth 4 is satisfied directly.
- If it **does not**, that is not a failure of Truth 4. It means the synced history is longer than
  assumed, and the plan's own fallback probe applies: *"When was my data last synced, and how
  confident should I be in the last 4 weeks?"* Record which probe was used and why.

Either way, record `coverage.earliest_data_at` as Claude reports it — that single value settles the
premise for every future reader.

## Setup

<Project name, whether it was created or reused, and confirmation that
docs/coaching-instructions.md was pasted into its custom instructions verbatim (D-08) and that
the BRETT connector is attached to that Project.>

## Observable Truths (ROADMAP criterion #4)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | The document exists and names only real tools | | |
| 2 | "Am I progressing?" is answered from real data, opening with fitness_get_training_summary | | |
| 3 | "Which muscles are undertrained?" is answered from real data, distinguishing direct from indirect sets | | |
| 4 | A window that outruns the data makes Claude surface coverage/freshness unprompted | | |

## Transcript

<per question: the tools Claude called, in order, with their arguments; a faithful summary or
excerpt of the answer; and what it said about metadata.>

## Observations for later tuning

<per-turn tool-call counts, any 429, any tool that felt slow or oversized — recorded as
evidence, NOT acted on: retuning tool budgets is explicitly out of this phase's boundary.>

## Gaps and honest limitations
