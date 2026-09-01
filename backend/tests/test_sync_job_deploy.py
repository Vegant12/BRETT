"""Hevy sync job deploy artifacts <-> Settings drift guard (D-10, DEPLOY-03).

The sibling of `test_cloud_run_deploy.py`, for the second workload. The failures it
catches are the same shape and just as silent: the job deploys green, the schedule
fires green, and the only symptom of a wrong env key or an unbound secret is that
data quietly stops being fresh -- which is exactly the condition the coaching layer
is supposed to detect rather than be caused by.

The helper functions below are DUPLICATED from `test_cloud_run_deploy.py` rather
than imported: test modules in this repo do not import each other, and a shared
fixture module would hide which artifact a given assertion actually read.

`--set-secrets` is read as text rather than executed: running either script would
deploy.
"""

import re
from pathlib import Path

import pytest
import yaml

from app.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
JOB_ENV_FILE = REPO_ROOT / "deploy" / "sync-job.env.yaml"
JOB_SCRIPT = REPO_ROOT / "scripts" / "deploy-sync-job.sh"
SCHEDULE_SCRIPT = REPO_ROOT / "scripts" / "create-sync-schedule.sh"

# PYTHONPATH is consumed by the interpreter, not by Settings. `backend/` is the import
# root (see pytest `pythonpath`), and `python -m app.cli` has no --app-dir equivalent.
_JOB_RUNTIME_VARS = frozenset({"PYTHONPATH"})

# Any env var whose NAME matches one of these must never appear in the job env file.
_SECRET_NAME_MARKERS = ("SECRET", "KEY", "TOKEN", "PASSWORD", "DATABASE_URL")

# A Secret Manager reference, never a literal: `name:latest` or `name:3`.
_SECRET_REF = re.compile(r"^[a-z0-9-]+:(latest|[0-9]+)$")

_SET_SECRETS_ARG = re.compile(r'--set-secrets="([^"]*)"')

# Dropping any one of these silently changes where, how, or as whom the job runs.
_REQUIRED_JOB_FLAGS = (
    "--source",
    "--region",
    "--project",
    "--service-account",
    "--env-vars-file",
    "--set-secrets",
    "--command",
    "--args",
    "--task-timeout",
    "--max-retries",
)

# Flags that belong to a Cloud Run SERVICE, or that would undo the env file. Mapped to
# the consequence rather than listed bare: a future reader hitting one of these needs
# to know why it is wrong here, not merely that it is.
_FORBIDDEN_JOB_FLAGS = {
    "--allow-unauthenticated": (
        "T-07-20 violated: a job has no ingress to open; the flag belongs to a "
        "service, and reaching for it here means the workload shape is wrong"
    ),
    "--set-env-vars": (
        "DEPLOY-03 violated: it removes every existing environment variable before "
        "adding its own, silently wiping everything --env-vars-file supplies, "
        "PYTHONPATH included -- the job then dies with "
        "ModuleNotFoundError: No module named 'app'"
    ),
    "--add-cloudsql-instances": (
        "D-06b violated: the database is Neon, reached over ordinary public egress -- "
        "Cloud SQL is not part of this architecture"
    ),
    "--vpc-connector": (
        "D-06b violated: the database is Neon, reached over ordinary public egress -- "
        "a VPC connector is not part of this architecture"
    ),
}

# Instance-scaling flags, matched WITH the `=` on purpose: a bare "--max" substring
# would also match the job's legitimate `--max-retries`, which is a required flag.
_FORBIDDEN_SCALING_FLAGS = ("--min=", "--max=")

# The invocation this whole plan exists to schedule. `app.cli` is the link from the
# deploy script to backend/app/cli.py; without it the job runs the buildpack's web
# entrypoint and serves HTTP nobody calls instead of syncing.
_JOB_COMMAND_ARGS = "--args=-m,app.cli,sync-hevy"

_JOB_DEFAULT = re.compile(r'JOB="\$\{BRETT_SYNC_JOB:-([a-z0-9-]+)\}"')
_RUN_URI_ASSIGNMENT = re.compile(r'RUN_URI="([^"]*)"')
_CRON_DEFAULT = re.compile(r'SCHEDULE="\$\{BRETT_SYNC_CRON:-([^}]*)\}"')
_TZ_DEFAULT = re.compile(r'TIME_ZONE="\$\{BRETT_SYNC_TZ:-([^}]*)\}"')


@pytest.fixture(scope="module")
def job_env_file() -> dict[str, str]:
    return yaml.safe_load(JOB_ENV_FILE.read_text())


def _settings_env_names() -> set[str]:
    """Every environment-variable name ``Settings`` will actually read.

    Matching on the lowercased field name alone is not enough: the Host allowlist
    field is ``mcp_allowed_hosts_raw`` but its env var is ``MCP_ALLOWED_HOSTS`` via
    ``validation_alias``, so a naive name-based check reports false drift.
    """
    names: set[str] = set()
    for name, field in Settings.model_fields.items():
        names.add(name.upper())
        alias = field.validation_alias
        if isinstance(alias, str):
            names.add(alias.upper())
    return names


def _secret_bindings() -> dict[str, str]:
    """``{ENV_NAME: SECRET_REF}`` parsed out of the job script's ``--set-secrets``.

    Read as text rather than executed: running the script would deploy.
    """
    match = _SET_SECRETS_ARG.search(JOB_SCRIPT.read_text())
    assert match is not None, (
        "DEPLOY-03 violated: scripts/deploy-sync-job.sh passes no quoted --set-secrets "
        "argument, so DATABASE_URL and HEVY_API_KEY would both be unbound and the "
        "scheduled sync would die at boot every six hours, forever, unwatched"
    )

    bindings: dict[str, str] = {}
    for pair in match.group(1).split(","):
        if not pair.strip():
            continue
        name, _, reference = pair.strip().partition("=")
        bindings[name] = reference
    return bindings


def test_job_env_file_parses_to_a_flat_string_mapping() -> None:
    """A nested or non-string value makes gcloud reject the whole file."""
    parsed = yaml.safe_load(JOB_ENV_FILE.read_text())

    assert isinstance(parsed, dict), (
        f"DEPLOY-03 violated: {JOB_ENV_FILE} is not a YAML mapping; --env-vars-file "
        f'requires a flat KEY: "value" mapping and rejects anything else'
    )
    for key, value in parsed.items():
        assert isinstance(key, str), (
            f"DEPLOY-03 violated: {JOB_ENV_FILE} has a non-string key {key!r}; "
            f"environment variable names must be plain strings"
        )
        assert isinstance(value, str), (
            f"DEPLOY-03 violated: {JOB_ENV_FILE} maps {key} to a "
            f"{type(value).__name__}; every value must be a quoted string or gcloud "
            f"rejects the file and the job keeps running its previous revision"
        )


def test_every_job_env_var_maps_to_a_settings_field_or_is_a_runtime_var(
    job_env_file: dict[str, str],
) -> None:
    """A key Settings does not read is ignored, not rejected -- hence this test.

    ``PYTHONPATH`` is the one legitimate exception: the interpreter consumes it
    before ``Settings`` is ever constructed, and without it ``python -m app.cli``
    cannot import ``app`` at all.
    """
    known = _settings_env_names()

    for key in job_env_file:
        if key in _JOB_RUNTIME_VARS:
            continue
        assert key in known, (
            f"DEPLOY-03 violated: deploy/sync-job.env.yaml sets {key} but Settings has "
            f"no such field, and it is not in _JOB_RUNTIME_VARS. extra='ignore' means "
            f"the job silently ignores it, so the deploy succeeds and the "
            f"misconfiguration only surfaces as data that stops being fresh"
        )


def test_no_credential_shaped_key_is_present_in_the_job_env_file(
    job_env_file: dict[str, str],
) -> None:
    """T-07-17: on Cloud Run the rule is 'not present at all', not 'no literal value'.

    ``--env-vars-file`` has no ``sync: false``/``generateValue`` escape hatch --
    every value in it is a literal -- so a credential-shaped key here can only be a
    committed secret, and ``HEVY_API_KEY`` is the exact name most likely to be
    pasted in by someone trying to make a failing job start.
    """
    for key in job_env_file:
        offending = [marker for marker in _SECRET_NAME_MARKERS if marker in key]
        assert not offending, (
            f"T-07-17 violated: deploy/sync-job.env.yaml declares {key}, whose name "
            f"matches {offending}. Any value here is a literal committed to git "
            f"forever, which no later commit can undo; bind it through --set-secrets "
            f"in scripts/deploy-sync-job.sh instead"
        )


def test_job_script_carries_every_required_flag() -> None:
    """A flag dropped during an edit changes where, how, or as whom the sync runs."""
    script = JOB_SCRIPT.read_text()

    assert "gcloud run jobs deploy" in script, (
        "DEPLOY-03 violated: scripts/deploy-sync-job.sh no longer runs `gcloud run "
        "jobs deploy`. A `gcloud run deploy` here would create a second always-on "
        "SERVICE that Cloud Scheduler's :run call cannot trigger at all"
    )
    for flag in _REQUIRED_JOB_FLAGS:
        assert flag in script, (
            f"DEPLOY-03 violated: scripts/deploy-sync-job.sh no longer passes {flag}; "
            f"this script is the single reproducible description of how the Hevy sync "
            f"runs in production (D-10), so a missing flag silently changes it"
        )
    assert _JOB_COMMAND_ARGS in script, (
        f"DEPLOY-03 violated: scripts/deploy-sync-job.sh no longer passes "
        f"{_JOB_COMMAND_ARGS!r}. The Procfile declares only a `web` process, so "
        f"without this override the job starts uvicorn and serves HTTP nobody calls "
        f"instead of running backend/app/cli.py's sync-hevy command"
    )


def test_job_binds_hevy_and_database_secrets_as_secret_manager_references() -> None:
    """T-07-18/T-07-19: a literal right-hand side is a committed secret.

    The binding set is asserted EXACTLY, not as a subset: ``MCP_AUTH_SECRET`` must
    stay out of it so a compromised sync task cannot read or mint the connector
    credential (T-07-19).

    The failure messages deliberately do NOT echo the offending value -- doing so
    would print the credential into CI output, which is the same mistake
    ``hide_input_in_errors=True`` exists to prevent in ``Settings``.
    """
    bindings = _secret_bindings()

    assert set(bindings) == {"DATABASE_URL", "HEVY_API_KEY"}, (
        f"T-07-19 violated: scripts/deploy-sync-job.sh binds {sorted(bindings)} but "
        f"must bind exactly ['DATABASE_URL', 'HEVY_API_KEY']. The sync needs no other "
        f"credential, and every extra binding widens what a compromised task can read"
    )
    for name, reference in bindings.items():
        assert _SECRET_REF.match(reference), (
            f"T-07-18 violated: --set-secrets binds {name} to something that is not a "
            f"Secret Manager reference (expected `secret-name:latest` or "
            f"`secret-name:VERSION`). If that is a credential literal it is now in git "
            f"history, which no later commit can undo"
        )


def test_job_env_file_and_secret_bindings_partition_the_environment(
    job_env_file: dict[str, str],
) -> None:
    """Cloud Run rejects a job that binds one name twice, and boots without a missing one."""
    bindings = _secret_bindings()

    overlap = sorted(set(job_env_file) & set(bindings))
    assert not overlap, (
        f"DEPLOY-03 violated: {overlap} appears both in deploy/sync-job.env.yaml and "
        f"in --set-secrets; Cloud Run rejects a deploy that binds one name in both "
        f"places, so the job would keep running its previous revision"
    )

    for required in ("DATABASE_URL", "HEVY_API_KEY"):
        assert required in bindings, (
            f"T-07-17 violated: {required} is not bound by --set-secrets. It is a "
            f"credential, so Secret Manager is its only legitimate source -- it must "
            f"never move into deploy/sync-job.env.yaml"
        )

    supplied = set(job_env_file) | set(bindings)
    for name, field in Settings.model_fields.items():
        if not field.is_required():
            continue
        alias = field.validation_alias
        env_name = alias.upper() if isinstance(alias, str) else name.upper()
        assert env_name in supplied, (
            f"DEPLOY-03 violated: Settings.{name} is required and has no default, but "
            f"neither deploy/sync-job.env.yaml nor --set-secrets supplies {env_name}; "
            f"every scheduled execution would die at boot with a pydantic "
            f"ValidationError that nobody is watching for"
        )


def test_job_script_avoids_service_only_and_dangerous_flags() -> None:
    """Flags that either do not apply to a job or quietly undo the env file."""
    script = JOB_SCRIPT.read_text()

    for flag, consequence in _FORBIDDEN_JOB_FLAGS.items():
        assert flag not in script, (
            f"scripts/deploy-sync-job.sh passes {flag}. {consequence}"
        )
    for flag in _FORBIDDEN_SCALING_FLAGS:
        assert flag not in script, (
            f"DEPLOY-03 violated: scripts/deploy-sync-job.sh passes {flag}; a Cloud "
            f"Run job has tasks, not instances, and gcloud rejects the flag. Use "
            f"--tasks and --max-retries, which bound stacking executions (T-07-21)"
        )


def test_the_schedule_targets_the_job_this_script_deploys() -> None:
    """A schedule pointing at a job name nothing deploys fails silently on a timer."""
    job_match = _JOB_DEFAULT.search(JOB_SCRIPT.read_text())
    schedule_match = _JOB_DEFAULT.search(SCHEDULE_SCRIPT.read_text())

    assert job_match is not None, (
        'DEPLOY-03 violated: scripts/deploy-sync-job.sh has no JOB="${BRETT_SYNC_JOB:-'
        '...}" default, so there is no name for create-sync-schedule.sh to agree with'
    )
    assert schedule_match is not None, (
        'DEPLOY-03 violated: scripts/create-sync-schedule.sh has no JOB="${BRETT_SYNC_'
        'JOB:-...}" default, so it cannot be checked against the job actually deployed'
    )

    deployed, scheduled = job_match.group(1), schedule_match.group(1)
    assert deployed == scheduled, (
        f"D-10 violated: scripts/deploy-sync-job.sh deploys {deployed!r} but "
        f"scripts/create-sync-schedule.sh triggers {scheduled!r}. Cloud Scheduler "
        f"would POST to a job that does not exist and the only symptom would be data "
        f"that stops being fresh"
    )

    uri_match = _RUN_URI_ASSIGNMENT.search(SCHEDULE_SCRIPT.read_text())
    assert uri_match is not None, (
        "D-10 violated: scripts/create-sync-schedule.sh assigns no RUN_URI; the "
        "scheduler needs the Run Admin API :run endpoint to start an execution"
    )
    uri = uri_match.group(1)
    assert uri.endswith(":run"), (
        f"D-10 violated: the scheduler URI is {uri!r}, which does not end in ':run'. "
        f"Only the Run Admin API's :run endpoint starts a job execution; any other "
        f"path returns a 2xx or a 404 that Cloud Scheduler reports as a plain failure"
    )
    assert "jobs/${JOB}:run" in uri, (
        f"D-10 violated: the scheduler URI {uri!r} does not interpolate the JOB "
        f"variable, so the job name agreed on above is not the one actually triggered"
    )


def test_the_schedule_runs_at_least_every_six_hours() -> None:
    """Blueprint 38 asks for a sync every 1-6 hours, in the user's own timezone."""
    script = SCHEDULE_SCRIPT.read_text()

    cron_match = _CRON_DEFAULT.search(script)
    assert cron_match is not None, (
        'D-10 violated: scripts/create-sync-schedule.sh has no SCHEDULE="${BRETT_SYNC_'
        'CRON:-...}" default, so the cadence is whatever the operator last typed'
    )
    assert cron_match.group(1) == "0 */6 * * *", (
        f"D-10 violated: the default cron is {cron_match.group(1)!r}, not '0 */6 * * "
        f"*'. Blueprint 38 asks for a sync every 1-6 hours; a slower cadence makes the "
        f"freshness the coaching layer reports permanently worse than it needs to be"
    )

    tz_match = _TZ_DEFAULT.search(script)
    assert tz_match is not None, (
        'D-10 violated: scripts/create-sync-schedule.sh has no TIME_ZONE="${BRETT_SYNC'
        '_TZ:-...}" default, so Cloud Scheduler falls back to UTC'
    )
    assert tz_match.group(1) == "Asia/Jakarta", (
        f"D-10 violated: the default time zone is {tz_match.group(1)!r}, not "
        f"'Asia/Jakarta'. The analytics layer buckets by local Monday-start weeks, so "
        f"a UTC-scheduled sync lands at four arbitrary local times and makes 'when was "
        f"this last synced' harder to reason about than it needs to be"
    )
