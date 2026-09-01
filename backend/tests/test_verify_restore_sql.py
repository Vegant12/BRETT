"""scripts/verify-restore.sql <-> mapped tables drift guard (D-02, DEPLOY-03).

The restore drill's whole value is that it compares EVERYTHING. A table added in a
later phase and forgotten in the digest query would make the next drill pass while
silently not checking the new data -- a false negative on the one procedure whose
entire purpose is catching data loss. Phase 7 plan 07-07 already proved this class
of failure is real here: eight tables existed in the code and had never reached
production, and every health signal in the system reported green.

Four things are guarded, and each maps to a way the drill could quietly stop being
a proof:

* **coverage** -- a mapped table missing from the query is data nobody compares;
* **read-only** -- this file is run by hand against the production branch, so a
  write verb reaching it is a write against real health data;
* **ordered aggregates** -- ``string_agg`` has no defined order without an explicit
  ``ORDER BY`` inside the call, so an unordered arm makes two byte-identical
  databases digest differently and turns every future drill into a coin flip;
* **no connection string** -- the file is committed, and a DSN in git is a
  full-access credential to real health data, forever (T-07-41).

Static assertions over a committed file: no container, no network, and deliberately
no integration marker -- drift must fail the fast suite on the commit that
introduces it, not at the next drill months later.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFY_SQL = REPO_ROOT / "scripts" / "verify-restore.sql"

# Every verb that could modify data or schema. ``update`` carries a trailing space
# so the word "updated" in a column name or comment is not a false positive; the
# rest have no such collision in SQL.
_WRITE_VERBS = ("insert", "update ", "delete", "drop", "truncate", "alter", "create")

# A DSN or a Neon host reaching this committed file is the leak T-07-41 exists to
# stop. ``ep-<id>.`` is the shape of every Neon endpoint hostname.
_CREDENTIAL_SHAPES = (
    re.compile(r"postgres(ql)?://", re.IGNORECASE),
    re.compile(r"neon\.tech", re.IGNORECASE),
    re.compile(r"\bep-[a-z0-9-]+\.", re.IGNORECASE),
)


def _sql_text() -> str:
    return VERIFY_SQL.read_text()


def _executable_sql() -> str:
    """The file with ``--`` comments stripped: what psql would actually execute.

    The read-only check has to run against this rather than the raw text, because
    the header comment legitimately explains what the query must never contain and
    would otherwise fail its own rule. Naive stripping is safe here precisely
    because the query holds no string literal containing ``--``; if one is ever
    added, this helper is the thing to fix, not the assertion.
    """
    stripped: list[str] = []
    for line in _sql_text().splitlines():
        head, separator, _tail = line.partition("--")
        stripped.append(head if separator else line)
    return "\n".join(stripped)


def _mapped_tables() -> set[str]:
    """Every table SQLAlchemy knows about.

    ``app.db.models`` is imported for its side effect: importing that package is
    what attaches each model to ``Base.metadata`` (see its own docstring, and
    ``migrations/env.py``, which imports it for the identical reason). Reading the
    inventory from the live metadata rather than from a hand-kept tuple is the
    entire point -- a hand-kept tuple drifts silently, which is the failure this
    module exists to prevent.
    """
    import app.db.models  # noqa: F401  -- import side effect populates Base.metadata
    from app.db.base import Base

    return set(Base.metadata.tables)


def _string_agg_arguments(sql: str) -> list[str]:
    """The argument text of every ``string_agg(...)`` call, by paren matching.

    Matching to the balanced closing paren rather than to the next ``)`` matters:
    the aggregated expression is itself a call (``md5(x::text)``), so a naive scan
    would cut the argument list off before reaching the ``ORDER BY``.
    """
    arguments: list[str] = []
    for match in re.finditer(r"string_agg\s*\(", sql, re.IGNORECASE):
        opening = match.end() - 1
        depth = 0
        for index in range(opening, len(sql)):
            if sql[index] == "(":
                depth += 1
            elif sql[index] == ")":
                depth -= 1
                if depth == 0:
                    arguments.append(sql[opening + 1 : index])
                    break
        else:  # pragma: no cover - only reachable on a malformed file
            raise AssertionError(
                f"D-02 violated: {VERIFY_SQL} has an unbalanced string_agg( call starting at "
                f"character {match.start()}; psql would reject the whole file and the drill "
                f"would produce no comparison at all"
            )
    return arguments


def test_the_digest_query_covers_every_mapped_table() -> None:
    """Every mapped table is compared, exactly once, and the list is not hand-kept.

    A table present in ``Base.metadata`` but absent from the query is data the
    restore drill does not look at. The drill would still print a clean ``diff``
    and still be recorded as a PASS -- which is worse than having no drill, because
    it manufactures confidence about data nobody checked.
    """
    sql = _sql_text()

    for table in sorted(_mapped_tables()):
        occurrences = re.findall(rf"\bFROM\s+{re.escape(table)}\b", sql, re.IGNORECASE)
        assert len(occurrences) == 1, (
            f"D-02 violated: {table!r} is mapped on Base.metadata but appears as a FROM target "
            f"in scripts/verify-restore.sql {len(occurrences)} times (expected exactly 1). A "
            f"missing table is data the restore drill silently does not compare; a duplicated "
            f"one double-counts and makes the digest output ambiguous. Add an arm for it."
        )


def test_the_digest_query_is_read_only() -> None:
    """No write verb survives comment-stripping.

    This file is run by an operator, by hand, against the PRODUCTION branch's
    connection string -- that is the whole point of the drill's step 5. A write verb
    reaching it is not a failed test, it is a write against real health data. The
    check runs on the comment-stripped text so the header can keep explaining the
    rule it is enforcing.
    """
    executable = _executable_sql().lower()

    for verb in _WRITE_VERBS:
        assert verb not in executable, (
            f"D-02/T-07-43 violated: scripts/verify-restore.sql contains the write verb "
            f"{verb.strip()!r} outside a comment. This query is executed against the live "
            f"production branch during the drill; it must only ever read."
        )


def test_the_digest_query_orders_every_aggregate() -> None:
    """Every ``string_agg`` names its own ordering.

    ``string_agg`` without ``ORDER BY`` inside the call has no defined order at all,
    so the same rows can digest to two different md5s on two runs of the same
    database. The drill would then report a mismatch between a branch and its own
    parent and a real restore would be abandoned over a bug in the proof, or --
    worse the other way -- a genuine mismatch would be dismissed as this known
    flakiness.
    """
    arguments = _string_agg_arguments(_sql_text())

    assert arguments, (
        "D-02 violated: scripts/verify-restore.sql contains no string_agg( call at all, so "
        "the comparison is row counts only -- and an identical count over corrupted rows "
        "passes, which is exactly what the digest exists to catch"
    )
    for argument in arguments:
        assert re.search(r"\border\s+by\b", argument, re.IGNORECASE), (
            f"D-02 violated: a string_agg( call in scripts/verify-restore.sql has no ORDER BY "
            f"inside the call, so its digest is not reproducible and two identical databases "
            f"can disagree. Arguments were: {argument.strip()!r}"
        )


def test_the_digest_query_contains_no_connection_string() -> None:
    """No DSN, and no Neon host, in a committed file (T-07-41).

    The drill's two connection strings live in shell variables and are never
    written down. An assertion here rather than a review habit because a DSN
    committed once is in the repository's history permanently, and it is a
    full-access credential to real health data.
    """
    sql = _sql_text()

    for shape in _CREDENTIAL_SHAPES:
        assert shape.search(sql) is None, (
            f"T-07-41 violated: scripts/verify-restore.sql matches the credential-shaped "
            f"pattern {shape.pattern!r}. Connection strings belong in $PROD_DSN / $DRILL_DSN "
            f"for the length of one shell session and nowhere else -- least of all in git."
        )
