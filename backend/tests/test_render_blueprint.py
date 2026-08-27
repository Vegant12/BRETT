"""render.yaml <-> Settings drift guard (DEPLOY-01).

This is a test rather than a comment because the failure it catches is silent
and remote. Render reads ``render.yaml`` verbatim, and ``Settings.model_config``
sets ``extra="ignore"`` -- so an ``envVars`` key that no longer corresponds to a
real field is not an error at deploy time. The service boots happily on the
defaults, and the only symptom surfaces much later as a ``421 Invalid Host
header`` or a ``401`` from a deploy that Render reports as healthy. The reverse
drift is worse: if a credential-shaped key ever gains a literal ``value:``, again
nothing fails -- the secret is simply in git forever (T-02-10).

These are static assertions over the committed file: no container, no network,
and deliberately no integration marker -- drift must fail the fast suite on the
commit that introduces it, not after a deploy.
"""

from pathlib import Path
from typing import Any, get_args
from urllib.parse import urlsplit

import pytest
import yaml

from app.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
BLUEPRINT = REPO_ROOT / "render.yaml"

# Set by the Render platform or by the runtime, not by Settings.
_PLATFORM_VARS = frozenset({"UV_VERSION", "PYTHON_VERSION", "PORT"})

# Any env var whose NAME matches one of these must never carry a literal value.
_SECRET_NAME_MARKERS = ("SECRET", "KEY", "TOKEN", "PASSWORD", "DATABASE_URL")


@pytest.fixture(scope="module")
def blueprint() -> dict[str, object]:
    return yaml.safe_load(BLUEPRINT.read_text())


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


def _service(blueprint: dict[str, object]) -> dict[str, Any]:
    services = blueprint["services"]
    assert isinstance(services, list) and services, "render.yaml declares no services"
    service = services[0]
    assert isinstance(service, dict)
    return service


def _env_vars(blueprint: dict[str, object]) -> list[dict[str, Any]]:
    env_vars = _service(blueprint)["envVars"]
    assert isinstance(env_vars, list), "render.yaml declares no envVars for the web service"
    return env_vars


def _env_value(blueprint: dict[str, object], key: str) -> str:
    for entry in _env_vars(blueprint):
        if entry["key"] == key:
            value = entry.get("value")
            assert isinstance(value, str), f"render.yaml sets no literal value for {key}"
            return value
    raise AssertionError(f"DEPLOY-01 violated: render.yaml declares no envVars entry for {key}")


def test_blueprint_parses() -> None:
    """One web service and one database -- the shape every other test assumes.

    A second service would double the cost and force the MCP layer to reach
    analytics over HTTP, which the project blueprint forbids.
    """
    parsed = yaml.safe_load(BLUEPRINT.read_text())

    assert isinstance(parsed, dict), f"DEPLOY-01 violated: {BLUEPRINT} is not a YAML mapping"
    services = parsed["services"]
    databases = parsed["databases"]
    assert len(services) == 1, (
        f"DEPLOY-01 violated: render.yaml must declare exactly one web service, "
        f"found {len(services)}"
    )
    assert len(databases) == 1, (
        f"DEPLOY-01 violated: render.yaml must declare exactly one database, found {len(databases)}"
    )
    assert services[0]["type"] == "web"

    # A `fromDatabase` pointing at a name no database block declares fails
    # Render's blueprint sync with an error that names neither file nor line.
    referenced = {
        entry["fromDatabase"]["name"] for entry in _env_vars(parsed) if "fromDatabase" in entry
    }
    declared = {database["name"] for database in databases}
    assert referenced <= declared, (
        f"DEPLOY-01 violated: render.yaml references databases {referenced - declared} "
        f"that it does not declare"
    )


def test_every_env_var_maps_to_a_settings_field(blueprint: dict[str, object]) -> None:
    """A key Settings does not read is ignored, not rejected -- hence this test."""
    known = _settings_env_names()

    for entry in _env_vars(blueprint):
        key = entry["key"]
        if key in _PLATFORM_VARS:
            continue
        assert key in known, (
            f"DEPLOY-01 violated: render.yaml sets {key} but Settings has no such field "
            f"(extra='ignore' means the deployed service would silently ignore it)"
        )


def test_environment_value_is_a_valid_literal(blueprint: dict[str, object]) -> None:
    """A value outside the Literal kills the process at boot, on Render, remotely."""
    value = _env_value(blueprint, "ENVIRONMENT")
    allowed = get_args(Settings.model_fields["environment"].annotation)

    assert value in allowed, (
        f"DEPLOY-01 violated: render.yaml sets ENVIRONMENT={value!r}, which is not one "
        f"of Settings.environment's allowed values {allowed}"
    )


def test_no_secret_is_committed_as_a_literal(blueprint: dict[str, object]) -> None:
    """T-02-10: every credential must be supplied by Render, never by this repo.

    ``generateValue`` mints the value server-side, ``sync: false`` prompts for it
    in the dashboard, and ``fromDatabase`` reads it from the managed database. A
    literal ``value:`` on any of these keys is a credential in git history, which
    no later commit can undo.
    """
    for entry in _env_vars(blueprint):
        key = entry["key"]
        if not any(marker in key for marker in _SECRET_NAME_MARKERS):
            continue

        assert "value" not in entry, (
            f"T-02-10 violated: render.yaml commits a literal value for {key}; "
            f"use generateValue, sync: false, or fromDatabase instead"
        )
        supplied_by_render = (
            entry.get("generateValue") is True
            or entry.get("sync") is False
            or "fromDatabase" in entry
        )
        assert supplied_by_render, (
            f"T-02-10 violated: {key} is neither minted by Render (generateValue), "
            f"prompted for (sync: false), nor read from the database (fromDatabase)"
        )


def test_start_command_points_at_the_backend_package(blueprint: dict[str, object]) -> None:
    """Without --app-dir, uvicorn cannot import a package that lives in backend/.

    ``pythonpath = ["backend"]`` in pyproject.toml sits under
    ``[tool.pytest.ini_options]`` and applies to pytest only, so the local test
    suite passes while the deploy crashes on ``ModuleNotFoundError``.
    """
    service = _service(blueprint)

    assert "--app-dir backend" in service["startCommand"], (
        "DEPLOY-01 violated: render.yaml's startCommand omits `--app-dir backend`, so "
        "uvicorn will fail with ModuleNotFoundError: No module named 'app'"
    )
    assert "rootDir" not in service, (
        "DEPLOY-01 violated: the service root directory must stay unset -- Render "
        "activates uv only when uv.lock is in the service's root directory, and this "
        "repo keeps uv.lock at the repo root"
    )


def test_health_check_path_is_open_endpoint(blueprint: dict[str, object]) -> None:
    """T-02-06/D-04: the health check must point at the deliberately open route.

    ``/health`` is unauthenticated by design and its body is ``{status, database}``
    only. Repointing this at an authenticated route would make every deploy fail
    its health check and roll back, with a 401 as the only clue.
    """
    assert _service(blueprint)["healthCheckPath"] == "/health", (
        "DEPLOY-01 violated: healthCheckPath must be /health, the one route with no auth dependency"
    )


def test_resource_url_and_allowed_hosts_agree(blueprint: dict[str, object]) -> None:
    """RESEARCH Pitfall 8: the resource identifier and the Host allowlist must agree.

    ``MCP_RESOURCE_URL`` is published in the RFC 9728 metadata document and must
    match, character for character, the URL typed into Claude's connector dialog.
    If its host is not in ``MCP_ALLOWED_HOSTS``, the DNS-rebinding guard answers
    every request with ``421 Invalid Host header`` and no MCP-level error body.
    """
    resource = _env_value(blueprint, "MCP_RESOURCE_URL")
    hosts = [h.strip() for h in _env_value(blueprint, "MCP_ALLOWED_HOSTS").split(",") if h.strip()]
    parsed = urlsplit(resource)

    assert resource.endswith("/mcp"), (
        f"MCP-01 violated: MCP_RESOURCE_URL is {resource!r}; it must end with /mcp and "
        f"carry no trailing slash"
    )
    assert parsed.scheme == "https", (
        f"MCP-01 violated: MCP_RESOURCE_URL is {resource!r}; the deployed endpoint must be HTTPS"
    )
    assert not parsed.query, (
        f"T-02-03 violated: MCP_RESOURCE_URL is {resource!r}; a query string on the "
        f"resource identifier is how a token gets smuggled into a URL"
    )
    assert parsed.hostname in hosts, (
        f"T-02-01 violated: MCP_RESOURCE_URL host {parsed.hostname!r} is absent from "
        f"MCP_ALLOWED_HOSTS {hosts} -- every request would return 421 Invalid Host header"
    )
