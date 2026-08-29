---
phase: 02-deploy-connector-auth-spike
plan: 06
subsystem: auth
tags: [jwt, jwks, pyjwt, workos, authkit, oauth, cimd, dcr, mcp, rs256, anyio]
status: COMPLETE — all 3 tasks done; the deployed service is deliberately unchanged (02-07 owns the cutover)

# Dependency graph
requires:
  - phase: 02-deploy-connector-auth-spike (plan 05)
    provides: the live Cloud Run service, the reconciled canonical hostname, and the deployed RFC 9728 document whose `resource` field is the exact Resource Indicator this plan registered
  - phase: 02-deploy-connector-auth-spike (plan 02)
    provides: StaticTokenVerifier, build_token_verifier and its `authkit` stub, and the 8 Stage-A unit tests
  - phase: 02-deploy-connector-auth-spike (plan 04)
    provides: the 5 HTTP wire-contract tests (401 shape, RFC 9728 path) that must keep passing unchanged across the mechanism swap
provides:
  - A live WorkOS AuthKit tenant with CIMD and DCR both enabled and the Resource Indicator registered
  - The authoritative `issuer` and `jwks_uri`, read from the discovery document and recorded verbatim for plan 02-07 to paste into deploy/cloud-run.env.yaml
  - AuthKitJWTVerifier — RS256 JWKS validation enforcing iss, exp and an aud equal to the registered Resource Indicator, off the event loop, failing closed and silent
  - build_token_verifier's `authkit` branch, which now returns a verifier instead of raising, and refuses to start on an empty MCP_JWKS_URI rather than degrading to static bearer
  - 10 new unit tests (23 total in test_mcp_auth.py) driven by a real RSA-2048 key pair, with only the JWKS key fetch stubbed
  - Live-tenant evidence that the verifier's RS256 allowlist matches what WorkOS actually signs with
  - Evidence that the deployed Stage-A service is unaffected by this plan
affects: [02-07 connector round-trip and the MCP_AUTH_MODE=authkit cutover]

# Tech tracking
tech-stack:
  added:
    - "WorkOS AuthKit — managed IdP, free tier, nothing paid-gated (D-03/D-04)"
    - "pyjwt 2.13.0 PyJWKClient — already in the tree as an mcp transitive; no new dependency"
    - "cryptography 50.0.1 rsa key generation in tests — likewise transitive"
  patterns:
    - "Push a blocking third-party call out of an async handler with anyio.to_thread.run_sync rather than accepting event-loop stalls"
    - "Stub the network, never the decision: replace only PyJWKClient.get_signing_key_from_jwt so signature, iss, aud, exp and the algorithm allowlist all run for real"
    - "Read a must-match-exactly string back from the live system that already serves it, instead of retyping it from a document"
    - "Refuse to write a heading that an automated check greps for, until the values under it are actually known"
    - "Corroborate a human-reported dashboard toggle against a machine-readable artifact the toggle changes, rather than taking it on trust"
    - "Probe a recorded URL with the real production object, not just with curl — reachability and usability are different claims"

key-files:
  created:
    - .planning/phases/02-deploy-connector-auth-spike/02-06-SUMMARY.md
  modified:
    - backend/app/mcp/auth.py
    - backend/tests/test_mcp_auth.py
    - .planning/phases/02-deploy-connector-auth-spike/02-DEPLOY-LOG.md

# The two values plan 02-07 must copy. Recorded here because 02-07's acceptance
# criteria compare deploy/cloud-run.env.yaml against THIS file by grep, not by eye.
workos:
  authkit_domain: "https://quiet-fireplace-16-staging.authkit.app"
  issuer: "https://quiet-fireplace-16-staging.authkit.app"
  jwks_uri: "https://quiet-fireplace-16-staging.authkit.app/oauth2/jwks"
  resource_indicator: "https://brett-792870654598.us-central1.run.app/mcp"
  cimd_supported: true
  token_endpoint_auth_methods_supported: ["none", "client_secret_post", "client_secret_basic"]
  claude_will_select: CIMD  # both preconditions hold; DCR stays as the automatic fallback
  paid_gated: none

key-decisions:
  - "Executed Tasks 2 and 3's code before Task 1's checkpoint: neither depends on the WorkOS project existing, so pausing first would have banked no work"
  - "jwks_uri is constructor configuration, not derived from the issuer — /oauth2/jwks turned out to be correct, but it was only ever knowable by reading it"
  - "Repurposed test_build_token_verifier_rejects_unimplemented_mode rather than deleting it: 'authkit never degrades to static' outlives the 'not implemented' guard it was written around"
  - "Withheld the '## WorkOS AuthKit (verified)' heading at the checkpoint, then wrote it only once real values existed — the grep is a tripwire, not a formality"
  - "Read the Resource Indicator back from the deployed RFC 9728 document instead of composing it from the summary text, since Pitfall 8 is a character-for-character match"
  - "Did NOT touch deploy/cloud-run.env.yaml: the plan's files_modified excludes it, verification step 6 requires the deployed service unchanged, and 02-07 Task 1 owns the flip"
  - "Verified the recorded jwks_uri by pointing the real AuthKitJWTVerifier at it, rather than trusting that a URL in a JSON document is usable"

patterns-established:
  - "A fail-closed test asserts two things at once: the return value is None (closed) and the call returned rather than raising (quiet)"
  - "Assert a constructed dependency's wiring, not just its type — swapped issuer/audience arguments produce the right class and the wrong verifier"
  - "When a human reports dashboard state, find the independent machine-readable witness for it before recording it as fact"

requirements-completed: [MCP-04, DEPLOY-02]

# Metrics
duration: ~8min to the checkpoint + ~6min to resume and close
completed: 2026-08-29
---

# Phase 2 Plan 06: WorkOS AuthKit Stage-B Verifier Summary

**A WorkOS AuthKit tenant is live with CIMD and DCR both enabled and this server's Resource Indicator registered, and `AuthKitJWTVerifier` — proven by 10 tests against real RSA signatures and then pointed at the real tenant's JWKS — validates WorkOS RS256 tokens off the event loop, binds `aud` to the Resource Indicator, and fails closed and silent on a JWKS outage; the deployed service still runs Stage A on purpose, because the cutover is plan 02-07.**

## Status

| Task | Type | State |
|---|---|---|
| 1. Create the WorkOS AuthKit project and its three Connect settings | `checkpoint:human-action` | **COMPLETE** — prep `9da7f3e`, closed `db027da` |
| 2. Implement AuthKitJWTVerifier and wire the authkit branch | `auto` (TDD) | **COMPLETE** (`ab2c263` RED, `ca223c1` GREEN) |
| 3. Unit tests for the JWKS verifier | `auto` (TDD) | **COMPLETE** (`ab2c263` code, `db027da` deploy-log half) |

**3 of 3 tasks complete.**

## Task Commits

| # | Commit | Message |
|---|---|---|
| 1 | `ab2c263` | `test(02-06)`: add failing JWKS verifier tests for AuthKitJWTVerifier |
| 2 | `ca223c1` | `feat(02-06)`: implement AuthKitJWTVerifier and wire the authkit branch |
| 3 | `9da7f3e` | `docs(02-06)`: record the Task 1 prep and pause the WorkOS gate |
| 4 | `0a0e6d9` | `docs(02-06)`: partial-state summary at the WorkOS checkpoint |
| 5 | `db027da` | `docs(02-06)`: record the verified WorkOS AuthKit tenant, closing Task 1 |

TDD gate sequence satisfied: `test(...)` → `feat(...)`. No `refactor(...)` — the GREEN implementation needed no cleanup.

## The WorkOS tenant — what plan 02-07 needs

| Field | Value | Source |
|---|---|---|
| AuthKit domain | `https://quiet-fireplace-16-staging.authkit.app` | developer, matches the plan's `^https://[a-z0-9-]+\.authkit\.app$` regex (checked, not eyeballed) |
| `issuer` → `MCP_ISSUER_URL` | `https://quiet-fireplace-16-staging.authkit.app` | read from the discovery document; no trailing slash |
| `jwks_uri` → `MCP_JWKS_URI` | `https://quiet-fireplace-16-staging.authkit.app/oauth2/jwks` | read from the discovery document |
| `client_id_metadata_document_supported` | `true` | discovery document |
| `token_endpoint_auth_methods_supported` | `["none", "client_secret_post", "client_secret_basic"]` — contains `"none"` | discovery document |
| Resource Indicator | `https://brett-792870654598.us-central1.run.app/mcp` | read back from the live RFC 9728 document, then registered |
| Paid-gated? | **Nothing.** CIMD, DCR and Resource Indicators were all available without an upgrade | developer (A7) |

**Claude will select CIMD, not DCR.** Both preconditions hold simultaneously — `client_id_metadata_document_supported: true` **and** `"none"` in `token_endpoint_auth_methods_supported`. DCR stays enabled as the automatic fallback, which is what D-03 asked for. Nothing in our server code differs between the two paths, so this determines only what plan 02-07 should *expect to observe*, not what it must build.

## Accomplishments

- **The full OAuth chain now has an authorization server.** Before this plan the deployed service emitted a compliant `401` pointing at an RFC 9728 document that named a placeholder. The one missing link — a real AS for that document to point at — now exists.

- **Three assumptions closed, one of them at the transport layer rather than the documentation layer.**
  - **A1** (`jwks_uri`) — read, not derived. It *does* land on `/oauth2/jwks`, but that is recorded as a coincidence, not adopted as a rule: the verifier still takes the URI from configuration, because the value was only ever knowable by reading it.
  - **A2** (CIMD vs DCR) — both preconditions verified present; Claude will use CIMD.
  - **A7** (free-tier gating) — nothing gated, nothing upgraded, no cost incurred.

- **The human's dashboard report was corroborated, not merely transcribed.** Two of the three Connect toggles have independent machine-readable witnesses in the discovery document: CIMD by `client_id_metadata_document_supported: true`, and DCR by the presence of `registration_endpoint`, which AuthKit omits when DCR is off. Only the Resource Indicator remains developer-reported — it is not published in AS metadata and cannot be observed from outside until a real token's `aud` claim is inspected in 02-07. That limit is stated in the deploy log rather than glossed.

- **The recorded `jwks_uri` was probed with the real production object, not just `curl`.** The actual `AuthKitJWTVerifier` was constructed from the real settings and pointed at the live endpoint. Reachability and usability are different claims, and this proves the second:

  | Check | Observed |
  |---|---|
  | Keys published | exactly 1 — `kty=RSA`, `alg=RS256`, `use=sig` |
  | Algorithm vs. our allowlist | WorkOS signs **RS256**; `algorithms=["RS256"]` matches, so the allowlist will not reject genuine tokens |
  | `build_token_verifier` wiring | returns `AuthKitJWTVerifier`, **not** `StaticTokenVerifier`; `_issuer`, `_audience`, `_jwks.uri` each equal their source setting — no Pitfall-8 swap |
  | `PyJWKClient` cold fetch | 0.504 s |
  | `PyJWKClient` cached fetch | 0.0004 s — **T-02-08's "cold-start cost, not per-request cost" is now measured, not asserted** |
  | Fail-closed against the live endpoint | garbage token and unknown-key token both returned `None` and did not raise |

  The RS256 check is the one that would have hurt most if skipped. Had WorkOS signed with ES256, every genuine token would have been rejected by our allowlist and presented in 02-07 as a completed OAuth flow followed by a universal `401` — indistinguishable from a Resource Indicator mismatch.

- **The Stage-B verifier is exercised for real in tests.** A real RSA-2048 key pair signs real tokens; `jwt.decode` really makes the accept/reject call. Only the HTTPS key fetch is stubbed. A token signed by an unrelated key is genuinely rejected by the signature check, which is what makes the other seven rejection tests meaningful rather than circular.

- **All of the plan's threat-register `mitigate` rows are implemented and each has a test.** T-02-02 (two tests), T-02-07, T-02-08, T-02-04, algorithm confusion, T-02-10.

- **The mechanism swapped without the plumbing moving.** The 5 HTTP wire-contract tests from plan 02-04 — the 401 shape, the `resource_metadata=` pointer, the RFC 9728 path — pass unchanged. That was the design claim of the two-stage split and it now has evidence.

- **99 tests pass**, `ruff check backend/` clean, `mypy backend/app` clean across 20 files, gitleaks clean.

- **The deployed service was confirmed unaffected, after the final commit.** `POST /mcp` with no header → `401` with the byte-identical challenge; the RFC 9728 document still serves `authorization_servers: ["https://example.authkit.app"]`, which is the positive proof that no cutover leaked into this plan.

## Files Created/Modified

- `backend/app/mcp/auth.py` — added `AuthKitJWTVerifier`; replaced the `authkit` raise in `build_token_verifier`; extended the module docstring. `StaticTokenVerifier` is byte-for-byte untouched (confirmed by `git diff`).
- `backend/tests/test_mcp_auth.py` — 10 new tests, 2 module-scoped RSA fixtures, 3 helpers, and a docstring paragraph stating exactly where the stubbing boundary sits and why the inverse choice would be worthless.
- `.planning/phases/02-deploy-connector-auth-spike/02-DEPLOY-LOG.md` — the `## WorkOS AuthKit (verified)` section: the tenant, the four discovery fields verbatim, the Connect-toggle corroboration, the live JWKS probe, the `-staging` caveat, and the handoff block for 02-07.

**Deliberately NOT modified:** `deploy/cloud-run.env.yaml`. See "Scope boundary" below.

## Scope boundary — why the cutover did not happen here

`MCP_AUTH_MODE` is still `"static"` and `MCP_ISSUER_URL` / `MCP_JWKS_URI` still hold their placeholders. This is correct, and three independent sources in the repository agree:

1. **02-06's frontmatter `files_modified`** lists only `auth.py`, `test_mcp_auth.py` and `02-DEPLOY-LOG.md` — the env file is absent.
2. **02-06's verification step 6** states outright: *"The deployed service is UNCHANGED at this point — `MCP_AUTH_MODE` is still `static` in `deploy/cloud-run.env.yaml`. … The cutover is plan 02-07."*
3. **02-07's Task 1** is *"Flip `MCP_AUTH_MODE` to `authkit` and fill `MCP_ISSUER_URL` / `MCP_JWKS_URI`"*, sourcing both *"as recorded in `02-06-SUMMARY.md`"*.

02-07's acceptance criteria compare the env file against **this file** by grep rather than by eye, which is exactly why the two values appear in the frontmatter `workos:` block above as quotable strings.

## Decisions Made

**1. Tasks 2 and 3 were executed before Task 1's checkpoint.** The plan orders the WorkOS gate first, but nothing in the verifier or its tests depends on the project existing — the issuer and JWKS URI are constructor arguments, and every test generates its own key material. Pausing first would have returned a checkpoint with zero code committed.

**2. `jwks_uri` is passed in, never derived.** `/oauth2/jwks` is a WorkOS documentation claim; the discovery document is the only authoritative source. The claim turned out to be accurate — which changes nothing, because the point was never that the path is wrong, it is that deriving it makes a silent WorkOS path change into a total auth outage. `build_token_verifier` accordingly refuses to start when `MCP_JWKS_URI` is empty rather than constructing a client aimed at nothing.

**3. The `(verified)` heading was withheld at the checkpoint and written on resume.** Task 3's own verification greps `02-DEPLOY-LOG.md` for `## WorkOS AuthKit (verified)`. Writing that heading over placeholders would have made the grep pass while proving nothing, so the phrase was kept out of the file entirely (`grep -c` → `0`) until a real discovery document had been read. It now returns `1` over real values, which is the state the check was designed to certify.

**4. The env file was left alone.** See "Scope boundary". The temptation was real — the two values are known and the edit is two lines — but 02-07's Task 1 verification asserts `MCP_AUTH_MODE == "authkit"` in the same file, so a partial edit here would have left the phase in a state neither plan describes.

## Observation — the `-staging` AuthKit domain

The domain carries a `-staging` component: `https://quiet-fireplace-16-staging.authkit.app`. **This is not a blocker and creates no conflict with any acceptance criterion** — the domain matches the plan's `^https://[a-z0-9-]+\.authkit\.app$` regex, and the tenant is fully functional (discovery document, registration endpoint and JWKS all live and serving).

It is WorkOS's own naming for the default environment a new project receives, not a deliberate staging-versus-production choice by the developer. Flagged rather than silently normalised, because there is a genuine forward-looking consequence: **in WorkOS each environment has its own AuthKit domain, its own signing keys and its own JWKS.** If this project is ever promoted to a production environment, both `MCP_ISSUER_URL` and `MCP_JWKS_URI` change and staging-minted tokens stop validating. That is a configuration change rather than a code change — which is precisely the property that made both values constructor arguments in the first place.

No action needed for 02-07. Recorded in `02-DEPLOY-LOG.md` under "The `-staging` suffix — read before plan 02-07".

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Implementing `authkit` breaks an existing test the plan requires to keep passing**

- **Found during:** Task 2/3 planning, before writing any code
- **Issue:** `test_build_token_verifier_rejects_unimplemented_mode` asserts `"02-06" in str(excinfo.value)` — it is pinned to the exact stub string this plan is instructed to delete. The plan simultaneously requires `grep -q 'not implemented until plan 02-06'` to return **no match** and "the 13 existing tests still pass". Those two criteria cannot both hold with the test as written. Left alone, the suite would have gone red the moment the stub was replaced, with the `MCP_JWKS_URI` error message failing an assertion looking for a plan number.
- **Fix:** Repurposed rather than deleted. Renamed to `test_build_token_verifier_authkit_never_degrades_to_static` and rewritten to assert the property the original docstring actually cared about — *"`authkit` must raise, never silently degrade to static bearer"* — which survives the implementation intact and is now the stronger claim: fully configured, the mode must not return a `StaticTokenVerifier`; half configured, it must refuse to start. Deleting it and relying on the two new `build_token_verifier` tests would have dropped the test count to 22 and lost the "never degrade" framing.
- **Files modified:** `backend/tests/test_mcp_auth.py`
- **Verification:** `grep -c 'def test_'` returns 23 and `grep -c 'def test_authkit_'` returns 8, exactly as the acceptance criteria require; 23 passed, 0 failed.
- **Committed in:** `ab2c263`

**2. [Rule 2 - Missing critical] `test_build_token_verifier_returns_authkit` as specified would pass with the arguments swapped**

- **Found during:** Task 3
- **Issue:** The plan's behaviour spec is "returns an `AuthKitJWTVerifier`". An implementation that passed `issuer=` where `audience=` belonged would satisfy that assertion perfectly — and would then reject every token WorkOS ever issued, presenting in plan 02-07 as a completed OAuth flow followed by a 401 on every request. That is precisely the Pitfall 8 failure mode this plan exists to avoid, and an `isinstance` check cannot see it.
- **Fix:** Added three assertions on the constructed instance: `_issuer`, `_audience` and `_jwks.uri` each equal the setting they came from. `AUDIENCE` is deliberately set to a different string from `ISSUER` in the test constants, so a swap cannot pass by coincidence.
- **Files modified:** `backend/tests/test_mcp_auth.py`
- **Verification:** Mutation-tested, not assumed. `build_token_verifier`'s two keyword arguments were deliberately transposed and the test was re-run; it failed with `assert 'https://brett.example.com/mcp' == 'https://example.authkit.app'`. The mutation was then reverted and `git diff HEAD` confirmed empty. An `isinstance`-only test would have stayed green through that mutation. **Re-confirmed on resume against the real tenant**, where the same three fields were asserted with production values.
- **Committed in:** `ab2c263`

**3. [Rule 2 - Missing critical] A second RSA key pair was needed that the plan's fixture list does not mention**

- **Found during:** Task 3
- **Issue:** `test_authkit_rejects_unknown_signing_key` needs a token signed by a key that is not the tenant's, but the plan specifies only one `rsa_key` fixture. Generating the second key inside the test body would have put a ~0.2 s RSA-2048 keygen in the hot path of a unit suite that otherwise runs in milliseconds.
- **Fix:** Added a second module-scoped fixture, `foreign_rsa_key`. Module scope keeps the cost paid once.
- **Files modified:** `backend/tests/test_mcp_auth.py`
- **Verification:** The full module runs in 2.68 s.
- **Committed in:** `ab2c263`

**4. [Rule 2 - Missing critical] Writing the deploy-log heading at the checkpoint would defeat its own verification**

- **Found during:** Task 3 (at the checkpoint), resolved on resume
- **Issue:** Task 3 instructs a `## WorkOS AuthKit (verified)` section, and Task 3's `<verify>` greps for that exact string. With the four discovery values unknown, writing it would have satisfied the grep with placeholder content — the grep would then certify nothing for the remainder of the phase. A first draft of the blocked section also *mentioned* the phrase in prose, which by itself made the grep return 1.
- **Fix:** At the checkpoint, the section was written under `## WorkOS AuthKit — BLOCKED at the plan 02-06 Task 1 checkpoint` with the literal phrase scrubbed from the file entirely. On resume, once real values existed, the heading was written as the plan specifies and the blocked framing removed.
- **Files modified:** `.planning/phases/02-deploy-connector-auth-spike/02-DEPLOY-LOG.md`
- **Verification:** `grep -c 'WorkOS AuthKit (verified)'` → `0` at the checkpoint, `1` after resume. `grep -c 'BLOCKED at the plan 02-06'` → `0` after resume.
- **Committed in:** `9da7f3e` (blocked form), `db027da` (verified form)

**5. [Rule 3 - Blocking] The worktree was based on a commit five behind the required base**

- **Found during:** Startup, before any task
- **Issue:** `git merge-base HEAD 06bc917` returned `1e97f3b`, i.e. HEAD was an *ancestor* of the required base — the worktree predated wave 5 and did not contain plan 02-05's deploy log or summary, both of which this plan reads.
- **Fix:** `git reset --hard 06bc917aafedce886e4b35d416b23240c9e36908` on a clean tree, then re-verified `git rev-parse HEAD`.
- **Verification:** HEAD matched the required base exactly; no work was lost (the tree was clean).
- **Committed in:** n/a — a base correction, not a change

### Additions on resume (not deviations — Rule 2 verification hardening)

**6. [Rule 2 - Missing critical] The plan verifies `jwks_uri` is *present*, never that it is *usable***

- **Found during:** Task 1 closure on resume
- **Issue:** Task 1's acceptance criteria stop at "that JSON carries a non-empty `issuer` and a non-empty `jwks_uri`". A URI can be non-empty, well-formed, and still unusable — unreachable, empty of keys, or publishing keys in an algorithm our `algorithms=["RS256"]` allowlist rejects. Every one of those failures would surface for the first time in plan 02-07, as a completed OAuth flow followed by a universal `401`, which is indistinguishable from a Resource Indicator mismatch and is the single hardest failure in this phase to diagnose.
- **Fix:** Probed the live JWKS with the real `AuthKitJWTVerifier` built from the real settings — confirming 1 published RSA key with `alg=RS256` (matching our allowlist), correct `_issuer`/`_audience`/`_jwks.uri` wiring, working `cache_jwk_set`, and fail-closed behaviour against the live endpoint. No credential is involved; the JWKS is a public document and nothing was mutated.
- **Files modified:** none — verification only; results recorded in `02-DEPLOY-LOG.md`
- **Verification:** Recorded in the deploy log under "The live JWKS, probed with the real verifier".
- **Committed in:** `db027da` (the evidence)

---

**Total deviations:** 6 auto-fixed (1 bug, 4 missing-critical, 1 blocking). None changes what the plan builds — five are defects in the plan's test and documentation instructions, and one adds verification depth the plan omitted. No Rule 4 escalation: the architecture is exactly as specified.

## Issues Encountered

**A circular TDD dependency between Tasks 2 and 3.** Both are marked `tdd="true"`, but Task 3 *is* the test suite for Task 2's code, so following each task's RED/GREEN cycle independently is impossible. Resolved by running one cycle across both: RED wrote all 10 tests and watched them fail at import (`ImportError: cannot import name 'AuthKitJWTVerifier'`), GREEN implemented the class and turned them green. The gate sequence in `git log` is correct, and each task still has an identifiable commit.

**The `-staging` domain suffix** — see the dedicated section above. Flagged, not worked around; not a blocker.

**Nothing else.** The implementation matched the RESEARCH Pattern-5 sketch on the first attempt; ruff, ruff-format and mypy were clean without iteration. The WorkOS tenant worked on the first probe with no gating and no configuration surprises.

## Verification Evidence

| Plan verification step | Result |
|---|---|
| 1. `uv run pytest -q` (full suite, Docker up) — 23 tests in `test_mcp_auth.py` | **99 passed**, 0 failed; `test_mcp_auth.py` reports **23 passed** in 2.68 s |
| 2. `uv run ruff check backend/ && uv run mypy backend/app` | both clean (mypy: 20 source files) |
| 3. `curl .../.well-known/oauth-authorization-server` against the AuthKit domain | **`200` in 0.946 s**; `issuer`, `jwks_uri`, `client_id_metadata_document_supported: true`, `token_endpoint_auth_methods_supported` all recorded verbatim |
| 4. `grep -c 'log\.' backend/app/mcp/auth.py` | `0` |
| 5. `uv run pre-commit run gitleaks --all-files` | Passed |
| 6. Deployed service unchanged; Stage A still serving | `MCP_AUTH_MODE` still `static` in `deploy/cloud-run.env.yaml` (`git diff --stat` empty); row 1 → `401` with the byte-identical challenge; RFC 9728 doc still serves `authorization_servers: ["https://example.authkit.app"]` |

**Task 1 acceptance criteria, each checked:**

| Criterion | Observed |
|---|---|
| Domain matches `^https://[a-z0-9-]+\.authkit\.app$` | **True** (regex-checked in Python, not eyeballed) |
| `curl -sf <domain>/.well-known/oauth-authorization-server` → 200 + valid JSON | `200`, valid JSON, 0.946 s |
| Non-empty `issuer` and `jwks_uri`, reported verbatim (A1) | both present, both recorded verbatim |
| `client_id_metadata_document_supported` reported verbatim (A2) | `true` |
| `"none"` in `token_endpoint_auth_methods_supported` reported verbatim (A2) | present — `["none", "client_secret_post", "client_secret_basic"]` |
| CIMD, DCR and Resource Indicator all confirmed | CIMD and DCR **independently corroborated** by the discovery document; Resource Indicator developer-reported (not observable externally) |
| Paid-gating reported rather than silently upgraded (A7) | nothing gated, nothing upgraded |
| No WorkOS client secret requested, obtained, or stored | none — the resource-server flow needs none |

**Every acceptance-criteria grep, run and recorded:**

| Check | Required | Observed |
|---|---|---|
| `grep -c 'class AuthKitJWTVerifier'` | ≥1 | `1` |
| `grep -c 'anyio.to_thread.run_sync'` | `2` | `2` |
| `grep -c 'algorithms=["RS256"]'` | ≥1 | `1` |
| `grep -c 'options={"require": ["exp", "iss", "aud"]}'` | ≥1 | `1` |
| `grep -c 'audience=self._audience'` | ≥1 | `1` |
| `grep -c 'log\.'` in `auth.py` | `0` | `0` |
| `grep -c 'class StaticTokenVerifier'` | ≥1 | `1`, body unchanged per `git diff` |
| `grep -c 'not implemented until plan 02-06'` | `0` | `0` |
| `grep -c 'def test_'` | `23` | `23` |
| `grep -c 'def test_authkit_'` | `8` | `8` |
| `grep -c 'rsa.generate_private_key'` | ≥1 | `2` |
| `grep -c 'get_signing_key_from_jwt'` | ≥1 | `4` |
| `grep -c 'jwt.decode.*monkeypatch\|setattr(jwt'` | `0` | `0` |
| `grep -c 'WorkOS AuthKit (verified)'` in the deploy log | ≥1 | `1` |
| `grep -icE 'Bearer [A-Za-z0-9_.-]{30,}\|postgres(ql)?://…@'` in the deploy log | `0` | `0` |

## Security Notes

Every `mitigate` disposition in this plan's threat register is implemented and has a test:

- **T-02-02** (confused deputy / token replay) — `audience=self._audience` binds `aud` to the registered Resource Indicator, and `options={"require": ["exp","iss","aud"]}` makes the claim mandatory. Two tests: `test_authkit_rejects_wrong_audience` and `test_authkit_rejects_token_without_audience`. The second matters most — without `require`, PyJWT skips a claim it does not find, so a token omitting `aud` would sail through. The WorkOS half is now in place: the Resource Indicator is registered, so AuthKit will stamp `aud`.
- **T-02-07** (JWKS outage → fail open) — every exception path returns `None`. `test_authkit_rejects_when_jwks_fetch_fails` asserts both halves: `is None` (closed) and that the call returned at all rather than raising (quiet). **Additionally confirmed against the live WorkOS endpoint on resume**, where a garbage token and an unknown-key token both returned `None` without raising. `cache_jwk_set=True` (300 s) keeps a transient outage from becoming an instant lockout — measured at 0.504 s cold versus 0.0004 s cached.
- **T-02-08** (blocking JWKS fetch stalls the event loop) — both `PyJWKClient` calls go through `anyio.to_thread.run_sync`; the count is asserted at exactly 2. The "cold-start cost, not per-request cost" claim is now measured against the real tenant rather than asserted from the docs.
- **T-02-04** (token or claims in logs) — zero logging statements in the module; the exception is swallowed rather than re-raised, so no traceback can carry the token upward.
- **Algorithm confusion** — `algorithms=["RS256"]` explicitly. `test_authkit_rejects_alg_none_token` uses a hand-built unsigned token (PyJWT will not mint one) with the key fetch stubbed to *succeed*, so the allowlist is the only thing left standing. `test_authkit_rejects_unknown_signing_key` covers the foreign-key case. **The live tenant confirms WorkOS signs with RS256**, so the allowlist is correctly matched to reality rather than merely restrictive.
- **T-02-10** (WorkOS credentials) — none exist, and none were created. The resource-server flow needs no client secret; `MCP_ISSUER_URL` and `MCP_JWKS_URI` are public URLs that correctly stay out of `_SECRET_FIELDS`. Nothing in the deploy log or this summary is a credential.
- **A7 (cost)** — resolved. Nothing was paid-gated and nothing was upgraded.

**Credential handling.** No credential was used on resume: every probe in this session hit public, unauthenticated documents (the AuthKit discovery document, the AuthKit JWKS, and the deployed service's RFC 9728 document plus its unauthenticated `401` path). The earlier session's matrix row 3 needed the live `MCP_AUTH_SECRET`; it was read from Secret Manager into a temporary file outside the repository, loaded from that file rather than passed on a command line, and deleted immediately. It appears in no commit and no log file.

**No threat flags.** No new network endpoint, auth path, file access pattern or schema change was introduced. The `authkit` code path remains unreachable on the deployed service, which still runs `MCP_AUTH_MODE=static`.

## Known Stubs

| Stub | File | Line | Reason / resolver |
|---|---|---|---|
| `MCP_AUTH_MODE: "static"`, `MCP_ISSUER_URL: "https://example.authkit.app"`, `MCP_JWKS_URI: ""` | `deploy/cloud-run.env.yaml` | 36-38 | **Intentional and in scope for 02-07, not a defect of this plan.** 02-06's `files_modified` excludes this file and its verification step 6 requires the deployed service unchanged. The real values are recorded in this summary's frontmatter `workos:` block and in `02-DEPLOY-LOG.md`, which is where 02-07 Task 1 sources them. |

No stub in the code prevents this plan's goal. `AuthKitJWTVerifier` is complete and was exercised against the real tenant.

## User Setup Required

**None outstanding.** The WorkOS setup that blocked this plan is done: the developer created the project, enabled CIMD and DCR, registered the Resource Indicator `https://brett-792870654598.us-central1.run.app/mcp`, and configured the Claude.ai callback plus the RFC 8252 loopback pair. No WorkOS client secret was needed or created.

## Next Phase Readiness

**Plan 02-07 is unblocked.** Both values it was waiting on now exist and are quotable verbatim from this file's frontmatter:

```yaml
MCP_ISSUER_URL: "https://quiet-fireplace-16-staging.authkit.app"
MCP_JWKS_URI: "https://quiet-fireplace-16-staging.authkit.app/oauth2/jwks"
```

**No further code is needed for the cutover** — only the two env values, the `MCP_AUTH_MODE` flip, and a redeploy.

**What 02-07 should expect:**
- **CIMD, not DCR.** Both preconditions hold. If Claude nonetheless registers via DCR, that is a client-side choice, not a server misconfiguration — `registration_endpoint` is live either way.
- **`--min=1` is pre-authorised** (D-06f) and must not be re-asked. The measured cold start is **7.53 s** against Claude's 10-second discovery budget.
- **A residual Neon wake-up penalty of roughly 0.3–0.5 s** even with `--min=1`, since Neon autosuspends after 5 minutes idle independently of Cloud Run.
- **The `aud` claim is the first real test of the Resource Indicator.** It is the one Connect setting with no external witness; a completed OAuth flow followed by a universal `401` means a character mismatch there, not a verifier bug — the verifier's wiring is already confirmed correct against the live tenant.
- **The `-staging` domain caveat** — see the observation section. No action needed now.

### Defect found in plan 02-07's own verify command — fix before running it

Plan 02-07 Task 1's `<automated>` verification ends with:

```bash
uv run python -c "import yaml,pathlib; d=yaml.safe_load(...)"
```

**This will fail with `ModuleNotFoundError: No module named 'yaml'`.** Reproduced in this worktree. `pyyaml==6.0.3` lives in the `dev` dependency group, and `pyproject.toml` sets `[tool.uv] default-groups = []` — a deliberate choice from plan 02-08 that keeps 32 dev packages out of the production image. So a bare `uv run python` gets the production environment, which has no `yaml`.

The first half of the same command (`uv run pytest backend/tests/test_cloud_run_deploy.py -q`) is unaffected and passes 12 tests, because that path resolves the dev group — which is exactly why the defect is easy to miss: the command fails only after its first half succeeds.

Fix — either form works, both verified here:

```bash
uv run --group dev python -c "import yaml,pathlib; ..."   # preferred: uses the pinned 6.0.3
uv run --with pyyaml python -c "import yaml,pathlib; ..."
```

This is a defect in the plan's tooling invocation, not in the deploy config it inspects. Flagged rather than fixed, because editing 02-07's plan text is outside this plan's scope.

## Self-Check: PASSED

- **Files claimed modified verified present and changed:** `backend/app/mcp/auth.py`, `backend/tests/test_mcp_auth.py` and `02-DEPLOY-LOG.md` all appear in `git show --stat` for their respective commits.
- **All five claimed commits verified in `git log`:** `ab2c263`, `ca223c1`, `9da7f3e`, `0a0e6d9`, `db027da`.
- **Test counts verified by running, not asserted:** `23 passed` for the module, `99 passed` for the full suite.
- **Every acceptance-criteria grep was executed and its literal output recorded** in the tables above, rather than being assumed from the code.
- **The RED phase was genuinely red:** collection failed with `ImportError: cannot import name 'AuthKitJWTVerifier'` before the implementation commit. No test was written against already-working code.
- **One assertion was mutation-tested rather than trusted** (Deviation #2), and the mutation reverted with `git diff HEAD` confirmed empty afterwards.
- **Every WorkOS value in this file was read from the live discovery document**, and the `jwks_uri` was additionally probed with the real verifier. None is transcribed from the plan, the research document, or the developer's message without an independent check — except the Resource Indicator registration, which is explicitly marked as developer-reported because it has no external witness.
- **The deployed service was probed live after the final commit**, not assumed unchanged, and `deploy/cloud-run.env.yaml` has an empty `git diff`.
- **The scope boundary was checked against three independent sources** before deciding not to edit the env file.
- **No credential appears anywhere:** gitleaks passed, and `grep -icE 'Bearer [A-Za-z0-9_.-]{30,}|postgres(ql)?://…@'` returns `0` against the deploy log.

**Not modified, by design (worktree mode):** `.planning/STATE.md` and `.planning/ROADMAP.md` — the orchestrator owns those writes.

---
*Phase: 02-deploy-connector-auth-spike*
*Status: COMPLETE — 3/3 tasks; deployed service deliberately still on Stage A*
*Date: 2026-08-29*
