"""Progression and plateau tools (MCP-02, MCP-03, MCP-05, MCP-06; D-01, D-02, D-03, D-04, D-05).

**D-01: Claude asks by NAME. A Hevy template id is never a tool parameter.** The ids are opaque
strings (8-char hex for Hevy's built-ins, full UUIDs for user-custom templates) that carry no
meaning a model could reason about, so exposing one as an argument would make every call depend on
a value Claude can only have obtained from an earlier response -- or invented. The name is what the
user says out loud; the id resolution happens here, server-side, in ``find_templates_by_title``.

**D-02: no silent auto-pick, ever.** ``exercise_templates.title`` carries no uniqueness constraint
and Hevy ships built-in and user-custom templates that can share a title, so "Bench Press
(Barbell)" legitimately matching two rows is a real case, not a hypothetical. Picking one would
answer a progression question from half the data, and the answer would look entirely plausible --
a wrong-exercise answer with no signal is worse than an extra round trip. So zero matches and two
or more matches BOTH short-circuit with ``matched=False`` and the candidate list, and both are
ordinary successful results (``is_error`` stays false).

**No union RETURN annotation, here or anywhere in this phase.** ``mcp 2.0.0`` sets
``wrap_output=True`` for union returns, which would nest EVERY response -- including every
successful one -- under ``{"result": ...}`` in ``structured_content``. A single ``BaseModel``
return with optional payload FIELDS is left unwrapped, which is why ``matched``/``candidates``/
``progression`` live as fields on one model rather than as alternative return types.
"""

from typing import Annotated

from mcp.server.mcpserver import Context
from pydantic import Field

from app.analytics.progression import (
    DEFAULT_PLATEAU_LOOKBACK_WEEKS,
    get_exercise_progression,
    get_plateaus,
)
from app.mcp.context import AppContext
from app.mcp.tools._common import (
    MAX_PLATEAU_EXERCISES,
    MAX_PROGRESSION_POINTS,
    MAX_WEEKS,
    find_templates_by_title,
    read_only_session,
    resolve_user_id,
    safe_tool,
    truncate,
    window_from_weeks,
)
from app.mcp.tools.schemas import (
    ExerciseCandidate,
    ExerciseProgressionResponse,
    PlateauResponse,
)


def _degraded_progression() -> ExerciseProgressionResponse:
    """The payload Claude gets when the tool body raised (MCP-06, T-06-01).

    ``data_available=False`` is the whole point: it is NOT the same claim as "you have never
    trained that exercise", which an empty ``points`` list with ``data_available=True`` would make.
    """
    return ExerciseProgressionResponse(
        data_available=False,
        requested_name="",
        matched=False,
        candidates=[],
        progression=None,
        points_truncated=False,
        total_points=0,
    )


@safe_tool(degraded=_degraded_progression)
async def fitness_get_exercise_progression(
    ctx: Context[AppContext],
    exercise_name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=255,
            description="The exercise name as it appears in Hevy, e.g. 'Bench Press (Barbell)'.",
        ),
    ],
    weeks: Annotated[
        int,
        Field(ge=1, le=MAX_WEEKS, description="Whole weeks back from today, ending today. Max 52."),
    ] = 12,
) -> ExerciseProgressionResponse:
    """One exercise's progression over the last N weeks: per training day, the sets, reps, volume,
    best weight, best reps and an estimated 1RM where the modality and rep range make one
    meaningful.

    Give the exercise by NAME. If the name matches no exercise, or more than one, no analytics are
    computed and `candidates` lists what was found so you can ask again with an exact name.
    """
    user_id = resolve_user_id(ctx)
    async with read_only_session(ctx) as session:
        matches = await find_templates_by_title(session, user_id=user_id, name=exercise_name)

        # D-02. `matched=False` with an EMPTY `candidates` means "no such exercise"; `matched=False`
        # with two or more means "be more specific". Both are ordinary SUCCESSFUL results -- the
        # tool did exactly what it was asked -- so nothing is raised and `is_error` stays false.
        if len(matches) != 1:
            return ExerciseProgressionResponse(
                data_available=True,
                requested_name=exercise_name,
                matched=False,
                candidates=[
                    ExerciseCandidate(title=title, exercise_template_external_id=external_id)
                    for title, external_id in matches
                ],
                progression=None,
                points_truncated=False,
                total_points=0,
            )

        _title, external_id = matches[0]
        start_day, end_day = await window_from_weeks(session, user_id=user_id, weeks=weeks)
        result = await get_exercise_progression(
            session,
            user_id=user_id,
            exercise_template_external_id=external_id,
            start_day=start_day,
            end_day=end_day,
        )

    # The TAIL, not the head. "Am I progressing?" is a question about recent sessions, so the
    # points that must survive the cap are the most recent ones; slicing from the front would
    # answer it with a year-old series and no indication that it had.
    total_points = len(result.points)
    points_truncated = total_points > MAX_PROGRESSION_POINTS
    kept = result.points[-MAX_PROGRESSION_POINTS:]
    # `model_copy` rather than rebuilding `ExerciseProgressionResult` field by field: a field added
    # to that model later would be silently DROPPED by a hand-written constructor call here, and
    # nothing in the type checker or the tests would notice.
    progression = result.model_copy(update={"points": kept})

    return ExerciseProgressionResponse(
        data_available=True,
        requested_name=exercise_name,
        matched=True,
        candidates=[],
        progression=progression,
        points_truncated=points_truncated,
        total_points=total_points,
    )


def _degraded_plateaus() -> PlateauResponse:
    """The payload Claude gets when the tool body raised (MCP-06, T-06-01).

    Every window field is ``None`` rather than a plausible default: a degraded response that
    carried a lookback window would let Claude report "nothing is plateaued over the last 12 weeks"
    when the truth is that no weeks were examined at all.
    """
    return PlateauResponse(
        data_available=False,
        plateaued_only=True,
        lookback_weeks=None,
        lookback_start=None,
        lookback_end=None,
        exercises=[],
        exercises_truncated=False,
        total_exercises=0,
        coverage=None,
        freshness=None,
    )


@safe_tool(degraded=_degraded_plateaus)
async def fitness_get_plateaus(
    ctx: Context[AppContext],
    lookback_weeks: Annotated[
        int,
        Field(ge=1, le=MAX_WEEKS, description="Weeks of history to judge against. Max 52."),
    ] = DEFAULT_PLATEAU_LOOKBACK_WEEKS,
    plateaued_only: Annotated[
        bool,
        Field(description="Return only exercises judged plateaued. Set false to see every one."),
    ] = True,
) -> PlateauResponse:
    """Exercises that have stopped progressing, with the lookback window, the threshold and the
    minimum-session and minimum-elapsed-day rules each verdict was reached under.
    """
    user_id = resolve_user_id(ctx)
    async with read_only_session(ctx) as session:
        # D-05: `lookback_weeks` goes STRAIGHT through -- no `window_from_weeks` conversion, unlike
        # every other window-taking tool in this phase. `get_plateaus` takes a relative window on
        # purpose, because a plateau is always measured back from today ("you have not PR'd in 40
        # days" is only meaningful relative to now) and it resolves the anchor day in the user's
        # timezone itself. Handing it a start/end pair computed here would duplicate that
        # resolution and let a stale end date freeze a duration that should still be accruing.
        # The `Field(ge=1)` bound above is also what makes the function's own
        # `ValueError("lookback_weeks must be positive")` unreachable from MCP (T-06-01).
        report = await get_plateaus(session, user_id=user_id, lookback_weeks=lookback_weeks)

    candidates = (
        [e for e in report.exercises if e.plateaued] if plateaued_only else list(report.exercises)
    )
    # Longest-standing plateaus first, so the cap keeps the rows a coach would act on. The full
    # key is total and deterministic: `not plateaued` sorts the stalled ones ahead of the rest when
    # `plateaued_only=False`, the negated duration puts the longest first, and the external id
    # breaks remaining ties so two runs over the same data cannot disagree.
    candidates.sort(
        key=lambda e: (
            not e.plateaued,
            -(e.plateau_duration_days or 0),
            e.exercise_template_external_id,
        )
    )
    # `total_exercises` counts the FILTERED candidate set, not the whole report, so "3 of 47
    # plateaued, showing 3" is expressible rather than being flattened into one ambiguous number.
    exercises, exercises_truncated, total_exercises = truncate(candidates, MAX_PLATEAU_EXERCISES)

    # PROG-03 requires the window and the threshold to travel WITH the result, and `PlateauResult`
    # already echoes both per exercise (`threshold_percent`, `min_sessions`, `min_elapsed_days`,
    # `lookback_start`, `lookback_end`). Nothing is re-derived here -- a second copy of the
    # threshold in this module is a second copy that drifts.
    return PlateauResponse(
        data_available=True,
        plateaued_only=plateaued_only,
        lookback_weeks=report.lookback_weeks,
        lookback_start=report.lookback_start,
        lookback_end=report.lookback_end,
        exercises=exercises,
        exercises_truncated=exercises_truncated,
        total_exercises=total_exercises,
        coverage=report.coverage,
        freshness=report.freshness,
    )
