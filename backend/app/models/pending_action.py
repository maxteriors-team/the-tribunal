"""PendingAction model for HITL (Human-In-The-Loop) approval gate."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.user import User
    from app.models.workspace import Workspace


class PendingAction(Base):
    """Queue of AI-proposed actions awaiting human approval.

    Stores actions proposed by AI agents that require human review
    before execution, enabling a Human-In-The-Loop approval workflow.
    """

    __tablename__ = "pending_actions"
    __table_args__ = (
        Index(
            "ix_pending_actions_status_expires_at",
            "status",
            "expires_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Action details
    action_type: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True
    )  # book_appointment, send_sms, enroll_campaign, apply_tag
    action_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )  # {source, conversation_id, contact_id, automation_id}

    # Status workflow
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False, index=True
    )  # pending, approved, rejected, expired, executed, failed
    urgency: Mapped[str] = mapped_column(
        String(20), default="normal", nullable=False
    )  # low, normal, high

    # Review tracking
    reviewed_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    review_channel: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # web, sms, push
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Execution tracking
    executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    execution_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Expiration
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # Notification tracking
    notification_sent: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    notification_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")
    agent: Mapped["Agent"] = relationship("Agent")
    reviewed_by: Mapped["User | None"] = relationship("User")

    def __repr__(self) -> str:
        return f"<PendingAction(id={self.id}, type={self.action_type}, status={self.status})>"
