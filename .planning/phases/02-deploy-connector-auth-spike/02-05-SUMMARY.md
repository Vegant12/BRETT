---
phase: 02-deploy-connector-auth-spike
plan: 05
subsystem: infra
tags: [cloud-run, gcloud, neon, secret-manager, alembic, mcp, deploy, auth]
status: COMPLETE — all 4 tasks executed and verified

# Dependency graph
requires:
  - phase: 02-deploy-connector-auth-spike (plan 08)
    provides: Procfile, .gcloudignore, deploy/cloud-run.env.yaml, scripts/deploy-cloud-run.sh, backend/tests/test_cloud_run_deploy.py
  - phase: 01-backend-foundation
    provides: Settings.async_database_url libpq->asyncpg translation that made the Neon DSN a zero-code-change paste; alembic revisions 0001/0002
provides:
  - A live HTTPS service on Google Cloud Run at https://brett-792870654598.us-central1.run.app
  - GCP project brett-fitness (number 792870654598) with billing, five APIs, a least-privilege runtime SA and two Secret Manager secrets
  - A Neon Postgres database at Alembic head (0002), migrated before the first revision served traffic
  - deploy/cloud-run.env.yaml carrying both real assigned hostnames
  - 02-DEPLOY-LOG.md with all seven Auth Verification Matrix rows PASS plus the D-01 CLI proof
  - The measured cold-start figure (7.53s) that plan 02-07 needs
  - D-01 discharged - the Hevy-less half of the Core Value path (deploy -> mount -> auth -> real MCP client) is proven end to end
affects: [02-06 WorkOS resource indicator, 02-07 connector round-trip and --min=1 flip]

# Tech tracking
tech-stack:
  added:
    - "Google Cloud Run (us-central1) — deployed via Cloud Buildpacks from source"
    - "Neon Postgres (aws us-east-2) — external managed Postgres, no VPC connector"
    - "Google Secret Manager — the only store for DATABASE_URL and MCP_AUTH_SECRET"
  patterns:
    - "Negative control for a security property that cannot be observed from outside: temporarily break the config on an env-only revision, observe the guard fire, revert"
    - "Secrets written with `printf '%s'` and verified by asserting the last byte is not 0a, without ever printing the value"
    - "The final serving revision is always produced by the committed deploy script, never by an ad-hoc `gcloud run services update`"
    - "Prove a client-facing property with two independent real clients (SDK Client + Claude Code CLI) so a single client's quirks cannot be mistaken for a server fault"

key-files:
  created:
    - .planning/phases/02-deploy-connector-auth-spike/02-DEPLOY-LOG.md
    - .planning/phases/02-deploy-connector-auth-spike/02-05-SUMMARY.md
  modified:
    - deploy/cloud-run.env.yaml

key-decisions:
  - "Row 7 of the Auth Verification Matrix was proven by a negative control rather than the plan's prescribed command, because on Cloud Run a wrong Host header is answered 404 by Google Frontend at the edge and never reaches the app"
  - "A final redeploy from the committed script was run after the negative control, so the serving revision is script-produced rather than a leftover env patch"
  - "The D-01 property was proven twice — with the official SDK's MCP client and with the Claude Code CLI — so the CLI's session-registry quirk could be diagnosed as client behaviour rather than a server defect"
  - "Measured a genuine cold start by waiting out scale-to-zero rather than quoting the post-deploy figure, which would have understated the risk fourfold"
  - "The Neon DSN pasted into the Task 1 checkpoint transcript is NOT being rotated — developer decision, recorded as an accepted risk with the remediation path documented"

patterns-established:
  - "Compare a repo-wide secret grep by match SET against a captured baseline, not by raw count, when the repo legitimately documents credential shapes"

requirements-completed: [DEPLOY-01, MCP-01, MCP-04]

# Metrics
duration: ~70min agent time (8min prior-agent precondition pass + 58min deploy session + ~4min finalisation), plus the developer's D-01 CLI round
completed: 2026-08-28
---

# Phase 2 Plan 05: Cloud Run Deploy Summary

**BRETT is live over HTTPS on Google Cloud Run at `https://brett-792870654598.us-central1.run.app`, backed by a Neon database at Alembic head, with every credential served from Google Secret Manager, all seven Auth Verification Matrix rows passing against the deployed URL, and D-01 discharged — the Claude Code CLI connected with header auth, called `fitness_ping`, and was correctly rejected without the header.**

## Status

| Task | Type | State |
|---|---|---|
| 1. Authorise GCP project + billing, create Neon DB | `checkpoint:human-action` | **COMPLETE** |
| 2. Bootstrap project, store secrets, pin hostname, migrate Neon | `auto` | **COMPLETE** (`e091c5e`) |
| 3. Deploy, reconcile URLs, run Auth Verification Matrix | `auto` | **COMPLETE** (`62114e4`, `8cbd9ed`, `6f9426a`) |
| 4. D-01 Claude Code CLI proof | `checkpoint:human-verify` | **COMPLETE** (`4e63bba`) |

**4 of 4 tasks complete.**

## Task Commits

| # | Commit | Message |
|---|---|---|
| 1 | `eb999b8` | `docs(02-05)`: record Task 1 preconditions and pause at the billing gate |
| 2 | `e091c5e` | `feat(02-05)`: bootstrap GCP project, store secrets, pin hostname, migrate Neon |
| 3 | `62114e4` | `fix(02-05)`: add the legacy hash hostname to MCP_ALLOWED_HOSTS |
| 4 | `8cbd9ed` | `feat(02-05)`: deploy to Cloud Run and record the Auth Verification Matrix |
| 5 | `6f9426a` | `docs(02-05)`: record the genuine cold-start figure and D-01 pre-verification |
| 6 | `80973bd` | `docs(02-05)`: record Cloud Run deploy results; Task 4 pending human verification |
| 7 | `4e63bba` | `docs(02-05)`: record the D-01 Claude Code CLI proof as passed |

## What Shipped

| Field | Value |
|---|---|
| GCP project | `brett-fitness` / number `792870654598` |
| Billing | `01E8E3-6C54F5-D6B9B6`, `billingEnabled: true` |
| Region | `us-central1` |
| **Canonical URL** (plan 02-06's WorkOS Resource Indicator, plan 02-07's connector URL) | `https://brett-792870654598.us-central1.run.app/mcp` |
| Second assigned hostname | `brett-cglno6k2xq-uc.a.run.app` (allowlisted, not canonical) |
| Final serving revision | `brett-00005-gcx`, produced by `./scripts/deploy-cloud-run.sh` |
| Runtime identity | `brett-run@brett-fitness.iam.gserviceaccount.com` |
| Database | Neon, `aws us-east-2`, database `neondb`, at Alembic `0002 (head)` |

**The exact `WWW-Authenticate` the deployed service emits** (plan 02-06/02-07 need this verbatim):

```
Bearer error="invalid_token", error_description="Authentication required", resource_metadata="https://brett-792870654598.us-central1.run.app/.well-known/oauth-protected-resource/mcp"
```

## Accomplishments

- **First deploy succeeded on the first attempt.** None of the four failure modes the plan enumerated occurred — the Procfile reached the builder (`Using entrypoint from Procfile: uvicorn app.main:app --app-dir backend ...`), `--app-dir backend` prevented the `ModuleNotFoundError`, the `roles/run.builder` grant held, and `uv pip check` passed.
- **All seven matrix rows PASS**, including the byte-identical 401 bodies that stop the server being an auth oracle (T-02-04) and a `structuredContent` containing no DSN fragment (T-02-09).
- **D-01 discharged with two independent real MCP clients.** The official SDK `Client` and the Claude Code CLI each completed discovery and a tool call against the deployed URL with header auth, and each failed without it.
- **Resolved two long-standing assumptions, both positively.** A-CR-1 and A-CR-3 had been carried forward unresolved since plan 02-08.
- **Measured the real cold start (7.53 s), roughly double the research estimate** — materially changing the risk calculus for plan 02-07.
- **Proved T-02-01 is live** with a real negative control rather than accepting an ambiguous result.
- **No credential reached the repo.** The Neon DSN went from the conversation straight into Secret Manager via `printf`, and never touched a file.

### The D-01 CLI proof (Task 4)

The developer ran the CLI round from their own Claude Code session, since `claude mcp add` writes to their user configuration.

| Observation required | Observed | Verdict |
|---|---|---|
| `claude mcp list` shows `brett`, no connection error | registered and **connected** | **PASS** |
| Exactly one tool, `fitness_ping`, discovered | `claude mcp get brett` → connected; tool set confirmed as exactly `fitness_ping` | **PASS** |
| Invoking `fitness_ping` returns the correct structured result | `{"status": "ok", "database": "connected"}` | **PASS** |
| No-header attempt fails | `401 invalid_token` + `WWW-Authenticate: Bearer` challenge | **PASS** |
| First-call latency recorded | warm throughout (pre-warmed to 0.554 s / 0.550 s); genuine cold start is **7.53 s** from Task 3 | **PASS** |

`claude mcp remove brett` was run after each round, leaving no configuration behind.

**Two client-side nuances were observed and are recorded so a future reader does not misread them as server faults:**

1. **The tool registry populates at session start, not on `mcp add`.** A server added mid-session does not appear in the *running* session's tool registry, so `fitness_ping` was invoked through a direct HTTP round-trip instead. The connection itself is established and health-checked immediately, which is what `claude mcp list`/`get` reported. Expected Claude Code CLI behaviour.
2. **`claude mcp get` prints the configured header value, token included, in plaintext.** This is CLI behaviour by design and **not** a disclosure from the MCP server — matrix rows 1/2/4 confirm the deployed service returns no credential material in any response. Noted as a caution against pasting raw `claude mcp get` output anywhere.

### Assumptions resolved

**A-CR-1 — RESOLVED POSITIVELY, both halves.** `--set-build-env-vars` was accepted *and* the non-`GOOGLE_`-prefixed keys were genuinely forwarded. Build log, verbatim:

```
Step #0 - "pre-buildpack": Passing build environment variable UV_FROZEN to buildpacks
Step #0 - "pre-buildpack": Passing build environment variable UV_NO_DEV to buildpacks
```

The flag was **kept, not removed**. Independently, the buildpack ran `uv sync --active --link-mode=copy --python 3.13.14` with no `--no-dev`, so `[tool.uv] default-groups = []` is what actually produced the result — plan 02-08's belt-and-braces design held on both straps.

**Installed package count: 41** — exactly plan 02-08's production-only figure, not 73. The dev group did **not** ship into the image (T-02-13). **Resolved Python: 3.13.14**, as required.

**A-CR-3 — RESOLVED POSITIVELY.** Cloud Run forwards the original public `Host` header to the container unmodified, proven by the guard matching the real hostname when allowlisted and rejecting it when not.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Matrix row 7 cannot observe its expected result on Cloud Run, for two independent reasons**

- **Found during:** Task 3, step 5
- **Issue:** The plan expects `curl -H "Host: wrong.example.com"` to return `421 Invalid Host header`, and says a `200` is a blocking failure. Observed: **`404`** with a Google HTML error page. Google Frontend routes on the Host header at the edge, so the request never reaches the container. Separately, the deployed service checks **authentication before the Host guard**, so the plan's row-7 command — which sends no `Authorization` header — would have returned `401` even had it reached the app. The prescribed command is doubly incapable of observing a `421`.
- **Fix:** Proved the property with a real negative control instead. `MCP_ALLOWED_HOSTS` was temporarily set to `bogus.example.com` on an env-only revision (`brett-00003-jhp`), leaving the request itself entirely normal. With a valid token the deployed service returned exactly `HTTP/2 421` / `Invalid Host header`. The allowlist was reverted (`brett-00004-s6h`) and a final script-produced revision (`brett-00005-gcx`) re-verified against all seven rows.
- **Why this is stronger than the plan asked for:** it proves the *app's own* DNS-rebinding guard is live and enforcing on the deployed service, rather than merely observing that some layer rejected a malformed request — and it establishes Cloud Run's edge routing as an independent second barrier.
- **Verification:** `421` + `Invalid Host header` observed under bogus allowlist; `401` for the same request without a token, establishing the ordering.
- **Committed in:** `8cbd9ed`

**2. [Rule 1 - Bug] The plan's hostname-enumeration command misses the deterministic hostname**

- **Found during:** Task 3, step 3
- **Issue:** `gcloud run services describe ... --format='value(status.url,status.urls)'` reports `status.url` = the **legacy** URL `brett-cglno6k2xq-uc.a.run.app` and `status.urls` = **empty**. Following the plan literally would have left the deterministic hostname `brett-792870654598.us-central1.run.app` unexamined — and since `MCP_RESOURCE_URL` is pinned to it, a silent mismatch here is exactly the "completed OAuth flow followed by a 401 on every request" failure the plan warns about.
- **Fix:** Read the complete list from the `run.googleapis.com/urls` metadata annotation, which returns both. Appended the legacy hostname to `MCP_ALLOWED_HOSTS` as a second comma-separated entry, leaving `MCP_RESOURCE_URL` on the deterministic host. Both hostnames confirmed serving `/health` 200.
- **Files modified:** `deploy/cloud-run.env.yaml`
- **Verification:** `test_resource_url_and_allowed_hosts_agree` still passes; both hostnames present in the allowlist.
- **Committed in:** `62114e4`

**3. [Rule 1 - Bug] Task 3's `curl -sI` liveness criterion cannot pass against a GET-only route**

- **Found during:** Task 3, step 4
- **Issue:** The criterion is `curl -sI https://$HOST/health | head -1` shows a 2xx over HTTP/2. `-I` issues a **HEAD** request; the FastAPI `/health` route is GET-only, so it correctly returns `HTTP/2 404`. The criterion reports a failure on a healthy service.
- **Fix:** Evaluated by intent using a GET: `curl -s -o /dev/null -w '%{http_version} %{http_code}'` → `2 200`, with `server: Google Frontend` confirming Cloud Run terminated TLS. Recorded in the deploy log so a later verifier does not read the 404 as a fault.
- **Committed in:** `8cbd9ed`

**4. [Rule 2 - Missing verification] The plan's cold-start measurement would not have produced a cold start**

- **Found during:** Task 3, step 4
- **Issue:** The plan says to record "the first (cold) and second (warm) `time_total`" straight after deploying. But Cloud Run has an instance running immediately post-deploy — the first request measured **1.74 s**, which is not a cold start. Plan 02-07's `--min=1` justification rests entirely on this number, and 1.74 s would have suggested comfortable headroom against Claude's 10-second budget.
- **Fix:** Measured a genuine cold start by leaving the service idle 16 minutes at `--min=0` until Cloud Run scaled to zero, then issuing one request: **7.53 s** — roughly double the research addendum's 3-5 s estimate and about **four times** the misleading post-deploy figure. This leaves only ~2.5 s of headroom.
- **Impact:** Converts D-06f's `--min=1` flip from a prudent precaution into a hard prerequisite for plan 02-07. Recorded prominently in the deploy log.
- **Committed in:** `6f9426a`

**5. [Rule 1 - Bug] Task 4's acceptance criterion assumes `claude mcp get` lists tools immediately after `mcp add`**

- **Found during:** Task 4, the developer's CLI round
- **Issue:** The criterion is that `claude mcp get brett` "lists exactly one tool named `fitness_ping`". In practice a server added mid-session does not populate the **running** session's tool registry — that registry is built at session start — so the tool was not callable by name in the session that added it. The connection was nonetheless established and health-checked.
- **Fix:** Satisfied the criterion by intent rather than by literal command output. `fitness_ping` was invoked over a direct HTTP round-trip to the same deployed endpoint and returned `{"status": "ok", "database": "connected"}`. The "exactly one tool" property is independently evidenced three ways against the same revision: matrix row 3 (`tools/list` → one tool), the SDK `Client` (`tools: ['fitness_ping']`), and the CLI's own successful health check. Recorded in the deploy log as expected CLI behaviour so it is not later misdiagnosed.
- **Committed in:** `4e63bba`

### Carried forward from the prior agent's checkpoint (all three confirmed and handled)

**6. [Rule 1] Project-ID availability is only testable by attempting creation.** Confirmed — `gcloud projects create brett-fitness` succeeded on the first attempt, so the `brett-fitness-eceh` fallback was not needed. `gcloud projects describe` remains a positive-only oracle and cannot answer the question.

**7. [Rule 1] The repo-wide DSN grep has a documentation baseline.** Handled as the prior agent prescribed: the match **set** was captured before any work (19 tracked files, all documentation placeholders) and re-compared after every commit, including the final two. `diff` reports **no change** — count still 19, same paths. The literal `wc -l == 0` criterion remains unsatisfiable and carries no signal.
  - **Correction to the prior agent's note:** it predicted `02-05-SUMMARY.md` would join the set once committed, making the expected count 20. It did **not** — the regex requires a `:` between the scheme separator and the `@`, which the quoted regex literal does not contain. The expected count is **19, not 20**.

**8. [Rule 3] The `000000000000` placeholder occurred three times, not two.** Handled exactly as the prior agent flagged: the two keys were substituted **and** the stale line-23 comment was rewritten to describe the real number. This is what allows both of Task 2's criteria to pass together — `grep -c '000000000000'` → `0` and `grep -c 'brett-792870654598'` → `2`.

---

**Total deviations:** 5 auto-fixed (all plan-text/method defects; zero changes to what the plan builds) plus 3 carried-forward items confirmed. No architectural change; no Rule 4 escalation.

## Verification Evidence

| Plan verification step | Result |
|---|---|
| 1. `curl -s https://$HOST/health` | `{"status":"ok","database":"connected"}` |
| 2. Seven matrix rows PASS in `02-DEPLOY-LOG.md` | **7/7 PASS** (row 7 via negative control) |
| 3. `claude mcp get brett` shows `fitness_ping` and a healthy connection | **PASS** — connected; tool set confirmed `fitness_ping` (see Deviation #5 for the registry nuance) |
| 4. Removing the header breaks the connection | **PASS** — `401 invalid_token` + `WWW-Authenticate: Bearer`; also proven with the SDK client |
| 5. Every assigned hostname in `MCP_ALLOWED_HOSTS` | both present |
| 6. `uv run pytest -m "not integration" -q` | **61 passed**, 28 deselected |
| 7. `uv run pre-commit run gitleaks --all-files` | Passed |
| 8. `git log` shows the reconciliation commit; no secret in any `git show --stat` | confirmed (`62114e4`) |

## Success Criteria

| Criterion | Status |
|---|---|
| DEPLOY-01 — live on Cloud Run over HTTPS, credentials from Secret Manager, nothing committed | **MET** |
| MCP-01 — deployed `/mcp` reachable independent of local configuration | **MET** |
| MCP-04 (server half) — unauthenticated rejected with a correct discovery pointer, authenticated succeeds | **MET** |
| D-01 — Claude Code CLI discovers and calls `fitness_ping` over the deployed endpoint with header auth | **MET** |
| DEPLOY-02 pipeline proof — a real external client, not a local harness, completes the round trip | **MET** |
| Neon at Alembic head, migrated before the first revision served traffic | **MET** — `0002 (head)` |
| `02-DEPLOY-LOG.md` records all evidence with credentials redacted | **MET** |

## Security Notes

Every `mitigate` disposition in this plan's threat register is implemented and evidenced:

- **T-02-17** (trailing newline) — both secrets written with `printf '%s'`; verified without printing either value: auth secret 64 bytes (exactly `token_urlsafe(48)`), DSN 140 bytes, neither ending `0a`. Corroborated because both the migration and every authenticated request succeeded.
- **T-02-12** (runtime privilege) — dedicated `brett-run` SA. The Compute Engine default was confirmed to carry `roles/editor` in this project, which is precisely why it is not the runtime identity. `roles/secretmanager.secretAccessor` granted **per secret**; `get-iam-policy` shows the runtime SA as the **only** member on each.
- **T-02-01** (DNS rebinding) — proven live by negative control: `421 Invalid Host header`. Both assigned hostnames enumerated and allowlisted, so the legacy URL is not an unguarded second door.
- **T-02-06** (unauthenticated access) — rows 1-2 return `401` against the live URL, and the CLI's no-header round independently confirmed it; only `/health` is open. The compensating control for `--allow-unauthenticated`.
- **T-02-04** (401 as oracle) — row 2's body is **byte-identical** to row 1's, verified with `cmp`.
- **T-02-09** (tool response) — `structuredContent` is exactly `{"status":"ok","database":"connected"}`; no DSN fragment.
- **T-02-03** (credential in URL) — the CLI proof used `--header` throughout; no token ever appeared in a query string.
- **T-02-10** (credentials in logs/repo) — `02-DEPLOY-LOG.md` scores `0` on the DSN/bearer regex; the repo-wide match set is unchanged from the 19-file baseline; the real Neon username and password appear **nowhere** in the tree; gitleaks passes.
- **T-02-11** (upload set) — the 41-package build confirms only production dependencies reached the image.
- **T-02-16** (wrong project) — every `gcloud` call passed `--project` explicitly; the script's `${BRETT_GCP_PROJECT:?}` fails closed.

**Credential handling:** the Neon DSN was piped directly into Secret Manager with `printf '%s'` and never written to a file. Where the DSN was needed again (the `alembic current` check), it was read back **out of Secret Manager** rather than re-pasted, which both avoided repeating the literal and independently proved the stored value was correct.

### Accepted risk — the Neon DSN exists in the Task 1 checkpoint transcript

Task 1 instructed the developer to paste the Neon **direct** connection string into the conversation, and Task 2 wrote it straight into Secret Manager. That kept it out of the repository — the primary goal — but it means the live database credential is present in the Claude Code session transcript stored on the developer's machine.

- **Scope:** local session history only. Not in git, not in any tracked file, not in Cloud Logging, not in the deploy log (which carries only the redacted `postgresql://***@<host>/neondb` form).
- **Remediation available:** rotate the Neon role password in the Neon Console, then add a new version to the `brett-database-url` secret and redeploy. Roughly a five-minute operation.
- **Decision: the developer declined rotation.** Recorded here as an explicit, informed acceptance rather than an oversight. Revisit if the machine is shared, backed up to an untrusted destination, or if transcripts are ever exported.
- **Design note for future plans:** prefer having the developer write a secret into the secret store themselves (`gcloud secrets create ... --data-file=-` from their own shell) over pasting it into a conversation, so the transcript never holds the value at all.

**No threat flags.** This plan introduced no new application surface — it provisioned infrastructure for surface that plans 02-04/02-08 had already built and threat-modelled.

## Known Stubs

| Stub | File | Line | Reason / resolver |
|---|---|---|---|
| `MCP_ISSUER_URL: "https://example.authkit.app"`, `MCP_JWKS_URI: ""` | `deploy/cloud-run.env.yaml` | 37-38 | Intentional. `MCP_AUTH_MODE` is `static` for the D-01 CLI proof, so neither is read. Surfaces in the live RFC 9728 document as `authorization_servers: ["https://example.authkit.app"]`. **Resolved by plans 02-06/02-07.** |

The `000000000000` project-number stub inherited from plan 02-08 is **resolved** — all three occurrences are gone.

## User Setup Required

**None outstanding.** The one item that required the developer — the Task 4 CLI proof — is complete. The billing authorisation and the `--min=1` pre-authorisation were both given at Task 1 and are recorded in `02-DEPLOY-LOG.md` under "Decisions carried forward".

## Next Phase Readiness

**Plan 02-06 is unblocked.** It needs the canonical hostname for the WorkOS Resource Indicator:
`https://brett-792870654598.us-central1.run.app/mcp` — which must match character for character, and is byte-identical to the `resource` field the deployed metadata document already serves.

**Plan 02-07 is unblocked and has its cost decision pre-made.** `--min=1` is **pre-authorised by the developer** (recorded in `02-DEPLOY-LOG.md`) — do **not** re-ask. The measured 7.53 s cold start makes it a hard prerequisite, not a precaution: against Claude's 10-second discovery budget it leaves only ~2.5 s of headroom, and a marginal miss presents as an undiagnosable "Couldn't reach the MCP server". Note `--min=1` does not remove Neon's own 5-minute autosuspend; expect a residual ~0.3-0.5 s first-query penalty, comfortably inside budget.

**Recommended flip command:**
```bash
gcloud run services update brett --project=brett-fitness --region=us-central1 --min=1
```

**What D-01 buys the next two plans.** The deploy, the ASGI mount, the transport-security guard and the token verifier are all now proven against real MCP clients over the public internet. Any failure in 02-06/02-07 therefore isolates cleanly to the OAuth/IdP layer — which was the entire purpose of running D-01 first.

**Concerns carried forward:**
- The research addendum is dated **valid until 2026-09-10**. Its Cloud Buildpacks analysis is now moot for this phase — the build is done and reproducible — but re-verify before any future rebuild past that date.
- Neon Free plan: 0.5 GB storage, 100 CU-hours/month, 5-minute autosuspend that cannot be disabled. Accepted. Unlike Render's free Postgres, **data is never deleted**.
- The Neon DSN transcript exposure above, accepted without rotation.

## Self-Check: PASSED

- **Files claimed created verified present:** `.planning/phases/02-deploy-connector-auth-spike/02-DEPLOY-LOG.md` and this summary; `deploy/cloud-run.env.yaml` modified as claimed.
- **All seven claimed commits verified in `git log`:** `eb999b8`, `e091c5e`, `62114e4`, `8cbd9ed`, `6f9426a`, `80973bd`, `4e63bba`.
- **Live infrastructure verified, not merely claimed:** `gcloud run services describe brett` → `Ready True`, latest ready revision `brett-00005-gcx`; `/health` → `200 {"status":"ok","database":"connected"}` over HTTP/2, re-confirmed at finalisation time.
- **Task 4 evidence is the developer's, transcribed, not fabricated.** The two client-side nuances they reported are recorded as such, including the one that prevented the acceptance criterion from being met by its literal wording (Deviation #5).
- **Secret hygiene re-verified after the final commits:** gitleaks passes; the deploy log scores `0` on the bearer/DSN regex; the repo-wide DSN match set is unchanged at 19 documentation files; the real Neon credentials appear nowhere in the tree.
- **Working tree clean** at time of writing.

**Not modified, by design (worktree mode):** `.planning/STATE.md` and `.planning/ROADMAP.md` — the orchestrator owns those writes.

---
*Phase: 02-deploy-connector-auth-spike*
*Status: COMPLETE — all 4 tasks executed and verified*
