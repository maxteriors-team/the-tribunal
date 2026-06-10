"""Ad-library creative model.

An :class:`AdCreative` is one ad (one creative delivery) observed for an
:class:`~app.models.ad_advertiser.AdAdvertiser`. We track each ad over time so
the signal engine can compute how long the same creative has been running, how
many *distinct* creatives an advertiser uses, and how often they refresh — the
inputs to the "consistent but not testing" ICP signal.

Creatives are keyed by ``(advertiser_id, ad_external_id)`` so re-scans are
idempotent: a re-query of the same ad updates delivery stop time / active flag
and ``last_seen_at`` instead of inserting a duplicate. ``creative_hash`` is a
normalized fingerprint of body + link + media so we can collapse the same
creative re-published under different ad IDs when counting *distinct* creatives.
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
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
    from app.models.ad_advertiser import AdAdvertiser
    from app.models.workspace import Workspace


class AdMediaType(StrEnum):
    """Coarse media classification of a creative."""

    IMAGE = "image"
    VIDEO = "video"
    CAROUSEL = "carousel"
    TEXT = "text"
    UNKNOWN = "unknown"


class AdCreative(Base):
    """One ad/creative observed for an advertiser, tracked across scans."""

    __tablename__ = "ad_creatives"
    __table_args__ = (
        UniqueConstraint(
            "advertiser_id",
            "ad_external_id",
            name="uq_ad_creatives_advertiser_ad_external_id",
        ),
        Index(
            "ix_ad_creatives_advertiser_active",
            "advertiser_id",
            "is_active",
        ),
        Index(
            "ix_ad_creatives_advertiser_hash",
            "advertiser_id",
            "creative_hash",
        ),
        Index(
            "ix_ad_creatives_workspace_created_at",
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
    advertiser_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ad_advertisers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Provider-side identifier for the ad (Meta ``id`` / ad archive id).
    ad_external_id: Mapped[str] = mapped_column(String(255), nullable=False)

    # Normalized fingerprint of body + link + media for distinct-creative dedupe.
    creative_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Creative content (public ad copy — not PII).
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    link_caption: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    link_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    link_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cta_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Token-embedded snapshot URL (render in a headless browser). NEVER log it.
    snapshot_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    media_type: Mapped[AdMediaType] = mapped_column(
        SAEnum(
            AdMediaType,
            native_enum=False,
            create_constraint=False,
            length=20,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=AdMediaType.UNKNOWN,
    )
    platforms: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)

    # Delivery window from the ad library.
    ad_delivery_start_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ad_delivery_stop_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # When our scans first/last observed this ad (for refresh-cadence math).
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

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
    advertiser: Mapped["AdAdvertiser"] = relationship("AdAdvertiser", back_populates="creatives")

    def __repr__(self) -> str:
        return (
            f"<AdCreative(id={self.id}, ad_external_id={self.ad_external_id}, "
            f"active={self.is_active}, media={self.media_type})>"
        )
