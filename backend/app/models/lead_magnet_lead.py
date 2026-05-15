"""Lead magnet lead model for tracking captured leads."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.contact import Contact
    from app.models.lead_magnet import LeadMagnet
    from app.models.offer import Offer
    from app.models.workspace import Workspace


class LeadMagnetLead(Base):
    """Track leads captured via lead magnets."""

    __tablename__ = "lead_magnet_leads"
    __table_args__ = (
        Index(
            "ix_lead_magnet_leads_workspace_created_at",
            "workspace_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    lead_magnet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lead_magnets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Contact information
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    phone_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Link to CRM contact if created/matched
    contact_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("contacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Quiz/Calculator data
    quiz_answers: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    calculator_inputs: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Delivery tracking
    delivered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Source tracking
    source_offer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("offers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    # Relationships
    lead_magnet: Mapped["LeadMagnet"] = relationship("LeadMagnet")
    workspace: Mapped["Workspace"] = relationship("Workspace")
    contact: Mapped["Contact | None"] = relationship("Contact")
    source_offer: Mapped["Offer | None"] = relationship("Offer")

    def __repr__(self) -> str:
        return f"<LeadMagnetLead(id={self.id}, email={self.email}, score={self.score})>"
