# Phase 7 Deploy Record

Evidence record for plan 07-06 (DEPLOY-03, ROADMAP Phase 7 criterion #2).
Deployed: 2026-09-01T09:39:33Z

**Redaction rule for this file:** no credential value is ever recorded. `MCP_AUTH_SECRET` and
`DATABASE_URL` are referred to by name only, and no Neon DSN, WorkOS token or Secret Manager
payload appears anywhere below.

---

## Correction to the plan's stated starting point

`07-06-PLAN.md`'s interfaces table records the live revision as `brett-00005-gcx` (2026-08-29).
**It was actually `brett-00006-sg2`.** The plan's own instruction — "to be re-confirmed, never
assumed" — is what caught this, and the real value was read from the live service before anything
was changed:

```
gcloud run services describe brett --project=brett-fitness --region=us-central1 \
  --format='value(status.latestReadyRevisionName,status.url)'
-->  brett-00006-sg2   https://brett-cglno6k2xq-uc.a.run.app
```

`brett-00005-gcx` was the *Stage A* revision from plan 02-05; `brett-00006-sg2` superseded it in
plan 02-07's AuthKit cutover, which `02-DEPLOY-LOG.md` § *The AuthKit cutover* records. The
substance of the plan's premise is unaffected — `brett-00006-sg2` predates all of Phase 6 and
served `fitness_ping` alone — but the "before" column below names the revision that was actually
serving, not the one the plan expected.

**Note on `status.url`.** It reports the **legacy** hash hostname
(`https://brett-cglno6k2xq-uc.a.run.app`), not the deterministic one. This is the same trap
`02-DEPLOY-LOG.md` § *Hostnames assigned* documents. Cloud Run serves both; the complete list lives
in the `run.googleapis.com/urls` metadata annotation:

```
["https://brett-792870654598.us-central1.run.app","https://brett-cglno6k2xq-uc.a.run.app"]
```

Every verification row below uses the **deterministic** host, because that is the host inside
`MCP_RESOURCE_URL` and therefore the one Claude and WorkOS both match:

```
BASE="https://brett-792870654598.us-central1.run.app"
```

## Pre-deploy gates

| Gate | Command | Observed | Verdict |
|---|---|---|---|
| Test suite green before deploying | `uv run pytest backend/tests -q` | **683 passed** in 19.79 s | **PASS** |
| Lint | `uv run ruff check .` | `All checks passed!` | **PASS** |
| Types | `uv run mypy backend/app` | `Success: no issues found in 64 source files` | **PASS** |
| Project pinned explicitly | `echo "${BRETT_GCP_PROJECT:?}"` | `brett-fitness` | **PASS** |
| Deploying account | `gcloud auth list --filter=status:ACTIVE` | `hovegant12@gmail.com` | **PASS** |
| gcloud version | `gcloud version` | `Google Cloud SDK 578.0.0` | — |
| **Auth mode before deploying is not the rollback config** (T-07-28) | env dump on `brett-00006-sg2` | `MCP_AUTH_MODE = authkit` | **PASS — not `static`, so no abort** |

The auth-mode gate is the one with teeth: had it read `static`, this plan was required to stop and
let plan 07-09 flip it back first. It read `authkit`, so the deploy proceeded.

## Revision

| Field | Before | After |
|---|---|---|
| Revision | `brett-00006-sg2` | **`brett-00007-xz7`** |
| Deployed | 2026-08-29 (plan 02-07 cutover) | 2026-09-01T09:39:33Z |
| Tools served | `fitness_ping` only | 13 (see "Tool set" below) |
| Rate limiting | none — `grep -c RATE_LIMIT` → `0` | `RATE_LIMIT_PER_MINUTE=30`, `RATE_LIMIT_BURST=30` — `grep -c RATE_LIMIT` → `2` |
| `MCP_AUTH_MODE` | `authkit` | `authkit` (unchanged, re-read after deploy) |
| Image digest | — | `sha256:8230343875e0812dd0f8a917b24bb71a717e18657af4992b17c8959a6337b0a8` |
| Traffic | 100% | **100%** — `[{"latestRevision": true, "percent": 100, "revisionName": "brett-00007-xz7"}]` |
| Source commit | — | `b49f7c03161445ebc49132d1d2305fe8bbe61704` |
| Image repo | — | `us-central1-docker.pkg.dev/brett-fitness/cloud-run-source-deploy/brett` |

Deployed with the committed script, never a hand-reconstructed command line:

```bash
export BRETT_GCP_PROJECT=brett-fitness
export BRETT_GCP_REGION=us-central1
./scripts/deploy-cloud-run.sh
```

```
Service [brett] revision [brett-00007-xz7] has been deployed and is serving 100 percent of traffic.
Service URL: https://brett-792870654598.us-central1.run.app
```

### The deployed environment, as actually read back off the serving revision

Non-secret values in full; credentials by **name only**, per this file's redaction rule.

```
          ENVIRONMENT = production
            LOG_LEVEL = INFO
    MCP_ALLOWED_HOSTS = brett-792870654598.us-central1.run.app,brett-cglno6k2xq-uc.a.run.app
     MCP_RESOURCE_URL = https://brett-792870654598.us-central1.run.app/mcp
        MCP_AUTH_MODE = authkit
       MCP_ISSUER_URL = https://quiet-fireplace-16-staging.authkit.app
         MCP_JWKS_URI = https://quiet-fireplace-16-staging.authkit.app/oauth2/jwks
RATE_LIMIT_PER_MINUTE = 30
     RATE_LIMIT_BURST = 30

         DATABASE_URL <- secret brett-database-url:latest
      MCP_AUTH_SECRET <- secret brett-mcp-auth-secret:latest
```

`--env-vars-file` replaces the service's **entire** environment on every deploy, so this is
re-verified rather than assumed. `MCP_ALLOWED_HOSTS` survived byte-identical and still names both
assigned hostnames; both secret bindings survived, which is what keeps the 07-09 rollback a
configuration change rather than a code change.

### Runtime shape

| Field | Value |
|---|---|
| Service account | `brett-run@brett-fitness.iam.gserviceaccount.com` |
| Resources | `cpu: 1000m`, `memory: 512Mi` |
| Port | `8080` (`http1`) |
| Request timeout | `300 s` |
| Startup CPU boost | `true` |
| Service-level `run.googleapis.com/maxScale` | **`2`** — unchanged by this deploy |

## Tool set

The deployed source registers **13** tools, structurally:
`backend/app/mcp/server.py` calls `mcp.add_tool(fitness_ping, ...)` once (D-08 — the Phase 2 canary
stays first-class) and then loops over a 12-entry `_TOOLS` tuple. 1 + 12 = 13.

`fitness_ping`, `fitness_get_recent_workouts`, `fitness_get_workout`,
`fitness_get_training_summary`, `fitness_get_weekly_volume`, `fitness_get_muscle_group_volume`,
`fitness_get_training_frequency`, `fitness_get_exercise_progression`,
`fitness_get_personal_records`, `fitness_get_plateaus`, `fitness_compare_periods`,
`fitness_get_body_weight_trend`, `fitness_get_recomposition_status`.

#### Why the authenticated tool-list proof is not a curl row

`MCP_AUTH_MODE` is `authkit`, so `build_token_verifier` returns `AuthKitJWTVerifier` and a raw
bearer token is rejected regardless of its value. A `curl` cannot mint a WorkOS JWT, so no
credential available to this agent can produce a `200` from `tools/list`. The authenticated proof is
therefore deliberately **split**, and this is a split rather than an omission:

1. **Task 3 of this plan** — a real Claude client, driven by the developer through the connector's
   OAuth flow, lists and calls the tools. Recorded below under
   *Claude client round-trip (human-verified)*.
2. **Plan 07-09's rotation drill** — flips `MCP_AUTH_MODE` to `static` for the rotation window, and
   can therefore `curl` a full `tools/list` while it is there.

Registration in source (13 `add_tool` targets) is a third, independent line of evidence, but it is
the weakest of the three: it proves what was built, not what is being served. That is exactly the
gap Pitfall 1 warns about, so it is not treated as sufficient on its own.
