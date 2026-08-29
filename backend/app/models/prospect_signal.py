"""Normalized, queryable buying-signal model for lead prospects.

A :class:`ProspectSignal` is a single, typed buying signal attached to a
:class:`~app.models.lead_prospect.LeadProspect` — e.g. "running ads",
"ad/analytics tech installed", "actively hiring". Unlike the freeform
``LeadProspect.signals``/``evidence`` JSONB (kept for outreach copy), these rows
exist so the people-search API can **filter and rank in SQL** by signal type and
strength.

One row per ``(workspace_id, prospect_id, signal_type)`` — the aggregator
upserts the latest observation. The rich, outreach-ready blob still lands on the
prospect's ``evidence`` column; ``payload`` here keeps the structured facts that
back the ``strength`` score.
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
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.tenancy import WorkspaceScoped

if TYPE_CHECKING:
    from app.models.lead_prospect import LeadProspect
    from app.models.workspace import Workspace


class ProspectSignalType(StrEnum):
    """Canonical buying-signal types a prospect can carry.

    Stored as plain text (non-native enum) so new signal providers can land
    rows without an ORM enum migration.
    """

    RUNNING_ADS = "running_ads"
    AD_TECH = "ad_tech"
    HIRING = "hiring"
    FUNDING = "funding"


class ProspectSignalStatus(StrEnum):
    """Lifecycle of a single observed signal."""

    ACTIVE = "active"
    STALE = "stale"
    DISMISSED = "dismissed"


class ProspectSignal(Base, WorkspaceScoped):
    """One typed, queryable buying signal attached to a prospect."""

    __tablename__ = "prospect_signals"
    __table_args__ = (
        # One live row per signal type per prospect; the aggregator upserts.
        UniqueConstraint(
            "workspace_id",
            "prospect_id",
            "signal_type",
            name="uq_prospect_signals_workspace_prospect_type",
        ),
        # Drives the people-search filter/sort: by type, strongest first.
        Index(
            "ix_prospect_signals_workspace_type_strength",
            "workspace_id",
            "signal_type",
            "strength",
            postgresql_ops={"strength": "DESC"},
        ),
        Index(
            "ix_prospect_signals_prospect",
            "prospect_id",
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
    )

    # Signal descriptor. ``signal_type`` mirrors ``ProspectSignalType`` values
    # but is stored as plain text so new providers don't require a migration.
    signal_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # Normalized 0..100 strength used for ranking + filtering.
    strength: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[ProspectSignalStatus] = mapped_column(
        SAEnum(
            ProspectSignalStatus,
            native_enum=False,
            create_constraint=False,
            length=20,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=ProspectSignalStatus.ACTIVE,
    )
    # Where the signal came from (provider key, e.g. "ad_library", "website").
    source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Structured facts backing the strength score (counts, summaries, links).
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
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
    prospect: Mapped["LeadProspect"] = relationship(
        "LeadProspect", back_populates="prospect_signals"
    )

    def __repr__(self) -> str:
        return (
            f"<ProspectSignal(id={self.id}, prospect={self.prospect_id}, "
            f"type={self.signal_type}, strength={self.strength})>"
        )
