"""Contact model."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.appointment import Appointment
    from app.models.campaign import CampaignContact
    from app.models.conversation import Conversation
    from app.models.message_test import TestContact
    from app.models.tag import ContactTag
    from app.models.workspace import Workspace


class Contact(Base):
    """CRM contact."""

    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Basic info
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Mailing address (for physical cards/mail)
    address_line1: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_line2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address_city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    address_state: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address_zip: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Lifecycle
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="new", index=True
    )  # new, contacted, qualified, converted, lost
    lead_score: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    # Qualification
    is_qualified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    qualification_signals: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Structure: {
    #     "budget": {"detected": bool, "value": str|None, "confidence": float},
    #     "authority": {"detected": bool, "value": str|None, "confidence": float},
    #     "need": {"detected": bool, "value": str|None, "confidence": float},
    #     "timeline": {"detected": bool, "value": str|None, "confidence": float},
    #     "interest_level": str,  # "high", "medium", "low", "unknown"
    #     "pain_points": list[str],
    #     "objections": list[str],
    #     "next_steps": str|None,
    #     "last_analyzed_at": str (ISO datetime),
    #     "conversation_count": int
    # }
    qualified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Organization
    # TODO(tags-migration): Legacy ARRAY(Text) column. Superseded by the
    # normalized Tag / ContactTag tables (see app.models.tag), but still
    # actively read/written by automation_worker, never_booked_worker, and
    # noshow_reengagement_worker for lifecycle marker tags
    # (e.g. "no-show", "noshow-day3-sent", "never-booked-reengaged",
    # "appointment-scheduled"). Migration plan:
    #   1. Port those three workers to use ContactTag rows (create tags
    #      lazily via TagService, query via join instead of
    #      Contact.tags.contains([...])).
    #   2. Backfill: for every distinct value currently in contacts.tags,
    #      upsert a Tag row per workspace and insert matching ContactTag
    #      rows in an alembic data migration.
    #   3. Drop this column (op.drop_column("contacts", "tags")) and remove
    #      this Mapped attribute.
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    important_dates: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Structure: {
    #     "birthday": "1990-03-15",
    #     "anniversary": "2020-06-20",
    #     "custom": [{"label": "Contract Renewal", "date": "2026-08-01"}]
    # }

    # AI Enrichment fields
    website_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    business_intel: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    enrichment_status: Mapped[str | None] = mapped_column(
        String(20), nullable=True, index=True
    )  # pending, enriched, failed, skipped
    enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Appointment tracking
    noshow_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    last_appointment_status: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Source tracking
    source: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # campaign, inbound_call, manual, api
    source_campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Engagement tracking
    last_engaged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    engagement_score: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
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
    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="contacts")
    conversations: Mapped[list["Conversation"]] = relationship(
        "Conversation", back_populates="contact", cascade="all, delete-orphan"
    )
    appointments: Mapped[list["Appointment"]] = relationship(
        "Appointment", back_populates="contact", cascade="all, delete-orphan"
    )
    campaign_contacts: Mapped[list["CampaignContact"]] = relationship(
        "CampaignContact", back_populates="contact", cascade="all, delete-orphan"
    )
    test_contacts: Mapped[list["TestContact"]] = relationship(
        "TestContact", back_populates="contact", cascade="all, delete-orphan"
    )
    contact_tags: Mapped[list["ContactTag"]] = relationship(
        "ContactTag", back_populates="contact", cascade="all, delete-orphan"
    )

    @property
    def full_name(self) -> str:
        """Get full name."""
        if self.last_name:
            return f"{self.first_name} {self.last_name}"
        return self.first_name

    @property
    def has_address(self) -> bool:
        """Check if contact has a complete mailing address."""
        return bool(
            self.address_line1 and self.address_city and self.address_state and self.address_zip
        )

    def __repr__(self) -> str:
        return f"<Contact(id={self.id}, phone={self.phone_number}, status={self.status})>"
