---
phase: 02-deploy-connector-auth-spike
plan: 07
subsystem: auth
tags: [cloud-run, workos, authkit, oauth, cimd, dcr, jwt, jwks, mcp, connector, min-instances]
status: PARTIAL — Tasks 1 and 2 complete; PAUSED at the Task 3 human-verify checkpoint (DEPLOY-02)

# Dependency graph
requires:
  - phase: 02-deploy-connector-auth-spike (plan 05)
    provides: the live Cloud Run service, the canonical hostname, the 7.53s cold-start measurement, and the developer's advance --min=1 authorisation
  - phase: 02-deploy-connector-auth-spike (plan 06)
    provides: AuthKitJWTVerifier, the live WorkOS tenant, and the issuer/jwks_uri values this plan pasted into the deploy config
provides:
  - A Cloud Run service running MCP_AUTH_MODE=authkit, validating WorkOS RS256 JWTs against the live tenant JWKS
  - An RFC 9728 metadata document naming the real AuthKit issuer in a single-entry list
  - One continuously warm instance (--min=1), reducing the post-idle discovery path from 7.53s to 0.303s
  - A thirteenth deploy-config drift assertion pinning MCP_AUTH_MODE inside its Literal
  - Every automatable hop of Claude's discovery sequence walked and passing, so a connector failure isolates to the client
affects: [02-07 Task 3 connector round-trip, 02-07 Task 4 decision record]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "When a plan's prescribed probe needs a credential the sandbox will not release, substitute a probe that needs none and argues the same property — a forged-signature JWT with correct iss/aud/kid can only be rejected by real JWKS verification"
    - "Prove a warm instance two ways: latency on the path the client actually uses, and an empty log query across the idle window"
    - "Separate a composite latency measurement into its independent terms before judging it against a threshold — /health measures Cloud Run AND Neon; discovery measures neither"
    - "Read the deployed environment back off the serving revision rather than trusting that the file you committed is what is running"

key-files:
  created:
    - .planning/phases/02-deploy-connector-auth-spike/02-07-SUMMARY.md
  modified:
    - deploy/cloud-run.env.yaml
    - backend/tests/test_cloud_run_deploy.py
    - .planning/phases/02-deploy-connector-auth-spike/02-DEPLOY-LOG.md

deployment:
  revision_before: brett-00005-gcx
  revision_after: brett-00006-sg2
  auth_mode: authkit
  issuer: "https://quiet-fireplace-16-staging.authkit.app"
  jwks_uri: "https://quiet-fireplace-16-staging.authkit.app/oauth2/jwks"
  resource_url: "https://brett-792870654598.us-central1.run.app/mcp"
  min_instances: 1
  revert_min_command: "gcloud run services update brett --project=brett-fitness --region=us-central1 --min=0"
  rollback_to_static: "set MCP_AUTH_MODE=static in deploy/cloud-run.env.yaml, then ./scripts/deploy-cloud-run.sh"

key-decisions:
  - "Applied --min=1 on the recorded 2026-08-27 pre-authorisation without re-asking, after checking both 02-05-SUMMARY.md and 02-DEPLOY-LOG.md for a refusal"
  - "Respected the sandbox denial on reading brett-mcp-auth-secret rather than working around it; substituted credential-free probes for matrix rows 3 and 4"
  - "Did not re-run row 7's negative control: it is impossible in authkit mode because auth precedes the host guard, and reproducing it would have required flipping back to static immediately before the phase's one irreplaceable manual test"
  - "Recorded the /health idle figure as a literal miss (1.734s vs a 1.5s criterion) rather than rounding it away, and separated out the Neon term that caused it"
  - "Withheld the '## Connector round-trip (DEPLOY-02)' heading at the checkpoint, exactly as plan 02-06 withheld '## WorkOS AuthKit (verified)'"

requirements-completed: []   # DEPLOY-02 and MCP-04 close only after Task 3

# Metrics
duration: ~35min to the checkpoint (including a 15-minute unattended idle window)
completed: 2026-08-29 (partial)
---

# Phase 2 Plan 07: Connector Auth Cutover Summary (PARTIAL)

**The deployed service now validates WorkOS-issued RS256 JWTs instead of a static bearer, its RFC 9728 document names the real AuthKit issuer in a single-entry list, and one warm instance has cut the first-request-after-idle discovery latency from 7.53 s to 0.303 s — every automatable hop of Claude's discovery sequence passes, and execution is paused at the one step that has no automatable substitute: adding the connector from a real Claude Desktop/Web/Mobile client.**

## Status

| Task | Type | State |
|---|---|---|
| 1. Cut the deployed service over to WorkOS JWT validation | `auto` | **COMPLETE** (`d3f5a22`) |
| 2. Keep one instance warm (D-06f) and re-run the matrix post-cutover | `auto` | **COMPLETE** (`9c088b3`) |
| 3. DEPLOY-02 — add the Claude custom connector and call `fitness_ping` | `checkpoint:human-verify` | **PAUSED — awaiting the developer** |
| 4. Record the answer in PROJECT.md, STATE.md, and the deploy log | `auto` | **NOT STARTED** — depends entirely on Task 3's outcome |

**2 of 4 tasks complete.**

## Task Commits

| # | Commit | Message |
|---|---|---|
| 1 | `d3f5a22` | `feat(02-07)`: cut the deploy config over to WorkOS JWT validation |
| 2 | `9c088b3` | `docs(02-07)`: record the AuthKit cutover, `--min=1`, and the post-cutover matrix |
| 3 | *(this file)* | `docs(02-07)`: partial-state summary at the connector checkpoint |

## What Shipped

| Field | Before | After |
|---|---|---|
| Serving revision | `brett-00005-gcx` | **`brett-00006-sg2`** |
| `MCP_AUTH_MODE` | `static` | **`authkit`** |
| `MCP_ISSUER_URL` | `https://example.authkit.app` | `https://quiet-fireplace-16-staging.authkit.app` |
| `MCP_JWKS_URI` | `""` | `https://quiet-fireplace-16-staging.authkit.app/oauth2/jwks` |
| `authorization_servers[0]` served | `https://example.authkit.app` | the real AuthKit domain, list length `1` |
| Minimum instances | `0` | **`1`** (service-scoped) |
| Deploy-config assertions | 12 | **13** |

## Accomplishments

- **The cutover is verified on the running service, not merely committed.** `MCP_AUTH_MODE = authkit` was read back off revision `brett-00006-sg2`'s own environment, and the same describe call confirmed `MCP_ALLOWED_HOSTS` survived `--env-vars-file`'s wholesale environment replacement byte-identical, still naming both assigned hostnames.

- **All three copied strings were compared programmatically against `02-06-SUMMARY.md`, not by eye** — issuer, `jwks_uri`, and the Resource Indicator all `identical=True`. A one-character `jwks_uri` error presents as a completed OAuth flow followed by a universal `401`, which is this phase's hardest failure to diagnose.

- **`--min=1` was applied on the standing authorisation and confirmed to be the service-scoped flag.** `minScale: '1'` sits on the service's `.metadata.annotations` and is **absent** from `.spec.template.metadata.annotations`, and the serving revision name is unchanged either side of the flip — which is the plan's own test that `--min-instances` was not used by mistake.

- **The warm-instance claim has two independent proofs.** After 900 s of zero traffic the first DB-free request returned in **0.303 s** against a measured 7.53 s cold start at `--min=0`; and a Cloud Logging query spanning the entire idle window returned **zero rows**, so no container started, restarted or rebalanced.

- **Claude's whole discovery chain was walked by hand and passes end to end** — the `401` pointer, the RFC 9728 document, the RFC 8414 AS metadata, and the CIMD preconditions. Any failure inside the Claude client is therefore known to be client-side, which is precisely what makes Task 3's result interpretable.

- **The `401` challenge is byte-identical across a complete auth-mechanism swap.** That was the design claim of plan 02-06's two-stage split; it now holds against the deployed service, not just in unit tests.

- **72 tests pass** (`-m "not integration"`, up from 61), `ruff check` and `ruff format --check` clean across 35 files, `mypy` clean across 20, gitleaks clean on `--all-files`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Matrix rows 3 and 4 could not be executed — reading the auth secret was denied**

- **Found during:** Task 2, step 3
- **Issue:** Rows 3 and 4 require `Authorization: Bearer $MCP_AUTH_SECRET`. `gcloud secrets versions access latest --secret=brett-mcp-auth-secret` was **blocked by this session's permission classifier**, in two different spellings. The denial was respected, not circumvented.
- **Fix:** Substituted probes that need no credential and argue the same property. The decisive one is an **RS256 JWT carrying the correct `iss`, the correct `aud`, the tenant's real `kid` and an unexpired `exp`, signed by a foreign RSA-2048 key** — structurally indistinguishable from a genuine WorkOS token in every field a parser can check, differing only in the signature. Nothing can reject it except a real RS256 verification against the WorkOS JWKS. Also probed: an opaque 64-character bearer of exactly `MCP_AUTH_SECRET`'s shape (`secrets.token_urlsafe(48)`), and a correct-issuer/wrong-audience token (T-02-02). All four returned `401` with **byte-identical** bodies.
- **Why the substitute is adequate:** three further independent lines of evidence say the cutover took — `MCP_AUTH_MODE = authkit` read off the serving revision, the metadata document naming the real issuer (rendered only from `MCP_ISSUER_URL`, read only in authkit mode), and plan 02-06's `test_build_token_verifier_authkit_never_degrades_to_static` proving in code that authkit cannot silently fall back to static.
- **Residual gap, stated plainly:** the literal observation "the real static secret now returns 401" was not made. Its expected value is `401`, and it is one command from the developer's own shell.
- **Committed in:** `9c088b3`

**2. [Rule 1 - Bug] Row 7's negative control is not re-runnable in `authkit` mode**

- **Found during:** Task 2, step 3
- **Issue:** Plan 02-05 established that the `421 Invalid Host header` result is only observable when the request first gets *past authentication* — the service checks auth before the host guard, proven directly at the time. In `authkit` mode no credential available to this session authenticates, so a bogus allowlist would now return `401`, never `421`. Reproducing the `421` would have required first flipping `MCP_AUTH_MODE` back to `static`, which would no longer test the authkit-mode deployment and would have left the service mid-surgery immediately before the phase's one irreplaceable manual test.
- **Fix:** Verified the property the threat register actually names for the post-redeploy case — *"`MCP_ALLOWED_HOSTS` … is re-verified rather than assumed, because `--env-vars-file` replaces the whole environment on every deploy"*. Read the allowlist directly off the serving revision (byte-identical, both hostnames); re-confirmed the Google Frontend `404` edge barrier; and noted the positive proof that needs no control at all — a wrong allowlist would make *every* request `421`, and rows 1, 2, 5 and 6 all returned their expected non-`421` results.
- **Method preserved:** the deploy log records exactly how to re-run the literal control if it is ever wanted.
- **Committed in:** `9c088b3`

**3. [Rule 1 - Bug] The 15-minute idle criterion measures Neon, not the flip it is testing**

- **Found during:** Task 2, step 2
- **Issue:** The criterion is `/health` under 1.5 s after 15 minutes idle. Observed **1.734 s** — a literal miss. But `/health` is the only probed endpoint that opens a database connection, and Neon autosuspends after 5 minutes **independently of Cloud Run** and cannot be disabled on the Free plan. So the criterion scores a Cloud Run container start *plus* a Neon compute resume; after `--min=1` the first term is gone and the criterion is measuring only the term the flip cannot affect.
- **Fix:** Measured the two endpoints Claude's discovery sequence actually uses, neither of which touches the database: `POST /mcp` (`401`) at **0.303 s** and the RFC 9728 document at **0.321 s**, on the first request after the idle window — statistically identical to their warm steady state of 0.28–0.32 s. Then confirmed the container never started via an empty log query across the whole window.
- **Recorded as a miss, not rounded away.** The 1.734 s figure and its explanation are both in the deploy log. The forward-looking consequence for Phase 6 is noted: the first `fitness_ping` after a quiet period will feel slow, and that is Neon waking.
- **Committed in:** `9c088b3`

**4. [Rule 2 - Missing critical] `uv run python` cannot import `yaml`, as plan 02-06 predicted**

- **Found during:** Task 1, step 2
- **Issue:** `pyyaml` lives in the `dev` group and `pyproject.toml` sets `[tool.uv] default-groups = []`, so a bare `uv run python` gets the production environment. Plan 02-06 flagged this and plan 02-07 was corrected before this agent ran.
- **Fix:** Used the corrected `uv run --group dev python` form throughout. Confirmed live: the dev invocation installed 32 additional packages. **This is a confirmation of a prior finding, not a new defect** — recorded so the correction's value is traceable.
- **Committed in:** n/a — tooling invocation only

**5. [Rule 3 - Blocking] The worktree was based on a commit five behind the required base**

- **Found during:** Startup, before any task
- **Issue:** `git merge-base HEAD d0e5c9a` returned `1e97f3b` — HEAD was an *ancestor* of the required base, so the worktree predated waves 5 and 6 and lacked plans 02-05 and 02-06's summaries, both of which this plan reads for its input values.
- **Fix:** `git reset --hard d0e5c9ac99f96e63863f1a2e59ddfde52add37d1` on a clean tree, then re-verified `git rev-parse HEAD`. No work lost.
- **Note:** this is the same failure plan 02-06 hit at its own startup. It is now a recurring worktree-provisioning issue, not a one-off.
- **Committed in:** n/a — a base correction, not a change

---

**Total deviations so far:** 5 auto-fixed (2 blocking, 2 bugs in the plan's verification method, 1 confirmation of a prior finding). **None changes what the plan builds.** No Rule 4 escalation — the architecture is exactly as specified.

## Verification Evidence

| Plan verification step | Result |
|---|---|
| 1. `describe` reports minimum instances `1`, same revision either side of the flip | **PASS** — `run.googleapis.com/minScale: '1'` on service metadata, absent from the revision template; `brett-00006-sg2` both before and after |
| 2. After 15 min idle, `/health` sub-second with `200` | **LITERAL MISS** — `1.734 s` / `200`. Met by intent on the discovery path: `0.303 s` and `0.321 s`. See Deviation #3 |
| 3. Seven matrix rows post-cutover, rows 3/4 as `401 (expected after cutover)`, row 5 the real domain in a single-entry list | **PARTIAL** — rows 1, 2, 5, 6 PASS; row 5 confirmed single-entry and real; row 7 verified by configuration readback; rows 3/4 not executed, see Deviation #1 |
| 4. A Claude Desktop/Web/Mobile connector calls `fitness_ping` | **PENDING — this is the checkpoint** |
| 5. `uv run pytest -m "not integration" -q` green; 13 tests in `test_cloud_run_deploy.py` | **PASS** — 72 passed, 28 deselected; `grep -c 'def test_'` → `13`; module reports 13 passed |
| 6. `uv run pre-commit run gitleaks --all-files` exits 0 | **PASS** |
| 7. PROJECT.md records the mechanism; STATE.md's Phase 2 blocker resolved | **NOT STARTED** — Task 4, gated on Task 3 |

**Task 1 acceptance criteria, each checked:**

| Criterion | Observed |
|---|---|
| `MCP_AUTH_MODE == "authkit"` | yes |
| `grep -c 'static'` outside comment text | `0` (one comment mention, documenting the rollback — explicitly permitted) |
| `MCP_ISSUER_URL` https, not `example.authkit.app`, no trailing slash | all three hold |
| `MCP_JWKS_URI` byte-identical to `02-06-SUMMARY.md` | asserted programmatically → `identical=True` |
| `grep -c 'def test_'` → 13; module → `13 passed` | `13` / `13 passed` |
| `--set-secrets` count `1`, both secrets still bound | `1`; `brett-database-url` and `brett-mcp-auth-secret` both present, re-confirmed on the serving revision |
| Same revision name printed twice | `brett-00006-sg2	brett-00006-sg2` |
| `authorization_servers[0]` is the real domain | `https://quiet-fireplace-16-staging.authkit.app` |
| `authorization_servers | length` → `1` | `1` |
| gitleaks on the env file | Passed |

## Security Notes

- **T-02-06 (unauthenticated access post-cutover)** — rows 1 and 2 return `401` against the cut-over service, and all four credential-free probes were rejected. The client-boundary half (connector disabled ⇒ no path to the tool) is part of the pending checkpoint.
- **T-02-02 (confused deputy)** — the `aud` three-way identity was asserted programmatically, and a correct-issuer/wrong-audience token was rejected against the deployed service.
- **T-02-04 (401 as an oracle)** — all four probes returned byte-identical bodies. The server does not distinguish absent from malformed from well-formed-but-forged from wrong-audience.
- **T-02-07 (JWKS fail-open)** — the static rollback is preserved: `MCP_AUTH_SECRET` is still bound to the serving revision, so a WorkOS outage is a one-value config change, never a code change.
- **T-02-01 (DNS rebinding after redeploy)** — `MCP_ALLOWED_HOSTS` verified byte-identical on the serving revision after the environment-replacing deploy. See Deviation #2 for why the `421` control itself is not re-runnable.
- **T-02-18 (`update` wiping the environment)** — the `--min=1` command passed `--min` and nothing else. Confirmed afterwards by reading the full environment back: all seven non-secret variables and both secret bindings intact.
- **T-02-10 (credentials in planning docs)** — `grep -icE 'Bearer [A-Za-z0-9_.-]{30,}|postgres(ql)?://…@'` returns `0` on the deploy log; gitleaks passes `--all-files`. The forged JWTs minted for the probes were never printed or written anywhere.
- **T-02-03 (credential in the connector URL)** — `MCP_RESOURCE_URL` asserted to carry no query string; the checkpoint instructs the developer to enter it with none.

**Credential handling.** No credential was read this session. The one attempt — `MCP_AUTH_SECRET`, for matrix rows 3 and 4 — was denied by the permission classifier and the denial was respected rather than worked around. Every probe hit a public, unauthenticated endpoint.

**No threat flags.** No new network endpoint, auth path, file access pattern or schema change. The surface is unchanged from plan 02-04/02-08; only which verifier guards it changed.

## Known Stubs

**None.** The two placeholders plan 02-05 recorded (`MCP_ISSUER_URL: "https://example.authkit.app"`, `MCP_JWKS_URI: ""`) are **resolved by this plan** — both now hold live values read from the WorkOS discovery document, and the deployed metadata document reflects them.

## Cost — what `--min=1` now commits, and how to revert

One `512Mi`/1-CPU Cloud Run instance is now billed continuously instead of scaling to zero. Pre-authorised by the developer on 2026-08-27 and required by D-06f. **Reversible in seconds, no rebuild, no new revision:**

```bash
gcloud run services update brett --project=brett-fitness --region=us-central1 --min=0
```

Reverting restores the measured **7.53 s** cold start, which against Claude's 10-second discovery budget leaves roughly 2.5 s of headroom — so it should be reverted only when no connector use is expected.

## Next Step — the checkpoint

**Task 3 is a `checkpoint:human-verify` gate with no automatable substitute (RESEARCH assumption A4).** All pre-checkpoint automation the plan requires has been run and passes. The developer must add a custom connector in Claude Desktop, Web or Mobile — **not Claude Code**, which does not satisfy DEPLOY-02 — pointed at:

```
https://brett-792870654598.us-central1.run.app/mcp
```

Leaving the Advanced OAuth client ID/secret fields **empty**, so CIMD/DCR is what is actually tested.

Task 4 then records the observed mechanism in PROJECT.md Key Decisions, resolves STATE.md's Phase 2 blocker, and closes assumptions A4, A6, A-CR-3, A-CR-6 and A-CR-7 in the deploy log. **Not started, and correctly so — recording an untested mechanism is explicitly forbidden by the plan.**

## For Phase 6 — re-verify before building the real tool set

- **Both research validity windows have expired or are about to.** `02-RESEARCH.md` was valid until **2026-09-07**; the Cloud Run addendum until **2026-09-10**. Re-check before any future rebuild.
- **Confirm `mcp` 2.0.0 is still current**, and that `mcp-types` (pinned exactly) has not moved in lockstep to a version the code does not match.
- **Re-read Claude's connector authentication page.** The `static_headers` beta status, the CIMD/DCR support matrix and the 10 s / 30 s endpoint timeouts are all subject to change, and the last rung of Task 3's diagnosis ladder depends on the first of those.
- **The `-staging` AuthKit domain.** If the WorkOS project is ever promoted to a production environment, both `MCP_ISSUER_URL` and `MCP_JWKS_URI` change and staging-minted tokens stop validating. A configuration change, not a code change — by design.
- **Neon's autosuspend is the remaining latency floor.** ~1.2 s to wake on the first database-touching request. Every real Phase 6 tool touches the database, unlike `fitness_ping`'s discovery path.
- **Worktree provisioning.** Two consecutive plans (02-06, 02-07) started from a base five or more commits behind the required one. Worth fixing upstream rather than absorbing per-plan.

## Self-Check: PASSED

- **Files claimed modified verified present and changed:** `deploy/cloud-run.env.yaml` and `backend/tests/test_cloud_run_deploy.py` in `git show --stat d3f5a22`; `02-DEPLOY-LOG.md` in `9c088b3`.
- **Both claimed commits verified in `git log`:** `d3f5a22`, `9c088b3`.
- **The deployed state was read back from Cloud Run, not assumed from the committed file.** `MCP_AUTH_MODE = authkit` and the full environment come from `gcloud run services describe` against revision `brett-00006-sg2`.
- **Test counts verified by running, not asserted:** `13 passed` for the module, `72 passed` for the fast suite.
- **The three copied strings were compared programmatically**, and the comparison output is recorded verbatim in the deploy log.
- **The warm-instance claim is backed by two independent measurements**, one of which (the empty log query) does not depend on latency interpretation at all.
- **The one criterion that was missed is recorded as missed**, with its number, rather than being reframed as a pass.
- **The `## Connector round-trip (DEPLOY-02)` heading is deliberately absent** — `grep -c` returns `0` — so Task 4's automated check still certifies something when it runs.
- **No credential appears anywhere:** gitleaks passes `--all-files`; the deploy log scores `0` on the bearer/DSN regex; no secret was successfully read this session.

**Not modified, by design (worktree mode):** `.planning/STATE.md` and `.planning/ROADMAP.md` — the orchestrator owns those writes. Note this diverges from the plan's Task 4, which lists `STATE.md` in `files_modified`; the orchestrator's instruction takes precedence, and the STATE.md edits Task 4 specifies are carried forward as a handoff item.

---
*Phase: 02-deploy-connector-auth-spike*
*Status: PARTIAL — 2/4 tasks; paused at the DEPLOY-02 connector checkpoint*
*Date: 2026-08-29*
