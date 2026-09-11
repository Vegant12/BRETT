"""Read and write physique observations (PHYS-01..PHYS-05).

This module is the ONE writer of `physique_observations` and `physique_ratings`. Every
function takes an `AsyncSession` positionally and never commits — the CALLER owns the
transaction, the same contract `programs.py` states, so Phase 17's MCP tool can make the
commit the last statement it executes.

D-07: an observation is ALWAYS all 19 `CanonicalMuscleGroup` rows, never a subset. Each row is
either a rating level or `Not Assessable` with a reason. That makes "missing entirely" a
non-state, so Phase 17's diff never has to distinguish three cases where two will do, and it
is why the two hip-stabilizer groups a standard photo set never shows need no special-casing
(PHYS-02): they take the identical path every other group takes and simply end up
`Not Assessable` in ordinary use.

ASVS V4: every function takes `user_id` explicitly and puts it in the predicate. There is one
user today; the query that forgets the predicate is the one that would still be there when
there are two.

No ORM relationship mapping and no eager-loading helper are used anywhere in this module:
`test_db_models.test_reference_models_declare_no_relationships`
bans lazy-loadable relationships repo-wide because async lazy-load raises `MissingGreenlet`.
`get_latest_observation` therefore issues two explicit queries and assembles a frozen
dataclass, the same shape `repositories/workouts.py` returns.

PHYS-08 (Phase 17) is implemented here: `_mark_superseded` is the ONLY place the three supersede
columns are written, `create_observation` is its only caller, and `get_recent_observations` holds
the only `superseded_at IS NULL` predicate in the repo. Nothing is ever hard-deleted -- the
superseded row stays in the table and simply stops being returned by the read path.
"""

import datetime as dt
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utc_now
from app.db.models.physique import (
    PhysiqueObservation,
    PhysiqueRating,
    PhysiqueRatingLevel,
    PoseState,
)
from app.normalization.muscles import CanonicalMuscleGroup

# D-05. A `not_assessable_reason` past this length is refused here rather than left for
# asyncpg to truncate mid-transaction, aborting the session on a write that started clean.
_NOT_ASSESSABLE_REASON_MAX_LENGTH = 160

# The `superseded_reason` column is String(200). Refused here rather than left for asyncpg to
# truncate mid-transaction, aborting a session that started clean -- the same argument
# `_NOT_ASSESSABLE_REASON_MAX_LENGTH` makes.
_SUPERSEDED_REASON_MAX_LENGTH = 200


@dataclass(frozen=True, slots=True)
class RatingEntry:
    """One muscle group's verdict. Exactly one of the two optional fields is set.

    Used for BOTH the write input and the read output: an entry that round-trips unchanged is
    easier to reason about than an input type and a near-identical output type that can drift.
    """

    muscle_group: CanonicalMuscleGroup
    rating_level: PhysiqueRatingLevel | None = None
    not_assessable_reason: str | None = None


@dataclass(frozen=True, slots=True)
class PhysiqueObservationRecord:
    """One whole observation: the header's own facts plus all 19 ratings.

    `ratings` is always length 19, ordered by `CanonicalMuscleGroup` declaration order, so a
    caller can zip it against the enum without sorting.
    """

    id: uuid.UUID
    observed_on: dt.date
    leanness_notes: str | None
    conditioning_notes: str | None
    symmetry_notes: str | None
    photo_angles_present: tuple[str, ...]
    pose_state: PoseState
    conditions_note: str | None
    superseded_at: dt.datetime | None
    superseded_reason: str | None
    superseded_by_id: uuid.UUID | None
    created_at: dt.datetime
    ratings: tuple[RatingEntry, ...]


def _validate_rating_coverage(ratings: Sequence[RatingEntry]) -> None:
    """D-07: exactly one entry per CanonicalMuscleGroup, each a level XOR a reason.

    Raises `ValueError` naming the offending groups. The database's own constraints
    (`uq_physique_ratings_observation_id_muscle_group`,
    `ck_physique_ratings_rating_xor_not_assessable`) are the backstop for any writer that
    bypasses this module -- not the first line of defence for this one, which would leave a
    half-written observation to clean up.
    """
    seen: set[CanonicalMuscleGroup] = set()
    duplicates: set[CanonicalMuscleGroup] = set()
    for entry in ratings:
        if entry.muscle_group in seen:
            duplicates.add(entry.muscle_group)
        seen.add(entry.muscle_group)
    if duplicates:
        raise ValueError(
            "physique observation has duplicate rating rows for: "
            f"{sorted(group.value for group in duplicates)}"
        )

    missing = set(CanonicalMuscleGroup) - seen
    if missing:
        raise ValueError(
            "physique observation is missing rating rows for: "
            f"{sorted(group.value for group in missing)}"
        )

    for entry in ratings:
        has_level = entry.rating_level is not None
        has_reason = entry.not_assessable_reason is not None
        if has_level == has_reason:
            raise ValueError(
                f"physique rating for {entry.muscle_group.value} must set exactly one of "
                "rating_level or not_assessable_reason"
            )
        if (
            entry.not_assessable_reason is not None
            and len(entry.not_assessable_reason) > _NOT_ASSESSABLE_REASON_MAX_LENGTH
        ):
            raise ValueError(
                f"physique rating for {entry.muscle_group.value} has a not_assessable_reason "
                f"longer than {_NOT_ASSESSABLE_REASON_MAX_LENGTH} characters"
            )


async def _mark_superseded(
    session: AsyncSession,
    *,
    observation_id: uuid.UUID,
    user_id: uuid.UUID,
    superseded_by_id: uuid.UUID,
    reason: str,
) -> int:
    """Set the three supersede columns on ONE older observation. Returns the row count.

    PHYS-08's retention rule is structural, not a convention: this is an UPDATE and there is no
    DELETE statement anywhere in this module. The superseded row keeps every rating it ever had.

    Four predicates, each doing work:
    * `id ==` -- the target.
    * `user_id ==` -- ASVS V4. The id arrives from a model-supplied tool argument, so a missing
      tenant predicate here is an IDOR that would let one user's observation be marked superseded
      by another user's write.
    * `superseded_at IS NULL` -- supersede once. A second supersede would overwrite the first
      reason and re-point `superseded_by_id`, losing the original correction's provenance.

    A returned count of 0 means one of those three did not hold. The caller decides whether that
    is a refusal (the MCP tool pre-validates through `get_observation`, so it is a race) or a
    programming error.

    Counted via `RETURNING` rather than `Result.rowcount` -- the async `execute()` is typed as a
    plain `Result`, which has no `rowcount`, and Postgres gives the exact count for free (same
    argument `normalization/resolver.py::clear_override` makes).
    """
    updated = await session.scalars(
        update(PhysiqueObservation)
        .where(
            PhysiqueObservation.id == observation_id,
            PhysiqueObservation.user_id == user_id,
            PhysiqueObservation.superseded_at.is_(None),
        )
        .values(
            superseded_at=utc_now(),
            superseded_reason=reason,
            superseded_by_id=superseded_by_id,
        )
        .returning(PhysiqueObservation.id)
    )
    return len(updated.all())


async def create_observation(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    observed_on: dt.date,
    ratings: Sequence[RatingEntry],
    pose_state: PoseState,
    photo_angles_present: Sequence[str] = (),
    leanness_notes: str | None = None,
    conditioning_notes: str | None = None,
    symmetry_notes: str | None = None,
    conditions_note: str | None = None,
    supersedes_observation_id: uuid.UUID | None = None,
    superseded_reason: str | None = None,
) -> PhysiqueObservationRecord:
    """INSERT the header, then all 19 rating rows, in this session. The caller commits.

    `ratings` must cover every `CanonicalMuscleGroup` exactly once (D-07) — validated before
    any statement is issued.

    PHYS-08: when `supersedes_observation_id` is given, `superseded_reason` is REQUIRED and the
    older row is marked superseded inside this same transaction, AFTER the new row has been
    flushed -- `physique_observations.superseded_by_id` is a self-referential FK, so the new id
    must exist before another row can point at it. Both arguments together or neither; one alone
    raises.
    """
    if (supersedes_observation_id is None) != (superseded_reason is None):
        raise ValueError(
            "supersede requires both supersedes_observation_id and superseded_reason, or neither"
        )
    if superseded_reason is not None and len(superseded_reason) > _SUPERSEDED_REASON_MAX_LENGTH:
        raise ValueError(
            f"superseded_reason is longer than {_SUPERSEDED_REASON_MAX_LENGTH} characters"
        )

    _validate_rating_coverage(ratings)

    observation_id = uuid.uuid4()
    await session.execute(
        insert(PhysiqueObservation).values(
            id=observation_id,
            user_id=user_id,
            observed_on=observed_on,
            leanness_notes=leanness_notes,
            conditioning_notes=conditioning_notes,
            symmetry_notes=symmetry_notes,
            photo_angles_present=list(photo_angles_present),
            pose_state=pose_state.value,
            conditions_note=conditions_note,
        )
    )

    by_group = {entry.muscle_group: entry for entry in ratings}

    def _rating_payload(entry: RatingEntry) -> str | None:
        level = entry.rating_level
        return level.value if level is not None else None

    await session.execute(
        insert(PhysiqueRating),
        [
            {
                "id": uuid.uuid4(),
                "observation_id": observation_id,
                "muscle_group": group.value,
                "rating_level": _rating_payload(by_group[group]),
                "not_assessable_reason": by_group[group].not_assessable_reason,
            }
            for group in CanonicalMuscleGroup
        ],
    )

    await session.flush()

    if supersedes_observation_id is not None and superseded_reason is not None:
        # After the flush, never before: `superseded_by_id` is a self-referential FK and the new
        # row has to exist for the older one to point at it.
        marked = await _mark_superseded(
            session,
            observation_id=supersedes_observation_id,
            user_id=user_id,
            superseded_by_id=observation_id,
            reason=superseded_reason,
        )
        if marked != 1:
            # Wrong user, unknown id, or already superseded. The MCP write tool pre-validates all
            # three through `get_observation`, so reaching here means the row changed underneath
            # that check. Raising rolls the whole transaction back -- including the new
            # observation, which is correct: a correction that did not correct anything must not
            # land half-applied.
            raise ValueError(
                "supersedes_observation_id does not name an un-superseded observation "
                "belonging to this user"
            )

    record = await get_observation(session, observation_id=observation_id, user_id=user_id)
    if record is None:  # pragma: no cover - the inserts above just created this row
        raise RuntimeError("create_observation: newly inserted observation not found")
    return record


async def get_observation(
    session: AsyncSession, *, observation_id: uuid.UUID, user_id: uuid.UUID
) -> PhysiqueObservationRecord | None:
    """Assemble one observation plus its ratings from two explicit queries.

    The `user_id` predicate is belt-and-braces even when the id is already known (ASVS V4).

    Public because the MCP write tool validates a caller-supplied `supersedes_observation_id`
    through THIS lookup rather than adding a second query path (17-CONTEXT.md D-07). It
    deliberately does NOT filter `superseded_at` -- a caller asking for a specific id is
    entitled to see that the row is already superseded.
    """
    observation = (
        await session.execute(
            select(PhysiqueObservation).where(
                PhysiqueObservation.id == observation_id,
                PhysiqueObservation.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if observation is None:
        return None

    rating_rows = (
        (
            await session.execute(
                select(PhysiqueRating).where(PhysiqueRating.observation_id == observation_id)
            )
        )
        .scalars()
        .all()
    )

    by_group = {row.muscle_group: row for row in rating_rows}

    def _rating_level(stored: str | None) -> PhysiqueRatingLevel | None:
        return PhysiqueRatingLevel(stored) if stored is not None else None

    entries = tuple(
        RatingEntry(
            muscle_group=group,
            rating_level=_rating_level(by_group[group.value].rating_level),
            not_assessable_reason=by_group[group.value].not_assessable_reason,
        )
        for group in CanonicalMuscleGroup
        if group.value in by_group
    )

    return PhysiqueObservationRecord(
        id=observation.id,
        observed_on=observation.observed_on,
        leanness_notes=observation.leanness_notes,
        conditioning_notes=observation.conditioning_notes,
        symmetry_notes=observation.symmetry_notes,
        photo_angles_present=tuple(observation.photo_angles_present),
        pose_state=PoseState(observation.pose_state),
        conditions_note=observation.conditions_note,
        superseded_at=observation.superseded_at,
        superseded_reason=observation.superseded_reason,
        superseded_by_id=observation.superseded_by_id,
        created_at=observation.created_at,
        ratings=entries,
    )


async def get_recent_observations(
    session: AsyncSession, *, user_id: uuid.UUID, limit: int
) -> list[PhysiqueObservationRecord]:
    """The user's `limit` most recent NON-superseded observations, newest first.

    `superseded_at IS NULL` lives HERE and nowhere else (PHYS-08). `get_latest_observation` is a
    `limit=1` wrapper over this function and `app/analytics/physique.py`'s diff reads its two
    inputs from here, so "a superseded observation is excluded from diffs" is one predicate in one
    place rather than the same predicate written twice and drifting once.

    Ordered `observed_on DESC, created_at DESC`. The `created_at` tie-break is load-bearing: there
    is deliberately no unique constraint on `(user_id, observed_on)` (16-RESEARCH.md Open Question
    2), so two observations can share a calendar day and an unordered tie would make the answer
    depend on the planner.

    Two explicit queries per record, same as `get_observation`: no ORM relationship is mapped
    anywhere in this module because an async lazy-load raises `MissingGreenlet`.
    """
    observation_ids = (
        (
            await session.execute(
                select(PhysiqueObservation.id)
                .where(
                    PhysiqueObservation.user_id == user_id,
                    PhysiqueObservation.superseded_at.is_(None),
                )
                .order_by(
                    PhysiqueObservation.observed_on.desc(),
                    PhysiqueObservation.created_at.desc(),
                )
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    records: list[PhysiqueObservationRecord] = []
    for observation_id in observation_ids:
        record = await get_observation(session, observation_id=observation_id, user_id=user_id)
        if record is not None:
            records.append(record)
    return records


async def get_latest_observation(
    session: AsyncSession, *, user_id: uuid.UUID
) -> PhysiqueObservationRecord | None:
    """The user's most recent observation, or `None` if they have none.

    Superseded observations are EXCLUDED (PHYS-08). The predicate lives in
    `get_recent_observations`, which this function delegates to, so a user whose only observation
    has been superseded reads as `None` -- the same answer as a user with no observations, which is
    correct: a superseded observation is not the current picture.
    """
    records = await get_recent_observations(session, user_id=user_id, limit=1)
    return records[0] if records else None
