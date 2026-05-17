"""Automation model."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.automation_execution import AutomationExecution
    from app.models.workspace import Workspace


class Automation(Base):
    """Workflow automation configuration."""

    __tablename__ = "automations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Basic info
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Trigger configuration
    trigger_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="event"
    )  # event, schedule, condition
    trigger_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, nullable=False
    )  # Stores trigger-specific details

    # Actions to perform
    actions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, nullable=False
    )  # Array of action objects [{type, config}, ...]

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Execution tracking
    last_triggered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Timestamp of the last time the worker evaluated this automation's trigger.
    # Used to bound contact queries to "updated since last_evaluated_at".
    last_evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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
    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="automations")
    executions: Mapped[list["AutomationExecution"]] = relationship(
        "AutomationExecution",
        back_populates="automation",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Automation(id={self.id}, name={self.name}, trigger={self.trigger_type})>"
