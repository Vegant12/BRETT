"""MCP-05's runtime half: PostgreSQL refuses the write, not the application (T-06-03).

Phase 6 success criterion #4 asks for two things -- every tool annotated read-only, AND a write
attempt with no surface to reach. Plan 06-09 did the annotation. This module does the other half,
and the distinction is the entire point: ``ToolAnnotations(read_only_hint=True)`` is documented by
the SDK as a hint that "should not be relied upon for security enforcement". It constrains
nothing. It is a label on a box, and this project's only copy of seventeen months of training
history is inside the box.

``read_only_session`` sets ``postgresql_readonly=True`` on the connection before the first query,
which makes asyncpg open the transaction with ``READ ONLY``, which makes the SERVER raise on any
INSERT, UPDATE or DELETE. That is a control. These tests drive real writes against a real
PostgreSQL to prove it -- every one of them is ``@pytest.mark.integration``, because a mocked
database cannot refuse anything and a test against one would prove only that the mock was
configured to raise.

Two findings recorded here because they contradict what the documentation would lead you to
expect:

* **It works at the DEFAULT transaction isolation level.** SQLAlchemy's PostgreSQL documentation
  pairs the read-only flag with SERIALIZABLE in its examples, which reads like a requirement. It
  is not one. Adding SERIALIZABLE would buy serialization-failure retries on queries that write
  nothing, for no benefit -- so the setting is deliberately absent, and its absence is
  deliberately written down here so nobody "fixes" it later.
* **The flag does not leak back into the pooled connection.** Verified by
  ``test_the_readonly_flag_does_not_leak_into_the_pool``, and it is the assumption with the
  nastiest failure mode if it were ever wrong.

These tests build a minimal fake context instead of going through ``Client(mcp)``, so the thing
under test is ``read_only_session`` itself rather than a tool that happens to use it -- except for
the last test, which is deliberately end-to-end. Raw ``text()`` is used freely: ``SHOW
transaction_read_only`` has no SQLAlchemy Core equivalent, and ``test_mcp_isolation.py``'s static
guards walk ``app/mcp/``, not ``backend/tests/``.
"""

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, insert, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import DEFAULT_USER_ID
from app.core.time import utc_now
from app.db.models.sync_state import SyncState
from app.mcp.context import AppContext
from app.mcp.tools._common import read_only_session
from tests.conftest import GoldenBuilder, GoldenExercise, GoldenSet

# A resource name no production code path ever writes, so the leak test's real write cannot
# collide with the `sync_state` rows the Hevy fixtures and repositories create.
_LEAK_PROBE_RESOURCE = "readonly-leak-probe"

# The string PostgreSQL's own error class carries. Asserted by NAME rather than by importing
# `asyncpg.exceptions.ReadOnlySQLTransactionError`, so the assertion survives a driver swap to
# psycopg3 -- which raises its own class with the same SQLSTATE (25006) and the same name.
_READ_ONLY_ERROR = "ReadOnlySQLTransaction"


@dataclass
class _FakeRequestContext:
    """The one attribute ``read_only_session`` reads off ``ctx.request_context``."""

    lifespan_context: AppContext


@dataclass
class _FakeCtx:
    """The one attribute ``read_only_session`` reads off ``ctx``.

    A hand-built stand-in rather than a real ``Context[AppContext]``: constructing one of those
    means constructing a request, a session and a server, none of which this module is testing.
    What ``read_only_session`` actually needs is a sessionmaker reachable at
    ``ctx.request_context.lifespan_context.sessionmaker``, and that is exactly what this provides.
    """

    request_context: _FakeRequestContext


def _fake_ctx(sessionmaker: async_sessionmaker[AsyncSession]) -> Any:
    """Wrap a sessionmaker in the shape a tool's ``ctx`` has.

    Returns ``Any`` on purpose: the real parameter is typed ``Context[AppContext]`` and a cast
    here would be a longer way of saying the same thing while implying the fake is one.
    """
    return _FakeCtx(
        request_context=_FakeRequestContext(lifespan_context=AppContext(sessionmaker=sessionmaker))
    )


def _error_class_names(error: BaseException) -> list[str]:
    """Every exception class name in the ``__cause__``/``.orig`` chain below ``error``.

    SQLAlchemy wraps the driver's exception, and the asyncpg dialect wraps it again in its own
    DBAPI shim, so the class that actually names the failure can sit two levels down. Walking the
    chain and asserting on the collected names is what makes this robust to how many layers the
    stack decides to add.
    """
    names: list[str] = []
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        names.append(type(current).__name__)
        nxt = getattr(current, "orig", None) or current.__cause__
        current = nxt if isinstance(nxt, BaseException) else None
    return names


@pytest.mark.integration
async def test_the_transaction_is_actually_read_only(client: TestClient) -> None:
    """PostgreSQL itself reports the transaction as read-only.

    The cheapest possible proof, and the one that localises every other failure in this module: if
    this is ``off``, the execution option never reached the connection and the INSERT/UPDATE/DELETE
    tests below are failing for a reason that has nothing to do with those statements.

    The ``client`` fixture is taken even though no HTTP request is made (Pitfall 7) -- it is what
    assigns ``app.state.sessionmaker``, which is the object ``mcp_lifespan`` hands to a tool.
    """
    app = client.app
    ctx = _fake_ctx(app.state.sessionmaker)

    async with read_only_session(ctx) as session:
        assert await session.scalar(text("SHOW transaction_read_only")) == "on"


@pytest.mark.integration
async def test_an_insert_is_refused_by_the_server(client: TestClient) -> None:
    """An INSERT inside a tool's session raises from PostgreSQL, not from a Python guard.

    MCP-05 and Phase 6 success criterion #4. The requirement is not "no tool contains an INSERT" --
    that is a code-review property that survives exactly as long as everyone keeps reviewing. The
    requirement is that a write has no surface to reach, which means the server must refuse one
    that is genuinely attempted. So this test genuinely attempts one.
    """
    app = client.app
    ctx = _fake_ctx(app.state.sessionmaker)

    async with read_only_session(ctx) as session:
        with pytest.raises(DBAPIError) as excinfo:
            await session.execute(text("INSERT INTO workouts (id) VALUES (gen_random_uuid())"))

    names = _error_class_names(excinfo.value)
    assert any(_READ_ONLY_ERROR in name for name in names), (
        "MCP-05 / Phase 6 success criterion #4: the INSERT was rejected, but not by PostgreSQL's "
        f"read-only transaction check. Exception chain was {names}. A NOT NULL or foreign-key "
        "violation here would mean the transaction was writable and the statement merely invalid."
    )


@pytest.mark.integration
async def test_an_update_and_a_delete_are_refused_too(client: TestClient) -> None:
    """UPDATE and DELETE are refused on the same terms as INSERT.

    Tested explicitly because "read-only" that only stops INSERT is not read-only, and an
    INSERT-only guarantee is exactly the shape a half-applied fix would leave behind. The UPDATE
    targets ``users.timezone`` and the DELETE targets ``sync_state`` -- two tables every tool
    already reads through ``local_timezone`` and ``build_freshness``, so both are reachable from a
    tool body today.
    """
    app = client.app
    ctx = _fake_ctx(app.state.sessionmaker)

    statements = {
        "UPDATE": text("UPDATE users SET timezone = 'UTC'"),
        "DELETE": text("DELETE FROM sync_state"),
    }

    for verb, statement in statements.items():
        async with read_only_session(ctx) as session:
            with pytest.raises(DBAPIError) as excinfo:
                await session.execute(statement)

        names = _error_class_names(excinfo.value)
        assert any(_READ_ONLY_ERROR in name for name in names), (
            f"MCP-05: {verb} was not refused by PostgreSQL's read-only transaction check. "
            f"Exception chain was {names}."
        )


@pytest.mark.integration
async def test_the_readonly_flag_does_not_leak_into_the_pool(client: TestClient) -> None:
    """A later plain session on the same engine is writable, and really writes.

    This is the assumption with the nastiest failure mode in the whole read-only design. If the
    ``readonly`` characteristic leaked back onto the pooled connection, the Hevy sync CLI and
    ``/health`` would start failing at random -- only after an MCP call had happened to check out
    and return that particular connection. Intermittent, unattributable, and it looks like a
    network problem for a week.

    So the assertion is not merely that ``SHOW transaction_read_only`` reads ``off``: it performs a
    real INSERT and a real DELETE and commits them, because "the flag is off" and "a write
    succeeds" are different claims and only the second one is the thing that matters.
    """
    app = client.app
    sessionmaker = app.state.sessionmaker
    ctx = _fake_ctx(sessionmaker)

    async with read_only_session(ctx) as session:
        assert await session.scalar(text("SHOW transaction_read_only")) == "on"

    probe_id = uuid.uuid4()
    async with sessionmaker() as plain:
        assert await plain.scalar(text("SHOW transaction_read_only")) == "off", (
            "T-06-17: the read-only characteristic followed the connection back into the pool. "
            "Every write path sharing this engine is now failing intermittently."
        )
        await plain.execute(
            insert(SyncState).values(
                id=probe_id,
                user_id=DEFAULT_USER_ID,
                provider="readonly-test",
                resource=_LEAK_PROBE_RESOURCE,
            )
        )
        await plain.commit()

        written = await plain.scalar(select(SyncState.id).where(SyncState.id == probe_id))
        assert written == probe_id, "the write reported success but no row landed"

        # Compensating delete rather than a rollback: the row was committed, so it has outlived
        # the transaction that made it and no rollback can reach it.
        await plain.execute(delete(SyncState).where(SyncState.id == probe_id))
        await plain.commit()
        assert await plain.scalar(select(SyncState.id).where(SyncState.id == probe_id)) is None


@pytest.mark.integration
async def test_the_session_is_rolled_back_on_exit(client: TestClient) -> None:
    """Leaving the context manager ends the transaction, every time.

    ``read_only_session`` rolls back in a ``finally``, unconditionally. Analytics never writes, so
    there is nothing to commit by construction -- the rollback is there to release the read
    snapshot promptly instead of holding it until the connection is returned to the pool, and to
    hand the connection back in a known state on the error path as well as the happy one.
    """
    app = client.app
    ctx = _fake_ctx(app.state.sessionmaker)

    captured: AsyncSession | None = None
    async with read_only_session(ctx) as session:
        captured = session
        await session.execute(text("SELECT 1"))
        assert session.in_transaction() is True

    assert captured is not None
    assert captured.in_transaction() is False, (
        "the snapshot is still open after the context manager exited; the unconditional rollback "
        "in read_only_session's finally is what is supposed to close it"
    )


@pytest.mark.integration
async def test_a_tool_call_leaves_no_rows_behind(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """A full composed tool call changes nothing in the database.

    The belt-and-braces check. ``fitness_get_training_summary`` is the heaviest composition in the
    phase -- it drives four analytics functions and seven aggregate queries through ONE
    ``read_only_session`` -- so if any layer under it had learned to write, this is where it would
    show. Every other test in this module proves a statement is refused; this one proves the real
    path never gets that far.

    ``committed_history`` rather than ``golden_workout`` because the tool opens its OWN session
    from the lifespan sessionmaker, on a different connection, and cannot see uncommitted rows at
    all.
    """
    from mcp import Client

    from app.mcp.server import mcp

    template = await committed_history.template(external_id="READONLY-T001", title="Readonly Probe")
    await committed_history.workout(
        start_time=utc_now() - dt.timedelta(days=1),
        exercises=[
            GoldenExercise(
                template_external_id=template,
                title="Readonly Probe",
                sets=[GoldenSet(weight_kg=None, reps=8), GoldenSet(weight_kg=None, reps=8)],
            )
        ],
    )
    await session.commit()

    before = await session.scalar(text("SELECT count(*) FROM workouts"))
    assert before == 1, "the fixture must have seeded something, or this test proves nothing"

    async with Client(mcp) as mcp_client:
        result = await mcp_client.call_tool("fitness_get_training_summary", {"weeks": 4})

    assert result.is_error is False

    # A fresh transaction, so the count is read after the tool's own transaction has ended rather
    # than from a snapshot taken before it started.
    await session.rollback()
    after = await session.scalar(text("SELECT count(*) FROM workouts"))
    assert after == before, (
        "MCP-05: a read-only tool call changed the workout count from "
        f"{before} to {after}. The composed path is not read-only end to end."
    )
