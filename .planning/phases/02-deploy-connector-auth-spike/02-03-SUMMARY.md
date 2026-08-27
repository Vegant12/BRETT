---
phase: 02-deploy-connector-auth-spike
plan: 03
subsystem: infra
tags: [render, render-yaml, iac, deploy, pyyaml, pytest, pydantic-settings]

# Dependency graph
requires:
  - phase: 02-deploy-connector-auth-spike
    provides: "plan 02-01's five MCP_* Settings fields (incl. the mcp_allowed_hosts_raw / MCP_ALLOWED_HOSTS validation_alias) and the pyyaml==6.0.3 dev pin"
  - phase: 01-backend-foundation
    provides: "Settings with extra='ignore', the REPO_ROOT static-file test idiom, the /health route, docker-compose.yml comment discipline, gitleaks pre-commit hook"
provides:
  - "render.yaml at the repo root: one free-tier web service + one free Postgres, ready for plan 02-05 to sync"
  - "Zero-credential-literal guarantee: MCP_AUTH_SECRET via generateValue, DATABASE_URL via fromDatabase, MCP_ISSUER_URL/MCP_JWKS_URI via sync:false"
  - "backend/tests/test_render_blueprint.py: 7 unit tests binding envVars keys to Settings fields, both negative controls demonstrated"
  - "The assumed public hostname brett.onrender.com, written once into MCP_ALLOWED_HOSTS and MCP_RESOURCE_URL"
  - "A commented, labelled preDeployCommand that plan 02-07 uncomments in the same commit as plan: starter"
affects: [02-05, 02-07, phase-03-hevy-integration]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "IaC drift guard: a committed config file is bound to the code that reads it by a unit test, not by a comment"
    - "Secret policy expressed as a name-marker rule (*SECRET*/*KEY*/*TOKEN*/*PASSWORD*/DATABASE_URL) rather than an allowlist of known keys, so a future secret is caught by default"
    - "Env-var cross-check resolves names through Field.validation_alias, not by lowercasing the field name"

key-files:
  created:
    - render.yaml
    - backend/tests/test_render_blueprint.py
  modified: []

key-decisions:
  - "Comment wording in render.yaml avoids the literal strings `sync: false`, `generateValue: true` and `rootDir`, because the plan's own acceptance criteria are line-count greps that the plan's illustrative comment text would have broken"
  - "test_blueprint_parses also asserts fromDatabase.name resolves to a declared database block — a dangling reference fails Render's blueprint sync with an error naming neither file nor line"
  - "test_resource_url_and_allowed_hosts_agree additionally asserts https and an empty query string (MCP-01, T-02-03)"
  - "pyproject.toml deliberately untouched: the missing types-PyYAML stub is consistent with a 26-error pre-existing mypy baseline across backend/tests, and editing the lockfile would risk a conflict with the sibling worktree agent"

patterns-established:
  - "Static IaC test: parse the committed YAML, cross-check every key against the model that consumes it, f-string failure messages naming the violated requirement id"
  - "Negative control is executed and its failure message recorded in the SUMMARY, so 'the test passes' is distinguishable from 'the test cannot fail'"

requirements-completed: []  # contributes to DEPLOY-01; not satisfied until 02-05 deploys. See "Requirements Status"
requirements-contributed: [DEPLOY-01]

# Metrics
duration: 15min
completed: 2026-08-27
---

# Phase 2 Plan 03: Render Blueprint and Its Drift Guard Summary

**`render.yaml` declaring one free-tier web service plus one free Postgres with every credential supplied by Render, and seven unit tests that fail the fast suite the moment an `envVars` key stops matching a `Settings` field or a secret gains a literal value.**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-08-27T03:02:00Z
- **Completed:** 2026-08-27T03:17:00Z
- **Tasks:** 2
- **Files created:** 2 (no existing file modified)

## Accomplishments

- The blueprint ships **zero credential literals**. `MCP_AUTH_SECRET` is minted server-side by `generateValue`, so it never exists on a developer machine; `DATABASE_URL` comes from `fromDatabase`; the two WorkOS values are `sync: false` dashboard prompts. Gitleaks passes on the file.
- The `MCP_ALLOWED_HOSTS` → `mcp_allowed_hosts_raw` naming mismatch that plan 02-01 explicitly carried forward is **handled, not tripped over**: `_settings_env_names()` resolves through `Field.validation_alias`, so the one variable a `421` depends on does not report a false drift.
- Both negative controls were executed and observed to fail (messages below), so the drift check and the secret-literal check are demonstrated capable of firing rather than merely green.
- Fast suite went from 37 to **44 passing** (`pytest -m "not integration"`, 0 failures, 14 integration tests deselected). `ruff check` and `ruff format --check` clean; all six pre-commit hooks pass on both files.
- The free-tier migration gap (RESEARCH Pitfall 6) is documented **in the file that causes it**: `preDeployCommand` is present, commented, and carries the paid-only quote plus the instruction to uncomment it in the same commit that sets `plan: starter`.

## Task Commits

1. **Task 1: Author render.yaml at the repo root** — `dfb601f` (chore)
2. **Task 2: Static blueprint test binding render.yaml to Settings** — `aef019c` (test)

## Files Created

- **`render.yaml`** (repo root, 80 lines) — one `type: web` service (`plan: free`, `region: oregon`, `autoDeployTrigger: commit`, `healthCheckPath: /health`) and one database (`brett-db`, `plan: free`, `databaseName: brett`). `buildCommand: uv sync --frozen`; `startCommand: uv run uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port $PORT`. The service's root-directory setting is left unset so the repo-root `uv.lock` activates uv. Ten `envVars` entries. No `PYTHON_VERSION` — `.python-version` already pins `3.13`. No `HEVY_API_KEY` — Phase 3 owns it, and an unused `sync: false` var only creates a dashboard prompt with nothing to answer.
- **`backend/tests/test_render_blueprint.py`** (224 lines) — seven unit tests plus four private helpers. No container, no network, no integration marker.

## The Assumed Hostname — action required in plan 02-05

`brett.onrender.com` is an **assumption**, written into exactly two places in `render.yaml`:

| Line | Key | Value |
|------|-----|-------|
| 53-54 | `MCP_ALLOWED_HOSTS` | `brett.onrender.com` |
| 58-59 | `MCP_RESOURCE_URL` | `https://brett.onrender.com/mcp` |

Render assigns the real hostname at service-creation time and appends a random suffix when the name is taken (e.g. `brett-a1b2.onrender.com`). **Plan 02-05 Task 1 must reconcile both values with the hostname Render actually assigns.** The failure modes if it does not, in the order they will be hit:

1. `MCP_ALLOWED_HOSTS` wrong → every MCP request returns `421 Invalid Host header` with no MCP-level error body (T-02-01, RESEARCH Pitfall 2).
2. `MCP_RESOURCE_URL` wrong → OAuth completes and then every request 401s, because the `resource` field in the RFC 9728 metadata document must match the connector URL character for character (RESEARCH Pitfall 8).

`test_resource_url_and_allowed_hosts_agree` guarantees the two values stay consistent **with each other**, but it cannot know the real hostname — it will pass just as happily on a wrong-but-consistent pair. This is a genuine limitation of a static test and the reason 02-05 owns the reconciliation.

## Negative Controls (recorded per plan acceptance criteria)

Both controls were applied to `render.yaml`, observed, and reverted with `git checkout -- render.yaml`. Working tree confirmed clean afterwards.

**Control 1 — env-var drift.** Added `- key: BOGUS_VAR` / `value: x` to `envVars`. Result: `1 failed, 6 passed`.

```
FAILED backend/tests/test_render_blueprint.py::test_every_env_var_maps_to_a_settings_field
E  AssertionError: DEPLOY-01 violated: render.yaml sets BOGUS_VAR but Settings has no such field
   (extra='ignore' means the deployed service would silently ignore it)
E  assert 'BOGUS_VAR' in {'DATABASE_URL', 'ENVIRONMENT', 'HEVY_API_KEY', 'LOG_LEVEL',
   'MCP_ALLOWED_HOSTS', 'MCP_ALLOWED_HOSTS_RAW', ...}
```

**Control 2 — committed secret (not required by the plan; added because T-02-10 is the strongest security claim in the file).** Replaced `MCP_AUTH_SECRET: generateValue: true` with a literal `value:`. Result: `1 failed, 6 passed`.

```
FAILED backend/tests/test_render_blueprint.py::test_no_secret_is_committed_as_a_literal
E  AssertionError: T-02-10 violated: render.yaml commits a literal value for MCP_AUTH_SECRET;
   use generateValue, sync: false, or fromDatabase instead
E  assert 'value' not in {'key': 'MCP_AUTH_SECRET', 'value': 'negative-control-not-a-real-credential'}
```

Note the two controls were run **sequentially with a revert between them**, never simultaneously, so neither could mask the other.

## Decisions Made

**1. Comment wording diverges from the plan's literal YAML block to satisfy the plan's own acceptance criteria.** See Deviations — this is the only substantive deviation and it changes no blueprint semantics.

**2. `test_blueprint_parses` also checks that `fromDatabase.name` resolves to a declared database.** A dangling reference is not a YAML error and not a `Settings` drift; it fails Render's blueprint sync with a message that names neither file nor line. Two lines of set arithmetic in the test that already parses the file (Rule 2 — correctness requirement for the artifact this plan exists to produce).

**3. `test_resource_url_and_allowed_hosts_agree` asserts `https` and an empty query string** in addition to the plan's `/mcp` suffix and host-membership checks. The threat register's T-02-03 mitigation is stated as "the URL ends in `/mcp` with no query string" — the query-string half needed an explicit assertion. `https` is MCP-01's transport requirement.

**4. `pyproject.toml` was not touched.** `mypy backend/tests/test_render_blueprint.py` emits one error — a missing `types-PyYAML` stub for `import yaml`. This was left alone rather than fixed with a stub dependency or an inline `type: ignore`, for three reasons: `mypy backend/tests` already has a **26-error pre-existing baseline across 6 files** (the project's checked surface is `backend/app`, per plan 02-01); mypy is not in `.pre-commit-config.yaml`; and `pyproject.toml`/`uv.lock` are outside this plan's `files_modified` and are exactly the files a parallel worktree agent would collide on. Logged here rather than in `deferred-items.md` because it is a whole-suite baseline question, not an item this plan created.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] The plan's literal `render.yaml` content contradicted three of its own acceptance criteria**

- **Found during:** Task 1 (authoring `render.yaml`)
- **Issue:** The plan instructs "create `render.yaml` with **exactly this content**, comments included", but three of that content's explanatory comments contain the very strings the acceptance criteria require to be absent or uniquely counted. Written verbatim, the file fails its own checks:

  | Acceptance criterion | Verbatim result | Cause |
  |---|---|---|
  | `grep -q 'rootDir'` returns NO match | **1 match** | Header comment: "``rootDir`` is deliberately UNSET" |
  | `grep -c 'sync: false'` returns `2` | **3** | Comment: "``sync: false`` means \"prompt for this value…\"" |
  | `grep -c 'generateValue: true'` returns `1` | **2** | Comment: "``generateValue: true`` makes Render mint…" |

  The criteria encode the real invariants (root dir unset; exactly two dashboard-prompted vars; exactly one server-minted secret); the comment text is illustrative. A verifier re-running these greps literally would report three false failures on a correct blueprint.
- **Fix:** Reworded three comments to express the same fact without the colliding literal — "The service's root-directory setting is deliberately left unset", "A `sync` flag of false means…", "`generateValue` makes Render mint…". **No YAML key, value, or structure changed.** All three criteria now hold: `rootDir` 0 matches, `sync: false` 2, `generateValue: true` 1.
- **Files modified:** `render.yaml`
- **Verification:** Every one of Task 1's eleven acceptance criteria re-run individually and passing, including `uv run pre-commit run --files render.yaml` (gitleaks included).
- **Committed in:** `dfb601f`

**2. [Rule 1 - Bug] Same collision in the test module's docstring**

- **Found during:** Task 2 (acceptance-criteria check)
- **Issue:** Task 2 requires `grep -q 'pytest.mark.integration'` to return **no** match, but the plan also requires the module docstring to explain the testing choices — and the natural phrasing ("deliberately no `@pytest.mark.integration`") puts the literal in the file. Criterion intent is that no test in the file carries the marker.
- **Fix:** Docstring now reads "deliberately no integration marker". Meaning preserved, criterion satisfied (0 matches), no test behaviour changed.
- **Files modified:** `backend/tests/test_render_blueprint.py`
- **Verification:** `grep -c 'pytest.mark.integration'` → `0`; `pytest backend/tests/test_render_blueprint.py -q` → 7 passed.
- **Committed in:** `aef019c`

---

**Total deviations:** 2 auto-fixed (2 bugs, both in the plan's own text rather than in the codebase)
**Impact on plan:** Cosmetic at the file level, load-bearing at the verification level — without these edits a correct artifact would have failed its own acceptance greps. Zero semantic change to the blueprint or the tests. No scope creep.

## Issues Encountered

- **Fresh worktree had no `.venv`.** `uv sync --frozen` was run once to materialise it (~200 packages, no lockfile change). `git status` stayed clean — `.venv` is gitignored.
- **`uv` emits `warning: VIRTUAL_ENV=…/BRETT/.venv does not match the project environment path .venv`** on every invocation, same artifact plan 02-01 reported: the parent repo's venv is active in the shell while executing in a worktree. Worked around by prefixing commands with `VIRTUAL_ENV=`. Harmless; will not appear outside worktree execution.

## TDD Gate Compliance

Task 2 is marked `tdd="true"`, but the plan orders Task 1 (write `render.yaml`) **before** Task 2 (write its test), so a conventional RED gate is impossible by construction — the artifact under test already exists and correct tests must pass on first run. The plan anticipates this and substitutes a **negative control** as its acceptance criterion, which is the equivalent proof that the test can fail.

Git history therefore shows `chore(02-03): add Render blueprint…` → `test(02-03): bind render.yaml to Settings…` with **no `feat(...)` commit**. This is by plan design for an IaC-plus-guard plan, not a skipped gate: `chore` is the correct conventional type for a config/IaC file, and the RED evidence is the two recorded control failures above. Flagged here so a gate-sequence check does not read the missing `feat` as a compliance failure.

## Known Stubs

None. `render.yaml` contains no placeholder that flows anywhere — the two `sync: false` entries are the documented mechanism for "Render prompts for this in the dashboard", not stubs. The `brett.onrender.com` hostname is a documented **assumption with a named owner** (plan 02-05 Task 1), covered in its own section above.

## Security Notes

All four `mitigate` dispositions in this plan's threat register are implemented and test-backed:

- **T-02-10** (Information Disclosure, committed secrets) — no credential literal anywhere in `render.yaml`. `MCP_AUTH_SECRET` → `generateValue: true` (minted server-side, never touches a developer machine); `DATABASE_URL` → `fromDatabase`; `MCP_ISSUER_URL`/`MCP_JWKS_URI` → `sync: false`. Enforced by `test_no_secret_is_committed_as_a_literal`, which matches on **name markers** rather than a fixed key list, so a secret added in a later plan is caught by default. Gitleaks pre-commit hook is the backstop and passes.
- **T-02-01** (Spoofing, Host allowlist) — a single explicit hostname, never `*`. `test_resource_url_and_allowed_hosts_agree` proves the resource URL's host is inside the allowlist.
- **T-02-03** (Information Disclosure, resource URL) — asserted to end in `/mcp`, use `https`, and carry no query string, so a token cannot be smuggled into the resource identifier.
- **T-02-06** (`/health` unauthenticated) — accepted as designed (D-04); `test_health_check_path_is_open_endpoint` pins the path so it cannot be silently repointed at an authenticated route, which would make every deploy fail its health check and roll back with a 401 as the only clue.
- **T-02-04** (`LOG_LEVEL: INFO` in production) — accepted; the blueprint sets `INFO`, not `DEBUG`.

No security-relevant surface was introduced beyond the threat model. This plan adds no endpoint, no auth path, and no schema change — it declares infrastructure and asserts over a file.

## Requirements Status

The plan frontmatter lists `requirements: [DEPLOY-01]`. **`REQUIREMENTS.md` was deliberately left unmodified**, consistent with plan 02-01's precedent:

| ID | Requirement | Why not satisfied here |
|----|-------------|------------------------|
| DEPLOY-01 | Backend + MCP deployed to Render over HTTPS with env-based secrets | The *env-based secrets* half is now structurally guaranteed and test-enforced, but **nothing is deployed** — no Render service exists, no blueprint has been synced. Plans 02-05 (deploy) and 02-07 (tier upgrade) own the deploy half. |

Marking it complete on the strength of a committed YAML file would be a false completion claim. Additionally, parallel worktree executors each editing `REQUIREMENTS.md` would produce guaranteed merge conflicts.

**Action for the orchestrator:** mark `DEPLOY-01` complete only once the verifier confirms a live deployed endpoint.

## Next Phase Readiness

**Ready for plan 02-05 (deploy).** It can now assume:

- `render.yaml` exists at the repo root, parses, and is the single source of truth for the service shape.
- Every `envVars` key is guaranteed to correspond to a real `Settings` field at the moment of commit.
- No secret needs to be typed anywhere except the two `sync: false` WorkOS values, which are unknown until 02-06 anyway and can be left blank for the initial free-tier deploy (`mcp_auth_mode` defaults to `static`, so neither is read).

**Carry forward, in priority order:**

1. **Reconcile `brett.onrender.com`** in `MCP_ALLOWED_HOSTS` and `MCP_RESOURCE_URL` with the hostname Render actually assigns (02-05 Task 1). This is the highest-probability failure in the phase.
2. **Migrations must run from the developer machine** while `plan: free` — there is no `preDeployCommand`, no shell, and no one-off jobs on the free tier: `DATABASE_URL="<render external connection string>" uv run --directory backend python -m alembic upgrade head`. Until this runs, `/health` will report `{"status":"degraded","database":"error"}` on a service that deployed successfully.
3. **Plan 02-07 must make three edits in one commit:** `plan: starter` on the service, `plan: basic-256mb` on the database, and uncomment `preDeployCommand` (line 31). The free Postgres is deleted 30 days after creation.
4. `MCP_AUTH_MODE` is `static` in the blueprint; 02-07 flips it to `authkit`.

## Self-Check: PASSED

- **Files verified present:** `render.yaml` (80 lines), `backend/tests/test_render_blueprint.py` (224 lines), `.planning/phases/02-deploy-connector-auth-spike/02-03-SUMMARY.md` — 3/3 found.
- **Commits verified in git history:** `dfb601f`, `aef019c` — 2/2 found. Neither commit deletes a tracked file (`git diff --diff-filter=D HEAD~1 HEAD` empty for both).
- **Every cited line number re-checked against the file after the negative-control reverts:** two claims were wrong on first write and corrected — the hostname env vars are at lines 53-54 and 58-59 (not 57/62, which were pre-revert offsets), and there are **ten** `envVars` entries, not nine. The commented `preDeployCommand` is at line 31 as stated.
- **Plan verification block, all five steps:** (1) `yaml.safe_load` exits 0; (2) `pytest backend/tests/test_render_blueprint.py -q` → 7 passed; (3) `pre-commit run --files render.yaml backend/tests/test_render_blueprint.py` → all six hooks pass; (4) `git status --short` empty, only the two declared files were created; (5) `grep -rn 'preDeployCommand' render.yaml` → both matches are on comment lines (24, 31).
- **Full fast suite:** `pytest -m "not integration" -q` → 44 passed, 14 deselected, 0 failed. `ruff check` and `ruff format --check` clean.
- **Shared orchestrator artifacts untouched:** no change to `STATE.md`, `ROADMAP.md`, `REQUIREMENTS.md`, `pyproject.toml`, or `uv.lock`.

---
*Phase: 02-deploy-connector-auth-spike*
*Completed: 2026-08-27*
