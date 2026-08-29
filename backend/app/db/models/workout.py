"""Hevy workout history: `workouts`, `workout_exercises`, `workout_sets` (HEVY-03, HEVY-04).

Modelled on Hevy's LIVE OpenAPI document, not on `BRETT blueprint.md` §8, which predates it:
there is no `rir` (Hevy sends `rpe`), no `weight_unit` (Hevy normalises to `weight_kg`), and
child objects carry only an `index` -- **no id**. That last fact is why HEVY-03's idempotency
is "upsert the parent, delete-and-reinsert the children": there is no stable key to upsert a
set against, and per-`(workout, index)` upserts would leave surplus rows behind when an edited
workout has FEWER sets than before, silently inflating every volume figure in Phase 4.

No `relationship()` is declared anywhere in this module, deliberately. The sync path writes with
explicit Core statements and reads with explicit selects; a lazy-loading relationship touched
outside an awaited context raises `MissingGreenlet` under asyncpg, and `User` must keep zero
relationships or `test_user_has_no_relationships` fails.
"""

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Workout(Base, TimestampMixin):
    """One completed Hevy session, the parent of the exercise/set tree."""

    __tablename__ = "workouts"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # Literal "hevy" in v1. The column exists so a second provider does not need
    # a migration, and so the unique key below is already provider-scoped.
    provider: Mapped[str] = mapped_column(String(32), nullable=False)

    # Hevy's workout `id`. String, NOT UUID -- Hevy mixes full UUIDs and 8-char
    # uppercase hex ids across its own resources, and a UUID column would reject
    # half of them.
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)

    # Hevy's example title contains an emoji; UTF-8 end to end, never truncated.
    title: Mapped[str] = mapped_column(String(255), nullable=False)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Hevy's `routine_id`; kept per blueprint §8 "do not throw away useful source metadata".
    routine_external_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # FOUND-04: TIMESTAMPTZ, never bare DateTime().
    start_time: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Hevy's own `created_at`, distinct from this row's `created_at` (which records
    # when WE first stored it).
    provider_created_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Hevy's `updated_at` -- the event-drain ordering key for HEVY-02.
    provider_updated_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        # ON CONFLICT needs a REAL unique index; without it Postgres raises
        # "there is no unique or exclusion constraint matching the ON CONFLICT
        # specification" and HEVY-03 becomes unenforceable.
        UniqueConstraint(
            "user_id", "provider", "external_id", name="uq_workouts_user_provider_external_id"
        ),
        # Phase 4 filters every volume query by user and date window.
        Index("ix_workouts_user_id_start_time", "user_id", "start_time"),
    )


class WorkoutExercise(Base):
    """One exercise within a workout, identified upstream only by its `index`."""

    # No TimestampMixin: children are delete-and-reinserted wholesale on every re-sync
    # of their parent, so a per-row `created_at` would record the last sync, not the
    # last edit, and would be actively misleading. The parent workout carries the
    # audit timestamps.

    __tablename__ = "workout_exercises"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    workout_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workouts.id", ondelete="CASCADE"), nullable=False
    )

    exercise_index: Mapped[int] = mapped_column(Integer, nullable=False)

    title: Mapped[str] = mapped_column(String(255), nullable=False)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # A PLAIN STRING, deliberately not a ForeignKey to exercise_templates.id.
    # A workout can reference a template that does not exist locally (templates not
    # synced yet, or a custom template deleted upstream). A hard FK would make the
    # workout sync fail on exactly the data D-03 says must still persist.
    exercise_template_external_id: Mapped[str] = mapped_column(String(64), nullable=False)

    supersets_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "workout_id", "exercise_index", name="uq_workout_exercises_workout_id_exercise_index"
        ),
        Index(
            "ix_workout_exercises_exercise_template_external_id", "exercise_template_external_id"
        ),
    )


class WorkoutSet(Base):
    """One set within an exercise, identified upstream only by its `index`."""

    # No TimestampMixin, for the same reason as WorkoutExercise.

    __tablename__ = "workout_sets"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    workout_exercise_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workout_exercises.id", ondelete="CASCADE"),
        nullable=False,
    )

    set_index: Mapped[int] = mapped_column(Integer, nullable=False)

    # Stored VERBATIM as Hevy sends it: 'normal' | 'warmup' | 'dropset' | 'failure'.
    # Coercing to an is_warmup boolean would discard the dropset/failure distinction
    # that Phase 5's PR detection needs. VOL-01 excludes exactly `set_type == 'warmup'`.
    set_type: Mapped[str] = mapped_column(String(16), nullable=False)

    # Numeric, never Float. Phase 4 sums thousands of these into tonnage and
    # 0.1 + 0.2 != 0.3 in binary floating point. Numeric(7,3) round-trips as an
    # exact Decimal. Hevy sends per-set weight already normalised to kilograms.
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(7, 3), nullable=True)

    reps: Mapped[int | None] = mapped_column(Integer, nullable=True)

    distance_meters: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)

    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    rpe: Mapped[Decimal | None] = mapped_column(Numeric(3, 1), nullable=True)

    custom_metric: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "workout_exercise_id", "set_index", name="uq_workout_sets_workout_exercise_id_set_index"
        ),
    )
