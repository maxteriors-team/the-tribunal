"""Lead discovery job model.

A unit of work that scans an external source (Google Places, web scrape, CSV
upload, manual seed) and emits :class:`~app.models.lead_prospect.LeadProspect`
rows. Each job records the source, search parameters, totals, and lifecycle
state so the application layer can resume or retry without re-querying paid
APIs.
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.outbound_mission import OutboundMission
    from app.models.user import User
    from app.models.workspace import Workspace


class DiscoverySourceType(StrEnum):
    """Where a lead discovery job pulls candidate prospects from."""

    GOOGLE_PLACES = "google_places"
    WEB_SCRAPE = "web_scrape"
    CSV_IMPORT = "csv_import"
    MANUAL = "manual"
    API = "api"
    LINKEDIN = "linkedin"
    META_AD_LIBRARY = "meta_ad_library"
    GOOGLE_ADS_TRANSPARENCY = "google_ads_transparency"
    OTHER = "other"


class DiscoveryJobStatus(StrEnum):
    """Lead discovery job lifecycle status."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class LeadDiscoveryJob(Base):
    """A single discovery run that emits lead prospect rows."""

    __tablename__ = "lead_discovery_jobs"
    __table_args__ = (
        Index(
            "ix_lead_discovery_jobs_mission_status",
            "mission_id",
            "status",
        ),
        Index(
            "ix_lead_discovery_jobs_workspace_created_at",
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
    mission_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("outbound_missions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    requested_by_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Source descriptor
    source_type: Mapped[DiscoverySourceType] = mapped_column(
        SAEnum(
            DiscoverySourceType,
            native_enum=False,
            create_constraint=False,
            length=50,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    source_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    # Status
    status: Mapped[DiscoveryJobStatus] = mapped_column(
        SAEnum(
            DiscoveryJobStatus,
            native_enum=False,
            create_constraint=False,
            length=50,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=DiscoveryJobStatus.PENDING,
        index=True,
    )

    # Counters
    requested_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    discovered_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    invalid_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Timing + errors
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

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
    requested_by: Mapped["User | None"] = relationship("User", foreign_keys=[requested_by_id])

    def __repr__(self) -> str:
        return (
            f"<LeadDiscoveryJob(id={self.id}, source={self.source_type}, "
            f"status={self.status}, discovered={self.discovered_count})>"
        )
