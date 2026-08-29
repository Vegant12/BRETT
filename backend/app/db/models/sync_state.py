"""Per-resource sync bookkeeping (HEVY-09, D-08).

One row per (user, provider, resource). Three resources exist in this phase -- workouts,
exercise_templates, body_measurements -- with three genuinely independent cursors, so a single
`last_synced_at` on a connections table could not answer HEVY-09 honestly.

Named `sync_state`, NOT `external_connections`. Blueprint §5.2's name implies the encrypted
credential storage this table deliberately does not do: `Settings.hevy_api_key` stays the
env-var secret, and a decryptable credential column would sit one SQL query away from the MCP
server for no v1 benefit.

`last_error` stores an exception CLASS NAME (plus a curated safe message where the exception
provides one), never a response body -- a Hevy error body can echo the request, headers
included.
"""

import datetime as dt
import uuid

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class SyncState(Base, TimestampMixin):
    """The cursor and freshness record for one (user, provider, resource) triple."""

    __tablename__ = "sync_state"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    provider: Mapped[str] = mapped_column(String(32), nullable=False)

    # 'workouts' | 'exercise_templates' | 'body_measurements'
    resource: Mapped[str] = mapped_column(String(32), nullable=False)

    # HEVY-09
    last_synced_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # The events-feed 'since' value. Advanced ONCE, after a full drain commits (HEVY-02).
    cursor_timestamp: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # D-08 full-sync resume point. Committed in the SAME transaction as the page it describes;
    # two transactions can interleave into a checkpoint that claims rolled-back work.
    cursor_page: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # idle | running | error
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'idle'"))

    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "user_id", "provider", "resource", name="uq_sync_state_user_provider_resource"
        ),
    )
