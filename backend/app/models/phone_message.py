"""PhoneMessage model — structured "take a message" captures from voice calls.

When the AI receptionist runs the ``take_message`` voice tool, it captures a
structured message the caller wants relayed to a human (name, callback number,
reason/topic, urgency, preferred callback time, and a free-text message). Each
capture is persisted here, linked to the call's :class:`Message` row and the
conversation/contact, so operators can review and action it from the calls UI.
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.conversation import Message


class PhoneMessageUrgency(StrEnum):
    """Caller-stated urgency of a taken message."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PhoneMessageStatus(StrEnum):
    """Operator workflow status for a taken message."""

    NEW = "new"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class PhoneMessage(Base):
    """A structured message captured for an operator during a voice call."""

    __tablename__ = "phone_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The call's Message row (the voice call during which the message was taken).
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    contact_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("contacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Structured capture fields.
    caller_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    callback_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    urgency: Mapped[PhoneMessageUrgency] = mapped_column(
        SAEnum(
            PhoneMessageUrgency,
            native_enum=False,
            create_constraint=False,
            length=20,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=PhoneMessageUrgency.MEDIUM,
        index=True,
    )
    # Free text — callers say things like "tomorrow afternoon" rather than a time.
    preferred_callback_time: Mapped[str | None] = mapped_column(String(200), nullable=True)
    message_body: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Operator workflow status.
    status: Mapped[PhoneMessageStatus] = mapped_column(
        SAEnum(
            PhoneMessageStatus,
            native_enum=False,
            create_constraint=False,
            length=20,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=PhoneMessageStatus.NEW,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Relationships
    message: Mapped["Message | None"] = relationship(
        "Message", back_populates="phone_messages", foreign_keys=[message_id]
    )

    def __repr__(self) -> str:
        return f"<PhoneMessage(id={self.id}, caller={self.caller_name}, urgency={self.urgency})>"
