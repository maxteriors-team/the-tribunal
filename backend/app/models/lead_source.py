"""Lead Source model for public lead ingestion."""

import secrets
import string
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def generate_lead_source_key() -> str:
    """Generate a short public key for lead source (e.g., ls_xK9mN2pQ)."""
    chars = string.ascii_letters + string.digits
    random_part = "".join(secrets.choice(chars) for _ in range(8))
    return f"ls_{random_part}"


if TYPE_CHECKING:
    from app.models.workspace import Workspace


class LeadSourceType(StrEnum):
    """Top-level channel used for lead attribution ROI reporting."""

    FACEBOOK_ADS = "facebook_ads"
    GOOGLE_ADS = "google_ads"
    ORGANIC = "organic"
    PHONE_RADIO = "phone_radio"
    OTHER = "other"


class LeadSource(Base):
    """Configurable lead source for public lead ingestion and attribution."""

    __tablename__ = "lead_sources"
    __table_args__ = (
        Index("ix_lead_sources_workspace_source_type", "workspace_id", "source_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Basic info
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    public_key: Mapped[str] = mapped_column(
        String(20), unique=True, nullable=False, index=True, default=generate_lead_source_key
    )
    allowed_domains: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    source_type: Mapped[LeadSourceType] = mapped_column(
        SAEnum(
            LeadSourceType,
            native_enum=False,
            create_constraint=False,
            length=50,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=LeadSourceType.OTHER,
    )

    # Post-capture action
    action: Mapped[str] = mapped_column(
        String(50), nullable=False, default="collect"
    )  # collect | auto_text | auto_call | enroll_campaign
    action_config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

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
    workspace: Mapped["Workspace"] = relationship("Workspace")
    campaigns: Mapped[list["LeadSourceCampaign"]] = relationship(
        "LeadSourceCampaign", back_populates="lead_source", cascade="all, delete-orphan"
    )
    spend_entries: Mapped[list["LeadSourceSpendEntry"]] = relationship(
        "LeadSourceSpendEntry", back_populates="lead_source", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<LeadSource(id={self.id}, name={self.name}, "
            f"source_type={self.source_type}, action={self.action})>"
        )


class LeadSourceCampaign(Base):
    """Attribution campaign nested under a lead source."""

    __tablename__ = "lead_source_campaigns"
    __table_args__ = (
        UniqueConstraint(
            "lead_source_id",
            "platform_campaign_id",
            name="uq_lead_source_campaigns_source_platform_id",
        ),
        Index("ix_lead_source_campaigns_workspace_source", "workspace_id", "lead_source_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    lead_source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lead_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Human + provider identity.
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    platform_campaign_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    platform_campaign_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    utm_campaign: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    campaign_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    # Optional campaign flight window.
    started_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    ended_on: Mapped[date | None] = mapped_column(Date, nullable=True)

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
    workspace: Mapped["Workspace"] = relationship("Workspace")
    lead_source: Mapped["LeadSource"] = relationship("LeadSource", back_populates="campaigns")
    spend_entries: Mapped[list["LeadSourceSpendEntry"]] = relationship(
        "LeadSourceSpendEntry", back_populates="lead_source_campaign"
    )

    def __repr__(self) -> str:
        return (
            f"<LeadSourceCampaign(id={self.id}, lead_source_id={self.lead_source_id}, "
            f"name={self.name})>"
        )


class LeadSourceSpendEntry(Base):
    """Manual ad/source spend entered for a source and optional campaign."""

    __tablename__ = "lead_source_spend_entries"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="amount_nonnegative"),
        CheckConstraint("spend_ends_on >= spend_starts_on", name="valid_date_range"),
        Index(
            "ix_lead_source_spend_entries_workspace_dates",
            "workspace_id",
            "spend_starts_on",
            "spend_ends_on",
        ),
        Index(
            "ix_lead_source_spend_entries_source_dates",
            "lead_source_id",
            "spend_starts_on",
            "spend_ends_on",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    lead_source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lead_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    lead_source_campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lead_source_campaigns.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Manual spend range.
    spend_starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    spend_ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

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
    workspace: Mapped["Workspace"] = relationship("Workspace")
    lead_source: Mapped["LeadSource"] = relationship("LeadSource", back_populates="spend_entries")
    lead_source_campaign: Mapped["LeadSourceCampaign | None"] = relationship(
        "LeadSourceCampaign", back_populates="spend_entries"
    )

    def __repr__(self) -> str:
        return (
            f"<LeadSourceSpendEntry(id={self.id}, lead_source_id={self.lead_source_id}, "
            f"amount={self.amount}, range={self.spend_starts_on}..{self.spend_ends_on})>"
        )
