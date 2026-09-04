"""GOAL-01's proof: the active training program is DATA, not a constant.

The "one open period per user" invariant is enforced by PostgreSQL, not by application code
(PITFALLS #16), and migration 0006's D-08 seed comes from live synced training history rather
than a hardcoded date. This plan covers schema, the partial index, and both branches of the
seed only -- Plan 02 extends this file with the repository's own tests.
"""

import datetime as dt
import subprocess
import uuid
from collections.abc import Callable

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.time import local_day
from app.db.models.program import ProgramPeriod, ProgramSwitchToken
from app.db.models.user import User
from app.db.models.workout import Workout
from tests.conftest import DEFAULT_USER_ID, GoldenBuilder

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
