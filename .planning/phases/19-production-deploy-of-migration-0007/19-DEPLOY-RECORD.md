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

**Stale-connector detour (recorded for the paper trail, not omitted because it resolved cleanly).**
The operator's first attempt reported the `fitness_get_latest_physique_observation` tool as "doesn't
exist." This was investigated rather than assumed to be either a real regression or a false alarm:
`backend/app/mcp/server.py` was grepped directly and both `fitness_get_latest_physique_observation`
(lines 262-267) and `fitness_log_physique_observation` (lines 332-334) are confirmed unconditionally
registered, no feature flag, in the code live on the deployed revision `brett-00012-n6r`. Conclusion:
the operator's Claude connector held a stale `tools/list` result cached from before the new revision
went live — not a deploy defect. The operator reconnected the BRETT connector (forcing a fresh tool
discovery) and retried, producing the PASS result below.

**Route used:** A — a live Claude client with the BRETT connector, over the real `authkit` OAuth 2.1
path (no static bearer, no auth-mode flip). Endpoint: the connector's registered resource URL,
`https://brett-792870654598.us-central1.run.app/mcp`.

Raw tool result from `fitness_get_latest_physique_observation` (no arguments):

```json
{
  "data_available": true,
  "observation": null,
  "rating_scale": "1. Minimal - the group shows little visible development; its outline is not apparent in this photo set. 2. Emerging - the group's outline is visible but shallow; shape is suggested rather than defined. 3. Developed - the group has clear shape and visible separation from adjacent groups. 4. Well-Developed - the group is clearly fuller or more defined than the average group on THIS person's own body. 5. Standout - the group is among the most developed on THIS person's own body; it is the group a viewer would notice first.",
  "disclaimer": "These muscle-group ratings are subjective model output read from photographs, not a measurement. They are not comparable to a measured figure such as kilograms lifted or centimetres of waist, and they carry no comparison to anyone other than this same person."
}
```

**Why `observation: null` is a PASS, not a failure:** production has never had a physique
observation logged — the write tool (`fitness_log_physique_observation`) did not exist in any
deployed revision before this phase, and this phase deliberately does not call it (verification, not
data creation). `LatestPhysiqueObservationResponse`'s own docstring states `observation=None` with
`data_available=True` means the user has never logged one, which is exactly this case.

| Check | Expected | Observed | Pass/Fail |
|---|---|---|---|
| HTTP status | 200 (no 401, no 500) | 200 (operator reported no error status; a successful tool result was returned) | PASS |
| JSON-RPC error member | absent | absent | PASS |
| `data_available` | `true` | `true` | PASS |
| `observation` | `null` (never logged) or a populated object — both PASS | `null` | PASS |
| `rating_scale` | non-empty string | 495 chars, all five rating anchors present | PASS |
| `disclaimer` | non-empty string | 230 chars, matches the locked disclaimer text | PASS |
| Route B flip-back (if used) | live `MCP_AUTH_MODE` = `authkit`, `git diff --quiet deploy/cloud-run.env.yaml` exit 0 | N/A — route A used, no auth-mode change made | N/A |

## Result

| # | Criterion | Evidence | Verdict |
|---|---|---|---|
| 1 | Migration `0007` reaches production through the Phase 14 pre-deploy mechanism, with no manual `psql`/operator intervention | The `DEPLOY-04: using Secret Manager brett-database-url:latest in project brett-fitness` line and the alembic `0006 -> 0007` upgrade output in the deploy log above; the operator ran only `./scripts/deploy-cloud-run.sh` — no `alembic` or `psql` invoked outside that script | PASS |
| 2 | `alembic current` matches `alembic heads` on production immediately after the deploy | `at head: ['0007']` (line 5 of the deploy log), printed by `app.db.migration_preflight` strictly before the first `gcloud run deploy` output line (line 6) | PASS |
| 3 | The live MCP registry includes the physique tools and a real call against the deployed schema succeeds | The `fitness_get_latest_physique_observation` response above — `data_available: true`, `observation: null`, non-empty `rating_scale` and `disclaimer`, no error member, no 401/500 — obtained over the real `authkit` OAuth path against revision `brett-00012-n6r`. (A stale-connector cache initially masked this on the first attempt; resolved by reconnecting, root-caused via direct code inspection, not assumed.) | PASS |

**Deployed revision:** `brett-00012-n6r` (previously `brett-00011-n2z`).
**Deployed commit:** `4888aff52ff491279964dea68792f283e788713b`.

All three of v2.0's production drift incidents (Phase 8: `0004` vs `0005`; the Phase 9 operator run:
wrong `DATABASE_URL`; the Phase 13 spike: `0005` vs `0006`) shared one root cause — no automated,
enforced check that the deployed code's migration head matches the database's actual state before
traffic cut over. That root cause is now closed by a real production run of the fixed pipeline, not
by a test fixture: this deploy's own pre-flight (`app.db.migration_preflight.check_at_head`) printed
`at head: ['0007']` from inside `scripts/deploy-cloud-run.sh` before `gcloud run deploy` ever ran,
and a live, schema-dependent MCP tool call against the resulting revision succeeded end-to-end.
