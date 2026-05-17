"""EmailEvent model for tracking Resend webhook events."""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EmailEventType(StrEnum):
    """Email event type."""

    SENT = "sent"
    DELIVERED = "delivered"
    BOUNCED = "bounced"
    OPENED = "opened"
    CLICKED = "clicked"
    COMPLAINED = "complained"
    UNSUBSCRIBED = "unsubscribed"


class EmailEvent(Base):
    """Inbound email event from the Resend webhook."""

    __tablename__ = "email_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[EmailEventType] = mapped_column(
        SAEnum(
            EmailEventType,
            native_enum=False,
            create_constraint=False,
            length=50,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    provider_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    event_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)

    def __repr__(self) -> str:
        return f"<EmailEvent(id={self.id}, type={self.event_type})>"
