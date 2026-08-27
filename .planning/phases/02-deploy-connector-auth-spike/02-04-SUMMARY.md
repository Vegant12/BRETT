---
phase: 02-deploy-connector-auth-spike
plan: 04
subsystem: mcp
tags: [mcp, mcp-sdk-v2, asgi, mount, lifespan, auth, rfc9728, tdd, pytest]

# Dependency graph
requires:
  - phase: 02-deploy-connector-auth-spike
    plan: 02
    provides: "app.mcp.server exposing `mcp` and `mcp_app`, the StaticTokenVerifier, and mcp_lifespan"
  - phase: 02-deploy-connector-auth-spike
    plan: 01
    provides: "the five MCP_* Settings fields and the conftest env seeding this plan relocated to module scope"
  - phase: 01-backend-foundation
    provides: "the FastAPI lifespan, app.state.sessionmaker, /health, and the degrade-not-500 convention"
provides:
  - "A FastAPI app that actually serves POST /mcp and GET /.well-known/oauth-protected-resource/mcp"
  - "The verified 401 body, WWW-Authenticate challenge, and RFC 9728 metadata document that plan 02-05 asserts against the deployed URL"
  - "conftest env seeding at MODULE scope, so any test module may import app.main at collection time"
  - "conftest reset of the SDK's one-shot session-manager flag, without which any second client-using test errors"
  - "Empirical confirmation that mcp_lifespan caches app.state.sessionmaker once per client context entry"
affects: [02-05, 02-06, 02-07, phase-06-mcp-server]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Catch-all `app.mount('/', ...)` registered last; any route added after import must re-append the mount or be shadowed"
    - "`contextlib.AsyncExitStack` in the parent lifespan to enter a mounted sub-app's dropped lifespan"
    - "Test env seeded at conftest MODULE scope, because session fixtures run after collection"
    - "Negative-control verification: sabotage the verifier, confirm the test fails, revert"

key-files:
  created:
    - backend/tests/test_mcp_tools.py
  modified:
    - backend/app/main.py
    - backend/tests/test_mcp_mount.py
    - backend/tests/test_mcp_auth.py
    - backend/tests/conftest.py
    - backend/tests/test_secret_redaction.py
    - .env.example

key-decisions:
  - "The SDK's one-shot `session_manager.run()` guard is reset in the TEST fixture, never tolerated in app/main.py: inside one process a repeat run() really is a bug and should keep crashing"
  - "MCP env moved from a session-scoped fixture to conftest module scope, because collection (which imports app.main via test_secret_redaction) finishes before any fixture runs"
  - "MCP_ALLOWED_HOSTS host matching is exact plus a trailing ':*' port wildcard -- local dev needs 'localhost:*', deployed needs the bare hostname"

requirements-completed: []  # contributes to MCP-01, MCP-04; neither is satisfied locally -- see "Requirements Status"
requirements-contributed: [MCP-01, MCP-04]

# Metrics
duration: 15min
completed: 2026-08-27
---

# Phase 2 Plan 04: Mount the MCP Sub-App Summary

**`POST /mcp` now answers on the real app — 401 with a `resource_metadata=` pointer without a credential, 200 with the tool list with one — while `/health`, `/docs` and `/openapi.json` survive the catch-all mount, proven by 26 tests and a real-uvicorn smoke that round-tripped `fitness_ping` against a live Postgres.**

## Performance

- **Duration:** 15 min
- **Started:** 2026-08-27T03:25:48Z
- **Completed:** 2026-08-27T03:40:29Z
- **Tasks:** 3 (all TDD-marked)
- **Files created:** 1 · **modified:** 6

## Task Commits

| # | Task | Commit(s) |
|---|------|-----------|
| 1 | Mount + session manager, MCP-01 tests | `5e72f65` (test, RED) → `270ed6c` (feat, GREEN) |
| 2 | MCP-04 HTTP auth matrix | `9784abc` (test) |
| 3 | D-08 tool round-trip + degradation | `9481d05` (test) |
| — | Deviation #4 (local host allowlist) | `7b13108` (fix) |

## Required Output Facts

The plan's `<output>` block asks for the exact shapes plan 02-05 will re-assert against the deployed URL. All captured from a live run, not predicted.

### 1. The `401` response

Byte-identical for a **missing** and a **wrong** credential — asserted, not assumed:

```
HTTP/1.1 401 Unauthorized
content-type: application/json
content-length: 74
www-authenticate: Bearer error="invalid_token", error_description="Authentication required", resource_metadata="http://localhost:8000/.well-known/oauth-protected-resource/mcp"

{"error": "invalid_token", "error_description": "Authentication required"}
```

Exact JSON key set: `{"error", "error_description"}` — exactly as RESEARCH.md predicted. The `WWW-Authenticate` value carries three parameters in this order: `error`, `error_description`, `resource_metadata`.

### 2. The RFC 9728 metadata document

`GET /.well-known/oauth-protected-resource/mcp`, **no** auth header, `200 application/json`:

```json
{"resource":"http://localhost:8000/mcp","authorization_servers":["https://example.authkit.app"],"bearer_methods_supported":["header"]}
```

Three fields, not two. `bearer_methods_supported` was **not** predicted by RESEARCH.md — noted here because 02-05 should expect it. `resource` reproduces `MCP_RESOURCE_URL` character for character with **no trailing slash added**, which retroactively confirms plan 02-02's decision to pass `str` rather than coerce through `AnyHttpUrl` (that coercion would have appended a slash here).

### 3. The `200` response

`Content-Type: application/json` — **not** `text/event-stream`, despite `Accept` offering both and `json_response` being left at its `False` default. A single-response method returns plain JSON, so `response.json()` works directly and 02-05 needs no SSE parsing:

```json
{"jsonrpc":"2.0","id":1,"result":{"cacheScope":"private","resultType":"complete","tools":[{"name":"fitness_ping", ...}],"ttlMs":0,"_meta":{"io.modelcontextprotocol/serverInfo":{"name":"BRETT","version":"0.1.0"}}}}
```

Note `result.tools`, `result.cacheScope`, `result.ttlMs` and the `_meta.serverInfo` block — the result envelope has more fields than the pre-2026 shape.

### 4. Where the observed SDK differed from RESEARCH.md

| Prediction | Observed | Consequence |
|---|---|---|
| 401 key set `{error, error_description}` | Confirmed exactly | none |
| Metadata has `resource` + `authorization_servers` | Also `bearer_methods_supported` | 02-05 must not assert a 2-key set |
| — (not covered) | `session_manager.run()` is **one-shot per instance** | Deviation #1 |
| — (not covered) | Host matching is exact + `:*` wildcard only | Deviation #4 |
| `allowed_hosts=["localhost","127.0.0.1"]` works locally | 421 on a non-default port | Deviation #4 |

## Local Smoke (plan verification step 3)

Run against real uvicorn + real Postgres (`docker compose up -d db`), not TestClient:

| Check | Expected | Observed |
|---|---|---|
| `GET /health` | 200 | **200** `{"status":"ok","database":"connected"}` |
| `POST /mcp` no auth | 401 + `resource_metadata=` | **401**, pointer present |
| `GET /.well-known/oauth-protected-resource/mcp` | resource + authorization_servers | **200**, both present (+ `bearer_methods_supported`) |
| `POST /mcp` valid bearer | *(not in the plan's script)* | **200**, `tools[0].name == "fitness_ping"` |
| `tools/call fitness_ping` | *(not in the plan's script)* | **200**, `structuredContent: {"status":"ok","database":"connected"}` |

The last row is the one that matters most and the plan did not ask for it: it is the first time the **whole** path — HTTPS-shaped request → mount → auth → transport → tool dispatch → lifespan-wired sessionmaker → real Postgres → structured output — has run outside a test harness. Added deliberately, because every earlier proof of the tool used the in-memory client, which bypasses auth and transport entirely.

**The plan's smoke script as written cannot produce a 200 on an authenticated call** — see Deviation #4. It used `MCP_ALLOWED_HOSTS=localhost,127.0.0.1` and got `421 Invalid Host header`; `localhost:*,127.0.0.1:*` was required.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] The SDK's session manager is one-shot, so every client-using test after the first errored**

- **Found during:** Task 1 GREEN, immediately after the mount was wired.
- **Issue:** `StreamableHTTPSessionManager.run()` raises `RuntimeError: StreamableHTTPSessionManager .run() can only be called once per instance` on a second call, and the manager is built exactly once by `streamable_http_app()` at import. Production honours this for free (one process, one lifespan), but the function-scoped `client` fixture starts and stops the same in-process app once per test. The first test passed; the remaining four **errored in fixture setup**. This was not a defect in the plan's design — it is the correct production wiring meeting a test harness the SDK does not anticipate. It would also have broken all three pre-existing `test_health.py` tests.
- **Fix:** Reset the one-shot flag in the `client` fixture, with a comment recording that `run()`'s own `finally` already restores every other piece of manager state (`_task_group`, `_lifespan_state`, `_server_instances`, `_session_owners`), so this is a complete reset rather than a partial one. Explicitly rejected the alternative of making `app/main.py` tolerate a repeat `run()`: inside one process that really is a bug and should keep crashing.
- **Files modified:** `backend/tests/conftest.py` *(not in the declared `files_modified`)*
- **Commit:** `270ed6c`

**2. [Rule 3 - Blocking] The carry-forward fix had to go in conftest, not `test_secret_redaction.py`**

- **Found during:** Task 1 GREEN, full-suite run.
- **Issue:** As plan 02-02 warned, `test_secret_redaction.py` seeds env at module scope and then imports `app.main`, which now pulls in `app.mcp.server` — dying at **collection** with `RuntimeError: MCP_AUTH_SECRET is required to start the MCP server`. Reproduced exactly.
- **Why the suggested fix was insufficient:** the carry-forward note proposed adding a one-line `MCP_AUTH_SECRET` seed to that module. That would have unblocked collection and then failed *more quietly*. Module-scope code runs during collection, so **whichever module imports `app.main` first freezes the MCP server for the entire session** — verifier secret, Host allowlist and resource URL included. Seeding only the secret leaves `MCP_ALLOWED_HOSTS` at its `localhost,127.0.0.1` default, so `testserver` is absent and every MCP request in the suite returns `421` instead of the asserted status. Seeding all five there instead would duplicate conftest's literals with a live drift hazard — and if the two ever disagreed, `test_accepts_valid_bearer` would 401.
- **Fix:** Moved the seeding out of the session-scoped `_default_mcp_env` fixture and into conftest **module scope** (pytest imports a conftest before collecting the test modules beside it), using `setdefault` so a developer's real environment still wins. The fixture was reduced to teardown only. One source of truth, correct for both collection-time and fixture-time consumers, and `test_secret_redaction.py` needed no seeding change at all.
- **Files modified:** `backend/tests/conftest.py` *(not in the declared `files_modified`)*
- **Commit:** `270ed6c`

**3. [Rule 1 - Bug] The catch-all mount shadowed a route registered after import**

- **Found during:** Task 1 GREEN, full-suite run (4 failures in `test_secret_redaction.py`).
- **Issue:** `test_secret_redaction.py` registers `/__test_boom__` on the imported `app` at its own module scope — i.e. *after* `app/main.py` has already appended `app.mount("/", mcp_app)`. Starlette resolves routes in list order, so the catch-all won and the MCP sub-app answered `/__test_boom__` with its own **404**. The D-05 sanitized-error handler under test was never reached. This is the exact failure mode the plan's mount comment predicts ("Registered LAST because it is a catch-all") — that reasoning holds for routes registered *before* the mount, and this one is not.
- **Fix:** After registering the route, re-append the `Mount` so it returns to being the handler of last resort. Scoped to that test module with a comment noting nothing in production registers routes post-import — which is precisely why `app/main.py` can register the mount last and be done.
- **Files modified:** `backend/tests/test_secret_redaction.py` *(not in the declared `files_modified`)*
- **Commit:** `270ed6c`

**4. [Rule 2 - Missing critical config] `.env.example` handed local developers a value that silently half-works**

- **Found during:** the plan's own verification step 3 (local smoke).
- **Issue:** `MCP_ALLOWED_HOSTS=localhost,127.0.0.1` does **not** authorise a local server on port 8000. The SDK's `_validate_host` does an exact string match with one special form — a trailing `:*` wildcards the port (read from `mcp/server/transport_security.py`). curl sends `Host: localhost:8000`, which matches neither entry, so the authenticated call returned `421 Invalid Host header`. The failure is nasty because it is **partial**: the unauthenticated request still returns a perfectly normal-looking `401` (auth middleware runs before transport security) and the metadata document still returns `200`, so three of four smoke checks pass and the config looks fine.
- **Fix:** `.env.example` now shows `localhost:*,127.0.0.1:*` with a comment explaining the exact-vs-wildcard rule and why the deployed value differs.
- **Not a deploy bug:** `render.yaml`'s `brett.onrender.com` is **correct** and was left alone — Render serves on 443, which is omitted from the Host header, so the bare hostname matches exactly. Verified by reading the blueprint rather than assumed.
- **Files modified:** `.env.example` *(not in the declared `files_modified`)*
- **Commit:** `7b13108`

### Scope note

Four of the six modified files were outside the plan's declared `files_modified`. Every one was a consequence of this plan's own change (the mount and the `app.main` → `app.mcp.server` import edge) surfacing in a file the plan did not anticipate, and each is required for the plan's own verification command (`uv run pytest -q`) to pass. None is speculative or unrelated cleanup.

## Empirical Findings the Plan Asked For

**`mcp_lifespan` caches the sessionmaker once per client context entry — confirmed, not assumed.** The plan asked for this to be verified rather than trusted. Swapping `app.state.sessionmaker` *before* `async with Client(mcp)` yields `database: "error"`; swapping *after* entry yields `database: "connected"`, proving the factory is read exactly once when the context opens and held in `AppContext` for the client's lifetime. The test's swap-before-entry ordering is therefore load-bearing, and a future refactor that moves the swap inside the block would produce a green test that proves nothing. Recorded because Phase 6 tools inherit this lifetime.

**Negative control (required by Task 2's acceptance criteria).** `StaticTokenVerifier.verify_token` was temporarily patched to accept every token. Result: `test_rejects_bad_token` and `test_401_leaks_nothing` both **failed** (`assert 200 == 401`); `auth.py` was restored and `git diff` confirmed byte-identical to `HEAD` before committing. Worth recording: `test_rejects_unauthenticated` **still passed** under sabotage, because a request with no `Authorization` header at all is rejected by `RequireAuthMiddleware` before the verifier is consulted. The two rejection paths are genuinely different code, which is why both tests exist.

## Verification

| Gate | Result |
|---|---|
| `uv run pytest -q` (full suite, Docker up) | **84 passed** (was 75 at plan start) |
| `uv run pytest -q -m "not integration"` | 56 passed, 28 deselected |
| `uv run ruff check backend/` | clean |
| `uv run mypy backend/app` | clean, 20 source files |
| `test_mcp_mount.py` | **9** (4 unit from 02-02 + 5 integration) |
| `test_mcp_auth.py` | **13** (8 unit from 02-02 + 5 integration) |
| `test_mcp_tools.py` | **4** |
| `git status --short` | empty |
| Deletions introduced (`--diff-filter=D`) | none |

All acceptance criteria across the three tasks were checked mechanically (the greps and the `awk` ordering check) and passed, including `grep -q 'app.mount("/mcp"'` returning no match and the mount appearing after `include_router`.

## Known Stubs

**None.** `fitness_ping` remains throwaway-in-scope/permanent-in-shape (D-08), not a stub — it performs a real `SELECT 1` and its degrade path is driven by a real connection failure, both now proven over real HTTP as well as in-memory.

## Threat Flags

None. This plan adds no new endpoint beyond the two the sub-app already defined; it makes them reachable, which is what the phase's existing threat model already covers. All five `mitigate` dispositions assigned to this plan now have a behavioural test:

| Threat | Test |
|---|---|
| T-02-01 spoofing / DNS rebinding | `test_rejects_disallowed_host` (421) |
| T-02-06 unauthenticated bypass | `test_rejects_unauthenticated`, `test_rejects_bad_token`, `test_health_still_wins_after_mount` |
| T-02-04 401 body disclosure | `test_401_leaks_nothing` (exact key set + leak loop, incl. the presented token) |
| T-02-09 ping failure disclosure | `test_ping_degradation_leaks_nothing` (real failure, not mocked) |
| T-02-03 / T-02-02 discovery metadata | `test_protected_resource_metadata_path` (single-entry `authorization_servers`) |

## Requirements Status

`REQUIREMENTS.md`, `STATE.md` and `ROADMAP.md` were **deliberately left unmodified** — worktree agents must not write shared artifacts.

| ID | Why not satisfied here |
|----|------------------------|
| MCP-01 | "deployed and reachable over HTTPS" — this plan proves the contract on localhost only; the deploy is 02-05 |
| MCP-04 | The requirement text explicitly demands verification "from an actual Claude client (not just a local test client)" |

Both should stay unchecked until the deployed endpoint is verified.

## Self-Check: PASSED

- **Files verified present:** `backend/tests/test_mcp_tools.py` and this SUMMARY — found. All six modified files present and tracked.
- **Commits verified in git history:** `5e72f65`, `270ed6c`, `9784abc`, `9481d05`, `7b13108` — 5/5 found via `git log`.
- **Clean tree:** `git status --short` empty after the final commit; no deletions introduced anywhere in the plan's range.
- **Smoke environment torn down:** uvicorn stopped, `docker compose down -v` completed.

---
*Phase: 02-deploy-connector-auth-spike*
*Completed: 2026-08-27*
