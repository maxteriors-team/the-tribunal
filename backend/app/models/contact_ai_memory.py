"""Durable, workspace-scoped AI memory for a CRM contact.

``ContactContextSnapshot`` remains the authoritative point-in-time CRM view. These
rows retain concise historical context and claims extracted from prior interactions;
callers must treat both summary and fact values as untrusted, potentially stale data.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.encryption import EncryptedString
from app.db.base import Base
from app.db.tenancy import WorkspaceScoped

if TYPE_CHECKING:
    from app.models.contact import Contact
    from app.models.conversation import Message
    from app.models.workspace import Workspace


class FactSupersessionState(StrEnum):
    """Lifecycle state for a historical memory fact."""

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    INVALIDATED = "invalidated"


class ContactAIMemory(Base, WorkspaceScoped):
    """One current aggregate memory per workspace-scoped contact."""

    __tablename__ = "contact_ai_memories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    contact_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
    )

    # AI-generated free text may contain PII or sensitive customer details.
    summary: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    summary_source_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    summary_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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
        UniqueConstraint(
            "workspace_id",
            "contact_id",
            name="uq_contact_ai_memories_workspace_contact",
        ),
        # Enables the fact table's composite FK to enforce that duplicated tenant
        # columns always identify the same parent memory.
        UniqueConstraint(
            "id",
            "workspace_id",
            "contact_id",
            name="uq_contact_ai_memories_id_workspace_contact",
        ),
        Index(
            "ix_contact_ai_memories_workspace_updated",
            "workspace_id",
            text("updated_at DESC"),
        ),
    )

    workspace: Mapped[Workspace] = relationship("Workspace")
    contact: Mapped[Contact] = relationship("Contact")
    facts: Mapped[list[ContactAIMemoryFact]] = relationship(
        "ContactAIMemoryFact",
        back_populates="memory",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="[ContactAIMemoryFact.memory_id, "
        "ContactAIMemoryFact.workspace_id, ContactAIMemoryFact.contact_id]",
    )

    def __repr__(self) -> str:
        return f"<ContactAIMemory(id={self.id}, contact_id={self.contact_id})>"


class ContactAIMemoryFact(Base, WorkspaceScoped):
    """A provenance-bearing historical claim retained for a contact."""

    __tablename__ = "contact_ai_memory_facts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    memory_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    contact_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    fact_type: Mapped[str] = mapped_column(String(80), nullable=False)
    # Values are untrusted free text and may contain sensitive customer data.
    value: Mapped[str] = mapped_column(EncryptedString(), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)

    provenance_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provenance_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_record_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_record_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    supersession_state: Mapped[str] = mapped_column(
        String(20),
        default=FactSupersessionState.ACTIVE.value,
        nullable=False,
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contact_ai_memory_facts.id", ondelete="SET NULL"),
        nullable=True,
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
        ForeignKeyConstraint(
            ["memory_id", "workspace_id", "contact_id"],
            [
                "contact_ai_memories.id",
                "contact_ai_memories.workspace_id",
                "contact_ai_memories.contact_id",
            ],
            name="fk_contact_ai_memory_facts_scoped_memory",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="confidence",
        ),
        CheckConstraint(
            "supersession_state IN ('active', 'superseded', 'invalidated')",
            name="supersession_state",
        ),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > observed_at",
            name="expiry",
        ),
        Index(
            "ix_contact_ai_memory_facts_workspace_contact_active",
            "workspace_id",
            "contact_id",
            text("observed_at DESC"),
            postgresql_where=text("supersession_state = 'active'"),
        ),
        Index(
            "ix_contact_ai_memory_facts_source",
            "workspace_id",
            "source_record_type",
            "source_record_id",
            "supersession_state",
        ),
        Index(
            "ix_contact_ai_memory_facts_event",
            "workspace_id",
            "contact_id",
            "provenance_event_id",
        ),
        Index(
            "ix_contact_ai_memory_facts_message",
            "provenance_message_id",
        ),
    )

    memory: Mapped[ContactAIMemory] = relationship(
        "ContactAIMemory",
        back_populates="facts",
        foreign_keys=[memory_id, workspace_id, contact_id],
    )
    provenance_message: Mapped[Message | None] = relationship(
        "Message", foreign_keys=[provenance_message_id]
    )
    superseded_by: Mapped[ContactAIMemoryFact | None] = relationship(
        "ContactAIMemoryFact",
        remote_side=[id],
        foreign_keys=[superseded_by_id],
    )

    def __repr__(self) -> str:
        return (
            f"<ContactAIMemoryFact(id={self.id}, type={self.fact_type!r}, "
            f"state={self.supersession_state!r})>"
        )
