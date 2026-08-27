---
phase: 02-deploy-connector-auth-spike
plan: 02
subsystem: mcp
tags: [mcp, mcp-sdk-v2, auth, bearer-token, asgi, lifespan, tdd, pytest]

# Dependency graph
requires:
  - phase: 02-deploy-connector-auth-spike
    plan: 01
    provides: "mcp==2.0.0 pin, the five MCP_* Settings fields, and the session-scoped _default_mcp_env fixture that seeds them before any app import"
  - phase: 01-backend-foundation
    provides: "app.state.sessionmaker assigned by the FastAPI lifespan, the degrade-not-500 convention in health.py, and the three-layer secret doctrine"
provides:
  - "app.mcp.server exposing `mcp` (MCPServer) and `mcp_app` (Starlette sub-app) — the two names plan 02-04 imports"
  - "mcp_app owns ['/mcp', '/.well-known/oauth-protected-resource/mcp'] at its OWN root, so 02-04 must mount at '/' not '/mcp'"
  - "mcp.session_manager reachable at import, which 02-04's lifespan must enter via session_manager.run()"
  - "StaticTokenVerifier: constant-time, byte-comparing, zero-logging bearer verifier"
  - "build_token_verifier(settings) selector that fails fast and refuses to degrade authkit -> static"
  - "AppContext + mcp_lifespan borrowing app.state.sessionmaker, never creating an engine"
  - "fitness_ping tool (D-08) with an empty model-facing inputSchema and a real SELECT 1"
affects: [02-04, 02-05, 02-06, 02-07, phase-06-mcp-server]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Bearer secrets compared as UTF-8 bytes, never as str, so non-ASCII input cannot raise out of the verifier"
    - "Deferred `from app.main import app` inside a lifespan body to break an import cycle without a holder module"
    - "Container-free MCP tests: lazy import in a fixture + a never-connected sessionmaker on app.state"
    - "Documented `type: ignore[arg-type]` where passing `str` is semantically required by a library's ConfigDict"

key-files:
  created:
    - backend/app/mcp/__init__.py
    - backend/app/mcp/context.py
    - backend/app/mcp/auth.py
    - backend/app/mcp/server.py
    - backend/app/mcp/tools/__init__.py
    - backend/app/mcp/tools/ping.py
    - backend/tests/test_mcp_auth.py
    - backend/tests/test_mcp_mount.py
  modified: []

key-decisions:
  - "StaticTokenVerifier compares UTF-8 bytes, not str: secrets.compare_digest raises TypeError on non-ASCII str and Starlette catches only AuthenticationError, so a str compare turned one attacker-supplied header byte into a 500 instead of a 401"
  - "issuer_url/resource_server_url are passed as `str` with a documented `type: ignore[arg-type]`, because AuthSettings sets url_preserve_empty_path=True and coercing via AnyHttpUrl() would append a trailing slash that breaks RFC 8414 exact-string issuer comparison"
  - "Both in-memory mcp.Client tests run WITHOUT the integration marker — every assertion is static structure, so a fixture wires a never-connected sessionmaker instead of a Postgres container"

requirements-completed: []  # contributes to MCP-01, MCP-04 — neither is satisfied by this plan; see "Requirements Status"
requirements-contributed: [MCP-01, MCP-04]

# Metrics
duration: 14min
completed: 2026-08-27
---

# Phase 2 Plan 02: MCP Server Package Summary

**The permanent MCP plumbing every Phase 6 tool will inherit — lifespan context, a constant-time byte-comparing bearer verifier, and the `MCPServer` + `streamable_http_app()` wiring — proven by 12 tests that need no Postgres container.**

## Performance

- **Duration:** 14 min
- **Started:** 2026-08-27T03:06:24Z
- **Completed:** 2026-08-27T03:20:03Z
- **Tasks:** 3 (2 under TDD gates)
- **Files created:** 8

## Accomplishments

- `app.mcp.server` imports cleanly with no network access and exposes exactly the two names plan 02-04 needs: `mcp` and `mcp_app`.
- The route inventory is now an **asserted exact list**, not a hope. This is the one Phase 2 failure that is otherwise invisible until a real connector fails (Pitfall 3 never fires during static-bearer testing, because a valid header means no 401 and therefore no discovery).
- `fitness_ping` was verified end-to-end by hand against both a live Postgres container and a closed port: `{"status": "ok", "database": "connected"}` and `{"status": "ok", "database": "error"}` respectively, both with `is_error: false` and neither leaking a DSN, host, driver name, or traceback into the tool payload (T-02-09).
- Found and closed a real 500-instead-of-401 hole in the verifier as specified — see Deviations #1. It was reachable with a single arbitrary byte in the `Authorization` header.
- `pytest -m "not integration"` went 45 → **49 passed** and the full suite is **63 passed**. `ruff check backend/` and `mypy backend/app` (20 files) are both clean.

## Task Commits

1. **Task 1: mcp package, AppContext, mcp_lifespan, fitness_ping** — `b33731f` (feat)
2. **Task 2: Stage A static bearer verifier** (TDD) — `84b04af` (test, RED) → `f1c64a2` (feat, GREEN)
3. **Task 3: MCPServer and ASGI sub-app** (TDD) — `24d2131` (test, RED) → `ed5d6bf` (feat, GREEN)

_No REFACTOR commits: neither GREEN implementation needed cleanup._

## Required Output Facts

The plan's `<output>` block asks for three specific facts:

**1. Exact `mcp_app.routes` output:**

```
['/mcp', '/.well-known/oauth-protected-resource/mcp']
```

Both at the sub-app's **own root**. Plan 02-04 must therefore call `app.mount("/", mcp_app)`. Mounting at `/mcp` would relocate the metadata document to `/mcp/.well-known/oauth-protected-resource/mcp`, which Claude never probes.

**2. Did `test_exactly_one_tool_registered` need the `integration` marker?**

**No — and neither did `test_ping_tool_hides_ctx_from_the_model`.** Both in-memory `mcp.Client` tests run container-free, so all four tests in `test_mcp_mount.py` are unit tests.

The plan anticipated the marker because entering `Client(mcp)` runs `mcp_lifespan`, which reads `app.state.sessionmaker` — an attribute that does not exist until the FastAPI lifespan has run. Rather than pull in a Postgres container for that, the `mcp_server` fixture assigns a real `async_sessionmaker` over an engine that is **never connected to**. SQLAlchemy defers connection until first use and `tools/list` issues no query, so the assertions (route paths, tool registration, JSON schema shape) are all pure static structure. Requiring a container to assert "the tool list has one entry" would have been a bad trade against keeping `-m "not integration"` fast.

**3. Exported names plan 02-04 must import:**

```python
from app.mcp.server import mcp, mcp_app
```

- `mcp_app` → `app.mount("/", mcp_app)`
- `mcp` → `await stack.enter_async_context(mcp.session_manager.run())` inside the FastAPI lifespan, **after** `app.state.sessionmaker` is assigned and **inside** the existing `try:` so `finally: await engine.dispose()` still runs.

## Files Created

- `backend/app/mcp/__init__.py`, `backend/app/mcp/tools/__init__.py` — one-line package docstrings, matching `app/api/__init__.py`.
- `backend/app/mcp/context.py` — `AppContext` (`@dataclass(slots=True)`, the repo's first dataclass) and `mcp_lifespan`. Borrows `app.state.sessionmaker`; the `from app.main import app` is inside the function body to break the cycle.
- `backend/app/mcp/tools/ping.py` — `PingResult` + `fitness_ping`. Degrades to `database="error"` without raising; detail goes to the log only.
- `backend/app/mcp/auth.py` — `StaticTokenVerifier` + `build_token_verifier`. **Zero logging calls in the entire module** (T-02-04).
- `backend/app/mcp/server.py` — `mcp`, `mcp_app`, `AuthSettings`, `TransportSecuritySettings`. No `custom_route`, no `CORSMiddleware`.
- `backend/tests/test_mcp_auth.py` — 8 unit tests, no integration marker.
- `backend/tests/test_mcp_mount.py` — 4 unit tests, no integration marker.

## Decisions Made

**1. The bearer secret is compared as UTF-8 bytes, not as `str`.** See Deviations #1 — this was a security fix, not a style preference.

**2. `issuer_url` and `resource_server_url` are passed as `str`, with a documented `type: ignore[arg-type]`.**

mypy flagged both (the fields are annotated `AnyHttpUrl`). The obvious fix — wrapping in `AnyHttpUrl(...)` — is **wrong**, and the SDK source says so in a comment on `AuthSettings`:

> Preserve empty URL paths so a path-less issuer/resource passed as a string keeps its canonical form (no trailing slash). RFC 8414/9207 issuer comparison is exact string comparison, so a spurious trailing slash would break it.

Verified empirically:

| Input | `AnyHttpUrl(...)` | `AuthSettings(issuer_url=...)` |
|---|---|---|
| `https://example.authkit.app` | `https://example.authkit.app/` | `https://example.authkit.app` |
| `http://localhost:8000/mcp` | `http://localhost:8000/mcp` | `http://localhost:8000/mcp` |

`AuthSettings` sets `model_config = ConfigDict(url_preserve_empty_path=True)`, which only applies to values it validates itself. Pre-coercing bypasses it and would have appended a trailing slash to the issuer — silently breaking discovery against the real WorkOS tenant in plan 02-06, in a way no local test would catch. Passing `str` is the correct call; the ignore is the price. (`warn_unused_ignores = true` is on, so both ignores are load-bearing.)

**3. Both `mcp.Client` tests are container-free.** See Required Output Facts #2.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing security control] `StaticTokenVerifier` as specified turned an attacker-supplied header byte into a 500**

- **Found during:** Task 2 (before writing the RED tests)
- **Issue:** The plan's implementation was `secrets.compare_digest(token, self._secret)` on two `str`s. `secrets.compare_digest` **raises `TypeError: comparing strings with non-ASCII characters is not supported`** when either `str` argument is non-ASCII (verified live). ASGI servers latin-1 decode header bytes, so any byte in `0x80–0xFF` inside `Authorization: Bearer …` produces a non-ASCII `str`. Tracing the call path: `BearerAuthBackend.authenticate` awaits `verify_token` with **no** try/except (read from the installed `mcp/server/auth/middleware/bearer_auth.py`), and Starlette's `AuthenticationMiddleware.__call__` catches **only** `AuthenticationError` (read from the installed source). The `TypeError` therefore escapes to the ASGI error handler as a **500 with a traceback** instead of a silent 401 — directly contradicting the fail-CLOSED-and-silent contract the module's own docstring states (T-02-04). Reachable by an unauthenticated attacker with one byte.
- **Fix:** Compare UTF-8 **bytes**. The secret is encoded once in `__init__`; the token is encoded per call. `str.encode("utf-8")` is total and never raises, and `compare_digest`'s bytes overload has no ASCII restriction and remains constant-time. A comment on the line explains why, so nobody "simplifies" it back.
- **Files modified:** `backend/app/mcp/auth.py`
- **Verification:** `verify_token("é")` now returns `None`. Asserted inside `test_static_verifier_rejects_wrong_token` with a message naming T-02-04.
- **Committed in:** `84b04af` (RED, assertion) → `f1c64a2` (GREEN, fix)
- **Note on test count:** the assertion was folded into the existing rejection test rather than added as a 9th, so the plan's `grep -c 'def test_' == 8` acceptance criterion still holds exactly. All eight specified test names are unchanged.

**2. [Rule 3 - Blocking] mypy rejected `str` for `AuthSettings`'s `AnyHttpUrl` fields**

- **Found during:** Task 3 (the task's own `uv run mypy backend/app/mcp` verification gate)
- **Issue:** `error: Argument "issuer_url" to "AuthSettings" has incompatible type "str"; expected "AnyHttpUrl"` (and the same for `resource_server_url`). The plan's code as written could not pass its own verification command.
- **Fix:** Two `# type: ignore[arg-type]` comments plus a block comment explaining that `str` is deliberate. Investigated the tempting fix first and rejected it — see Decisions #2.
- **Files modified:** `backend/app/mcp/server.py`
- **Verification:** `uv run mypy backend/app` clean across 20 files; runtime coercion unchanged (`str(s.issuer_url) == "https://example.authkit.app"`, no trailing slash).
- **Committed in:** `ed5d6bf`

### Acceptance-Criterion Conflicts (no code change)

**3. Task 1's `grep -q 'make_engine' … returns NO match` is unsatisfiable against the plan's own specified docstring**

The plan's `<action>` block dictates a `context.py` docstring containing *"must never call `make_engine()`"*, and `02-PATTERNS.md` independently **requires** that sentence ("State this in the docstring the same way the analogs do"). A literal `grep` for `make_engine` therefore matches the very text the plan mandates.

The criterion's *intent* is the borrow invariant, so that is what was verified — with a stronger check than the grep. Parsing `context.py` with `ast`, stripping all docstrings and re-rendering the executable code:

- occurrences of `make_engine` in executable code: **0**
- calls to `make_engine`: **0**
- imports from `app.db.session`: **none**

The invariant holds; only the mechanical grep was defective. No code or docstring was changed.

---

**Total deviations:** 2 auto-fixed (1 missing security control, 1 blocking type error), 1 acceptance-criterion conflict resolved by verifying intent.
**Impact on plan:** No scope change. Deviation #1 closed an unauthenticated 500; #2 was required to pass the plan's own gate. All specified test names, counts, and file lists are exactly as planned.

## Issues Encountered

- **Transient testcontainers failure under parallel execution.** The first full `uv run pytest -q` produced `14 errors` with `docker.errors.APIError` on every container-backed test. Re-running immediately gave `63 passed`. The sibling worktree agent (plan 02-03) was executing concurrently; this is Docker API contention, not a code defect. Running `test_health.py` alone passed throughout.
- **The log value scrubber garbles the word `testcontainers` in test output** (`***REDACTED***containers`). Harmless and **pre-existing**: `conftest._PLACEHOLDER_DB_URL` uses password `test`, so `secret_values()` adds the 4-character string `test` to the scrubber and it matches inside unrelated words. Cosmetic log noise only — `test_secret_redaction.py` uses a distinctive seeded secret precisely so its assertions do not depend on this. Out of scope for this plan; flagged rather than fixed. A longer placeholder password would resolve it.

## TDD Gate Compliance

Both TDD-marked tasks have an intact gate sequence in git history:

| Task | RED | GREEN | REFACTOR |
|------|-----|-------|----------|
| 2 — verifier | `84b04af` — verified failing (`ModuleNotFoundError: app.mcp.auth`) | `f1c64a2` — `8 passed` | none needed |
| 3 — server | `24d2131` — verified failing (4 errors, `cannot import name 'server'`) | `ed5d6bf` — `4 passed` | none needed |

No test passed unexpectedly during either RED phase, so the fail-fast rule was not triggered.

## Known Stubs

**None.** `fitness_ping` is explicitly *throwaway in scope, permanent in shape* (D-08) — Phase 6 replaces the tool, not the lifespan/auth/transport path it proves — but it is not a stub: it performs a real `SELECT 1` through the production session factory and its degrade path was verified against a closed port. `build_token_verifier`'s `authkit` branch raises rather than returning a placeholder, which is the opposite of a stub: it makes the unimplemented path impossible to use by accident.

## Security Notes

All six `mitigate` dispositions in the plan's threat register are implemented:

- **T-02-01** (Spoofing / DNS rebinding) — `TransportSecuritySettings(allowed_hosts=settings.mcp_allowed_hosts, allowed_origins=[])` passed explicitly at `streamable_http_app()`. `enable_dns_rebinding_protection` is never set to `False`.
- **T-02-05** (Spoofing / timing) — `secrets.compare_digest` only; enforced by `test_static_verifier_uses_constant_time_comparison`, which reads the function source and asserts no `==` against the token.
- **T-02-04** (Info disclosure / verifier) — `grep -c 'log\.' backend/app/mcp/auth.py` returns **0**. Rejection returns `None` with no exception detail. **Strengthened beyond the plan:** the verifier can no longer raise at all on hostile input (Deviations #1), and `test_build_token_verifier_requires_secret` asserts the startup error carries no `SecretStr`/`get_secret_value`/`''` fragment.
- **T-02-06** (EoP / custom routes) — no `@mcp.custom_route` anywhere; `/health` stays a FastAPI route.
- **T-02-09** (Info disclosure / ping) — verified live against a closed port: payload was `{"status": "ok", "database": "error"}` and contained none of `nobody`, `nopass`, `127.0.0.1`, `asyncpg`, `nodb`, `Traceback`.
- **T-02-02** (EoP / token replay) — `AuthSettings.resource_server_url` binds the Resource Indicator; `aud` enforcement lands with the JWKS verifier in 02-06 as planned.

**T-02-08** (DoS / blocking call in `verify_token`) remains **accepted** as planned: Stage A performs no network I/O.

## Threat Flags

None. This plan adds no network endpoint that is reachable yet (nothing is mounted until 02-04), no schema change, and no new file-access pattern. The auth path it introduces is the one the plan's threat model already covers.

## Carry-Forward for Plan 02-04 (important)

**`backend/tests/test_secret_redaction.py` will break at collection the moment `app/main.py` imports `app.mcp.server`.**

That module seeds `ENVIRONMENT`, `DATABASE_URL` and `HEVY_API_KEY` into `os.environ` at **module scope**, calls `get_settings.cache_clear()`, then does `from app.main import app  # noqa: E402`. It does **not** seed `MCP_AUTH_SECRET`. Module-scope code runs during pytest's **collection** phase, which is *before* any session-scoped autouse fixture — so `conftest._default_mcp_env` has not run yet.

Confirmed by direct reproduction:

```
IMPORT FAILS AS DESIGNED -> RuntimeError: MCP_AUTH_SECRET is required to start the MCP server
```

This is `build_token_verifier` failing fast exactly as designed; the bug would be in the test module's seeding, not in the verifier. **Fix in 02-04:** add `MCP_AUTH_SECRET` (and, for safety, `MCP_ALLOWED_HOSTS` including `testserver`) to that module-scope seeding block, next to the existing `os.environ` assignments.

Also carried forward:

- Mount at `/`, never `/mcp` (route list above).
- `mcp.session_manager.run()` must be entered in the FastAPI lifespan after `app.state.sessionmaker` is assigned and inside the existing `try:`.
- `test_mcp_auth.py` and `test_mcp_mount.py` currently contain **only** unit tests. Plan 02-04 appends the HTTP halves (401/200 wire contract, mount shadowing); those will need `@pytest.mark.integration` and the `client` fixture.

## Requirements Status

`REQUIREMENTS.md` was **deliberately left unmodified**, consistent with plan 02-01 and with the parallel-execution constraint that worktree agents must not write shared artifacts.

| ID | Requirement | Why not satisfied here |
|----|-------------|------------------------|
| MCP-01 | Remote MCP server deployed and reachable over HTTPS | Nothing is deployed, and nothing is even mounted into FastAPI until 02-04 |
| MCP-04 | Auth verified end-to-end **from an actual Claude client (not just a local test client)** | The requirement text explicitly excludes local verification; this plan proves the verifier's decision function, not a Claude round-trip |

**Action for the orchestrator:** leave both unchecked until the phase's plans are merged and the verifier confirms the deployed endpoint.

## Self-Check: PASSED

- **Files verified present:** all 8 created files plus this SUMMARY — 9/9 found.
- **Commits verified in git history:** `b33731f`, `84b04af`, `f1c64a2`, `24d2131`, `ed5d6bf` — 5/5 found.
- **Plan verification block, all 5 items:**
  1. `uv run ruff check backend/` clean; `uv run mypy backend/app` clean (20 source files).
  2. `uv run pytest -q` → **63 passed** (Docker up).
  3. Route inventory prints exactly `['/mcp', '/.well-known/oauth-protected-resource/mcp']`.
  4. `grep -rn 'from mcp.server.fastmcp' backend/` → no matches.
  5. `git status --short` empty; `git diff --name-only` lists exactly the 8 declared files and nothing else.

---
*Phase: 02-deploy-connector-auth-spike*
*Completed: 2026-08-27*
