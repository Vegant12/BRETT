"""Read and write the active training program's history (GOAL-01, GOAL-03, D-07).

D-07: this module is the append-only history's ONE writer. `user_program_history` is never
UPDATEd in place except to close a period (`ended_on`), and `program_switch_tokens` is never
UPDATEd except to consume it (`consumed_at`) -- both writes are here, nowhere else.

Every function takes an `AsyncSession` positionally and never commits. The CALLER owns the
transaction -- PITFALLS #15 requires the switch's commit to be the LAST statement the TOOL
executes, so a helper that committed on its own would make that impossible.

This is the ONE place under `app/` outside the integrations layer that constructs a `program`
write. `app/mcp/tools/programs.py` (Plan 04) must therefore never import `insert`/`update`/
`delete` itself -- 12-RESEARCH.md Pitfall A, enforced by `test_mcp_isolation._WRITE_IMPORT`
across the whole `app/mcp/` package with no allowlist.
"""

import datetime as dt
import uuid
from collections.abc import Sequence

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.program import ProgramPeriod

# D-11. Five minutes: long enough for Claude to relay the warning and the user to answer,
# short enough that a token found in a scrolled-back conversation is already dead.
SWITCH_TOKEN_TTL = dt.timedelta(minutes=5)

# PITFALLS #13's own recommendation. `secrets`, never `random`: this value is the entire
# confirmation gate, so it must be CSPRNG-backed. 16 bytes -> a 22-character urlsafe string,
# comfortably inside the String(64) column.
_NONCE_BYTES = 16


async def get_active_period(session: AsyncSession, *, user_id: uuid.UUID) -> ProgramPeriod | None:
    """The currently open period -- `ended_on IS NULL`. At most one row, by the partial
    unique index; `None` only on a database whose migrations ran before any user existed."""
    return await session.scalar(
        select(ProgramPeriod).where(
            ProgramPeriod.user_id == user_id, ProgramPeriod.ended_on.is_(None)
        )
    )


async def get_periods_overlapping(
    session: AsyncSession, *, user_id: uuid.UUID, window_start: dt.date, window_end: dt.date
) -> Sequence[ProgramPeriod]:
    """Every period touching the inclusive window, ascending by `started_on`.

    More than one row means the window STRADDLES a switch (D-10). Ascending order lets the
    caller name the prior program and the switch date without a second query. The open
    period (`ended_on IS NULL`) is treated as extending to infinity, which is what `or_`
    below expresses -- a naive `ended_on >= window_start` would silently exclude the
    CURRENT period from every window.
    """
    stmt = (
        select(ProgramPeriod)
        .where(
            ProgramPeriod.user_id == user_id,
            ProgramPeriod.started_on <= window_end,
            or_(
                ProgramPeriod.ended_on.is_(None),
                ProgramPeriod.ended_on >= window_start,
            ),
        )
        .order_by(ProgramPeriod.started_on)
    )
    return (await session.scalars(stmt)).all()


async def get_recent_periods(
    session: AsyncSession, *, user_id: uuid.UUID, limit: int = 2
) -> Sequence[ProgramPeriod]:
    """The most recent periods, newest first. `limit=2` answers "what am I on, and what did
    it replace" (ROADMAP success criterion #1) in one query.

    Ordered by `started_on DESC, ended_on NULLS FIRST` so the open period sorts ahead of a
    period closed on the same day -- a same-day switch is legal (D-09 always starts today)
    and an unordered tie would make the read tool's answer depend on the planner.
    """
    stmt = (
        select(ProgramPeriod)
        .where(ProgramPeriod.user_id == user_id)
        .order_by(
            ProgramPeriod.started_on.desc(),
            ProgramPeriod.ended_on.is_(None).desc(),
        )
        .limit(limit)
    )
    return (await session.scalars(stmt)).all()
