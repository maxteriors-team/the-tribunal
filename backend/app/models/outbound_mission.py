"""Outbound Mission model.

An outbound mission orchestrates lead discovery, enrichment, and multi-channel
sequenced outreach for a specific objective (book_call, qualify, demo, etc.).
Missions are the top-level container for the Lead Miner feature; they own
:class:`~app.models.lead_discovery_job.LeadDiscoveryJob`,
:class:`~app.models.lead_prospect.LeadProspect`, and
:class:`~app.models.outbound_sequence.OutboundSequenceEnrollment` rows.
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
    from app.models.agent import Agent
    from app.models.offer import Offer
    from app.models.outbound_sequence import OutboundSequence
    from app.models.user import User
    from app.models.workspace import Workspace


class MissionStatus(StrEnum):
    """Outbound mission lifecycle status."""

    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class OutboundMission(Base):
    """Outbound mission: a discovery + enrichment + sequencing run."""

    __tablename__ = "outbound_missions"
    __table_args__ = (
        Index(
            "ix_outbound_missions_workspace_status",
            "workspace_id",
            "status",
        ),
        Index(
            "ix_outbound_missions_workspace_updated_at",
            "workspace_id",
            "updated_at",
            postgresql_ops={"updated_at": "DESC"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    offer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("offers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    default_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    default_sequence_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("outbound_sequences.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Mission details
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    objective: Mapped[str] = mapped_column(
        String(50), nullable=False, default="book_call"
    )  # book_call, qualify, nurture, demo, custom
    status: Mapped[MissionStatus] = mapped_column(
        SAEnum(
            MissionStatus,
            native_enum=False,
            create_constraint=False,
            length=50,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=MissionStatus.DRAFT,
        index=True,
    )

    # Configuration blobs — service layer reads/writes these.
    # ``target_audience``: ICP description (industries, geos, headcount bands).
    # ``discovery_config``: source params, search queries, max prospects/day.
    # ``enrichment_config``: which providers, AI enable flag, min score cutoff.
    # ``sequence_config``: per-mission overrides for the default sequence.
    target_audience: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    discovery_config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    enrichment_config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    sequence_config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    # Sending defaults — used when sequence steps don't override.
    default_from_phone_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    default_from_email: Mapped[str | None] = mapped_column(String(320), nullable=True)

    # Caps + scheduling
    daily_prospect_cap: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    daily_outreach_cap: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    timezone: Mapped[str] = mapped_column(String(50), default="America/New_York", nullable=False)

    # Denormalized stats
    total_prospects_discovered: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_prospects_enriched: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_prospects_contacted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_prospects_replied: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_prospects_qualified: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_contacts_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_appointments_booked: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Lifecycle timestamps
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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
    created_by: Mapped["User | None"] = relationship("User", foreign_keys=[created_by_id])
    offer: Mapped["Offer | None"] = relationship("Offer", foreign_keys=[offer_id])
    default_agent: Mapped["Agent | None"] = relationship("Agent", foreign_keys=[default_agent_id])
    default_sequence: Mapped["OutboundSequence | None"] = relationship(
        "OutboundSequence", foreign_keys=[default_sequence_id]
    )

    def __repr__(self) -> str:
        return (
            f"<OutboundMission(id={self.id}, name={self.name}, "
            f"status={self.status}, objective={self.objective})>"
        )
