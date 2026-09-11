"""BRETT's second MCP write path, plus its required companion read (PHYS-06..PHYS-08, PHYS-11;
MCP-07, MCP-08).

`fitness_log_physique_observation` is the SECOND tool under `app/mcp/` allowed to commit.
`test_mcp_isolation._WRITE_ALLOWLIST` names this module alongside `program_switch.py` and asserts
that allowlist holds exactly TWO entries -- a third write tool either fails the write-import ban
(no allowlist at all) or fails that length assertion. The guard was WIDENED, never loosened to a
prefix or substring check.

Unlike `program_switch.py`, this module ALSO holds a read tool
(`fitness_get_latest_physique_observation`) in the same file, so both `read_only_session` and
`writable_session` are imported here, deliberately. The reason the two live together is PHYS-07:
the read is the documented precursor to the write, and 17-CONTEXT.md D-07 folds the supersede
correction into the write tool's own signature rather than adding a third module -- putting the
read in a sibling file would leave one module holding a single tool that only exists to be called
before the other one.

There is NO confirmation-token ceremony here, and its absence is a decision rather than an
omission (PHYS-06). `program_switch.py`'s two-call token gates an IRREVERSIBLE reclassification of
every future recomposition verdict. This tool appends a dated row and destroys nothing: the
correction path for a mistake is PHYS-08's supersede, which is itself just another append. So
`destructive_hint=False`, and a token would be ceremony protecting nothing.

Per 12-RESEARCH.md Pitfall A (inherited unchanged), this module must NOT import `insert`, `update`
or `delete` from `sqlalchemy` -- `test_mcp_isolation._WRITE_IMPORT` bans that across the WHOLE
`app/mcp/` package with NO allowlist. Every write statement lives in
`app/db/repositories/physique.py`; this module only calls into it and owns the commit.
"""

import uuid
from typing import Annotated

from mcp.server.mcpserver import Context
from pydantic import Field

from app.db.models.physique import (
    PHYSIQUE_RATING_ANCHORS,
    PHYSIQUE_RATING_DISCLAIMER,
    PhotoAngle,
    PoseState,
)
from app.db.repositories.physique import (
    RatingEntry,
    create_observation,
    get_latest_observation,
    get_observation,
)
from app.mcp.context import AppContext
from app.mcp.tools._common import (
    local_today,
    read_only_session,
    resolve_user_id,
    safe_tool,
    writable_session,
)
from app.mcp.tools.schemas import (
    LatestPhysiqueObservationResponse,
    PhysiqueLogResponse,
    PhysiqueLogStatus,
    PhysiqueObservationView,
    PhysiqueRatingInput,
    PhysiqueRatingView,
)
from app.normalization.muscles import CanonicalMuscleGroup

# Unlike `program_switch.py`'s single `_REFUSAL_REASON` (which is deliberately undifferentiated
# because distinguishing its four token failures would be an oracle), these refusals name the
# problem: the inputs are the model's own data, not a credential, so telling it which field to fix
# leaks nothing and is the difference between a fixable call and a guessing loop.
_REFUSAL_SUPERSEDE_PAIR = (
    "Nothing was logged. Superseding an earlier observation needs BOTH "
    "`supersedes_observation_id` and `superseded_reason`. Send both, or neither."
)
_REFUSAL_SUPERSEDE_TARGET = (
    "Nothing was logged. `supersedes_observation_id` does not name an observation that is yours "
    "and not already superseded. Call fitness_get_latest_physique_observation to read the current "
    "observation's id."
)


def _coverage_refusal(*, missing: list[str], duplicated: list[str]) -> str:
    """The refusal text for an incomplete or duplicated rating set (D-07's 19-row invariant).

    Interpolates MUSCLE GROUP NAMES, never an exception. `_validate_rating_coverage` in the
    repository raises a `ValueError` carrying almost this text, and letting that exception escape
    to `safe_tool` would report `unknown` -- "the server does not know whether it landed" -- for a
    call the server knows perfectly well it refused, and refused for a reason the model can fix.
    """
    parts = ["Nothing was logged. The ratings list must cover all 19 muscle groups exactly once."]
    if missing:
        parts.append(f"Missing: {', '.join(missing)}.")
    if duplicated:
        parts.append(f"Duplicated: {', '.join(duplicated)}.")
    return " ".join(parts)


def _degraded_log() -> PhysiqueLogResponse:
    """`safe_tool`'s exception payload. `UNKNOWN`, never `REFUSED` (PITFALLS #15).

    An exception here means the server does not know whether the append landed -- which is a
    different fact from knowing it did not. `REFUSED` would invite an immediate retry, and unlike
    `program_switch.py` there is no single-use token to make that retry safe: a retry after a
    successful-but-unreported append is a SECOND observation on the same day. So the reason text
    instructs the model to read the current observation back instead.
    """
    return PhysiqueLogResponse(
        data_available=False,
        log_status=PhysiqueLogStatus.UNKNOWN,
        reason=(
            "Could not confirm whether the observation was logged. Call "
            "fitness_get_latest_physique_observation to read the current observation before doing "
            "anything else -- do not retry this call."
        ),
        observation_id=None,
        observed_on=None,
        superseded_observation_id=None,
        disclaimer=PHYSIQUE_RATING_DISCLAIMER,
    )


def _degraded_latest() -> LatestPhysiqueObservationResponse:
    """`safe_tool`'s exception payload for the read side.

    A factory, not a value, so each failure gets a fresh object -- `safe_tool`'s contract, the same
    argument `programs.py::_degraded_program` makes.
    """
    return LatestPhysiqueObservationResponse(
        data_available=False,
        observation=None,
        rating_scale=PHYSIQUE_RATING_ANCHORS,
        disclaimer=PHYSIQUE_RATING_DISCLAIMER,
    )


@safe_tool(degraded=_degraded_log)
async def fitness_log_physique_observation(
    ctx: Context[AppContext],
    ratings: Annotated[
        list[PhysiqueRatingInput],
        Field(
            description=(
                "One entry for EACH of the 19 canonical muscle groups -- all 19, every time. Set "
                "`rating_level` to one of Minimal / Emerging / Developed / Well-Developed / "
                "Standout, OR set `not_assessable_reason` instead when the photos do not show the "
                "group (abductors and adductors usually do not). Never both, never neither."
            )
        ),
    ],
    pose_state: Annotated[
        PoseState,
        Field(
            description=(
                "'relaxed' or 'lightly_flexed'. Record what the photos actually show -- a pose "
                "change between observations moves ratings on its own."
            )
        ),
    ],
    photo_angles_present: Annotated[
        list[PhotoAngle],
        Field(
            description=(
                "Which angles this photo set contained: 'front', 'back', 'side'. A back rating "
                "from a front-only set is not comparable to one from a full set."
            )
        ),
    ],
    leanness_notes: Annotated[
        str | None,
        Field(
            default=None,
            max_length=500,
            description="Optional free-text note on visible leanness/conditioning cues.",
        ),
    ] = None,
    conditioning_notes: Annotated[
        str | None,
        Field(
            default=None,
            max_length=500,
            description="Optional free-text note on muscle conditioning/definition.",
        ),
    ] = None,
    symmetry_notes: Annotated[
        str | None,
        Field(
            default=None,
            max_length=500,
            description="Optional free-text note on left/right or upper/lower symmetry.",
        ),
    ] = None,
    conditions_note: Annotated[
        str | None,
        Field(
            default=None,
            max_length=200,
            description=(
                "Optional note on conditions that could affect the ratings: lighting, pump, "
                "hydration, time since training, and similar."
            ),
        ),
    ] = None,
    supersedes_observation_id: Annotated[
        uuid.UUID | None,
        Field(
            default=None,
            description=(
                "Set this to correct a duplicate observation or one recorded without a photo "
                "actually present. The earlier observation is RETAINED, never deleted -- it is "
                "marked superseded. Requires `superseded_reason` together with it."
            ),
        ),
    ] = None,
    superseded_reason: Annotated[
        str | None,
        Field(
            default=None,
            max_length=200,
            description=(
                "Required together with `supersedes_observation_id`: a short reason the earlier "
                "observation is being superseded."
            ),
        ),
    ] = None,
) -> PhysiqueLogResponse:
    """Append one physique observation: 19 muscle-group ratings plus notes and photo conditions.

    Call `fitness_get_latest_physique_observation` FIRST -- it returns the prior observation and
    the rating scale, and a rating made without it is an absolute judgement where a relative one
    was asked for.

    Derive each muscle-group rating primarily from the photo in front of you. The prior observation
    returned by fitness_get_latest_physique_observation is a sanity check on your reading, not a
    target to move toward or away from. If your reading disagrees with it, record your reading.

    One call appends one observation. There is no confirmation token and nothing is overwritten.

    There is deliberately no `observed_on` parameter: the date is always the user's local today,
    server-derived, never a caller-supplied or backdated date -- `program_switch.py`'s D-09
    reasoning applies here too, and the photos being rated are attached in the conversation
    happening now.
    """
    user_id = resolve_user_id(ctx)
    async with writable_session(ctx) as session:
        # Paired-argument check first: the cheapest refusal, and it needs no query.
        if (supersedes_observation_id is None) != (superseded_reason is None):
            return PhysiqueLogResponse(
                data_available=True,
                log_status=PhysiqueLogStatus.REFUSED,
                reason=_REFUSAL_SUPERSEDE_PAIR,
                observation_id=None,
                observed_on=None,
                superseded_observation_id=None,
                disclaimer=PHYSIQUE_RATING_DISCLAIMER,
            )

        # D-07's discretion note: validate through the EXISTING tenant-scoped lookup, never a new
        # query path. Any prior observation of this user's is a legal target -- the `user_id`
        # predicate inside `get_observation` is the control, not "must be the latest".
        if supersedes_observation_id is not None:
            target = await get_observation(
                session, observation_id=supersedes_observation_id, user_id=user_id
            )
            if target is None or target.superseded_at is not None:
                return PhysiqueLogResponse(
                    data_available=True,
                    log_status=PhysiqueLogStatus.REFUSED,
                    reason=_REFUSAL_SUPERSEDE_TARGET,
                    observation_id=None,
                    observed_on=None,
                    superseded_observation_id=None,
                    disclaimer=PHYSIQUE_RATING_DISCLAIMER,
                )

        # D-07's 19-row invariant, checked HERE rather than left to `create_observation`'s
        # ValueError: an escaping ValueError degrades to `unknown`, and "I don't know if it
        # landed" is a strictly worse answer than "your ratings list was short by two groups".
        supplied = [entry.muscle_group for entry in ratings]
        duplicated = sorted({group.value for group in supplied if supplied.count(group) > 1})
        missing = sorted(
            group.value for group in CanonicalMuscleGroup if group not in set(supplied)
        )
        if missing or duplicated:
            return PhysiqueLogResponse(
                data_available=True,
                log_status=PhysiqueLogStatus.REFUSED,
                reason=_coverage_refusal(missing=missing, duplicated=duplicated),
                observation_id=None,
                observed_on=None,
                superseded_observation_id=None,
                disclaimer=PHYSIQUE_RATING_DISCLAIMER,
            )

        today = await local_today(session, user_id=user_id)
        record = await create_observation(
            session,
            user_id=user_id,
            observed_on=today,
            ratings=[
                RatingEntry(
                    muscle_group=entry.muscle_group,
                    rating_level=entry.rating_level,
                    not_assessable_reason=entry.not_assessable_reason,
                )
                for entry in ratings
            ],
            pose_state=pose_state,
            photo_angles_present=[angle.value for angle in photo_angles_present],
            leanness_notes=leanness_notes,
            conditioning_notes=conditioning_notes,
            symmetry_notes=symmetry_notes,
            conditions_note=conditions_note,
            supersedes_observation_id=supersedes_observation_id,
            superseded_reason=superseded_reason,
        )
        response = PhysiqueLogResponse(
            data_available=True,
            log_status=PhysiqueLogStatus.LOGGED,
            reason=None,
            observation_id=record.id,
            observed_on=record.observed_on,
            superseded_observation_id=supersedes_observation_id,
            disclaimer=PHYSIQUE_RATING_DISCLAIMER,
        )
        # The LAST statement in the success branch (PITFALLS #15): nothing may run after it,
        # because an exception past a successful commit degrades to `unknown` on an append that
        # actually landed -- and there is no token here to make the retry safe.
        await session.commit()
        return response


@safe_tool(degraded=_degraded_latest)
async def fitness_get_latest_physique_observation(
    ctx: Context[AppContext],
) -> LatestPhysiqueObservationResponse:
    """The most recent physique observation: its 19 ratings, notes and photo conditions.

    Takes no arguments, for the same reason the body-weight and program tools do not: "what is the
    current picture" is always a question about now.

    CALL THIS BEFORE fitness_log_physique_observation, every time. It is the required precursor
    (PHYS-07): it returns the prior ratings so the new ones are relative to this same person's own
    history, and the rating scale so they are made against the five levels as written. Honest
    labelling -- nothing in MCP can force call ordering; this is steering, not a gate.

    Superseded observations are excluded. A retracted observation is not the current picture.
    """
    user_id = resolve_user_id(ctx)
    async with read_only_session(ctx) as session:
        record = await get_latest_observation(session, user_id=user_id)
        # Built INSIDE the session block, not after it: `read_only_session`'s unconditional
        # `rollback()` on exit expires everything the session loaded. `PhysiqueObservationRecord`
        # is a frozen dataclass the repository assembled, but it was assembled FROM ORM instances
        # inside this transaction, so the mapping to Pydantic belongs here -- exactly as
        # `programs.py` lines 51-56 document for the same reason.
        response = LatestPhysiqueObservationResponse(
            data_available=True,
            observation=(
                PhysiqueObservationView(
                    observation_id=record.id,
                    observed_on=record.observed_on,
                    leanness_notes=record.leanness_notes,
                    conditioning_notes=record.conditioning_notes,
                    symmetry_notes=record.symmetry_notes,
                    photo_angles_present=list(record.photo_angles_present),
                    pose_state=record.pose_state,
                    conditions_note=record.conditions_note,
                    ratings=[
                        PhysiqueRatingView(
                            muscle_group=entry.muscle_group,
                            rating_level=entry.rating_level,
                            not_assessable_reason=entry.not_assessable_reason,
                        )
                        for entry in record.ratings
                    ],
                )
                if record is not None
                else None
            ),
            rating_scale=PHYSIQUE_RATING_ANCHORS,
            disclaimer=PHYSIQUE_RATING_DISCLAIMER,
        )
    return response
