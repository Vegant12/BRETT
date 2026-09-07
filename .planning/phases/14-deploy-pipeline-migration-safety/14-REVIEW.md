---
phase: 14-deploy-pipeline-migration-safety
reviewed: 2026-09-07T00:00:00Z
depth: standard
files_reviewed: 6
files_reviewed_list:
  - backend/app/db/migration_preflight.py
  - backend/tests/test_migration_preflight.py
  - scripts/deploy-cloud-run.sh
  - backend/tests/test_cloud_run_deploy.py
  - backend/tests/test_deploy_script_preflight.py
  - docs/runbook-deploy.md
findings:
  critical: 0
  warning: 2
  info: 2
  total: 4
status: issues_found
---

# Phase 14: Code Review Report

**Reviewed:** 2026-09-07
**Depth:** standard
**Files Reviewed:** 6
**Status:** issues_found

## Summary

This phase adds a genuinely well-engineered migration pre-flight gate: `migration_preflight.py`
is a small, pure predicate with fail-closed semantics (empty head set is never treated as "in
sync"), DSN/password redaction on every error path, and thorough unit + drift-rehearsal
integration coverage. `scripts/deploy-cloud-run.sh` correctly sequences DSN resolution → `alembic
upgrade head` → independent re-verification → `exec gcloud run deploy`, and the test suite goes
further than most deploy-safety tests by actually executing the script against a stubbed `gcloud`
and a real, deliberately-drifted Postgres container rather than only grepping the script as text.
No hardcoded secrets, injection vectors, or Critical-severity issues were found.

Two issues are worth fixing: a verified, real discrepancy between what `docs/runbook-deploy.md`
tells an operator to expect on an IAM/secret-access failure and what the script actually produces
under `set -e` (I confirmed this in a live bash test — see WR-01), and a missing subprocess
timeout that could turn a stalled database connection into a hung deploy pipeline with no
diagnostic output (WR-02). Two lower-severity robustness notes are also included (IN-01, IN-02).

## Warnings

### WR-01: Runbook's "DATABASE_URL resolved to an empty value" troubleshooting entry is unreachable for the causes it lists

**File:** `docs/runbook-deploy.md:97` (troubleshooting table), corresponding to `scripts/deploy-cloud-run.sh:49-56`

**Issue:** The runbook's troubleshooting table says the friendly message

```
DEPLOY-04: DATABASE_URL resolved to an empty value; gcloud secrets versions access latest
--secret=brett-database-url returned nothing and BRETT_DATABASE_URL is unset. Refusing to deploy.
```

is caused by "the secret has no accessible version, the deploying account lacks
`roles/secretmanager.secretAccessor`, or `BRETT_GCP_PROJECT` names the wrong project." I verified
with a live bash reproduction that this is not how the script actually behaves:

```bash
$ bash -c '
set -euo pipefail
foo() { return 1; }
VAR="${OVERRIDE:-$(foo)}"
echo "reached after assignment: VAR=$VAR"
'
echo "script exit code: $?"
# -> "reached after assignment" is never printed; script exit code: 1
```

Under `set -euo pipefail` (`scripts/deploy-cloud-run.sh:9`), when `gcloud secrets versions
access` exits non-zero — which is exactly what happens on `PERMISSION_DENIED` or `NOT_FOUND` for
a missing/inaccessible secret version, i.e. every cause the runbook lists — the assignment on
line 49 aborts the script immediately with `set -e`. Execution never reaches the `if [[ -z
"$DATABASE_URL" ]]` check on line 53, so the friendly custom message is never printed. What the
operator actually sees is gcloud's own raw stderr (e.g. `ERROR: (gcloud.secrets.versions.access)
PERMISSION_DENIED: ...`), with no `DEPLOY-04` prefix at all.

The custom empty-value message can only fire when `gcloud secrets versions access` *succeeds*
(exit 0) yet prints an empty string to stdout — a narrower and different failure mode than the
one documented (e.g., a secret whose latest version's payload is genuinely an empty string).

This matters because the runbook exists precisely so an operator under pressure recognizes the
symptom and jumps straight to the fix; as written, they will grep the runbook for a message they
will never see for the IAM/missing-secret causes it names, and waste time before realizing the
raw gcloud error is what they should have searched for instead.

**Fix:** Either update the runbook to describe the two distinct failure shapes, or make the
script produce one unified message by capturing the gcloud failure explicitly instead of relying
on `set -e`'s default behavior:

```bash
if ! DATABASE_URL="${BRETT_DATABASE_URL:-$(gcloud secrets versions access latest \
    --project="$PROJECT_ID" --secret="brett-database-url" 2>&1)}"; then
  echo "DEPLOY-04: failed to resolve DATABASE_URL from Secret Manager (brett-database-url). " \
       "This is an IAM permission or missing-secret-version issue, not an empty-value one. " \
       "gcloud said: $DATABASE_URL" >&2
  exit 1
fi
```
(Note: capturing stderr this way requires care not to also capture-and-leak the DSN if the
resolution *succeeds* — validate this doesn't reintroduce a leak path before adopting it.) At
minimum, update the runbook table to split this row into "gcloud command fails outright (IAM /
missing secret / wrong project) → raw gcloud error, no DEPLOY-04 prefix" versus "gcloud succeeds
with empty payload → the DEPLOY-04 empty-value message."

### WR-02: No timeout on alembic subprocess invocations — a stalled DB connection hangs the deploy pipeline indefinitely

**File:** `backend/app/db/migration_preflight.py:115-122` (`build_runner._run`); also
`scripts/deploy-cloud-run.sh:68,74` (the `uv run alembic upgrade head` and `uv run python -m
app.db.migration_preflight` invocations)

**Issue:** `subprocess.run` is called with no `timeout=`. The module's own docstring and the
runbook both emphasize failing loudly and fast (the whole point of DEPLOY-04 is to never let a
bad state pass silently), but if the database connection attempt stalls rather than being
immediately refused or erroring out — e.g. a firewall silently drops packets instead of sending
RST/ICMP-unreachable, or a lock is held open on `alembic_version` — `alembic current`/`alembic
upgrade head` can block for the OS-level TCP connect timeout (often minutes) or indefinitely if a
query is blocked on a lock. The deploy script and any CI/CD job wrapping it would then hang with
no diagnostic output at all, which is a worse operator experience than a fast, clear failure.

**Fix:**
```python
def _run(*args: str) -> "subprocess.CompletedProcess[str]":
    try:
        return subprocess.run(  # noqa: S603
            [sys.executable, "-m", "alembic", *args],
            cwd=BACKEND_DIR,
            env={**os.environ, "DATABASE_URL": database_url},
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            args=exc.cmd, returncode=1,
            stdout=exc.stdout or "", stderr=f"alembic timed out after {exc.timeout}s",
        )
```
Consider the same for the two `uv run` invocations in `scripts/deploy-cloud-run.sh` (e.g. via
`timeout 60 uv run ...`), so a stalled connection at the shell layer is caught the same way.

## Info

### IN-01: Log-banner filter recognizes only standard Python logging level names

**File:** `backend/app/db/migration_preflight.py:44`

**Issue:** `_LOG_LEVEL_TOKENS = frozenset({"INFO", "WARNING", "ERROR", "DEBUG", "CRITICAL"})` is
used by `parse_revisions` to skip alembic's log banner if it leaks onto stdout. This covers
Python's own `logging` level names, but not every logger's convention (e.g. `WARN` instead of
`WARNING`, or a banner from a different dependency in the alembic call chain). If such a line
ever appeared on stdout, its first token would not be recognized as a log-level token and would
be misparsed as a bogus revision id by `_REVISION_TOKEN`, causing `check_at_head` to report a
false drift. This fails closed (blocks a deploy rather than passing a bad state), which is the
safe direction, but it would produce a confusing false alarm rather than being silently ignored.

**Fix:** Low priority given the fail-closed direction, but consider also matching Python's
built-in `WARN` alias, or switching to a small allowlist regex anchored on the exact
`\[alembic\.` logger-name pattern actually seen in this codebase's alembic output, which is more
specific than matching on any leading log-level word.

### IN-02: `redact()` may not catch a percent-encoded password without the surrounding DSN

**File:** `backend/app/db/migration_preflight.py:84-105`

**Issue:** `redact()` builds its secrets list from the raw `database_url` string (matched
verbatim) and `make_url(database_url).password` (matched verbatim, but SQLAlchemy's `make_url`
URL-decodes the password component). If a password contains characters requiring percent-encoding
and some future error message echoes only the encoded password substring without the full DSN
around it, the decoded form used by `redact()` would not match that literal substring and the
password would leak. In the current codebase every code path that calls `redact()` also has the
full `database_url` available and replaces it first (which removes the encoded password too,
since it's embedded in the DSN), so this is not currently exploitable — it is only a latent gap
if a future caller passes a bare password-containing fragment through `redact()` without the full
URL.

**Fix:** No change required today; if this function is ever reused for a text fragment that
might contain only the encoded password, also add the URL-encoded form of the password to the
`secrets` list (e.g. via `urllib.parse.quote(password, safe="")`).

---

_Reviewed: 2026-09-07T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
