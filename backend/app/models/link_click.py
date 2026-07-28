"""Link click event model."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.encryption import EncryptedString
from app.db.base import Base


class LinkClick(Base):
    """A single click event on a ShortLink."""

    __tablename__ = "link_clicks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    short_link_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("short_links.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    clicked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    # Visitor IP is personal data under GDPR, so it is Fernet-encrypted at rest.
    # No lookup hash: clicks are only ever read back through ``short_link_id``
    # and nothing filters or aggregates on the IP value.
    ip_address: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    referer: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<LinkClick(short_link_id={self.short_link_id}, at={self.clicked_at})>"
