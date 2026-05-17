"""Offer model for campaign promotions with Hormozi-style value stacking."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.campaign import Campaign
    from app.models.offer_lead_magnet import OfferLeadMagnet
    from app.models.workspace import Workspace


class Offer(Base):
    """Reusable offer/promotion for campaigns."""

    __tablename__ = "offers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Offer details
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Discount configuration
    discount_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="percentage"
    )  # percentage, fixed, free_service
    discount_value: Mapped[float] = mapped_column(Float, nullable=False, default=0)

    # Additional details
    terms: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Validity
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Hormozi-style offer fields
    headline: Mapped[str | None] = mapped_column(String(500), nullable=True)
    subheadline: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Pricing for value anchoring
    regular_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    offer_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    savings_amount: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Guarantee
    guarantee_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    guarantee_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    guarantee_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Urgency and scarcity
    urgency_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    urgency_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scarcity_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Value stack items (JSON array of {name, description, value, included})
    value_stack_items: Mapped[list[dict[str, str | float | bool]] | None] = mapped_column(
        JSONB, default=list, nullable=True
    )

    # Call to action
    cta_text: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cta_subtext: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Public landing page fields
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    public_slug: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    require_email: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    require_phone: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    require_name: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Public page analytics
    page_views: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    opt_ins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

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
    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="offers")
    campaigns: Mapped[list["Campaign"]] = relationship("Campaign", back_populates="offer")
    offer_lead_magnets: Mapped[list["OfferLeadMagnet"]] = relationship(
        "OfferLeadMagnet", back_populates="offer", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Offer(id={self.id}, name={self.name}, discount_type={self.discount_type})>"
