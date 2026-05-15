"""Phone number model."""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.workspace import Workspace


class TrustTier(StrEnum):
    """10DLC trust tier levels."""

    LOW_VOLUME = "low_volume"
    STANDARD = "standard"
    HIGH_VOLUME = "high_volume"


class PhoneNumberHealthStatus(StrEnum):
    """Phone number health status."""

    HEALTHY = "healthy"
    WARMING = "warming"
    COOLDOWN = "cooldown"
    QUARANTINED = "quarantined"


class PhoneNumber(Base):
    """Telnyx phone number assigned to a workspace."""

    __tablename__ = "phone_numbers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Phone number
    phone_number: Mapped[str] = mapped_column(
        String(50), nullable=False, unique=True, index=True
    )  # E.164 format
    friendly_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Telnyx identifiers
    telnyx_phone_number_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    telnyx_messaging_profile_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Capabilities
    sms_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    voice_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    mms_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Agent assignment
    assigned_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # === 10DLC Trust Tier Configuration ===
    trust_tier: Mapped[TrustTier] = mapped_column(
        SAEnum(
            TrustTier,
            native_enum=False,
            create_constraint=False,
            length=50,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=TrustTier.LOW_VOLUME,
    )
    daily_limit: Mapped[int] = mapped_column(Integer, default=75, nullable=False)
    hourly_limit: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    messages_per_second: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)

    # === Health Status ===
    health_status: Mapped[PhoneNumberHealthStatus] = mapped_column(
        SAEnum(
            PhoneNumberHealthStatus,
            native_enum=False,
            create_constraint=False,
            length=50,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=PhoneNumberHealthStatus.HEALTHY,
        index=True,
    )

    # === 7-Day Rolling Reputation Metrics ===
    messages_sent_7d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    messages_delivered_7d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    hard_bounces_7d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    soft_bounces_7d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    spam_complaints_7d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    opt_outs_7d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # === Calculated Rates (0.0 to 1.0) ===
    delivery_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    bounce_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    complaint_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # === Warming Schedule ===
    warming_stage: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )  # 0=not warming, 1-7=warming days
    warming_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # === Quarantine Tracking ===
    quarantined_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    quarantine_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    quarantine_reviewed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # === Last Send Tracking ===
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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
    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="phone_numbers")
    assigned_agent: Mapped["Agent | None"] = relationship(
        "Agent", back_populates="phone_numbers"
    )

    def __repr__(self) -> str:
        return f"<PhoneNumber(id={self.id}, number={self.phone_number})>"
