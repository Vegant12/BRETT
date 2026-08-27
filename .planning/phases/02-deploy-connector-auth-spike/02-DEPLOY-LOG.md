# BRETT — Cloud Run Deploy Log

Evidence record for plan 02-05 (DEPLOY-01, MCP-01, MCP-04, D-01).

**Redaction rule for this file:** no credential value is ever recorded. `MCP_AUTH_SECRET` is
referred to by name only, and the Neon DSN is redacted to
`postgresql://***@ep-small-wave-ayqfaloh.c-5.us-east-2.aws.neon.tech/neondb`.

---

## Project bootstrap (Task 2)

| Field | Value |
|---|---|
| GCP project ID | `brett-fitness` |
| GCP project number | `792870654598` |
| Project name | BRETT |
| Billing account | `01E8E3-6C54F5-D6B9B6` ("My Billing Account 1"), `billingEnabled: true` |
| Region | `us-central1` |
| Cloud Run service name | `brett` |
| Deterministic URL | `https://brett-792870654598.us-central1.run.app` |
| MCP endpoint | `https://brett-792870654598.us-central1.run.app/mcp` |
| Artifact Registry repo | `cloud-run-source-deploy` (implicitly created by `gcloud run deploy --source`; noted so it is not later mistaken for stray state) |
| Runtime service account | `brett-run@brett-fitness.iam.gserviceaccount.com` |
| Deploying account | `hovegant12@gmail.com` |

`brett-fitness` was available on the first attempt — the fallback ID `brett-fitness-eceh` was not
needed. This is also the only way availability was ever knowable: `gcloud projects describe` returns
`PERMISSION_DENIED` for every ID the caller does not own, whether or not it exists, so `create` is
the only real probe (see 02-05-SUMMARY.md Deviation #1).

### APIs enabled

All five required, verified present in `gcloud services list --enabled`:

`run.googleapis.com`, `cloudbuild.googleapis.com`, `artifactregistry.googleapis.com`,
`secretmanager.googleapis.com`, `compute.googleapis.com`

`compute.googleapis.com` is enabled not for VMs but because it materialises the Compute Engine
default service account, whose absence is a named cause of first-deploy failure in a Run-only
project.

### IAM

| Principal | Role | Scope | Why |
|---|---|---|---|
| `792870654598-compute@developer.gserviceaccount.com` | `roles/run.builder` | project | Since July 2024 the Compute Engine default SA no longer inherits the legacy Cloud Build role in new projects; without this the build fails opaquely, often as "could not write logs" |
| `brett-run@brett-fitness.iam.gserviceaccount.com` | `roles/secretmanager.secretAccessor` | **per secret**, both secrets | T-02-12 least privilege. Granted on the secret resource, not project-wide |
| `hovegant12@gmail.com` | `roles/iam.serviceAccountUser` | on `brett-run` SA | Required to attach the runtime SA to the service at deploy time |

The Compute Engine default SA was confirmed to carry `roles/editor` in this project — which is
exactly why a dedicated `brett-run` identity holds the runtime credentials instead (T-02-12).

### Secrets (Google Secret Manager)

`gcloud secrets list` returns exactly two, as required:

| Secret | Bound to | Accessor binding |
|---|---|---|
| `brett-mcp-auth-secret` | `MCP_AUTH_SECRET` via `--set-secrets` | `serviceAccount:brett-run@brett-fitness.iam.gserviceaccount.com` **and nothing else** |
| `brett-database-url` | `DATABASE_URL` via `--set-secrets` | `serviceAccount:brett-run@brett-fitness.iam.gserviceaccount.com` **and nothing else** |

Both written with `printf '%s'`, never `echo` (Pitfall CR-6 / T-02-17). Trailing-newline check,
performed without printing either value:

| Secret | Length | Last byte |
|---|---|---|
| `brett-mcp-auth-secret` | 64 bytes — exactly `secrets.token_urlsafe(48)` | not `0a` — **PASS** |
| `brett-database-url` | 140 bytes | not `0a` — **PASS** |

A trailing newline here would have made every authenticated request 401 while the console showed a
correct-looking value. Independently corroborated below: the migration connected using the DSN read
back out of Secret Manager, which it could not have done had the stored value been corrupted.

### Hostname pinned before first deploy

`deploy/cloud-run.env.yaml` now names the real deterministic hostname:

- `MCP_ALLOWED_HOSTS: "brett-792870654598.us-central1.run.app"`
- `MCP_RESOURCE_URL: "https://brett-792870654598.us-central1.run.app/mcp"` (no trailing slash)

`grep -c '000000000000'` → `0`; `grep -c 'brett-792870654598'` → `2`.
`uv run pytest backend/tests/test_cloud_run_deploy.py -q` → **12 passed**.

Note the placeholder occurred **three** times, not the two the 02-08 handoff recorded: the third was
an explanatory comment on line 23 that named the literal. It was rewritten to describe the real
number, which is what allows `grep -c '000000000000'` → 0 and `grep -c 'brett-<number>'` → 2 to be
satisfied simultaneously (02-05-SUMMARY.md Deviation #3).

### Database (Neon)

| Field | Value |
|---|---|
| Provider | Neon (external managed Postgres, D-06b — no VPC connector, no Auth Proxy sidecar) |
| Region | `us-east-2` (AWS, US) |
| Database name | `neondb` |
| Endpoint kind | **DIRECT / unpooled** — host carries no `-pooler` suffix, per Neon's guidance that migrations must not run through the pooler |
| DSN (redacted) | `postgresql://***@ep-small-wave-ayqfaloh.c-5.us-east-2.aws.neon.tech/neondb` |
| TLS | `sslmode=require&channel_binding=require`, pasted verbatim — `Settings.async_database_url` translates it to asyncpg's `ssl` parameter with zero code change |

Neon is in `us-east-2` and Cloud Run in `us-central1`. Both are US regions, which is what the
research addendum asked for (Anthropic's connector egress is US-based); the intra-US cross-region
hop costs far less than the Asia/US pairing it avoids.

**Migration ran from the developer machine, before any revision existed** — Cloud Run has no
pre-deploy hook, and startup migrations stay forbidden because a Cloud Run deploy runs old and new
revisions simultaneously by design.

```
alembic upgrade head   ->  -> 0001, initial schema: the users table (blueprint §5.1)
                           0001 -> 0002, seed the single v1 default user (D-01, D-02)
alembic current        ->  0002 (head)
```

---

## Decisions carried forward

### D-06f — `--min=1` pre-authorised for plan 02-07

**The developer explicitly authorised this on 2026-08-27, in advance. Plan 02-07 must NOT re-ask.**

Plan 02-07 is to run `gcloud run services update brett --project=brett-fitness --region=us-central1
--min=1` before any Claude connector round-trip test, accepting one continuously-billed warm
instance. Rationale: Claude allows **10 seconds** for OAuth discovery, registration and token
endpoints, and a Cloud Run cold start for this app is expected around 3-5 s with real variance above
that; a marginal miss presents as an undiagnosable "Couldn't reach the MCP server". Reversible in
seconds with `--min=0` after the test.

The deploy script reads `BRETT_MIN_INSTANCES` (default `0`), but the service-level
`gcloud run services update --min=1` is preferred because it needs no rebuild.

### Billing

The developer explicitly authorised charging billing account `01E8E3-6C54F5-D6B9B6` for this
project's Cloud Run, Cloud Build, Artifact Registry and Secret Manager usage.
