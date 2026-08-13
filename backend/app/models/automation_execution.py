"""AutomationExecution model — tracks which contacts have been processed per automation."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.automation import Automation
    from app.models.automation_event import AutomationEvent
    from app.models.contact import Contact


class AutomationExecution(Base):
    """Records that a contact was processed by an automation.

    Dedupe is keyed two ways via partial unique indexes:

    * **Polling triggers** (``event_id IS NULL``) are unique per
      (automation, contact) so a contact is processed at most once per
      automation — the original contact-centric behaviour.
    * **Event triggers** (``event_id IS NOT NULL``) are unique per
      (automation, event) so each emitted domain event runs an automation at
      most once, while still allowing the same contact to be processed for
      repeated events (e.g. a deal moving stage twice).

    A ``status`` field lets delayed/scheduled executions carry state across
    poll cycles. Three columns make that resumable rather than merely recorded:
    ``step_index`` (how far the workflow got), ``context`` (the trigger payload,
    which is otherwise an in-memory argument and would be lost across a wait,
    rendering ``{rating}``-style tokens blank on resume), and ``resume_count``
    (the lifetime budget that stops a goto loop hiding behind a wait).
    """

    __tablename__ = "automation_executions"
    __table_args__ = (
        Index(
            "uq_automation_execution_contact",
            "automation_id",
            "contact_id",
            unique=True,
            postgresql_where=text("event_id IS NULL"),
        ),
        Index(
            "uq_automation_execution_event",
            "automation_id",
            "event_id",
            unique=True,
            postgresql_where=text("event_id IS NOT NULL"),
        ),
        Index(
            "ix_automation_executions_status_scheduled_for",
            "status",
            "scheduled_for",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    automation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("automations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # Set for event-triggered executions; NULL for polling-trigger executions.
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("automation_events.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Status: "pending" | "completed" | "failed" | "scheduled"
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", index=True)

    # For delayed actions — worker re-checks executions where this is <= now
    scheduled_for: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # Cursor into ``automations.actions``: the step to run next. Workflows are a
    # flat list precisely so a paused run's position is one integer.
    step_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # Trigger payload ({rating}, {stage}, ...) carried across a wait. Passed as
    # an in-memory dict on the first cycle; persisted here so a resumed step
    # renders the same tokens instead of blanks.
    context: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    # Lifetime resume budget (see runner.MAX_RESUMES). Bounds a goto cycle that
    # passes through a wait and would otherwise resume politely, forever.
    resume_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    # Optional error message
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    automation: Mapped["Automation"] = relationship("Automation", back_populates="executions")
    contact: Mapped["Contact | None"] = relationship("Contact")
    event: Mapped["AutomationEvent | None"] = relationship("AutomationEvent")

    def __repr__(self) -> str:
        return (
            f"<AutomationExecution(automation_id={self.automation_id}, "
            f"contact_id={self.contact_id}, status={self.status})>"
        )
