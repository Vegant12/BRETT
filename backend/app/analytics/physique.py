"""Physique diff and volume cross-reference (PHYS-09, PHYS-10, PHYS-11). Composition only.

No SQL of its own. The diff's inputs come from `db.repositories.physique.get_recent_observations`
and the volume side from `analytics.volume.get_muscle_group_volume`; this module joins them and
adds nothing else.

**No model call, no image, no arithmetic beyond ordinal comparison** (PHYS-09). The diff compares
two `PhysiqueRatingLevel` DECLARATION-ORDER indices and compares their difference against an
integer. There is no average, no score and no weighting -- a five-point ordinal scale has no
arithmetic mean, and computing one would invent a precision the rater does not have.

**A one-level move is UNCHANGED, deliberately** (`PHYSIQUE_DIFF_MIN_LEVEL_DELTA = 2`). The Phase 15
spike measured the rater's own noise floor: across 5 blind draws on an UNCHANGED photo set, the
largest level-range any muscle group showed was exactly 1. A diff of 1 is therefore
indistinguishable from the instrument, not from the body. The raw `level_delta` still travels on
every row so "unchanged" is never mistaken for "identical".
Planner confirmation (17-01/17-02, required by 15-SPIKE-RESULT.md's own AUTHORITY NOTE): this
magnitude gate IS adopted, because the alternative -- classifying the measured noise floor itself
as a real change -- makes the verdict worse than no verdict. It stays a comparison of an ordinal
index difference against an integer, so PHYS-09's "no arithmetic beyond ordinal comparison" rule
is intact.

**RECOMP_LOOKBACK_WEEKS is reused, not reinvented** (D-02). The 12-week window the cross-reference
reads is `app.analytics.recomposition.RECOMP_LOOKBACK_WEEKS` -- imported, never a second literal
`12` -- so "am I recomping" and "which muscles are undertrained" describe the same block of
training.

**Underdeveloped and undertrained are BOTH self-relative** (D-01, D-02). Underdeveloped is
`rating_level in {Minimal, Emerging}`, the bottom two of the five locked levels. Undertrained is
the bottom quartile of THIS user's own 19 groups by `weighted_sets` -- never an absolute
sets-per-week floor, because PHYS-01 already forbids rating a muscle against anyone but this same
person and an external volume minimum would reintroduce exactly the population comparison the
rating side structurally excludes.

**`Not Assessable` is excluded from the underdeveloped side only** (D-03). A group with no rating
cannot be called underdeveloped. It still participates in the bottom-quartile computation, which
is pure `weighted_sets` and has nothing to do with the rating.

**PHYSIQUE_MIN_ELAPSED_DAYS is surfaced, never enforced.** PHYS-F01 is deferred; this module
reports the constant beside the real elapsed interval and refuses nothing.

No MCP tool wraps either function this phase (17-CONTEXT.md D-08). Phase 18's `compose_report` is
the named consumer.
"""

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.recomposition import RECOMP_LOOKBACK_WEEKS
from app.analytics.schemas import (
    PhysiqueDiffResult,
    PhysiqueDiffVerdict,
    PhysiqueMuscleDiff,
    PhysiqueVolumeCrossReference,
    PhysiqueVolumeFlag,
)
from app.analytics.volume import get_muscle_group_volume
from app.db.models.physique import (
    PHYSIQUE_DIFF_MIN_LEVEL_DELTA,
    PHYSIQUE_MIN_ELAPSED_DAYS,
    PHYSIQUE_RATING_DISCLAIMER,
    PhysiqueRatingLevel,
)
from app.db.repositories.physique import (
    PhysiqueObservationRecord,
    get_latest_observation,
    get_recent_observations,
)
from app.normalization.muscles import CanonicalMuscleGroup

# Declaration order IS ordinal order (`PhysiqueRatingLevel`'s own docstring). Built once from the
# enum rather than written out, so a level added by a future migration cannot desynchronise from
# the ordinals this module compares.
_LEVEL_ORDINALS: dict[PhysiqueRatingLevel, int] = {
    level: index for index, level in enumerate(PhysiqueRatingLevel)
}

# D-01. The bottom two of the five locked levels, named rather than sliced, so the set reads as a
# decision instead of an index expression.
UNDERDEVELOPED_LEVELS: frozenset[PhysiqueRatingLevel] = frozenset(
    {PhysiqueRatingLevel.MINIMAL, PhysiqueRatingLevel.EMERGING}
)

# D-02's bottom quartile, by RANK rather than by a 25th-percentile interpolation. 19 groups / 4 is
# 4.75, so the quartile is the 5 lowest-volume groups. Rank avoids interpolating between two
# `Decimal` totals -- a percentile cut would need a fractional index and would make the threshold a
# number that appears in no group's actual volume, which is harder to audit than "these five".
# Ties are INCLUSIVE: every group whose total is <= the 5th-lowest total is inside the quartile, so
# six groups tied at zero all count rather than five of them counting by sort order.
_UNDERTRAINED_BOTTOM_RANKS = 5


def get_physique_diff(
    *, earlier: PhysiqueObservationRecord, later: PhysiqueObservationRecord
) -> PhysiqueDiffResult:
    """PHYS-09: one verdict per muscle group, from stored rows only.

    Keyword-only on both sides on purpose: `get_physique_diff(a, b)` has no readable argument
    order, and a swapped pair silently inverts every `improved` into a `regressed`.

    Both records carry all 19 ratings (D-07's invariant, enforced by `create_observation`), so this
    function never has to decide what a missing group means.
    """
    earlier_by_group = {entry.muscle_group: entry for entry in earlier.ratings}
    later_by_group = {entry.muscle_group: entry for entry in later.ratings}

    muscle_groups: list[PhysiqueMuscleDiff] = []
    for group in sorted(CanonicalMuscleGroup, key=lambda g: g.value):
        earlier_level = earlier_by_group[group].rating_level
        later_level = later_by_group[group].rating_level

        if earlier_level is None or later_level is None:
            muscle_groups.append(
                PhysiqueMuscleDiff(
                    muscle_group=group,
                    earlier_level=earlier_level,
                    later_level=later_level,
                    level_delta=None,
                    verdict=PhysiqueDiffVerdict.NOT_COMPARABLE,
                )
            )
            continue

        delta = _LEVEL_ORDINALS[later_level] - _LEVEL_ORDINALS[earlier_level]
        if delta >= PHYSIQUE_DIFF_MIN_LEVEL_DELTA:
            verdict = PhysiqueDiffVerdict.IMPROVED
        elif delta <= -PHYSIQUE_DIFF_MIN_LEVEL_DELTA:
            verdict = PhysiqueDiffVerdict.REGRESSED
        else:
            verdict = PhysiqueDiffVerdict.UNCHANGED

        muscle_groups.append(
            PhysiqueMuscleDiff(
                muscle_group=group,
                earlier_level=earlier_level,
                later_level=later_level,
                level_delta=delta,
                verdict=verdict,
            )
        )

    return PhysiqueDiffResult(
        earlier_observed_on=earlier.observed_on,
        later_observed_on=later.observed_on,
        elapsed_days=(later.observed_on - earlier.observed_on).days,
        min_elapsed_days=PHYSIQUE_MIN_ELAPSED_DAYS,
        min_level_delta=PHYSIQUE_DIFF_MIN_LEVEL_DELTA,
        muscle_groups=muscle_groups,
        disclaimer=PHYSIQUE_RATING_DISCLAIMER,
    )


async def get_latest_physique_diff(
    session: AsyncSession, *, user_id: uuid.UUID
) -> PhysiqueDiffResult | None:
    """The two most recent NON-superseded observations, diffed. `None` when fewer than two exist.

    PHYS-08's "a superseded observation is excluded from diffs" is satisfied HERE by construction:
    `get_recent_observations` holds the only `superseded_at IS NULL` predicate in the repo, and this
    is the only fetch path a diff has. A caller that hands `get_physique_diff` two records it
    obtained some other way is outside this guarantee, which is why that function is documented as
    taking already-fetched records and this one is the entry point Phase 18 calls.
    """
    records = await get_recent_observations(session, user_id=user_id, limit=2)
    if len(records) < 2:
        return None
    # `get_recent_observations` is newest-first, so [1] is the earlier observation.
    return get_physique_diff(earlier=records[1], later=records[0])


async def get_physique_volume_cross_reference(
    session: AsyncSession, *, user_id: uuid.UUID
) -> PhysiqueVolumeCrossReference | None:
    """PHYS-10: the muscle groups that are BOTH underdeveloped and undertrained.

    `None` means the user has no non-superseded observation to cross-reference -- a different fact
    from an empty `flagged` list, which means the join found no overlap.

    The volume window is anchored on the OBSERVATION's `observed_on`, not on today: the question is
    "was the training behind this photo thin", and anchoring on the clock would make the same
    observation produce different answers on different days. It also makes this function testable
    without freezing time.
    """
    observation = await get_latest_observation(session, user_id=user_id)
    if observation is None:
        return None

    end_day = observation.observed_on
    # Same expression `recomposition.py` uses to derive its own lookback window.
    start_day = end_day - dt.timedelta(days=7 * RECOMP_LOOKBACK_WEEKS - 1)

    # Called ONCE and reused for every group's total below -- never re-queried.
    volume = await get_muscle_group_volume(
        session, user_id=user_id, start_day=start_day, end_day=end_day
    )

    totals: dict[CanonicalMuscleGroup, Decimal] = {
        group: Decimal("0") for group in CanonicalMuscleGroup
    }
    for week in volume.weeks:
        for entry in week.muscle_groups:
            totals[entry.muscle_group] += entry.weighted_sets

    ranked = sorted(totals.values())
    threshold = ranked[_UNDERTRAINED_BOTTOM_RANKS - 1]
    undertrained = {group for group, total in totals.items() if total <= threshold}

    flagged = [
        PhysiqueVolumeFlag(
            muscle_group=entry.muscle_group,
            rating_level=entry.rating_level,
            weighted_sets=totals[entry.muscle_group],
        )
        for entry in sorted(observation.ratings, key=lambda item: item.muscle_group.value)
        if entry.rating_level is not None
        and entry.rating_level in UNDERDEVELOPED_LEVELS
        and entry.muscle_group in undertrained
    ]

    return PhysiqueVolumeCrossReference(
        observed_on=observation.observed_on,
        lookback_weeks=RECOMP_LOOKBACK_WEEKS,
        # The SNAPPED spine start (`get_muscle_group_volume` widens outward to whole local
        # weeks), not the requested `start_day` -- this is what actually got summed.
        window_start=volume.weeks[0].week_start if volume.weeks else start_day,
        window_end=end_day,
        undertrained_threshold_weighted_sets=threshold,
        flagged=flagged,
        disclaimer=PHYSIQUE_RATING_DISCLAIMER,
    )
