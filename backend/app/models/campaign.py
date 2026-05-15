"""Campaign models."""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.appointment import Appointment
    from app.models.contact import Contact
    from app.models.conversation import Conversation
    from app.models.offer import Offer
    from app.models.workspace import Workspace


class CampaignType(StrEnum):
    """Campaign type."""

    SMS = "sms"
    VOICE_SMS_FALLBACK = "voice_sms_fallback"


class CampaignStatus(StrEnum):
    """Campaign status."""

    DRAFT = "draft"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELED = "canceled"


class CampaignContactStatus(StrEnum):
    """Contact status within a campaign."""

    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    REPLIED = "replied"
    QUALIFIED = "qualified"
    OPTED_OUT = "opted_out"
    FAILED = "failed"
    COMPLETED = "completed"
    # Voice campaign statuses
    CALLING = "calling"
    CALL_ANSWERED = "call_answered"
    CALL_FAILED = "call_failed"
    SMS_FALLBACK_SENT = "sms_fallback_sent"


class Campaign(Base):
    """Campaign for lead qualification via SMS or voice calls with SMS fallback."""

    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    offer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("offers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Campaign details
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    campaign_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="sms", index=True
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="draft", index=True
    )

    # Phone settings
    from_phone_number: Mapped[str] = mapped_column(String(50), nullable=False)
    use_number_pool: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Initial message (for SMS campaigns, nullable for voice campaigns)
    initial_message: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Supports {first_name}, {company_name}

    # AI settings
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    qualification_criteria: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Scheduling
    scheduled_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    scheduled_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Sending windows
    sending_hours_start: Mapped[datetime | None] = mapped_column(Time, nullable=True)
    sending_hours_end: Mapped[datetime | None] = mapped_column(Time, nullable=True)
    sending_days: Mapped[list[int] | None] = mapped_column(
        ARRAY(Integer), nullable=True
    )  # 0=Mon, 6=Sun
    timezone: Mapped[str] = mapped_column(String(50), default="America/New_York", nullable=False)

    # Rate limiting
    messages_per_minute: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    max_messages_per_contact: Mapped[int] = mapped_column(Integer, default=5, nullable=False)

    # Follow-up settings
    follow_up_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    follow_up_delay_hours: Mapped[int] = mapped_column(Integer, default=24, nullable=False)
    follow_up_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_follow_ups: Mapped[int] = mapped_column(Integer, default=2, nullable=False)

    # Voice campaign settings (for campaign_type="voice_sms_fallback")
    voice_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    voice_connection_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    enable_machine_detection: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    max_call_duration_seconds: Mapped[int] = mapped_column(
        Integer, default=120, nullable=False
    )
    calls_per_minute: Mapped[int] = mapped_column(Integer, default=5, nullable=False)

    # SMS fallback settings (for voice campaigns)
    sms_fallback_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    sms_fallback_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    sms_fallback_use_ai: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    sms_fallback_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Statistics (denormalized)
    total_contacts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    messages_sent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    messages_delivered: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    messages_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    replies_received: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    contacts_qualified: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    contacts_opted_out: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    appointments_booked: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    appointments_completed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    links_clicked: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Guarantee tracking
    guarantee_target: Mapped[int | None] = mapped_column(Integer, nullable=True)
    guarantee_window_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    guarantee_status: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Voice campaign statistics
    calls_attempted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    calls_answered: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    calls_no_answer: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    calls_busy: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    calls_voicemail: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sms_fallbacks_sent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Email campaign statistics
    emails_sent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    emails_delivered: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    emails_bounced: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    emails_opened: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    emails_clicked: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    emails_unsubscribed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Error tracking
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Timestamps
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="campaigns")
    agent: Mapped["Agent | None"] = relationship(
        "Agent", foreign_keys=[agent_id], back_populates="campaigns"
    )
    voice_agent: Mapped["Agent | None"] = relationship(
        "Agent", foreign_keys=[voice_agent_id]
    )
    sms_fallback_agent: Mapped["Agent | None"] = relationship(
        "Agent", foreign_keys=[sms_fallback_agent_id]
    )
    offer: Mapped["Offer | None"] = relationship("Offer", back_populates="campaigns")
    campaign_contacts: Mapped[list["CampaignContact"]] = relationship(
        "CampaignContact", back_populates="campaign", cascade="all, delete-orphan"
    )
    appointments: Mapped[list["Appointment"]] = relationship(
        "Appointment", back_populates="campaign"
    )

    def __repr__(self) -> str:
        return f"<Campaign(id={self.id}, name={self.name}, status={self.status})>"


class CampaignContact(Base):
    """Contact enrollment in a campaign."""

    __tablename__ = "campaign_contacts"
    __table_args__ = (
        UniqueConstraint("campaign_id", "contact_id", name="uq_campaign_contact"),
        Index("ix_campaign_contacts_campaign_status", "campaign_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Status tracking
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending", index=True
    )

    # Message tracking
    messages_sent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    messages_received: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    follow_ups_sent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Timing
    first_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_reply_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_follow_up_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # Qualification
    is_qualified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    qualification_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    qualified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Opt-out
    opted_out: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    opted_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Priority
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Call tracking (for voice campaigns)
    call_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_call_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_call_status: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # answered, no_answer, busy, voicemail, rejected
    call_duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    call_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # SMS fallback tracking (for voice campaigns)
    sms_fallback_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sms_fallback_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sms_fallback_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Error tracking
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

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
    campaign: Mapped["Campaign"] = relationship("Campaign", back_populates="campaign_contacts")
    contact: Mapped["Contact"] = relationship("Contact", back_populates="campaign_contacts")
    conversation: Mapped["Conversation | None"] = relationship(
        "Conversation", back_populates="campaign_contacts"
    )

    def __repr__(self) -> str:
        return (
            f"<CampaignContact(campaign_id={self.campaign_id}, "
            f"contact_id={self.contact_id}, status={self.status})>"
        )
