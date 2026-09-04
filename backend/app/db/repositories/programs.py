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
import secrets
import uuid
from collections.abc import Sequence

from sqlalchemy import func, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.schemas import TrainingProgram
from app.db.models.program import ProgramPeriod, ProgramSwitchToken

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


async def issue_switch_token(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    from_period_id: uuid.UUID,
    to_program: TrainingProgram,
    ttl: dt.timedelta = SWITCH_TOKEN_TTL,
) -> tuple[str, dt.datetime]:
    """Mint one single-use confirmation nonce. Returns `(nonce, expires_at)`.

    `expires_at` is computed by the DATABASE (`now() + :ttl`) and read back with RETURNING,
    never by the application clock: the value is compared against `now()` inside the consume
    predicate, and two clocks disagreeing by a minute is a five-minute TTL that is sometimes
    four and sometimes six.

    `ttl` is a parameter with the D-11 default rather than a hardcoded constant so an
    already-expired token is CONSTRUCTIBLE in a test -- the expiry path is a security
    control, and a control no test can reach is a control nobody has checked.
    """
    nonce = secrets.token_urlsafe(_NONCE_BYTES)
    stmt = (
        insert(ProgramSwitchToken)
        .values(
            id=uuid.uuid4(),
            user_id=user_id,
            nonce=nonce,
            from_period_id=from_period_id,
            to_program=to_program.value,
            expires_at=func.now() + ttl,
        )
        .returning(ProgramSwitchToken.expires_at)
    )
    expires_at = await session.scalar(stmt)
    if expires_at is None:  # pragma: no cover - RETURNING on a successful INSERT always yields
        raise RuntimeError("issue_switch_token: INSERT ... RETURNING produced no row")
    return nonce, expires_at


async def consume_switch_token(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    nonce: str,
    to_program: TrainingProgram,
) -> uuid.UUID | None:
    """Atomically spend the nonce. Returns the authorized `from_period_id`, or `None`.

    `None` covers four cases deliberately indistinguishably: no such nonce, wrong target
    program, already consumed, expired. Distinguishing them in the return value would tell a
    caller which guess was closest, and none of the four is a state the model should be
    coached around -- it re-reads and asks again.

    ONE statement, not select-then-update. All four predicates and the mutation happen in the
    same round trip, so there is no window in which two concurrent confirmations both see an
    unconsumed row (PITFALLS #13's "consume atomically"). `to_program` is IN the WHERE clause
    rather than checked afterwards: a mismatched argument then leaves the nonce untouched and
    still usable for the correct call inside its TTL, instead of burning a valid token on a
    typo.

    `user_id` is in the WHERE list too (ASVS V4). The nonce is globally unique, so this is
    belt-and-braces -- and it is exactly the predicate whose absence turns a unique-string
    lookup into a cross-tenant one the day a second user exists.
    """
    stmt = (
        update(ProgramSwitchToken)
        .where(
            ProgramSwitchToken.user_id == user_id,
            ProgramSwitchToken.nonce == nonce,
            ProgramSwitchToken.to_program == to_program.value,
            ProgramSwitchToken.consumed_at.is_(None),
            ProgramSwitchToken.expires_at > func.now(),
        )
        .values(consumed_at=func.now())
        .returning(ProgramSwitchToken.from_period_id)
    )
    return await session.scalar(stmt)


async def close_period_and_open_new(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    from_period_id: uuid.UUID,
    to_program: TrainingProgram,
    today: dt.date,
) -> ProgramPeriod | None:
    """Close the authorized period and open the new one. Returns the NEW period, or `None`.

    `None` means the period the nonce was issued against is no longer open -- something else
    switched the program between issue and confirm. The caller must NOT commit in that case;
    returning `None` rather than raising is what lets the tool report `not_applied` with a
    reason instead of degrading to `unknown` (PITFALLS #15: those are different facts).

    The close is `UPDATE ... WHERE id = :from_period_id AND ended_on IS NULL`, and the
    zero-rows case is the check -- a SELECT-then-UPDATE would re-open the race the atomic
    consume just closed.

    `ended_on` is set to `today` and the new period's `started_on` is the SAME `today`
    (D-09: a switch always starts on the user's local today, never a backdated date). The two
    periods therefore touch on one day; `get_periods_overlapping`'s inclusive predicates
    report both for that day, which is correct -- the window genuinely contains both.

    The close MUST precede the insert: the partial unique index permits only one open period,
    so inserting first would raise `IntegrityError` and turn an ordinary "someone else
    switched" outcome into an exception the tool can only report as `unknown`.
    """
    close_stmt = (
        update(ProgramPeriod)
        .where(
            ProgramPeriod.id == from_period_id,
            ProgramPeriod.user_id == user_id,
            ProgramPeriod.ended_on.is_(None),
        )
        .values(ended_on=today)
        .returning(ProgramPeriod.id)
    )
    closed_id = await session.scalar(close_stmt)
    if closed_id is None:
        return None

    new_period_id = uuid.uuid4()
    insert_stmt = insert(ProgramPeriod).values(
        id=new_period_id,
        user_id=user_id,
        program=to_program.value,
        started_on=today,
        ended_on=None,
    )
    await session.execute(insert_stmt)
    new_period = await session.get(ProgramPeriod, new_period_id)
    if new_period is None:  # pragma: no cover - the insert above just created this row
        raise RuntimeError("close_period_and_open_new: newly inserted period not found")
    return new_period
