---
phase: 02-deploy-connector-auth-spike
reviewed: 2026-08-29T04:02:58Z
depth: standard
files_reviewed: 26
files_reviewed_list:
  - .env.example
  - .gcloudignore
  - .gitignore
  - CLAUDE.md
  - Procfile
  - README.md
  - backend/app/config.py
  - backend/app/main.py
  - backend/app/mcp/__init__.py
  - backend/app/mcp/auth.py
  - backend/app/mcp/context.py
  - backend/app/mcp/server.py
  - backend/app/mcp/tools/__init__.py
  - backend/app/mcp/tools/ping.py
  - backend/migrations/README
  - backend/migrations/versions/0001_initial_schema.py
  - backend/tests/conftest.py
  - backend/tests/test_cloud_run_deploy.py
  - backend/tests/test_config.py
  - backend/tests/test_mcp_auth.py
  - backend/tests/test_mcp_mount.py
  - backend/tests/test_mcp_tools.py
  - backend/tests/test_secret_redaction.py
  - backend/tests/test_time.py
  - deploy/cloud-run.env.yaml
  - pyproject.toml
  - scripts/deploy-cloud-run.sh
findings:
  critical: 0
  warning: 0
  info: 1
  total: 1
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-08-29T04:02:58Z
**Depth:** standard
**Files Reviewed:** 26
**Status:** issues_found (info-only)

## Summary

This phase (deploy + connector auth spike) was reviewed with particular attention to secret
handling, the auth verifier's constant-time comparison and JWT validation, `TransportSecuritySettings`
host allowlisting, and the deploy script's Secret Manager vs. plain env var handling.

The implementation is unusually rigorous for a spike: every risk called out in the review brief is
independently addressed and covered by a specific, named test.

- **Secret handling**: `Settings` stores every credential as `SecretStr`, `hide_input_in_errors=True`
  prevents `DATABASE_URL`/password echo in `ValidationError`, and `secret_values()` feeds a
  three-layer log-redaction pipeline (verified end-to-end by `test_secret_redaction.py`, including
  third-party stdlib loggers and rendered tracebacks). `deploy/cloud-run.env.yaml` contains no
  credential-shaped keys, and `test_cloud_run_deploy.py` enforces this with a name-pattern guard
  (`test_no_credential_shaped_key_is_present`) plus a partition check that `DATABASE_URL` and
  `MCP_AUTH_SECRET` are bound only via `--set-secrets` Secret Manager references, never literals
  (`test_every_secret_binding_is_a_secret_manager_reference`,
  `test_env_file_and_secret_bindings_partition_the_environment`).
- **Constant-time comparison**: `StaticTokenVerifier.verify_token` uses `secrets.compare_digest` on
  `bytes` (not `str`), which correctly sidesteps the `TypeError` that `str`-mode `compare_digest`
  raises on non-ASCII input — verified by `test_static_verifier_rejects_wrong_token`'s `"é"` case and
  a source-inspection test (`test_static_verifier_uses_constant_time_comparison`) that fails the
  build if a `==` comparison is reintroduced.
- **JWT validation**: `AuthKitJWTVerifier` pins `algorithms=["RS256"]` (no `none`/alg-confusion path,
  confirmed by `test_authkit_rejects_alg_none_token` against a hand-built unsigned token), enforces
  `issuer`/`audience` with `options={"require": ["exp", "iss", "aud"]}` (closing the
  omitted-claim-skips-check gap PyJWT has without `require`), and fails closed — not open, and not
  loudly — on a JWKS fetch failure (`test_authkit_rejects_when_jwks_fetch_fails`). The blocking
  `PyJWKClient` key fetch is correctly pushed to a worker thread via `anyio.to_thread.run_sync` so it
  cannot stall the event loop.
- **Host allowlisting**: `TransportSecuritySettings(allowed_hosts=settings.mcp_allowed_hosts,
  allowed_origins=[])` is live (verified against the installed SDK source at
  `mcp/server/transport_security.py`), and `Settings.mcp_allowed_hosts` strips whitespace and drops
  empty entries from a comma-split so a stray `"a,,b"` cannot silently widen the allowlist.
  `test_rejects_disallowed_host` confirms a foreign `Host` header gets `421`, not a silently-disabled
  guard.
- **Deploy script**: `scripts/deploy-cloud-run.sh` uses `--env-vars-file` (a full-replace, not
  `--set-env-vars`, which the tests confirm is absent) for non-secret config and `--set-secrets` for
  `DATABASE_URL`/`MCP_AUTH_SECRET`, with `test_cloud_run_deploy.py` cross-checking that the two sets
  never overlap and that every required `Settings` field has a source. Variables are properly quoted
  throughout (`"$PROJECT_ID"`, `"$REPO_ROOT"`), and none are passed through `eval` or a subshell that
  would allow injection via a maliciously-crafted environment value.

I additionally verified independently (not just by reading the code) that:
- `MCP_ALLOWED_HOSTS`'s documented `:*` port-wildcard behavior in `.env.example` matches the actual
  `TransportSecurityMiddleware._validate_host` implementation in the installed `mcp==2.0.0` package.
- `AuthSettings`'s `url_preserve_empty_path=True` claim in `server.py`'s comment matches the installed
  `mcp/server/auth/settings.py`.
- `PyJWKClient`'s default cache lifespan is genuinely 300s, matching the `auth.py` docstring.
- `.gcloudignore` does not exclude `backend/`, `pyproject.toml`, `uv.lock`, `.python-version`, or
  `Procfile`, as the file's own header comment claims.
- The full non-integration test suite (72 tests), `ruff check`, and `mypy backend/app` all pass
  cleanly with no modifications.

No critical or warning-level issues were found. One minor configuration-drift observation is
recorded below.

## Info

### IN-01: `testcontainers.*` mypy override is dead configuration for the checked command

**File:** `pyproject.toml:79-81`
**Issue:** `[[tool.mypy.overrides]]` sets `ignore_missing_imports = true` for
`module = ["testcontainers.*", "asgi_correlation_id.*"]`. `asgi_correlation_id` is imported by
`backend/app/main.py`, so that half is live. `testcontainers` is imported only in
`backend/tests/conftest.py`, and both `README.md`'s documented command and this review's own run use
`uv run mypy backend/app` — a target that never imports `testcontainers`. Running that exact command
confirms it: mypy emits `note: unused section(s): module = ['testcontainers.*']`. This is harmless
today (a note, not an error) but is exactly the kind of drift that silently stops mattering the
moment `backend/tests` is added to the mypy target, at which point an unrelated third override would
be needed anyway if this one had bit-rotted unnoticed.
**Fix:** Either scope the override comment to acknowledge it's currently unused for `mypy backend/app`
and reserved for a future `mypy backend/tests` run, or split it into two override blocks and gate the
`testcontainers` one behind whatever config eventually type-checks the test suite:
```toml
[[tool.mypy.overrides]]
module = ["asgi_correlation_id.*"]
ignore_missing_imports = true

# Only exercised once backend/tests is added to a mypy target.
[[tool.mypy.overrides]]
module = ["testcontainers.*"]
ignore_missing_imports = true
```

---

_Reviewed: 2026-08-29T04:02:58Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
