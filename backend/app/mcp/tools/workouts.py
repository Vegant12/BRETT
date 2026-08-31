"""The two tools that show actual training sessions (MCP-02, MCP-03, MCP-05, MCP-06;
D-09, D-10, D-11, D-12).

**These are the only two tools in this phase with no `app/analytics/` function behind them**, and
that is the thing a reader will get wrong. Every other Phase 6 tool is a thin adapter over a
verified analytics result; these two adapt a REPOSITORY PROJECTION instead
(`app/db/repositories/workouts.py`). The distinction matters because "no analytics function" reads
like "raw table access", and raw table access is what REQUIREMENTS.md puts explicitly out of
scope. What these tools expose is a purpose-built projection with a FIXED shape and a HARD count
cap -- `fitness_get_recent_workouts` can never return more than `MAX_RECENT_WORKOUTS` rows and
`fitness_get_workout` can never return more than `MAX_WORKOUT_SETS` sets, at any argument. There
is no tool here that hands Claude a table and lets it choose the columns.

**They are a PAIR, and the pairing is the design** (D-09, D-12). The list is deliberately
summary-only -- no per-exercise and no per-set detail -- so it stays compact however many workouts
are asked for; `fitness_get_workout` exists to expand exactly one of them, keyed on the
`workout_id` the list already echoed. List, then drill in. Neither tool takes a date: D-10 makes
the list count-based rather than days-based, because a days-based window lets a high-frequency
training block return an unpredictably large payload, and D-12 keys the detail on the Hevy
external id rather than a calendar day, because a date-keyed lookup would need a
same-day-multiple-workouts policy that an id-keyed one never has to invent.

**`found` and `data_available` are different facts and must never be collapsed** (MCP-06). See
`fitness_get_workout`'s body comment; conflating them is how "you have no workout on record" gets
said about a database outage.

`ctx` MUST be annotated `Context[AppContext]`. Unannotated, the SDK exposes it to the model as a
required string argument and every call fails schema validation (`ping.py`).
"""

from typing import Annotated

from mcp.server.mcpserver import Context
from pydantic import Field

from app.analytics.metadata import FRESHNESS_RESOURCES_WORKOUTS, build_freshness
from app.db.repositories.workouts import recent_workout_summaries
from app.mcp.context import AppContext
from app.mcp.tools._common import (
    MAX_RECENT_WORKOUTS,
    local_timezone,
    read_only_session,
    resolve_user_id,
    safe_tool,
)
from app.mcp.tools.schemas import RecentWorkoutsResponse, WorkoutSummary


def _degraded_recent() -> RecentWorkoutsResponse:
    """The payload Claude gets when this tool could not reach its data (T-06-01).

    `limit=0` rather than the requested limit: the echoed limit is documented as "that is all
    there is", and echoing the request back on a failure path would invite exactly the reading the
    `data_available` flag exists to prevent. A factory rather than a module constant so the
    placeholder is built fresh per failure and cannot be mutated across calls.
    """
    return RecentWorkoutsResponse(
        data_available=False,
        limit=0,
        workouts=[],
        freshness=None,
    )


@safe_tool(degraded=_degraded_recent)
async def fitness_get_recent_workouts(
    ctx: Context[AppContext],
    limit: Annotated[
        int,
        Field(
            ge=1,
            le=MAX_RECENT_WORKOUTS,
            description="How many recent workouts to list, newest first. Max 25.",
        ),
    ] = 10,
) -> RecentWorkoutsResponse:
    """The most recent workouts as compact summaries: date, title, duration, exercise count,
    hard sets and tonnage. No per-exercise or per-set detail -- call `fitness_get_workout` with a
    `workout_id` from this list for that.

    `hard_sets` excludes warm-ups. `tonnage_kg` is null when no set in the session recorded both a
    weight and a rep count, which is not the same as zero; `tonnage_sets` reports how many sets the
    figure was actually computed over.
    """
    # The bound on `limit` is declared, not checked here. `Field(ge=1, le=MAX_RECENT_WORKOUTS)`
    # lands `{"minimum": 1, "maximum": 25, "default": 10}` in `inputSchema` AND is enforced by the
    # SDK before this body runs (T-06-05). Advertising the bound prevents far more bad calls than
    # a prettier in-body error message ever would.
    user = resolve_user_id(ctx)
    async with read_only_session(ctx) as session:
        # ASVS V4 / T-06-02: whose data this is was resolved server-side above and is never a tool
        # argument, so it cannot appear in `inputSchema` for the model to choose.
        tz = await local_timezone(session, user_id=user)
        rows = await recent_workout_summaries(session, user_id=user, tz=tz, limit=limit)
        freshness = await build_freshness(
            session, user_id=user, resources=FRESHNESS_RESOURCES_WORKOUTS
        )
    # Built after the session closes, and only because every value above is already a plain
    # dataclass or Pydantic model -- nothing here triggers a lazy load.
    return RecentWorkoutsResponse(
        data_available=True,
        limit=limit,
        workouts=[
            WorkoutSummary(
                # D-12/T-06-08: the Hevy external id, which is the id `fitness_get_workout` takes.
                # The internal `workouts.id` surrogate never leaves the repository.
                workout_id=row.external_id,
                local_day=row.local_day,
                title=row.title,
                duration_minutes=row.duration_minutes,
                exercise_count=row.exercise_count,
                hard_sets=row.hard_sets,
                tonnage_sets=row.tonnage_sets,
                tonnage_kg=row.tonnage_kg,
            )
            for row in rows
        ],
        freshness=freshness,
    )
