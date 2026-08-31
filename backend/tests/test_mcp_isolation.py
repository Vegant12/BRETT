"""The `app/mcp/` boundary, asserted statically over committed source.

No container, no network, and deliberately NO integration marker -- a boundary violation must
fail the FAST suite on the commit that introduces it, not after a deploy. This is the sibling of
`test_analytics_isolation.py` and carries its regexes verbatim; the guards that are new here are
the exception-interpolation ban (MCP-06) and the `@safe_tool` coverage check.

The boundary is ONE-DIRECTIONAL and it points INWARD. MCP tools call `app/analytics/` and
`app/db/repositories/`; nothing under `app/mcp/` may write, build raw SQL, name a provider, or put
an exception's text into anything it returns.

**Why every check runs over a CODE-ONLY projection of the source rather than over the raw text.**
Modules under `app/mcp/` deliberately discuss the very patterns being banned. `_common.safe_tool`'s
docstring quotes the SDK's behaviour verbatim -- it contains the literal strings
`TextContent(text=str(e))` and `ToolError(f"Error executing tool {name}: {e}")`, because naming the
exact leak is what makes the guard's existence legible. A bare substring check would therefore fail
on the sentence documenting the rule, which is the trap already recorded at
`test_hevy_isolation.py:88-93`. Anchoring alone does not save this one: `str(e)` has no line
position to anchor on.

So `_code_only` blanks every comment, string literal and f-string LITERAL segment, preserving line
and column offsets so the anchored regexes still mean what they say. What survives is executable
code -- including f-string INTERPOLATIONS, which tokenize as ordinary `{`/NAME/`}` in Python 3.12+,
so `return f"failed: {e}"` is still caught while the docstring quoting it is not. That is strictly
what these guards are trying to express: "no module may DO this", not "no module may mention it".
"""

import io
import re
import tokenize
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MCP = REPO_ROOT / "backend" / "app" / "mcp"

# Anchored at the START of a line (modulo indentation): a mention in a docstring or comment --
# of which there are several, deliberately -- must not be read as an import.
_INTEGRATIONS_IMPORT = re.compile(r"^\s*(?:import|from)\s+app\.integrations", re.MULTILINE)

# S608 belt-and-braces: no hand-built SQL string may reach the driver from this package. Both
# import spellings are covered -- the bare `text(` of `from sqlalchemy import text`, and the
# qualified `sa.text(` / `sqlalchemy.text(` -- because a guard with one spelling missing is a
# guard with a documented way around it.
_RAW_SQL_TEXT = re.compile(r"(?<![\w.])(?:(?:sa|sqlalchemy)\.)?text\s*\(")

# Read-only in v1 (MCP-05). `session_ids.add(...)` on a Python set is fine and deliberately not
# matched -- only session-bound mutations are.
_SESSION_WRITE = re.compile(r"\bsession\.(?:commit|flush|add|add_all)\s*\(")
_WRITE_IMPORT = re.compile(
    r"^\s*from\s+sqlalchemy\s+import\s+.*\b(?:insert|update|delete)\b", re.MULTILINE
)

# C-2: `Decimal`, never `float`. Anchored on the CONSTRUCTOR and the ANNOTATION positions, never
# the bare word -- `volume.py` and `comparison.py` both use the phrase "binary floating point" in
# prose explaining why they do not use one.
_FLOAT_USE = re.compile(r"(?<![\w.])float\s*\(|:\s*float\b|->\s*float\b|\[\s*float\s*[],]")

# MCP-06 / Pitfall 3: no module may interpolate an exception into anything it returns. The
# `except` hands the exception to structlog -- which runs the FOUND-05 redaction chain -- and
# returns a constant-shaped payload. `mcp 2.0.0` returns any escaping exception's str() to Claude
# verbatim, and an asyncpg connection error carries the full DSN.
_EXC_IN_RETURN = re.compile(r"str\(exc\)|str\(e\)|repr\(e\)|repr\(exc\)|\{(?:exc|e|err|error)[!:}]")

# Every public tool coroutine, anchored at column zero -- a nested helper or a mention in prose is
# not a registered tool.
_PUBLIC_TOOL = re.compile(r"^async def (fitness_\w+)\(", re.MULTILINE)

# The tool modules that hold no registered tool, and are therefore exempt from the `@safe_tool`
# coverage check: the Phase 2 canary (which carries its own inline guard), the shared helpers, and
# the response models.
_NOT_TOOL_MODULES = frozenset({"ping.py", "_common.py", "schemas.py"})

def _mcp_modules() -> list[Path]:
    """Every committed module under `app/mcp/`.

    `rglob`, never a hand-maintained list: a new tool module must be covered by these boundaries
    the moment it exists, without anyone remembering to add it here.
    """
    return sorted(MCP.rglob("*.py"))


def _code_only(source: str) -> str:
    """`source` with every comment, string literal and f-string literal segment blanked out.

    Offsets are PRESERVED -- each blanked character becomes a space, and newlines survive -- so
    the anchored, multiline regexes above still match at the positions they were written for.

    f-string INTERPOLATIONS deliberately survive. Since Python 3.12 `tokenize` splits an f-string
    into `FSTRING_START` / `FSTRING_MIDDLE` / the interpolation's own tokens / `FSTRING_END`, so
    blanking `FSTRING_MIDDLE` removes the literal text while `{e}` stays visible as `{`, `e`, `}`.
    That is the difference between a module that returns an exception's text and a module whose
    docstring quotes the SDK doing so.
    """
    blank_types = {tokenize.COMMENT, tokenize.STRING, tokenize.FSTRING_MIDDLE}
    lines = source.splitlines(keepends=True)
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type not in blank_types:
            continue
        (start_row, start_col), (end_row, end_col) = token.start, token.end
        for row in range(start_row, end_row + 1):
            line = lines[row - 1]
            begin = start_col if row == start_row else 0
            finish = end_col if row == end_row else len(line)
            span = "".join(char if char.isspace() else " " for char in line[begin:finish])
            lines[row - 1] = line[:begin] + span + line[finish:]
    return "".join(lines)


def _module_code(path: Path) -> str:
    return _code_only(path.read_text(encoding="utf-8"))


def test_the_walk_actually_finds_files() -> None:
    """A guard on the guards: an empty walk would make every test below vacuously true.

    If `MCP` were ever wrong -- a moved package, a renamed directory -- `rglob` returns nothing
    and six boundary tests pass while checking nothing at all.
    """
    modules = _mcp_modules()

    # As of Phase 6 the package holds `__init__`, `auth`, `context`, `server`, `tools/__init__`,
    # `tools/_common`, `tools/schemas`, `tools/ping`, plus the seven tool modules `workouts`,
    # `volume`, `progression`, `records`, `comparison`, `body` and `summary` -- fifteen. The floor
    # rises with the package on purpose: a floor of 2 stays satisfied by a walk that has silently
    # lost most of what it was supposed to be checking.
    assert len(modules) >= 15, f"the walk found only {len(modules)} modules under {MCP}"


def test_mcp_never_writes() -> None:
    """MCP-05: v1 is read-only, and no tool may open its own writable path.

    `_common.read_only_session` opens a PostgreSQL READ ONLY transaction, and that is the RUNTIME
    guarantee -- the server refuses the write, whatever the code asks for. This test is the other
    half: that a future tool does not quietly construct its own session from the sessionmaker and
    bypass the helper entirely, which is the one way around the runtime control.
    """
    for path in _mcp_modules():
        source = _module_code(path)
        assert not _SESSION_WRITE.search(source), (
            f"MCP-05 violated: {path.relative_to(REPO_ROOT)} mutates the session. Every MCP tool "
            f"reads through `_common.read_only_session`, whose transaction PostgreSQL itself "
            f"refuses to let write"
        )
        assert not _WRITE_IMPORT.search(source), (
            f"MCP-05 violated: {path.relative_to(REPO_ROOT)} imports a write construct from "
            f"sqlalchemy. A read-only tool layer has no use for insert/update/delete"
        )


def test_mcp_uses_no_raw_sql_text() -> None:
    """ASVS V5 / S608: every predicate is a bound parameter, not a string fragment.

    Exercise names, workout ids and dates all arrive from the MODEL and cross a trust boundary
    into a query. They belong in SQLAlchemy Core expressions, where they are bound parameters by
    construction -- `_common.find_templates_by_title` is the pattern.

    `ping.py` is the single exemption, by name. Its `text("SELECT 1")` is a literal with no bound
    values and no user input anywhere near it, and it is the Phase 2 connectivity canary -- the
    cheapest available proof that the lifespan-wired session factory reached the tool layer.
    """
    offenders = [
        path.relative_to(REPO_ROOT)
        for path in _mcp_modules()
        if path.name != "ping.py" and _RAW_SQL_TEXT.search(_module_code(path))
    ]
    assert not offenders, (
        f"T-06-04 violated: raw SQL via text() outside ping.py: {offenders}. Build SQLAlchemy "
        "Core expressions so model-supplied values are bound parameters, never interpolated "
        "string fragments"
    )


def test_mcp_never_interpolates_an_exception() -> None:
    """MCP-06 / Pitfall 3: the detail goes to the log, the caller gets a coarse constant.

    `mcp 2.0.0` returns any escaping exception's `str()` to Claude verbatim, and an asyncpg
    connection error carries the full DSN -- user, password, host, port, database. Structlog's
    three-layer redaction (FOUND-05) does not touch that channel, because a tool result is not a
    log record. So an exception may be handed to `log.exception`, which DOES run the redaction
    chain, and never to a return value.

    Running over `_code_only` is what makes this test possible at all: `_common.safe_tool`'s
    docstring quotes both leaking expressions verbatim, and it should.
    """
    for path in _mcp_modules():
        source = _module_code(path)
        assert not _EXC_IN_RETURN.search(source), (
            f"MCP-06 violated: {path.relative_to(REPO_ROOT)} interpolates an exception. Hand it "
            f"to `log.exception` -- which runs the FOUND-05 redaction chain -- and return a "
            f"constant-shaped degraded payload. An asyncpg connection error carries the DSN"
        )


def test_mcp_uses_no_float() -> None:
    """C-2: exact `Decimal` end to end, across the tool layer too.

    A leaked float does not announce itself. It makes two arithmetically identical totals compare
    unequal, which surfaces as a flaky equality assertion somewhere far from the cause, and the
    usual "fix" is a tolerance -- at which point the analytics no longer have exact answers.
    `app/analytics/` bans it next door for the same reason, and a serialization layer that
    re-widens a Decimal into a float undoes that ban at the last possible moment.
    """
    for path in _mcp_modules():
        source = _module_code(path)
        assert not _FLOAT_USE.search(source), (
            f"C-2 violated: {path.relative_to(REPO_ROOT)} constructs or annotates a float. "
            "Binary floating point turns an exact Decimal comparison into a test that needs "
            "pytest.approx. Use Decimal."
        )


def test_every_tool_module_guards_its_public_tools() -> None:
    """MCP-06 / T-06-01, the structural half: every registered tool is wrapped in `@safe_tool`.

    An unguarded tool sends its exception text straight to Claude. `safe_tool` is the only thing
    standing between an asyncpg connection error and the model, so a tool that ships without the
    decorator is a leak with no other control behind it. `test_mcp_never_interpolates_an_exception`
    above bans writing the leak by hand; this bans forgetting the guard.

    The count assertion is the second half. Proving that every tool FOUND is decorated says
    nothing if the walk found none of them.
    """
    found: list[str] = []
    for path in sorted((MCP / "tools").glob("*.py")):
        if path.name in _NOT_TOOL_MODULES:
            continue
        lines = _module_code(path).splitlines()
        for index, line in enumerate(lines):
            match = _PUBLIC_TOOL.match(line)
            if match is None:
                continue
            found.append(match.group(1))
            # Walk BACKWARDS past blank lines. Comments are already blank in the code-only
            # projection, so a decorator separated from its `def` by an explanatory comment block
            # -- which `body.py` genuinely has -- still reads as adjacent.
            previous = index - 1
            while previous >= 0 and not lines[previous].strip():
                previous -= 1
            preceding = lines[previous].strip() if previous >= 0 else ""
            assert preceding.startswith("@safe_tool("), (
                f"MCP-06 violated: {match.group(1)} in {path.relative_to(REPO_ROOT)} is not "
                f"wrapped in @safe_tool. An unguarded tool sends its exception text -- DSN, "
                f"credentials and all -- straight to Claude. Found instead: {preceding!r}"
            )

    # The literal 12 is the whole point of this assertion, so it is written as a literal rather
    # than derived from anything: the loop above proves every tool it FINDS is decorated, which
    # says nothing if the walk found none of them.
    assert len(found) == 12, (
        f"expected 12 public tool coroutines under app/mcp/tools/, found {len(found)}: "
        f"{sorted(found)}. If a tool was added, register it in `server.py`, add it to "
        f"`EXPECTED_TOOLS` in test_mcp_tool_schemas.py, and raise this count -- all three, so a "
        f"new tool cannot ship unguarded and unnoticed"
    )


def test_mcp_does_not_import_integrations() -> None:
    """HEVY-05: the MCP layer is provider-NEUTRAL.

    Hevy's own docs say the API structure may change without notice. An `app.integrations` import
    here means a Hevy field rename becomes a TOOL rename -- and a tool rename breaks every saved
    Claude conversation that calls it. Provider details reach this layer only as already-normalized
    values from `app/analytics/` and `app/db/repositories/`.
    """
    for path in _mcp_modules():
        source = _module_code(path)
        assert not _INTEGRATIONS_IMPORT.search(source), (
            f"HEVY-05 violated: {path.relative_to(REPO_ROOT)} imports app.integrations. The MCP "
            f"layer is provider-neutral by design; a Hevy field rename must not become a tool "
            f"rename"
        )
