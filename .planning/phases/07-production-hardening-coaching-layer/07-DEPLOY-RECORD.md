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

---

## Anonymous Verification Matrix (deployed)

All eight rows against `BASE = https://brett-792870654598.us-central1.run.app`, revision
`brett-00007-xz7`. Every row is anonymous: no row sends a credential, so nothing in this section
required reading a secret.

The MCP envelope used by rows 3, 4, 5 and 8 carries the mandatory `params._meta` — without it the
server answers `-32602` **inside a 200**, which would make an auth assertion meaningless:

```bash
MCP_BODY='{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{}}}}'
curl -sS -D- -o /dev/null -X POST "$BASE/mcp" \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  -H 'MCP-Protocol-Version: 2026-07-28' \
  -H 'Mcp-Method: tools/list' \
  -H 'Mcp-Name: tools/list' \
  --data "$MCP_BODY"
```

| Row | Command summary | Expected | Observed | Pass/Fail |
|---|---|---|---|---|
| 1 | `GET /health` | `200`, `{"status":"ok","database":"connected"}` | `200` in 1.93 s (first, Neon waking) then 0.36 s warm; body exactly `{"status":"ok","database":"connected"}` | **PASS** |
| 2 | `GET /.well-known/oauth-protected-resource/mcp`, no auth header | `200`, names resource + WorkOS AS | `200` in 0.358 s; document quoted verbatim below | **PASS** |
| 3 | `POST /mcp`, full envelope, **no** `Authorization` | `401` + `WWW-Authenticate` containing `resource_metadata=` | `HTTP/2 401` in 0.363 s; challenge quoted verbatim below, contains `resource_metadata=` | **PASS** |
| 4 | Row 3 + an `Authorization: Bearer` header whose value is the literal `definitely-not-a-real-token` | `401`, body byte-identical to row 3 | `HTTP/2 401` in 0.351 s; `cmp` → **byte-identical**; the `WWW-Authenticate` challenge is identical too | **PASS** |
| 5 | Rapid POSTs to `/mcp`, no auth, collecting status codes | at least one `429`, body exactly `{"error":"rate_limited"}`, `Retry-After` present | **first attempt (40 sequential) produced ZERO 429 — instrument inadequate, see below.** Re-run concurrently (120 req, 30-way, 4.0 s): **89 × `429`**, 31 × `401`. First 429 at request #31. Body exactly `{"error":"rate_limited"}` (24 bytes, hex-verified); `retry-after: 1` and `retry-after: 2`; `content-type: application/json` | **PASS (on the corrected method)** |
| 6 | `GET /health` **while a burst is in flight** | still `200` — `/health` exempt | `200`, `{"status":"ok","database":"connected"}`, fired 2.0 s into a live 200-request burst with the burst process confirmed still running | **PASS** |
| 7 | `GET /.well-known/oauth-protected-resource/mcp` **while a burst is in flight** | still `200` — discovery exempt | `200`, same instant as row 6 | **PASS** |
| 8 | Wait ~90 s after a burst that genuinely drained the bucket, re-run row 3 | back to `401`, proving refill | drained state confirmed by a `429` control at 09:53:48Z; after 90 s (09:53:59Z → 09:55:29Z) `POST /mcp` → `HTTP/2 401` in 0.429 s, body **byte-identical to row 3** | **PASS** |

### The decisive exemption evidence (rows 6 and 7)

Rows 6 and 7 are only meaningful if the limiter was actually rejecting at that instant. All three
probes below were fired at **09:53:48.99Z**, 2.0 s into a 200-request burst, with the burst process
verified alive:

```
ROW 6  GET /health          (during burst): {"status":"ok","database":"connected"} [HTTP 200]
ROW 7  GET discovery        (during burst): [HTTP 200]
ctrl   POST /mcp            (during burst): [HTTP 429]
  (confirmed: burst process still alive when the probes ran)
```

Same moment, same instance: the two exempt paths served `200` while the non-exempt path was being
rejected `429`. That is `EXEMPT_PREFIXES = ("/health", "/.well-known/")` demonstrated in production
rather than inferred from the module.

### Row 5 required a different method than the plan prescribes

**The plan's row 5 — "40 rapid POSTs … in a `for` loop" — cannot reliably trip this limiter, and
the first attempt did not.** All 40 returned `401`; not one `429`. Recorded as an initial **FAIL of
the method**, not rounded away, because the arithmetic explains it exactly:

- A sequential `curl` loop issues roughly **2.9 requests/second** (~0.35 s round-trip each).
- The bucket refills at `RATE_LIMIT_PER_MINUTE=30` → **0.5 tokens/second**, capacity 30.
- The loop, including the two interleaved exemption probes, ran for roughly 15–20 s wall-clock, so
  the bucket replenished on the order of 8–10 tokens while it drained.
- Effective supply (30 capacity + ~10 refilled) was therefore approximately equal to the 40 requests
  issued. **The prescribed burst sits on the boundary rather than clearing it.**

Making the burst concurrent removes the ambiguity, because a burst that finishes in seconds cannot
be meaningfully refilled while it runs:

```
120 requests, 30-way concurrency
start 09:52:29.936Z   end 09:52:33.932Z      (4.0 s -> only ~2 tokens refilled)
429 count: 89
401 count: 31
first 429: request #31
```

**31 allowed against a configured capacity of 30 is the result that makes this conclusive.** It
matches `RATE_LIMIT_BURST=30` plus the ~2 tokens the 4-second window replenishes, and it reproduced
on the second, independent 200-request burst (also exactly 31 allowed). It also shows the burst was
served by a **single instance** — two instances would have admitted ~60.

This is the same class of finding as `02-DEPLOY-LOG.md` § *Row 7 required a different method than
the plan prescribes*: the security property is real, the prescribed probe was the wrong instrument.
**A future runbook should specify a concurrent burst**, not a sequential loop.

### The 429, byte for byte

```
HTTP/1.1 429 Too Many Requests
content-type: application/json
retry-after: 2
Content-Length: 24
```

```
00000000: 7b22 6572 726f 7222 3a22 7261 7465 5f6c  {"error":"rate_l
00000010: 696d 6974 6564 227d                      imited"}
```

Every one of the 89 rejections carried an identical 24-byte body — `sort -u` over all of them
returns exactly one line. The body never grew a field echoing the presented credential or an
exception detail (T-07-02). Observed `Retry-After` values were `1` and `2` seconds, consistent with
`max(1, int(wait) + 1)` at a 0.5 tokens/second refill.

### Row 2 document, verbatim

```json
{"resource":"https://brett-792870654598.us-central1.run.app/mcp","authorization_servers":["https://quiet-fireplace-16-staging.authkit.app"],"bearer_methods_supported":["header"]}
```

`resource` is byte-identical to `MCP_RESOURCE_URL` on the serving revision, and
`authorization_servers` is a single entry naming the real AuthKit tenant — the Phase 2
`example.authkit.app` placeholder is long gone.

### Rows 3, 4 and 8 challenge, verbatim

```
www-authenticate: Bearer error="invalid_token", error_description="Authentication required", resource_metadata="https://brett-792870654598.us-central1.run.app/.well-known/oauth-protected-resource/mcp"
```

Body for rows 3, 4 and 8, identical in all three:

```json
{"error": "invalid_token", "error_description": "Authentication required"}
```

The challenge is **byte-identical to the string `02-DEPLOY-LOG.md` recorded against
`brett-00005-gcx` and again against `brett-00006-sg2`.** It has now survived the AuthKit cutover and
this redeploy unchanged, which is what lets Claude rediscover the RFC 9728 document without
re-consent. The server also remains a non-oracle: "absent credential" and "malformed credential"
are indistinguishable in both status and body (T-02-04).

### The burst was run deliberately, against production, outside any coaching session

Rows 5–8 trip the **real** limiter on the **live** service. This is accepted risk T-07-30, and the
mitigating facts were confirmed rather than assumed:

- Recovery is ~2 seconds — the bucket refills at 30/minute, so a legitimate connector call
  immediately behind the burst waits at most one `Retry-After`.
- `/health` stayed `200` throughout, so Cloud Run's liveness probe was never at risk of marking the
  revision unhealthy.
- Discovery stayed `200` throughout, so a connector mid-handshake would not have seen "Couldn't
  reach the MCP server".
- Row 8 proves full recovery 90 seconds later.
- No coaching session was in progress: the connector round-trip (Task 3) had not yet been run.

## Known limitations

1. **The bucket is per-process, and the service allows 2 instances.** Service-level
   `run.googleapis.com/maxScale` reads `2` on the serving revision, so the service-wide ceiling is
   up to **2 × 30 = 60 requests/minute**, not 30. Accepted deliberately (`app/middleware.py`): making
   one single-user connector's limit exact would mean adding Redis, doubling the failure surface and
   the bill of the component whose purpose is to protect against cost. Both bursts here were in fact
   served by a single instance (exactly 31 admitted each time), so the 2× multiplier is a documented
   worst case, not an observed one.
   - Note the **revision**-level annotation `autoscaling.knative.dev/maxScale` reads `20`. That is a
     Cloud Run per-revision default and is superseded by the service-level `2` that
     `scripts/deploy-cloud-run.sh --max=2` sets. It read `20` identically before this deploy, so it
     is pre-existing and was not introduced here. Recorded because a future reader grepping for
     `maxScale` will find both numbers and needs to know which one binds.
2. **`--min=1` was silently reset to `0` by this deploy.** See the deviation section below. This is
   the one item that needs an action before Task 3.
3. **5 of 200 requests in the second burst returned no status line at all** (200 header files
   written, 195 containing an HTTP status). These are client-side connection failures under 40-way
   concurrency from a single laptop, not service responses; 195 requests were answered
   (164 × `429` + 31 × `401`). Recorded so the tally is reconcilable rather than appearing to lose
   requests.
4. **The authenticated 13-tool proof is not in this matrix.** By design — see *Why the authenticated
   tool-list proof is not a curl row* above. It is split between Task 3 and plan 07-09.

## Deviations

### 1. [Rule 3 — blocking] The deploy reset `--min=1` to `--min=0`, undoing D-06f

**Found during:** Task 1, step 6, comparing the pre- and post-deploy service annotations.

**Issue:** `scripts/deploy-cloud-run.sh` passes `--min="${BRETT_MIN_INSTANCES:-0}"` unconditionally.
`BRETT_MIN_INSTANCES` was not set, so the deploy wrote `--min=0` over the service-scoped `--min=1`
that plan 02-07 applied under D-06f.

```
PRE : run.googleapis.com/minScale = "1"
POST: run.googleapis.com/minScale = absent   (i.e. 0)
```

**Why it matters:** `02-DEPLOY-LOG.md` measured a genuine cold start at **7.53 s** against Claude's
documented **10-second** discovery budget — roughly 25% headroom — and concluded that `--min=1` is
"a **hard prerequisite** for any Claude connector test". Task 3 *is* a Claude connector test. At
`--min=0`, if the service scales to zero before the developer opens Claude, the connector may
present as "Couldn't reach the MCP server" for reasons that have nothing to do with this redeploy.

**Attempted fix:** re-applying the service-scoped flag, which needs no rebuild and was
**pre-authorised by the developer on 2026-08-27** (recorded twice in `02-DEPLOY-LOG.md` with an
explicit "Plan 02-07 must NOT re-ask"):

```bash
gcloud run services update brett --project=brett-fitness --region=us-central1 --min=1
```

**Outcome: BLOCKED.** The command was denied by this session's permission classifier. The denial was
respected rather than worked around — the same choice `02-DEPLOY-LOG.md` records for its own denied
secret read. **This command must be run before Task 3.** Only `--min` may appear on that command
line: `gcloud run services update` removes any env or secret flag it does not list, which would drop
`DATABASE_URL` and 500 the next request (T-02-18).

Not a code change and not a plan change — restoring state this deploy incidentally cleared.

### 2. [Rule 1 — method] Row 5's prescribed sequential burst does not trip the limiter

Documented in full under *Row 5 required a different method than the plan prescribes*. The
prescribed 40-request sequential loop was replaced with a concurrent burst after the sequential one
produced zero `429`s. The security property is proven; the plan's instrument was not sensitive
enough.

### 3. [Documentation] The plan's "before" revision was wrong

`brett-00006-sg2`, not `brett-00005-gcx`. Documented at the top of this file. Caught by following
the plan's own "re-confirmed, never assumed" instruction.
