"""Appointment model."""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.campaign import Campaign
    from app.models.contact import Contact
    from app.models.conversation import Message
    from app.models.workspace import Workspace


class AppointmentStatus(StrEnum):
    """Appointment status."""

    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_SHOW = "no_show"


class Appointment(Base):
    """Booked appointment with Cal.com sync."""

    __tablename__ = "appointments"
    __table_args__ = (
        Index(
            "ix_appointments_workspace_scheduled_at",
            "workspace_id",
            "scheduled_at",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Booking details
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    status: Mapped[AppointmentStatus] = mapped_column(
        SAEnum(
            AppointmentStatus,
            native_enum=False,
            create_constraint=False,
            length=50,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=AppointmentStatus.SCHEDULED,
        index=True,
    )
    service_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Cal.com sync
    calcom_booking_uid: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True, index=True
    )
    calcom_booking_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    calcom_event_type_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sync_status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Reminder tracking
    reminder_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Multi-touch reminder tracking — list of offsets (minutes) already sent
    reminders_sent: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), default=list, nullable=False
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
    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="appointments")
    contact: Mapped["Contact"] = relationship("Contact", back_populates="appointments")
    agent: Mapped["Agent | None"] = relationship("Agent", back_populates="appointments")
    message: Mapped["Message | None"] = relationship("Message", back_populates="appointment")
    campaign: Mapped["Campaign | None"] = relationship("Campaign", back_populates="appointments")

    def __repr__(self) -> str:
        return (
            f"<Appointment(id={self.id}, scheduled_at={self.scheduled_at}, "
            f"status={self.status})>"
        )
