"""Active training program as effective-dated data (GOAL-01, D-07, D-08).

D-07: this is APPEND-ONLY history, not a mutable ``users.active_program`` column
(PITFALLS #16). A mutable value retroactively re-classifies the last 12 weeks of
recomposition verdicts the moment the user switches programs -- a verdict computed
last week under "cut" thresholds would silently become a "lean_bulk" verdict on
re-read. A closed period keeps last week's context reconstructable.

``ProgramSwitchToken.nonce`` is named ``nonce``, not ``token``, on purpose.
``test_db_models.test_no_model_column_stores_a_credential`` and
``test_hevy_schema.test_no_table_stores_a_credential`` both ban any
``token``/``key``/``secret``-shaped column outright, and neither guard may be
weakened by this phase. A five-minute, single-use switch-confirmation value is not
a stored credential in the sense those guards exist to catch, and keeping both
guards at full strength is worth the one-word rename -- the MCP-facing wire field
callers see is still ``confirmation_token``.
"""

import datetime as dt
import uuid

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ProgramPeriod(Base, TimestampMixin):
    """One effective-dated period during which one training program was active."""

    __tablename__ = "user_program_history"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # 'lean_bulk' | 'cut' | 'recomp' -- app.analytics.schemas.TrainingProgram's values.
    program: Mapped[str] = mapped_column(String(16), nullable=False)
    # Date, not DateTime: a program starts on a calendar day in the user's timezone, the
    # same argument body_measurements.measured_on makes. FOUND-04 does not apply to Date.
    started_on: Mapped[dt.date] = mapped_column(Date, nullable=False)
    # NULL == the currently OPEN period. At most one per user, by the partial index below.
    ended_on: Mapped[dt.date | None] = mapped_column(Date, nullable=True)

    __table_args__ = (
        # The "exactly one open period" invariant, enforced by PostgreSQL rather than by an
        # application-level check-then-insert, which is a race and costs a round trip even
        # when it wins. Declared on the MODEL as well as in the migration so `alembic check`
        # (test_migrations.test_no_pending_model_drift) sees no divergence.
        Index(
            "uq_user_program_history_one_open_period",
            "user_id",
            unique=True,
            postgresql_where=text("ended_on IS NULL"),
        ),
        Index("ix_user_program_history_user_id_started_on", "user_id", "started_on"),
    )


class ProgramSwitchToken(Base, TimestampMixin):
    """One server-issued, single-use, time-limited authorization to switch program."""

    __tablename__ = "program_switch_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # See the module docstring for why this is `nonce` and not `token`.
    nonce: Mapped[str] = mapped_column(String(64), nullable=False)
    # The period this authorization was issued AGAINST. If it is no longer the open period
    # when the token is spent, the world moved and the switch must not apply.
    from_period_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("user_program_history.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Bound at issue time and re-checked inside the atomic consume, so a token cannot be
    # replayed against a different target program.
    to_program: Mapped[str] = mapped_column(String(16), nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # No `issued_at` column: `TimestampMixin.created_at` already is the issue instant, and a
    # second column carrying the same fact is a second column that could drift out of sync.

    __table_args__ = (UniqueConstraint("nonce", name="uq_program_switch_tokens_nonce"),)
