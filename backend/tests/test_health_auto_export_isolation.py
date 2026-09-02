"""HEALTH-06/07: nothing HAE-shaped escapes `app/integrations/health_auto_export/`.

Static assertions over committed source: no container, no network, and deliberately no
integration marker -- a boundary violation must fail the FAST suite on the commit that
introduces it, not after a deploy.

The boundary is what makes Health Auto Export replaceable. HAE units are a per-metric user
preference inside the phone app, converted on-device at export time, so the wire format can
change with no version bump and nothing to notice it by. If an HAE Pydantic model or an HAE
metric name is imported by `db/`, `analytics/` or a route, that change stops being a
one-package problem.

The boundary is ONE-DIRECTIONAL by design. Nothing outside may reach in; the HAE package
reaching out to `app.db.models` and `app.core.time` is expected and permitted -- the
provider-specific persistence decisions live next to the provider-specific wire format. A
symmetric rule would forbid the very thing the layout is for.

**Pitfall N-5:** `test_hevy_isolation.py`'s guards are scoped to the Hevy path and cover NONE
of this. A new provider package needs its own guards or it has none.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APP = REPO_ROOT / "backend" / "app"
HAE_PKG = APP / "integrations" / "health_auto_export"

# Matched at the START of a line (modulo indentation) so a mention inside a docstring or a
# comment -- of which there are several, deliberately -- is not read as an import.
_HTTP_CLIENT_IMPORT = re.compile(
    r"^\s*(?:import|from)\s+(?:httpx2|httpx|requests|aiohttp|urllib\.request)\b", re.MULTILINE
)
_MCP_IMPORT = re.compile(r"^\s*(?:import|from)\s+(?:app\.mcp|mcp)\b", re.MULTILINE)


def _app_modules_outside_hae() -> list[Path]:
    """Every committed module under `app/` that is not part of the HAE package.

    `rglob` rather than a hand-maintained list: a new subpackage must be covered by this
    boundary the moment it exists, without anyone remembering to add it here.
    """
    return [path for path in sorted(APP.rglob("*.py")) if HAE_PKG not in path.parents]


def _hae_modules() -> list[Path]:
    return sorted(HAE_PKG.rglob("*.py"))


def test_the_walk_actually_finds_files() -> None:
    """A guard on the guards: an empty walk would make every test below vacuously true.

    If `APP` or `HAE_PKG` were ever wrong -- a moved package, a renamed directory -- `rglob`
    returns nothing and four boundary tests pass while checking nothing at all.
    """
    outside = _app_modules_outside_hae()

    assert len(outside) > 10, f"the walk found only {len(outside)} modules under {APP}"
    assert _hae_modules(), f"no Health Auto Export package found at {HAE_PKG}"


def test_hae_schemas_are_not_imported_outside_the_package() -> None:
    """An HAE wire type in `db/` or `analytics/` makes an HAE field rename a whole-app rename.

    `schemas.py` specifically: it is the quarantine boundary. The shapes it parses must be
    translated at the edge of this package and never handed onward raw (T-08-25).
    """
    for path in _app_modules_outside_hae():
        source = path.read_text(encoding="utf-8")
        for forbidden in (
            "from app.integrations.health_auto_export.schemas",
            "import app.integrations.health_auto_export.schemas",
        ):
            assert forbidden not in source, (
                f"HEALTH-06 violated: {path.relative_to(REPO_ROOT)} imports HAE's wire "
                f"schemas. Translate them inside app/integrations/health_auto_export/ and "
                f"pass domain types outward -- otherwise an HAE field rename reaches this "
                f"file too, and HAE renames without a version bump"
            )


def test_hae_registry_is_not_imported_outside_the_package() -> None:
    """The twelve metric names are HAE's identifiers, not BRETT's.

    An analytics module keyed on `dietary_energy` or `total_fat` would drift the moment HAE
    renames one -- and under D-04 that rename is a silent drop, so nothing would fail; the
    column would simply stop filling.
    """
    for path in _app_modules_outside_hae():
        source = path.read_text(encoding="utf-8")
        for forbidden in (
            "from app.integrations.health_auto_export.registry",
            "import app.integrations.health_auto_export.registry",
        ):
            assert forbidden not in source, (
                f"HEALTH-06 violated: {path.relative_to(REPO_ROOT)} imports HAE's metric "
                f"registry. Those are wire identifiers; keying application code on them "
                f"spreads HAE's vocabulary through the app"
            )


def test_no_http_client_is_imported_inside_the_package() -> None:
    """THE INVERSION, and the reason this file is not a copy of `test_hevy_isolation.py`.

    Hevy's guard asserts no `httpx2` OUTSIDE its package, because that integration is OUTBOUND
    and the client legitimately lives inside. This integration is INBOUND -- HAE calls BRETT,
    never the reverse -- so the stronger assertion applies INSIDE: no HTTP client may be
    imported here at all. An outbound call from this package would be an unreviewed egress path
    in a health-data service (T-08-26).
    """
    for path in _hae_modules():
        source = path.read_text(encoding="utf-8")
        assert not _HTTP_CLIENT_IMPORT.search(source), (
            f"T-08-26 violated: {path.relative_to(REPO_ROOT)} imports an HTTP client. The "
            f"Health Auto Export integration is INBOUND ONLY; a client here is an unreviewed "
            f"outbound egress path from a service holding health data"
        )


def test_no_mcp_import_inside_the_package() -> None:
    """The webhook verifier is deliberately NOT an MCP `TokenVerifier`.

    Importing `mcp.server.auth.provider` here would put an MCP dependency inside an
    integrations package and break the boundary this package exists to draw -- the two auth
    surfaces answer to different clients and must be able to change independently.
    """
    for path in _hae_modules():
        source = path.read_text(encoding="utf-8")
        assert not _MCP_IMPORT.search(source), (
            f"HEALTH-07 violated: {path.relative_to(REPO_ROOT)} imports the MCP SDK or "
            f"app.mcp. The ingest credential check returns a plain bool and shares nothing "
            f"with the MCP token verifier"
        )
