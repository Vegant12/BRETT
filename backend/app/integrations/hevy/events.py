"""Incremental sync over `/v1/workouts/events` (HEVY-02, HEVY-04).

Hevy's own description: "Retrieve a paged list of workout events (updates or deletes) since a
given date. Events are ordered from newest to oldest."

That ordering is a trap, and the failure is silent. Advancing `since` while paging re-windows
the query, so pages 2..N -- which hold OLDER events -- fall outside the new window and are
never fetched. Simulated against an 8-event feed during research:

    total events on server : 8
    expected final state   : {'w0': 6, 'w2': 5}
    NAIVE   -> events applied= 2  state={'w0': 6}           MATCH=False
    CORRECT -> events applied= 8  state={'w0': 6, 'w2': 5}  MATCH=True

The naive run applied 2 of 8 events, dropped workout `w2` entirely, and reported success.

Three rules, each load-bearing:
  1. `since` MUST NOT change while paging.
  2. Collect every page BEFORE applying anything.
  3. Apply oldest-first. Each `updated` event carries a FULL workout snapshot, so applying in
     arrival order (newest first) means the older snapshot lands last and wins -- a workout
     edited twice since the last sync would end up holding the stale version (Pitfall 2).

The cursor advances exactly ONCE, after the whole drain has been applied and committed. When
in doubt, choose an EARLIER cursor: overlap is free because the upsert is idempotent, a gap is
unrecoverable.
"""

import datetime as dt
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

import structlog
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.time import utc_now
from app.db.repositories.sync_state import (
    PROVIDER_HEVY,
    RESOURCE_WORKOUTS,
    complete_sync,
    ensure_sync_state,
    mark_running,
    record_sync_error,
)
from app.integrations.hevy.client import HevyClient
from app.integrations.hevy.schemas import HevyWorkoutEvent, event_timestamp
from app.integrations.hevy.workouts import delete_workout, upsert_workout

log = structlog.get_logger()

# Deliberate re-read window. Hevy's `since` filter and our clock are not the same clock, and
# an event landing in the same second as the previous cursor could otherwise fall outside the
# next window. Five minutes of overlap costs a handful of idempotent upserts; a five-minute
# gap costs a workout nobody ever notices is missing.
EVENT_CURSOR_OVERLAP = dt.timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class DrainResult:
    """Everything the feed had to say, already ordered for application."""

    events: tuple[HevyWorkoutEvent, ...]  # OLDEST-FIRST
    pages_fetched: int
    cursor: dt.datetime


@dataclass(frozen=True, slots=True)
class EventSyncResult:
    """Counts only, never a payload -- this value is what callers log.

    `skipped_reason` is not an error. It is the answer to "why did an incremental sync do
    nothing?", which is otherwise indistinguishable from "nothing changed upstream".
    """

    pages_fetched: int
    events_applied: int
    workouts_updated: int
    workouts_deleted: int
    deletes_not_found: int
    skipped_reason: str | None = None


async def drain_events(client: HevyClient, *, since: dt.datetime) -> DrainResult:
    """Read every page of the events feed against ONE `since`, oldest-first. HEVY-02.

    Touches no database and applies nothing: separating the read from the write is what makes
    Rule 2 ("collect every page before applying anything") a property of the type rather than
    a discipline the caller has to remember.
    """
    # FOUND-04 as a guard, not a convention -- mirrors `app.core.time._require_aware`. A naive
    # value has no defined instant, so the checkpoint would be reinterpreted in whatever
    # offset the process happens to run in. The client's events endpoint checks this too;
    # duplicating it here means the drain fails before the first socket rather than after it.
    if since.tzinfo is None or since.tzinfo.utcoffset(since) is None:
        raise ValueError("naive datetime rejected: `since` must be timezone-aware UTC")

    # Rule 1. Never recompute this inside the loop.
    frozen_since = since

    collected: list[HevyWorkoutEvent] = []
    pages_fetched = 0
    page = 1
    while True:
        payload = await client.get_workout_events(since=frozen_since, page=page)
        pages_fetched += 1
        collected.extend(payload.events)
        # The empty-list arm is the second terminator: a server that returns a nonsense
        # `page_count` still stops when it runs out of data.
        if not payload.events or page >= payload.page_count:
            break
        page += 1

    # `.sort()` is stable, so two events sharing a timestamp keep
    # their relative feed order. That is the best available tiebreak -- Hevy gives no sequence
    # number.
    collected.sort(key=event_timestamp)

    # max(), never `collected[-1]` before the sort and never `utc_now()`. The newest event is
    # wherever it happens to be in the feed, and a clock-derived cursor would skip anything
    # logged between the last event and this call.
    cursor = max((event_timestamp(event) for event in collected), default=frozen_since)

    log.info("hevy_event_drain_completed", pages=pages_fetched, events=len(collected))
    return DrainResult(events=tuple(collected), pages_fetched=pages_fetched, cursor=cursor)


async def apply_events(
    session: AsyncSession, *, user_id: uuid.UUID, events: Sequence[HevyWorkoutEvent]
) -> tuple[int, int, int]:
    """Apply a drained, oldest-first event list. Caller owns the transaction.

    Each event gets its own SAVEPOINT so that one malformed workout snapshot is skipped
    rather than aborting the whole apply (Pitfall 11).
    """
    updated = 0
    deleted = 0
    not_found = 0
    for event in events:
        try:
            async with session.begin_nested():
                if event.type == "updated":
                    await upsert_workout(session, user_id=user_id, workout=event.workout)
                    updated += 1
                else:
                    existed = await delete_workout(
                        session, user_id=user_id, external_id=event.id
                    )
                    if existed:
                        deleted += 1
                    else:
                        # HEVY-04: a delete for a workout we never stored is a NO-OP. The
                        # feed can report a deletion for a workout created and deleted
                        # between two of our syncs.
                        not_found += 1
        except SQLAlchemyError as exc:
            # Class name only, never the exception's message: a DataError renders the bound
            # parameters, which here are this person's workout titles and weights (T-03-43).
            log.warning(
                "hevy_event_skipped", event_type=event.type, reason=type(exc).__name__
            )
    return updated, deleted, not_found


async def sync_workout_events(
    client: HevyClient,
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    user_id: uuid.UUID,
) -> EventSyncResult:
    """Incremental sync: drain the events feed, apply it, advance the cursor once. HEVY-02.

    Takes an `async_sessionmaker`, never an engine and never `Settings`: the caller owns the
    engine's lifetime, for the reasons `app/db/session.py` documents.
    """
    # D-09: deletion detection is the events feed and nothing else -- no periodic
    # full-reconciliation sweep in v1. The accepted risk is that a sync gap longer than Hevy
    # retains events for could leave a deleted workout lingering locally. `sync_workouts`
    # logs `hevy_workout_count_mismatch` against `/v1/workouts/count`, which is the cheap
    # detector if that ever happens in practice.
    async with sessionmaker() as session:
        state = await ensure_sync_state(
            session, user_id=user_id, provider=PROVIDER_HEVY, resource=RESOURCE_WORKOUTS
        )
        # `cursor_timestamp` first: it is the events feed's own checkpoint. `last_synced_at`
        # is the fallback for the very first incremental run after a full sync, which has no
        # events cursor yet.
        baseline = state.cursor_timestamp or state.last_synced_at
        if baseline is None:
            # No full sync has ever completed, so there is no window to be incremental FROM.
            # Draining from the epoch would be a full history import through an endpoint that
            # pages at 10 and is designed for deltas. Refuse, loudly and harmlessly.
            log.info("hevy_event_sync_skipped", reason="no_baseline")
            return EventSyncResult(
                0, 0, 0, 0, 0, skipped_reason="no baseline: run a full workout sync first"
            )
        since = baseline - EVENT_CURSOR_OVERLAP
        await mark_running(
            session, user_id=user_id, provider=PROVIDER_HEVY, resource=RESOURCE_WORKOUTS
        )
        await session.commit()
    log.info("hevy_event_sync_started", since=since.isoformat())

    try:
        drain = await drain_events(client, since=since)

        # One transaction for the whole drain is correct HERE (unlike the full sync, which
        # commits per page): a drain is bounded by what changed since the last run, and a
        # rollback simply means the next run re-reads the same window.
        async with sessionmaker() as session:
            updated, deleted, not_found = await apply_events(
                session, user_id=user_id, events=drain.events
            )
            # The cursor advances ONCE, in the same transaction as the events it accounts for.
            # A separate transaction could commit a cursor over an apply that was rolled back.
            await complete_sync(
                session,
                user_id=user_id,
                provider=PROVIDER_HEVY,
                resource=RESOURCE_WORKOUTS,
                last_synced_at=utc_now(),
                cursor_timestamp=drain.cursor,
                cursor_page=None,
            )
            await session.commit()
    except Exception as exc:
        # A FRESH session: the one that failed may hold an aborted transaction, in which case
        # every statement on it -- including the one recording the failure -- would be refused.
        async with sessionmaker() as session:
            await record_sync_error(
                session,
                user_id=user_id,
                provider=PROVIDER_HEVY,
                resource=RESOURCE_WORKOUTS,
                exc=exc,
            )
            await session.commit()
        # cursor_timestamp is NOT advanced on failure. Re-reading the same window next run is
        # free (every apply is idempotent); skipping it is unrecoverable.
        log.warning("hevy_event_sync_failed", reason=type(exc).__name__)
        raise

    log.info(
        "hevy_event_sync_completed",
        pages=drain.pages_fetched,
        applied=len(drain.events),
        updated=updated,
        deleted=deleted,
        not_found=not_found,
    )
    return EventSyncResult(
        pages_fetched=drain.pages_fetched,
        events_applied=len(drain.events),
        workouts_updated=updated,
        workouts_deleted=deleted,
        deletes_not_found=not_found,
    )
