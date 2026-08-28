---
phase: 02-deploy-connector-auth-spike
plan: 06
subsystem: auth
tags: [jwt, jwks, pyjwt, workos, authkit, oauth, mcp, rs256, anyio]
status: PARTIAL — Tasks 2 and 3's code complete; BLOCKED at the Task 1 WorkOS human-action checkpoint

# Dependency graph
requires:
  - phase: 02-deploy-connector-auth-spike (plan 05)
    provides: the live Cloud Run service, the reconciled canonical hostname, and the deployed RFC 9728 document whose `resource` field is the exact Resource Indicator this plan must register
  - phase: 02-deploy-connector-auth-spike (plan 02)
    provides: StaticTokenVerifier, build_token_verifier and its `authkit` stub, and the 8 Stage-A unit tests
  - phase: 02-deploy-connector-auth-spike (plan 04)
    provides: the 5 HTTP wire-contract tests (401 shape, RFC 9728 path) that must keep passing unchanged across the mechanism swap
provides:
  - AuthKitJWTVerifier — RS256 JWKS validation enforcing iss, exp and an aud equal to the registered Resource Indicator, off the event loop, failing closed and silent
  - build_token_verifier's `authkit` branch, which now returns a verifier instead of raising, and refuses to start on an empty MCP_JWKS_URI rather than degrading to static bearer
  - 10 new unit tests (23 total in test_mcp_auth.py) driven by a real RSA-2048 key pair, with only the JWKS key fetch stubbed
  - The exact Resource Indicator string, read back from the live metadata document rather than composed by hand
  - Evidence that the deployed Stage-A service is unaffected by this plan
affects: [02-07 connector round-trip and the MCP_AUTH_MODE=authkit cutover]

# Tech tracking
tech-stack:
  added:
    - "pyjwt 2.13.0 PyJWKClient — already in the tree as an mcp transitive; no new dependency"
    - "cryptography 50.0.1 rsa key generation in tests — likewise transitive"
  patterns:
    - "Push a blocking third-party call out of an async handler with anyio.to_thread.run_sync rather than accepting event-loop stalls"
    - "Stub the network, never the decision: replace only PyJWKClient.get_signing_key_from_jwt so signature, iss, aud, exp and the algorithm allowlist all run for real"
    - "Read a must-match-exactly string back from the live system that already serves it, instead of retyping it from a document"
    - "Refuse to write a heading that an automated check greps for, when the values under it are not yet known"

key-files:
  created:
    - .planning/phases/02-deploy-connector-auth-spike/02-06-SUMMARY.md
  modified:
    - backend/app/mcp/auth.py
    - backend/tests/test_mcp_auth.py
    - .planning/phases/02-deploy-connector-auth-spike/02-DEPLOY-LOG.md

key-decisions:
  - "Executed Tasks 2 and 3's code before Task 1's checkpoint: neither depends on the WorkOS project existing, so pausing first would have banked no work"
  - "jwks_uri is constructor configuration, not derived from the issuer — /oauth2/jwks is a documentation claim and RESEARCH assumption A1 is unresolved"
  - "Repurposed test_build_token_verifier_rejects_unimplemented_mode rather than deleting it: 'authkit never degrades to static' outlives the 'not implemented' guard it was written around"
  - "Did NOT write the '## WorkOS AuthKit (verified)' heading Task 3 specifies, because Task 3's own verify step greps for it — writing it over unknown values would convert a tripwire into a rubber stamp"
  - "Read the Resource Indicator back from the deployed RFC 9728 document instead of composing it from the summary text, since Pitfall 8 is a character-for-character match"

patterns-established:
  - "A fail-closed test asserts two things at once: the return value is None (closed) and the call returned rather than raised (quiet)"
  - "Assert a constructed dependency's wiring, not just its type — swapped issuer/audience arguments produce the right class and the wrong verifier"

requirements-completed: []  # MCP-04 and DEPLOY-02 remain OPEN — the WorkOS half is unbuilt

# Metrics
duration: ~8min agent time to the checkpoint
completed: 2026-08-28 (partial)
---

# Phase 2 Plan 06: WorkOS AuthKit Stage-B Verifier Summary (PARTIAL — at checkpoint)

**`AuthKitJWTVerifier` is written, type-clean and proven by 10 new tests against real RSA signatures — it validates WorkOS RS256 tokens off the event loop, binds `aud` to this server's Resource Indicator, and fails closed and silent on a JWKS outage — but no WorkOS project exists yet, so the issuer and JWKS URI it must be pointed at are still unknown and Task 1 is blocked on a dashboard-only step.**

## Status

| Task | Type | State |
|---|---|---|
| 1. Create the WorkOS AuthKit project and its three Connect settings | `checkpoint:human-action` | **BLOCKED — awaiting the developer.** All automatable prep done (`9da7f3e`) |
| 2. Implement AuthKitJWTVerifier and wire the authkit branch | `auto` (TDD) | **COMPLETE** (`ab2c263` RED, `ca223c1` GREEN) |
| 3. Unit tests for the JWKS verifier | `auto` (TDD) | **CODE COMPLETE** (`ab2c263`). The deploy-log half is blocked on Task 1's four discovery values |

**2 of 3 tasks complete; the third is complete apart from transcribing values that do not exist yet.**

## Task Commits

| # | Commit | Message |
|---|---|---|
| 1 | `ab2c263` | `test(02-06)`: add failing JWKS verifier tests for AuthKitJWTVerifier |
| 2 | `ca223c1` | `feat(02-06)`: implement AuthKitJWTVerifier and wire the authkit branch |
| 3 | `9da7f3e` | `docs(02-06)`: record the Task 1 prep and pause the WorkOS gate |

TDD gate sequence satisfied: `test(...)` → `feat(...)`. No `refactor(...)` — the GREEN implementation needed no cleanup.

## Accomplishments

- **The Stage-B verifier exists and is exercised for real.** A real RSA-2048 key pair signs real tokens; `jwt.decode` really makes the accept/reject call. Only the HTTPS key fetch is stubbed. A token signed by an unrelated key is genuinely rejected by the signature check, which is what makes the other seven rejection tests meaningful rather than circular.
- **All eight of the plan's threat-register `mitigate` rows are implemented and each has a test.** T-02-02 (two tests), T-02-07, T-02-08, T-02-04, and algorithm confusion.
- **The mechanism swapped without the plumbing moving.** The 5 HTTP wire-contract tests from plan 02-04 — the 401 shape, the `resource_metadata=` pointer, the RFC 9728 path — pass unchanged. That was the design claim of the two-stage split and it now has evidence.
- **99 tests pass** (up from 89), `ruff check backend/` clean, `mypy backend/app` clean across 20 files, gitleaks clean.
- **The deployed service was confirmed unaffected.** Rows 1 and 3 of the Auth Verification Matrix re-run against the live URL after the code landed: `401` with the byte-identical challenge, and `200` returning exactly `fitness_ping` in 0.329 s.
- **The Resource Indicator was read, not retyped.** `https://brett-792870654598.us-central1.run.app/mcp`, taken from the `resource` field the live metadata document already serves.

## Files Created/Modified

- `backend/app/mcp/auth.py` — added `AuthKitJWTVerifier`; replaced the `authkit` raise in `build_token_verifier`; extended the module docstring. `StaticTokenVerifier` is byte-for-byte untouched (confirmed by `git diff`).
- `backend/tests/test_mcp_auth.py` — 10 new tests, 2 module-scoped RSA fixtures, 3 helpers, and a docstring paragraph stating exactly where the stubbing boundary sits and why the inverse choice would be worthless.
- `.planning/phases/02-deploy-connector-auth-spike/02-DEPLOY-LOG.md` — a `## WorkOS AuthKit — BLOCKED …` section holding the established values, the four outstanding ones, the prepared probe command, and the Stage-A regression evidence.

## Decisions Made

**1. Tasks 2 and 3 were executed before Task 1's checkpoint.** The plan orders the WorkOS gate first, but nothing in the verifier or its tests depends on the project existing — the issuer and JWKS URI are constructor arguments, and every test generates its own key material. Pausing first would have returned a checkpoint with zero code committed.

**2. `jwks_uri` is passed in, never derived.** The plan is emphatic and this implementation honours it: `/oauth2/jwks` is a WorkOS documentation claim, RESEARCH assumption A1 is unresolved, and the discovery document is the only authoritative source. Consequently `build_token_verifier` refuses to start when `MCP_JWKS_URI` is empty rather than constructing a client aimed at nothing.

**3. The `(verified)` heading was deliberately withheld.** Task 3's own verification greps `02-DEPLOY-LOG.md` for `## WorkOS AuthKit (verified)`. Writing that heading now — with placeholders under it — would make the grep pass while proving nothing. The section is present under an explicitly-blocked heading instead, and the literal phrase is kept out of the file so the grep still returns zero.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Implementing `authkit` breaks an existing test the plan requires to keep passing**

- **Found during:** Task 2/3 planning, before writing any code
- **Issue:** `test_build_token_verifier_rejects_unimplemented_mode` asserts `"02-06" in str(excinfo.value)` — it is pinned to the exact stub string this plan is instructed to delete. The plan simultaneously requires `grep -q 'not implemented until plan 02-06'` to return **no match** and "the 13 existing tests still pass". Those two criteria cannot both hold with the test as written. Left alone, the suite would have gone red the moment the stub was replaced, with the `MCP_JWKS_URI` error message failing an assertion looking for a plan number.
- **Fix:** Repurposed rather than deleted. Renamed to `test_build_token_verifier_authkit_never_degrades_to_static` and rewritten to assert the property the original docstring actually cared about — *"``authkit`` must raise, never silently degrade to static bearer"* — which survives the implementation intact and is now the stronger claim: fully configured, the mode must not return a `StaticTokenVerifier`; half configured, it must refuse to start. Deleting it and relying on the two new `build_token_verifier` tests would have dropped the test count to 22 and lost the "never degrade" framing.
- **Files modified:** `backend/tests/test_mcp_auth.py`
- **Verification:** `grep -c 'def test_'` returns 23 and `grep -c 'def test_authkit_'` returns 8, exactly as the acceptance criteria require; 23 passed, 0 failed.
- **Committed in:** `ab2c263`

**2. [Rule 2 - Missing critical] `test_build_token_verifier_returns_authkit` as specified would pass with the arguments swapped**

- **Found during:** Task 3
- **Issue:** The plan's behaviour spec is "returns an `AuthKitJWTVerifier`". An implementation that passed `issuer=` where `audience=` belonged would satisfy that assertion perfectly — and would then reject every token WorkOS ever issued, presenting in plan 02-07 as a completed OAuth flow followed by a 401 on every request. That is precisely the Pitfall 8 failure mode this plan exists to avoid, and an `isinstance` check cannot see it.
- **Fix:** Added three assertions on the constructed instance: `_issuer`, `_audience` and `_jwks.uri` each equal the setting they came from. `AUDIENCE` is deliberately set to a different string from `ISSUER` in the test constants, so a swap cannot pass by coincidence.
- **Files modified:** `backend/tests/test_mcp_auth.py`
- **Verification:** Mutation-tested, not assumed. `build_token_verifier`'s two keyword arguments were deliberately transposed and the test was re-run; it failed with `assert 'https://brett.example.com/mcp' == 'https://example.authkit.app'`. The mutation was then reverted and `git diff HEAD` confirmed empty. An `isinstance`-only test would have stayed green through that mutation.
- **Committed in:** `ab2c263`

**3. [Rule 2 - Missing critical] A second RSA key pair was needed that the plan's fixture list does not mention**

- **Found during:** Task 3
- **Issue:** `test_authkit_rejects_unknown_signing_key` needs a token signed by a key that is not the tenant's, but the plan specifies only one `rsa_key` fixture. Generating the second key inside the test body would have put a ~0.2 s RSA-2048 keygen in the hot path of a unit suite that otherwise runs in milliseconds.
- **Fix:** Added a second module-scoped fixture, `foreign_rsa_key`. Module scope keeps the cost paid once.
- **Files modified:** `backend/tests/test_mcp_auth.py`
- **Verification:** The full module runs in 2.64 s.
- **Committed in:** `ab2c263`

**4. [Rule 2 - Missing critical] Writing the deploy-log heading now would defeat its own verification**

- **Found during:** Task 3
- **Issue:** Task 3 instructs a `## WorkOS AuthKit (verified)` section, and Task 3's `<verify>` greps for that exact string. With the four discovery values unknown, writing it would satisfy the grep with placeholder content — the grep would then certify nothing for the remainder of the phase. A first draft of the blocked section also *mentioned* the phrase in prose, which by itself made the grep return 1.
- **Fix:** Section written under `## WorkOS AuthKit — BLOCKED at the plan 02-06 Task 1 checkpoint`, with the literal phrase scrubbed from the file entirely (`grep -c` confirms `0`) and a note explaining that it stays absent until a real discovery document has been read.
- **Files modified:** `.planning/phases/02-deploy-connector-auth-spike/02-DEPLOY-LOG.md`
- **Verification:** `grep -c 'WorkOS AuthKit (verified)' 02-DEPLOY-LOG.md` → `0`.
- **Committed in:** `9da7f3e`

**5. [Rule 3 - Blocking] The worktree was based on a commit five behind the required base**

- **Found during:** Startup, before any task
- **Issue:** `git merge-base HEAD 06bc917` returned `1e97f3b`, i.e. HEAD was an *ancestor* of the required base — the worktree predated wave 5 and did not contain plan 02-05's deploy log or summary, both of which this plan reads.
- **Fix:** `git reset --hard 06bc917aafedce886e4b35d416b23240c9e36908` on a clean tree, then re-verified `git rev-parse HEAD`.
- **Verification:** HEAD matched the required base exactly; no work was lost (the tree was clean).
- **Committed in:** n/a — a base correction, not a change

---

**Total deviations:** 5 auto-fixed (1 bug, 3 missing-critical, 1 blocking). All five are defects in the plan's *test and documentation instructions*; none changes what the plan builds. No Rule 4 escalation — the architecture is exactly as specified.

## Issues Encountered

**A circular TDD dependency between Tasks 2 and 3.** Both are marked `tdd="true"`, but Task 3 *is* the test suite for Task 2's code, so following each task's RED/GREEN cycle independently is impossible. Resolved by running one cycle across both: RED wrote all 10 tests and watched them fail at import (`ImportError: cannot import name 'AuthKitJWTVerifier'`), GREEN implemented the class and turned them green. The gate sequence in `git log` is correct, and each task still has an identifiable commit.

**Nothing else.** The implementation matched the RESEARCH Pattern-5 sketch on the first attempt; ruff, ruff-format and mypy were clean without iteration.

## Verification Evidence

| Plan verification step | Result |
|---|---|
| 1. `uv run pytest -q` (full suite, Docker up) — 23 tests in `test_mcp_auth.py` | **99 passed**, 0 failed; `test_mcp_auth.py` reports **23 passed** |
| 2. `uv run ruff check backend/ && uv run mypy backend/app` | both clean (mypy: 20 source files) |
| 3. `curl .../.well-known/oauth-authorization-server` against the AuthKit domain | **BLOCKED** — no WorkOS tenant exists |
| 4. `grep -c 'log\.' backend/app/mcp/auth.py` | `0` |
| 5. `uv run pre-commit run gitleaks --all-files` | Passed |
| 6. Deployed service unchanged; matrix row 3 still works | `MCP_AUTH_MODE` still `static` in `deploy/cloud-run.env.yaml`; row 1 → `401` with the byte-identical challenge, row 3 → `200` / `['fitness_ping']` in 0.329 s |

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

## Security Notes

Every `mitigate` disposition in this plan's threat register is implemented and has a test:

- **T-02-02** (confused deputy / token replay) — `audience=self._audience` binds `aud` to the registered Resource Indicator, and `options={"require": ["exp","iss","aud"]}` makes the claim mandatory. Two tests: `test_authkit_rejects_wrong_audience` and `test_authkit_rejects_token_without_audience`. The second matters most — without `require`, PyJWT skips a claim it does not find, so a token omitting `aud` would sail through.
- **T-02-07** (JWKS outage → fail open) — every exception path returns `None`. `test_authkit_rejects_when_jwks_fetch_fails` asserts both halves: `is None` (closed) and that the call returned at all rather than raising (quiet). `cache_jwk_set=True` (300 s) keeps a transient outage from becoming an instant lockout.
- **T-02-08** (blocking JWKS fetch stalls the event loop) — both `PyJWKClient` calls go through `anyio.to_thread.run_sync`; the count is asserted at exactly 2.
- **T-02-04** (token or claims in logs) — zero logging statements in the module; the exception is swallowed rather than re-raised, so no traceback can carry the token upward.
- **Algorithm confusion** — `algorithms=["RS256"]` explicitly. `test_authkit_rejects_alg_none_token` uses a hand-built unsigned token (PyJWT will not mint one) with the key fetch stubbed to *succeed*, so the allowlist is the only thing left standing. `test_authkit_rejects_unknown_signing_key` covers the foreign-key case.
- **T-02-10** (WorkOS credentials) — none exist. The resource-server flow needs no client secret, and `MCP_ISSUER_URL`/`MCP_JWKS_URI` are public URLs that correctly stay out of `_SECRET_FIELDS`.
- **A7 (cost)** — unresolved, and deliberately so: Task 1 instructs a stop-and-report if CIMD, DCR or Resource Indicators turn out to be paid-gated. Nothing was upgraded.

**Credential handling during verification.** Confirming matrix row 3 needed the live `MCP_AUTH_SECRET`. It was read from Secret Manager into a temporary file outside the repository, loaded from that file by the requesting script rather than passed on a command line, and deleted immediately. It appears in no commit, no log file and no transcript. This is the pattern plan 02-05's summary recommended for future plans after the Neon DSN was pasted into a conversation.

**No threat flags.** No new network endpoint, auth path, file access pattern or schema change was introduced. The `authkit` code path is not reachable on the deployed service, which still runs `MCP_AUTH_MODE=static`.

## Known Stubs

| Stub | File | Line | Reason / resolver |
|---|---|---|---|
| `MCP_ISSUER_URL: "https://example.authkit.app"`, `MCP_JWKS_URI: ""` | `deploy/cloud-run.env.yaml` | 37-38 | Unchanged and intentional. `MCP_AUTH_MODE` is still `static`, so neither is read at runtime. **Resolved by plan 02-07**, which flips the mode and fills both from Task 1's discovery document. |

## User Setup Required

**YES — this plan is stopped on it.** See the checkpoint returned alongside this summary and the
`## WorkOS AuthKit — BLOCKED …` section of `02-DEPLOY-LOG.md`. In short: create a WorkOS project,
enable CIMD and DCR, register the Resource Indicator
`https://brett-792870654598.us-central1.run.app/mcp`, and report the AuthKit domain plus four fields
from `GET /.well-known/oauth-authorization-server`. No WorkOS client secret is needed or wanted.

## Next Phase Readiness

**Plan 02-07 is blocked on the same gate.** It cannot flip `MCP_AUTH_MODE` to `authkit` without a
real `MCP_ISSUER_URL` and `MCP_JWKS_URI`, and it cannot run a connector round-trip without an
authorization server for the RFC 9728 document to point at.

**What is ready the moment those two values arrive:** the verifier itself. No further code is needed
for the cutover — only the two environment values in `deploy/cloud-run.env.yaml`, the mode flip, and
a redeploy.

**Carried forward unchanged from plan 02-05:** `--min=1` is pre-authorised for 02-07 and must not be
re-asked; the measured cold start is 7.53 s against Claude's 10-second discovery budget.

## Self-Check: PASSED

- **Files claimed modified verified present and changed:** `backend/app/mcp/auth.py`, `backend/tests/test_mcp_auth.py` and `02-DEPLOY-LOG.md` all appear in `git show --stat` for their respective commits.
- **All three claimed commits verified in `git log`:** `ab2c263`, `ca223c1`, `9da7f3e`.
- **Test counts verified by running, not asserted:** `23 passed` for the module, `99 passed` for the full suite.
- **Every acceptance-criteria grep was executed and its literal output recorded** in the table above, rather than being assumed from the code.
- **The RED phase was genuinely red:** collection failed with `ImportError: cannot import name 'AuthKitJWTVerifier'` before the implementation commit. No test was written against already-working code.
- **One assertion was mutation-tested rather than trusted** (Deviation #2), and the mutation reverted with `git diff HEAD` confirmed empty afterwards.
- **The deployed service was probed live**, not assumed unchanged.
- **No WorkOS value is claimed anywhere.** The four discovery fields are recorded as outstanding in both this summary and the deploy log, and the phrase Task 3's grep looks for is absent from the repository.

**Not modified, by design (worktree mode):** `.planning/STATE.md` and `.planning/ROADMAP.md` — the orchestrator owns those writes.

---
*Phase: 02-deploy-connector-auth-spike*
*Status: PARTIAL — blocked at the Task 1 `checkpoint:human-action` gate*
*Date: 2026-08-28*
