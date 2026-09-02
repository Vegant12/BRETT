"""Cloud Run deploy artifacts <-> Settings drift guard (DEPLOY-01).

These are tests rather than comments because every failure they catch is silent
and remote. ``gcloud`` reads ``deploy/cloud-run.env.yaml`` and
``scripts/deploy-cloud-run.sh`` verbatim, ``Settings.model_config`` sets
``extra="ignore"``, and Cloud Run then reports the deploy healthy -- so a key
that no longer corresponds to a real field is not an error at deploy time. The
service boots on the defaults and the only symptom surfaces much later as a
``421 Invalid Host header`` or a ``401``. The reverse drift is worse: a
credential-shaped key added to the env file is simply in git forever (T-02-10),
and Cloud Run offers no ``sync: false``/``generateValue`` escape hatch, so the
rule is stricter than the Render one this module replaces -- such a key must not
be present at all.

Two more failures live here because they are equally invisible until a deploy:
the ``Procfile`` is what lets Cloud Buildpacks find an entrypoint for a package
that lives in ``backend/`` (T-02-13's sibling), and ``.gcloudignore`` is the only
thing keeping ~490 MB of personal health exports out of a Cloud Storage build
bucket once any such file exists (T-02-11).

Static assertions over committed files: no container, no network, and
deliberately no integration marker -- drift must fail the fast suite on the
commit that introduces it, not after a deploy.
"""

import re
from pathlib import Path
from typing import get_args
from urllib.parse import urlsplit

import pytest
import yaml

from app.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / "deploy" / "cloud-run.env.yaml"
DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "deploy-cloud-run.sh"
PROCFILE = REPO_ROOT / "Procfile"
GCLOUDIGNORE = REPO_ROOT / ".gcloudignore"

# Injected by the Cloud Run platform, never by Settings.
_PLATFORM_VARS = frozenset({"PORT"})

# Any env var whose NAME matches one of these must never appear in the env file.
_SECRET_NAME_MARKERS = ("SECRET", "KEY", "TOKEN", "PASSWORD", "DATABASE_URL")

# A Secret Manager reference, never a literal: `name:latest` or `name:3`.
_SECRET_REF = re.compile(r"^[a-z0-9-]+:(latest|[0-9]+)$")

_SET_SECRETS_ARG = re.compile(r'--set-secrets="([^"]*)"')

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


@pytest.fixture(scope="module")
def env_file() -> dict[str, str]:
    return yaml.safe_load(ENV_FILE.read_text())


def _settings_env_names() -> set[str]:
    """Every environment-variable name ``Settings`` will actually read.

    Matching on the lowercased field name alone is not enough: the Host
    allowlist field is ``mcp_allowed_hosts_raw`` but its env var is
    ``MCP_ALLOWED_HOSTS`` via ``validation_alias``, so a naive name-based check
    would report a false drift for the one variable a 421 depends on.
    """
    names: set[str] = set()
    for name, field in Settings.model_fields.items():
        names.add(name.upper())
        alias = field.validation_alias
        if isinstance(alias, str):
            names.add(alias.upper())
    return names


def _deploy_script_text() -> str:
    """The deploy script as text. Read, never executed -- running it would deploy."""
    return DEPLOY_SCRIPT.read_text()


def _secret_bindings() -> dict[str, str]:
    """``{ENV_NAME: SECRET_REF}`` parsed out of the script's ``--set-secrets``.

    Read as text rather than executed: running the script would deploy.
    """
    match = _SET_SECRETS_ARG.search(DEPLOY_SCRIPT.read_text())
    assert match is not None, (
        "DEPLOY-01 violated: scripts/deploy-cloud-run.sh passes no quoted --set-secrets "
        "argument, so DATABASE_URL and MCP_AUTH_SECRET would be unbound at runtime"
    )

    bindings: dict[str, str] = {}
    for pair in match.group(1).split(","):
        if not pair.strip():
            continue
        name, _, reference = pair.strip().partition("=")
        bindings[name] = reference
    return bindings


def test_env_file_parses_to_a_flat_string_mapping() -> None:
    """A nested or non-string value makes gcloud reject the whole file."""
    parsed = yaml.safe_load(ENV_FILE.read_text())

    assert isinstance(parsed, dict), (
        f"DEPLOY-01 violated: {ENV_FILE} is not a YAML mapping; --env-vars-file requires a "
        f'flat KEY: "value" mapping and rejects anything else'
    )
    for key, value in parsed.items():
        assert isinstance(key, str), (
            f"DEPLOY-01 violated: {ENV_FILE} has a non-string key {key!r}; environment "
            f"variable names must be plain strings"
        )
        assert isinstance(value, str), (
            f"DEPLOY-01 violated: {ENV_FILE} maps {key} to a {type(value).__name__}; every "
            f"value must be a quoted string or gcloud rejects the file"
        )


def test_every_env_var_maps_to_a_settings_field(env_file: dict[str, str]) -> None:
    """A key Settings does not read is ignored, not rejected -- hence this test."""
    known = _settings_env_names()

    for key in env_file:
        if key in _PLATFORM_VARS:
            continue
        assert key in known, (
            f"DEPLOY-01 violated: deploy/cloud-run.env.yaml sets {key} but Settings has no "
            f"such field (extra='ignore' means the deployed service silently ignores it, so "
            f"the deploy succeeds and the misconfiguration surfaces much later)"
        )


def test_environment_value_is_a_valid_literal(env_file: dict[str, str]) -> None:
    """A value outside the Literal kills the process at boot, on Cloud Run, remotely."""
    value = env_file["ENVIRONMENT"]
    allowed = get_args(Settings.model_fields["environment"].annotation)

    assert value in allowed, (
        f"DEPLOY-01 violated: deploy/cloud-run.env.yaml sets ENVIRONMENT={value!r}, which is "
        f"not one of Settings.environment's allowed values {allowed}"
    )


def test_auth_mode_is_a_valid_literal(env_file: dict[str, str]) -> None:
    """Same failure shape as ENVIRONMENT, on the one variable that gates all auth.

    ``MCP_AUTH_MODE`` is the plan 02-07 cutover switch and the documented
    rollback lever, so it is the value most likely to be hand-edited under
    pressure -- and a typo like ``"authkit "`` or ``"workos"`` does not fail the
    deploy, it kills the process at boot on Cloud Run with a pydantic
    ``ValidationError`` nobody is watching for.
    """
    value = env_file["MCP_AUTH_MODE"]
    allowed = get_args(Settings.model_fields["mcp_auth_mode"].annotation)

    assert value in allowed, (
        f"MCP-04 violated: deploy/cloud-run.env.yaml sets MCP_AUTH_MODE={value!r}, which is "
        f"not one of Settings.mcp_auth_mode's allowed values {allowed} -- the process would "
        f"die at boot, on Cloud Run, remotely"
    )


def test_no_credential_shaped_key_is_present(env_file: dict[str, str]) -> None:
    """T-02-10: on Cloud Run the rule is 'not present at all', not 'no literal value'.

    Render offered ``sync: false``/``generateValue``/``fromDatabase`` as ways to
    name a credential in the blueprint without committing its value. Cloud Run's
    ``--env-vars-file`` has no such escape hatch -- every value in it is a
    literal -- so a credential-shaped key here can only be a committed secret.
    """
    for key in env_file:
        offending = [marker for marker in _SECRET_NAME_MARKERS if marker in key]
        assert not offending, (
            f"T-02-10 violated: deploy/cloud-run.env.yaml declares {key}, whose name matches "
            f"{offending}. --env-vars-file has no sync: false equivalent, so any value here "
            f"is a literal committed to git forever; bind it through --set-secrets in "
            f"scripts/deploy-cloud-run.sh instead"
        )


def test_resource_url_and_allowed_hosts_agree(env_file: dict[str, str]) -> None:
    """RESEARCH Pitfall 8 / CR-4: the resource identifier and the Host allowlist must agree.

    ``MCP_RESOURCE_URL`` is published in the RFC 9728 metadata document and must
    match, character for character, the URL typed into Claude's connector dialog.
    Cloud Run forwards the ORIGINAL public Host header to the container, so if
    that URL's host is absent from ``MCP_ALLOWED_HOSTS`` the DNS-rebinding guard
    answers every request with ``421 Invalid Host header`` and no error body.
    """
    resource = env_file["MCP_RESOURCE_URL"]
    # `urlsplit().hostname` lowercases; lowercase the allowlist too or an uppercase
    # entry reports a false failure on the one variable a 421 depends on.
    hosts = [h.strip().lower() for h in env_file["MCP_ALLOWED_HOSTS"].split(",") if h.strip()]
    parsed = urlsplit(resource)

    assert resource.endswith("/mcp"), (
        f"MCP-01 violated: MCP_RESOURCE_URL is {resource!r}; it must end with /mcp and carry "
        f"no trailing slash"
    )
    assert parsed.scheme == "https", (
        f"MCP-01 violated: MCP_RESOURCE_URL is {resource!r}; the deployed endpoint must be HTTPS"
    )
    assert not parsed.query, (
        f"T-02-03 violated: MCP_RESOURCE_URL is {resource!r}; a query string on the resource "
        f"identifier is how a token gets smuggled into a URL, which the MCP authorization "
        f"spec prohibits"
    )
    assert parsed.hostname in hosts, (
        f"T-02-01 violated: MCP_RESOURCE_URL host {parsed.hostname!r} is absent from "
        f"MCP_ALLOWED_HOSTS {hosts} -- every request would return 421 Invalid Host header"
    )


def test_deploy_script_carries_every_required_flag() -> None:
    """A flag dropped during an edit changes where or how the service deploys."""
    script = DEPLOY_SCRIPT.read_text()

    for flag in _REQUIRED_FLAGS:
        assert flag in script, (
            f"DEPLOY-01 violated: scripts/deploy-cloud-run.sh no longer passes {flag}; this "
            f"script is the single reproducible description of how BRETT deploys (D-06e), so "
            f"a missing flag silently changes the deployed service"
        )


def test_service_has_enough_memory_for_json_ingest() -> None:
    """RESEARCH Pitfall 5: 512Mi OOMs on a 10 MB ingest body and Cloud Run reports only a 503.

    Asserted in both directions. The presence check alone would pass a script that
    somehow carried two ``--memory`` flags, and the absence check alone would pass a
    script that had dropped the flag entirely and inherited Cloud Run's own default.
    """
    script = _deploy_script_text()
    memory_flags = [line.strip() for line in script.splitlines() if "--memory" in line]

    assert "--memory=1Gi" in script, (
        f"HEALTH-06 violated: the deploy no longer requests 1Gi. Measured peak resident memory "
        f"decoding a 10 MB Health Auto Export body is ~235 MB; at 512Mi the instance OOMs and "
        f"Cloud Run answers 503 with no application log line, so a whole sync window is lost "
        f"with no diagnosable cause. Found memory flag: {memory_flags}"
    )
    assert "--memory=512Mi" not in script, (
        f"HEALTH-06 violated: --memory=512Mi is back in scripts/deploy-cloud-run.sh. That is "
        f"the measured-too-small value this plan replaced, and the failure it produces (a 503 "
        f"with no log line) looks like an outage rather than a capacity problem. Found memory "
        f"flag: {memory_flags}"
    )


def test_deploy_script_has_no_comment_inside_the_gcloud_call() -> None:
    """A `#` between two continued lines truncates the command, and `bash -n` says nothing.

    Backslash continuation is removed during tokenization, so a comment line inside the
    invocation is joined onto the previous one, swallows the rest of that logical line,
    and the unescaped newline then ENDS the command. Everything below the comment --
    ``--env-vars-file``, ``--set-secrets``, ``--memory`` -- becomes a separate line that
    bash tries to run as its own command. The script exits non-zero eventually, but only
    AFTER ``gcloud run deploy`` has already deployed a revision with no environment, no
    secrets and default memory.

    Nothing else catches this. ``bash -n`` reports the file as syntactically valid
    (verified), and ``test_deploy_script_carries_every_required_flag`` greps the file as
    TEXT, so every flag it looks for is still present in a script that no longer passes
    any of them. Documenting the hazard in a comment is not enough either -- the comment
    would sit right next to the place someone is about to add another one.
    """
    lines = _deploy_script_text().splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith("exec gcloud run deploy")]
    assert len(starts) == 1, (
        f"DEPLOY-01 violated: expected exactly one `exec gcloud run deploy` invocation in "
        f"scripts/deploy-cloud-run.sh, found {len(starts)}"
    )

    offenders: list[str] = []
    for line in lines[starts[0] :]:
        stripped = line.strip()
        if stripped.startswith("#"):
            offenders.append(stripped)
        if not line.rstrip().endswith("\\"):
            break

    assert not offenders, (
        f"DEPLOY-01 violated: scripts/deploy-cloud-run.sh has a comment INSIDE the "
        f"backslash-continued gcloud invocation. That silently truncates the command at the "
        f"comment -- the deploy still runs, but without every flag below it (no --env-vars-file, "
        f"no --set-secrets, no --memory) and `bash -n` reports the file as valid. Move the "
        f"comment above `exec gcloud run deploy`. Offending lines: {offenders}"
    )


def test_every_secret_binding_is_a_secret_manager_reference() -> None:
    """T-02-10, Cloud Run edition: a literal on the right-hand side is a committed secret.

    The failure message deliberately does NOT echo the offending value -- doing so
    would print the credential into CI output, which is the same mistake
    ``hide_input_in_errors=True`` exists to prevent in ``Settings``.
    """
    bindings = _secret_bindings()

    assert bindings, (
        "DEPLOY-01 violated: scripts/deploy-cloud-run.sh binds no secrets at all; "
        "DATABASE_URL and MCP_AUTH_SECRET have no other source on Cloud Run"
    )
    for name, reference in bindings.items():
        assert _SECRET_REF.match(reference), (
            f"T-02-10 violated: --set-secrets binds {name} to something that is not a Secret "
            f"Manager reference (expected `secret-name:latest` or `secret-name:VERSION`). If "
            f"that is a credential literal it is now in git history, which no later commit "
            f"can undo"
        )


def test_env_file_and_secret_bindings_partition_the_environment(env_file: dict[str, str]) -> None:
    """Cloud Run rejects a deploy that binds one name twice, and boots without a missing one."""
    bindings = _secret_bindings()

    overlap = sorted(set(env_file) & set(bindings))
    assert not overlap, (
        f"DEPLOY-01 violated: {overlap} appears both in deploy/cloud-run.env.yaml and in "
        f"--set-secrets; Cloud Run rejects a deploy that binds one name in both places"
    )

    for required in ("DATABASE_URL", "MCP_AUTH_SECRET", "HEALTH_INGEST_SECRET"):
        assert required in bindings, (
            f"T-02-10 violated: {required} is not bound by --set-secrets. It is a credential, "
            f"so Secret Manager is its only legitimate source -- it must never move into "
            f"deploy/cloud-run.env.yaml"
        )

    supplied = set(env_file) | set(bindings)
    for name, field in Settings.model_fields.items():
        if not field.is_required():
            continue
        alias = field.validation_alias
        env_name = alias.upper() if isinstance(alias, str) else name.upper()
        assert env_name in supplied, (
            f"DEPLOY-01 violated: Settings.{name} is required and has no default, but neither "
            f"deploy/cloud-run.env.yaml nor --set-secrets supplies {env_name}; the deployed "
            f"service would die at boot with a pydantic ValidationError"
        )


def test_deploy_script_avoids_env_wiping_and_cloudsql_flags() -> None:
    """Two shapes of drift that are invisible in review but fatal in production."""
    script = DEPLOY_SCRIPT.read_text()

    assert "--set-env-vars" not in script, (
        "DEPLOY-01 violated: scripts/deploy-cloud-run.sh passes --set-env-vars, which removes "
        "every existing environment variable before adding its own and would therefore "
        "silently wipe everything --env-vars-file supplies"
    )
    for flag in ("--add-cloudsql-instances", "--vpc-connector"):
        assert flag not in script, (
            f"D-06b violated: scripts/deploy-cloud-run.sh passes {flag}; the database is Neon, "
            f"reached over ordinary public egress -- neither Cloud SQL nor a VPC connector is "
            f"part of this architecture"
        )


def test_procfile_entrypoint_points_at_the_backend_package() -> None:
    """Without a Procfile the build fails; without --app-dir the container dies at start.

    Cloud Buildpacks opt into ``google.config.entrypoint`` only when a Procfile
    (or ``GOOGLE_ENTRYPOINT``) exists; otherwise the build falls through to
    ``missing-entrypoint``, which looks for ``main.py``/``app.py`` at the SOURCE
    ROOT and fails with a message that never mentions ``backend/``.
    """
    assert PROCFILE.exists(), (
        "DEPLOY-01 violated: the repo-root Procfile is gone. `gcloud run deploy --source` "
        "then fails before installing a single dependency with 'for Python with "
        "pyproject.toml, provide a main.py or app.py file'"
    )

    web_lines = [line for line in PROCFILE.read_text().splitlines() if line.startswith("web:")]
    assert len(web_lines) == 1, (
        f"DEPLOY-01 violated: the Procfile declares {len(web_lines)} `web:` processes; Cloud "
        f"Run starts exactly one and the CNB Procfile parser is not the place to experiment"
    )

    for fragment in ("--app-dir backend", "--host 0.0.0.0", "$PORT"):
        assert fragment in web_lines[0], (
            f"DEPLOY-01 violated: the Procfile `web:` line omits {fragment!r}. uv.lock records "
            f"the root project as virtual, so `uv sync` never puts backend/ on sys.path and "
            f"the container dies remotely and silently with `ModuleNotFoundError: No module "
            f"named 'app'`; Cloud Run additionally requires 0.0.0.0 and its injected $PORT"
        )


def test_gcloudignore_excludes_the_health_data_exports() -> None:
    """T-02-11: gcloud's implicit .gitignore fallback dies the moment this file exists."""
    assert GCLOUDIGNORE.exists(), (
        "T-02-11 violated: .gcloudignore is gone. gcloud falls back to a generated "
        "Git-compatible list only while it is absent, so its removal is survivable -- but its "
        "presence with the wrong contents is not, which is what the entries below guard"
    )

    entries = {
        line.strip()
        for line in GCLOUDIGNORE.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    for excluded in ("export.xml", "records.csv", ".venv/"):
        assert excluded in entries, (
            f"T-02-11 violated: .gcloudignore no longer excludes {excluded!r}. Once this file "
            f"exists it replaces the implicit .gitignore fallback entirely, so `gcloud run "
            f"deploy --source` would upload roughly 490 MB of personal health data into a "
            f"Cloud Storage build bucket on every deploy"
        )


def test_render_blueprint_is_gone() -> None:
    """D-06 (revised): a resurrected blueprint would document an abandoned target."""
    assert not (REPO_ROOT / "render.yaml").exists(), (
        "D-06 (revised) violated: render.yaml is back. The deploy target moved to Google "
        "Cloud Run on 2026-08-27; an unused Render blueprint sitting in the repo would "
        "mislead a future reader into deploying to an abandoned target. "
        "scripts/deploy-cloud-run.sh is the deploy path"
    )
