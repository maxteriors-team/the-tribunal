"""Ad-library advertiser model.

An :class:`AdAdvertiser` is one advertiser tracked across an ad library (a Meta
Page or a Google Ads Transparency advertiser/domain). It is the unit the signal
engine scores: we watch its ads over time to detect the ICP — advertisers who
run consistently but never iterate creatives (long-running same ads, few
distinct creatives, low refresh cadence).

Advertisers are workspace-scoped and keyed by ``(workspace_id, platform,
advertiser_key)`` where ``advertiser_key`` is the normalized ``page_id`` (Meta)
or ``domain`` (Google). Each carries the computed signal columns + an
``opportunity_score`` so the API can rank "consistent but not testing"
advertisers without recomputation.

PII note: traced emails/phones are **not** stored here. The advertiser links to
a :class:`~app.models.lead_prospect.LeadProspect` (encrypted at rest) once
contact tracing succeeds; only public web identifiers live on this row.
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
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

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.ad_creative import AdCreative
    from app.models.lead_discovery_job import LeadDiscoveryJob
    from app.models.lead_prospect import LeadProspect
    from app.models.workspace import Workspace


class AdPlatform(StrEnum):
    """Which public ad library an advertiser was discovered in."""

    META = "meta"
    GOOGLE = "google"


class AdAdvertiser(Base):
    """One advertiser tracked across an ad library, with computed ad signals."""

    __tablename__ = "ad_advertisers"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "platform",
            "advertiser_key",
            name="uq_ad_advertisers_workspace_platform_key",
        ),
        Index(
            "ix_ad_advertisers_workspace_score",
            "workspace_id",
            "opportunity_score",
            postgresql_ops={"opportunity_score": "DESC"},
        ),
        Index(
            "ix_ad_advertisers_workspace_platform",
            "workspace_id",
            "platform",
        ),
        Index(
            "ix_ad_advertisers_workspace_last_scanned",
            "workspace_id",
            "last_scanned_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Discovery / monitor job that most recently touched this advertiser.
    discovery_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lead_discovery_jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Set once the advertiser is turned into an outbound prospect.
    prospect_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lead_prospects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Identity
    platform: Mapped[AdPlatform] = mapped_column(
        SAEnum(
            AdPlatform,
            native_enum=False,
            create_constraint=False,
            length=20,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    # Normalized dedupe key: page_id (Meta) or registrable domain (Google).
    advertiser_key: Mapped[str] = mapped_column(String(255), nullable=False)
    page_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    advertiser_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    page_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    website_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    website_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)

    # Lifecycle of the advertiser within tracking.
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Whether the advertiser currently has at least one active ad.
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # --- Computed signal columns (see services/ad_intelligence/signals.py) ---
    signal_window_days: Mapped[int] = mapped_column(Integer, default=365, nullable=False)
    total_ad_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active_ad_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    distinct_creative_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active_creative_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    longest_running_active_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # New distinct creatives introduced per 30 days over the window.
    creative_refresh_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # Fraction of weeks in the window with >= 1 active ad (0..1).
    continuity_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # Weighted 0..100 opportunity score; high = consistent + stale + no testing.
    opportunity_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Context blobs.
    platform_spread: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    media_mix: Mapped[dict[str, int]] = mapped_column(JSONB, default=dict, nullable=False)
    reasons: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    signals: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    # Denormalized "the ad we'd reference" for personalized outreach. Lets a
    # message say e.g. "saw your ad running since March about <offer>" without
    # joining creatives. Shape (see signals.py ``representative_creative``):
    # {ad_external_id, body_snippet, link_caption, link_url, snapshot_url,
    #  media_type, running_days, delivery_start_time}.
    example_creative: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Whether contact tracing has resolved a usable web/contact identifier.
    contact_traced: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Provenance / audit
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

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
    discovery_job: Mapped["LeadDiscoveryJob | None"] = relationship(
        "LeadDiscoveryJob", foreign_keys=[discovery_job_id]
    )
    prospect: Mapped["LeadProspect | None"] = relationship(
        "LeadProspect", foreign_keys=[prospect_id]
    )
    creatives: Mapped[list["AdCreative"]] = relationship(
        "AdCreative",
        back_populates="advertiser",
        cascade="all, delete-orphan",
        order_by="AdCreative.ad_delivery_start_time",
    )

    @property
    def is_promoted(self) -> bool:
        """Whether the advertiser has been turned into a prospect."""
        return self.prospect_id is not None

    def __repr__(self) -> str:
        return (
            f"<AdAdvertiser(id={self.id}, platform={self.platform}, "
            f"key={self.advertiser_key}, score={self.opportunity_score})>"
        )
