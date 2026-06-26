"""Contact model."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    event,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.encryption import EncryptedString, LookupHash, hash_phone, hash_value
from app.db.base import Base

if TYPE_CHECKING:
    from app.models.appointment import Appointment
    from app.models.campaign import CampaignContact
    from app.models.conversation import Conversation
    from app.models.lead_source import LeadSource, LeadSourceCampaign
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
    # PII at rest — ``email`` and ``phone_number`` are Fernet-encrypted via
    # :class:`EncryptedString`. Their sibling ``*_hash`` columns hold the
    # BLAKE2b-keyed deterministic hash and carry the index used for
    # equality lookups. Always write both together via
    # :func:`app.core.encryption.hash_value`.
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    email: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    email_hash: Mapped[str | None] = mapped_column(LookupHash(), nullable=True, index=True)
    phone_number: Mapped[str] = mapped_column(EncryptedString(), nullable=False)
    phone_hash: Mapped[str] = mapped_column(LookupHash(), nullable=False, index=True)
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Optional profile/company image URL. Non-PII — stored as plain text since
    # the URL itself (Gravatar hash, uploaded asset URL) is not sensitive.
    avatar_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # Mailing address (PII — Fernet-encrypted, no lookup hash needed)
    address_line1: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    address_line2: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    address_city: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    address_state: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    address_zip: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)

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

    # Structured lead attribution. These fields preserve the first-known touch
    # while allowing the latest touch to change as a lead returns through ads,
    # organic visits, or phone/radio tracking numbers.
    first_touch_lead_source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lead_sources.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    first_touch_lead_source_campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lead_source_campaigns.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    first_touch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latest_touch_lead_source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lead_sources.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    latest_touch_lead_source_campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lead_source_campaigns.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    latest_touch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attribution_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    utm_source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    utm_medium: Mapped[str | None] = mapped_column(String(255), nullable=True)
    utm_campaign: Mapped[str | None] = mapped_column(String(255), nullable=True)
    utm_content: Mapped[str | None] = mapped_column(String(255), nullable=True)
    utm_term: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gclid: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fbclid: Mapped[str | None] = mapped_column(String(255), nullable=True)
    landing_page: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    referrer: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    # SMS consent tracking
    sms_consent_status: Mapped[str] = mapped_column(
        String(50), default="unknown", server_default="unknown", nullable=False, index=True
    )
    sms_consent_source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sms_consent_collected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sms_consent_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

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
    first_touch_lead_source: Mapped["LeadSource | None"] = relationship(
        "LeadSource", foreign_keys=[first_touch_lead_source_id]
    )
    first_touch_lead_source_campaign: Mapped["LeadSourceCampaign | None"] = relationship(
        "LeadSourceCampaign", foreign_keys=[first_touch_lead_source_campaign_id]
    )
    latest_touch_lead_source: Mapped["LeadSource | None"] = relationship(
        "LeadSource", foreign_keys=[latest_touch_lead_source_id]
    )
    latest_touch_lead_source_campaign: Mapped["LeadSourceCampaign | None"] = relationship(
        "LeadSourceCampaign", foreign_keys=[latest_touch_lead_source_campaign_id]
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
        return f"<Contact(id={self.id}, phone_hash={self.phone_hash[:8]}..., status={self.status})>"


def _sync_contact_lookup_hashes(_mapper: object, _connection: object, target: Contact) -> None:
    """Keep encrypted contact lookup hashes in sync for all write paths."""
    target.email_hash = hash_value(target.email) if target.email else None
    if target.phone_number:
        target.phone_hash = hash_phone(target.phone_number)


event.listen(Contact, "before_insert", _sync_contact_lookup_hashes)
event.listen(Contact, "before_update", _sync_contact_lookup_hashes)
