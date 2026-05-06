"""Conversation and Message models."""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.appointment import Appointment
    from app.models.call_feedback import CallFeedback
    from app.models.call_outcome import CallOutcome
    from app.models.campaign import CampaignContact
    from app.models.contact import Contact
    from app.models.message_test import TestContact
    from app.models.phone_number import PhoneNumber
    from app.models.prompt_version import PromptVersion
    from app.models.workspace import Workspace


class MessageDirection(StrEnum):
    """Message direction."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"


class MessageStatus(StrEnum):
    """Message delivery status."""

    QUEUED = "queued"
    SENDING = "sending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    RECEIVED = "received"


class MessageChannel(StrEnum):
    """Message channel."""

    SMS = "sms"
    VOICE = "voice"
    VOICEMAIL = "voicemail"


class Conversation(Base):
    """Unified conversation thread with a contact."""

    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "workspace_phone", "contact_phone", name="uq_conversation_phones"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("contacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Phone numbers
    workspace_phone: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True
    )  # Our Telnyx number
    contact_phone: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True
    )  # Contact's phone

    # Status
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="active", index=True
    )  # active, archived, blocked
    channel: Mapped[str] = mapped_column(
        String(20), nullable=False, default="sms"
    )  # sms, voice, mixed

    # AI handling
    assigned_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    ai_paused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ai_paused_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Message preview (denormalized)
    unread_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_message_preview: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    last_message_direction: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Origin tracking
    initiated_by: Mapped[str] = mapped_column(
        String(20), nullable=False, default="platform"
    )  # platform, external

    # Follow-up settings
    followup_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    followup_delay_hours: Mapped[int] = mapped_column(Integer, default=24, nullable=False)
    followup_max_count: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    followup_count_sent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_followup_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_followup_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="conversations")
    contact: Mapped["Contact | None"] = relationship("Contact", back_populates="conversations")
    assigned_agent: Mapped["Agent | None"] = relationship(
        "Agent", back_populates="conversations", foreign_keys=[assigned_agent_id]
    )
    messages: Mapped[list["Message"]] = relationship(
        "Message", back_populates="conversation", cascade="all, delete-orphan"
    )
    campaign_contacts: Mapped[list["CampaignContact"]] = relationship(
        "CampaignContact", back_populates="conversation"
    )
    test_contacts: Mapped[list["TestContact"]] = relationship(
        "TestContact", back_populates="conversation"
    )

    def __repr__(self) -> str:
        return f"<Conversation(id={self.id}, contact_phone={self.contact_phone})>"


class BounceType(StrEnum):
    """Bounce type classification."""

    HARD = "hard"
    SOFT = "soft"
    SPAM_COMPLAINT = "spam_complaint"


class Message(Base):
    """Individual message in a conversation."""

    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint(
            "provider_message_id", name="uq_messages_provider_message_id"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Message details
    direction: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # sms, voice, voicemail, email
    body: Mapped[str] = mapped_column(Text, nullable=False)

    # Email-specific fields
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recipient_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    sender_email: Mapped[str | None] = mapped_column(String(320), nullable=True)

    # Delivery tracking
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="queued", index=True
    )
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # === Bounce Classification ===
    bounce_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # hard, soft, spam_complaint
    bounce_category: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # invalid_number, carrier_block, opted_out, etc.
    carrier_error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    carrier_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # === Phone Number Tracking ===
    from_phone_number_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("phone_numbers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # AI attribution
    is_ai: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Campaign attribution
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Voice-specific
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recording_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    booking_outcome: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Prompt version attribution for calls
    prompt_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("prompt_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Timestamps
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )

    # Relationships
    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="messages")
    agent: Mapped["Agent | None"] = relationship(
        "Agent", back_populates="messages", foreign_keys=[agent_id]
    )
    from_phone_number: Mapped["PhoneNumber | None"] = relationship(  # noqa: F821
        "PhoneNumber", foreign_keys=[from_phone_number_id]
    )
    prompt_version: Mapped["PromptVersion | None"] = relationship(
        "PromptVersion", foreign_keys=[prompt_version_id]
    )
    call_outcome: Mapped["CallOutcome | None"] = relationship(
        "CallOutcome", back_populates="message", uselist=False
    )
    feedback: Mapped[list["CallFeedback"]] = relationship(
        "CallFeedback", back_populates="message"
    )
    appointment: Mapped["Appointment | None"] = relationship(
        "Appointment", back_populates="message", uselist=False
    )

    def __repr__(self) -> str:
        return f"<Message(id={self.id}, direction={self.direction}, status={self.status})>"
