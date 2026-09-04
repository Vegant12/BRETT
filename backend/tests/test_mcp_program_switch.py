"""GOAL-03's proof: the confirm-gated write tool, and the read tool that checks its result
(ROADMAP success criteria #3 and #4).

Both tools are called DIRECTLY through a fake `ctx`, never through `Client(mcp)` or the HTTP
transport, because registration lands in Plan 05 and the security property proven here is a
property of the TOOL BODY, not of the registry -- `test_mcp_isolation.py`'s own
`test_every_tool_module_guards_its_public_tools` already proves the count of registered tools
separately, and duplicating that proof here would couple this module to Plan 05 for no gain.

The `_FakeCtx`/`_FakeRequestContext`/`_fake_ctx` helpers are duplicated from
`test_mcp_readonly.py` rather than imported: no other test module in this suite imports
fixtures from a sibling test module (every cross-module import in `backend/tests/` goes through
`tests.conftest`), so duplication here follows the suite's existing convention rather than
introducing a new one.

The `client` fixture is taken by every test even though no HTTP request is made (mirrors
`test_mcp_readonly.py`'s own note on this) -- it is what assigns `app.state.sessionmaker`,
the object the fake `ctx` hands the tool, wired to the real test container.
"""

import datetime as dt
from dataclasses import dataclass
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.analytics.schemas import TrainingProgram
from app.core.time import utc_now
from app.db.models.program import ProgramPeriod, ProgramSwitchToken
from app.db.repositories.programs import get_active_period, get_recent_periods
from app.mcp.context import AppContext
from app.mcp.tools.program_switch import fitness_switch_training_program
from app.mcp.tools.programs import fitness_get_training_program
from tests.conftest import DEFAULT_USER_ID, GoldenBuilder
from tests.test_mcp_tools import LEAK_MARKERS

# Mirrors `test_mcp_tools.py:59`. Port 1 is reserved and never listening, so the connection
# fails immediately rather than hanging on a routable-but-silent host.
_DEAD_DB_URL = "postgresql+asyncpg://nobody:nopass@127.0.0.1:1/nodb"


@dataclass
class _FakeRequestContext:
    """The one attribute the tools read off ``ctx.request_context``."""

    lifespan_context: AppContext


@dataclass
class _FakeCtx:
    """The one attribute the tools read off ``ctx``.

    A hand-built stand-in rather than a real ``Context[AppContext]``: what the tools actually
    need is a sessionmaker reachable at ``ctx.request_context.lifespan_context.sessionmaker``,
    and that is exactly what this provides.
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


@pytest.mark.integration
async def test_warn_branch_writes_nothing_and_returns_a_token(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """SC#3 / T-12-01. Call with `program='cut'` and no token: `switch_status` is
    `not_applied`, `confirmation_token` is a non-empty string, `expires_at` is roughly five
    minutes ahead, and -- the actual assertion -- `get_active_period` still returns the
    lean_bulk period afterwards. Also assert `data_available is True`: this is a real answer,
    not a degradation.
    """
    await session.commit()
    ctx = _fake_ctx(client.app.state.sessionmaker)

    result = await fitness_switch_training_program(ctx, program=TrainingProgram.CUT)

    assert result.data_available is True
    assert result.switch_status.value == "not_applied"
    assert result.confirmation_token
    assert isinstance(result.confirmation_token, str)
    now = dt.datetime.now(dt.UTC)
    assert result.expires_at is not None
    assert now + dt.timedelta(minutes=4) < result.expires_at < now + dt.timedelta(minutes=6)

    active = await get_active_period(session, user_id=DEFAULT_USER_ID)
    assert active is not None
    assert active.program == "lean_bulk"


@pytest.mark.integration
async def test_the_token_is_not_the_program_name_or_anything_guessable(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """T-12-01. The returned token is at least 20 characters and contains neither the program
    name nor any substring a model could derive from its own arguments. A gate the model can
    construct is not a gate.
    """
    await session.commit()
    ctx = _fake_ctx(client.app.state.sessionmaker)

    result = await fitness_switch_training_program(ctx, program=TrainingProgram.CUT)

    token = result.confirmation_token
    assert token is not None
    assert len(token) >= 20
    assert "cut" not in token.lower()
    assert "lean_bulk" not in token.lower()
    assert "confirm" not in token.lower()


@pytest.mark.integration
async def test_confirm_atomic_switch_closes_the_old_period_and_opens_the_new(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """SC#3. Second call with the same program and the exact token: `switch_status` is
    `applied`, `previous_program` is lean_bulk, `switched_on` is the user's local today, and
    `get_active_period` now returns an open `cut` period while the lean_bulk period carries
    `ended_on = today`. Exactly one open period exists.
    """
    await session.commit()
    ctx = _fake_ctx(client.app.state.sessionmaker)
    warn = await fitness_switch_training_program(ctx, program=TrainingProgram.CUT)
    assert warn.confirmation_token is not None

    applied = await fitness_switch_training_program(
        ctx, program=TrainingProgram.CUT, confirmation_token=warn.confirmation_token
    )

    assert applied.switch_status.value == "applied"
    assert applied.active_program == TrainingProgram.CUT
    assert applied.previous_program == TrainingProgram.LEAN_BULK
    assert applied.switched_on is not None

    current = await get_active_period(session, user_id=DEFAULT_USER_ID)
    assert current is not None
    assert current.program == "cut"
    assert current.started_on == applied.switched_on

    recent = await get_recent_periods(session, user_id=DEFAULT_USER_ID, limit=2)
    assert len(recent) == 2
    previous_row = recent[1]
    assert previous_row.program == "lean_bulk"
    assert previous_row.ended_on == applied.switched_on

    open_count = await session.scalar(
        sa.select(sa.func.count())
        .select_from(ProgramPeriod)
        .where(ProgramPeriod.user_id == DEFAULT_USER_ID, ProgramPeriod.ended_on.is_(None))
    )
    assert open_count == 1


@pytest.mark.integration
async def test_replay_of_a_consumed_token_is_refused(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """SC#4 / T-12-03. Apply the switch, then call a third time with the SAME token: the
    result is `not_applied` and the active period is unchanged.
    """
    await session.commit()
    ctx = _fake_ctx(client.app.state.sessionmaker)
    warn = await fitness_switch_training_program(ctx, program=TrainingProgram.CUT)
    assert warn.confirmation_token is not None
    applied = await fitness_switch_training_program(
        ctx, program=TrainingProgram.CUT, confirmation_token=warn.confirmation_token
    )
    assert applied.switch_status.value == "applied"

    replay = await fitness_switch_training_program(
        ctx, program=TrainingProgram.CUT, confirmation_token=warn.confirmation_token
    )

    assert replay.switch_status.value == "not_applied"
    current = await get_active_period(session, user_id=DEFAULT_USER_ID)
    assert current is not None
    assert current.program == "cut"


@pytest.mark.integration
async def test_wrong_program_token_is_refused_without_being_consumed(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """SC#4 / T-12-02. Request a token for `cut`, then present it with `program='recomp'`:
    `not_applied`, nothing switched -- and then present it correctly for `cut` in the same
    test and assert it STILL works. Not burning the token on a mismatch is part of the
    design, not an accident.
    """
    await session.commit()
    ctx = _fake_ctx(client.app.state.sessionmaker)
    warn = await fitness_switch_training_program(ctx, program=TrainingProgram.CUT)
    assert warn.confirmation_token is not None

    wrong = await fitness_switch_training_program(
        ctx, program=TrainingProgram.RECOMP, confirmation_token=warn.confirmation_token
    )
    assert wrong.switch_status.value == "not_applied"
    active = await get_active_period(session, user_id=DEFAULT_USER_ID)
    assert active is not None
    assert active.program == "lean_bulk"

    correct = await fitness_switch_training_program(
        ctx, program=TrainingProgram.CUT, confirmation_token=warn.confirmation_token
    )
    assert correct.switch_status.value == "applied"


@pytest.mark.integration
async def test_expired_token_is_refused(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """SC#4 / T-12-04 / D-11. Seed an already-expired token with
    `GoldenBuilder.switch_token(expires_at=<past>)` bound to the real open period, present
    it, and assert `not_applied` with nothing switched.
    """
    active = await get_active_period(session, user_id=DEFAULT_USER_ID)
    assert active is not None
    await committed_history.switch_token(
        nonce="12-04-expired-nonce",
        from_period_id=active.id,
        to_program="cut",
        expires_at=utc_now() - dt.timedelta(minutes=1),
    )
    await session.commit()
    ctx = _fake_ctx(client.app.state.sessionmaker)

    result = await fitness_switch_training_program(
        ctx, program=TrainingProgram.CUT, confirmation_token="12-04-expired-nonce"
    )

    assert result.switch_status.value == "not_applied"
    current = await get_active_period(session, user_id=DEFAULT_USER_ID)
    assert current is not None
    assert current.program == "lean_bulk"


@pytest.mark.integration
async def test_a_fabricated_token_is_refused(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """T-12-01. A plausible-looking token the server never issued changes nothing. This is
    the literal shape of "the model made one up".
    """
    await session.commit()
    ctx = _fake_ctx(client.app.state.sessionmaker)

    result = await fitness_switch_training_program(
        ctx, program=TrainingProgram.CUT, confirmation_token="totally-fabricated-token-value"
    )

    assert result.switch_status.value == "not_applied"
    active = await get_active_period(session, user_id=DEFAULT_USER_ID)
    assert active is not None
    assert active.program == "lean_bulk"


@pytest.mark.integration
async def test_switching_to_the_current_program_is_refused_without_issuing_a_token(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """A no-op switch must not mint a credential. Assert `confirmation_token is None` AND
    that `program_switch_tokens` gained no row.
    """
    await session.commit()
    ctx = _fake_ctx(client.app.state.sessionmaker)
    before = await session.scalar(
        sa.select(sa.func.count())
        .select_from(ProgramSwitchToken)
        .where(ProgramSwitchToken.user_id == DEFAULT_USER_ID)
    )

    result = await fitness_switch_training_program(ctx, program=TrainingProgram.LEAN_BULK)

    assert result.switch_status.value == "not_applied"
    assert result.confirmation_token is None
    after = await session.scalar(
        sa.select(sa.func.count())
        .select_from(ProgramSwitchToken)
        .where(ProgramSwitchToken.user_id == DEFAULT_USER_ID)
    )
    assert after == before


@pytest.mark.integration
async def test_the_refusal_reason_does_not_say_which_check_failed(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """The four refusal paths (missing / wrong program / expired / already used) return the
    same reason text. Distinguishing them tells a caller which guess was closest.
    """
    active = await get_active_period(session, user_id=DEFAULT_USER_ID)
    assert active is not None
    await committed_history.switch_token(
        nonce="12-04-reason-expired",
        from_period_id=active.id,
        to_program="cut",
        expires_at=utc_now() - dt.timedelta(minutes=1),
    )
    await session.commit()
    ctx = _fake_ctx(client.app.state.sessionmaker)

    fabricated = await fitness_switch_training_program(
        ctx, program=TrainingProgram.CUT, confirmation_token="totally-fabricated-token"
    )
    expired = await fitness_switch_training_program(
        ctx, program=TrainingProgram.CUT, confirmation_token="12-04-reason-expired"
    )

    warn = await fitness_switch_training_program(ctx, program=TrainingProgram.CUT)
    assert warn.confirmation_token is not None
    wrong_program = await fitness_switch_training_program(
        ctx, program=TrainingProgram.RECOMP, confirmation_token=warn.confirmation_token
    )
    applied = await fitness_switch_training_program(
        ctx, program=TrainingProgram.CUT, confirmation_token=warn.confirmation_token
    )
    assert applied.switch_status.value == "applied"
    replayed = await fitness_switch_training_program(
        ctx, program=TrainingProgram.CUT, confirmation_token=warn.confirmation_token
    )

    reasons = {fabricated.reason, expired.reason, wrong_program.reason, replayed.reason}
    assert len(reasons) == 1


@pytest.mark.integration
async def test_degraded_payload_is_unknown_and_leaks_nothing(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """T-12-06 / PITFALLS #15. Drive the tool against a dead database -- the same trick
    `test_mcp_tools.py`'s degradation test uses, a sessionmaker over an unreachable URL --
    and assert `switch_status == 'unknown'` (never `not_applied`), `data_available is False`,
    and that the rendered payload contains none of `test_mcp_tools.LEAK_MARKERS`. Import
    `LEAK_MARKERS` rather than re-listing it.
    """
    await session.commit()
    dead = create_async_engine(_DEAD_DB_URL, connect_args={"timeout": 1}, pool_pre_ping=False)
    dead_sessionmaker = async_sessionmaker(dead, expire_on_commit=False, autoflush=False)
    ctx = _fake_ctx(dead_sessionmaker)
    try:
        result = await fitness_switch_training_program(ctx, program=TrainingProgram.CUT)
    finally:
        await dead.dispose()

    assert result.switch_status.value == "unknown"
    assert result.data_available is False

    rendered = repr(result.model_dump())
    for leak in LEAK_MARKERS:
        assert leak not in rendered, f"{leak!r} leaked into the degraded switch payload"


@pytest.mark.integration
async def test_the_read_tool_reports_the_program_and_what_it_replaced(
    client: TestClient, committed_history: GoldenBuilder, session: AsyncSession
) -> None:
    """SC#1. After a switch, `fitness_get_training_program` returns `program='cut'` with its
    `started_on`, and `previous_program='lean_bulk'` with that period's start and end dates.
    """
    await session.commit()
    ctx = _fake_ctx(client.app.state.sessionmaker)
    warn = await fitness_switch_training_program(ctx, program=TrainingProgram.CUT)
    assert warn.confirmation_token is not None
    applied = await fitness_switch_training_program(
        ctx, program=TrainingProgram.CUT, confirmation_token=warn.confirmation_token
    )
    assert applied.switch_status.value == "applied"

    result = await fitness_get_training_program(ctx)

    assert result.data_available is True
    assert result.program == TrainingProgram.CUT
    assert result.started_on == applied.switched_on
    assert result.previous_program == TrainingProgram.LEAN_BULK
    assert result.previous_period_ended_on == applied.switched_on
