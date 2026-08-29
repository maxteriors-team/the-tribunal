"""AutomationEvent model — durable queue of domain events for automations.

Event-based automation triggers (``review_received``, ``opportunity_created``,
``deal_stage_changed``, ``missed_call``, ``roleplay_completed``,
``knowledge_document_uploaded`` …) are emitted from the services where those
things actually happen and persisted here. The automation worker drains pending
rows each poll cycle, matches them to active automations whose ``trigger_type``
equals the event type, and runs the automation's actions.

Persisting events (rather than evaluating them inline) keeps emission cheap and
crash-safe: the producing transaction either commits the event with its source
row or not at all, and the worker owns retry/back-off + the approval gate.
"""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.tenancy import WorkspaceScoped

if TYPE_CHECKING:
    from app.models.contact import Contact
    from app.models.workspace import Workspace

# Lifecycle states for an event row.
EVENT_STATUS_PENDING = "pending"
EVENT_STATUS_PROCESSED = "processed"
EVENT_STATUS_FAILED = "failed"


class AutomationEvent(Base, WorkspaceScoped):
    """A domain event awaiting (or having completed) automation evaluation."""

    __tablename__ = "automation_events"
    __table_args__ = (
        # Worker drains pending rows oldest-first.
        Index("ix_automation_events_status_created", "status", "created_at"),
        # Emitters check for matching active automations by workspace + type.
        Index("ix_automation_events_workspace_type", "workspace_id", "event_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # The trigger identifier this event maps to (e.g. "review_received").
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # Many events are about a specific contact; some (roleplay, knowledge) are not.
    contact_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("contacts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Event-specific metadata (rating, stage names, opportunity_id, …). Used for
    # template rendering and future conditional matching.
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    # "pending" | "processed" | "failed"
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=EVENT_STATUS_PENDING, index=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")
    contact: Mapped["Contact | None"] = relationship("Contact")

    def __repr__(self) -> str:
        return (
            f"<AutomationEvent(id={self.id}, type={self.event_type}, "
            f"status={self.status}, contact_id={self.contact_id})>"
        )
