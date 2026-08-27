"""Persisted SMS booking details awaiting explicit customer confirmation."""

import uuid
from datetime import UTC, date, datetime, time
from enum import StrEnum

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Time, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.encryption import EncryptedString
from app.db.base import Base


class BookingDraftCallType(StrEnum):
    """Customer-selected appointment format."""

    PHONE_CALL = "phone_call"
    VIDEO_CALL = "video_call"


class ConversationBookingDraft(Base):
    """One complete, validated booking summary waiting for customer approval."""

    __tablename__ = "conversation_booking_drafts"
    __table_args__ = (
        CheckConstraint(
            "duration_minutes BETWEEN 5 AND 480",
            name="ck_conversation_booking_drafts_duration",
        ),
        CheckConstraint(
            "call_type IN ('phone_call', 'video_call')",
            name="ck_conversation_booking_drafts_call_type",
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    time: Mapped[time] = mapped_column(Time(timezone=False), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    call_type: Mapped[BookingDraftCallType] = mapped_column(
        SAEnum(
            BookingDraftCallType,
            native_enum=False,
            create_constraint=False,
            length=20,
            values_callable=lambda enum: [member.value for member in enum],
        ),
        nullable=False,
    )
    # Invite email and the customer-visible summary contain PII, so both remain
    # Fernet-encrypted and are never queried by value.
    email: Mapped[str] = mapped_column(EncryptedString(), nullable=False)
    confirmation_text: Mapped[str] = mapped_column(EncryptedString(), nullable=False)
    prepared_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
