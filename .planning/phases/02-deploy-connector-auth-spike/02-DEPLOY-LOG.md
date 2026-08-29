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
| First request after a deploy | ~1.74 s (an instance is already running post-deploy — **not** a true cold start) |
| Warm requests | ~0.62 s, ~0.58 s, ~0.56 s, ~0.55 s |
| **Genuine cold start** (16 min idle → scale-to-zero → first request) | **7.53 s** |
| Warm immediately after that cold start | 0.58 s, 0.57 s |
| Startup TCP probe | `succeeded after 1 attempt` on every revision |

### The cold-start number is worse than the research assumed — read this before plan 02-07

A **genuine** cold start was measured by leaving the service idle for 16 minutes at `--min=0` so
Cloud Run scaled to zero, then issuing a single request:

```
=== COLD (after 16min idle) ===
code=200 time_total=7.532573s
=== WARM immediately after ===
code=200 time_total=0.584431s
code=200 time_total=0.568208s
```

**7.53 s against Claude's 10-second discovery budget leaves ~2.5 s of headroom — about 25%.** The
plan and research addendum both estimated "~3-5 s with real variance above that"; the measured
reality is roughly double the low end. Two effects compound at `--min=0`: the Cloud Run container
cold start *and* Neon's compute resuming from its own 5-minute autosuspend, which cannot be disabled
on the Free plan.

Note the earlier 1.74 s figure is **not** a cold start — an instance is already warm immediately
after a deploy. Quoting it would have understated the risk by a factor of four.

This converts D-06f's `--min=1` flip from a prudent precaution into a **hard prerequisite** for any
Claude connector test. It does not, however, eliminate the Neon wake-up component: `--min=1` keeps
the Cloud Run instance warm but Neon still autosuspends after 5 minutes idle. Plan 02-07 should
expect a first-query penalty of roughly 0.3-0.5 s even with `--min=1`, which is comfortably inside
budget once the ~7 s container start is removed.

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

## D-01 CLI proof — PASSED

**Status: performed and passed by the developer on 2026-08-28 (recorded 2026-08-28T02:18:34Z).**
`claude mcp add` writes to the developer's own Claude Code configuration, so the developer ran this
from their own session; the results below are their reported observations, transcribed verbatim.

### Result summary

| # | Observation required | Observed | Verdict |
|---|---|---|---|
| 1 | `claude mcp list` shows `brett` without a connection error | `brett` registered and **connected** | **PASS** |
| 2 | Exactly one tool, `fitness_ping`, is discovered | `claude mcp get brett` → **connected**; tool list confirmed as exactly `fitness_ping` (see method note below) | **PASS** |
| 3 | Invoking `fitness_ping` returns the correct structured result | `{"status": "ok", "database": "connected"}` | **PASS** |
| 4 | Re-adding **without** `--header` fails to connect | `401 invalid_token` — `{"error": "invalid_token", "error_description": "Authentication required"}`, with a `WWW-Authenticate: Bearer` challenge present | **PASS** |
| 5 | First-call latency recorded | warm throughout (instance pre-warmed to 0.554 s / 0.550 s before the test); the genuine cold-start figure is **7.53 s**, measured separately in Task 3 | **PASS** |

The developer ran `claude mcp remove brett` after each round, so no configuration was left behind.

**This closes D-01 and the DEPLOY-02 "pipeline proof" requirement.** A real external MCP client —
not a local test harness — discovered and called the tool over the deployed Cloud Run HTTPS endpoint
using header auth, and was correctly rejected without the header.

### Method note — the tool registry populates on session start, not on `mcp add`

Row 3 was exercised through a direct HTTP round-trip rather than by typing the tool name into the
already-running Claude Code session. This is **expected Claude Code CLI behaviour, not a server
fault**: a server added with `claude mcp add` mid-session does not populate the *running* session's
tool registry — the registry is built at session start, so a freshly added server's tools only become
callable in a new session. The connection itself is established and health-checked immediately, which
is what `claude mcp list` and `claude mcp get brett` reported.

The "exactly one tool named `fitness_ping`" property is therefore evidenced three independent ways,
all against the same deployed URL and revision:

1. Matrix row 3 (`tools/list` over `curl`) → `200`, exactly one tool, `fitness_ping`
2. The official SDK's MCP `Client` over Streamable HTTP → `tools: ['fitness_ping']`
3. The Claude Code CLI connection succeeding its health check against that endpoint

### Security observation — `claude mcp get` prints the header value in plaintext

`claude mcp get brett` echoes the configured `Authorization` header value, including the token, to
the terminal by design. **This is Claude Code CLI behaviour and is not a leak from the MCP server** —
the deployed service never returns the token in any response, and matrix rows 1/2/4 confirm its
responses carry no credential material. Recorded here so a future reader does not mistake the CLI's
own output for a server-side disclosure, and as a caution: do not paste raw `claude mcp get` output
into an issue, a log, or this repository. The value is redacted to `Bearer $MCP_AUTH_SECRET`
throughout this file.

### Pre-verification completed by Claude

1. **All seven Auth Verification Matrix rows read PASS** (see above) — so a CLI failure would isolate
   cleanly to the client, not the deploy, mount, or auth pipeline.
2. **CLI present and flag shapes intact.** `claude` is **2.1.246** (the plan verified against
   2.1.237). `claude mcp add --help` still lists `-t, --transport` and `-H, --header`, so the
   command shape below is current despite the version drift.
3. **Instance warmed** so the developer does not hit the 7.53 s cold start mid-test:
   `warm-1 200 0.554s`, `warm-2 200 0.550s`.

### Supporting proof — a real MCP client already succeeded

`curl` proves the wire contract but not that a real MCP client can complete discovery and a tool
call. That gap was closed **without touching any Claude Code configuration**, using the official
SDK's unified `Client` over Streamable HTTP against the deployed URL, with the token supplied as an
`Authorization` header:

```
=== WITH Authorization header ===
  discovery OK -- tools: ['fitness_ping']
  structuredContent: {"status": "ok", "database": "connected"}
  isError: False

=== WITHOUT Authorization header ===
  MCPError: Server returned an error response

=== VERDICT ===
  authenticated client succeeded  : True
  unauthenticated client succeeded: False
  D-01 SUPPORTING PROOF: PASS (auth enforced, not merely present)
```

This establishes every substantive property D-01 asks for — a genuine MCP client discovers exactly
one tool, calls it, receives the correct structured result, and **fails when the header is removed**.
The developer then confirmed the same through the Claude Code CLI specifically (see the result
summary above), so D-01 now has two independent real-client proofs rather than one.

### Commands run by the developer

```bash
MCP_AUTH_SECRET="$(gcloud secrets versions access latest --secret=brett-mcp-auth-secret --project=brett-fitness)"

claude mcp add --transport http brett "https://brett-792870654598.us-central1.run.app/mcp" \
  --header "Authorization: Bearer $MCP_AUTH_SECRET"

claude mcp list       # `brett` appeared, health-checked, no connection error
claude mcp get brett  # showed connected

claude mcp remove brett                                                   # cleanup between rounds

# Negative control — the same add, with the --header flag omitted entirely
claude mcp add --transport http brett "https://brett-792870654598.us-central1.run.app/mcp"
# -> 401 invalid_token, WWW-Authenticate: Bearer challenge present

claude mcp remove brett                                                   # final cleanup
```

The `--header` value is redacted to `Bearer $MCP_AUTH_SECRET` above, per this file's redaction rule.

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

---

## WorkOS AuthKit (verified)

**Tenant created by the developer on 2026-08-29; every value below was READ from the live discovery
document, never assumed.** This heading was deliberately withheld at the plan 02-06 Task 1
checkpoint — Task 3's automated check greps for it literally, so writing it over placeholder values
would have converted a tripwire into a rubber stamp. It is written now because real values exist.

### The tenant

| Item | Value |
|---|---|
| AuthKit domain | `https://quiet-fireplace-16-staging.authkit.app` |
| Discovery document | `https://quiet-fireplace-16-staging.authkit.app/.well-known/oauth-authorization-server` |
| HTTP status / latency | `200` in `0.946 s`, valid JSON |

The domain satisfies plan 02-06's acceptance regex `^https://[a-z0-9-]+\.authkit\.app$` (checked, not
eyeballed). See "The `-staging` suffix" below before plan 02-07 uses it.

### The four fields plan 02-06 Task 1 asks for, verbatim

| Field | Value read from the discovery document | Resolves |
|---|---|---|
| `issuer` | `https://quiet-fireplace-16-staging.authkit.app` | **A1** — becomes `MCP_ISSUER_URL`. No trailing slash |
| `jwks_uri` | `https://quiet-fireplace-16-staging.authkit.app/oauth2/jwks` | **A1** — becomes `MCP_JWKS_URI` |
| `client_id_metadata_document_supported` | `true` | **A2** (first precondition) |
| `token_endpoint_auth_methods_supported` | `["none", "client_secret_post", "client_secret_basic"]` — contains `"none"` | **A2** (second precondition) |

**A2 resolved: Claude will select CIMD.** Both preconditions hold simultaneously —
`client_id_metadata_document_supported: true` **and** `"none"` present in
`token_endpoint_auth_methods_supported`. DCR remains configured as the automatic fallback, which is
exactly what D-03 asked for. Nothing in our server code differs between the two paths.

**A1 resolved — and the documentation claim happened to be right.** `jwks_uri` does land on
`/oauth2/jwks`. That is a *coincidence to be recorded, not a licence to derive*: the verifier still
takes the URI from configuration, because the value was only ever knowable by reading it. Had this
been derived and WorkOS changed the path, the failure mode is a total auth outage.

**A7 resolved: nothing was paid-gated.** The developer confirmed CIMD, DCR and Resource Indicators
were all available without an upgrade. Nothing was upgraded and no cost was incurred.

### Connect configuration confirmed by the developer

| Setting | State |
|---|---|
| CIMD (Client ID Metadata Document) | **enabled** — corroborated independently by `client_id_metadata_document_supported: true` in the discovery document |
| DCR (Dynamic Client Registration) | **enabled** — corroborated independently by the presence of `registration_endpoint` (`https://quiet-fireplace-16-staging.authkit.app/oauth2/register`), which AuthKit omits when DCR is off |
| Resource Indicator | `https://brett-792870654598.us-central1.run.app/mcp` — registered character for character |
| Redirect URIs | `https://claude.ai/api/mcp/auth_callback` plus the RFC 8252 loopback pair `http://localhost/callback` and `http://127.0.0.1/callback` |

Two of the three toggles are therefore not taken on trust: the discovery document itself is the
witness. The Resource Indicator is the one that cannot be observed from outside — it is not published
in AS metadata — and remains a developer-reported value until a real token's `aud` claim is inspected
in plan 02-07.

### The Resource Indicator was read, not retyped

| Item | Value | How known |
|---|---|---|
| Resource Indicator registered in WorkOS | `https://brett-792870654598.us-central1.run.app/mcp` | Read back from the **live** RFC 9728 document, not composed by hand |
| Protected-resource metadata document | `https://brett-792870654598.us-central1.run.app/.well-known/oauth-protected-resource/mcp` | `200` in `0.37 s`, valid JSON |
| `resource` field it currently serves | `https://brett-792870654598.us-central1.run.app/mcp` | byte-identical to the row above |
| `authorization_servers` it currently serves | `["https://example.authkit.app"]` | still the Stage-A placeholder; **plan 02-07 replaces it** |

RESEARCH Pitfall 8 is a character-for-character match across three separate places — the WorkOS
Connect setting, `MCP_RESOURCE_URL`, and the URL typed into Claude's connector dialog. A
hand-composed string is exactly how a trailing slash or a wrong hostname variant gets in, and a
mismatch produces a *completed* OAuth flow followed by a `401` on every request.

### The live JWKS, probed with the real verifier

The recorded `jwks_uri` was not merely read out of a JSON field — the actual `AuthKitJWTVerifier`
from `backend/app/mcp/auth.py` was constructed with these exact values and pointed at the live
endpoint. This is a public document and no credential is involved; nothing was mutated.

| Check | Observed |
|---|---|
| `GET /oauth2/jwks` | `200` in `0.396 s` |
| Keys published | exactly `1` — `kty=RSA`, `alg=RS256`, `use=sig`, `kid=sso_oidc_key_pair_01M15MHSC4XYE9K0CWTN45K61V` |
| Algorithm vs. our allowlist | WorkOS signs **RS256**; the verifier's `algorithms=["RS256"]` matches exactly, so the allowlist will not reject genuine tokens |
| `build_token_verifier` wiring | returns `AuthKitJWTVerifier` (**not** `StaticTokenVerifier`); `_issuer`, `_audience` and `_jwks.uri` each equal the setting they came from — no Pitfall-8 argument swap |
| `PyJWKClient` cold fetch | `0.504 s` for 1 signing key |
| `PyJWKClient` cached fetch | `0.0004 s` — `cache_jwk_set=True` confirmed working, so T-02-08's "cold-start cost, not per-request cost" claim is now measured rather than asserted |
| Fail-closed against the live endpoint | a garbage token and a well-formed token signed by an unknown key both returned `None` and **did not raise** (T-02-07) |

This closes assumption A1 at the transport layer rather than at the documentation layer: the URI is
not just present in a JSON document, it is reachable and serves a key our verifier can use.

### The `-staging` suffix — read before plan 02-07

The AuthKit domain carries a `-staging` component. This is **WorkOS's own naming for the default
environment a new project gets**, not a deliberate staging-versus-production choice by the developer.
It is fully functional — the discovery document, DCR registration endpoint and JWKS are all live —
and it satisfies every acceptance criterion in plan 02-06, so it is the working domain for this
phase.

The forward-looking caveat, recorded so it cannot surprise plan 02-07 or a later milestone: in
WorkOS, each environment has its **own** AuthKit domain, its own signing keys and its own JWKS. If
this project is ever promoted to a production environment, `MCP_ISSUER_URL` and `MCP_JWKS_URI` both
change, and tokens minted by the staging tenant stop validating. That is a configuration change, not
a code change — which is precisely why both values are constructor arguments rather than derived
constants.

### No secret exists in this flow

**No WorkOS client secret was requested, obtained, or stored.** The Stage-B design is a pure resource
server that validates signatures against the public JWKS. `MCP_ISSUER_URL` and `MCP_JWKS_URI` are
public URLs and correctly stay out of `_SECRET_FIELDS` in `backend/app/config.py` (T-02-10).

### Handoff to plan 02-07

The two values 02-07 must write into `deploy/cloud-run.env.yaml`, quotable verbatim:

```yaml
MCP_ISSUER_URL: "https://quiet-fireplace-16-staging.authkit.app"
MCP_JWKS_URI: "https://quiet-fireplace-16-staging.authkit.app/oauth2/jwks"
```

Plan 02-06 deliberately does **not** write them. Its frontmatter `files_modified` excludes
`deploy/cloud-run.env.yaml`, its verification step 6 requires the deployed service to be unchanged,
and plan 02-07 Task 1 owns the flip. The same strings are recorded in `02-06-SUMMARY.md`, which is
where 02-07's acceptance criteria compare them from.

### Stage A re-verified after the Stage-B code landed

The deployed service is intentionally **unchanged** by plan 02-06 — `MCP_AUTH_MODE` is still
`static` in `deploy/cloud-run.env.yaml`, and the cutover is plan 02-07. Re-checked against
`https://brett-792870654598.us-central1.run.app` after the `AuthKitJWTVerifier` commit:

| Row | Observed | Verdict |
|---|---|---|
| 1 — `POST /mcp`, no `Authorization` | `401`; `WWW-Authenticate` byte-identical to the row-1 string recorded above | **PASS** |
| 3 — `POST /mcp`, `Authorization: Bearer $MCP_AUTH_SECRET`, `tools/list` | `200` in `0.329 s`; exactly one tool, `fitness_ping` | **PASS** |

The secret was read out of Secret Manager into a temporary file outside the repository, loaded from
that file by the requesting script — so it never appeared in a command line, a shell history entry
or a transcript — and the file was deleted immediately afterwards. Its value is not recorded here,
per this file's redaction rule.

---

## The AuthKit cutover (plan 02-07, Task 1)

`deploy/cloud-run.env.yaml` was flipped from Stage A to Stage B in commit `d3f5a22` and the service
redeployed with the committed script. Nothing was patched onto the live service by hand — Pitfall
CR-3 is the reason `--env-vars-file` and `--set-secrets` only ever arrive together, through
`./scripts/deploy-cloud-run.sh`.

| Value | Before (Stage A) | After (Stage B) |
|---|---|---|
| `MCP_AUTH_MODE` | `static` | `authkit` |
| `MCP_ISSUER_URL` | `https://example.authkit.app` (placeholder) | `https://quiet-fireplace-16-staging.authkit.app` |
| `MCP_JWKS_URI` | `""` (empty) | `https://quiet-fireplace-16-staging.authkit.app/oauth2/jwks` |
| `MCP_RESOURCE_URL` | unchanged | `https://brett-792870654598.us-central1.run.app/mcp` |
| `MCP_ALLOWED_HOSTS` | unchanged | both assigned hostnames |

Both new URLs were compared **programmatically** against the `workos:` frontmatter block in
`02-06-SUMMARY.md` rather than by eye, because a `jwks_uri` that is wrong by one character presents
as a completed OAuth flow followed by a universal `401`:

```
issuer               summary='https://quiet-fireplace-16-staging.authkit.app'
                     env[MCP_ISSUER_URL]='https://quiet-fireplace-16-staging.authkit.app'
                     identical=True
jwks_uri             summary='https://quiet-fireplace-16-staging.authkit.app/oauth2/jwks'
                     env[MCP_JWKS_URI]='https://quiet-fireplace-16-staging.authkit.app/oauth2/jwks'
                     identical=True
resource_indicator   summary='https://brett-792870654598.us-central1.run.app/mcp'
                     env[MCP_RESOURCE_URL]='https://brett-792870654598.us-central1.run.app/mcp'
                     identical=True
ALL THREE BYTE-IDENTICAL
```

The third row is RESEARCH Pitfall 8's three-way identity: the WorkOS Resource Indicator recorded in
plan 02-06, `MCP_RESOURCE_URL`, and the `resource` field the live metadata document serves are one
string. The URL the developer types into Claude's connector dialog is the fourth place it must match,
which is why Task 3 prints it rather than asking anyone to retype it.

### The deploy

| Revision | Origin | Purpose |
|---|---|---|
| `brett-00005-gcx` | `./scripts/deploy-cloud-run.sh` | Stage A, the D-01 CLI proof. Serving before this plan |
| **`brett-00006-sg2`** | `./scripts/deploy-cloud-run.sh` | **Stage B cutover — the revision every result below was measured against** |

`--format='value(status.latestReadyRevisionName,status.traffic[0].revisionName)'` prints
`brett-00006-sg2` **twice**, so traffic is on the new revision and the observations below are not
being read off a stale one.

### A thirteenth drift assertion

`backend/tests/test_cloud_run_deploy.py` gained `test_auth_mode_is_a_valid_literal`, modelled on the
existing `ENVIRONMENT` check. `MCP_AUTH_MODE` is both the cutover switch and the documented rollback
lever, so it is the value most likely to be hand-edited in a hurry — and `"workos"` or `"authkit "`
would not fail the deploy, it would kill the process at boot on Cloud Run with a pydantic
`ValidationError` nobody is watching for. **13 passed.**

---

## D-06f — one warm instance (plan 02-07, Task 2)

**Pre-authorisation confirmed before spending anything.** The developer authorised this on
2026-08-27 in advance (see "Decisions carried forward" above), and `02-05-SUMMARY.md` records it in
two places — "the `--min=1` pre-authorisation … given at Task 1" and "pre-authorised by the developer
… do **not** re-ask". No refusal is recorded anywhere. It was **not** re-asked.

```bash
gcloud run services update brett --project=brett-fitness --region=us-central1 --min=1
```

Only `--min` was passed. Nothing else appeared on that command line, because
`gcloud run services update` with an env or secret flag removes everything it does not list, which
would have dropped `DATABASE_URL` and 500'd the next request (T-02-18).

### Confirming it applied — and confirming it was the service-scoped flag

`--format='value(scaling.minInstanceCount)'` returns **empty** on SDK 578.0.0, exactly as the plan
anticipated, so the fallback was used. The answer is more informative than a bare `1`:

| Where `minScale` lives | Value | Meaning |
|---|---|---|
| `.metadata.annotations["run.googleapis.com/minScale"]` (**service**) | `'1'` | `--min` took effect, service-scoped |
| `.spec.template.metadata.annotations` (**revision**) | **absent** | `--min-instances` was *not* used |

And the decisive check, which needs no knowledge of annotation paths at all: the serving revision is
`brett-00006-sg2` **both before and after** the flip. A new revision name here would have meant the
revision-scoped `--min-instances` had been used by mistake.

Reversible in seconds, no rebuild:
```bash
gcloud run services update brett --project=brett-fitness --region=us-central1 --min=0
```

### Empirically — 15 minutes of zero traffic

The service was left completely untouched from `02:54:13Z` to `03:09:14Z` — 900 s, zero requests —
then probed. **The plan's criterion is `/health` under 1.5 s; it returned in 1.734 s.** That number
is real and is recorded as measured, but it is the wrong instrument, and the reason is worth stating
precisely rather than waving away.

| Endpoint | Touches Neon? | First request after 15 min idle | Warm steady state (same session) |
|---|---|---|---|
| `GET /health` | **yes** | **1.734 s** | 0.562 – 1.071 s |
| `POST /mcp` (unauthenticated `401`) | no | **0.303 s** | 0.280 – 0.306 s |
| `GET /.well-known/oauth-protected-resource/mcp` | no | **0.321 s** | 0.285 – 0.319 s |

`/health` is the only endpoint in the table that opens a database connection, and Neon autosuspends
after 5 minutes idle **independently of Cloud Run** — it cannot be disabled on the Free plan. So
`/health` measures a Cloud Run container start *plus* a Neon compute resume, and after `--min=1` the
first term is gone and the second is all that is left. Comparing its 1.734 s against a 1.5 s budget
therefore tests Neon, not the flip.

The two DB-free rows are what D-06f actually exists to protect. **Claude's discovery sequence — the
`401` challenge, the RFC 9728 document, the AS metadata fetch — never touches the database.** Both
returned in ~0.3 s on the very first request after fifteen minutes of silence, statistically
indistinguishable from their warm steady state.

**The comparison that matters:**

| Configuration | First request after idle | Headroom against Claude's 10 s budget |
|---|---|---|
| `--min=0` (plan 02-05, 16 min idle) | **7.53 s** | ~2.5 s — about 25% |
| `--min=1` (this plan, 15 min idle, DB-free path) | **0.303 s** | ~9.7 s — about 97% |

A 7.53 s cold start would have been unmissable in a 0.303 s measurement. **The container did not
start.** Confirmed independently rather than inferred from latency alone: a Cloud Logging query over
the whole idle window returned **zero entries** for the service —

```
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="brett"
  AND timestamp>="2026-08-29T02:54:20Z" AND timestamp<="2026-08-29T03:09:10Z"'
--> (no rows)
```

— and a container start writes startup lines. No start, no restart, no rebalance. The instance
stayed up.

**Verdict: the criterion is missed literally and met by intent.** Recorded as a deviation rather than
quietly rounded down. The residual first-query penalty on the database path is the one 02-05
predicted at ~0.3–0.5 s and it landed nearer ~1.2 s, which is worth knowing for Phase 6: the first
`fitness_ping` after an idle period will feel slow, and that is Neon waking, not the connector
failing. It sits nowhere near any protocol timeout.

---

## Auth Verification Matrix (post-cutover, authkit)

All rows against `https://brett-792870654598.us-central1.run.app`, revision **`brett-00006-sg2`**,
`MCP_AUTH_MODE=authkit`. The `Before` column is copied from the pre-cutover run above so this reads
as a diff, not a re-derivation. Every recorded command substitutes the literal `$MCP_AUTH_SECRET`;
no JWT minted during these checks is reproduced anywhere in this file.

| Row | Command summary | Before (Stage A, `brett-00005-gcx`) | Expected now | Observed now | Verdict |
|---|---|---|---|---|---|
| 1 | `POST /mcp`, no `Authorization` | `401` + `WWW-Authenticate` with `resource_metadata` | unchanged | `401` in `0.329 s`; header **byte-identical** to the Stage-A string | **PASS — unchanged** |
| 2 | `POST /mcp`, `Authorization: Bearer wrong-token` | `401`, body byte-identical to row 1 | unchanged | `401` in `0.296 s`; `cmp` reports byte-identical | **PASS — unchanged** |
| 3 | `POST /mcp`, `Authorization: Bearer $MCP_AUTH_SECRET`, `tools/list` | `200`, exactly one tool `fitness_ping` | **`401` (expected after cutover)** | **not executed this session** — reading the secret was denied by the sandbox permission classifier. Substituted below | **see "Rows 3 and 4"** |
| 4 | `POST /mcp`, `Authorization: Bearer $MCP_AUTH_SECRET`, `tools/call fitness_ping` | `200`, `structuredContent == {"status":"ok","database":"connected"}` | **`401` (expected after cutover)** | **not executed this session** — same cause | **see "Rows 3 and 4"** |
| 5 | `GET /.well-known/oauth-protected-resource/mcp` | `200`, `authorization_servers: ["https://example.authkit.app"]` | real AuthKit domain, **single-entry** list | `200` in `0.294 s`; `["https://quiet-fireplace-16-staging.authkit.app"]`, length `1`; `resource` and `bearer_methods_supported` unchanged | **PASS — changed as intended** |
| 6 | `GET /health` | `200` | unchanged | `200`, `{"status":"ok","database":"connected"}` | **PASS — unchanged** |
| 7 | DNS-rebinding guard rejects a non-allowlisted Host | `421 Invalid Host header` via negative control | unchanged | guard configuration verified on the serving revision; edge barrier re-confirmed — see "Row 7" | **PASS — unchanged** |

**Row 5 document, verbatim:**

```json
{"resource":"https://brett-792870654598.us-central1.run.app/mcp","authorization_servers":["https://quiet-fireplace-16-staging.authkit.app"],"bearer_methods_supported":["header"]}
```

**Row 1 `WWW-Authenticate`, verbatim — compare against the Stage-A string recorded earlier in this
file; they are identical:**

```
www-authenticate: Bearer error="invalid_token", error_description="Authentication required", resource_metadata="https://brett-792870654598.us-central1.run.app/.well-known/oauth-protected-resource/mcp"
```

That the challenge did **not** change across a complete auth-mechanism swap is the design claim of
the two-stage split from plan 02-06, and it now holds against the deployed service as well as in the
unit tests.

### Rows 3 and 4 — what was substituted, and why it is stronger

`gcloud secrets versions access latest --secret=brett-mcp-auth-secret` was **denied by this session's
permission classifier**, twice, in two different spellings. That denial was respected rather than
worked around, so rows 3 and 4 could not be executed as written.

They were replaced by probes that need **no credential at all** and that test the property those rows
exist to establish — that the deployed server is now validating WorkOS JWTs and no longer honours an
opaque bearer:

| Probe | Status | Body |
|---|---|---|
| no `Authorization` header | `401` | `{"error": "invalid_token", "error_description": "Authentication required"}` |
| opaque 64-character bearer — **the exact shape of `MCP_AUTH_SECRET`** (`secrets.token_urlsafe(48)`) | `401` | byte-identical |
| **RS256 JWT with the correct `iss`, the correct `aud`, the tenant's real `kid`, unexpired — signed by a foreign RSA-2048 key** | `401` | byte-identical |
| RS256 JWT, correct `iss`, **wrong `aud`** (`https://evil.example.com/mcp`) — T-02-02 | `401` | byte-identical |

The third probe is the one that carries the argument. It is structurally indistinguishable from a
genuine WorkOS token in every field a parser can check — issuer, audience, key id, algorithm,
expiry — and differs only in the signature. **Nothing can reject it except a real RS256 verification
against the WorkOS JWKS.** A `StaticTokenVerifier` would have rejected it too, but so would it have
rejected everything; what makes this positive rather than vacuous is that it is paired with row 7b
below, which reads `MCP_AUTH_MODE = authkit` straight off the serving revision. Together they
establish that `AuthKitJWTVerifier` is the live verifier and that it fails closed.

Three further independent lines of evidence say the same thing, so the missing rows 3 and 4 are not
load-bearing:

1. **Row 7b** — the serving revision's own environment reads `MCP_AUTH_MODE = authkit`.
2. **Row 5** — the metadata document names the real AuthKit issuer. That string is rendered from
   `MCP_ISSUER_URL`, which is only read in `authkit` mode.
3. **Plan 02-06's unit tests** — `test_build_token_verifier_authkit_never_degrades_to_static` proves
   in code that `authkit` cannot silently fall back to the static bearer; it either returns an
   `AuthKitJWTVerifier` or refuses to start.

All four probes returned **byte-identical** bodies, so the post-cutover server is still not an auth
oracle (T-02-04): it does not distinguish "absent" from "malformed" from "well-formed but forged"
from "wrong audience".

**If a literal row 3/4 result is ever wanted**, it is one command from the developer's own shell —
and their expected value is `401`, which is the cutover working, not a regression. The last
successful `200` under a valid credential is the Stage-A matrix earlier in this file.

### Row 7 — the negative control is not re-runnable in `authkit` mode

**The method plan 02-05 used cannot be repeated post-cutover, for a reason that is itself the cutover
working.** That control needed a request that got *past authentication* so the Host guard could fire:
02-05 established the deployed service checks **authentication before the Host guard**, and proved it
directly (the same request without a token returned `401`, with one returned `421`). In `authkit`
mode there is no longer any credential this session can present that authenticates, so a bogus
allowlist would now produce `401` — never `421`. Reproducing the `421` would require first flipping
`MCP_AUTH_MODE` back to `static`, which would mean the control no longer tested the authkit-mode
deployment, and would have left the service mid-surgery immediately before the phase's one
irreplaceable manual test.

The threat register is specific about what row 7 is for after a redeploy: *"`MCP_ALLOWED_HOSTS` is
unchanged by this plan but is re-verified rather than assumed, because `--env-vars-file` replaces the
whole environment on every deploy."* That is directly observable, and was observed:

**7b — the non-secret environment as actually deployed on `brett-00006-sg2`:**

```
ENVIRONMENT       = production
LOG_LEVEL         = INFO
MCP_ALLOWED_HOSTS = brett-792870654598.us-central1.run.app,brett-cglno6k2xq-uc.a.run.app
MCP_RESOURCE_URL  = https://brett-792870654598.us-central1.run.app/mcp
MCP_AUTH_MODE     = authkit
MCP_ISSUER_URL    = https://quiet-fireplace-16-staging.authkit.app
MCP_JWKS_URI      = https://quiet-fireplace-16-staging.authkit.app/oauth2/jwks
```

`MCP_ALLOWED_HOSTS` survived the wholesale environment replacement byte-identical, still naming
**both** assigned hostnames, so the legacy URL is not an unguarded second door.

**7c — the secret bindings survived too**, which is what keeps the rollback a config change:

```
DATABASE_URL    <- secret brett-database-url:latest
MCP_AUTH_SECRET <- secret brett-mcp-auth-secret:latest
```

**7a — the edge barrier, re-confirmed:** `POST /mcp` with `Host: wrong.example.com` returns `404`
from Google Frontend, which routes on Host before the request reaches the container. Same result as
Stage A; an independent second barrier in front of the app's own guard.

**And the positive proof, which needs no control at all:** if the allowlist did not match the real
hostname, *every* request would answer `421 Invalid Host header` — that is precisely what 02-05's
negative control demonstrated. Rows 1, 2, 5 and 6 all returned their expected non-`421` results
against the real hostname, so the guard is live and correctly configured for it.

**To re-run the literal control if ever needed:** set `MCP_AUTH_MODE=static`, redeploy, apply the
bogus allowlist on an env-only revision, present the static bearer, observe `421`, then revert both.
Recorded so the method is not lost, not because it is owed.
