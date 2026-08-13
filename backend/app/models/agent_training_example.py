"""Human-approved examples that guide an AI agent's future SMS replies."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.encryption import EncryptedString
from app.db.base import Base

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.conversation import Conversation, Message
    from app.models.user import User
    from app.models.workspace import Workspace


class AgentTrainingExample(Base):
    """An operator-approved correction scoped to one workspace and agent."""

    __tablename__ = "agent_training_examples"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    # CRM history may be pruned without deleting the reusable lesson.
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # These fields contain customer conversation text and are encrypted at rest.
    customer_message: Mapped[str] = mapped_column(EncryptedString(), nullable=False)
    ai_response: Mapped[str] = mapped_column(EncryptedString(), nullable=False)
    ideal_response: Mapped[str] = mapped_column(EncryptedString(), nullable=False)
    operator_note: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("source_message_id", name="uq_agent_training_examples_source_message_id"),
        Index(
            "ix_agent_training_examples_workspace_agent_active_created",
            "workspace_id",
            "agent_id",
            "is_active",
            "created_at",
        ),
    )

    workspace: Mapped["Workspace"] = relationship("Workspace")
    agent: Mapped["Agent"] = relationship("Agent", back_populates="training_examples")
    conversation: Mapped["Conversation | None"] = relationship("Conversation")
    source_message: Mapped["Message | None"] = relationship("Message")
    created_by_user: Mapped["User | None"] = relationship("User")

    def __repr__(self) -> str:
        return f"<AgentTrainingExample(id={self.id}, agent_id={self.agent_id})>"
