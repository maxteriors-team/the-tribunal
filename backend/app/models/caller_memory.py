"""CallerMemory model — persistent, cross-call conversational memory.

Each row is a short, embedded summary of one completed call with a contact.
Unlike :class:`KnowledgeChunk` (agent-scoped business knowledge), caller
memories are *contact*-scoped: they let a future call recall what was actually
discussed with THIS person on prior calls, not just their structured CRM fields.

The summary carries a ``vector(1536)`` embedding (same OpenAI
``text-embedding-3-small`` space as the knowledge stack) so prior context can be
retrieved either chronologically (most recent first) or semantically (most
relevant to the current topic). Every row is scoped to ``workspace_id`` +
``contact_id`` so one tenant can never read another's caller memory.
"""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.encryption import EncryptedString
from app.db.base import Base
from app.services.ai.embeddings import EMBEDDING_DIM

if TYPE_CHECKING:
    from app.models.contact import Contact
    from app.models.workspace import Workspace


class CallerMemory(Base):
    """A summarized, embedded memory of one completed call with a contact."""

    __tablename__ = "caller_memories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The conversation/message (call) this memory was distilled from. Nullable so
    # a memory survives if the originating message is later pruned, and the
    # message_id powers idempotency (one memory per call).
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Short natural-language recap of what was discussed on the call. This is
    # verbatim customer conversation content, so it is Fernet-encrypted at rest
    # via :class:`EncryptedString`. No lookup hash: recall is chronological
    # (``occurred_at``) or semantic (``embedding`` cosine distance) — nothing
    # filters on the summary text itself.
    summary: Mapped[str] = mapped_column(EncryptedString(), nullable=False)
    # "inbound" | "outbound" — how the call that produced this memory was placed.
    direction: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Semantic arm: OpenAI text-embedding-3-small output (1536 dims, cosine).
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)

    # When the call actually happened (used for chronological recall + recency).
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        # Hot path: list/retrieve a caller's memories newest-first, scoped to the
        # tenant + contact with a single indexed predicate.
        Index(
            "ix_caller_memories_workspace_contact_occurred",
            "workspace_id",
            "contact_id",
            "occurred_at",
            postgresql_ops={"occurred_at": "DESC"},
        ),
    )

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")
    contact: Mapped["Contact"] = relationship("Contact")

    def __repr__(self) -> str:
        return (
            f"<CallerMemory(id={self.id}, contact_id={self.contact_id}, "
            f"occurred_at={self.occurred_at})>"
        )
