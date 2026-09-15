# Phase 19 — DEPLOY-05 Production Deploy Record

**Purpose:** ROADMAP Phase 19 / REQUIREMENTS DEPLOY-05 — prove Phase 14's deploy-safety fix works by
putting this milestone's own migration (`0007_physique_observations`) through it, rather than
asserting it from tests alone.

**Redaction rule for this file (inherited verbatim from `docs/runbook-deploy.md`):** no credential
value is ever recorded. `DATABASE_URL` is referred to by Secret Manager name only — never as a full
DSN, never with a host, user or password. No bearer token, header value or JWT appears below.

## Pre-deploy state (recorded 2026-09-14T00:00:00Z)

| Check | Command | Observed |
|---|---|---|
| Working tree clean | `git status --porcelain` | clean, no output |
| Commit to be deployed | `git rev-parse HEAD` | `4888aff52ff491279964dea68792f283e788713b` |
| Fast suite | `uv run pytest backend/tests -m "not integration" -q` | `684 passed, 11 skipped, 500 deselected in 5.89s`, exit 0 |
| Local alembic head | `alembic heads` (dummy DSN, no credential) | `0007 (head)` |
| Migration file present | `test -f backend/migrations/versions/0007_physique_observations.py` | exit 0 |
| Physique tools in source | grep `backend/app/mcp/server.py` | 8 matches; `EXPECTED_TOOLS` = 22 (observed; plan text estimated 21) |
| Production revision BEFORE | `gcloud run services describe ... latestReadyRevisionName` | `brett-00011-n2z` |
| Production URL | `gcloud run services describe ... status.url` | `https://brett-cglno6k2xq-uc.a.run.app` |
| Live auth mode | `deploy/cloud-run.env.yaml:50` | `authkit` |

## Method (pre-registered before any deploy output exists)

`docs/runbook-deploy.md` Steps 3-5, followed verbatim by a human operator. This agent's sandbox
refuses `gcloud secrets versions access` under the "Credential Materialization" classifier — the
same block recorded as NUTR-F01 in `.planning/STATE.md`.

Expected deploy-log ordering. All four, in this order, is the DEPLOY-05 criteria 1 + 2 proof taken
together — the pre-flight's own stdout IS the post-upgrade `alembic current` vs `alembic heads`
check, so no separate post-deploy check is needed or wanted:

    DEPLOY-04: using Secret Manager brett-database-url:latest in project brett-fitness
    <alembic upgrade head output, applying 0007>
    at head: ['0007']
    <gcloud run deploy build/deploy output, ending in a new revision serving 100% traffic>

FAIL conditions, taken verbatim from `docs/runbook-deploy.md`'s abort table:

- `DEPLOY-04: failed to resolve DATABASE_URL from Secret Manager (brett-database-url); ...`
- `DEPLOY-04: DATABASE_URL resolved to an empty value; ...`
- an alembic traceback during `alembic upgrade head` (nothing was deployed)
- `DEPLOY-04 violated: the database is at [...] but the migrations head is [...]`
- deploy output appearing at all when the `at head:` line never printed, or appearing before it

Expected MCP smoke-test result
(`backend/app/mcp/tools/schemas.py::LatestPhysiqueObservationResponse`):

    {"data_available": true, "observation": null, "rating_scale": <non-empty>, "disclaimer": <non-empty>}

`observation: null` is the expected PASS value, not an inconclusive result — production has never
had a physique observation logged.

## Deploy log (verbatim, redacted)

**Note on exit code:** the operator's capture command used bash's `${PIPESTATUS[0]}` syntax in a
zsh shell, so the `EXIT:` line came back empty — this is a shell-syntax artifact of the operator's
capture command, not a deploy failure signal. Success is evidenced instead by the log's own
terminal markers below (`at head: ['0007']`, `Done.`, `has been deployed and is serving 100 percent
of traffic`) plus the independent live `gcloud run services describe` revision/traffic check in the
table that follows.

```
DEPLOY-04: using Secret Manager brett-database-url:latest in project brett-fitness
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade 0006 -> 0007, physique observations: header + one rating row per (observation, muscle_group) (PHYS-01..PHYS-05)
at head: ['0007']
Building using Buildpacks and deploying container to Cloud Run service [brett] in project [brett-fitness] region [us-central1]
Building and deploying...
Validating configuration.........done
Uploading sources........................................................done
[... build progress output elided ...]
Setting IAM Policy............................done
Creating Revision...............................................................................................................................................................................................................................................done
Routing traffic.....done
Done.
Service [brett] revision [brett-00012-n6r] has been deployed and is serving 100 percent of traffic.
Service URL: https://brett-792870654598.us-central1.run.app
```

| Check | Expected | Observed | Pass/Fail |
|---|---|---|---|
| Deploy script exit code | 0 | not captured (zsh `$PIPESTATUS` artifact — see note above); log's own terminal success markers and independent live revision check used as evidence instead | N/A (see note) |
| Secret Manager source line | present, exactly once | 1 | PASS |
| BRETT_DATABASE_URL override line | absent | 0 | PASS |
| Pre-flight head line | `at head: ['0007']` present | 1 | PASS |
| Log ordering | `at head:` line < first gcloud deploy line | 5 < 6 | PASS |
| Abort strings | none of the four | 0 | PASS |
| DSN-shaped substring in log | none | 0 | PASS |
| Revision BEFORE | (from pre-deploy table) | `brett-00011-n2z` | — |
| Revision AFTER | different from BEFORE | `brett-00012-n6r` (confirmed independently via live `gcloud run services describe ... latestReadyRevisionName`) | PASS |
| Traffic | 100% on latest revision | `100`/`True` (live `gcloud run services describe`) | PASS |

## MCP smoke test (verbatim)

pending -- written by Task 5 from the operator's pasted response

## Result

pending -- PASS/FAIL per DEPLOY-05 criterion, written by Task 5
