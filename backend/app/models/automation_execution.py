"""AutomationExecution model — tracks which contacts have been processed per automation."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.automation import Automation
    from app.models.contact import Contact


class AutomationExecution(Base):
    """Records that a contact was processed by an automation.

    The unique constraint on (automation_id, contact_id) prevents the worker
    from re-executing the same automation on the same contact.  A ``status``
    field lets delayed/scheduled executions carry state across poll cycles.
    """

    __tablename__ = "automation_executions"
    __table_args__ = (
        UniqueConstraint(
            "automation_id",
            "contact_id",
            name="uq_automation_execution",
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
    contact_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Status: "pending" | "completed" | "failed" | "scheduled"
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", index=True)

    # For delayed actions — worker re-checks executions where this is <= now
    scheduled_for: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
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
    contact: Mapped["Contact"] = relationship("Contact")

    def __repr__(self) -> str:
        return (
            f"<AutomationExecution(automation_id={self.automation_id}, "
            f"contact_id={self.contact_id}, status={self.status})>"
        )
