"""DEPLOY-04: an importable predicate that verifies a database is at the alembic head.

Production drifted behind deployed code three separate times during v2.0, each caught only
during live verification rather than by anything automated:

- Phase 8: `alembic current` was `0004` while the deployed code needed `0005`.
- The Phase 9 operator run: a shell was pointed at the wrong `DATABASE_URL`, showing a stale
  before-state and hiding the real drift.
- The Phase 13 spike: `0005` vs `0006` surfaced live as
  `UndefinedTableError: relation "user_program_history" does not exist`.

This module closes that gap by extracting the pre-flight check into a testable predicate rather
than leaving it as inline shell a developer could forget to invoke correctly, or as an ad-hoc
manual runbook nobody re-runs on the next change. Invoke it as:

    DATABASE_URL=<url> PYTHONPATH=backend uv run python -m app.db.migration_preflight

This module VERIFIES and never applies. `scripts/deploy-cloud-run.sh` runs `alembic upgrade
head` itself (D-01) immediately before calling this module; this module is the independent
confirmation that the upgrade actually landed (D-02) -- trusting the upgrade command's exit
code alone is exactly what D-02 forbids, because a partial or silently-incomplete apply can
still exit 0.
"""

import os
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.engine import make_url

from app.logging import REDACTED

# `migration_preflight.py` lives at `backend/app/db/migration_preflight.py`; `parents[2]` is
# `backend/`, matching the `alembic` fixture's own `cwd=BACKEND_DIR` in `tests/conftest.py`.
BACKEND_DIR = Path(__file__).resolve().parents[2]

# Alembic writes its `INFO  [alembic.runtime.migration] ...` banner to stderr, but a
# misconfigured logging handler could put it on stdout; a banner word must never be mistaken
# for a revision id.
_LOG_LEVEL_TOKENS = frozenset({"INFO", "WARNING", "ERROR", "DEBUG", "CRITICAL"})

# `0006 (head)` -> `0006`. Revision ids in this repo are zero-padded numerals, but the pattern
# stays generic so a future hash-style id still parses.
_REVISION_TOKEN = re.compile(r"^([0-9A-Za-z_]+)(?:\s|$)")

AlembicRunner = Callable[..., "subprocess.CompletedProcess[str]"]


@dataclass(frozen=True)
class PreflightResult:
    """The outcome of comparing `alembic current` against `alembic heads`."""

    ok: bool
    current: frozenset[str]
    heads: frozenset[str]
    detail: str


def parse_revisions(output: str) -> set[str]:
    """Extract revision ids from `alembic current`/`alembic heads` stdout.

    Skips blank lines and alembic's own `INFO  [alembic.runtime.migration] ...` log banner
    (recognized by its leading log-level token), rather than raising on unrecognized lines --
    alembic's exact stdout formatting is not this module's contract to enforce.
    """
    revisions: set[str] = set()
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        first_token = stripped.split(None, 1)[0]
        if first_token in _LOG_LEVEL_TOKENS:
            continue
        match = _REVISION_TOKEN.match(stripped)
        if match:
            revisions.add(match.group(1))
    return revisions


def redact(text: str, database_url: str) -> str:
    """Replace `database_url` and its password (if any) in `text` with `REDACTED`.

    Mirrors `Settings.secret_values`'s documented ordering rule: sorted longest-first so a
    scrubber replacing sequentially removes the full DB URL before it removes the bare password
    substring inside it. A malformed URL must not crash the redactor -- this runs on the error
    path, where alembic's own stderr is the thing most likely to be surfaced verbatim.
    """
    if not database_url:
        return text
    secrets = [database_url]
    try:
        password = make_url(database_url).password
        if password:
            secrets.append(password)
    except Exception:  # noqa: S110 - a non-URL DATABASE_URL is fine here, just skip the password
        pass
    scrubbed = text
    for secret in sorted(secrets, key=len, reverse=True):
        if secret:
            scrubbed = scrubbed.replace(secret, REDACTED)
    return scrubbed


def build_runner(database_url: str) -> AlembicRunner:
    """Return a callable that runs `alembic` against `database_url`.

    Mirrors `tests/conftest.py`'s `alembic` fixture exactly: does not raise on a nonzero exit,
    because a raised `CalledProcessError` would hide the alembic output that explains the drift.
    """

    def _run(*args: str) -> "subprocess.CompletedProcess[str]":
        return subprocess.run(  # noqa: S603
            [sys.executable, "-m", "alembic", *args],
            cwd=BACKEND_DIR,
            env={**os.environ, "DATABASE_URL": database_url},
            capture_output=True,
            text=True,
        )

    return _run


def check_at_head(run: AlembicRunner, *, database_url: str = "") -> PreflightResult:
    """The pre-flight predicate: is this database's current revision the migrations head?

    `database_url` is used only for redaction of any DSN/password that leaks into alembic's
    stdout/stderr on a failure path -- the caller already owns the connection via `run`.
    """
    current = run("current")
    if current.returncode != 0:
        return PreflightResult(
            ok=False,
            current=frozenset(),
            heads=frozenset(),
            detail=redact(
                "alembic current failed: " + current.stdout + current.stderr, database_url
            ),
        )

    heads = run("heads")
    if heads.returncode != 0:
        return PreflightResult(
            ok=False,
            current=frozenset(),
            heads=frozenset(),
            detail=redact("alembic heads failed: " + heads.stdout + heads.stderr, database_url),
        )

    current_revs = parse_revisions(current.stdout)
    head_revs = parse_revisions(heads.stdout)
    # The `bool(head_revs)` guard is load-bearing: with no migrations resolvable (broken
    # `script_location`, wrong cwd, alembic not installed), `set() == set()` would report a
    # stale database as in sync instead of failing closed.
    ok = bool(head_revs) and current_revs == head_revs

    if ok:
        detail = f"at head: {sorted(head_revs)}"
    else:
        detail = (
            f"DEPLOY-04 violated: the database is at {sorted(current_revs) or 'no revision'} "
            f"but the migrations head is {sorted(head_revs) or 'unresolvable'}; deploying now "
            f"would run application code against a schema it does not match (this is exactly "
            f"the Phase 13 UndefinedTableError). Run `alembic upgrade head` against this "
            f"database and re-run the pre-flight."
        )

    return PreflightResult(
        ok=ok,
        current=frozenset(current_revs),
        heads=frozenset(head_revs),
        detail=detail,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Entrypoint for `python -m app.db.migration_preflight`.

    `argv` exists only so tests can call `main([])` deterministically; no flags are read.
    """
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        print(
            "DEPLOY-04 violated: DATABASE_URL is unset, so the migration pre-flight has no "
            "database to verify. scripts/deploy-cloud-run.sh resolves it from `gcloud secrets "
            'versions access latest --secret=brett-database-url`.',
            file=sys.stderr,
        )
        return 1

    result = check_at_head(build_runner(database_url), database_url=database_url)
    if result.ok:
        print(result.detail)
        return 0
    print(result.detail, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
