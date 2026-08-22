"""FOUND-02: migrations are the sole authority over the schema.

Every assertion here runs against a real Postgres container. SQLite would prove
nothing -- ``TIMESTAMPTZ``, ``information_schema`` and the UUID type all behave
differently or not at all.
"""

import subprocess
import uuid
from collections.abc import Callable

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.conftest import DEFAULT_USER_ID


async def _tables(engine: AsyncEngine) -> list[str]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            sa.text(
                "select table_name from information_schema.tables "
                "where table_schema = 'public' order by table_name"
            )
        )
    return [row[0] for row in rows]


async def _users(engine: AsyncEngine) -> list[tuple[uuid.UUID, str]]:
    async with engine.connect() as conn:
        rows = await conn.execute(sa.text("select id, timezone from users order by id"))
    return [(row[0], row[1]) for row in rows]


@pytest.mark.integration
async def test_migrations_round_trip(
    engine: AsyncEngine,
    alembic: Callable[..., subprocess.CompletedProcess[str]],
    restore_schema: None,
) -> None:
    """A fresh database reaches head, reverses to bare, and re-seeds exactly once."""
    assert alembic("upgrade", "head").returncode == 0
    assert alembic("current").stdout.strip().endswith("(head)")
    assert len(await _users(engine)) == 1  # D-01 seed

    result = alembic("downgrade", "base")
    assert result.returncode == 0, result.stderr
    # No manual SQL and no leftover tables: `downgrade base` is genuinely complete.
    assert await _tables(engine) == ["alembic_version"]

    assert alembic("upgrade", "head").returncode == 0
    # Re-running the seed must not produce a second user.
    assert len(await _users(engine)) == 1


@pytest.mark.integration
async def test_default_user_seeded(engine: AsyncEngine) -> None:
    """D-01/D-02: the id and timezone are fixed constants, not generated values."""
    rows = await _users(engine)
    assert len(rows) == 1
    user_id, timezone = rows[0]
    assert user_id == DEFAULT_USER_ID == uuid.UUID("00000000-0000-0000-0000-000000000001")
    assert timezone == "Asia/Jakarta"

    # FOUND-04: a bare `DateTime()` anywhere would surface here as a naive column.
    async with engine.connect() as conn:
        naive = (
            await conn.execute(
                sa.text(
                    "select column_name from information_schema.columns "
                    "where table_schema = 'public' and data_type like 'timestamp%' "
                    "and data_type <> 'timestamp with time zone'"
                )
            )
        ).all()
    assert naive == []


@pytest.mark.integration
def test_no_pending_model_drift(
    alembic: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    """`alembic check` fails if the models and the migrations have diverged."""
    result = alembic("check")
    assert result.returncode == 0, result.stdout + result.stderr
