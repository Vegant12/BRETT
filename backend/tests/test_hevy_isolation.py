"""HEVY-05: nothing Hevy-shaped escapes `app/integrations/hevy/`.

Static assertions over committed source: no container, no network, and deliberately no
integration marker -- a boundary violation must fail the FAST suite on the commit that
introduces it, not after a deploy.

The boundary is what makes Hevy replaceable. Hevy's own docs say the API structure may change
without notice; if a Pydantic Hevy model is imported by `db/`, `normalization/` or (later)
`analytics/`, that change stops being a one-package problem.

The boundary is ONE-DIRECTIONAL by design. Nothing outside may reach in; the Hevy package
reaching out to `app.db.models` is expected and permitted -- plan 03-06 puts the sync modules
inside this package precisely so the provider-specific persistence decisions live next to the
provider-specific wire format. A symmetric rule would forbid the very thing the layout is for.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APP = REPO_ROOT / "backend" / "app"
HEVY_PKG = APP / "integrations" / "hevy"

# Matched at the START of a line (modulo indentation) so a mention inside a docstring or a
# comment -- of which there are several, deliberately -- is not read as an import.
_HTTPX2_IMPORT = re.compile(r"^\s*(?:import httpx2|from httpx2)", re.MULTILINE)
_INTEGRATIONS_IMPORT = re.compile(r"^\s*(?:import|from)\s+app\.integrations", re.MULTILINE)


def _app_modules_outside_hevy() -> list[Path]:
    """Every committed module under `app/` that is not part of the Hevy package.

    `rglob` rather than a hand-maintained list: a new subpackage must be covered by this
    boundary the moment it exists, without anyone remembering to add it here.
    """
    return [path for path in sorted(APP.rglob("*.py")) if HEVY_PKG not in path.parents]


def test_the_walk_actually_finds_files() -> None:
    """A guard on the guards: an empty walk would make every test below vacuously true.

    If `APP` were ever wrong -- a moved package, a renamed directory -- `rglob` returns
    nothing and four boundary tests pass while checking nothing at all.
    """
    outside = _app_modules_outside_hevy()

    assert len(outside) > 10, f"the walk found only {len(outside)} modules under {APP}"
    assert list(HEVY_PKG.rglob("*.py")), f"no Hevy package found at {HEVY_PKG}"


def test_hevy_schemas_are_not_imported_outside_the_package() -> None:
    """A Hevy wire type in `db/` or `analytics/` makes a Hevy rename a whole-app rename.

    `schemas.py` specifically: it is the quarantine boundary. `client.py` and (later)
    `sync.py` are legitimately called from a CLI or a route, but the shapes they parse must
    be translated at the edge of this package and never handed onward raw.
    """
    for path in _app_modules_outside_hevy():
        source = path.read_text(encoding="utf-8")
        for forbidden in (
            "from app.integrations.hevy.schemas",
            "import app.integrations.hevy.schemas",
        ):
            assert forbidden not in source, (
                f"HEVY-05 violated: {path.relative_to(REPO_ROOT)} imports Hevy's wire "
                f"schemas. Translate them inside app/integrations/hevy/ and pass domain "
                f"types outward -- otherwise a Hevy field rename reaches this file too"
            )


def test_httpx2_is_only_imported_inside_the_hevy_package() -> None:
    """An HTTP client outside a provider package means provider logic has leaked out of it."""
    for path in _app_modules_outside_hevy():
        source = path.read_text(encoding="utf-8")
        assert not _HTTPX2_IMPORT.search(source), (
            f"HEVY-05 violated: {path.relative_to(REPO_ROOT)} imports httpx2. Outbound HTTP "
            f"belongs to a provider package; a client here is provider logic that has "
            f"escaped its boundary"
        )


def test_normalization_does_not_import_integrations() -> None:
    """The exercise -> muscle-group mapping is provider-NEUTRAL and must stay that way.

    It maps canonical exercise identity to muscle groups. The moment it imports anything
    under `app.integrations`, it has learned that its input came from Hevy -- and a second
    provider (or a manual entry path) can no longer feed it.

    Matched as an IMPORT rather than as a bare substring: `app/normalization/__init__.py`
    states this very rule in its own docstring ("Nothing here may import from
    ``app.integrations``"), so a substring check would fail on the sentence that documents
    the boundary. The regex is the same one `db/` is checked with, so both tests mean the
    same thing by "does not import".
    """
    for path in sorted((APP / "normalization").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        assert not _INTEGRATIONS_IMPORT.search(source), (
            f"HEVY-05 violated: {path.relative_to(REPO_ROOT)} imports app.integrations. "
            f"The normalization layer is provider-neutral by design"
        )


def test_db_does_not_import_integrations() -> None:
    """Models and sessions describe BRETT's schema, not any provider's response shape.

    `workouts.provider` is a plain string column for exactly this reason: the database
    records WHICH provider a row came from without importing that provider's code.
    """
    for path in sorted((APP / "db").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        assert not _INTEGRATIONS_IMPORT.search(source), (
            f"HEVY-05 violated: {path.relative_to(REPO_ROOT)} imports app.integrations. The "
            f"persistence layer must not depend on a provider package -- the dependency runs "
            f"the other way"
        )
