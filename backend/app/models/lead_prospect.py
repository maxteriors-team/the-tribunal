"""Lead prospect and enrichment-result models.

A :class:`LeadProspect` is a pre-contact lead candidate discovered by an
outbound mission. Unlike :class:`~app.models.contact.Contact` — which requires a
phone number — a prospect can be partial-identity: phone-only, email-only,
website-only, or owner-name-only. Once a prospect produces real engagement
(reply, qualification) the application layer promotes it into a Contact via
``lead_prospects.contact_id``.

:class:`LeadEnrichmentResult` is an append-only audit row: one per provider
call against a prospect. It captures the request, response, normalized
extracted fields, and the score delta the provider produced.
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.encryption import EncryptedString, LookupHash
from app.db.base import Base

if TYPE_CHECKING:
    from app.models.contact import Contact
    from app.models.lead_discovery_job import LeadDiscoveryJob
    from app.models.outbound_mission import OutboundMission
    from app.models.outbound_sequence import (
        OutboundSequenceEnrollment,
        OutboundSequenceStepAttempt,
    )
    from app.models.workspace import Workspace


class ProspectIdentityKind(StrEnum):
    """Primary identity facet for a prospect.

    Used to route enrichment + dedupe behaviour. ``MULTI`` means more than one
    identifier is populated (e.g. phone + email + website).
    """

    PHONE = "phone"
    EMAIL = "email"
    WEBSITE = "website"
    OWNER_NAME = "owner_name"
    MULTI = "multi"


class ProspectStatus(StrEnum):
    """Lead prospect lifecycle status."""

    NEW = "new"
    ENRICHING = "enriching"
    ENRICHED = "enriched"
    QUEUED = "queued"
    CONTACTED = "contacted"
    REPLIED = "replied"
    QUALIFIED = "qualified"
    CONVERTED = "converted"
    SUPPRESSED = "suppressed"
    ARCHIVED = "archived"


class EnrichmentProvider(StrEnum):
    """Lead enrichment provider identifier."""

    GOOGLE_PLACES = "google_places"
    WEBSITE_SCRAPER = "website_scraper"
    AI_CONTENT_ANALYZER = "ai_content_analyzer"
    LINKEDIN_LOOKUP = "linkedin_lookup"
    EMAIL_LOOKUP = "email_lookup"
    PHONE_LOOKUP = "phone_lookup"
    MANUAL = "manual"
    OTHER = "other"


class EnrichmentResultStatus(StrEnum):
    """Outcome status of a single enrichment provider call."""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


class LeadProspect(Base):
    """Partial-identity lead candidate produced by a discovery job."""

    __tablename__ = "lead_prospects"
    __table_args__ = (
        # Workspace-scoped upsert key. Application layer computes the dedupe
        # key from the available identifiers; rows without a key are allowed
        # (Postgres treats NULL as distinct in a unique constraint).
        UniqueConstraint(
            "workspace_id",
            "dedupe_key",
            name="uq_lead_prospects_workspace_dedupe_key",
        ),
        Index(
            "ix_lead_prospects_workspace_status",
            "workspace_id",
            "status",
        ),
        Index(
            "ix_lead_prospects_workspace_source",
            "workspace_id",
            "source_type",
        ),
        Index(
            "ix_lead_prospects_workspace_score",
            "workspace_id",
            "lead_score",
            postgresql_ops={"lead_score": "DESC"},
        ),
        Index(
            "ix_lead_prospects_mission_status",
            "mission_id",
            "status",
        ),
        Index(
            "ix_lead_prospects_source_external_id",
            "source_type",
            "source_external_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mission_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("outbound_missions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    discovery_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lead_discovery_jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Set when the prospect is promoted to a real Contact row.
    contact_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("contacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Identity facet that drives enrichment routing + dedupe.
    identity_kind: Mapped[ProspectIdentityKind] = mapped_column(
        SAEnum(
            ProspectIdentityKind,
            native_enum=False,
            create_constraint=False,
            length=50,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=ProspectIdentityKind.MULTI,
    )

    # Personal identity — all nullable.
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Channel identifiers — encrypted at rest, lookup hashes for indexes.
    email: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    email_hash: Mapped[str | None] = mapped_column(LookupHash(), nullable=True, index=True)
    phone_number: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    phone_hash: Mapped[str | None] = mapped_column(LookupHash(), nullable=True, index=True)

    # Business / web — plaintext (public-ish info).
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    website_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    website_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    website_host_hash: Mapped[str | None] = mapped_column(
        LookupHash(), nullable=True, index=True
    )
    linkedin_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # blake2b(normalized owner name) — lets us find duplicate prospects across
    # discovery runs when only the owner's name is known.
    owner_name_hash: Mapped[str | None] = mapped_column(LookupHash(), nullable=True, index=True)

    # Location
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    region: Mapped[str | None] = mapped_column(String(100), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    location_label: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Source provenance. ``source_type`` mirrors ``DiscoverySourceType`` values
    # but is stored as plain text so newly-added sources can land on prospects
    # without an ORM enum migration.
    source_type: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    source_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)

    # Dedupe + scoring
    dedupe_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lead_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    qualification_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Status
    status: Mapped[ProspectStatus] = mapped_column(
        SAEnum(
            ProspectStatus,
            native_enum=False,
            create_constraint=False,
            length=50,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=ProspectStatus.NEW,
        index=True,
    )
    suppression_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Stats
    enrichment_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_enriched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_contacted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_replied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reply_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bounce_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Audit timestamps
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Standard timestamps
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
    mission: Mapped["OutboundMission | None"] = relationship(
        "OutboundMission", foreign_keys=[mission_id]
    )
    discovery_job: Mapped["LeadDiscoveryJob | None"] = relationship(
        "LeadDiscoveryJob", foreign_keys=[discovery_job_id]
    )
    contact: Mapped["Contact | None"] = relationship("Contact", foreign_keys=[contact_id])
    enrichment_results: Mapped[list["LeadEnrichmentResult"]] = relationship(
        "LeadEnrichmentResult",
        back_populates="prospect",
        cascade="all, delete-orphan",
        order_by="LeadEnrichmentResult.created_at",
    )
    sequence_enrollments: Mapped[list["OutboundSequenceEnrollment"]] = relationship(
        "OutboundSequenceEnrollment",
        back_populates="prospect",
        cascade="all, delete-orphan",
    )
    sequence_step_attempts: Mapped[list["OutboundSequenceStepAttempt"]] = relationship(
        "OutboundSequenceStepAttempt",
        back_populates="prospect",
        cascade="all, delete-orphan",
    )

    # Helper booleans — mirror Contact.has_address shape.
    @property
    def has_phone(self) -> bool:
        """Whether the prospect carries a phone identifier."""
        return self.phone_hash is not None

    @property
    def has_email(self) -> bool:
        """Whether the prospect carries an email identifier."""
        return self.email_hash is not None

    @property
    def has_website(self) -> bool:
        """Whether the prospect carries a website identifier."""
        return bool(self.website_url or self.website_host or self.website_host_hash)

    @property
    def has_owner_name(self) -> bool:
        """Whether the prospect carries an owner-name identifier."""
        return bool(self.full_name or self.first_name or self.last_name or self.owner_name_hash)

    @property
    def is_promoted(self) -> bool:
        """Whether the prospect has been promoted to a Contact row."""
        return self.contact_id is not None

    def __repr__(self) -> str:
        return (
            f"<LeadProspect(id={self.id}, status={self.status}, "
            f"identity_kind={self.identity_kind}, score={self.lead_score})>"
        )


class LeadEnrichmentResult(Base):
    """Append-only audit record for a single enrichment provider call."""

    __tablename__ = "lead_enrichment_results"
    __table_args__ = (
        Index(
            "ix_lead_enrichment_results_provider_status",
            "provider",
            "status",
        ),
        Index(
            "ix_lead_enrichment_results_workspace_created_at",
            "workspace_id",
            "created_at",
            postgresql_ops={"created_at": "DESC"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    prospect_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lead_prospects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mission_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("outbound_missions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    provider: Mapped[EnrichmentProvider] = mapped_column(
        SAEnum(
            EnrichmentProvider,
            native_enum=False,
            create_constraint=False,
            length=50,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    status: Mapped[EnrichmentResultStatus] = mapped_column(
        SAEnum(
            EnrichmentResultStatus,
            native_enum=False,
            create_constraint=False,
            length=50,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )

    request_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    response_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    extracted: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    score_delta: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    cost_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Immutable rows — no updated_at.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")
    prospect: Mapped["LeadProspect"] = relationship(
        "LeadProspect", back_populates="enrichment_results"
    )
    mission: Mapped["OutboundMission | None"] = relationship(
        "OutboundMission", foreign_keys=[mission_id]
    )

    def __repr__(self) -> str:
        return (
            f"<LeadEnrichmentResult(id={self.id}, prospect={self.prospect_id}, "
            f"provider={self.provider}, status={self.status})>"
        )
