"""Drip campaign models for multi-step lead reactivation sequences.

A DripCampaign defines a sequence of timed SMS messages (steps stored as JSONB).
A DripEnrollment tracks each contact's progress through the sequence.

When a contact replies, the enrollment is paused and the AI text agent takes
over the conversation. The drip only handles outbound cadence — response
handling is delegated to the existing text_agent + response_classifier.
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.contact import Contact
    from app.models.workspace import Workspace


class DripCampaignStatus(StrEnum):
    """Drip campaign lifecycle status."""

    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"


class DripEnrollmentStatus(StrEnum):
    """Per-contact enrollment status."""

    ACTIVE = "active"
    PAUSED = "paused"
    RESPONDED = "responded"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ResponseCategory(StrEnum):
    """Classification of a contact's reply."""

    INTERESTED = "interested"
    NOT_INTERESTED = "not_interested"
    TIMING = "timing"
    QUESTION = "question"
    APPOINTMENT_REQUEST = "appointment_request"
    OPT_OUT = "opt_out"
    UNKNOWN = "unknown"


class DripCampaign(Base):
    """Multi-step drip sequence for lead reactivation."""

    __tablename__ = "drip_campaigns"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
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

    # Campaign details
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[DripCampaignStatus] = mapped_column(
        SAEnum(
            DripCampaignStatus,
            native_enum=False,
            create_constraint=False,
            length=50,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=DripCampaignStatus.DRAFT,
        index=True,
    )

    # Phone settings
    from_phone_number: Mapped[str] = mapped_column(String(50), nullable=False)

    # Sequence steps stored as JSONB array:
    # [
    #   {"step": 0, "delay_days": 0, "message": "...", "type": "value_offer"},
    #   {"step": 1, "delay_days": 2, "message": "...", "type": "follow_up"},
    #   ...
    # ]
    sequence_steps: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
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

    # Statistics (denormalized)
    total_enrolled: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_completed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_responded: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_cancelled: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_messages_sent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_appointments_booked: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

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
    workspace: Mapped["Workspace"] = relationship("Workspace")
    agent: Mapped["Agent | None"] = relationship("Agent")
    enrollments: Mapped[list["DripEnrollment"]] = relationship(
        "DripEnrollment", back_populates="drip_campaign", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<DripCampaign(id={self.id}, name={self.name}, status={self.status})>"


class DripEnrollment(Base):
    """Tracks a single contact's progress through a drip sequence."""

    __tablename__ = "drip_enrollments"
    __table_args__ = (
        UniqueConstraint("drip_campaign_id", "contact_id", name="uq_drip_enrollment"),
        Index(
            "ix_drip_enrollment_next_step",
            "status",
            "next_step_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    drip_campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("drip_campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Progress
    status: Mapped[DripEnrollmentStatus] = mapped_column(
        SAEnum(
            DripEnrollmentStatus,
            native_enum=False,
            create_constraint=False,
            length=50,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=DripEnrollmentStatus.ACTIVE,
        index=True,
    )
    current_step: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_step_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # Response tracking
    response_category: Mapped[ResponseCategory | None] = mapped_column(
        SAEnum(
            ResponseCategory,
            native_enum=False,
            create_constraint=False,
            length=50,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=True,
    )
    cancel_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Message stats
    messages_sent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    messages_received: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Timing
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_reply_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Timestamps
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
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
    drip_campaign: Mapped["DripCampaign"] = relationship(
        "DripCampaign", back_populates="enrollments"
    )
    contact: Mapped["Contact"] = relationship("Contact")

    def __repr__(self) -> str:
        return (
            f"<DripEnrollment(campaign={self.drip_campaign_id}, "
            f"contact={self.contact_id}, step={self.current_step}, "
            f"status={self.status})>"
        )
