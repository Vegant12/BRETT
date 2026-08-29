"""Read and advance per-resource sync bookkeeping (HEVY-09, D-08).

Provider-neutral on purpose: these helpers take `provider` and `resource` as arguments and
import nothing from `app.integrations`, so HEVY-05's boundary holds in both directions.

Every function takes an `AsyncSession` and never commits. The CALLER owns the transaction --
D-08 requires the checkpoint to commit in the SAME transaction as the page of rows it
describes, and a helper that committed on its own would make that impossible.
"""

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.sync_state import SyncState

PROVIDER_HEVY = "hevy"

RESOURCE_WORKOUTS = "workouts"
RESOURCE_EXERCISE_TEMPLATES = "exercise_templates"
RESOURCE_BODY_MEASUREMENTS = "body_measurements"

# HEVY-09: three independent data sources, three independent last_synced_at values.
SYNC_RESOURCES: frozenset[str] = frozenset(
    {RESOURCE_WORKOUTS, RESOURCE_EXERCISE_TEMPLATES, RESOURCE_BODY_MEASUREMENTS}
)

STATUS_IDLE = "idle"
STATUS_RUNNING = "running"
STATUS_ERROR = "error"

_MAX_ERROR_LEN = 500

# `ON CONFLICT` is bound to the constraint BY NAME rather than by column list. If the
# constraint is ever renamed, this raises immediately instead of silently degrading into
# a duplicate-row insert.
_CONFLICT_CONSTRAINT = "uq_sync_state_user_provider_resource"


def format_sync_error(exc: BaseException) -> str:
    """Render an exception for storage WITHOUT leaking a payload.

    Only exceptions that opt in -- by exposing a `safe_message` attribute the raiser curated
    -- contribute any detail. Everything else stores its class name alone. This matters
    concretely: `pydantic.ValidationError.__str__` renders `input_value=...`, so a naive
    `str(exc)` would write a user's workout titles and body-composition numbers into a
    column and, from there, into any log line that reads it back (T-03-13).
    """
    detail = getattr(exc, "safe_message", None)
    if isinstance(detail, str) and detail:
        return f"{type(exc).__name__}: {detail}"[:_MAX_ERROR_LEN]
    return type(exc).__name__[:_MAX_ERROR_LEN]


async def _upsert(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    provider: str,
    resource: str,
    values: dict[str, Any],
) -> None:
    """Insert the bookkeeping row or update it in place, in one round trip.

    Every mutator routes through here so that a sync can record progress for a resource
    whose row does not exist yet -- the first run of a new resource -- without the caller
    having to remember to `ensure_sync_state` first.

    `updated_at` is set explicitly. SQLAlchemy's `onupdate=func.now()` fires for an
    `update()` statement but is NOT injected into an `ON CONFLICT DO UPDATE SET` clause,
    so omitting it here would freeze the audit timestamp at row creation.
    """
    statement = pg_insert(SyncState).values(
        id=uuid.uuid4(), user_id=user_id, provider=provider, resource=resource, **values
    )
    await session.execute(
        statement.on_conflict_do_update(
            constraint=_CONFLICT_CONSTRAINT,
            set_={**values, "updated_at": func.now()},
        )
    )


async def get_sync_state(
    session: AsyncSession, *, user_id: uuid.UUID, provider: str, resource: str
) -> SyncState | None:
    """The bookkeeping row, or None if this resource has never been synced."""
    return await session.scalar(
        select(SyncState).where(
            SyncState.user_id == user_id,
            SyncState.provider == provider,
            SyncState.resource == resource,
        )
    )


async def ensure_sync_state(
    session: AsyncSession, *, user_id: uuid.UUID, provider: str, resource: str
) -> SyncState:
    """Get-or-create, atomically.

    Uses `pg_insert(...).on_conflict_do_nothing(constraint="uq_sync_state_user_provider_resource")`
    followed by a SELECT, not SELECT-then-INSERT: the read-then-write is a race and costs two
    round trips even when it wins.
    """
    statement = pg_insert(SyncState).values(
        id=uuid.uuid4(), user_id=user_id, provider=provider, resource=resource
    )
    await session.execute(statement.on_conflict_do_nothing(constraint=_CONFLICT_CONSTRAINT))

    state = await get_sync_state(session, user_id=user_id, provider=provider, resource=resource)
    if state is None:  # pragma: no cover - the insert above guarantees a row exists
        raise RuntimeError(f"sync_state row missing after upsert: {provider}/{resource}")
    return state


async def mark_running(
    session: AsyncSession, *, user_id: uuid.UUID, provider: str, resource: str
) -> None:
    """Set status='running' and clear last_error. Does not touch the cursors."""
    await _upsert(
        session,
        user_id=user_id,
        provider=provider,
        resource=resource,
        # The cursors are deliberately absent from this dict: a resumed run needs the
        # page D-08 left behind, and a re-drain needs the HEVY-02 events timestamp.
        values={"status": STATUS_RUNNING, "last_error": None},
    )


async def advance_cursor_page(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    provider: str,
    resource: str,
    cursor_page: int | None,
) -> None:
    """D-08: record the next page to resume from. Caller commits this with the page's rows."""
    await _upsert(
        session,
        user_id=user_id,
        provider=provider,
        resource=resource,
        values={"cursor_page": cursor_page},
    )


async def complete_sync(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    provider: str,
    resource: str,
    last_synced_at: dt.datetime,
    cursor_timestamp: dt.datetime | None = None,
    cursor_page: int | None = None,
) -> None:
    """Finish a run: status='idle', last_error=NULL, last_synced_at set.

    `cursor_page=None` is the normal end state -- a completed full sync has no page to resume
    from. `cursor_timestamp` is only passed by the events drain (HEVY-02), and only once, after
    the whole drain has been applied.
    """
    # FOUND-04 enforced by a guard, not a convention. A naive value is stored as if it
    # were UTC, so a Jakarta-local timestamp would record the sync seven hours into the
    # future and suppress the next run with no error anywhere in the stack.
    if last_synced_at.tzinfo is None or last_synced_at.tzinfo.utcoffset(last_synced_at) is None:
        raise ValueError("naive datetime rejected: last_synced_at must be timezone-aware UTC")

    values: dict[str, Any] = {
        "status": STATUS_IDLE,
        "last_error": None,
        "last_synced_at": last_synced_at,
        "cursor_page": cursor_page,
    }
    # Only written when the caller supplies it. Passing None here would RESET the events
    # cursor to "the beginning of time" on every completed full sync (Pitfall 1).
    if cursor_timestamp is not None:
        values["cursor_timestamp"] = cursor_timestamp

    await _upsert(session, user_id=user_id, provider=provider, resource=resource, values=values)


async def record_sync_error(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    provider: str,
    resource: str,
    exc: BaseException,
) -> None:
    """status='error', last_error=format_sync_error(exc). Cursors are LEFT ALONE so the next
    run resumes rather than restarting (D-08, HEVY-08)."""
    await _upsert(
        session,
        user_id=user_id,
        provider=provider,
        resource=resource,
        values={"status": STATUS_ERROR, "last_error": format_sync_error(exc)},
    )
