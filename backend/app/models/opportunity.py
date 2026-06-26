"""Opportunity model for sales pipeline tracking."""

import uuid
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DATE,
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.contact import Contact
    from app.models.lead_source import LeadSource, LeadSourceCampaign
    from app.models.pipeline import Pipeline, PipelineStage
    from app.models.user import User
    from app.models.workspace import Workspace


# Association table for many-to-many relationship between Opportunity and Contact
opportunity_contact_table = Table(
    "opportunity_contacts",
    Base.metadata,
    Column(
        "opportunity_id",
        UUID(as_uuid=True),
        ForeignKey("opportunities.id", ondelete="CASCADE"),
        index=True,
    ),
    Column(
        "contact_id",
        ForeignKey("contacts.id", ondelete="CASCADE"),
        index=True,
    ),
)


class Opportunity(Base):
    """Opportunity/Deal in a sales pipeline."""

    __tablename__ = "opportunities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pipelines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stage_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pipeline_stages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Primary contact
    primary_contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Assigned user (deal owner)
    assigned_user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Basic info
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Financial
    amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    probability: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )  # 0-100, auto-set by stage

    # Timeline
    expected_close_date: Mapped[date | None] = mapped_column(DATE, nullable=True)
    closed_date: Mapped[date | None] = mapped_column(DATE, nullable=True)
    closed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    stage_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Metadata
    source: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # campaign, manual, api, etc.

    # Attribution snapshot used by ROI reporting for closed-won jobs. It can be
    # copied from the primary contact when the opportunity is created/won so
    # later contact touches do not rewrite historical job attribution.
    lead_source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lead_sources.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    lead_source_campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lead_source_campaigns.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    attribution_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    status: Mapped[str] = mapped_column(
        Enum("open", "won", "lost", "abandoned", name="opportunity_status"),
        default="open",
        nullable=False,
        index=True,
    )  # GHL-style status: open, won, lost, abandoned
    lost_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

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
    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="opportunities")
    pipeline: Mapped["Pipeline"] = relationship("Pipeline", back_populates="opportunities")
    stage: Mapped["PipelineStage | None"] = relationship(
        "PipelineStage", back_populates="opportunities"
    )
    primary_contact: Mapped["Contact | None"] = relationship("Contact")
    lead_source: Mapped["LeadSource | None"] = relationship(
        "LeadSource", foreign_keys=[lead_source_id]
    )
    lead_source_campaign: Mapped["LeadSourceCampaign | None"] = relationship(
        "LeadSourceCampaign", foreign_keys=[lead_source_campaign_id]
    )
    assigned_user: Mapped["User | None"] = relationship("User", foreign_keys=[assigned_user_id])
    closed_by_user: Mapped["User | None"] = relationship("User", foreign_keys=[closed_by_id])

    # Many-to-many contacts
    contacts: Mapped[list["Contact"]] = relationship(
        "Contact",
        secondary=opportunity_contact_table,
        lazy="selectin",
    )

    # Line items
    line_items: Mapped[list["OpportunityLineItem"]] = relationship(
        "OpportunityLineItem", back_populates="opportunity", cascade="all, delete-orphan"
    )

    # Activities
    activities: Mapped[list["OpportunityActivity"]] = relationship(
        "OpportunityActivity", back_populates="opportunity", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Opportunity(id={self.id}, name={self.name}, amount={self.amount})>"


class OpportunityLineItem(Base):
    """Line item (product/service) in an opportunity."""

    __tablename__ = "opportunity_line_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("opportunities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Item info
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Pricing
    quantity: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=1)
    unit_price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    discount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    total: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)

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
    opportunity: Mapped["Opportunity"] = relationship("Opportunity", back_populates="line_items")

    def __repr__(self) -> str:
        return f"<OpportunityLineItem(id={self.id}, name={self.name}, total={self.total})>"


class OpportunityActivity(Base):
    """Activity log for opportunity changes."""

    __tablename__ = "opportunity_activities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("opportunities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Activity details
    activity_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    # activity_type values: stage_changed, amount_updated, contact_added, contact_removed, etc.
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )

    # Relationships
    opportunity: Mapped["Opportunity"] = relationship("Opportunity", back_populates="activities")
    user: Mapped["User | None"] = relationship("User")

    def __repr__(self) -> str:
        return f"<OpportunityActivity(id={self.id}, type={self.activity_type})>"
