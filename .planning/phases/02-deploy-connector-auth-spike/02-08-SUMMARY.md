---
phase: 02-deploy-connector-auth-spike
plan: 08
subsystem: infra
tags: [cloud-run, gcloud, cloud-buildpacks, uv, procfile, secret-manager, neon, pytest, yaml]

# Dependency graph
requires:
  - phase: 02-deploy-connector-auth-spike (plan 03)
    provides: render.yaml + test_render_blueprint.py — the Render deliverable this plan replaces, and the source of the ported `_settings_env_names()` helper and five of the twelve assertions
  - phase: 02-deploy-connector-auth-spike (plan 04)
    provides: the FastAPI + MCP mount at `/`, so `app.main:app` is the entrypoint the Procfile names
  - phase: 01-backend-foundation
    provides: `Settings` with `extra="ignore"`, the `MCP_ALLOWED_HOSTS` validation_alias, and `async_database_url`'s libpq→asyncpg translation that makes Neon a zero-code-change swap
provides:
  - Procfile — the entrypoint Cloud Buildpacks requires; without it `gcloud run deploy --source` fails before installing a single dependency
  - .gcloudignore — upload exclusion list keeping ~490 MB of personal health exports out of a Cloud Storage build bucket
  - deploy/cloud-run.env.yaml — the complete non-secret runtime environment (the render.yaml envVars analog)
  - scripts/deploy-cloud-run.sh — the D-06e reproducibility artifact wrapping `gcloud run deploy` and every load-bearing flag
  - backend/tests/test_cloud_run_deploy.py — twelve static drift assertions binding all four artifacts to Settings and to each other
  - Render-free planning docs, CLAUDE.md, and config.py
affects: [02-05 deploy checkpoint, 02-07 min-instances flip and connector round-trip, 07 production hardening]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Deploy config lives in a machine-parsable file (deploy/cloud-run.env.yaml), not inside the shell script, so a unit test can cross-check it against Settings"
    - "[tool.uv] default-groups = [] — checked-in and testable, unlike a build-time env var, because the buildpack runs a bare `uv sync`"
    - "Credential bindings are Secret Manager references only; the assertion that proves it never echoes the offending value"

key-files:
  created:
    - Procfile
    - .gcloudignore
    - deploy/cloud-run.env.yaml
    - scripts/deploy-cloud-run.sh
    - backend/tests/test_cloud_run_deploy.py
  modified:
    - pyproject.toml
    - README.md
    - backend/app/config.py
    - CLAUDE.md
    - .planning/PROJECT.md
    - .planning/REQUIREMENTS.md
  deleted:
    - render.yaml
    - backend/tests/test_render_blueprint.py

key-decisions:
  - "Deleted render.yaml and test_render_blueprint.py outright rather than archiving them (CONTEXT.md's recommended default) — an unused blueprint in the repo would mislead a future reader into deploying to an abandoned target"
  - "Both deletions land in the same commit as the new artifacts, so the fast suite is never left referencing a missing file"
  - "[tool.uv] default-groups = [] is the primary defence against dev deps shipping to production; --set-build-env-vars=UV_NO_DEV=1/UV_FROZEN=1 is belt-and-braces because assumption A-CR-1 is unverified"
  - "The T-02-10 failure message names the binding but never echoes its value — printing a credential into CI output is the same mistake hide_input_in_errors=True exists to prevent in Settings"
  - "Cloud Run's startup probe stays at the default TCP check; the Render healthCheckPath: /health assertion was dropped rather than translated, because an HTTP probe against /health would make every deploy depend on Neon being awake"

patterns-established:
  - "Negative controls substitute for a RED gate when the artifact necessarily precedes its test — run each, observe the failure verbatim, revert, confirm a clean tree"
  - "Static repo-file assertions carry no marker at all, so drift fails the fast suite on the commit that introduces it rather than after a deploy"

requirements-completed: []  # DEPLOY-01's ARTIFACT half only. The service is not deployed; plan 02-05 deploys it and plan 02-07 finishes DEPLOY-01. Do not check DEPLOY-01 off yet.

# Metrics
duration: 14min
completed: 2026-08-27
---

# Phase 2 Plan 08: Cloud Run Deploy Artifacts Summary

**Four committed Cloud Run deploy artifacts (Procfile, .gcloudignore, env-vars YAML, gcloud wrapper script) plus a twelve-assertion drift test that binds them to `Settings`, replacing the abandoned Render blueprint and every doc that still named it.**

## Performance

- **Duration:** ~14 min
- **Started:** 2026-08-27T05:20:00Z
- **Completed:** 2026-08-27T05:34:00Z
- **Tasks:** 3
- **Files touched:** 18 (5 created, 6 modified, 2 deleted, 5 formatting-drift fixes)

## Accomplishments

- **Unblocked plan 02-05.** `gcloud run deploy --source .` fails today, before installing a single dependency, with `for Python with pyproject.toml, provide a main.py or app.py file` — an error about the source root that has nothing to do with the real cause. The two-line `Procfile` closes the Cloud Buildpacks entrypoint gap, and its `--app-dir backend` is what keeps the container from dying remotely with `ModuleNotFoundError: No module named 'app'` (uv.lock records the root project as `source = { virtual = "." }`, so `uv sync` never puts `backend/` on `sys.path`).
- **Closed T-02-11 before it could open.** gcloud's implicit `.gitignore` fallback is the only thing keeping ~490 MB of personal health exports out of a Cloud Storage build bucket today, and it disappears the instant anyone adds a `.gcloudignore` for any unrelated reason. The committed one re-states every exclusion and adds `.claude/` and `.planning/`.
- **Cut the production image from 73 to 41 packages.** The uv buildpack runs a bare `uv sync` — no `--no-dev` — so uv's default `default-groups = ["dev"]` would have shipped pytest, mypy, ruff, pre-commit, testcontainers and the `docker` client into the image of a health-data service (T-02-13).
- **Twelve static assertions, all four negative controls observed failing.** The module has no marker of any kind, so drift fails the fast suite on the commit that introduces it. Fast suite went 56 → 49 (seven Render tests deleted) → 61.
- **Retargeted every document that still said Render**, including a `SUPERSEDED 2026-08-27` banner above CLAUDE.md's Deployment table so no future agent silently follows the stale rows.

## Task Commits

1. **Pre-existing formatting drift (Rule 3 blocker, see Deviations)** — `e5663a4` (style)
2. **Task 1: Create the four Cloud Run deploy artifacts and delete the Render pair** — `dc275db` (chore)
3. **Task 2: Twelve static assertions binding the deploy artifacts to Settings** — `07c78ea` (test)
4. **Task 3: Retarget every document that still names Render** — `efd32a4` (docs)

## Files Created/Modified

- `Procfile` — `web: uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port $PORT`. No `uv run` prefix: the uv buildpack prepends its venv's `bin` to `PATH` in the layer's shared environment, so `uvicorn` is already on `PATH` at launch. `$PORT` expands because `ctx.AddProcess` wraps every process as `bash -c`.
- `.gcloudignore` — 24 exclusion entries. Deliberately excludes none of `backend/`, `pyproject.toml`, `uv.lock`, `.python-version`, `Procfile` (verified: `grep -cxE` returns 0).
- `deploy/cloud-run.env.yaml` — seven keys, all strings, all resolving to a `Settings` field: `ENVIRONMENT`, `LOG_LEVEL`, `MCP_ALLOWED_HOSTS`, `MCP_RESOURCE_URL`, `MCP_AUTH_MODE`, `MCP_ISSUER_URL`, `MCP_JWKS_URI`.
- `scripts/deploy-cloud-run.sh` (mode 0755) — `PROJECT_ID="${BRETT_GCP_PROJECT:?set BRETT_GCP_PROJECT}"` fails closed rather than inheriting `gcloud config`, whose active project on this machine is `idx-yfinance-mcp-1785725283` (T-02-16).
- `backend/tests/test_cloud_run_deploy.py` — 12 tests, 0 markers, `_settings_env_names()` ported verbatim.
- `pyproject.toml` — `[tool.uv] default-groups = []` and `required-version = ">=0.12.1"` (a floor, not an equality: uv enforces `required-version` locally too and the dev machine is on 0.12.1).
- `README.md` — Local setup `uv sync` → `uv sync --group dev`, since a bare `uv sync` no longer installs pytest.
- `backend/app/config.py` — three stale comments only; zero executable lines changed.
- `CLAUDE.md`, `.planning/PROJECT.md`, `.planning/REQUIREMENTS.md` — Render → Google Cloud Run.

## Negative Controls (required by the plan — verbatim failure messages)

A conventional RED gate is impossible by construction: Task 1 wrote the artifacts before the test existed, so correct tests must pass on first run. Four controls were injected one at a time, observed failing, and reverted; `git status --short` was confirmed clean between each.

**Control 1 — `BOGUS_VAR: "x"` added to `deploy/cloud-run.env.yaml`.** Failed test 2 only (11 passed):

```
AssertionError: DEPLOY-01 violated: deploy/cloud-run.env.yaml sets BOGUS_VAR but Settings has no such field (extra='ignore' means the deployed service silently ignores it, so the deploy succeeds and the misconfiguration surfaces much later)
```

**Control 2 — `MCP_AUTH_SECRET: "negative-control-not-a-real-credential"` added to the env file.** Failed tests 4 and 8 (10 passed):

```
AssertionError: T-02-10 violated: deploy/cloud-run.env.yaml declares MCP_AUTH_SECRET, whose name matches ['SECRET']. --env-vars-file has no sync: false equivalent, so any value here is a literal committed to git forever; bind it through --set-secrets in scripts/deploy-cloud-run.sh instead
```

```
AssertionError: DEPLOY-01 violated: ['MCP_AUTH_SECRET'] appears both in deploy/cloud-run.env.yaml and in --set-secrets; Cloud Run rejects a deploy that binds one name in both places
```

**Control 3 — `--set-secrets` right-hand side changed to `DATABASE_URL=postgresql://u:p@h/db`.** Failed test 7 only (11 passed):

```
AssertionError: T-02-10 violated: --set-secrets binds DATABASE_URL to something that is not a Secret Manager reference (expected `secret-name:latest` or `secret-name:VERSION`). If that is a credential literal it is now in git history, which no later commit can undo
```

Note the message names the binding but does **not** echo the value — deliberate, so a real leaked credential is not reprinted into CI output.

**Control 4 — `--app-dir backend` removed from the `Procfile`.** Failed test 10 only (11 passed):

```
AssertionError: DEPLOY-01 violated: the Procfile `web:` line omits '--app-dir backend'. uv.lock records the root project as virtual, so `uv sync` never puts backend/ on sys.path and the container dies remotely and silently with `ModuleNotFoundError: No module named 'app'`; Cloud Run additionally requires 0.0.0.0 and its injected $PORT
```

## Handoff to Plan 02-05

**Package counts (for resolving assumption A-CR-1).** Resolved in clean environments via `UV_PROJECT_ENVIRONMENT`:

| Set | Command | Packages |
|---|---|---|
| Production only (what the image should contain) | `uv sync --frozen --dry-run` | **41** |
| With the dev group (what a bare `uv sync` would have shipped before `default-groups = []`) | `uv sync --frozen --group dev --dry-run` | **73** (32 extra) |

Grep the first Cloud Build log for the installed package count. **41 means `[tool.uv] default-groups = []` took effect. 73 means it did not**, and `--set-build-env-vars=UV_NO_DEV=1` also failed to reach the buildpack — which would resolve A-CR-1 negatively and require the Dockerfile fallback (Q1.3) or `GOOGLE_`-prefixed alternatives.

**`uv pip check` on the production-only set: CLEAN.** `Checked 41 packages in 0.76ms / All installed packages are compatible`. This matters because the uv buildpack runs `uv pip check` as a hard build gate — a resolver conflict would fail the deploy with `found incompatible dependencies`. The 73-package dev set is also clean.

**The placeholder that plan 02-05 must reconcile.** `000000000000` is a stand-in for the 12-digit GCP project number, and it appears in **two keys in `deploy/cloud-run.env.yaml` that must be changed together**:

| Key | Current value | Why both |
|---|---|---|
| `MCP_ALLOWED_HOSTS` | `brett-000000000000.us-central1.run.app` | The DNS-rebinding guard; wrong value → every request returns `421 Invalid Host header` with no MCP-level error body (T-02-01) |
| `MCP_RESOURCE_URL` | `https://brett-000000000000.us-central1.run.app/mcp` | Published in the RFC 9728 metadata document; must match the connector dialog character for character |

`test_resource_url_and_allowed_hosts_agree` asserts the second's host is inside the first, so editing one without the other fails the fast suite immediately. Get the real number with `gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)'` — the deterministic URL is knowable **before** the first deploy, which removes the Render plan's "deploy → discover hostname → redeploy" round trip. Cloud Run also assigns a legacy hash URL and serves both: run `gcloud run services describe brett --format='value(status.url,status.urls)'` after the first deploy and append any second hostname to `MCP_ALLOWED_HOSTS` (comma-separated).

Region is `us-central1` throughout the env file and the script default (`BRETT_GCP_REGION`); if 02-05 picks a different region to co-locate with Neon, all three occurrences move together.

## Decisions Made

See `key-decisions` in the frontmatter. The one worth restating: the Render `healthCheckPath: /health` assertion was **dropped rather than translated**. Cloud Run's default startup probe is TCP on the container port and the deploy waits for it; `/health` performs a live `SELECT 1`, so an HTTP startup probe against it would couple every deploy's success to Neon being awake. That is why this module has twelve assertions rather than a straight 7→12 superset of the deleted one.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Pre-existing pre-commit formatting drift blocked Task 1's acceptance criterion**

- **Found during:** Task 1 (running `uv run pre-commit run --all-files`)
- **Issue:** `ruff-format` reformatted three files and `end-of-file-fixer` fixed two more, none of them in this plan's scope: `backend/migrations/versions/0001_initial_schema.py`, `backend/tests/test_mcp_mount.py`, `backend/tests/test_time.py`, `backend/migrations/README`, `.planning/config.json`. Cause: earlier Phase 2 waves ran as parallel worktree executors and commit with `--no-verify` by design, so formatter output never landed. Task 1's acceptance criterion `uv run pre-commit run --all-files exits 0` is unsatisfiable while this drift exists.
- **Fix:** Accepted the formatter's output and committed it **in its own isolated `style` commit before any task commit**, so no task commit carries unrelated changes. Every diff is whitespace/line-wrapping or a trailing newline; 5 insertions, 11 deletions across five files; zero semantic change.
- **Files modified:** the five listed above
- **Verification:** `pytest -m "not integration"` unchanged at 49 passed immediately before and after; `pre-commit run --all-files` exits 0 from that commit onward
- **Committed in:** `e5663a4` (separate from all three task commits)

**2. [Rule 1 - Bug] The plan's prescribed PROJECT.md Constraints text failed the plan's own acceptance grep**

- **Found during:** Task 3 (acceptance-criteria check)
- **Issue:** The plan dictates the Constraints bullet read `Google Cloud Run for v1 (switched from Render on 2026-08-27, revised D-06)`, but its own criterion is `grep -n 'Render' .planning/PROJECT.md | grep -vciE 'supersed|unused'` returns `0`. The prescribed text contains "Render" and matches neither exclusion, so the criterion reported 1 on a correct file. This is the same class of collision plan 02-03 hit twice.
- **Fix:** Reworded to `Google Cloud Run for v1 (supersedes Render as of 2026-08-27, revised D-06)`. Identical meaning, arguably clearer, and the criterion now returns 0. No other text changed.
- **Files modified:** `.planning/PROJECT.md`
- **Verification:** `grep -n 'Render' .planning/PROJECT.md | grep -vciE 'supersed\|unused'` → `0`; `grep -c 'Google Cloud Run' .planning/PROJECT.md` → `3` (criterion wants ≥2)
- **Committed in:** `efd32a4` (Task 3 commit)

---

**Total deviations:** 2 auto-fixed (1 blocking, 1 bug — both in tooling state and plan text rather than in the delivered artifacts)
**Impact on plan:** Zero semantic change to anything this plan ships. No scope creep. Every one of the plan's own artifacts was written exactly as specified.

## Issues Encountered

- **`uv sync --frozen --dry-run` acceptance criterion is environment-dependent.** The criterion reads "output names none of `pytest`, `mypy`, `ruff`, `pre-commit`". Run against a developer venv that *has* the dev group installed, the dry run names all four — as **uninstalls** (`Would uninstall 32 packages`), which is the desired behaviour, not a violation. It is only literally satisfiable against a production-shaped environment. Resolved by evaluating it two ways: (a) in a clean scratch environment, `uv sync --frozen --dry-run` resolves to `Checked 41 packages / Would make no changes`; (b) after applying `uv sync --frozen` to the real venv, the dry run again names nothing. Both confirm the intent. A verifier re-running this grep against a dev-installed venv should read the output direction, not just the package names.
- **Fresh worktree had no `.venv`.** `uv sync --frozen` was run once to materialise it. Same `warning: VIRTUAL_ENV=…/BRETT/.venv does not match the project environment path .venv` artifact plans 02-01 and 02-03 reported (the parent repo's venv is active in the worktree shell); worked around by prefixing commands with `VIRTUAL_ENV=`. Harmless, worktree-only.
- **Commit-boundary correction.** `git rm` staged the two Render deletions before the style commit was made, sweeping them into it. Caught immediately via `git show --stat HEAD --diff-filter=D`, corrected with `git reset --soft HEAD~1` + `git restore --staged` on the two paths, and recommitted so the deletions land in Task 1 as the plan requires. Final history is correct: `git show --stat dc275db --diff-filter=D --name-only` lists exactly `render.yaml` and `backend/tests/test_render_blueprint.py`.

## Known Stubs

| Stub | File | Line | Reason / resolver |
|---|---|---|---|
| `000000000000` GCP project number | `deploy/cloud-run.env.yaml` | 26 (`MCP_ALLOWED_HOSTS`), 31 (`MCP_RESOURCE_URL`) | **Intentional and documented in-file.** The real project number does not exist until plan 02-05 creates the GCP project. It is a placeholder rather than a blank because Cloud Run's deterministic URL format makes the final value knowable pre-deploy, and a well-formed placeholder keeps `test_resource_url_and_allowed_hosts_agree` meaningful (it proves the two keys agree with each other regardless of the number). **Resolved by plan 02-05.** |
| `MCP_ISSUER_URL: "https://example.authkit.app"`, `MCP_JWKS_URI: ""` | `deploy/cloud-run.env.yaml` | 37-38 | Intentional. `MCP_AUTH_MODE` is `static` for the D-01 CLI proof, so neither value is read yet. **Resolved by plans 02-06/02-07** when the mode flips to `authkit`. These are the `Settings` defaults, not invented values. |

No stub prevents this plan's goal: the artifacts are complete and self-consistent, and the placeholder is the one value that cannot exist before 02-05 runs.

## Security Notes

Every `mitigate` disposition in this plan's threat register is implemented and test-backed:

- **T-02-11** (health-data upload) — `.gcloudignore` committed with all six export/scratch exclusions plus `.venv/`, `.env`, `.env.*`, `.planning/`, `.claude/`. Asserted by test 11.
- **T-02-10** (committed credentials) — no credential literal in any artifact. `DATABASE_URL` and `MCP_AUTH_SECRET` are bound only as `name:latest` Secret Manager references. Test 4 forbids a credential-shaped key in the env file outright (stricter than the Render rule it replaces, because Cloud Run has no `sync: false` equivalent); test 7 forbids a literal on the right-hand side of `--set-secrets`; test 8 forbids the two being bound in both places. gitleaks passes on `--all-files`.
- **T-02-13** (dev deps in the production image) — `[tool.uv] default-groups = []` verified to cut 73 → 41 packages, plus `--set-build-env-vars=UV_NO_DEV=1`.
- **T-02-14** (build-time re-locking) — `--set-build-env-vars=UV_FROZEN=1`. Residual risk per A-CR-1 accepted and diagnosable from the first build log's package count (see Handoff).
- **T-02-01** (Host allowlist) — a single explicit hostname, never `*`. Test 5 proves the resource URL's host is inside it.
- **T-02-03** (resource identifier) — test 5 asserts `https`, `/mcp` suffix, and empty query string.
- **T-02-16** (deploy into the wrong project) — `${BRETT_GCP_PROJECT:?...}` fails closed; test 6 asserts `--project` is still passed.
- **T-02-15** (`--allow-unauthenticated`) — accepted as designed. Claude's connectors cannot mint a Google ID token, so Cloud Run's IAM invoker check must be off and the MCP `TokenVerifier` is the real gate. Plan 02-05's Auth Verification Matrix rows 1-3 are what prove the service is not actually open.

No new security-relevant surface was introduced beyond the threat model. This plan adds no endpoint, no auth path, and no schema change — it declares infrastructure and asserts over files. **No threat flags.**

## User Setup Required

None from this plan. Plan 02-05 carries the human checkpoints (GCP project ID + billing authorisation, Neon project creation). Note the research addendum's D-06a correction: the gcloud CLI, an authenticated account, and an **open billing account** already exist, so that checkpoint is smaller than CONTEXT.md originally assumed.

## Next Phase Readiness

**Ready for plan 02-05.** The `Procfile` blocker that would have failed 02-05's first `gcloud run deploy --source` is closed, the deploy command is committed and syntax-checked, and the two placeholder keys 02-05 must reconcile are documented above with the exact command that produces the real value.

**Not done, by design:** `render.yaml`'s deletion means there is no longer any committed description of a *working* deploy until 02-05 runs the script successfully once. That is the intended sequencing (02-08 → 02-05 → 02-06 → 02-07).

**Concerns carried forward:**
- **A-CR-1 unresolved.** Whether `--set-build-env-vars` forwards non-`GOOGLE_`-prefixed keys to the buildpack is unverified. Impact is low because `default-groups = []` covers the same defect independently, but 02-05 should grep the first build log for the package count and record the answer.
- **A-CR-3 unresolved.** Whether Cloud Run forwards the original public `Host` header unmodified. If it does not, every MCP request returns 421 and `MCP_ALLOWED_HOSTS` needs a different value — diagnosable in one request against the deployed URL.
- Research addendum is dated **valid until 2026-09-10**; Cloud Buildpacks' Python/uv support is actively changing. If 02-05 slips past that date, re-run `gcloud run deploy --help` and re-read `cmd/python/missing_entrypoint` before trusting the Procfile analysis.

## Verification Evidence

| Plan verification step | Result |
|---|---|
| 1. `uv run pytest -m "not integration" -q` | **61 passed**, 0 failed, 28 deselected |
| 2. `uv run pytest backend/tests/test_cloud_run_deploy.py -q` | **12 passed** |
| 3. `bash -n scripts/deploy-cloud-run.sh` + executable | exit 0; `test -x` OK (mode 0755) |
| 4. `test ! -e render.yaml && test ! -e backend/tests/test_render_blueprint.py` | both absent |
| 5. `uv sync --frozen --dry-run` names no dev package | 41 packages, `Would make no changes` (see Issues for the environment caveat) |
| 6. `grep -c 'Render'` on REQUIREMENTS.md / ROADMAP.md / config.py | `0` / `0` after excluding the two pivot-describing lines / `0` |
| 7. `uv run pre-commit run --all-files` | exit 0, gitleaks Passed |
| 8. `git log --oneline -3` shows artifact, test, doc commits; no credential in any `git show --stat` | confirmed (`dc275db`, `07c78ea`, `efd32a4`) |

Additional greps: `grep -c 'def test_'` → 12; `grep -c '@pytest.mark'` → 0; the twelve required test names → 12 matches; `grep -c -- '--set-env-vars' scripts/deploy-cloud-run.sh` → 0; `grep -cE -- '--add-cloudsql-instances|--vpc-connector'` → 0; `grep -cxE 'backend/?|pyproject\.toml|uv\.lock|Procfile|\.python-version' .gcloudignore` → 0; `grep -c 'render_as_string' backend/app/config.py` → 1 (the SQLAlchemy call was not collateral damage).

## Self-Check: PASSED

All 12 claimed files verified present on disk (`Procfile`, `.gcloudignore`, `deploy/cloud-run.env.yaml`, `scripts/deploy-cloud-run.sh` at mode 0755, `backend/tests/test_cloud_run_deploy.py`, `pyproject.toml`, `README.md`, `backend/app/config.py`, `CLAUDE.md`, `.planning/PROJECT.md`, `.planning/REQUIREMENTS.md`, this summary). Both claimed deletions verified absent (`render.yaml`, `backend/tests/test_render_blueprint.py`). All 4 claimed commits verified in `git log`: `e5663a4`, `dc275db`, `07c78ea`, `efd32a4`.

**Not modified, by design (worktree mode):** `.planning/STATE.md` and `.planning/ROADMAP.md` — the orchestrator owns those writes after the wave merges. `.planning/REQUIREMENTS.md` was edited for DEPLOY-01's *text* only; its checkbox is deliberately left unchecked, since only the artifact half of DEPLOY-01 is done.

---
*Phase: 02-deploy-connector-auth-spike*
*Completed: 2026-08-27*
