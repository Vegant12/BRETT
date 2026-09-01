"""docs/coaching-instructions.md <-> live MCP registry drift guard (COACH-01).

This is a test rather than a review checklist because the failure it catches is
silent and remote. A tool rename passes every existing test -- the registry test
is updated in the same commit -- while the document keeps telling Claude to call
the old name inside a user's Project, where the only symptom is a tool call that
errors mid-conversation with no connection to the rename that caused it.

Static assertions over a committed file plus an in-memory `Client(mcp)` read: no
container, no network, and deliberately no integration marker.

`from app.mcp.server import mcp` is repeated inside every test and never written
at module scope, for the reason `test_mcp_tool_schemas.py` spells out: `conftest`
seeds the MCP environment at module import, and `app.mcp.server` freezes the
token verifier and the Host allowlist at ITS import. A module-scope import would
run that bootstrap during pytest's collection phase.
"""

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

REPO_ROOT = Path(__file__).resolve().parents[2]
COACHING_DOC = REPO_ROOT / "docs" / "coaching-instructions.md"

# Every tool reference in the document, wherever it appears -- table cell, prose
# sentence or annotated example. Deliberately NOT anchored to backticks or to the
# table: a name that drifts inside a sentence is exactly as wrong as one that
# drifts inside the mapping table, and Claude reads both.
_TOOL_TOKEN = re.compile(r"fitness_[a-z_]+")

# `fitness_ping` is the Phase 2 connectivity canary, not an analytics tool. The
# document happens to name it, but a future edit that drops it in favour of the
# twelve tools that answer training questions is an editorial choice, not drift --
# so the "nothing is missing" direction excludes it while the "nothing is
# invented" direction does not.
_CANARY = "fitness_ping"

# D-08: the document is pasted into a Claude Project's custom instructions. The
# practical ceiling is unverified and ~8,000 characters; 9,000 is the point past
# which "it silently did not all fit" becomes the likely failure, and that failure
# is invisible from this repo. Characters, not bytes -- the document is full of em
# dashes and arrows, and a byte budget would punish punctuation rather than length.
_PASTE_CEILING_CHARS = 9_000

# ROADMAP criterion #4 is "Claude correctly flags stale or sparse data when
# present", and it is unachievable if the document never names the fields that
# carry the signal. Written out as literals rather than introspected from
# `app.analytics.schemas`: a test that derives the names from the same source the
# document was written against would keep passing after a rename of both.
_REQUIRED_METADATA_FIELDS = (
    "data_available",
    "sessions_in_window",
    "insufficient_data",
    "earliest_data_at",
    "freshness.resources",
)


@pytest.fixture(scope="module")
def document() -> str:
    return COACHING_DOC.read_text(encoding="utf-8")


@pytest.fixture
def _mcp_state() -> Iterator[None]:
    """Populate `app.state.sessionmaker` without a container.

    Lifted from `test_mcp_tool_schemas.py` for the same reason it exists there:
    `Client(mcp)` enters `mcp_lifespan`, which reads `app.state.sessionmaker`, and
    outside a `TestClient` the FastAPI lifespan has never run. SQLAlchemy defers
    connection until first use and `tools/list` issues no query, so this engine is
    created and never dialled.
    """
    from app.config import get_settings
    from app.main import app

    engine = create_async_engine(get_settings().async_database_url)
    preexisting = getattr(app.state, "sessionmaker", None)
    app.state.sessionmaker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        yield
    finally:
        if preexisting is not None:
            app.state.sessionmaker = preexisting
        engine.sync_engine.dispose()


def _documented_names(document: str) -> set[str]:
    """Every distinct tool name the document mentions.

    `fitness_[a-z_]+` is greedy over trailing underscores, so a name written as
    `` `fitness_get_plateaus`_ `` in emphasised prose would otherwise be reported
    as an invented tool. Strip the trailing underscore rather than tightening the
    pattern: a stricter regex would stop matching names in running text, which is
    precisely where drift hides.
    """
    return {token.rstrip("_") for token in _TOOL_TOKEN.findall(document)}


async def _registry_names() -> set[str]:
    from mcp import Client

    from app.mcp.server import mcp

    async with Client(mcp) as mcp_client:
        return {tool.name for tool in (await mcp_client.list_tools()).tools}


async def test_every_tool_the_document_names_exists_in_the_registry(
    document: str, _mcp_state: None
) -> None:
    """Nothing invented: every name in the document is a name the server serves."""
    names = await _registry_names()
    unknown = _documented_names(document) - names

    assert unknown == set(), (
        f"COACH-01 violated: docs/coaching-instructions.md names {sorted(unknown)}, which the "
        f"live MCP registry does not serve. A user with this document pasted into a Claude "
        f"Project will get a failing tool call mid-conversation, with nothing pointing at the "
        f"rename that caused it. Registry: {sorted(names)}"
    )


async def test_every_registered_tool_appears_in_the_document(
    document: str, _mcp_state: None
) -> None:
    """Nothing missing: all twelve analytics tools are documented.

    A tool Claude is never told about is a tool Claude will not reach for, which
    makes it functionally undeployed however green its own tests are.
    """
    names = await _registry_names()
    documented = _documented_names(document)
    undocumented = (names - {_CANARY}) - documented

    assert undocumented == set(), (
        f"COACH-01 violated: the MCP registry serves {sorted(undocumented)}, which "
        f"docs/coaching-instructions.md never names. Claude is not told these tools exist, so "
        f"it will answer from a narrower set than the server actually offers -- add each to the "
        f"'Which tool answers which question' table with the question it answers."
    )


def test_the_document_names_the_metadata_fields_claude_must_read(document: str) -> None:
    """ROADMAP criterion #4: the staleness and sparsity signals are named, exactly."""
    missing = [field for field in _REQUIRED_METADATA_FIELDS if field not in document]

    assert missing == [], (
        f"COACH-01 violated: docs/coaching-instructions.md no longer names {missing}. These are "
        f"the fields that carry the freshness and coverage signal on every analytics response; a "
        f"document that does not name them cannot make Claude flag stale or sparse data, and the "
        f"resulting answers look confident and are unqualified."
    )


def test_the_document_fits_a_project_custom_instruction_paste(document: str) -> None:
    """D-08: the document is pasted whole, so its length is part of its contract."""
    length = len(document)

    assert length <= _PASTE_CEILING_CHARS, (
        f"COACH-01 violated: docs/coaching-instructions.md is {length} characters, over the "
        f"{_PASTE_CEILING_CHARS}-character ceiling for a Claude Project custom-instructions "
        f"paste. An over-long paste is truncated silently at the client, so the sections at the "
        f"end simply stop applying with no error anywhere. Cut prose before cutting the tool "
        f"mapping table."
    )
