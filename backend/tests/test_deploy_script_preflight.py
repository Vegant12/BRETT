"""DEPLOY-04: rehearse the real `scripts/deploy-cloud-run.sh`, not just the predicate it calls.

Uniquely among the deploy-safety test files, this module EXECUTES `scripts/deploy-cloud-run.sh`
as a subprocess. `test_cloud_run_deploy.py` only reads the script as text -- its own module
docstring explains why that is sometimes not enough: `test_deploy_script_carries_every_required_
flag` greps the file as TEXT, so every flag it looks for is still present in a script that no
longer passes any of them. A static assertion proves the gate is WRITTEN DOWN; only executing the
script proves the gate RUNS. The comment-truncation hazard documented at
`scripts/deploy-cloud-run.sh:87-92` is the proven, concrete example of a script that could pass
every text assertion while running none of them -- a `#` comment between two backslash-continued
lines silently truncates the command, `bash -n` still reports the file as valid, and nothing
short of actually running the script would catch it.

This is safe because a recording stub named `gcloud` is prepended to `PATH` for every invocation
here, and `_run_deploy` asserts that stub is the one `shutil.which` resolves BEFORE the real
script is ever invoked -- failing loudly with "REFUSING TO RUN" otherwise. `scripts/deploy-cloud-
run.sh`'s last statement is `exec gcloud run deploy`, which replaces the shell process in place;
with the stub resolved first, that `exec` reaches the stub and never Google. `BRETT_GCP_PROJECT`
is additionally set to `brett-stub-project`, a project that does not exist, so even a stub-
resolution failure could not reach a real GCP project.

Plan 14-01 rehearsed the extracted predicate (`app.db.migration_preflight`) against a real
drifted Postgres container. This plan rehearses the SCRIPT that calls that predicate, against the
same kind of real, drifted container, with the same safety discipline `test_migration_preflight.py`
established: every destructive test declares `restore_schema` in its finally, and every
non-destructive test deliberately does not.
"""

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "deploy-cloud-run.sh"


@pytest.fixture
def gcloud_stub(tmp_path: Path) -> tuple[Path, Path]:
    """A recording `gcloud` that writes its argv to a log and exits 0.

    Every invocation is appended, so the abort assertions can prove `run deploy`
    was never reached rather than merely that the script exited non-zero.
    Prints nothing on stdout: `gcloud secrets versions access` therefore yields
    an empty value, which is precisely the case
    ``test_deploy_script_refuses_when_the_secret_resolves_empty`` needs.
    """
    log = tmp_path / "gcloud-invocations.log"
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    stub = stub_dir / "gcloud"
    stub.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$GCLOUD_STUB_LOG"\nexit 0\n')
    stub.chmod(0o755)
    return stub_dir, log


def _run_deploy(
    stub_dir: Path, log: Path, **overrides: str
) -> "subprocess.CompletedProcess[str]":
    env = {
        **os.environ,
        "PATH": f"{stub_dir}{os.pathsep}{os.environ['PATH']}",
        "GCLOUD_STUB_LOG": str(log),
        "BRETT_GCP_PROJECT": "brett-stub-project",
    }
    env.pop("BRETT_DATABASE_URL", None)
    env.update(overrides)
    # The safety interlock: if anything about PATH is wrong, this fails BEFORE
    # a real `gcloud run deploy` could ever be issued.
    resolved = shutil.which("gcloud", path=env["PATH"])
    assert resolved == str(stub_dir / "gcloud"), (
        f"REFUSING TO RUN: `gcloud` resolves to {resolved!r}, not the stub at "
        f"{stub_dir / 'gcloud'}; executing scripts/deploy-cloud-run.sh now would "
        f"attempt a real deploy"
    )
    return subprocess.run(  # noqa: S603
        ["bash", str(DEPLOY_SCRIPT)],  # noqa: S607 - "bash" is intentionally resolved via PATH
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


@pytest.mark.integration
def test_deploy_applies_a_pending_migration_then_deploys(
    alembic: Callable[..., "subprocess.CompletedProcess[str]"],
    restore_schema: None,
    postgres_url: str,
    gcloud_stub: tuple[Path, Path],
) -> None:
    """The Phase 13 incident, run through the REAL script: D-01's auto-apply, end to end."""
    assert alembic("upgrade", "head").returncode == 0
    down = alembic("downgrade", "-1")
    assert down.returncode == 0, down.stderr
    assert alembic("current").stdout.strip().startswith("0005"), (
        "the drift really exists before the script runs"
    )

    stub_dir, log = gcloud_stub
    result = _run_deploy(stub_dir, log, BRETT_DATABASE_URL=postgres_url)
    assert result.returncode == 0, result.stdout + result.stderr

    assert alembic("current").stdout.strip().endswith("(head)"), (
        "DEPLOY-04 violated: scripts/deploy-cloud-run.sh exited 0 but did not leave the "
        "database at head; D-01 requires the script to APPLY the pending migration, not "
        "merely detect it"
    )
    assert "run deploy" in log.read_text(), (
        "DEPLOY-04 violated: the script exited 0 but never reached `gcloud run deploy`"
    )
    assert "BRETT_DATABASE_URL override" in result.stdout, (
        "T-14-03 violated: the run did not announce which database it touched"
    )
    # `restore_schema` is DECLARED, not optional: this test downgrades the session-scoped
    # container and every later test in the session fails for an unrelated reason if it is
    # left behind.


@pytest.mark.integration
def test_deploy_aborts_before_gcloud_when_the_database_is_unreachable(
    postgres_url: str, gcloud_stub: tuple[Path, Path]
) -> None:
    """The exact v2.0 failure mode, proven absent: an unmigratable database must never reach
    `gcloud run deploy`.

    This test does NOT declare `restore_schema` or `alembic`: it never touches the real
    container's schema at all (the DSN it hands the script points at a closed port), and
    declaring the destructive fixtures would falsely couple this test to schema state it does
    not affect.
    """
    unreachable = make_url(postgres_url).set(port=1).render_as_string(hide_password=False)

    stub_dir, log = gcloud_stub
    result = _run_deploy(stub_dir, log, BRETT_DATABASE_URL=unreachable)
    assert result.returncode != 0

    log_text = log.read_text() if log.exists() else ""
    assert "run deploy" not in log_text, (
        "DEPLOY-04 violated: scripts/deploy-cloud-run.sh reached `gcloud run deploy` even "
        "though it could not migrate the database; this is the exact v2.0 failure mode -- code "
        "shipped against a schema that was never updated"
    )


@pytest.mark.integration
def test_deploy_is_idempotent_on_an_already_current_database(
    alembic: Callable[..., "subprocess.CompletedProcess[str]"],
    postgres_url: str,
    gcloud_stub: tuple[Path, Path],
) -> None:
    """A gate that false-alarms when there is nothing to apply gets disabled within a week.

    Proves the D-02 verification arm passes cleanly on a database already at head, across TWO
    consecutive deploys. This test does not downgrade, so it deliberately does NOT declare
    `restore_schema`, matching the reasoning in the unreachable-database test above.
    """
    assert alembic("upgrade", "head").returncode == 0

    stub_dir, log = gcloud_stub
    first = _run_deploy(stub_dir, log, BRETT_DATABASE_URL=postgres_url)
    second = _run_deploy(stub_dir, log, BRETT_DATABASE_URL=postgres_url)

    assert first.returncode == 0, first.stdout + first.stderr
    assert second.returncode == 0, second.stdout + second.stderr
    assert alembic("current").stdout.strip().endswith("(head)")
    assert log.read_text().count("run deploy") == 2, (
        "DEPLOY-04 violated: an already-current database did not reach `gcloud run deploy` on "
        "both repeated runs; a gate that false-alarms on a healthy database gets disabled "
        "within a week"
    )


@pytest.mark.integration
def test_deploy_refuses_when_the_secret_resolves_empty(
    gcloud_stub: tuple[Path, Path],
) -> None:
    """D-05: the script really does resolve the DSN from Secret Manager when no override is
    given, and refuses to deploy on an empty result rather than inheriting a stray shell value."""
    stub_dir, log = gcloud_stub
    result = _run_deploy(stub_dir, log)
    assert result.returncode != 0

    log_text = log.read_text()
    assert "secrets versions access latest" in log_text, (
        "DEPLOY-04 violated: the script did not attempt to resolve DATABASE_URL from Secret "
        "Manager when BRETT_DATABASE_URL was unset"
    )
    assert "run deploy" not in log_text, (
        "DEPLOY-04 violated: scripts/deploy-cloud-run.sh reached `gcloud run deploy` with an "
        "empty resolved DATABASE_URL"
    )
    combined = result.stdout + result.stderr
    assert "DEPLOY-04" in combined
