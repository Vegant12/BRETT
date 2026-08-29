---
phase: 02-deploy-connector-auth-spike
plan: 07
subsystem: auth
tags: [cloud-run, workos, authkit, oauth, cimd, dcr, jwt, jwks, mcp, connector, min-instances]
status: COMPLETE — all 4 tasks; DEPLOY-02 verified on Claude Desktop

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
  - A verified end-to-end Claude Desktop connector round-trip via WorkOS AuthKit + CIMD
  - The recorded, empirically-grounded auth decision that overturns "bearer token, not OAuth"
affects: [Phase 6 MCP tools, Phase 7 secret rotation and production hardening]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "When a plan's prescribed probe needs a credential the sandbox will not release, substitute a probe that needs none and argues the same property — a forged-signature JWT with correct iss/aud/kid can only be rejected by real JWKS verification"
    - "Prove a warm instance two ways: latency on the path the client actually uses, and an empty log query across the idle window"
    - "Separate a composite latency measurement into its independent terms before judging it against a threshold — /health measures Cloud Run AND Neon; discovery measures neither"
    - "Read the deployed environment back off the serving revision rather than trusting that the file you committed is what is running"
    - "Record a prediction about third-party client behaviour before the test, then record the observation separately — CIMD-vs-DCR was predicted from the discovery document and confirmed, and the two records stay distinguishable"
    - "Prove every automatable hop before a human checkpoint, so the manual result is attributable on success and isolable on failure"

key-files:
  created:
    - .planning/phases/02-deploy-connector-auth-spike/02-07-SUMMARY.md
  modified:
    - deploy/cloud-run.env.yaml
    - backend/tests/test_cloud_run_deploy.py
    - .planning/phases/02-deploy-connector-auth-spike/02-DEPLOY-LOG.md
    - .planning/PROJECT.md

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

connector_result:
  client: Claude Desktop
  authentication: always required
  client_identification: CIMD (Anthropic hosted client metadata document)
  dcr: enabled, available, never exercised
  tool_result: '{"status": "ok", "database": "connected"}'
  diagnosis_rung: 0 (none needed)

key-decisions:
  - "Applied --min=1 on the recorded 2026-08-27 pre-authorisation without re-asking, after checking both 02-05-SUMMARY.md and 02-DEPLOY-LOG.md for a refusal"
  - "Respected the sandbox denial on reading brett-mcp-auth-secret rather than working around it; substituted credential-free probes for matrix rows 3 and 4"
  - "Did not re-run row 7's negative control: it is impossible in authkit mode because auth precedes the host guard, and reproducing it would have required flipping back to static immediately before the phase's one irreplaceable manual test"
  - "Recorded the /health idle figure as a literal miss (1.734s vs a 1.5s criterion) rather than rounding it away, and separated out the Neon term that caused it"
  - "MCP connector auth = OAuth 2.1 via WorkOS AuthKit, BRETT as resource server only; the prior 'bearer token, not OAuth' decision is OVERTURNED, marked superseded rather than deleted"
  - "Recorded the connector-disabled negative as NOT explicitly confirmed rather than inferring it from the developer's silence"
  - "Did not modify STATE.md or ROADMAP.md despite Task 4 listing STATE.md; worktree mode gives those writes to the orchestrator, and the intended edits are handed off verbatim below"

requirements-completed: [DEPLOY-02, MCP-04, DEPLOY-01]

# Metrics
duration: ~50min of agent time across two sessions, plus the developer's checkpoint wall-clock
completed: 2026-08-29
---

# Phase 2 Plan 07: Connector Auth Cutover Summary

**A personal Claude account on Claude Desktop authenticated to the self-hosted MCP server on Cloud Run through WorkOS AuthKit, discovered `fitness_ping`, and called it successfully at the first attempt — closing the single question Phase 2 existed to answer, and overturning the project's standing "bearer token, not OAuth" decision with an observation rather than an argument.**

## Status — all 4 tasks complete

| Task | Type | State |
|---|---|---|
| 1. Cut the deployed service over to WorkOS JWT validation | `auto` | **COMPLETE** (`d3f5a22`) |
| 2. Keep one instance warm (D-06f) and re-run the matrix post-cutover | `auto` | **COMPLETE** (`9c088b3`) |
| 3. DEPLOY-02 — add the Claude custom connector and call `fitness_ping` | `checkpoint:human-verify` | **COMPLETE — verified by the developer** (`e3a8a88`) |
| 4. Record the answer in PROJECT.md and the deploy log | `auto` | **COMPLETE** (`41560e2`) |

## Task Commits

| # | Commit | Message |
|---|---|---|
| 1 | `d3f5a22` | `feat(02-07)`: cut the deploy config over to WorkOS JWT validation |
| 2 | `9c088b3` | `docs(02-07)`: record the AuthKit cutover, `--min=1`, and the post-cutover matrix |
| — | `25cdb9b` | `docs(02-07)`: partial-state summary at the DEPLOY-02 connector checkpoint |
| 3 | `e3a8a88` | `docs(02-07)`: record the successful DEPLOY-02 connector round-trip |
| 4 | `41560e2` | `docs(02-07)`: record the verified connector auth mechanism in PROJECT.md |

## The answer — DEPLOY-02

| Field | Observed |
|---|---|
| Client | **Claude Desktop** (satisfies DEPLOY-02; Claude Code would not) |
| Authentication | Always required |
| Client identification | **CIMD** — Anthropic's hosted client metadata document |
| DCR | Enabled and available, **never exercised** |
| Consent flow | WorkOS AuthKit sign-in + consent completed; connector connected |
| `fitness_ping` | `{"status": "ok", "database": "connected"}` |
| Diagnosis rung | **0 — none needed**, Advanced OAuth fields left empty |

**CIMD, not DCR — and the distinction was predicted before it was observed.** At the checkpoint, the
tenant's RFC 8414 document was recorded as advertising `client_id_metadata_document_supported: true`
*and* `"none"` in `token_endpoint_auth_methods_supported`. Claude selects CIMD only when both hold.
Both held, and CIMD is what Claude Desktop used. The prediction and the observation are recorded as
separate entries in the deploy log, so the record shows which mechanism was *exercised* rather than
which was hoped for. `registration_endpoint` remains live, so **DCR is a configured but untested
fallback** — which is exactly the position D-03 asked for.

Notably, **nothing in BRETT's code differs between the CIMD and DCR paths.** The MCP SDK is a
resource server; it never sees client registration either way. That is why the fallback costs nothing
to keep.

## The decision recorded in PROJECT.md

ROADMAP success criterion 4 required the mechanism to *confirm or explicitly overturn* the standing
decision. **It is overturned.**

- The row `MCP auth = bearer token for v1, not OAuth` is **struck through and marked superseded, not
  deleted** — an overturned decision with its history intact is more useful than a rewritten one.
- A new row records the mechanism actually observed working: **OAuth 2.1 via WorkOS AuthKit (managed
  IdP), with BRETT as a resource server only**, validating RS256 JWTs against the tenant JWKS and
  enforcing `iss`/`aud`/`exp`, with `aud` pinned to the Resource Indicator against cross-server replay.
- **The static bearer is not retired.** It remains the Claude Code CLI path (D-01, proven in plan
  02-05) and the WorkOS-outage rollback: `MCP_AUTH_MODE=static` plus a redeploy — a one-value config
  change, never a code change.
- Evidence pointer: `.planning/phases/02-deploy-connector-auth-spike/02-DEPLOY-LOG.md`.

**The Out of Scope note was reconciled**, because leaving it would have directly contradicted the new
row. The old line deferred OAuth on the grounds that a bearer token was sufficient; that reasoning
died with the observation that a Claude connector cannot use a bearer token at all. What remains out
of scope is narrower and still true: **hand-rolling an OAuth authorization server**. WorkOS is the
authorization server; BRETT only validates its tokens.

**Why the original assumption failed is worth stating precisely:** the prior decision was never that
bearer auth was insecure. It was that the *client* would accept one. It does not.

## Handoff — STATE.md and ROADMAP.md edits the orchestrator must apply

**This agent did not modify `.planning/STATE.md` or `.planning/ROADMAP.md`.** Worktree mode reserves
those writes for the orchestrator, and every prior plan in this worktree (02-06, and 02-07 Tasks 1–2)
observed the same convention. Task 4's `files_modified` lists `STATE.md`, so this is a **known,
deliberate scope divergence** — the edits are specified here verbatim rather than silently dropped.

### 1. `.planning/STATE.md` — resolve the Phase 2 blocker

Replace the line (currently at **STATE.md:79**):

> `- **Open (Phase 2):** Whether a personal Claude account can authenticate a custom remote MCP connector via bearer token. `static_headers` is beta and org-admin-shaped; the GitHub request for connector bearer support was closed "not planned." Fallback is a minimal OAuth 2.1 resource-server shim.`

with:

> `- **Resolved (Phase 2, 2026-08-29):** A personal Claude account authenticates a custom remote MCP connector via WorkOS AuthKit (OAuth 2.1, CIMD client identification), not a bearer token — verified on Claude Desktop. See `.planning/phases/02-deploy-connector-auth-spike/02-DEPLOY-LOG.md`.`

**Leave the two Phase 3 entries and the one Phase 6 entry untouched** — Task 4's acceptance criteria
check that `Open (Phase 3)` still returns 2 and `Open (Phase 6)` still returns 1.

### 2. `.planning/STATE.md` — Accumulated Context → Decisions

Add, in the existing style:

> `- [Phase 2]: MCP connector auth = OAuth 2.1 via WorkOS AuthKit with CIMD; "bearer token, not OAuth" is overturned`

### 3. `.planning/STATE.md` — correct the stale Render line

**STATE.md:67** still reads `...deploy target Render`. It is the one place in STATE.md that still
asserts the abandoned target. Change `deploy target Render` → `deploy target Google Cloud Run`.
Task 4's criterion is `grep -c 'deploy target Render'` returns `0`.

### 4. `.planning/ROADMAP.md` — mark the plan and phase

- Tick `02-07-PLAN.md` in the Phase 2 plan list (currently `- [ ]`).
- Phase 2 is now **complete** — all 8 plans done and all 4 success criteria satisfied (see below).
  Tick `- [ ] **Phase 2: Deploy & Connector Auth Spike**` in the phase list.

### 5. `.planning/REQUIREMENTS.md`

Mark **DEPLOY-02**, **MCP-04** and **DEPLOY-01** complete. Not touched by this agent, consistent with
the worktree convention.

### 6. One consistency item this plan deliberately did *not* fix

`.planning/PROJECT.md` **Active requirements** still contains:

> `- [ ] MCP authentication via strong bearer token (env secret) + HTTPS + rate limiting; no secrets ever returned in tool responses`

The bearer-token clause now contradicts the new Key Decisions row. **This was left alone on purpose**
— the plan scoped Task 4 to Key Decisions and Out of Scope, and Active requirements are owned by
`/gsd-transition` and traced against REQUIREMENTS.md. Editing it here risked desynchronising that
traceability. **Flagged for the phase transition**, where the natural rewrite is "MCP authentication
via OAuth 2.1 (WorkOS AuthKit) for connectors and a static bearer for CLI, + HTTPS + rate limiting;
no secrets ever returned in tool responses". The rest of the line is still accurate.

## Phase-level goal verification — ROADMAP Phase 2 success criteria

**All four are satisfied.** This was the last plan in the phase.

| # | Criterion | Status |
|---|---|---|
| 1 | Live on Cloud Run over HTTPS, backed by Neon, every credential from Secret Manager, nothing committed | **SATISFIED** — plans 02-08 and 02-05; re-confirmed here by reading the serving revision's full environment back, with both secrets still bound via `--set-secrets` and gitleaks clean `--all-files` |
| 2 | A Claude custom connector discovers a throwaway tool and calls it from an actual Desktop/Web/Mobile client | **SATISFIED** — this plan, Task 3. Claude Desktop, CIMD, `{"status": "ok", "database": "connected"}`, first attempt |
| 3 | Unauthenticated rejected and authenticated succeeds, verified against the deployed URL | **SATISFIED** — rejection by matrix rows 1–2 plus four credential-free probes (all `401`, byte-identical bodies); success by the connector's live tool call. One narrow gap: the client-side connector-disabled check was not explicitly confirmed (below) |
| 4 | The mechanism that works is recorded in PROJECT.md Key Decisions, confirming or explicitly overturning "bearer token, not OAuth" | **SATISFIED** — explicitly **overturned**, with the superseded row retained |

**Phase 2's goal — "resolve the project's single highest-uncertainty question while it is still cheap
to change the answer" — is met.** The answer arrived before any real functionality was built on the
assumption, which is precisely what the spike was for. Had it gone the other way, Phases 3–7 would
have been built on a transport that could not be reached.

## The one open gap, stated rather than assumed

**Task 3's criterion "the developer confirmed the negative: with the connector disabled, Claude has
no path to the tool" was NOT explicitly confirmed.** It was in the instructions given, and nothing was
reported as failing, but the literal observation was never stated. It is recorded as unconfirmed
rather than inferred from silence.

**Why this does not weaken MCP-04.** The requirement is that unauthenticated requests are rejected,
and that is proven *server-side* — the half that actually enforces anything:

- Matrix rows 1 and 2 return `401` with a correct `resource_metadata=` pointer against the deployed,
  cut-over service.
- All four credential-free probes were rejected with byte-identical bodies, including an RS256 token
  carrying the correct `iss`, the correct `aud`, the tenant's real `kid` and a valid `exp`, differing
  only in its signature — a token nothing can reject except real JWKS verification.

The connector-disabled check is a **client-side UX confirmation** that Claude does not surface an
ungranted tool. No server behaviour depends on it. **Cheap to close:** toggle the connector off in
Claude Desktop and confirm `fitness_ping` is no longer offered.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Matrix rows 3 and 4 could not be executed — reading the auth secret was denied**

- **Found during:** Task 2, step 3
- **Issue:** Rows 3 and 4 require `Authorization: Bearer $MCP_AUTH_SECRET`. `gcloud secrets versions access latest --secret=brett-mcp-auth-secret` was **blocked by the session's permission classifier**, in two spellings. The denial was respected, not circumvented.
- **Fix:** Substituted probes needing no credential that argue the same property. The decisive one is an **RS256 JWT with correct `iss`, correct `aud`, the tenant's real `kid` and an unexpired `exp`, signed by a foreign RSA-2048 key** — structurally indistinguishable from a genuine WorkOS token in every field a parser can check. Also probed an opaque 64-character bearer of `MCP_AUTH_SECRET`'s exact shape, and a correct-issuer/wrong-audience token (T-02-02). All four returned `401` with byte-identical bodies.
- **Residual gap:** the literal observation "the real static secret now returns 401" was not made. Expected value `401`; one command from the developer's shell.
- **Commit:** `9c088b3`

**2. [Rule 1 - Bug] Row 7's negative control is not re-runnable in `authkit` mode**

- **Found during:** Task 2, step 3
- **Issue:** The `421 Invalid Host header` result is only observable once a request gets *past authentication*. In `authkit` mode no credential available to the session authenticates, so a bogus allowlist returns `401`, never `421`. Reproducing it would have required flipping back to `static` immediately before the phase's one irreplaceable manual test.
- **Fix:** Verified the property the threat register actually names — `MCP_ALLOWED_HOSTS` read byte-identical off the serving revision after the environment-replacing deploy. **Task 3's success is now an additional positive proof:** a wrong allowlist would have made *every* request `421`, and the connector completed.
- **Commit:** `9c088b3`

**3. [Rule 1 - Bug] The 15-minute idle criterion measures Neon, not the flip it is testing**

- **Found during:** Task 2, step 2
- **Issue:** The criterion is `/health` under 1.5 s after 15 minutes idle. Observed **1.734 s** — a literal miss. But `/health` is the only probed endpoint that opens a database connection, and Neon autosuspends after 5 minutes independently of Cloud Run. The criterion scores a container start *plus* a Neon resume; after `--min=1` only the term the flip cannot affect remains.
- **Fix:** Measured the two endpoints Claude's discovery actually uses, neither touching the database: `POST /mcp` at **0.303 s** and the RFC 9728 document at **0.321 s**, first request after the idle window. Confirmed by an empty log query across the window.
- **Vindicated by Task 3:** discovery completed comfortably inside the 10-second budget.
- **Commit:** `9c088b3`

**4. [Rule 2 - Missing critical] `uv run python` cannot import `yaml`, as plan 02-06 predicted**

- **Found during:** Task 1, step 2
- **Issue:** `pyyaml` lives in the `dev` group and `[tool.uv] default-groups = []`, so bare `uv run python` gets the production environment.
- **Fix:** Used `uv run --group dev python` throughout. A confirmation of a prior finding, not a new defect.
- **Commit:** n/a — tooling invocation only

**5. [Rule 3 - Blocking] The worktree was based on a commit five behind the required base**

- **Found during:** Startup, before any task
- **Issue:** `git merge-base HEAD d0e5c9a` returned `1e97f3b` — HEAD was an *ancestor* of the required base, so the worktree lacked plans 02-05 and 02-06's summaries, both of which this plan reads for input values.
- **Fix:** `git reset --hard d0e5c9a` on a clean tree. No work lost.
- **Note:** the same failure hit plan 02-06 at its own startup. A recurring worktree-provisioning issue, not a one-off.
- **Commit:** n/a — a base correction

**6. [Scope] Task 4's `files_modified` lists STATE.md, which worktree mode forbids this agent to write**

- **Found during:** Task 4
- **Issue:** Task 4 instructs edits to `.planning/STATE.md`; worktree mode reserves STATE.md and ROADMAP.md for the orchestrator. A direct conflict between plan text and execution convention.
- **Fix:** Followed the convention and **specified every intended edit verbatim** in the Handoff section above — exact line numbers, exact replacement text, and the acceptance criteria each edit satisfies. Nothing is dropped; it is relocated to whoever owns the write.
- **Consequence:** three of Task 4's acceptance criteria (the STATE.md greps) cannot pass until the orchestrator applies the handoff. They are listed explicitly below rather than silently marked green.
- **Commit:** `41560e2`

**7. [Judgement] The connector-disabled negative was recorded as a gap rather than assumed**

- **Found during:** Task 3 write-up
- **Issue:** The developer's report did not state the connector-disabled observation. The tempting move is to infer it from "no problems reported".
- **Fix:** Recorded it as **NOT explicitly confirmed**, with the server-side evidence that makes it non-blocking and a one-line procedure to close it. Silence is not evidence.
- **Commit:** `e3a8a88`

---

**Total deviations:** 7 — 5 auto-fixed during Tasks 1–2, 1 scope divergence handled by handoff, 1 verification-honesty call. **None changes what the plan builds.** No Rule 4 escalation; the architecture is exactly as specified.

## Verification Evidence

| Plan verification step | Result |
|---|---|
| 1. `describe` reports minimum instances `1`, same revision either side of the flip | **PASS** — `minScale: '1'` on service metadata, absent from the revision template; `brett-00006-sg2` both sides |
| 2. After 15 min idle, `/health` sub-second with `200` | **LITERAL MISS** — `1.734 s` / `200`. Met by intent on the discovery path: `0.303 s` and `0.321 s`. See Deviation #3 |
| 3. Seven matrix rows post-cutover, rows 3/4 as `401 (expected after cutover)`, row 5 the real domain in a single-entry list | **PARTIAL** — rows 1, 2, 5, 6 PASS; row 7 by configuration readback; rows 3/4 substituted, see Deviation #1 |
| 4. A Claude Desktop/Web/Mobile connector calls `fitness_ping` | **PASS** — Claude Desktop, `{"status": "ok", "database": "connected"}`, first attempt |
| 5. `uv run pytest -m "not integration" -q` green; 13 tests in `test_cloud_run_deploy.py` | **PASS** — re-run at plan close: **72 passed, 28 deselected** |
| 6. `uv run pre-commit run gitleaks --all-files` exits 0 | **PASS** — re-run at plan close |
| 7. PROJECT.md records the mechanism; STATE.md's Phase 2 blocker resolved | **PARTIAL** — PROJECT.md **done**; STATE.md **handed off** (Deviation #6) |

**Task 4 acceptance criteria, each checked:**

| Criterion | Observed |
|---|---|
| PROJECT.md still contains the original bearer row, marked superseded (`grep -qi 'supersed'`) | **PASS** — 3 matches; original row text retained verbatim under strikethrough |
| PROJECT.md has a new row naming the observed mechanism, with `02-DEPLOY-LOG.md` as evidence pointer | **PASS** |
| `grep -q 'MCP connector auth' .planning/STATE.md` | **DEFERRED** — orchestrator handoff item 2 |
| Phase 2 blocker text no longer present in STATE.md | **DEFERRED** — orchestrator handoff item 1 |
| `Open (Phase 3)` → 2, `Open (Phase 6)` → 1 | **DEFERRED** — handoff explicitly instructs leaving them untouched |
| `grep -c 'deploy target Render' .planning/STATE.md` → 0 | **DEFERRED** — orchestrator handoff item 3 |
| Deploy log has `## Connector round-trip (DEPLOY-02)` + A4, A6, A-CR-3, A-CR-6, A-CR-7 resolutions | **PASS** — heading count 1; all five assumption lines present |
| PROJECT.md no longer contains "OAuth-based MCP authentication — deferred" | **PASS** — `grep -c` → `0`; replaced with the narrower, still-true hand-rolled-AS exclusion |
| Credential regex → 0 across deploy log and PROJECT.md | **PASS** — `0` |
| `uv run pre-commit run gitleaks --all-files` exits 0 | **PASS** |

## Assumption resolutions

| ID | Resolution |
|---|---|
| **A4** — a personal Claude account can complete the connector OAuth flow | **RESOLVED — YES.** The phase's central unknown. Claude Desktop, personal account, first attempt |
| **A6** — `stateless_http=True` is compatible with Claude's connector | **RESOLVED — YES.** `backend/app/mcp/server.py:78` sets it, and discovery, consent and the tool call all completed against exactly that configuration. Under the `2026-07-28` transport there is no session to lose, and Claude never attempted a `GET` stream |
| **A-CR-3** — Cloud Run forwards the original public `Host` header | **RESOLVED — YES** (plan 02-05, row 7 `421`). Post-cutover re-verified by configuration readback; the connector's success is an additional positive proof |
| **A-CR-6** — cold start ~3–5 s at `min=0` | **REFUTED IN MAGNITUDE, THEN MITIGATED.** Measured **7.53 s**, ~2× the assumed range, leaving ~2.5 s of headroom against the 10-second budget. `--min=1` cut the discovery path to **0.303 s**. Trusting the assumption would have made Task 3 a coin toss |
| **A-CR-7** — a rotated `:latest` secret only reaches a running service after the next instance start | **UNRESOLVED — untested.** No rotation occurred. **`--min=1` sharpens this:** an instance now stays up indefinitely rather than being recycled by scale-to-zero, so a rotated secret may never reach the running service without a forced revision. Treat rotation as requiring a deliberate redeploy until proven otherwise — **Phase 7 secret-rotation work depends on this** |

## Security Notes

- **T-02-06 (unauthenticated access post-cutover)** — rows 1–2 return `401`; all four credential-free probes rejected. Client-boundary half is the one recorded gap, above.
- **T-02-02 (confused deputy)** — the `aud` three-way identity asserted programmatically (50-character string, no trailing slash, no query); a correct-issuer/wrong-audience token was rejected against the deployed service. The connector's success confirms the binding is correct in the positive direction too — an `aud` mismatch would have produced a completed OAuth flow followed by a universal `401`, and did not.
- **T-02-04 (401 as an oracle)** — all four probes returned byte-identical bodies; absent, malformed, forged and wrong-audience are indistinguishable to a caller.
- **T-02-07 (JWKS fail-open)** — the static rollback is preserved: `MCP_AUTH_SECRET` is still bound to the serving revision, so a WorkOS outage is a config change, never a code change.
- **T-02-01 (DNS rebinding after redeploy)** — `MCP_ALLOWED_HOSTS` verified byte-identical on the serving revision. See Deviation #2.
- **T-02-18 (`update` wiping the environment)** — the `--min=1` command passed `--min` and nothing else; full environment read back afterwards, all seven non-secret variables and both secret bindings intact.
- **T-02-10 (credentials in planning docs)** — credential regex `0` across the deploy log, PROJECT.md and this summary; gitleaks passes `--all-files`. No JWT — including the forged probe tokens — was ever written to a file.
- **T-02-03 (credential in the connector URL)** — the URL entered into Claude carries no query string; asserted programmatically before the checkpoint.

**Credential handling.** No credential was read across either session. The one attempt was denied by
the permission classifier and the denial was respected rather than worked around.

**No threat flags.** No new network endpoint, auth path, file access pattern or schema change. The
surface is unchanged; only which verifier guards it changed.

## Known Stubs

**None.** The two placeholders plan 02-05 recorded (`MCP_ISSUER_URL: "https://example.authkit.app"`,
`MCP_JWKS_URI: ""`) are resolved — both hold live values read from the WorkOS discovery document, and
the deployed metadata document reflects them.

`fitness_ping` itself is a **throwaway tool by design**, not a stub: DEPLOY-02 specifies a throwaway
tool, and Phase 6 builds the real tool set.

## Cost — what `--min=1` commits, and how to revert

One `512Mi`/1-CPU Cloud Run instance is billed continuously instead of scaling to zero. Pre-authorised
on 2026-08-27, required by D-06f. **Reversible in seconds, no rebuild, no new revision:**

```bash
gcloud run services update brett --project=brett-fitness --region=us-central1 --min=0
```

Reverting restores the measured **7.53 s** cold start — roughly 2.5 s of headroom against Claude's
10-second discovery budget. **Now that the connector is live and in use, reverting will make it
intermittently unreachable.** Keep `--min=1` while the connector is expected to work; revert only
during idle periods where a failed discovery is acceptable.

## For Phase 6 — re-verify before building the real tool set

- **Both research validity windows have expired or are about to.** `02-RESEARCH.md` was valid until **2026-09-07**; the Cloud Run addendum until **2026-09-10**. Re-check before any rebuild.
- **Confirm `mcp` 2.0.0 is still current**, and that `mcp-types` (pinned exactly) has not moved in lockstep to a version the code does not match.
- **Re-read Claude's connector authentication page.** The CIMD/DCR support matrix and the 10 s / 30 s timeouts are all subject to change. Less urgent than before — the `static_headers` beta is no longer on the critical path, since OAuth works.
- **The `-staging` AuthKit domain.** Promoting the WorkOS project to production changes both `MCP_ISSUER_URL` and `MCP_JWKS_URI`, and staging-minted tokens stop validating. A configuration change, not a code change — by design.
- **Neon's autosuspend is the remaining latency floor.** ~1.2 s to wake on the first database-touching request. **Every real Phase 6 tool touches the database, unlike `fitness_ping`'s discovery path** — so the first tool call after a quiet period will feel slower than this phase's measurements suggest.
- **A-CR-7 is unresolved and now matters more** — see the assumption table. Phase 7's secret rotation should not assume a rotated secret propagates to a warm instance.
- **Worktree provisioning.** Two consecutive plans (02-06, 02-07) started from a base five or more commits behind the required one. Worth fixing upstream rather than absorbing per-plan.

## Self-Check: PASSED

- **All five claimed commits verified in `git log`:** `d3f5a22`, `9c088b3`, `25cdb9b`, `e3a8a88`, `41560e2`.
- **Claimed modified files verified present in those commits:** `deploy/cloud-run.env.yaml` and `backend/tests/test_cloud_run_deploy.py` in `d3f5a22`; `02-DEPLOY-LOG.md` in `9c088b3` and `e3a8a88`; `02-DEPLOY-LOG.md` and `PROJECT.md` in `41560e2`.
- **PROJECT.md assertions verified by grep, not by eye:** `supersed` → 3; `02-DEPLOY-LOG.md` → 1; `OAuth-based MCP authentication — deferred` → **0**; the original bearer row text → still present.
- **Deploy log assertions verified by grep:** `## Connector round-trip (DEPLOY-02)` → 1; A4, A6, A-CR-3, A-CR-6, A-CR-7 → 1 each.
- **Tests and gitleaks re-run at plan close, not quoted from the partial summary:** `72 passed, 28 deselected`; gitleaks `Passed`.
- **`stateless_http=True` was read from source** (`backend/app/mcp/server.py:78`) before A6 was called resolved, rather than assumed from the plan text.
- **The unconfirmed criterion is recorded as unconfirmed**, with its compensating evidence, in both the deploy log and this summary.
- **The deferred STATE.md criteria are listed as DEFERRED, not as passed** — four of Task 4's criteria cannot be satisfied by this agent and say so.
- **No credential appears anywhere:** gitleaks passes `--all-files`; the bearer/DSN regex scores `0` across the deploy log, PROJECT.md and this summary.

**Not modified, by design (worktree mode):** `.planning/STATE.md`, `.planning/ROADMAP.md`,
`.planning/REQUIREMENTS.md`. The orchestrator owns those writes; every intended edit is specified
verbatim in the Handoff section.

---
*Phase: 02-deploy-connector-auth-spike — final plan; all 4 ROADMAP success criteria satisfied*
*Status: COMPLETE — 4/4 tasks*
*Date: 2026-08-29*
