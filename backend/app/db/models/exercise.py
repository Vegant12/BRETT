"""Exercise templates and the muscle mapping layered on them (HEVY-06, NORM-02, NORM-03).

Three tables, deliberately:

* ``exercise_templates`` stores Hevy's RAW muscle-group strings verbatim. It is the audit
  baseline -- NORM-02 requires an override be checkable against "the original source mapping",
  and that is only possible if the original survives untouched.
* ``exercise_muscles`` is the CANONICAL derived mapping (D-02): Hevy's flat taxonomy translated
  and the deltoid/oblique splits applied. Recomputed from ``app.normalization`` on every
  template sync.
* ``exercise_muscle_overrides`` is the manual correction layer (D-04). It NEVER mutates the two
  above. Resolution is per-TEMPLATE replacement, not per-row merge -- a per-row merge would let
  a user add or change a muscle but never REMOVE one, so "this exercise does not actually work
  rear delts" would be unexpressible.

Neither table stores the direct/indirect WEIGHT. NORM-03 and blueprint §18 both require it be
configurable at query time; a weight column would freeze one answer into the data.
"""

import uuid

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ExerciseTemplate(Base, TimestampMixin):
    """One Hevy exercise definition, stored exactly as Hevy describes it."""

    __tablename__ = "exercise_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # Literal "hevy" in v1, matching `workouts.provider`.
    provider: Mapped[str] = mapped_column(String(32), nullable=False)

    # Hevy's template `id`. String, NOT UUID -- built-in templates use 8-char uppercase
    # hex ("05293BCA") and custom ones use a full UUID; a UUID column rejects half of them.
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)

    title: Mapped[str] = mapped_column(String(255), nullable=False)

    # Hevy's `type`, stored verbatim: weight_reps | reps_only | bodyweight_reps |
    # bodyweight_assisted_reps | duration | weight_duration | distance_duration |
    # short_distance_weight. This is the modality signal PROG-01 (Phase 5) needs to decide
    # whether an estimated 1RM is meaningful at all. Persist it now or resync everything later.
    exercise_type: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Hevy's RAW values, NOT translated. This pair is the audit baseline NORM-02 compares an
    # override against. `equipment_category == 'dumbbell'` is also the discriminator for the
    # open per-dumbbell-vs-combined weight question (Pitfall 12).
    primary_muscle_group: Mapped[str | None] = mapped_column(String(32), nullable=True)
    secondary_muscle_groups: Mapped[list[str]] = mapped_column(
        ARRAY(String(32)), nullable=False, server_default=text("'{}'::varchar[]")
    )

    equipment_category: Mapped[str | None] = mapped_column(String(32), nullable=True)

    is_custom: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "provider",
            "external_id",
            name="uq_exercise_templates_user_provider_external_id",
        ),
    )


class ExerciseMuscle(Base, TimestampMixin):
    """The canonical mapping derived from a template (D-02). Never mutated by an override."""

    __tablename__ = "exercise_muscles"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # A PLAIN STRING, deliberately not a ForeignKey to exercise_templates.external_id.
    # Same reasoning as `workout_exercises`: a mapping may exist for a template that has
    # not been synced yet, and a hard FK would make curation depend on sync ordering.
    exercise_template_external_id: Mapped[str] = mapped_column(String(64), nullable=False)

    # One of the 19 `CanonicalMuscleGroup` values, stored as its `.value` string.
    # Deliberately NOT a Postgres ENUM: changing a PG enum requires a migration for
    # every taxonomy tweak.
    muscle_group: Mapped[str] = mapped_column(String(32), nullable=False)

    # `MuscleRole`: 'direct' | 'indirect'. NORM-03 keeps the WEIGHT out of the schema.
    role: Mapped[str] = mapped_column(String(16), nullable=False)

    # `MappingSource`: 'hevy' | 'curated'. Records how this row was derived, which is
    # half of the NORM-02 audit.
    source: Mapped[str] = mapped_column(String(16), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "exercise_template_external_id",
            "muscle_group",
            name="uq_exercise_muscles_user_template_muscle",
        ),
        Index("ix_exercise_muscles_user_id_template", "user_id", "exercise_template_external_id"),
    )


class ExerciseMuscleOverride(Base, TimestampMixin):
    """The manual correction layer (D-04). Presence of ANY row replaces the base set."""

    __tablename__ = "exercise_muscle_overrides"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    exercise_template_external_id: Mapped[str] = mapped_column(String(64), nullable=False)

    muscle_group: Mapped[str] = mapped_column(String(32), nullable=False)

    role: Mapped[str] = mapped_column(String(16), nullable=False)

    # Why the override exists, in the user's own words. NORM-02's audit is the diff between
    # exercise_muscles and this table; the note is what makes that diff readable a year later.
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "exercise_template_external_id",
            "muscle_group",
            name="uq_exercise_muscle_overrides_user_template_muscle",
        ),
        Index(
            "ix_exercise_muscle_overrides_user_id_template",
            "user_id",
            "exercise_template_external_id",
        ),
    )
