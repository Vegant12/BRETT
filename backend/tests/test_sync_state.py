"""Per-resource sync bookkeeping (HEVY-09, D-08).

The integration tests run against the real Postgres container because the whole point
of `ensure_sync_state` is the `ON CONFLICT` clause, which has no meaning outside
PostgreSQL. The two `format_sync_error` tests need no database and stay in the fast
suite -- they are the T-03-12 redaction guard, and that one should never be skippable
because Docker is not running.
"""

import datetime as dt
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SyncState
from app.db.repositories.sync_state import (
    RESOURCE_BODY_MEASUREMENTS,
    RESOURCE_EXERCISE_TEMPLATES,
    RESOURCE_WORKOUTS,
    STATUS_ERROR,
    STATUS_IDLE,
    STATUS_RUNNING,
    SYNC_RESOURCES,
    advance_cursor_page,
    complete_sync,
    ensure_sync_state,
    format_sync_error,
    get_sync_state,
    mark_running,
    record_sync_error,
)
from tests.conftest import DEFAULT_USER_ID

# Deliberately NOT "hevy": these rows share a session-scoped container with every other
# integration test, and the cleanup below keys on this value. A test that wrote real
# `provider='hevy'` bookkeeping could delete a row a later test depended on.
_PROVIDER = "test-provider"

# Fixed and aware. Ruff's DTZ rules reject a naive literal, and `complete_sync` rejects
# one at runtime -- which `test_naive_last_synced_at_is_rejected` relies on.
_SYNCED_AT = dt.datetime(2026, 8, 29, 6, 0, tzinfo=dt.UTC)


class _RateLimited(Exception):
    """An exception that opts in to storing detail, the way the Hevy client will."""

    safe_message = "429 from provider"


@pytest_asyncio.fixture
async def bookkeeping(session: AsyncSession) -> AsyncIterator[AsyncSession]:
    """A session whose `sync_state` rows are removed afterwards, pass or fail."""
    try:
        yield session
    finally:
        # Roll back anything the test left uncommitted before issuing the DELETE:
        # a failed statement poisons the transaction, and the cleanup would then
        # fail too and mask the real assertion error.
        await session.rollback()
        await session.execute(
            sa.delete(SyncState).where(
                SyncState.user_id == DEFAULT_USER_ID,
                SyncState.provider == _PROVIDER,
            )
        )
        await session.commit()


async def _row(session: AsyncSession, resource: str) -> SyncState:
    state = await get_sync_state(
        session, user_id=DEFAULT_USER_ID, provider=_PROVIDER, resource=resource
    )
    assert state is not None
    return state


@pytest.mark.integration
async def test_ensure_is_idempotent(bookkeeping: AsyncSession) -> None:
    """Get-or-create really is get-or-create: two calls leave one row.

    `ON CONFLICT DO NOTHING` rather than SELECT-then-INSERT. The read-then-write is a
    race two concurrent syncs can both lose, and it costs two round trips even when it
    wins.
    """
    first = await ensure_sync_state(
        bookkeeping, user_id=DEFAULT_USER_ID, provider=_PROVIDER, resource=RESOURCE_WORKOUTS
    )
    second = await ensure_sync_state(
        bookkeeping, user_id=DEFAULT_USER_ID, provider=_PROVIDER, resource=RESOURCE_WORKOUTS
    )
    await bookkeeping.commit()

    assert first.id == second.id
    assert first.status == STATUS_IDLE
    assert first.last_synced_at is None

    count = await bookkeeping.scalar(
        sa.select(sa.func.count())
        .select_from(SyncState)
        .where(SyncState.user_id == DEFAULT_USER_ID, SyncState.provider == _PROVIDER)
    )
    assert count == 1


@pytest.mark.integration
async def test_three_resources_have_independent_last_synced_at(
    bookkeeping: AsyncSession,
) -> None:
    """HEVY-09: freshness is per data source, so three sources need three answers.

    A single `last_synced_at` on a connections table would report the newest of the
    three for all of them, which is precisely the staleness Claude must be able to see.
    """
    assert SYNC_RESOURCES == {
        RESOURCE_WORKOUTS,
        RESOURCE_EXERCISE_TEMPLATES,
        RESOURCE_BODY_MEASUREMENTS,
    }

    expected = {
        RESOURCE_WORKOUTS: _SYNCED_AT,
        RESOURCE_EXERCISE_TEMPLATES: _SYNCED_AT - dt.timedelta(days=3),
        RESOURCE_BODY_MEASUREMENTS: _SYNCED_AT - dt.timedelta(hours=7),
    }
    for resource, synced_at in expected.items():
        await complete_sync(
            bookkeeping,
            user_id=DEFAULT_USER_ID,
            provider=_PROVIDER,
            resource=resource,
            last_synced_at=synced_at,
        )
    await bookkeeping.commit()

    actual = {resource: (await _row(bookkeeping, resource)).last_synced_at for resource in expected}
    assert actual == expected
    # Three genuinely distinct values, not three reads of one row.
    assert len(set(actual.values())) == 3


@pytest.mark.integration
async def test_advance_cursor_page_persists(bookkeeping: AsyncSession) -> None:
    """D-08: the resume point survives, so a crashed full sync restarts mid-run."""
    await advance_cursor_page(
        bookkeeping,
        user_id=DEFAULT_USER_ID,
        provider=_PROVIDER,
        resource=RESOURCE_WORKOUTS,
        cursor_page=7,
    )
    await bookkeeping.commit()

    assert (await _row(bookkeeping, RESOURCE_WORKOUTS)).cursor_page == 7


@pytest.mark.integration
async def test_complete_sync_clears_error_and_page(bookkeeping: AsyncSession) -> None:
    """A successful run erases the previous failure rather than layering on top of it."""
    await record_sync_error(
        bookkeeping,
        user_id=DEFAULT_USER_ID,
        provider=_PROVIDER,
        resource=RESOURCE_WORKOUTS,
        exc=_RateLimited(),
    )
    await advance_cursor_page(
        bookkeeping,
        user_id=DEFAULT_USER_ID,
        provider=_PROVIDER,
        resource=RESOURCE_WORKOUTS,
        cursor_page=4,
    )
    await bookkeeping.commit()

    await complete_sync(
        bookkeeping,
        user_id=DEFAULT_USER_ID,
        provider=_PROVIDER,
        resource=RESOURCE_WORKOUTS,
        last_synced_at=_SYNCED_AT,
    )
    await bookkeeping.commit()

    state = await _row(bookkeeping, RESOURCE_WORKOUTS)
    assert state.status == STATUS_IDLE
    assert state.last_error is None
    # A completed full sync has no page to resume from; leaving 4 here would make the
    # NEXT run skip the first four pages of a fresh drain.
    assert state.cursor_page is None
    assert state.last_synced_at == _SYNCED_AT


@pytest.mark.integration
async def test_record_error_keeps_the_cursor(bookkeeping: AsyncSession) -> None:
    """HEVY-08/D-08: a failure resumes, it does not restart.

    Clearing the cursor here would silently turn every transient rate-limit into a full
    re-drain of Hevy's 10-item pages.
    """
    await mark_running(
        bookkeeping, user_id=DEFAULT_USER_ID, provider=_PROVIDER, resource=RESOURCE_WORKOUTS
    )
    await advance_cursor_page(
        bookkeeping,
        user_id=DEFAULT_USER_ID,
        provider=_PROVIDER,
        resource=RESOURCE_WORKOUTS,
        cursor_page=4,
    )
    await bookkeeping.commit()
    assert (await _row(bookkeeping, RESOURCE_WORKOUTS)).status == STATUS_RUNNING

    await record_sync_error(
        bookkeeping,
        user_id=DEFAULT_USER_ID,
        provider=_PROVIDER,
        resource=RESOURCE_WORKOUTS,
        exc=_RateLimited(),
    )
    await bookkeeping.commit()

    state = await _row(bookkeeping, RESOURCE_WORKOUTS)
    assert state.cursor_page == 4
    assert state.status == STATUS_ERROR
    assert state.last_error == "_RateLimited: 429 from provider"


@pytest.mark.integration
async def test_naive_last_synced_at_is_rejected(bookkeeping: AsyncSession) -> None:
    """FOUND-04 is a guard, not a convention.

    A naive value would be stored as if it were UTC, so a Jakarta-local timestamp would
    silently record the sync as seven hours in the future and suppress the next run.
    """
    with pytest.raises(ValueError, match="naive datetime rejected"):
        await complete_sync(
            bookkeeping,
            user_id=DEFAULT_USER_ID,
            provider=_PROVIDER,
            resource=RESOURCE_WORKOUTS,
            last_synced_at=dt.datetime(2026, 8, 29, 6, 0),  # noqa: DTZ001 - the point of the test
        )


@pytest.mark.integration
async def test_helpers_never_commit(bookkeeping: AsyncSession) -> None:
    """D-08 depends on this: the CALLER decides what commits with what.

    The resume checkpoint has to land in the same transaction as the page of rows it
    describes. A helper that committed on its own would split them into two, and an
    interleaving could then produce a checkpoint claiming work that rolled back.
    """
    await ensure_sync_state(
        bookkeeping, user_id=DEFAULT_USER_ID, provider=_PROVIDER, resource=RESOURCE_WORKOUTS
    )
    await advance_cursor_page(
        bookkeeping,
        user_id=DEFAULT_USER_ID,
        provider=_PROVIDER,
        resource=RESOURCE_WORKOUTS,
        cursor_page=9,
    )
    await bookkeeping.rollback()

    assert (
        await get_sync_state(
            bookkeeping,
            user_id=DEFAULT_USER_ID,
            provider=_PROVIDER,
            resource=RESOURCE_WORKOUTS,
        )
    ) is None


def test_format_sync_error_uses_safe_message_when_present() -> None:
    """An exception may opt in to detail by curating a `safe_message`."""
    assert format_sync_error(_RateLimited()) == "_RateLimited: 429 from provider"


def test_format_sync_error_omits_detail_by_default() -> None:
    """T-03-12: an exception that did not opt in contributes its class name and nothing else.

    `pydantic.ValidationError.__str__` renders `input_value=...`, so a naive `str(exc)`
    would write workout titles and body-composition numbers into `last_error` and, from
    there, into any log line that reads the column back.
    """
    rendered = format_sync_error(ValueError("secret-value-9f3a"))
    assert rendered == "ValueError"
    assert "secret-value-9f3a" not in rendered


def test_format_sync_error_is_length_capped() -> None:
    """`last_error` is a display field, not a place to accumulate a payload."""

    class _Chatty(Exception):
        safe_message = "x" * 5_000

    assert len(format_sync_error(_Chatty())) <= 500
