"""KnowledgeChunk model for hybrid (vector + keyword) knowledge retrieval.

Each row is one embedded slice of a :class:`KnowledgeDocument`. Chunks carry a
``vector(1536)`` embedding for semantic KNN search and a generated ``tsvector``
column (with a GIN index) for keyword search, fused together by
``app.services.knowledge.retrieval_service``.

``workspace_id`` and ``agent_id`` are denormalized from the parent document so
every retrieval query can be scoped to a single tenant + agent with a cheap
indexed predicate, without joining back to ``knowledge_documents``.
"""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.services.ai.embeddings import EMBEDDING_DIM

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.knowledge_document import KnowledgeDocument
    from app.models.workspace import Workspace


class KnowledgeChunk(Base):
    """An embedded, keyword-indexed slice of a knowledge document."""

    __tablename__ = "knowledge_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Position of this chunk within its document (0-based) and the char offsets
    # of the slice in the source text, so callers can cite / re-extract context.
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    # SHA-256 (hex) of the chunk content for dedupe / idempotent re-ingest.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # Semantic arm: OpenAI text-embedding-3-small output (1536 dims, cosine).
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)

    # Keyword arm: generated tsvector derived from ``content``. Persisted +
    # GIN-indexed (see ``__table_args__``) so ts_rank queries stay index-backed.
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', content)", persisted=True),
        nullable=False,
    )

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
        # One chunk per (document, ordinal): makes re-ingest idempotent.
        UniqueConstraint("document_id", "ordinal", name="uq_knowledge_chunks_document_id_ordinal"),
        # GIN index powering the keyword (tsvector @@ / ts_rank) arm.
        Index(
            "ix_knowledge_chunks_search_vector",
            "search_vector",
            postgresql_using="gin",
        ),
    )

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace")
    agent: Mapped["Agent | None"] = relationship("Agent")
    document: Mapped["KnowledgeDocument"] = relationship("KnowledgeDocument")

    def __repr__(self) -> str:
        return f"<KnowledgeChunk(id={self.id}, doc={self.document_id}, ordinal={self.ordinal})>"
