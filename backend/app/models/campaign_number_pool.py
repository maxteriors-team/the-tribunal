"""Campaign number pool model."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.campaign import Campaign
    from app.models.phone_number import PhoneNumber


class CampaignNumberPool(Base):
    """Phone number pool assignment for campaigns."""

    __tablename__ = "campaign_number_pools"
    __table_args__ = (
        UniqueConstraint("campaign_id", "phone_number_id", name="uq_campaign_phone_number_pool"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    phone_number_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("phone_numbers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Pool management
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # Higher = preferred

    # Usage tracking
    messages_sent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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
    campaign: Mapped["Campaign"] = relationship("Campaign")
    phone_number: Mapped["PhoneNumber"] = relationship("PhoneNumber")

    def __repr__(self) -> str:
        return (
            f"<CampaignNumberPool(campaign_id={self.campaign_id}, "
            f"phone_number_id={self.phone_number_id}, priority={self.priority})>"
        )
