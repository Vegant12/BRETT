"""The `app/analytics/` boundary, asserted statically over committed source.

No container, no network, and deliberately no integration marker -- a boundary violation must
fail the FAST suite on the commit that introduces it, not after a deploy.

The boundary is ONE-DIRECTIONAL. Phase 6's MCP tools call into analytics; analytics never calls
out to `app.mcp`, and never to `app.integrations` either. Reversing either arrow puts a wire
contract or a provider's field names inside the arithmetic, and makes the arithmetic untestable
without a transport or a provider.

The muscle-table ban is the load-bearing one. It is a STATIC guarantee that
`app.normalization.resolver.effective_muscles_bulk` is being used, because a direct
`exercise_muscles` join produces byte-identical output today -- `exercise_muscle_overrides` has
zero rows -- and only starts lying the first time a user corrects a mapping. No reviewer can
see that, and no test written against today's data can catch it. A static assertion can.

Every check is an ANCHORED REGEX or a CamelCase class identifier, never a bare substring.
`app/analytics/__init__.py` states these very rules in prose, so a substring check would fail on
the sentence documenting the boundary -- the trap already recorded at
`test_hevy_isolation.py:88-93`. The convention that makes this work: prose in `app/analytics/`
refers to the tables in lowercase (`exercise_muscles`), never by their ORM class name.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ANALYTICS = REPO_ROOT / "backend" / "app" / "analytics"

# Anchored at the START of a line (modulo indentation): a mention in a docstring or comment --
# of which there are several, deliberately -- must not be read as an import.
_INTEGRATIONS_IMPORT = re.compile(r"^\s*(?:import|from)\s+app\.integrations", re.MULTILINE)
_MCP_IMPORT = re.compile(r"^\s*(?:import|from)\s+app\.mcp", re.MULTILINE)

# The ORM class identifiers, CamelCase. Prose in this package refers to the tables in lowercase
# (`exercise_muscles`), so the class name appearing at all means somebody is querying it.
_MUSCLE_TABLE_CLASS = re.compile(r"\bExerciseMuscle(?:Override)?\b")

# S608 belt-and-braces: no hand-built SQL string may reach the driver from this package. The
# timezone is the only user-controlled value that touches SQL, and it must stay a BOUND
# parameter via `func.timezone(tz, col)`. Both import spellings are covered -- the bare `text(`
# of `from sqlalchemy import text`, and the qualified `sa.text(` / `sqlalchemy.text(` -- because
# a guard with one spelling missing is a guard with a documented way around it.
_RAW_SQL_TEXT = re.compile(r"(?<![\w.])(?:(?:sa|sqlalchemy)\.)?text\s*\(")

# Read-only in v1 (MCP-05 inherits this). `session_ids.add(...)` on a Python set is fine and
# deliberately not matched -- only session-bound mutations are.
_SESSION_WRITE = re.compile(r"\bsession\.(?:commit|flush|add|add_all)\s*\(")
_WRITE_IMPORT = re.compile(
    r"^\s*from\s+sqlalchemy\s+import\s+.*\b(?:insert|update|delete)\b", re.MULTILINE
)

# C-2: `Decimal`, never `float`. Anchored on the CONSTRUCTOR and the ANNOTATION positions, never
# the bare word -- `estimates.py`, `schemas.py` and `rollup.py` all use the words "float" and
# "binary floating point" in prose explaining why they do not use one, and a substring check
# would fail on the sentence documenting the rule (the trap recorded at
# `test_hevy_isolation.py:88-93`). A leaked float is how `regr_slope`'s `double precision` or
# `statistics.linear_regression` would enter, and it turns an exact Decimal comparison into a
# test that needs `pytest.approx`.
_FLOAT_USE = re.compile(r"(?<![\w.])float\s*\(|:\s*float\b|->\s*float\b|\[\s*float\s*[],]")

# Pitfall 1, the structural half of the defence (the docstring in `estimates.py` is the other
# half, and neither alone is enough). `weight_kg * (1 + reps / 30)` in PostgreSQL uses INTEGER
# division: `SELECT 10 * (1 + 8/30)` returns `10`, the bare weight. The guard is keyed on the
# divisor rather than on the word "Epley", because the wrong version would never be labelled.
# `estimates.py` is the ONE module allowed to divide by 30, and it does so in Python.
_DIVIDE_BY_THIRTY = re.compile(r"/\s*30\b|Decimal\s*\(\s*30\s*\)|_THIRTY")


def _analytics_modules() -> list[Path]:
    """Every committed module under `app/analytics/`.

    `rglob` rather than a hand-maintained list: a new analytics submodule must be covered by
    these boundaries the moment it exists, without anyone remembering to add it here.
    """
    return sorted(ANALYTICS.rglob("*.py"))


def test_the_walk_actually_finds_files() -> None:
    """A guard on the guards: an empty walk would make every test below vacuously true.

    If `ANALYTICS` were ever wrong -- a moved package, a renamed directory -- `rglob` returns
    nothing and five boundary tests pass while checking nothing at all.
    """
    modules = _analytics_modules()

    # As of Phase 5 the package holds `__init__`, `schemas`, `metadata`, `rollup`, `volume` and
    # `frequency` at minimum. The floor rises with the package on purpose: a floor of 2 stayed
    # satisfied by a walk that had silently lost most of what it was supposed to be checking.
    assert len(modules) >= 6, f"the walk found only {len(modules)} modules under {ANALYTICS}"


def test_analytics_does_not_import_integrations() -> None:
    """Analytics is provider-NEUTRAL, and that is what keeps Hevy replaceable.

    Hevy's own docs say the API structure may change without notice. A Hevy import here means a
    Hevy field rename becomes an analytics rename -- and a second provider, or a manual entry
    path, can no longer feed the same numbers.
    """
    for path in _analytics_modules():
        source = path.read_text(encoding="utf-8")
        assert not _INTEGRATIONS_IMPORT.search(source), (
            f"HEVY-05 violated: {path.relative_to(REPO_ROOT)} imports app.integrations. "
            f"Analytics is provider-neutral by design; a Hevy field rename must not become an "
            f"analytics rename"
        )


def test_analytics_does_not_import_mcp() -> None:
    """The Phase 6 arrow runs ONE WAY: MCP tools call analytics, never the reverse.

    Importing `app.mcp` here puts a wire contract inside the arithmetic and makes the arithmetic
    untestable without a transport -- exactly the coupling PROJECT.md's "analytics lives outside
    MCP handlers" requirement exists to prevent.
    """
    for path in _analytics_modules():
        source = path.read_text(encoding="utf-8")
        assert not _MCP_IMPORT.search(source), (
            f"boundary violated: {path.relative_to(REPO_ROOT)} imports app.mcp. Analytics must "
            f"know nothing about MCP, transports, tokens or tools -- otherwise the arithmetic "
            f"can no longer be tested without standing up a transport"
        )


def test_analytics_never_names_the_muscle_tables_directly() -> None:
    """RESEARCH Pitfall 4: a direct join silently ignores the user's own mapping corrections.

    `JOIN exercise_muscles ...` returns the BASE mapping and bypasses
    `exercise_muscle_overrides`, reimplementing the resolver's REPLACEMENT rule ("any override
    replaces the base set entirely") as a merge. It produces byte-identical output today because
    the override table has zero rows, so a test written today passes and a reviewer sees nothing
    wrong. Route every muscle lookup through
    `app.normalization.resolver.effective_muscles_bulk`.
    """
    for path in _analytics_modules():
        source = path.read_text(encoding="utf-8")
        assert not _MUSCLE_TABLE_CLASS.search(source), (
            f"NORM-02 violated: {path.relative_to(REPO_ROOT)} names the muscle-mapping ORM "
            f"classes directly. A join expresses MERGE; the override rule is REPLACEMENT. Call "
            f"app.normalization.resolver.effective_muscles_bulk instead -- the wrong answer here "
            f"is invisible until the first user correction"
        )


def test_analytics_uses_no_raw_sql_text() -> None:
    """The timezone reaches SQL, so it must stay a BOUND parameter, not string-formatted in.

    `users.timezone` is the only user-controlled value this package pushes into a query, and it
    belongs inside `func.timezone(tz, col)`. A hand-built SQL string is the injection surface
    Ruff `S608` exists to block; this is the belt to that pair of braces, because `S608` only
    flags what it recognises as a query.
    """
    for path in _analytics_modules():
        source = path.read_text(encoding="utf-8")
        assert not _RAW_SQL_TEXT.search(source), (
            f"T-04-01 violated: {path.relative_to(REPO_ROOT)} builds raw SQL with text(). Every "
            f"predicate must go through SQLAlchemy Core expressions so its values are bound "
            f"parameters, never interpolated string fragments"
        )


def test_analytics_never_writes() -> None:
    """Analytics is a READ path, and the caller owns the transaction.

    MCP-05 makes read-only a product guarantee for v1, and the enforcement has to live here
    rather than at the tool boundary: a `session.commit()` buried in an aggregate function is
    still a write no matter how read-only the tool that called it claims to be. Matching the
    `app/db/repositories/` convention, these functions never commit, flush, add, insert, update
    or delete.
    """
    for path in _analytics_modules():
        source = path.read_text(encoding="utf-8")
        assert not _SESSION_WRITE.search(source), (
            f"MCP-05 violated: {path.relative_to(REPO_ROOT)} mutates the session. Analytics "
            f"reads; the caller owns the transaction"
        )
        assert not _WRITE_IMPORT.search(source), (
            f"MCP-05 violated: {path.relative_to(REPO_ROOT)} imports a write construct from "
            f"sqlalchemy. A read path has no use for insert/update/delete"
        )


def test_analytics_declares_no_float() -> None:
    """C-2: exact `Decimal` end to end, statically.

    A leaked float does not announce itself. It makes two arithmetically identical totals
    compare unequal, which surfaces as a flaky equality assertion somewhere far from the cause,
    and the usual "fix" is to reach for a tolerance -- at which point the analytics no longer
    have exact answers and nobody notices when they drift further.

    Anchored on the constructor and annotation positions rather than the bare word, because
    `estimates.py`, `schemas.py` and `rollup.py` all use "float" and "binary floating point" in
    prose explaining why they avoid one.
    """
    for path in _analytics_modules():
        source = path.read_text(encoding="utf-8")
        assert not _FLOAT_USE.search(source), (
            f"C-2 violated: {path.relative_to(REPO_ROOT)} constructs or annotates a float. "
            "Binary floating point makes two arithmetically identical totals compare unequal, "
            "and it is how `regr_slope`'s double precision or `statistics.linear_regression` "
            "enters the analytics package. Use Decimal."
        )


def test_epley_is_computed_only_in_estimates() -> None:
    """Pitfall 1: the e1RM divisor may appear in exactly one module, and never inside SQL.

    Keyed on the DIVISOR, not on the word "Epley" -- a copy of the formula pushed down into a
    SQL expression would never be labelled, and that is precisely the copy this has to catch.
    The failure is silent by construction: PostgreSQL integer division makes the "estimate"
    equal the bare weight lifted, a number of the right magnitude in the right units on which
    every downstream `>` and `max` still works.
    """
    offenders = [
        path.relative_to(REPO_ROOT)
        for path in _analytics_modules()
        if path.name != "estimates.py"
        and _DIVIDE_BY_THIRTY.search(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        f"the Epley divisor appears outside estimates.py: {offenders}. In PostgreSQL "
        "`weight * (1 + reps/30)` is integer division and returns the BARE WEIGHT -- verified, "
        "`SELECT 10 * (1 + 8/30)` returns 10. Call `estimates.estimate_1rm` instead."
    )
