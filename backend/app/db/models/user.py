"""The ``users`` table (blueprint §5.1).

v1 is single-user, but the schema is deliberately not hard-coded to one row.
"""

import uuid

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    """A platform user. Exactly one row exists in v1, seeded by migration 0002."""

    __tablename__ = "users"

    # UUID PK, not an integer: blueprint §5.1 requires not precluding multi-user
    # later, and the seed migration needs a stable, known identifier.
    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # FOUND-03: the user's timezone lives HERE, not in an env var, so analytics
    # bucketing reads it from the row it is already loading.
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default="Asia/Jakarta")

    # NOTE (D-07): the provider-credentials table and the `connections` link to
    # it are deliberately absent. They ship in Phase 3 alongside real
    # encryption; a link to a non-existent table raises at mapper
    # configuration time, and an unencrypted credential column invites a
    # plaintext key (FOUND-05).
