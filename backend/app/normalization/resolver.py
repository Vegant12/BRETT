"""Effective muscle mapping: curated base overridden by manual corrections (NORM-02, NORM-03).

**The resolution rule, and it is not the obvious one.** If ANY override row exists for a
template, the override set REPLACES the base set entirely. If none exists, the base applies.

A per-row merge -- the intuitive design -- would let a user add a muscle or change a role but
never REMOVE one, so the most common correction there is ("this exercise does not actually
work rear delts") would be unexpressible. Replacement also makes NORM-02's audit trivial: both
sets survive intact in their own tables and are diffable side by side, which is exactly what
"auditable against the original source mapping" asks for.

Provider-neutral by construction: this module imports nothing from ``app.integrations``. A
second provider writes the same tables and gets the same resolution for free.

NORM-03: the direct/indirect WEIGHT is applied here, at query time, by ``apply_weights`` --
never stored. Phase 4 passes its own mapping to answer "what if indirect counted 0.3?" without
a migration.
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.exercise import ExerciseMuscle, ExerciseMuscleOverride, ExerciseTemplate
from app.normalization.muscles import (
    CanonicalMuscleGroup,
    MappingSource,
    MuscleRole,
    role_weight,
)


@dataclass(frozen=True, slots=True)
class EffectiveMuscle:
    """One resolved (muscle, role) pair with the provenance the caller should believe.

    `source` is the RESOLVED provenance, not the stored one: every row that came from an
    override reports `MappingSource.OVERRIDE` regardless of what the base said, because
    that is the answer to "why does Phase 4 think this exercise trains rear delts".
    """

    muscle_group: CanonicalMuscleGroup
    role: MuscleRole
    source: MappingSource


# DIRECT before INDIRECT. Spelled out rather than relying on the enum values sorting
# alphabetically ("direct" < "indirect" only by luck), so renaming a role cannot silently
# reorder every Phase 4 result.
_ROLE_ORDER: Mapping[MuscleRole, int] = {MuscleRole.DIRECT: 0, MuscleRole.INDIRECT: 1}


def _sort_key(muscle: EffectiveMuscle) -> tuple[int, str]:
    return _ROLE_ORDER[muscle.role], muscle.muscle_group.value


def _muscle_group(value: str) -> CanonicalMuscleGroup:
    """Convert a stored string, or fail loudly.

    T-03-31: a value outside the taxonomy means a taxonomy change landed without a data
    migration. Dropping the row instead would shrink every per-muscle volume figure with no
    error anywhere in the stack -- a data-integrity failure that reads as a training slump.
    The message names the column and the value and NOT the user, because it will be logged.
    """
    try:
        return CanonicalMuscleGroup(value)
    except ValueError:
        raise ValueError(
            f"exercise_muscles.muscle_group holds a value outside the canonical "
            f"taxonomy: {value!r}"
        ) from None


def _muscle_role(value: str) -> MuscleRole:
    try:
        return MuscleRole(value)
    except ValueError:
        raise ValueError(
            f"exercise_muscles.role holds a value outside the role vocabulary: {value!r}"
        ) from None


def _mapping_source(value: str) -> MappingSource:
    try:
        return MappingSource(value)
    except ValueError:
        raise ValueError(
            f"exercise_muscles.source holds a value outside the provenance "
            f"vocabulary: {value!r}"
        ) from None


async def effective_muscles(
    session: AsyncSession, *, user_id: uuid.UUID, template_external_id: str
) -> list[EffectiveMuscle]:
    """The mapping Phase 4 should use for one template.

    Delegates to `effective_muscles_bulk` so the replacement rule has exactly one
    implementation; a second copy here is how the two would eventually disagree.
    """
    resolved = await effective_muscles_bulk(
        session, user_id=user_id, template_external_ids=[template_external_id]
    )
    return resolved.get(template_external_id, [])


async def effective_muscles_bulk(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    template_external_ids: Sequence[str],
) -> dict[str, list[EffectiveMuscle]]:
    """Two queries total, not two per template.

    Phase 4 resolves every template in a training week at once; a per-template round trip
    would turn one volume query into hundreds.
    """
    requested = list(dict.fromkeys(template_external_ids))
    if not requested:
        return {}

    override_rows = (
        await session.execute(
            select(
                ExerciseMuscleOverride.exercise_template_external_id,
                ExerciseMuscleOverride.muscle_group,
                ExerciseMuscleOverride.role,
            ).where(
                ExerciseMuscleOverride.user_id == user_id,
                ExerciseMuscleOverride.exercise_template_external_id.in_(requested),
            )
        )
    ).all()

    base_rows = (
        await session.execute(
            select(
                ExerciseMuscle.exercise_template_external_id,
                ExerciseMuscle.muscle_group,
                ExerciseMuscle.role,
                ExerciseMuscle.source,
            ).where(
                ExerciseMuscle.user_id == user_id,
                ExerciseMuscle.exercise_template_external_id.in_(requested),
            )
        )
    ).all()

    overrides: dict[str, list[EffectiveMuscle]] = {}
    for template_id, muscle_group, role in override_rows:
        overrides.setdefault(template_id, []).append(
            EffectiveMuscle(
                muscle_group=_muscle_group(muscle_group),
                role=_muscle_role(role),
                # Always OVERRIDE, never the stored base source: this row is effective
                # BECAUSE a human said so, and that is what the audit needs to show.
                source=MappingSource.OVERRIDE,
            )
        )

    base: dict[str, list[EffectiveMuscle]] = {}
    for template_id, muscle_group, role, source in base_rows:
        base.setdefault(template_id, []).append(
            EffectiveMuscle(
                muscle_group=_muscle_group(muscle_group),
                role=_muscle_role(role),
                source=_mapping_source(source),
            )
        )

    resolved: dict[str, list[EffectiveMuscle]] = {}
    for template_id in requested:
        # The replacement rule, in one line: presence of ANY override wins outright.
        chosen = overrides.get(template_id) or base.get(template_id) or []
        resolved[template_id] = sorted(chosen, key=_sort_key)
    return resolved


async def unmapped_template_ids(session: AsyncSession, *, user_id: uuid.UUID) -> list[str]:
    """Templates with NO effective mapping at all (D-03).

    Deliberately computed by absence rather than tracked in a `mapping_status` column: a
    status column has to be kept in sync with reality and will eventually drift from it,
    whereas "no rows in either table" cannot be wrong.
    """
    has_base = (
        select(ExerciseMuscle.id)
        .where(
            ExerciseMuscle.user_id == user_id,
            ExerciseMuscle.exercise_template_external_id == ExerciseTemplate.external_id,
        )
        .exists()
    )
    has_override = (
        select(ExerciseMuscleOverride.id)
        .where(
            ExerciseMuscleOverride.user_id == user_id,
            ExerciseMuscleOverride.exercise_template_external_id == ExerciseTemplate.external_id,
        )
        .exists()
    )
    rows = await session.scalars(
        select(ExerciseTemplate.external_id)
        .where(ExerciseTemplate.user_id == user_id, ~has_base, ~has_override)
        # Sorted so a curation report is stable between runs and diffable.
        .order_by(ExerciseTemplate.external_id)
    )
    return list(rows)


async def set_override(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    template_external_id: str,
    assignments: Sequence[tuple[CanonicalMuscleGroup, MuscleRole]],
    note: str | None = None,
) -> int:
    """Replace this template's override set. Does NOT touch `exercise_muscles`.

    Deletes any existing override rows for the template first, so the override is always a
    complete statement of the intended mapping rather than an accumulation of past edits.
    """
    await session.execute(
        delete(ExerciseMuscleOverride).where(
            ExerciseMuscleOverride.user_id == user_id,
            ExerciseMuscleOverride.exercise_template_external_id == template_external_id,
        )
    )
    if not assignments:
        # An EMPTY override is not the same as no override, but it cannot be represented:
        # with zero rows the base becomes effective again. `clear_override` is the honest
        # spelling of that intent, so this path simply writes nothing.
        return 0
    await session.execute(
        insert(ExerciseMuscleOverride),
        [
            {
                "id": uuid.uuid4(),
                "user_id": user_id,
                "exercise_template_external_id": template_external_id,
                "muscle_group": muscle_group.value,
                "role": role.value,
                "note": note,
            }
            for muscle_group, role in assignments
        ],
    )
    return len(assignments)


async def clear_override(
    session: AsyncSession, *, user_id: uuid.UUID, template_external_id: str
) -> int:
    """Remove the override; the base mapping becomes effective again. Returns rows deleted.

    Counted via `RETURNING` rather than `Result.rowcount`: the async `execute()` is typed as
    a plain `Result`, which has no `rowcount`, and Postgres gives the exact count for free.
    """
    removed = await session.scalars(
        delete(ExerciseMuscleOverride)
        .where(
            ExerciseMuscleOverride.user_id == user_id,
            ExerciseMuscleOverride.exercise_template_external_id == template_external_id,
        )
        .returning(ExerciseMuscleOverride.id)
    )
    return len(removed.all())


def apply_weights(
    muscles: Sequence[EffectiveMuscle],
    weights: Mapping[MuscleRole, Decimal] | None = None,
) -> dict[CanonicalMuscleGroup, Decimal]:
    """NORM-03: turn roles into weights at QUERY time.

    Defaults to 1.0 direct / 0.5 indirect. Pure and synchronous on purpose -- Phase 4 calls
    it inside aggregation loops and it must not touch a session.

    `Decimal`, never `float`: these multiply into tonnage sums, and binary floating point
    would make two arithmetically identical weekly totals compare unequal.
    """
    return {muscle.muscle_group: role_weight(muscle.role, weights) for muscle in muscles}
