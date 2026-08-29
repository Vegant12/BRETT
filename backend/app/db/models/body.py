"""Body measurements (HEVY-07, D-06, D-07-corrected).

ONE table for every source, with a `source` discriminator, so weight and composition trends
are queried from one place regardless of origin. Manual entry is a later phase; the column
exists now so that phase needs no migration.

The natural key is `(user_id, source, measured_on)` -- the whole ROW, not one row per metric.
D-07's fallback assumed per-metric keying; the live API disproves it. Hevy's
`/v1/body_measurements` returns one object per calendar date carrying all 17 metrics and has
NO id field at all; its sibling endpoints (`GET/PUT /v1/body_measurements/{date}`, and a POST
that 409s if an entry exists for that date) confirm the date IS the identity.

`measured_on` is a `Date`, not a TIMESTAMPTZ. Hevy's field is `format: date`; storing a
timestamp would require inventing a time of day. This does not violate FOUND-04 -- a calendar
date is not an instant.
"""

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import (
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class BodyMeasurement(Base, TimestampMixin):
    """Every metric Hevy records for one calendar date, in one row."""

    __tablename__ = "body_measurements"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # 'hevy' | 'manual' (D-06)
    source: Mapped[str] = mapped_column(String(16), nullable=False)

    # Always NULL for source='hevy': the API has
    # no id. Kept for a future provider that does.
    external_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # A calendar DATE, never a timestamp -- see the module docstring.
    measured_on: Mapped[dt.date] = mapped_column(Date, nullable=False)

    # Numeric, never Float: Phase 4 averages these into 7/14/30-day trends and a
    # binary float would make the same inputs produce order-dependent results.
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    lean_mass_kg: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    fat_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    # Hevy sends the last seven WITHOUT a unit suffix (`abdomen`, `waist`, `hips`,
    # `left_thigh`, `right_thigh`, `left_calf`, `right_calf`). They are renamed to `*_cm`
    # locally for consistency with the other seven and with blueprint §41. Centimetres is an
    # assumption Hevy does not document -- confirm against the app on the first live sync.
    neck_cm: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    shoulder_cm: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    chest_cm: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    left_bicep_cm: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    right_bicep_cm: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    left_forearm_cm: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    right_forearm_cm: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    abdomen_cm: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    waist_cm: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    hips_cm: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    left_thigh_cm: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    right_thigh_cm: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    left_calf_cm: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    right_calf_cm: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "source",
            "measured_on",
            name="uq_body_measurements_user_source_measured_on",
        ),
        Index("ix_body_measurements_user_id_measured_on", "user_id", "measured_on"),
    )
