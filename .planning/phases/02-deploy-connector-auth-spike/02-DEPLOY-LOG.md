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

## Deploy (Task 3)

`./scripts/deploy-cloud-run.sh` was run with `BRETT_GCP_PROJECT=brett-fitness` and
`BRETT_GCP_REGION=us-central1`. The command line was never hand-reconstructed, so the committed
script remains the reproducible description of the deploy.

| Revision | Origin | Purpose |
|---|---|---|
| `brett-00001-ntc` | `./scripts/deploy-cloud-run.sh` | First deploy. Succeeded on the first attempt — no Procfile, entrypoint, IAM or resolver failure |
| `brett-00002-9z2` | `./scripts/deploy-cloud-run.sh` | After adding the legacy hostname to `MCP_ALLOWED_HOSTS` |
| `brett-00003-jhp` | `gcloud run services update` (env-only) | **T-02-01 negative control** — allowlist deliberately set to `bogus.example.com` |
| `brett-00004-s6h` | `gcloud run services update` (env-only) | Allowlist reverted |
| `brett-00005-gcx` | `./scripts/deploy-cloud-run.sh` | **Final serving revision**, produced by the committed script. All matrix results below are from this revision |

`gcloud run services describe brett --format='value(status.conditions[0].status)'` → `True`.

### What actually shipped — build log evidence

Build `0301e223-6485-46b3-911f-472519efeb25` (regional: `--region=us-central1`; note builds do **not**
appear in a global `gcloud builds list`).

| Check | Observed | Verdict |
|---|---|---|
| Packages installed by `uv sync` | `Prepared 41 packages` / `Installed 41 packages` | **41 = plan 02-08's production-only count.** The dev group did NOT ship (T-02-13 confirmed). 73 would have meant failure |
| `uv pip check` build gate | `Checked 41 packages` | Passed — no resolver conflict |
| Resolved Python | `Using CPython 3.13.14` | **3.13.x as required** — `.python-version` and `requires-python = ">=3.13,<3.14"` both honoured |
| Lockfile | `Using existing uv.lock.` | `UV_FROZEN=1` honoured; no build-time re-locking (T-02-14) |
| Entrypoint | `Using entrypoint from Procfile: uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port $PORT` | Plan 02-08's Procfile worked exactly as designed (Pitfall CR-1 avoided) |

**Assumption A-CR-1 — RESOLVED POSITIVELY, both halves.** `--set-build-env-vars` was not rejected,
*and* the non-`GOOGLE_`-prefixed keys were genuinely forwarded. The build log states verbatim:

```
Step #0 - "pre-buildpack": Passing build environment variable UV_FROZEN to buildpacks
Step #0 - "pre-buildpack": Passing build environment variable UV_NO_DEV to buildpacks
```

The flag was therefore **kept, not removed**. Note the buildpack's own command was
`uv sync --active --link-mode=copy --python 3.13.14` with no `--no-dev`, so `[tool.uv]
default-groups = []` is what independently guaranteed the 41-package result — the belt-and-braces
design from plan 02-08 held on both straps.

**Assumption A-CR-3 — RESOLVED POSITIVELY.** Cloud Run forwards the original public `Host` header to
the container unmodified. Proven two ways: the allowlist matching the real hostname serves traffic,
and the negative control below returns `421` naming the Host header.

### Hostnames assigned (Pitfall CR-4)

Cloud Run assigned **two** hostnames and serves both:

| Hostname | Kind | In `MCP_ALLOWED_HOSTS` |
|---|---|---|
| `brett-792870654598.us-central1.run.app` | deterministic | yes — and the sole `MCP_RESOURCE_URL` host |
| `brett-cglno6k2xq-uc.a.run.app` | legacy hash | yes (appended in commit `62114e4`) |

Both were confirmed live (`/health` → 200 on each). `MCP_RESOURCE_URL` deliberately stays on the
deterministic host: it is the single canonical identifier Claude and WorkOS must both match.

**Method note — the plan's prescribed enumeration command is insufficient.**
`--format='value(status.url,status.urls)'` reports `status.url` = the **legacy** URL and
`status.urls` = empty, so it would have missed the deterministic hostname entirely. The complete
list lives in the `run.googleapis.com/urls` metadata annotation:

```bash
gcloud run services describe brett --project=brett-fitness --region=us-central1 --format=json \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['metadata']['annotations']['run.googleapis.com/urls'])"
# ["https://brett-792870654598.us-central1.run.app","https://brett-cglno6k2xq-uc.a.run.app"]
```

### Liveness and latency

| Measurement | Value |
|---|---|
| `/health` status | `200` |
| `/health` body | `{"status":"ok","database":"connected"}` |
| Protocol | `HTTP/2`, `server: Google Frontend` (TLS terminated by Cloud Run) |
| First request after a deploy | ~1.74 s |
| Warm requests | ~0.62 s, ~0.56 s |
| Startup TCP probe | `succeeded after 1 attempt` on every revision |

`"database":"connected"` is the proof that Task 2's migration landed against the same database the
service is wired to, reached through the `brett-database-url` Secret Manager binding and the
`brett-run` service account.

**Caveat on `curl -sI`.** The plan's criterion is `curl -sI https://$HOST/health | head -1` shows a
2xx. `-I` issues a **HEAD** request, and the FastAPI route is GET-only, so it returns `HTTP/2 404`.
That is correct application behaviour, not a deploy fault. Verified over GET instead:
`curl -s -o /dev/null -w '%{http_version} %{http_code}'` → `2 200`.

### Auth Verification Matrix (deployed)

All seven rows against `https://brett-792870654598.us-central1.run.app`, revision `brett-00005-gcx`.
Every recorded command substitutes the literal `$MCP_AUTH_SECRET` for the header value.

| Row | Command summary | Expected | Observed | Pass/Fail |
|---|---|---|---|---|
| 1 | `POST /mcp`, no `Authorization` | 401 + `WWW-Authenticate` with `resource_metadata` | `401`; header exactly as below | **PASS** |
| 2 | `POST /mcp`, `Authorization: Bearer wrong-token` | 401, body byte-identical to row 1 | `401`; `cmp` reports byte-identical | **PASS** |
| 3 | `POST /mcp`, `Authorization: Bearer $MCP_AUTH_SECRET`, `tools/list` | 200, `tools[0].name == "fitness_ping"` | `200`; exactly one tool, `fitness_ping` | **PASS** |
| 4 | `POST /mcp`, valid token, `tools/call` `fitness_ping`, `Mcp-Name: fitness_ping` | 200, `structuredContent == {"status":"ok","database":"connected"}` | `200`; `{"status": "ok", "database": "connected"}` | **PASS** |
| 5 | `GET /.well-known/oauth-protected-resource/mcp` | 200, correct `resource`, `bearer_methods_supported: ["header"]` | `200`; `resource` byte-identical to `MCP_RESOURCE_URL`; `["header"]` | **PASS** |
| 6 | `GET /health` | 200 | `200`, `{"status":"ok","database":"connected"}` | **PASS** |
| 7 | DNS-rebinding guard rejects a non-allowlisted Host | `421 Invalid Host header` | `421 Invalid Host header` **via negative control** — see below | **PASS** |

**Row 1 `WWW-Authenticate`, recorded verbatim:**

```
www-authenticate: Bearer error="invalid_token", error_description="Authentication required", resource_metadata="https://brett-792870654598.us-central1.run.app/.well-known/oauth-protected-resource/mcp"
```

**Row 1/2 body (identical):** `{"error": "invalid_token", "error_description": "Authentication required"}`

**Row 5 document:**

```json
{"resource":"https://brett-792870654598.us-central1.run.app/mcp","authorization_servers":["https://example.authkit.app"],"bearer_methods_supported":["header"]}
```

`authorization_servers` still names the `example.authkit.app` placeholder because `MCP_AUTH_MODE` is
`static` for the D-01 CLI proof. Plans 02-06/02-07 replace it.

#### Row 7 required a different method than the plan prescribes

**The plan's command cannot test what it intends on Cloud Run.** Sending
`-H "Host: wrong.example.com"` from outside never reaches the container: Google Frontend routes on
the Host header at the edge and answers `404` with a Google HTML error page. The observed result was
`HTTP/2 404`, not `421` and not `200`.

There is a second, independent reason the plan's row 7 could not have observed a `421`: the
deployed service checks **authentication before the Host guard**. Even had the request reached the
app, the plan's row-7 command sends no `Authorization` header and would have returned `401`.
Confirmed directly during the negative control.

The security property was therefore proven with a real negative control instead — the allowlist was
temporarily pointed at a bogus host on an env-only revision (`brett-00003-jhp`), leaving the request
itself completely normal:

```bash
gcloud run services update brett --project=brett-fitness --region=us-central1 \
  --update-env-vars=MCP_ALLOWED_HOSTS=bogus.example.com
curl -si -X POST "https://brett-792870654598.us-central1.run.app/mcp" "${HDRS[@]}" \
  -H "Authorization: Bearer $MCP_AUTH_SECRET" -d "$BODY"
```

Observed, verbatim:

```
HTTP/2 421
Invalid Host header
```

Without the token, the same request returned `401` — which is what establishes the ordering above.
The allowlist was then reverted (`brett-00004-s6h`) and the final script-produced revision
(`brett-00005-gcx`) re-verified against all seven rows.

**This is a stronger result than the plan asked for.** It proves the app's own DNS-rebinding guard
is live and enforcing on the deployed service (T-02-01 mitigated), rather than merely observing that
some layer rejected a malformed request — and it establishes that Cloud Run's edge routing is an
independent second barrier in front of it.

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
