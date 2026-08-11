"""Durable private media attached to an inbound conversation message."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.encryption import EncryptedString
from app.db.base import Base

if TYPE_CHECKING:
    from app.models.conversation import Message
    from app.models.workspace import Workspace

MESSAGE_ATTACHMENT_PENDING = "pending"
MESSAGE_ATTACHMENT_PROCESSING = "processing"
MESSAGE_ATTACHMENT_READY = "ready"
MESSAGE_ATTACHMENT_FAILED = "failed"
MESSAGE_ATTACHMENT_STATUSES = (
    MESSAGE_ATTACHMENT_PENDING,
    MESSAGE_ATTACHMENT_PROCESSING,
    MESSAGE_ATTACHMENT_READY,
    MESSAGE_ATTACHMENT_FAILED,
)


class MessageAttachment(Base):
    """A provider media item queued for private object-storage ingestion."""

    __tablename__ = "message_attachments"
    __table_args__ = (
        CheckConstraint(
            f"status IN {MESSAGE_ATTACHMENT_STATUSES!r}",
            name="status",
        ),
        CheckConstraint(
            "provider_position >= 0",
            name="provider_position_nonnegative",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="attempt_count_nonnegative",
        ),
        UniqueConstraint(
            "message_id",
            "provider_position",
            name="uq_message_attachments_message_position",
        ),
        UniqueConstraint(
            "storage_key",
            name="uq_message_attachments_storage_key",
        ),
        Index(
            "ix_message_attachments_queue",
            "status",
            "next_attempt_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider_position: Mapped[int] = mapped_column(Integer, nullable=False)
    source_url: Mapped[str] = mapped_column(EncryptedString(), nullable=False)
    provider_content_type: Mapped[str] = mapped_column(String(127), nullable=False)
    provider_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    provider_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(127), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    status: Mapped[str] = mapped_column(
        String(20),
        default=MESSAGE_ATTACHMENT_PENDING,
        server_default=MESSAGE_ATTACHMENT_PENDING,
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

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

    workspace: Mapped["Workspace"] = relationship("Workspace")
    message: Mapped["Message"] = relationship("Message")
