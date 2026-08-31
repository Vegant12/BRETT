"""Freshness and coverage: the envelope every analytics response carries (DQ-01, DQ-02).

Four rules, each of which exists because the obvious alternative fails SILENTLY -- which is
this project's real risk, a plausible-looking number that is quietly wrong or quietly sparse.

1. DQ-01 reports a PER-RESOURCE breakdown, not one collapsed timestamp. A per-muscle answer
   depends on BOTH the `workouts` sync and the `exercise_templates` sync, because the muscle
   map comes from the templates -- so a stale template sync silently changes every per-muscle
   number with no error anywhere in the stack. On the live database the two were 25 minutes
   apart. A single "oldest of the relevant resources" scalar is a lossy projection Phase 6 can
   derive in one line; the reverse is impossible.

2. Only `last_synced_at` crosses this boundary. The bookkeeping row's stored error text is
   produced by `format_sync_error`, whose entire job is bounding what leaks; forwarding it here
   would undo that (MCP-06, ASVS V8). The row's `status` and its two resume cursors are
   operator-CLI concerns -- `hevy/sync.py::ResourceStatus` carries them and is right to, since
   an operator reading a terminal is not Claude reading a tool response. Correct THERE,
   forbidden HERE.

3. D-05's threshold is fewer than 2 SESSIONS, not 2 weeks. One session cannot support a
   per-week rate or a trend claim: dividing a single workout across a twelve-week window yields
   0.08 sessions/week, which is arithmetically true and coaching nonsense.

4. `earliest_data_at` is what lets Claude tell "you did not train in this window" apart from
   "your synced history does not reach back that far". Without it both answers are a zero, and
   the second one is a sync problem being reported as a training problem.

Read-only, like everything else under `app/analytics/`: nothing here commits, and the CALLER
owns the transaction. Every function takes the session positionally and everything else
keyword-only, matching `app/db/repositories/`.
"""

import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from types import MappingProxyType

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.schemas import CoverageMetadata, FreshnessMetadata, MeasurementCoverage
from app.db.models.body import BodyMeasurement
from app.db.models.workout import Workout
from app.db.repositories.sync_state import (
    PROVIDER_HEVY,
    RESOURCE_BODY_MEASUREMENTS,
    RESOURCE_EXERCISE_TEMPLATES,
    RESOURCE_WORKOUTS,
    get_sync_state,
)

# D-05. One session cannot support a "per week" rate or a trend claim; two is the minimum for
# that arithmetic to mean anything. ONE constant, reused by volume, frequency, their per-muscle
# rows and every test -- a second copy is how the response-level flag and a row-level flag would
# eventually disagree about the same window.
INSUFFICIENT_DATA_SESSION_THRESHOLD = 2

# Which bookkeeping rows actually feed a given answer (DQ-01). A per-muscle number is only as
# fresh as the STALER of the two: the muscle map comes from exercise_templates, so a stale
# template sync silently changes every per-muscle figure with no error anywhere in the stack.
FRESHNESS_RESOURCES_WORKOUTS: tuple[str, ...] = (RESOURCE_WORKOUTS,)
FRESHNESS_RESOURCES_MUSCLE: tuple[str, ...] = (RESOURCE_WORKOUTS, RESOURCE_EXERCISE_TEMPLATES)
FRESHNESS_RESOURCES_BODY: tuple[str, ...] = (RESOURCE_BODY_MEASUREMENTS,)
# BODY-02 reads BOTH sides -- a body-weight trend and a training-progression signal -- so its
# answer is only as fresh as the STALEST of the three. A stale template sync silently changes
# every e1RM eligibility decision (exercise_type is the D-03 gate), which changes the progression
# signal, with no error anywhere in the stack.
FRESHNESS_RESOURCES_ALL: tuple[str, ...] = (
    RESOURCE_WORKOUTS,
    RESOURCE_EXERCISE_TEMPLATES,
    RESOURCE_BODY_MEASUREMENTS,
)

# D-15. Keys are the window length in DAYS; values are the minimum number of distinct measured
# days that window needs before its average is believable. Recalibrated from
# `INSUFFICIENT_DATA_SESSION_THRESHOLD`'s per-SESSION cadence to a per-DAY one -- a weigh-in is
# not a training session and two of them do not carry the same weight over a month as two
# workouts do over a week.
#
# Why these three numbers and not others: each is a little under half the window, so an average
# always rests on a plurality of the days it claims to cover. Independent by design -- a 30-day
# average can be trustworthy while the 7-day one is not, which is exactly the case a single
# response-level flag cannot express.
MEASURED_DAY_FLOORS: Mapping[int, int] = MappingProxyType({7: 3, 14: 5, 30: 10})


def is_insufficient(sessions: int) -> bool:
    """DQ-02 / D-05: fewer than two sessions is not enough to believe a per-week figure."""
    return sessions < INSUFFICIENT_DATA_SESSION_THRESHOLD


async def sessions_in_window(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    utc_start: dt.datetime,
    utc_end: dt.datetime,
) -> int:
    """Distinct training sessions whose start falls in the half-open window.

    Counts WORKOUTS, not exercises and not sets: one workout containing three hamstring
    exercises is one session. Counting at any finer grain inflates this by up to 4x on real
    data, which turns every "per week" figure into fiction that still looks plausible.

    The predicate keeps `Workout.start_time` BARE on the left of both comparisons so
    `ix_workouts_user_id_start_time` stays usable; wrapping it in AT TIME ZONE was measured on
    the live database as a Seq Scan removing 299 of 327 rows.

    `user_id` is keyword-only with no default: ASVS V4 -- the schema is multi-user-ready, so an
    unscoped count is a cross-tenant disclosure a single-user suite cannot see.
    """
    count = await session.scalar(
        select(func.count())
        .select_from(Workout)
        .where(
            Workout.user_id == user_id,
            Workout.start_time >= utc_start,
            Workout.start_time < utc_end,
        )
    )
    return int(count or 0)


async def earliest_workout_at(session: AsyncSession, *, user_id: uuid.UUID) -> dt.datetime | None:
    """The user's oldest synced workout, across ALL time -- deliberately not window-scoped.

    D-06: this is what separates "you did not train in that window" from "your synced history
    does not reach back that far". Scoping it to the window would make the two identical and
    the field pointless.
    """
    result: dt.datetime | None = await session.scalar(
        select(func.min(Workout.start_time)).where(Workout.user_id == user_id)
    )
    return result


async def build_freshness(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    resources: Sequence[str],
    provider: str = PROVIDER_HEVY,
) -> FreshnessMetadata:
    """DQ-01. One `last_synced_at` per requested resource, and NOTHING else from the row.

    A resource that has never synced reports `None` rather than being omitted: "never synced"
    is the answer to "when was this last synced", and a missing key is indistinguishable from
    "the resource does not exist".

    Iterated in sorted order so the map is deterministic and diffable between runs.
    """
    out: dict[str, dt.datetime | None] = {}
    for resource in sorted(resources):
        state = await get_sync_state(session, user_id=user_id, provider=provider, resource=resource)
        # ONLY the last-synced timestamp is read off the row. MCP-06: the row's stored error
        # text, its run status and its two resume cursors are internal bookkeeping that must
        # never reach anything Claude can read, and `format_sync_error` exists precisely to
        # bound that leak at the point it is written.
        # Forbidden here: last_error, status, cursor_page, cursor_timestamp -- operator CLI only.
        out[resource] = state.last_synced_at if state is not None else None
    return FreshnessMetadata(resources=out)


async def build_coverage(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    utc_start: dt.datetime,
    utc_end: dt.datetime,
) -> CoverageMetadata:
    """DQ-02 / D-06's three fields, exactly. Do not add a fourth."""
    sessions = await sessions_in_window(
        session, user_id=user_id, utc_start=utc_start, utc_end=utc_end
    )
    return CoverageMetadata(
        sessions_in_window=sessions,
        insufficient_data=is_insufficient(sessions),
        earliest_data_at=await earliest_workout_at(session, user_id=user_id),
    )


def is_measurement_insufficient(*, window_days: int, measured_days: int) -> bool:
    """DQ-02 / D-15: is this specific window's average believable?

    An unsupported window length is a caller bug, not a permissive default -- raising beats
    silently accepting a window whose floor nobody chose. The message names the failure and
    carries no value, because it will be logged (FOUND-05).
    """
    floor = MEASURED_DAY_FLOORS.get(window_days)
    if floor is None:
        raise ValueError("unsupported measurement window length")
    return measured_days < floor


def build_measurement_coverage(
    *, window_days: int, measured_days: int, earliest_measurement_at: dt.date | None
) -> MeasurementCoverage:
    """DQ-02 for a day-grained window. PURE and synchronous, unlike ``build_coverage``.

    The divergence from its session-grained sibling is deliberate and is the one place the copy
    breaks. ``build_coverage`` issues its own count query because a workout count needs one;
    BODY-01 fetches all 35 candidate rows in a SINGLE query and folds them five ways, so calling
    an async builder per window would turn one query into five for no new information. Keeping
    this pure also puts D-15's floors in the fast suite instead of behind Docker.

    Note the argument type: LOCAL DATES and counts derived from them, never UTC instants.
    ``measured_on`` is a calendar ``Date`` column, so threading ``utc_start``/``utc_end`` through
    here by analogy with ``build_coverage`` would be wrong.
    """
    return MeasurementCoverage(
        window_days=window_days,
        measured_days_in_window=measured_days,
        insufficient_data=is_measurement_insufficient(
            window_days=window_days, measured_days=measured_days
        ),
        earliest_measurement_at=earliest_measurement_at,
    )


async def earliest_measurement_at(session: AsyncSession, *, user_id: uuid.UUID) -> dt.date | None:
    """The user's oldest synced weigh-in, across ALL time -- deliberately not window-scoped.

    The body-weight analogue of ``earliest_workout_at`` and for the same reason: it is what
    separates "you did not weigh in during that window" from "your synced history does not reach
    back that far". Scoping it to the window would make the two identical and the field pointless.

    ``user_id`` is keyword-only with no default (ASVS V4): the schema is multi-user-ready, so an
    unscoped read is a cross-tenant disclosure a single-user suite cannot see.
    """
    result: dt.date | None = await session.scalar(
        select(func.min(BodyMeasurement.measured_on)).where(BodyMeasurement.user_id == user_id)
    )
    return result
