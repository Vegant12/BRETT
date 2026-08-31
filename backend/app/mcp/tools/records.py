"""Personal-records tool (MCP-02, MCP-03, MCP-05, MCP-06; D-01, D-02, D-03, D-04).

**D-01: the exercise is named, never identified.** A Hevy template id is not a parameter of this
tool and must not become one -- the ids are opaque (8-char hex for built-ins, UUIDs for custom
templates), so an id argument is a value Claude can only echo from a previous response or invent.

**D-02: zero matches and two or more matches BOTH short-circuit.** No auto-pick. Reporting a max
weight from one of two same-named templates is a wrong answer that looks exactly like a right one,
and ``exercise_templates.title`` genuinely has no uniqueness constraint.

**The name-resolution block below is a deliberate SECOND COPY of the one in ``progression.py``.**
The shared part -- the tenant-scoped, bound-parameter title lookup -- already lives in
``_common.find_templates_by_title`` and is imported, not duplicated. What remains here is four
lines that construct THIS tool's own response model with THIS tool's own field set. Factoring those
out would mean one helper that knows about two unrelated response shapes, and every future
divergence between them would have to be threaded through it as a flag. Two short, honest copies
beat one helper with a mode switch.

**No union RETURN annotation.** ``mcp 2.0.0`` sets ``wrap_output=True`` for unions, which would
nest every successful response under ``{"result": ...}``. The disambiguation and the payload are
FIELDS on one model for that reason.
"""

from typing import Annotated

from mcp.server.mcpserver import Context
from pydantic import Field

from app.analytics.records import get_personal_records
from app.mcp.context import AppContext
from app.mcp.tools._common import (
    MAX_WEEKS,
    find_templates_by_title,
    read_only_session,
    resolve_user_id,
    safe_tool,
    window_from_weeks,
)
from app.mcp.tools.schemas import (
    ExerciseCandidate,
    PersonalRecordsResponse,
)


def _degraded_records() -> PersonalRecordsResponse:
    """The payload Claude gets when the tool body raised (MCP-06, T-06-01).

    ``data_available=False`` distinguishes "the tool could not reach its data" from "you hold no
    records for that exercise" -- byte-identical claims without this field, and Claude would
    narrate an outage as a training history that does not exist.
    """
    return PersonalRecordsResponse(
        data_available=False,
        requested_name="",
        matched=False,
        candidates=[],
        records=None,
    )


@safe_tool(degraded=_degraded_records)
async def fitness_get_personal_records(
    ctx: Context[AppContext],
    exercise_name: Annotated[
        str,
        Field(
            min_length=1,
            max_length=255,
            description="The exercise name as it appears in Hevy, e.g. 'Squat (Barbell)'.",
        ),
    ],
    weeks: Annotated[
        int,
        Field(
            ge=1,
            le=MAX_WEEKS,
            description="How far back to search for records. Max 52; defaults to the full year.",
        ),
    ] = MAX_WEEKS,
) -> PersonalRecordsResponse:
    """One exercise's personal records -- max weight, max reps at a weight, best estimated 1RM,
    best session volume and rep PR -- each with the date it was reached. Warm-up sets are excluded.

    Give the exercise by NAME. If the name matches no exercise, or more than one, no records are
    computed and `candidates` lists what was found.
    """
    # `weeks` defaults to MAX_WEEKS (52), not to the 12 that every other window-taking tool uses.
    # "What is my PR" is an all-time-ish question in a way that "am I progressing" is not: a
    # 12-week default would report a three-month best AS a personal record, with the narrower
    # window visible only to a reader who checked the parameter default.
    user_id = resolve_user_id(ctx)
    async with read_only_session(ctx) as session:
        matches = await find_templates_by_title(session, user_id=user_id, name=exercise_name)

        # D-02, identical semantics to `fitness_get_exercise_progression`. `matched=False` with an
        # EMPTY `candidates` means "no such exercise"; `matched=False` with two or more means "be
        # more specific". Both are ordinary SUCCESSFUL results, so `is_error` stays false and the
        # requested name never reaches Claude through the SDK's error-text channel.
        if len(matches) != 1:
            return PersonalRecordsResponse(
                data_available=True,
                requested_name=exercise_name,
                matched=False,
                candidates=[
                    ExerciseCandidate(title=title, exercise_template_external_id=external_id)
                    for title, external_id in matches
                ],
                records=None,
            )

        _title, external_id = matches[0]
        start_day, end_day = await window_from_weeks(session, user_id=user_id, weeks=weeks)
        result = await get_personal_records(
            session,
            user_id=user_id,
            exercise_template_external_id=external_id,
            start_day=start_day,
            end_day=end_day,
        )

    # NOT truncated, and that is a decision rather than an omission. The result is five records
    # plus at most ~12 reps-at-weight rows -- measured at 1,601 bytes structured / 3,940 on the
    # wire, well inside the 8 KB budget -- and the row count is bounded by the DATA (the live
    # account has at most 12 distinct weights per exercise), not by how wide a window is asked for.
    # A cap here would add a `*_truncated` flag that is always false, which is a field nobody reads
    # and therefore a field nobody would notice becoming true.
    return PersonalRecordsResponse(
        data_available=True,
        requested_name=exercise_name,
        matched=True,
        candidates=[],
        records=result,
    )
