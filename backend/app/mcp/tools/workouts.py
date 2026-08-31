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
from app.db.repositories.workouts import recent_workout_summaries, workout_detail
from app.mcp.context import AppContext
from app.mcp.tools._common import (
    MAX_RECENT_WORKOUTS,
    MAX_WORKOUT_SETS,
    local_timezone,
    read_only_session,
    resolve_user_id,
    safe_tool,
)
from app.mcp.tools.schemas import (
    RecentWorkoutsResponse,
    WorkoutDetail,
    WorkoutDetailResponse,
    WorkoutExerciseDetail,
    WorkoutSetDetail,
    WorkoutSummary,
)


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


def _degraded_workout() -> WorkoutDetailResponse:
    """The payload Claude gets when this tool could not reach its data (T-06-01).

    `requested_workout_id=""` rather than the id that was asked for. `safe_tool`'s factory takes
    no arguments by design -- it must not close over anything from a failed call -- and an empty
    string is honest about that where a fabricated echo would not be.

    Note `found=False` here means something DIFFERENT from `found=False` on the success path
    below, and the pair of flags is what distinguishes them: this payload carries
    `data_available=False` alongside it.
    """
    return WorkoutDetailResponse(
        data_available=False,
        requested_workout_id="",
        found=False,
        workout=None,
        freshness=None,
    )


@safe_tool(degraded=_degraded_workout)
async def fitness_get_workout(
    ctx: Context[AppContext],
    workout_id: Annotated[
        str,
        Field(
            min_length=1,
            max_length=64,
            description="The workout id echoed by fitness_get_recent_workouts.",
        ),
    ],
) -> WorkoutDetailResponse:
    """The full exercise and set breakdown for exactly one workout, identified by the
    `workout_id` that `fitness_get_recent_workouts` returns for it. Includes warm-up sets, each
    labelled by `set_type`.

    `found` is false when no workout carries that id -- an ordinary answer, not an error. Never
    sum these sets into a hard-set or volume figure; those come from the volume tools, which
    exclude warm-ups.
    """
    # `max_length=64` matches `workouts.external_id`'s `String(64)`, so an over-long id is
    # rejected by the SDK before any query runs -- the cheapest available ASVS V5 control
    # (T-06-04). D-12: this is the HEVY external id, never a calendar date and never the internal
    # `workouts.id` UUID. A date-keyed lookup would need a same-day-multiple-workouts policy that
    # an id-keyed one never has to invent.
    user = resolve_user_id(ctx)
    async with read_only_session(ctx) as session:
        # The repository needs the timezone for the same reason the list does: a workout belongs
        # to the USER's local day (FOUND-03), and the two tools must agree about which day that
        # is, or one session is dated 2026-08-30 in the list and 2026-08-31 in the detail view.
        tz = await local_timezone(session, user_id=user)
        row = await workout_detail(
            session,
            user_id=user,
            external_id=workout_id,
            tz=tz,
            max_sets=MAX_WORKOUT_SETS,
        )
        freshness = await build_freshness(
            session, user_id=user, resources=FRESHNESS_RESOURCES_WORKOUTS
        )

    if row is None:
        # `found=False` and `data_available=False` are DIFFERENT FACTS and must never be
        # collapsed into one flag. This branch is `data_available=True, found=False`: the tool
        # reached the data and there is no workout with that id. The degraded payload above is
        # `data_available=False`: the tool could not reach the data at all and knows nothing about
        # whether the workout exists. Conflating them is how "you have no workout on record" gets
        # said about a database outage -- a confident wrong answer with no signal attached.
        return WorkoutDetailResponse(
            data_available=True,
            requested_workout_id=workout_id,
            found=False,
            workout=None,
            freshness=freshness,
        )

    return WorkoutDetailResponse(
        data_available=True,
        requested_workout_id=workout_id,
        found=True,
        workout=WorkoutDetail(
            workout_id=row.external_id,
            local_day=row.local_day,
            title=row.title,
            duration_minutes=row.duration_minutes,
            exercises=[
                WorkoutExerciseDetail(
                    exercise_index=exercise.exercise_index,
                    title=exercise.title,
                    exercise_template_external_id=exercise.exercise_template_external_id,
                    supersets_id=exercise.supersets_id,
                    sets=[
                        WorkoutSetDetail(
                            set_index=logged.set_index,
                            # Carried on EVERY set: this projection includes warm-ups, and without
                            # the label a reader cannot tell one from a working set.
                            set_type=logged.set_type,
                            weight_kg=logged.weight_kg,
                            reps=logged.reps,
                            distance_meters=logged.distance_meters,
                            duration_seconds=logged.duration_seconds,
                            rpe=logged.rpe,
                        )
                        for logged in exercise.sets
                    ],
                )
                for exercise in row.exercises
            ],
            # `total_sets` is the TRUE pre-truncation count from the repository, so the comparison
            # is against what the session actually held rather than against what survived
            # (T-06-05). A silent truncation would be a wrong answer; a flagged one is a smaller
            # answer.
            sets_truncated=row.total_sets > MAX_WORKOUT_SETS,
            total_sets=row.total_sets,
        ),
        freshness=freshness,
    )
