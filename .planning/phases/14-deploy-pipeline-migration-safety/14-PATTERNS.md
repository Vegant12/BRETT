# Phase 14: Deploy Pipeline Migration Safety - Pattern Map

**Mapped:** 2026-09-07
**Files analyzed:** 3 (1 modified script, 1 extended test file, 1 new/extended test file or module)
**Analogs found:** 3 / 3 (all analogs are sibling files in the same subsystem — this phase
modifies an existing file and extends existing test files rather than creating a new
subsystem, so every analog is a near-exact match)

No RESEARCH.md exists for this phase (skipped by user decision per CONTEXT.md). All patterns
below are extracted directly from the canonical references CONTEXT.md names.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `scripts/deploy-cloud-run.sh` (modified: add pre-flight migration step before `exec gcloud run deploy`) | config/deploy-script | batch (sequential shell pre-flight → deploy) | `scripts/deploy-sync-job.sh` (sibling Cloud Run deploy script) + itself (existing conventions) | exact |
| `backend/tests/test_cloud_run_deploy.py` (extended: new static assertion mirroring `_REQUIRED_FLAGS`) | test | transform (parse script text → assert) | itself — `test_deploy_script_carries_every_required_flag`, `test_deploy_script_has_no_comment_inside_the_gcloud_call` | exact |
| New drift-rehearsal integration test (location: planner's call — either appended to `backend/tests/test_migrations.py` or a new sibling file, e.g. `backend/tests/test_deploy_migration_preflight.py`) | test | event-driven / batch (container lifecycle: downgrade → run predicate → assert abort) | `backend/tests/test_migrations.py`'s `test_migrations_round_trip` + `test_no_pending_model_drift` | exact |
| Extracted pre-flight predicate (planner's call: shell function in `deploy-cloud-run.sh` called via subprocess from the test, OR a small Python helper e.g. `backend/app/cli.py` addition or `backend/scripts/`-style module) | utility | request-response (compare two revision strings, return abort/proceed) | `backend/migrations/env.py`'s `do_run_migrations`/`run_async_migrations` shape (async engine + alembic context) for the Python-helper option; `scripts/deploy-sync-job.sh`'s flag-and-comment conventions for the shell-function option | role-match |

## Pattern Assignments

### `scripts/deploy-cloud-run.sh` (config/deploy-script, batch pre-flight)

**Analog:** itself (existing file, in-place edit) + `scripts/deploy-sync-job.sh` (sibling script, same house style)

**Imports/header pattern** (`scripts/deploy-cloud-run.sh` lines 1-11):
```bash
#!/usr/bin/env bash
# The single reproducible description of how BRETT deploys (D-06e). This replaces
# render.yaml: it is what a future reader opens to learn how this service reaches
# production, and backend/tests/test_cloud_run_deploy.py asserts every flag below
# is still here.
#
# Requires: gcloud >= 578, an authenticated account, and the project bootstrap
# performed by plan 02-05 (APIs enabled, runtime service account, secrets created).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
```
Extend this header comment to also document the new alembic pre-flight step's rationale
(the D-01/D-02/D-05 decisions), following the same "one paragraph, cites the requirement id"
convention already used for the memory-size rationale below.

**`${VAR:?required}` / `${VAR:-default}` pattern** (lines 13-25):
```bash
# Never inherit `gcloud config get-value project`: the active project on a
# developer machine is routinely something unrelated, and a silent deploy into the
# wrong project is expensive to notice.
PROJECT_ID="${BRETT_GCP_PROJECT:?set BRETT_GCP_PROJECT}"
REGION="${BRETT_GCP_REGION:-us-central1}"
SERVICE="${BRETT_SERVICE:-brett}"
# D-06f: 0 while proving the pipeline, 1 before any real connector test. Prefer
# flipping it with `gcloud run services update SERVICE --min=1`, which is a
# service-level change and needs no rebuild.
MIN_INSTANCES="${BRETT_MIN_INSTANCES:-0}"
# Bounds total Postgres connections: SQLAlchemy holds at most 10 per instance.
MAX_INSTANCES="${BRETT_MAX_INSTANCES:-2}"
RUNTIME_SA="brett-run@${PROJECT_ID}.iam.gserviceaccount.com"
```
**Copy this exact shape for D-05/D-06**: the new `DATABASE_URL` fetch is a required value with
an overridable escape hatch, so it belongs as a new variable block here, e.g. (illustrative,
not prescriptive of exact naming — planner's call per CONTEXT.md, but the shape is locked):
```bash
# D-05/D-06: fetch the production DATABASE_URL ourselves rather than trusting a pre-set
# shell env var — Phase 9's incident was exactly a stale/wrong DATABASE_URL in the operator's
# shell. BRETT_DATABASE_URL is the escape hatch for deliberate non-prod testing (D-06).
DATABASE_URL="${BRETT_DATABASE_URL:-$(gcloud secrets versions access latest \
  --project="$PROJECT_ID" --secret="brett-database-url")}"
```

**Comment-placement hazard (hard constraint, D-03)** — the exact hazard the new step must not
repeat, documented at lines 38-43:
```bash
# NOTE for future editors: this rationale lives ABOVE the invocation, not beside the flag it
# explains, because a `#` comment between two backslash-continued lines TERMINATES the command
# there. `bash -n` still reports the file as valid, and the deploy would silently run with every
# flag after the comment dropped -- no env file, no secrets, no memory setting. Never put a
# comment inside the block below; `test_deploy_script_has_no_comment_inside_the_gcloud_call`
# fails the build if anyone does.
exec gcloud run deploy "$SERVICE" \
  ...
```
The new migration pre-flight block (D-01 `alembic upgrade head`, D-02 `alembic current` ==
`alembic heads` verification) must be its own set of plain (non-continued) statements placed
between the variable setup and this `exec gcloud run deploy` block — never inserted as a
comment inside the backslash-continued invocation, and every rationale comment for it goes
ABOVE the statement it explains, exactly like the `--memory=1Gi` comment above does for that
flag (lines 27-33).

**`set -euo pipefail` is what makes failure abort the script** (line 9) — already present, no
change needed; this is what turns a non-zero `alembic upgrade head` or a failed `current` vs
`heads` comparison into a hard stop before `exec gcloud run deploy` runs (per D-02 and the
Integration Points note in CONTEXT.md).

**Sibling script's Cloud Run Job conventions** (`scripts/deploy-sync-job.sh`, for house-style
reference only, not modified):
```bash
# One attempt plus one retry. A Hevy full sync is idempotent and resumable from its
# checkpoint (HEVY-08/09), so a retry is safe -- but a high retry count on a 6-hourly
# schedule can stack executions, and the next scheduled run is only hours away.
MAX_RETRIES="${BRETT_SYNC_MAX_RETRIES:-1}"
```
```bash
exec gcloud run jobs deploy "$JOB" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --source="$REPO_ROOT" \
  --service-account="$RUNTIME_SA" \
  ...
  --set-secrets="DATABASE_URL=brett-database-url:latest,HEVY_API_KEY=brett-hevy-api-key:latest" \
  --quiet
```
Confirms `brett-database-url` is already the established Secret Manager name to fetch from in
D-05 — both scripts already bind it under this exact secret id.

**Invoking `alembic` via its CLI, matching how the script already shells out to `gcloud`**
(CONTEXT.md "Established Patterns" — no new subcommand needed in `backend/app/cli.py`):
```bash
(cd backend && uv run alembic upgrade head)
```
matches the project's own reference invocation, run as a subprocess from `backend/`, the same
way `backend/tests/conftest.py`'s `alembic` fixture does it (see below) and the same way
`REPO_ROOT="$(cd ... && pwd)"` is already established as the script's own path-resolution idiom.

---

### `backend/tests/test_cloud_run_deploy.py` (test, static text-parsing assertion)

**Analog:** itself — `_REQUIRED_FLAGS` guard (lines 54-64) and its consuming test (lines 228-237)

**Module docstring/framing pattern** (lines 1-24) — new assertions in this file should follow
the same "why this is a test, not a comment" framing: state the silent failure mode, when it
surfaces, and why nothing else catches it.

**Constant + helper pattern to mirror** (lines 54-64, 89-111):
```python
# Dropping any one of these silently changes where or how the service deploys.
_REQUIRED_FLAGS = (
    "--source",
    "--region",
    "--project",
    "--service-account",
    "--allow-unauthenticated",
    "--env-vars-file",
    "--set-secrets",
    "--min",
    "--max",
)


def _deploy_script_text() -> str:
    """The deploy script as text. Read, never executed -- running it would deploy."""
    return DEPLOY_SCRIPT.read_text()


def _secret_bindings() -> dict[str, str]:
    """``{ENV_NAME: SECRET_REF}`` parsed out of the script's ``--set-secrets``.

    Read as text rather than executed: running the script would deploy.
    """
    match = _SET_SECRETS_ARG.search(DEPLOY_SCRIPT.read_text())
    ...
```
The new assertion for the migration pre-flight step (ROADMAP success criterion 3) should be a
new small helper in this exact style — parse `_deploy_script_text()` for evidence the alembic
upgrade + verification runs BEFORE the `exec gcloud run deploy` line — e.g. asserting the line
index of `alembic upgrade head` (or the extracted predicate's invocation) is less than the line
index of `exec gcloud run deploy`, reusing the same `starts = [i for i, line in
enumerate(lines) if line.startswith("exec gcloud run deploy")]` idiom already used at lines
281-283 of `test_deploy_script_has_no_comment_inside_the_gcloud_call`.

**Assertion message style** (lines 232-237, 314-317, 332-335) — cite the requirement id, state
what's wrong and why it's dangerous:
```python
for flag in _REQUIRED_FLAGS:
    assert flag in script, (
        f"DEPLOY-01 violated: scripts/deploy-cloud-run.sh no longer passes {flag}; this "
        f"script is the single reproducible description of how BRETT deploys (D-06e), so "
        f"a missing flag silently changes the deployed service"
    )
```
```python
assert bindings, (
    "DEPLOY-01 violated: scripts/deploy-cloud-run.sh binds no secrets at all; "
    "DATABASE_URL and MCP_AUTH_SECRET have no other source on Cloud Run"
)
```
The new DEPLOY-04 assertion(s) should follow exactly this shape: `f"DEPLOY-04 violated: ...
{what's wrong}; {why it's dangerous, referencing the specific incident it prevents}"`.

**No-execution constraint** (module docstring, lines 21-24; reinforced in `_deploy_script_text`
and `_secret_bindings` docstrings) — a hard constraint carried into this phase's new tests too:
"Static assertions over committed files: no container, no network... Read, never executed --
running it would deploy." Any new static assertion in this file must keep reading the script as
text via `DEPLOY_SCRIPT.read_text()` / `_deploy_script_text()`, never invoke it.

---

### Drift-rehearsal integration test (new; file location is planner's call)

**Analog:** `backend/tests/test_migrations.py` — `test_migrations_round_trip` (lines 36-54) and
`test_no_pending_model_drift` (lines 80-86), plus their fixtures in `backend/tests/conftest.py`

**Imports pattern** (`test_migrations.py` lines 1-16):
```python
"""FOUND-02: migrations are the sole authority over the schema.

Every assertion here runs against a real Postgres container. SQLite would prove
nothing -- ``TIMESTAMPTZ``, ``information_schema`` and the UUID type all behave
differently or not at all.
"""

import subprocess
import uuid
from collections.abc import Callable

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import DEFAULT_USER_ID
```

**Core pattern to reuse — real Postgres, downgrade, then re-run the mechanism under test**
(lines 36-54):
```python
@pytest.mark.integration
async def test_migrations_round_trip(
    engine: AsyncEngine,
    alembic: Callable[..., subprocess.CompletedProcess[str]],
    restore_schema: None,
) -> None:
    """A fresh database reaches head, reverses to bare, and re-seeds exactly once."""
    assert alembic("upgrade", "head").returncode == 0
    assert alembic("current").stdout.strip().endswith("(head)")
    assert len(await _users(engine)) == 1  # D-01 seed

    result = alembic("downgrade", "base")
    assert result.returncode == 0, result.stderr
    # No manual SQL and no leftover tables: `downgrade base` is genuinely complete.
    assert await _tables(engine) == ["alembic_version"]

    assert alembic("upgrade", "head").returncode == 0
    # Re-running the seed must not produce a second user.
    assert len(await _users(engine)) == 1
```
The new drift-rehearsal test follows the same shape but stops one revision short of head
instead of `base` (e.g. `alembic("downgrade", "-1")` against the current head `0006`, landing
on `0005`), then calls the EXTRACTED pre-flight predicate (not raw `alembic upgrade head`
again) and asserts it detects the drift and reports abort — this is the "exercise the same
pre-flight logic the deploy script uses" requirement from D-04. Reuse `restore_schema` (below)
so this destructive test cannot leave the shared session-scoped container behind at a stale
revision for later tests.

**`alembic check` drift-detection pattern** (lines 80-86) — the closest existing analog for
"assert a check command's return code, not just trust exit status":
```python
@pytest.mark.integration
def test_no_pending_model_drift(
    alembic: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    """`alembic check` fails if the models and the migrations have diverged."""
    result = alembic("check")
    assert result.returncode == 0, result.stdout + result.stderr
```
D-02's "assert `alembic current` now matches `alembic heads`" verification is structurally the
same idea — run a read-only alembic command, parse/compare its output, fail loud on mismatch —
so the new predicate should follow this exact "run subprocess, inspect returncode AND stdout,
never swallow the diagnostic" shape.

**Fixtures to reuse verbatim, from `backend/tests/conftest.py`:**

`postgres_url` (lines 248-267) — session-scoped container already migrated to head via
subprocess (the same entrypoint production uses):
```python
@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """A running Postgres container, already migrated to head. ..."""
    with PostgresContainer("postgres:18-alpine", driver="asyncpg") as container:
        url = container.get_connection_url()
        subprocess.run(  # noqa: S603
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND_DIR,
            env={**os.environ, "DATABASE_URL": url},
            check=True,
            capture_output=True,
            text=True,
        )
        yield url
```

`alembic` callable fixture (lines 270-288) — deliberately does not raise on failure so a test
can assert on `returncode`/`stdout`:
```python
@pytest.fixture(scope="session")
def alembic(postgres_url: str) -> Callable[..., subprocess.CompletedProcess[str]]:
    """Run an arbitrary alembic command against the test container.

    Deliberately does NOT pass ``check=True``: ``test_no_pending_model_drift``
    asserts on the return code, and a raised ``CalledProcessError`` would hide
    the ``alembic check`` output that explains the drift.
    """

    def _alembic(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603
            [sys.executable, "-m", "alembic", *args],
            cwd=BACKEND_DIR,
            env={**os.environ, "DATABASE_URL": postgres_url},
            capture_output=True,
            text=True,
        )

    return _alembic
```

`restore_schema` (lines 291-304) — mandatory for any new destructive (downgrade) test sharing
the session-scoped container:
```python
@pytest.fixture
def restore_schema(
    alembic: Callable[..., subprocess.CompletedProcess[str]],
) -> Iterator[None]:
    """Guarantee the shared database is back at head after a destructive test.

    ``test_migrations_round_trip`` downgrades the session-scoped container. If
    it fails midway the database is left at ``base`` and every later test in the
    session fails for an unrelated reason, hiding the real failure.
    """
    try:
        yield
    finally:
        alembic("upgrade", "head")
```
The new drift test MUST also depend on `restore_schema` (or an equivalent that re-upgrades to
head in a `finally`), for exactly the reason stated in its docstring.

**pytest marker convention** (`pyproject.toml` `[tool.pytest.ini_options]`):
```toml
markers = [
    "integration: test requires a live Postgres container (deselect with -m 'not integration')",
    "realfile: test requires the user's gitignored export.xml at the repo root (deselect with -m 'not realfile')",
]
```
The new drift-rehearsal test must carry `@pytest.mark.integration`, matching every other
container-backed test in this suite, and must NOT be collapsed into the fast-suite static
assertion living in `test_cloud_run_deploy.py` (D-04's explicit instruction).

---

### Extracted pre-flight predicate (planner's discretion: shell function vs. small Python helper)

**Analog for the Python-helper option:** `backend/migrations/env.py` — shows the project's
established way to run an async alembic-adjacent check without a live `gcloud` binary, using
`config.set_main_option` / `context.configure` idioms already proven in this repo (lines 43,
64-76). If the predicate is Python, it likely shells out to `python -m alembic current` /
`python -m alembic heads` via `subprocess.run`, exactly matching the `alembic` fixture's own
`subprocess.run([sys.executable, "-m", "alembic", *args], ...)` shape in `conftest.py` (lines
279-286) — do not reimplement alembic's revision-resolution logic by hand; shell out to the
same CLI the fixture and the deploy script already trust.

**Analog for the shell-function option:** `scripts/deploy-cloud-run.sh`'s own existing
`${VAR:?...}`/`${VAR:-...}` variable block (lines 13-25) and `scripts/deploy-sync-job.sh`'s
comment-above-the-command convention (lines 20-22, 27-30) — a shell function
(`assert_migrations_current` or similar) defined near the top of `deploy-cloud-run.sh`, called
once before the `exec gcloud run deploy` line, with the new integration test invoking it via
`subprocess.run(["bash", "-c", "source scripts/deploy-cloud-run.sh; ..."])` or by extracting it
into its own sourceable file if that proves easier to test in isolation. CONTEXT.md leaves the
exact boundary to the planner, "informed by which is easier to unit-test without a live
`gcloud` binary" — note that BOTH options only need `alembic` (not `gcloud`) to run, since D-01
through D-02's logic is entirely about comparing `alembic current` to `alembic heads`, which is
why the Python-helper option composes more directly with the existing `alembic` pytest fixture.

## Shared Patterns

### Requirement-id-cited failure messages
**Source:** `backend/tests/test_cloud_run_deploy.py` (every assertion in the file, e.g. lines
232-237, 314-317, 358-365)
**Apply to:** every new assertion in both the static test file and the new integration test —
format is `f"{REQ-ID} violated: {what is wrong}; {why it is dangerous / what incident it
prevents}"`.

### `${VAR:?required}` / `${VAR:-default}` shape for new script variables
**Source:** `scripts/deploy-cloud-run.sh` lines 16-24, `scripts/deploy-sync-job.sh` lines 23-25,
31-34
**Apply to:** the new `DATABASE_URL`-fetch override (D-06) and any other new configurable value
the migration step introduces.

### Comment-above-the-command, never inside a backslash continuation
**Source:** `scripts/deploy-cloud-run.sh` lines 27-43 (the load-bearing example) and its guard
test `test_deploy_script_has_no_comment_inside_the_gcloud_call` (lines 264-302)
**Apply to:** every comment added to `deploy-cloud-run.sh` in this phase, including any
documenting the new alembic pre-flight block.

### Read-as-text, never-execute, for deploy-script tests
**Source:** `backend/tests/test_cloud_run_deploy.py` module docstring (lines 21-24) and
`_deploy_script_text()` (lines 89-91)
**Apply to:** any new static assertion added to this file for the migration-step ordering
check — must parse text, never shell out to the real script.

### Real-Postgres-only testing for schema/migration behavior
**Source:** `backend/tests/test_migrations.py` module docstring (lines 1-6), `conftest.py`'s
`postgres_url`/`alembic`/`restore_schema` fixtures (lines 248-304)
**Apply to:** the new drift-rehearsal integration test — SQLite is explicitly disallowed
project-wide for anything touching migrations or schema (`TIMESTAMPTZ`, `information_schema`,
UUID types diverge).

### `alembic` invoked as a subprocess via its own CLI, never in-process
**Source:** `backend/tests/conftest.py` `postgres_url` (lines 258-266) and `alembic` fixture
(lines 279-286); `backend/migrations/env.py` module docstring ("Alembic is invoked with
cwd=backend, but as a subprocess... make the dependency explicit")
**Apply to:** both the deploy script's new pre-flight step (`(cd backend && uv run alembic
upgrade head)`, matching CONTEXT.md's "Established Patterns" note) and the extracted predicate,
whichever boundary the planner chooses.

## No Analog Found

None. Every file this phase touches or creates has a direct, exact-match analog already in the
codebase — this phase is explicitly scoped to modifying one existing script and extending two
existing/sibling test files, not introducing a new architectural surface.

## Metadata

**Analog search scope:** `scripts/`, `backend/tests/`, `backend/migrations/`, `backend/app/`
(config, cli) — per CONTEXT.md's canonical references; no broader codebase search was needed
since CONTEXT.md names every relevant file explicitly.
**Files scanned:** `scripts/deploy-cloud-run.sh`, `scripts/deploy-sync-job.sh`,
`backend/tests/test_cloud_run_deploy.py`, `backend/tests/test_migrations.py`,
`backend/tests/conftest.py`, `backend/alembic.ini`, `backend/migrations/env.py`,
`backend/app/config.py`, `backend/app/cli.py`, `pyproject.toml` (pytest markers).
**Pattern extraction date:** 2026-09-07
