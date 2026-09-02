"""Day-grained Apple Health metrics (HEALTH-08, HEALTH-09, NUTR-03, D-01, D-02).

ONE row per ``(user, source, metric, source_name, local_day)``. The presence of ``source_name``
IN the natural key -- rather than as a nullable attribute hanging off it -- is the foundational
decision of this phase, and it exists for a measured reason.

**HEALTH-08 requires excluding data that originates from Hevy's own HealthKit write-back.**
Research measured the user's real export: Hevy writes an ``ActiveEnergyBurned`` record on 209
training days, and that single lump record is **70-88%** of the day's total active energy, while
the iPhone independently records the same physical activity across the same window (2026-01-02:
Hevy 666.5 kcal in 1 record, ``Vegant's iPhone`` 94.2 kcal in 16 records). ``active_energy`` is
an allowlisted metric, so a metric-name allowlist alone cannot satisfy HEALTH-08. If the day is
stored as one blended row, Hevy's contribution has already been summed in and can never be
filtered back out. With ``source_name`` in the key, Hevy's contribution is its own addressable
row and exclusion is a ``WHERE`` clause.

**Multi-source-per-day is real in this user's data, not hypothetical (Finding D).** On
2026-08-23 both ``Foodvisor`` (1040 + 504 + 670) and ``Built With Science`` (105 + 295.62) wrote
``DietaryEnergyConsumed``. Blindly summing them is correct only if the two apps logged disjoint
food, which nothing guarantees. The schema must be able to express the split rather than silently
blend it.

**``source_name`` is NOT NULL with an explicit ``'unknown'`` sentinel written at normalize time.**
PostgreSQL treats ``NULL``s as DISTINCT inside a UNIQUE constraint, so a nullable key column
silently permits unbounded duplicate rows -- and real Health Auto Export payloads *do* omit the
``source`` key entirely for gait metrics. ``UNIQUE NULLS NOT DISTINCT`` would also work but needs
PostgreSQL >= 15, which has not been verified against this Neon instance; the sentinel works on
every version.

**D-02: this is the only table this phase adds.** There is deliberately no second table for
Apple Health *workouts* -- 218 of 221 of them are Hevy re-exports of data BRETT already holds at
set-level detail, so ingesting them would double-count at lower fidelity. D-01 likewise keeps
``weight_body_mass`` out of ``body_measurements``: no new ``source`` value is added there by this
phase.
"""

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import (
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class HealthDailyMetric(Base, TimestampMixin):
    """One metric, from one originating app, aggregated to one of the user's local days."""

    __tablename__ = "health_daily_metrics"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    # 'apple_health' (12 chars). NEVER 'health_auto_export' (18) -- Pitfall 8: this column is
    # String(16) to match `body_measurements.source`, and the longer spelling would truncate.
    source: Mapped[str] = mapped_column(String(16), nullable=False)

    # The HAE wire metric name, verbatim: 'step_count', 'active_energy', 'basal_energy_burned',
    # 'walking_running_distance', 'flights_climbed', 'dietary_energy', 'protein', 'carbohydrates',
    # 'total_fat', 'fiber', 'dietary_sugar', 'sodium'. Longest today is 24 chars.
    metric: Mapped[str] = mapped_column(String(64), nullable=False)

    # The per-datapoint originating APP, e.g. 'Hevy', 'iPhone', 'Foodvisor', 'Built With Science'.
    # NOT NULL with an explicit 'unknown' sentinel written at normalize time. Nullable-in-key would
    # silently permit duplicate rows, because PostgreSQL treats NULLs as distinct inside a UNIQUE
    # constraint -- and real HAE payloads DO omit `source` for gait metrics.
    source_name: Mapped[str] = mapped_column(String(128), nullable=False)

    # The user's local calendar day (FOUND-03), resolved by core.time.local_day. A date, never a
    # timestamp: this row is a daily aggregate, so there is no instant to store.
    local_day: Mapped[dt.date] = mapped_column(Date, nullable=False)

    # NUMERIC -- never an integer column, never a binary float column. A `count`-unit metric
    # arrives FRACTIONAL from HAE (flights_climbed = 0.20163697817574894, prorated across
    # aggregation buckets), so an INTEGER column truncates 59 real fragments of a day to 0 with
    # no error anywhere (RESEARCH Finding C).
    value: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)

    # The CANONICAL unit this row is stored in ('kcal' | 'g' | 'mg' | 'km' | 'count'), not the wire
    # unit. HAE units are a per-metric USER PREFERENCE inside the phone app and change silently on
    # the next export, so the stored unit is recorded rather than assumed.
    units: Mapped[str] = mapped_column(String(16), nullable=False)

    # How many wire datapoints were aggregated into this row. The cheapest diagnostic for Pitfall
    # N-2: a sample_count that FALLS on a re-sync is a batch-split data loss, visible in one query.
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        # Named EXPLICITLY. `db/base.py`'s convention is `uq_%(table_name)s_%(column_0_name)s`,
        # which would generate `uq_health_daily_metrics_user_id` -- a name that says nothing about
        # the other four columns and would collide with any future single-column UQ on `user_id`.
        # 57 characters, inside PostgreSQL's 63-byte identifier limit. The ingest binds
        # `ON CONFLICT` to this name, so renaming it raises rather than degrading into duplicates.
        UniqueConstraint(
            "user_id",
            "source",
            "metric",
            "source_name",
            "local_day",
            name="uq_health_daily_metrics_user_source_metric_source_name_day",
        ),
        Index(
            "ix_health_daily_metrics_user_id_metric_local_day",
            "user_id",
            "metric",
            "local_day",
        ),
    )
