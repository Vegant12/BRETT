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
from dataclasses import dataclass

import structlog

from app.integrations.hevy.client import HevyClient
from app.integrations.hevy.schemas import HevyWorkoutEvent, event_timestamp

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
