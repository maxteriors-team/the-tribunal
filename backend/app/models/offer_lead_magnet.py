"""Association model for offers and lead magnets (many-to-many)."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.lead_magnet import LeadMagnet
    from app.models.offer import Offer


class OfferLeadMagnet(Base):
    """Association between offers and lead magnets for value stacking."""

    __tablename__ = "offer_lead_magnets"
    __table_args__ = (UniqueConstraint("offer_id", "lead_magnet_id", name="uq_offer_lead_magnet"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    offer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("offers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    lead_magnet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lead_magnets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Ordering and display
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_bonus: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    # Relationships
    offer: Mapped["Offer"] = relationship("Offer", back_populates="offer_lead_magnets")
    lead_magnet: Mapped["LeadMagnet"] = relationship(
        "LeadMagnet", back_populates="offer_lead_magnets"
    )

    def __repr__(self) -> str:
        return f"<OfferLeadMagnet(offer_id={self.offer_id}, lead_magnet_id={self.lead_magnet_id})>"
