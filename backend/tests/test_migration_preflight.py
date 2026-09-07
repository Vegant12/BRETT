"""DEPLOY-04: a database behind the migrations head must never be silently deployed to.

These tests exist because production drifted behind deployed code three separate times during
v2.0 (Phase 8's `0004` vs `0005`, the Phase 9 operator run against the wrong `DATABASE_URL`, and
the Phase 13 spike's `0005` vs `0006` surfacing as `UndefinedTableError`), and each time the only
thing that caught it was live verification after the fact. Nothing in the deploy pipeline
compared the running schema to the migrations head before deploying, so a silently-stale
database was indistinguishable from a healthy one until a query hit a column or table that did
not exist yet.

The tests below cover `parse_revisions`, `redact` and `check_at_head` against a fake runner --
no container, no network. A drift-rehearsal integration test against a REAL Postgres container
is added separately: a predicate that only ever sees fabricated strings could pass while still
being wrong about what `alembic current`/`alembic heads` actually print.
"""

import os
import subprocess
import sys
from collections.abc import Callable

import pytest
from sqlalchemy.engine import make_url

from app.db.migration_preflight import (
    check_at_head,
    main,
    parse_revisions,
    redact,
)
from tests.conftest import BACKEND_DIR


def _fake_runner(
    responses: dict[str, "subprocess.CompletedProcess[str]"],
) -> Callable[..., "subprocess.CompletedProcess[str]"]:
    """A local stand-in for `build_runner`'s subprocess closure, keyed on the alembic verb."""

    def _run(*args: str) -> "subprocess.CompletedProcess[str]":
        return responses[args[0]]

    return _run


def _completed(
    *, returncode: int = 0, stdout: str = "", stderr: str = ""
) -> "subprocess.CompletedProcess[str]":
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


# ---------------------------------------------------------------------------
# parse_revisions
# ---------------------------------------------------------------------------


def test_parse_revisions_single_head() -> None:
    assert parse_revisions("0006 (head)\n") == {"0006"}


def test_parse_revisions_empty_output_means_no_alembic_version_row() -> None:
    """An empty string is what `alembic current` prints against a bare database."""
    assert parse_revisions("") == set()


def test_parse_revisions_behind_head_has_no_marker() -> None:
    assert parse_revisions("0005\n") == {"0005"}


def test_parse_revisions_discards_log_noise_on_stdout() -> None:
    """A misconfigured logging handler could route alembic's INFO banner to stdout instead of
    stderr; a banner word must never be mistaken for a revision id."""
    output = "INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.\n0006 (head)\n"
    assert parse_revisions(output) == {"0006"}


def test_parse_revisions_multiple_heads() -> None:
    assert parse_revisions("0006 (head)\n0007 (head)\n") == {"0006", "0007"}


# ---------------------------------------------------------------------------
# redact
# ---------------------------------------------------------------------------


def test_redact_removes_full_dsn_and_bare_password() -> None:
    url = "postgresql://u:sw0rdf1sh@db.example/x"
    text = f"connect failed: {url}"
    scrubbed = redact(text, url)
    assert "sw0rdf1sh" not in scrubbed
    assert "db.example" not in scrubbed
    assert "***REDACTED***" in scrubbed


def test_redact_replaces_bare_password_longest_first() -> None:
    """The full URL is replaced before the bare password substring inside it, matching
    `Settings.secret_values`'s documented ordering rule."""
    url = "postgresql://u:sw0rdf1sh@db.example/x"
    scrubbed = redact("password was sw0rdf1sh", url)
    assert "sw0rdf1sh" not in scrubbed
    assert "***REDACTED***" in scrubbed


def test_redact_returns_text_unchanged_when_no_database_url() -> None:
    assert redact("no secrets here", "") == "no secrets here"


def test_redact_survives_a_malformed_url() -> None:
    """The redactor runs on the error path -- a malformed DATABASE_URL must not crash it."""
    scrubbed = redact("connect failed: not-a-url", "not-a-url")
    assert "***REDACTED***" in scrubbed


# ---------------------------------------------------------------------------
# check_at_head
# ---------------------------------------------------------------------------


def test_check_at_head_detects_drift() -> None:
    run = _fake_runner(
        {
            "current": _completed(stdout="0005\n"),
            "heads": _completed(stdout="0006 (head)\n"),
        }
    )
    result = check_at_head(run)
    assert result.ok is False
    assert result.current == frozenset({"0005"})
    assert result.heads == frozenset({"0006"})


def test_check_at_head_reports_ok_when_current_matches_head() -> None:
    run = _fake_runner(
        {
            "current": _completed(stdout="0006 (head)\n"),
            "heads": _completed(stdout="0006 (head)\n"),
        }
    )
    result = check_at_head(run)
    assert result.ok is True


def test_check_at_head_fails_closed_on_empty_head_set() -> None:
    """An empty head set (broken script_location, wrong cwd, alembic not installed) must never
    be read as 'in sync' just because both sides are equally empty."""
    run = _fake_runner(
        {
            "current": _completed(stdout=""),
            "heads": _completed(stdout=""),
        }
    )
    result = check_at_head(run)
    assert result.ok is False, (
        "DEPLOY-04 violated: an empty current/heads pair reported ok=True; this is a "
        "broken-alembic-invocation state, not a healthy one, and must fail closed"
    )


def test_check_at_head_redacts_the_dsn_on_a_failed_alembic_invocation() -> None:
    dsn = "postgresql://u:sw0rdf1sh@db.example/x"
    run = _fake_runner(
        {
            "current": _completed(returncode=1, stderr=f"connection failed: {dsn}"),
        }
    )
    result = check_at_head(run, database_url=dsn)
    assert result.ok is False
    assert dsn not in result.detail
    assert "sw0rdf1sh" not in result.detail


# ---------------------------------------------------------------------------
# main -- fast-suite coverage only; the real subprocess entrypoint is exercised against a
# container in the integration tests.
# ---------------------------------------------------------------------------


def test_main_returns_1_and_names_deploy_04_when_database_url_is_unset(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    exit_code = main([])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "DEPLOY-04" in captured.err


# ---------------------------------------------------------------------------
# Drift rehearsal: the same predicate, run against a REAL Postgres container
# deliberately downgraded one revision behind head -- the exact condition that broke
# production three times during v2.0. This is D-04's explicit requirement: a permanent
# regression test, not a one-off manual runbook that proves nothing on the next change.
# ---------------------------------------------------------------------------


def _preflight(url: str) -> "subprocess.CompletedProcess[str]":
    """The exact command `scripts/deploy-cloud-run.sh` will run in plan 14-02, invoked as a
    subprocess so its exit code -- the thing `set -euo pipefail` reacts to -- is what gets
    asserted here."""
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "app.db.migration_preflight"],
        cwd=BACKEND_DIR,
        env={**os.environ, "DATABASE_URL": url, "PYTHONPATH": BACKEND_DIR},
        capture_output=True,
        text=True,
    )


@pytest.mark.integration
def test_preflight_detects_a_database_one_revision_behind_head(
    alembic: Callable[..., "subprocess.CompletedProcess[str]"],
    restore_schema: None,
) -> None:
    """The Phase 13 incident, reproduced: `0005` applied, `0006` expected. This is the drift
    rehearsal -- a real database intentionally behind head, not a fixture."""
    assert alembic("upgrade", "head").returncode == 0
    assert check_at_head(alembic).ok is True  # baseline: at head means ok

    down = alembic("downgrade", "-1")
    assert down.returncode == 0, down.stderr

    drifted = check_at_head(alembic)
    assert drifted.ok is False, (
        "DEPLOY-04 violated: the pre-flight reported a database one revision behind head as "
        "in sync; this is exactly the state that shipped UndefinedTableError to production in "
        "Phase 13"
    )
    assert drifted.current == frozenset({"0005"})
    assert drifted.heads == frozenset({"0006"})
    assert "DEPLOY-04" in drifted.detail
    # `restore_schema` is DECLARED, not optional: this test downgrades the session-scoped
    # container and every later test in the session fails for an unrelated reason if it is
    # left behind.


@pytest.mark.integration
def test_preflight_passes_once_the_pending_migration_is_applied(
    alembic: Callable[..., "subprocess.CompletedProcess[str]"],
    restore_schema: None,
) -> None:
    """Proves the D-01 auto-apply actually clears the gate -- a detector that never returns to
    ok would block every deploy forever."""
    alembic("downgrade", "-1")
    assert check_at_head(alembic).ok is False

    assert alembic("upgrade", "head").returncode == 0
    result = check_at_head(alembic)
    assert result.ok is True
    assert "at head" in result.detail


@pytest.mark.integration
def test_preflight_module_entrypoint_exits_nonzero_on_drift_without_leaking_the_dsn(
    postgres_url: str,
    alembic: Callable[..., "subprocess.CompletedProcess[str]"],
    restore_schema: None,
) -> None:
    """The exact command the deploy script will run (plan 14-02), exercised as a real
    subprocess so its exit code is what `set -euo pipefail` reacts to."""
    alembic("upgrade", "head")
    assert _preflight(postgres_url).returncode == 0

    alembic("downgrade", "-1")
    drifted = _preflight(postgres_url)
    assert drifted.returncode == 1, (
        "DEPLOY-04 violated: the pre-flight entrypoint exited 0 against a drifted database; "
        "`set -euo pipefail` in scripts/deploy-cloud-run.sh would then let `gcloud run deploy` "
        "run against a stale schema"
    )
    combined = drifted.stdout + drifted.stderr
    assert "DEPLOY-04" in combined
    assert postgres_url not in combined
    if make_url(postgres_url).password:
        assert make_url(postgres_url).password not in combined
