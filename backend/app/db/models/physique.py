"""Physique observations and per-muscle-group ratings (PHYS-01 through PHYS-05).

This is the persistence shape for Claude-produced physique observations. BRETT never stores
photos -- only structured observations persist (milestone-gate decision, `.planning/STATE.md`).
A photo is attached in the Claude conversation and is gone the moment the call returns; nothing
here has a column, a table, or a foreign key that could hold one.

`rating_level` and `pose_state` are `String` + a named `CHECK`, deliberately NOT a native
PostgreSQL `ENUM` (PHYS-03, D-02): `DROP TABLE` leaves a `pg_type` behind for a native enum, and
`test_migrations.py::test_migrations_round_trip` is what catches that if it ever regresses.

The supersede columns (`superseded_at`, `superseded_reason`, `superseded_by_id`) exist on the
model and in migration `0007` now, but nothing in Phase 16 writes them (D-01); the write logic
that sets them is Phase 17's PHYS-08.

No ORM `relationship` mapping is declared anywhere on either model: an async lazy-load raises
`MissingGreenlet` the first time an unawaited attribute access triggers one, so the repository
loads a `PhysiqueObservation`'s ratings with a second explicit query instead.
"""

import datetime as dt
import uuid
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

# `CanonicalMuscleGroup` is deliberately NOT imported here -- `PhysiqueRating.muscle_group`
# stores one of its 19 `.value` strings but is validated in Python at the repository layer,
# exactly like `ExerciseMuscle.muscle_group`. Importing the enum only to reference it in a
# comment would be an unused import that Ruff `F401` rejects.

# LOCKED by PHYS-01. Copied verbatim from `15-SPIKE-RESULT.md`'s "## Recommended Constants" --
# do not paraphrase the wording below, it carries decision provenance from the Phase 15 spike.
PHYSIQUE_RATING_LEVELS = (
    "Minimal",
    "Emerging",
    "Developed",
    "Well-Developed",
    "Standout",
)

PHYSIQUE_RATING_ANCHORS = (
    "1. Minimal - the group shows little visible development; its outline is not apparent "
    "in this photo set. "
    "2. Emerging - the group's outline is visible but shallow; shape is suggested rather "
    "than defined. "
    "3. Developed - the group has clear shape and visible separation from adjacent groups. "
    "4. Well-Developed - the group is clearly fuller or more defined than the average group "
    "on THIS person's own body. "
    "5. Standout - the group is among the most developed on THIS person's own body; it is "
    "the group a viewer would notice first."
)

# Carried forward for Phase 17 (PHYS-09). Nothing in Phase 16 reads these.
PHYSIQUE_MIN_ELAPSED_DAYS = 30
PHYSIQUE_DIFF_MIN_LEVEL_DELTA = 2


class PhysiqueRatingLevel(StrEnum):
    """The five levels of PHYSIQUE_RATING_LEVELS. Declaration order IS ordinal order."""

    MINIMAL = "Minimal"
    EMERGING = "Emerging"
    DEVELOPED = "Developed"
    WELL_DEVELOPED = "Well-Developed"
    STANDOUT = "Standout"


class PoseState(StrEnum):
    """PHYS-05/D-02: exactly the two pose states, bounded by a named CHECK, never a pg ENUM."""

    RELAXED = "relaxed"
    LIGHTLY_FLEXED = "lightly_flexed"


class PhotoAngle(StrEnum):
    """PHYS-05/D-03: the three angles the Phase 15 spike's photo sets ever contained.

    Deliberately no `other`/`unspecified` member: a catch-all value would make the CHECK
    constraint on `photo_angles_present` accept anything a caller felt like calling "other",
    which is the same as having no constraint. A fourth real angle is a migration, on purpose.
    """

    FRONT = "front"
    BACK = "back"
    SIDE = "side"


class PhysiqueObservation(Base, TimestampMixin):
    """One dated physique observation header, produced by Claude from photos never stored."""

    __tablename__ = "physique_observations"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # A calendar DATE in the user's timezone (Asia/Jakarta), not an instant -- same argument
    # `body_measurements.measured_on` makes. PHYSIQUE_MIN_ELAPSED_DAYS needs a stable
    # calendar-day basis. FOUND-04 does not apply to `Date`.
    observed_on: Mapped[dt.date] = mapped_column(Date, nullable=False)

    # Caps are per-column and deliberately different: notes 500 (D-04), conditions_note 200
    # (D-06), PhysiqueRating.not_assessable_reason 160 (D-05).
    leanness_notes: Mapped[str | None] = mapped_column(String(500), nullable=True)  # D-04
    conditioning_notes: Mapped[str | None] = mapped_column(String(500), nullable=True)  # D-04
    symmetry_notes: Mapped[str | None] = mapped_column(String(500), nullable=True)  # D-04

    photo_angles_present: Mapped[list[str]] = mapped_column(
        ARRAY(String(16)), nullable=False, server_default=text("'{}'::varchar[]")
    )  # D-03
    pose_state: Mapped[str] = mapped_column(String(16), nullable=False)  # D-02, PoseState.value
    conditions_note: Mapped[str | None] = mapped_column(String(200), nullable=True)  # D-06

    superseded_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # D-01
    superseded_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)  # D-01
    # SET NULL, never CASCADE (16-RESEARCH.md Pitfall 4): deleting a newer, superseding
    # observation must not touch the older row it merely points at.
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("physique_observations.id", ondelete="SET NULL"),
        nullable=True,
    )  # D-01

    # The `name=` values below are SHORT, UNPREFIXED labels -- `NAMING_CONVENTION["ck"]` is
    # `ck_%(table_name)s_%(constraint_name)s` and `%(constraint_name)s` echoes back exactly
    # what you pass, so passing `"ck_physique_observations_valid_pose_state"` here would
    # resolve to `ck_physique_observations_ck_physique_observations_valid_pose_state`
    # (16-RESEARCH.md Pitfall 1). This is unlike `uq`/`fk`/`pk`, whose tokens are
    # column/table-derived.
    __table_args__ = (
        CheckConstraint(
            "pose_state IN ('relaxed','lightly_flexed')",
            name="valid_pose_state",
        ),
        CheckConstraint(
            "photo_angles_present <@ ARRAY['front','back','side']::varchar(16)[]",
            name="valid_photo_angles",
        ),
        Index(
            "ix_physique_observations_user_id_observed_on",
            "user_id",
            "observed_on",
        ),
        # Deliberately NO UniqueConstraint on (user_id, observed_on): two observations on one
        # calendar day are corrected by PHYS-08's supersede mechanism (Phase 17), not refused
        # by the schema (16-RESEARCH.md Open Question 2).
    )


class PhysiqueRating(Base, TimestampMixin):
    """One (observation, muscle_group) rating -- exactly 19 rows per observation (D-07)."""

    __tablename__ = "physique_ratings"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # CASCADE here (unlike `superseded_by_id`) because a rating row has no life of its own;
    # the observation's own append-only posture is enforced by the write path never issuing
    # a DELETE, not by this FK.
    observation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("physique_observations.id", ondelete="CASCADE"),
        nullable=False,
    )

    # One of the 19 `CanonicalMuscleGroup` values, stored as its `.value`. No CHECK constraint
    # on this column -- `exercise_muscles.muscle_group` sets the precedent (plain `String(32)`,
    # validated in Python) and a 19-value CHECK would make every future taxonomy tweak a
    # migration, which is the exact cost the "never a pg ENUM" rule exists to avoid. PHYS-03's
    # named-CHECK requirement is about the RATING vocabulary, not the taxonomy.
    muscle_group: Mapped[str] = mapped_column(String(32), nullable=False)

    rating_level: Mapped[str | None] = mapped_column(String(16), nullable=True)
    not_assessable_reason: Mapped[str | None] = mapped_column(String(160), nullable=True)  # D-05

    __table_args__ = (
        CheckConstraint(
            "rating_level IN ('Minimal','Emerging','Developed','Well-Developed','Standout')",
            name="valid_rating_level",
        ),
        # PHYS-02: `Not Assessable` is a first-class value carrying a reason, never a forced
        # numeric guess, and never a sentinel string crammed into `rating_level`. Exactly one
        # of the two columns is populated per row, enforced by PostgreSQL rather than by
        # whichever code path happens to write the row.
        CheckConstraint(
            "(rating_level IS NOT NULL AND not_assessable_reason IS NULL) OR "
            "(rating_level IS NULL AND not_assessable_reason IS NOT NULL)",
            name="rating_xor_not_assessable",
        ),
        # D-08 -- the "exactly one row per (observation, muscle group)" invariant belongs to
        # the database, mirroring `ProgramPeriod`'s partial unique index rationale. This
        # constraint's `name=` IS fully spelled out, matching
        # `UniqueConstraint("nonce", name="uq_program_switch_tokens_nonce")` in `program.py`.
        UniqueConstraint(
            "observation_id",
            "muscle_group",
            name="uq_physique_ratings_observation_id_muscle_group",
        ),
    )
