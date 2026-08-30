"""The rollup substrate under VOL-01/02/03: window guards, pure folds, and the SQL aggregate.

Three rules in ``app.analytics.rollup`` are counter-intuitive, and getting any of them wrong
produces a number that is wrong without being obviously wrong:

* **Hard sets are an EXCLUSION of ``warmup``, never an allow-list of ``normal``.** An allow-list
  silently discards every dropset -- 12% of all live hard sets -- and would start discarding
  ``failure`` sets the day the provider first sends one.
* **Tonnage is gated on OPERAND PRESENCE**, never on a modality vocabulary. Tonnage exists
  wherever both a weight and a rep count exist and nowhere else, so ``0 kg x 10 reps`` is a
  computed zero while a timed plank hold is "not computable" -- two different answers that a
  modality allow-list collapses into one.
* **Per-muscle sessions are a SET of workout ids, never a sum.** One workout containing three
  hamstring exercises is ONE hamstring session.

``test_fold_dedupes_sessions_within_one_workout`` is the load-bearing test here. The wrong
implementation -- incrementing a counter instead of adding to a set -- inflates 14 of 16 muscle
groups by up to 4x, and every inflated figure still looks entirely plausible next to the real
ones, so no reviewer catches it by reading the output. It is pinned in BOTH directions, because
the naive fix ("just report 1") is equally wrong and equally plausible.

The window-guard and fold tests below deliberately carry NO marker: they are business rules, not
database behaviour, and a business rule must stay verifiable when Docker is not running. Only the
four tests in the second half touch a container, and they are there because ``date_trunc``,
``AT TIME ZONE`` and ``FILTER (WHERE ...)`` have no meaning outside real PostgreSQL.
"""

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from app.analytics.rollup import (
    SetRollupRow,
    build_window,
    fold_weeks_by_muscle,
    fold_window_by_muscle,
    fold_window_by_template,
)
from app.normalization.muscles import CanonicalMuscleGroup, MappingSource, MuscleRole
from app.normalization.resolver import EffectiveMuscle

# `ROLLUP-*` so these cannot collide with `test_normalization_mapping.py`'s `RESOLVER-*` ids,
# `test_analytics_volume.py`'s `VOL-*`, or the sync tests' hevy ids: the Postgres container is
# session-scoped and shared across every integration test in the suite.
_BENCH = "ROLLUP-BENCH"
_ROW = "ROLLUP-ROW"
_CURL = "ROLLUP-CURL"

# Exactly Jakarta local midnight on Monday 2026-08-24. The bucket must be 2026-08-24, not the
# 2026-08-17 that naive-UTC bucketing produces.
_JAKARTA_MONDAY_MIDNIGHT = dt.datetime(2026, 8, 23, 17, 0, tzinfo=dt.UTC)
_WEEK_START = dt.date(2026, 8, 24)
_WEEK_END = dt.date(2026, 8, 30)

# NORM-03: deliberately not the defaults, so a test cannot pass against an implementation that
# ignored the weights argument entirely.
_CUSTOM_WEIGHTS = {MuscleRole.DIRECT: Decimal("0.8"), MuscleRole.INDIRECT: Decimal("0.3")}

_HAMSTRINGS = CanonicalMuscleGroup.HAMSTRINGS


def _ham_row(workout_id: uuid.UUID, template_external_id: str, hard_sets: int = 4) -> SetRollupRow:
    """A hand-built aggregate row. No database: the folds are pure by design."""
    return SetRollupRow(
        week_start=_WEEK_START,
        workout_id=workout_id,
        template_external_id=template_external_id,
        hard_sets=hard_sets,
        total_reps=hard_sets * 10,
        tonnage_sets=hard_sets,
        tonnage_kg=Decimal("100.000") * hard_sets * 10,
    )


def _direct(muscle: CanonicalMuscleGroup = _HAMSTRINGS) -> list[EffectiveMuscle]:
    return [EffectiveMuscle(muscle, MuscleRole.DIRECT, MappingSource.CURATED)]


def _indirect(muscle: CanonicalMuscleGroup = _HAMSTRINGS) -> list[EffectiveMuscle]:
    return [EffectiveMuscle(muscle, MuscleRole.INDIRECT, MappingSource.CURATED)]


# --------------------------------------------------------------------------
# The window guards (D-03 / U-01), pure and container-free
# --------------------------------------------------------------------------


def test_build_window_rejects_an_inverted_range() -> None:
    """An inverted window would return an empty result set instead of failing."""
    with pytest.raises(ValueError, match="end_day precedes start_day"):
        build_window(
            start_day=dt.date(2026, 8, 30),
            end_day=dt.date(2026, 8, 24),
            tz="Asia/Jakarta",
            snap_to_weeks=False,
        )


def test_build_window_rejects_an_absurd_span() -> None:
    """ASVS V5 / MCP-03: a Phase 6 tool must not be able to ask for two centuries of buckets.

    The rejection has to happen before any row is materialised. A row cap would have turned an
    over-wide request into a confidently-presented partial answer -- silently truncating the
    answer instead of refusing the question -- which is the exact failure mode T-04-07 exists to
    prevent. This test is what keeps the guard from later being removed as "unnecessary".
    """
    with pytest.raises(ValueError, match="exceeds the maximum span"):
        build_window(
            start_day=dt.date(1900, 1, 1),
            end_day=dt.date(2100, 1, 1),
            tz="Asia/Jakarta",
            snap_to_weeks=True,
        )


def test_build_window_rejects_an_unknown_timezone() -> None:
    """T-04-01: ``users.timezone`` carries no DB CHECK constraint.

    That string is about to reach the aggregate as a bound timezone parameter. Rejecting it at
    the boundary beats an unknown-zone failure raised from inside an aggregate query, where it
    arrives as a driver error with no indication that a configuration value caused it.
    """
    with pytest.raises(ValueError, match="unknown IANA timezone"):
        build_window(
            start_day=_WEEK_START,
            end_day=_WEEK_END,
            tz="Not/AZone",
            snap_to_weeks=False,
        )


def test_build_window_snaps_only_when_asked() -> None:
    """U-01 applies to WEEKLY VOLUME only; frequency keeps the raw range (D-03).

    Weekly volume snaps outward to whole Monday-start weeks so a partial week is never reported
    as a whole one. Frequency must not, because it divides by the true window length: a 61-day
    request is 61 days, and widening it to 63 would understate every rate by 3%.
    """
    snapped = build_window(
        start_day=dt.date(2026, 7, 1),
        end_day=dt.date(2026, 8, 30),
        tz="Asia/Jakarta",
        snap_to_weeks=True,
    )
    assert (snapped.start_day, snapped.end_day, snapped.days) == (
        dt.date(2026, 6, 29),
        dt.date(2026, 8, 30),
        63,
    )

    raw = build_window(
        start_day=dt.date(2026, 7, 1),
        end_day=dt.date(2026, 8, 30),
        tz="Asia/Jakarta",
        snap_to_weeks=False,
    )
    assert (raw.start_day, raw.end_day, raw.days) == (
        dt.date(2026, 7, 1),
        dt.date(2026, 8, 30),
        61,
    )


# --------------------------------------------------------------------------
# The pure muscle fan-out, also container-free
# --------------------------------------------------------------------------


def test_fold_dedupes_sessions_within_one_workout() -> None:
    """VOL-03: a per-muscle session count is a set of workout ids, pinned in both directions."""
    resolved = {_BENCH: _direct(), _ROW: _direct(), _CURL: _direct()}
    key = (_WEEK_START, _HAMSTRINGS)

    shared = uuid.uuid4()
    one = fold_weeks_by_muscle([_ham_row(shared, t) for t in (_BENCH, _ROW, _CURL)], resolved)[key]
    assert one.direct_sets == 12
    assert len(one.session_ids) == 1, (
        "sessions were summed instead of de-duplicated. One workout containing three hamstring "
        "exercises is ONE hamstring session -- summing inflated hamstrings 2 -> 8 on real data "
        "and inflated 14 of 16 muscle groups"
    )

    three = fold_weeks_by_muscle(
        [_ham_row(uuid.uuid4(), t) for t in (_BENCH, _ROW, _CURL)], resolved
    )[key]
    assert three.direct_sets == 12
    assert len(three.session_ids) == 3, "the partner assertion: 'always return 1' must also fail"


def test_fold_applies_default_and_custom_weights() -> None:
    """NORM-03: weighting is a query-time parameter, and it must not move the raw set counts."""
    workout_id = uuid.uuid4()
    rows = [_ham_row(workout_id, _BENCH), _ham_row(workout_id, _CURL)]
    resolved = {_BENCH: _direct(), _CURL: _indirect()}
    key = (_WEEK_START, _HAMSTRINGS)

    default = fold_weeks_by_muscle(rows, resolved)[key]
    custom = fold_weeks_by_muscle(rows, resolved, _CUSTOM_WEIGHTS)[key]

    assert default.weighted_sets == Decimal("6.0")
    assert custom.weighted_sets == Decimal("4.4")

    for bucket in (default, custom):
        assert (bucket.direct_sets, bucket.indirect_sets) == (4, 4), (
            "NORM-03: the direct/indirect weighting is applied at QUERY time and must never move "
            "`direct_sets` or `indirect_sets`. Those are counts of SETS PERFORMED, not weighted "
            "quantities -- a caller asking 'what if indirect counted 0.3?' is asking a different "
            "question about the same sets, and the raw counts are what makes the two comparable"
        )


def test_fold_ignores_an_unmapped_template() -> None:
    """D-03 (Phase 3): a mapping gap must not block anything.

    The exercise still happened and still counts toward VOL-01's hard sets -- it simply reaches
    no muscle bucket, silently, because "we have no mapping for this exercise" is a curation gap
    surfaced by the ``mapping-gaps`` command rather than by a query failure.
    """
    row = _ham_row(uuid.uuid4(), _BENCH)

    assert fold_weeks_by_muscle([row], {}) == {}
    assert fold_window_by_muscle([row], {}) == {}
    assert fold_window_by_template([row]) == {row.template_external_id: {row.workout_id}}
