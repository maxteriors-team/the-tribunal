"""Durable idempotency claims for manual Quo text sends."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.tenancy import WorkspaceScoped

if TYPE_CHECKING:
    from app.models.conversation import Conversation, Message
    from app.models.workspace import Workspace


class QuoSendAttemptState(StrEnum):
    """Provider acceptance certainty for a single client request."""

    SENDING = "sending"
    ACCEPTED = "accepted"
    FAILED = "failed"
    UNKNOWN = "unknown"


class QuoSendAttempt(Base, WorkspaceScoped):
    """One network-send claim per workspace and client request UUID."""

    __tablename__ = "quo_send_attempts"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "client_request_id",
            name="uq_quo_send_attempts_workspace_request",
        ),
        UniqueConstraint("message_id", name="uq_quo_send_attempts_message"),
        CheckConstraint(
            "state IN ('sending', 'accepted', 'failed', 'unknown')",
            name="state",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    client_request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    state: Mapped[QuoSendAttemptState] = mapped_column(
        SAEnum(
            QuoSendAttemptState,
            native_enum=False,
            create_constraint=False,
            length=20,
            values_callable=lambda enum: [member.value for member in enum],
        ),
        nullable=False,
        default=QuoSendAttemptState.SENDING,
        server_default=QuoSendAttemptState.SENDING.value,
    )
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    error_class: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    workspace: Mapped["Workspace"] = relationship("Workspace")
    conversation: Mapped["Conversation"] = relationship("Conversation")
    message: Mapped["Message | None"] = relationship("Message")
