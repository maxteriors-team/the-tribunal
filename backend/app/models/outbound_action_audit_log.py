"""Immutable outbound action audit log model."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.campaign import Campaign
    from app.models.contact import Contact
    from app.models.conversation import Message
    from app.models.pending_action import PendingAction
    from app.models.user import User
    from app.models.workspace import Workspace


class OutboundActionAuditLog(Base):
    """Append-only audit record for AI and campaign outbound actions."""

    __tablename__ = "outbound_action_audit_logs"
    __table_args__ = (
        Index("ix_outbound_action_audit_workspace_created_at", "workspace_id", "created_at"),
        Index("ix_outbound_action_audit_pending_action_id", "pending_action_id"),
        Index("ix_outbound_action_audit_campaign_id", "campaign_id"),
        Index("ix_outbound_action_audit_contact_id", "contact_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    pending_action_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pending_actions.id", ondelete="SET NULL"), nullable=True
    )
    action_type: Mapped[str] = mapped_column(String(100), nullable=False)
    action_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    compliance_result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    decision: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    contact_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    workspace: Mapped["Workspace"] = relationship("Workspace")
    agent: Mapped["Agent | None"] = relationship("Agent")
    pending_action: Mapped["PendingAction | None"] = relationship("PendingAction")
    actor_user: Mapped["User | None"] = relationship("User")
    contact: Mapped["Contact | None"] = relationship("Contact")
    campaign: Mapped["Campaign | None"] = relationship("Campaign")
    message: Mapped["Message | None"] = relationship("Message")

    def __repr__(self) -> str:
        return (
            f"<OutboundActionAuditLog(id={self.id}, action_type={self.action_type}, "
            f"decision={self.decision})>"
        )
