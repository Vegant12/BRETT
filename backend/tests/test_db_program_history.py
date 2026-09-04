"""GOAL-01's proof: the active training program is DATA, not a constant.

The "one open period per user" invariant is enforced by PostgreSQL, not by application code
(PITFALLS #16), and migration 0006's D-08 seed comes from live synced training history rather
than a hardcoded date. Plan 01 covers schema, the partial index, and both branches of the seed.
Plan 02 (below the seed tests) proves the repository's six functions: period resolution
including the open-period-extends-forever edge, the atomic nonce consume's single-use/
target-binding/TTL/tenant-scoping properties, and the guarded close-then-open pair.
"""

import datetime as dt
import subprocess
import uuid
from collections.abc import Callable

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.analytics.schemas import TrainingProgram
from app.core.time import local_day
from app.db.models.program import ProgramPeriod, ProgramSwitchToken
from app.db.models.user import User
from app.db.models.workout import Workout
from app.db.repositories.programs import (
    close_period_and_open_new,
    consume_switch_token,
    get_active_period,
    get_periods_overlapping,
    get_recent_periods,
    issue_switch_token,
)
from tests.conftest import ANALYTICS_SECOND_USER_ID, DEFAULT_USER_ID, GoldenBuilder

# 17:30Z is 00:30 the NEXT day in Asia/Jakarta (UTC+7). Picked deliberately so the UTC
# calendar day and the Jakarta calendar day DIFFER -- otherwise a timezone bug would pass
# this test by accident.
_REWIND_WORKOUT_START = dt.datetime(2026, 1, 10, 17, 30, tzinfo=dt.UTC)


@pytest.mark.integration
async def test_migration_creates_both_tables_with_the_expected_columns(engine: AsyncEngine) -> None:
    """Queried from `information_schema`, not from `Base.metadata`: the model asserting
    against itself proves nothing about the DDL migrations actually produced."""
    async with engine.connect() as conn:
        period_columns = (
            await conn.execute(
                sa.text(
                    "select column_name from information_schema.columns "
                    "where table_schema = 'public' and table_name = 'user_program_history'"
                )
            )
        ).all()
        token_columns = (
            await conn.execute(
                sa.text(
                    "select column_name from information_schema.columns "
                    "where table_schema = 'public' and table_name = 'program_switch_tokens'"
                )
            )
        ).all()
    assert {row[0] for row in period_columns} == {
        "id",
        "user_id",
        "program",
        "started_on",
        "ended_on",
        "created_at",
        "updated_at",
    }
    assert {row[0] for row in token_columns} == {
        "id",
        "user_id",
        "nonce",
        "from_period_id",
        "to_program",
        "expires_at",
        "consumed_at",
        "created_at",
        "updated_at",
    }


@pytest.mark.integration
async def test_migration_partial_index_refuses_a_second_open_period(engine: AsyncEngine) -> None:
    """PITFALLS #16's invariant, enforced by PostgreSQL rather than by application code.

    The seeded open period already exists, so inserting a second `ended_on IS NULL` row for
    the same user must raise IntegrityError. A CLOSED period (ended_on set) inserted for the
    same user must SUCCEED in the same test, so the index is proven narrow rather than merely
    restrictive.
    """
    closed_id = uuid.uuid4()
    try:
        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(
                    sa.insert(ProgramPeriod).values(
                        id=uuid.uuid4(),
                        user_id=DEFAULT_USER_ID,
                        program="cut",
                        started_on=dt.date(2026, 1, 1),
                        ended_on=None,
                    )
                )
        async with engine.begin() as conn:
            await conn.execute(
                sa.insert(ProgramPeriod).values(
                    id=closed_id,
                    user_id=DEFAULT_USER_ID,
                    program="cut",
                    started_on=dt.date(2026, 1, 1),
                    ended_on=dt.date(2026, 1, 15),
                )
            )
    finally:
        async with engine.begin() as conn:
            await conn.execute(sa.delete(ProgramPeriod).where(ProgramPeriod.id == closed_id))


@pytest.mark.integration
async def test_seed_is_one_open_lean_bulk_period(engine: AsyncEngine) -> None:
    """Exactly one row, program='lean_bulk', ended_on IS NULL, for DEFAULT_USER_ID."""
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                sa.select(ProgramPeriod.program, ProgramPeriod.ended_on).where(
                    ProgramPeriod.user_id == DEFAULT_USER_ID
                )
            )
        ).all()
    assert len(rows) == 1
    program, ended_on = rows[0]
    assert program == "lean_bulk"
    assert ended_on is None


@pytest.mark.integration
async def test_seed_falls_back_to_the_users_local_creation_day(engine: AsyncEngine) -> None:
    """RESEARCH Open Question 1: a database migrated before the first Hevy sync still gets a
    period. The container is migrated at session start with zero workouts, so the seeded
    `started_on` must equal `local_day(users.created_at, users.timezone)` -- NOT a NULL row
    and NOT a missing row.
    """
    async with engine.connect() as conn:
        user_row = (
            await conn.execute(
                sa.select(User.created_at, User.timezone).where(User.id == DEFAULT_USER_ID)
            )
        ).one()
        seeded_started_on = (
            await conn.execute(
                sa.select(ProgramPeriod.started_on).where(
                    ProgramPeriod.user_id == DEFAULT_USER_ID,
                    ProgramPeriod.ended_on.is_(None),
                )
            )
        ).scalar_one()
    assert seeded_started_on == local_day(user_row.created_at, user_row.timezone)


@pytest.mark.integration
async def test_seed_starts_on_the_earliest_local_training_day(
    engine: AsyncEngine,
    alembic: Callable[..., subprocess.CompletedProcess[str]],
    restore_schema: None,
) -> None:
    """D-08: the seed reflects when training under this program actually began.

    Exercised by rewinding: `alembic downgrade 0005`, commit a workout whose `start_time` is
    a known instant, `alembic upgrade head`, then assert the seeded `started_on` equals that
    workout's LOCAL day (Asia/Jakarta), not its UTC day and not today. `restore_schema`
    guarantees head either way; the workout is cleaned up explicitly since `workouts` survives
    the 0006 downgrade/upgrade cycle untouched.
    """
    assert alembic("downgrade", "0005").returncode == 0
    workout_id = uuid.uuid4()
    try:
        async with engine.begin() as conn:
            await conn.execute(
                sa.insert(Workout).values(
                    id=workout_id,
                    user_id=DEFAULT_USER_ID,
                    provider="hevy",
                    external_id="12-01-seed-rewind",
                    title="Seed Rewind Fixture",
                    description=None,
                    routine_external_id=None,
                    start_time=_REWIND_WORKOUT_START,
                    end_time=_REWIND_WORKOUT_START + dt.timedelta(hours=1),
                    provider_created_at=_REWIND_WORKOUT_START,
                    provider_updated_at=_REWIND_WORKOUT_START,
                )
            )
        assert alembic("upgrade", "head").returncode == 0
        async with engine.connect() as conn:
            seeded_started_on = (
                await conn.execute(
                    sa.select(ProgramPeriod.started_on).where(
                        ProgramPeriod.user_id == DEFAULT_USER_ID,
                        ProgramPeriod.ended_on.is_(None),
                    )
                )
            ).scalar_one()
        assert seeded_started_on == local_day(_REWIND_WORKOUT_START, "Asia/Jakarta")
        assert seeded_started_on != _REWIND_WORKOUT_START.date()
    finally:
        async with engine.begin() as conn:
            await conn.execute(sa.delete(Workout).where(Workout.id == workout_id))


@pytest.mark.integration
async def test_migration_enforces_a_unique_nonce(engine: AsyncEngine) -> None:
    """Two tokens carrying the same nonce is a replay the consume path could not tell apart.
    IntegrityError on the second insert."""
    period_id = uuid.uuid4()
    first_token_id = uuid.uuid4()
    nonce = "duplicate-nonce-12-01"
    try:
        async with engine.begin() as conn:
            await conn.execute(
                sa.insert(ProgramPeriod).values(
                    id=period_id,
                    user_id=DEFAULT_USER_ID,
                    program="cut",
                    started_on=dt.date(2026, 1, 1),
                    ended_on=dt.date(2026, 1, 15),
                )
            )
            await conn.execute(
                sa.insert(ProgramSwitchToken).values(
                    id=first_token_id,
                    user_id=DEFAULT_USER_ID,
                    nonce=nonce,
                    from_period_id=period_id,
                    to_program="cut",
                    expires_at=dt.datetime(2026, 1, 1, 0, 5, tzinfo=dt.UTC),
                    consumed_at=None,
                )
            )
        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(
                    sa.insert(ProgramSwitchToken).values(
                        id=uuid.uuid4(),
                        user_id=DEFAULT_USER_ID,
                        nonce=nonce,
                        from_period_id=period_id,
                        to_program="recomp",
                        expires_at=dt.datetime(2026, 1, 1, 0, 5, tzinfo=dt.UTC),
                        consumed_at=None,
                    )
                )
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                sa.delete(ProgramSwitchToken).where(ProgramSwitchToken.id == first_token_id)
            )
            await conn.execute(sa.delete(ProgramPeriod).where(ProgramPeriod.id == period_id))


@pytest.mark.integration
async def test_fixture_builders_round_trip_a_period_and_a_token(
    committed_history: GoldenBuilder,
    session: AsyncSession,
    engine: AsyncEngine,
) -> None:
    """A guard on the fixtures themselves: `GoldenBuilder.program_period` and `.switch_token`
    write rows the repository can read back. A builder that silently wrote the wrong column
    would make every test below assert against a fixture rather than against the schema.
    """
    # Migration 0006 already opened one `lean_bulk` period for DEFAULT_USER_ID. The partial
    # unique index permits only one open period per user, so -- per `program_period`'s own
    # docstring -- this test must close it before opening its own.
    await session.execute(
        sa.update(ProgramPeriod)
        .where(ProgramPeriod.user_id == DEFAULT_USER_ID, ProgramPeriod.ended_on.is_(None))
        .values(ended_on=dt.date(2026, 1, 31))
    )
    closed_period_id = await committed_history.program_period(
        program="cut",
        started_on=dt.date(2026, 2, 1),
        ended_on=dt.date(2026, 2, 15),
    )
    open_period_id = await committed_history.program_period(
        program="recomp",
        started_on=dt.date(2026, 2, 15),
    )
    token_id = await committed_history.switch_token(
        nonce="fixture-round-trip-nonce",
        from_period_id=open_period_id,
        to_program="cut",
        expires_at=dt.datetime(2026, 2, 15, 0, 5, tzinfo=dt.UTC),
    )
    await session.commit()

    async with engine.connect() as conn:
        period_rows = (
            await conn.execute(
                sa.select(ProgramPeriod.id, ProgramPeriod.program, ProgramPeriod.ended_on).where(
                    ProgramPeriod.id.in_([closed_period_id, open_period_id])
                )
            )
        ).all()
        token_row = (
            await conn.execute(
                sa.select(ProgramSwitchToken.nonce, ProgramSwitchToken.to_program).where(
                    ProgramSwitchToken.id == token_id
                )
            )
        ).one()
    by_id = {row[0]: (row[1], row[2]) for row in period_rows}
    assert by_id[closed_period_id] == ("cut", dt.date(2026, 2, 15))
    assert by_id[open_period_id] == ("recomp", None)
    assert token_row == ("fixture-round-trip-nonce", "cut")


# ---------------------------------------------------------------------------
# Plan 02: the repository's own proofs -- resolution, atomicity, TTL,
# wrong-program and replay.
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_get_active_period_returns_the_open_row(session: AsyncSession) -> None:
    """The seeded lean_bulk period, and it is the one with `ended_on IS NULL` -- not merely
    the most recent."""
    period = await get_active_period(session, user_id=DEFAULT_USER_ID)
    assert period is not None
    assert period.program == "lean_bulk"
    assert period.ended_on is None


@pytest.mark.integration
async def test_get_periods_overlapping_reports_one_period_for_an_unstraddled_window(
    session: AsyncSession,
) -> None:
    """A window entirely inside one period returns exactly one row. This is the case D-10's
    caveat field must stay silent for."""
    active = await get_active_period(session, user_id=DEFAULT_USER_ID)
    assert active is not None
    window_start = active.started_on
    window_end = window_start + dt.timedelta(days=5)

    periods = await get_periods_overlapping(
        session, user_id=DEFAULT_USER_ID, window_start=window_start, window_end=window_end
    )

    assert len(periods) == 1
    assert periods[0].id == active.id


@pytest.mark.integration
async def test_get_periods_overlapping_reports_both_across_a_switch(
    session: AsyncSession, committed_history: GoldenBuilder
) -> None:
    """Close the seeded period on a known day, open a `cut` period the same day, then ask for
    a window spanning both: two rows, ascending by `started_on`. This is the straddle
    Plan 03 turns into the caveat."""
    active = await get_active_period(session, user_id=DEFAULT_USER_ID)
    assert active is not None
    switch_day = active.started_on + dt.timedelta(days=10)

    await session.execute(
        sa.update(ProgramPeriod).where(ProgramPeriod.id == active.id).values(ended_on=switch_day)
    )
    new_period_id = await committed_history.program_period(
        program="cut", started_on=switch_day, ended_on=None
    )
    await session.commit()

    periods = await get_periods_overlapping(
        session,
        user_id=DEFAULT_USER_ID,
        window_start=active.started_on,
        window_end=switch_day + dt.timedelta(days=5),
    )

    assert [p.id for p in periods] == [active.id, new_period_id]
    assert periods[0].program == "lean_bulk"
    assert periods[1].program == "cut"


@pytest.mark.integration
async def test_get_periods_overlapping_includes_the_open_period_beyond_its_start(
    session: AsyncSession,
) -> None:
    """The open period has `ended_on IS NULL`, and a window whose end is far in the future
    must still include it. A naive `ended_on >= window_start` predicate excludes the CURRENT
    program from every window -- the most consequential possible bug in this function, and
    invisible in any test whose window happens to end inside the period."""
    active = await get_active_period(session, user_id=DEFAULT_USER_ID)
    assert active is not None

    periods = await get_periods_overlapping(
        session,
        user_id=DEFAULT_USER_ID,
        window_start=active.started_on,
        window_end=active.started_on + dt.timedelta(days=3650),
    )

    assert any(p.id == active.id for p in periods)


@pytest.mark.integration
async def test_get_recent_periods_orders_newest_first(
    session: AsyncSession, committed_history: GoldenBuilder
) -> None:
    """With three periods, `limit=2` returns the open one then the one it replaced -- the
    exact pair ROADMAP success criterion #1 needs."""
    active = await get_active_period(session, user_id=DEFAULT_USER_ID)
    assert active is not None
    day1 = active.started_on + dt.timedelta(days=10)
    day2 = day1 + dt.timedelta(days=10)

    await session.execute(
        sa.update(ProgramPeriod).where(ProgramPeriod.id == active.id).values(ended_on=day1)
    )
    cut_id = await committed_history.program_period(program="cut", started_on=day1, ended_on=day2)
    recomp_id = await committed_history.program_period(
        program="recomp", started_on=day2, ended_on=None
    )
    await session.commit()

    recent = await get_recent_periods(session, user_id=DEFAULT_USER_ID, limit=2)

    assert [p.id for p in recent] == [recomp_id, cut_id]


@pytest.mark.integration
async def test_period_reads_are_scoped_to_the_user(
    session: AsyncSession, committed_history: GoldenBuilder
) -> None:
    """ASVS V4: seed a second user (`GoldenBuilder.user`) with their own open period and
    assert neither read returns it. A single-user suite cannot detect a missing `user_id`
    predicate -- every row belongs to the only user, so an unscoped query is right by
    accident."""
    await committed_history.user(user_id=ANALYTICS_SECOND_USER_ID)
    other_period_id = await committed_history.program_period(
        program="cut",
        started_on=dt.date(2026, 1, 1),
        ended_on=None,
        user_id=ANALYTICS_SECOND_USER_ID,
    )
    await session.commit()

    active = await get_active_period(session, user_id=DEFAULT_USER_ID)
    assert active is not None
    assert active.id != other_period_id

    overlapping = await get_periods_overlapping(
        session,
        user_id=DEFAULT_USER_ID,
        window_start=dt.date(2020, 1, 1),
        window_end=dt.date(2030, 1, 1),
    )
    assert other_period_id not in {p.id for p in overlapping}

    recent = await get_recent_periods(session, user_id=DEFAULT_USER_ID, limit=10)
    assert other_period_id not in {p.id for p in recent}


@pytest.mark.integration
async def test_a_freshly_issued_token_consumes_once_and_returns_the_period(
    session: AsyncSession, committed_history: GoldenBuilder
) -> None:
    """The happy path: issue, consume, get back `from_period_id`. Assert `expires_at` is
    roughly five minutes ahead of `now()` (a range assertion, not an equality -- the value is
    the database's clock, not the test's)."""
    active = await get_active_period(session, user_id=DEFAULT_USER_ID)
    assert active is not None

    nonce, expires_at = await issue_switch_token(
        session,
        user_id=DEFAULT_USER_ID,
        from_period_id=active.id,
        to_program=TrainingProgram.CUT,
    )
    await session.commit()

    now = dt.datetime.now(dt.UTC)
    assert now + dt.timedelta(minutes=4) < expires_at < now + dt.timedelta(minutes=6)

    from_period_id = await consume_switch_token(
        session, user_id=DEFAULT_USER_ID, nonce=nonce, to_program=TrainingProgram.CUT
    )
    await session.commit()

    assert from_period_id == active.id


@pytest.mark.integration
async def test_consuming_the_same_token_twice_fails_the_second_time(
    session: AsyncSession, committed_history: GoldenBuilder
) -> None:
    """T-12-03 / SC#4. The second call returns None, and the row's `consumed_at` is unchanged
    from the first call's value -- proving the second attempt matched zero rows rather than
    re-stamping."""
    active = await get_active_period(session, user_id=DEFAULT_USER_ID)
    assert active is not None
    nonce, _ = await issue_switch_token(
        session,
        user_id=DEFAULT_USER_ID,
        from_period_id=active.id,
        to_program=TrainingProgram.CUT,
    )
    await session.commit()

    first = await consume_switch_token(
        session, user_id=DEFAULT_USER_ID, nonce=nonce, to_program=TrainingProgram.CUT
    )
    await session.commit()
    assert first == active.id

    consumed_at_after_first = await session.scalar(
        sa.select(ProgramSwitchToken.consumed_at).where(ProgramSwitchToken.nonce == nonce)
    )
    assert consumed_at_after_first is not None

    second = await consume_switch_token(
        session, user_id=DEFAULT_USER_ID, nonce=nonce, to_program=TrainingProgram.CUT
    )
    await session.commit()
    assert second is None

    consumed_at_after_second = await session.scalar(
        sa.select(ProgramSwitchToken.consumed_at).where(ProgramSwitchToken.nonce == nonce)
    )
    assert consumed_at_after_second == consumed_at_after_first


@pytest.mark.integration
async def test_a_token_bound_to_one_program_cannot_be_spent_on_another(
    session: AsyncSession, committed_history: GoldenBuilder
) -> None:
    """T-12-02 / SC#4. Issue for `cut`, attempt to consume for `recomp`: returns None AND
    `consumed_at IS NULL` afterwards -- the mismatched attempt must not burn the token, so
    the correct call still works inside the TTL. Assert that follow-up call succeeds in the
    SAME test; "was not consumed" and "is still usable" are two claims."""
    active = await get_active_period(session, user_id=DEFAULT_USER_ID)
    assert active is not None
    nonce, _ = await issue_switch_token(
        session,
        user_id=DEFAULT_USER_ID,
        from_period_id=active.id,
        to_program=TrainingProgram.CUT,
    )
    await session.commit()

    wrong = await consume_switch_token(
        session, user_id=DEFAULT_USER_ID, nonce=nonce, to_program=TrainingProgram.RECOMP
    )
    await session.commit()
    assert wrong is None

    consumed_at = await session.scalar(
        sa.select(ProgramSwitchToken.consumed_at).where(ProgramSwitchToken.nonce == nonce)
    )
    assert consumed_at is None

    correct = await consume_switch_token(
        session, user_id=DEFAULT_USER_ID, nonce=nonce, to_program=TrainingProgram.CUT
    )
    await session.commit()
    assert correct == active.id


@pytest.mark.integration
async def test_an_expired_token_is_refused(
    session: AsyncSession, committed_history: GoldenBuilder
) -> None:
    """T-12-04 / D-11. Issue with `ttl=dt.timedelta(seconds=-1)` and consume: None. No
    sleeping and no time-machine -- the TTL parameter exists so this test costs nothing."""
    active = await get_active_period(session, user_id=DEFAULT_USER_ID)
    assert active is not None
    nonce, _ = await issue_switch_token(
        session,
        user_id=DEFAULT_USER_ID,
        from_period_id=active.id,
        to_program=TrainingProgram.CUT,
        ttl=dt.timedelta(seconds=-1),
    )
    await session.commit()

    result = await consume_switch_token(
        session, user_id=DEFAULT_USER_ID, nonce=nonce, to_program=TrainingProgram.CUT
    )
    await session.commit()

    assert result is None


@pytest.mark.integration
async def test_a_token_from_another_user_cannot_be_consumed(
    session: AsyncSession, committed_history: GoldenBuilder
) -> None:
    """ASVS V4. Even with the exact nonce string, a different `user_id` returns None."""
    await committed_history.user(user_id=ANALYTICS_SECOND_USER_ID)
    active = await get_active_period(session, user_id=DEFAULT_USER_ID)
    assert active is not None
    nonce, _ = await issue_switch_token(
        session,
        user_id=DEFAULT_USER_ID,
        from_period_id=active.id,
        to_program=TrainingProgram.CUT,
    )
    await session.commit()

    result = await consume_switch_token(
        session, user_id=ANALYTICS_SECOND_USER_ID, nonce=nonce, to_program=TrainingProgram.CUT
    )
    await session.commit()

    assert result is None


@pytest.mark.integration
async def test_close_and_open_moves_the_open_period(
    session: AsyncSession, committed_history: GoldenBuilder
) -> None:
    """The old period gains `ended_on = today`, the new period is open with
    `started_on = today` and the requested program, and `get_active_period` now returns the
    new one. Exactly one open period exists afterwards."""
    active = await get_active_period(session, user_id=DEFAULT_USER_ID)
    assert active is not None
    today = active.started_on + dt.timedelta(days=20)

    new_period = await close_period_and_open_new(
        session,
        user_id=DEFAULT_USER_ID,
        from_period_id=active.id,
        to_program=TrainingProgram.CUT,
        today=today,
    )
    await session.commit()

    assert new_period is not None
    assert new_period.program == "cut"
    assert new_period.started_on == today
    assert new_period.ended_on is None

    old = await session.get(ProgramPeriod, active.id)
    assert old is not None
    assert old.ended_on == today

    open_count = await session.scalar(
        sa.select(sa.func.count())
        .select_from(ProgramPeriod)
        .where(ProgramPeriod.user_id == DEFAULT_USER_ID, ProgramPeriod.ended_on.is_(None))
    )
    assert open_count == 1

    current = await get_active_period(session, user_id=DEFAULT_USER_ID)
    assert current is not None
    assert current.id == new_period.id


@pytest.mark.integration
async def test_close_and_open_refuses_when_the_period_is_no_longer_open(
    session: AsyncSession, committed_history: GoldenBuilder
) -> None:
    """The interleaving case: close the period by other means first, then call
    `close_period_and_open_new` with its id. Returns None, inserts NOTHING, and the row count
    in `user_program_history` is unchanged. This is the difference between `not_applied` and
    `unknown` in the tool above it."""
    active = await get_active_period(session, user_id=DEFAULT_USER_ID)
    assert active is not None
    already_closed_on = active.started_on + dt.timedelta(days=5)

    await session.execute(
        sa.update(ProgramPeriod)
        .where(ProgramPeriod.id == active.id)
        .values(ended_on=already_closed_on)
    )
    await session.commit()

    count_before = await session.scalar(
        sa.select(sa.func.count())
        .select_from(ProgramPeriod)
        .where(ProgramPeriod.user_id == DEFAULT_USER_ID)
    )

    result = await close_period_and_open_new(
        session,
        user_id=DEFAULT_USER_ID,
        from_period_id=active.id,
        to_program=TrainingProgram.CUT,
        today=already_closed_on + dt.timedelta(days=1),
    )
    await session.commit()

    assert result is None

    count_after = await session.scalar(
        sa.select(sa.func.count())
        .select_from(ProgramPeriod)
        .where(ProgramPeriod.user_id == DEFAULT_USER_ID)
    )
    assert count_after == count_before
