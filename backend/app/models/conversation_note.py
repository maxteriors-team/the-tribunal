"""Human- and AI-authored notes kept alongside a conversation."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.encryption import EncryptedString
from app.db.base import Base
from app.db.tenancy import WorkspaceScoped

# Long enough for a full Quo call summary plus its next steps, short enough that
# a single note cannot be used to stash unbounded data in an encrypted column.
MAX_NOTE_BODY_CHARS = 5_000

NOTE_SOURCE_HUMAN = "human"
NOTE_SOURCE_QUO_SUMMARY = "quo_summary"
NOTE_SOURCES = (NOTE_SOURCE_HUMAN, NOTE_SOURCE_QUO_SUMMARY)


class ConversationNote(Base, WorkspaceScoped):
    """One note on a conversation, written by a rep or synced from Quo.

    Distinct from ``Contact.notes``, which is a single overwritable blob with no
    author and no history: reps need to see who observed what, and when, without
    clobbering each other mid-call.
    """

    __tablename__ = "conversation_notes"
    __table_args__ = (
        # The metadata naming convention prepends ``ck_<table>_``, so these are
        # named bare to avoid emitting ``ck_conversation_notes_ck_...``.
        CheckConstraint(
            "source IN ('human', 'quo_summary')",
            name="source",
        ),
        CheckConstraint(
            f"char_length(body) BETWEEN 1 AND {MAX_NOTE_BODY_CHARS * 4}",
            # Bound the ciphertext, not the plaintext: `body` is encrypted at
            # rest, so this is a storage guard. Plaintext length is enforced in
            # the schema, where the real value is visible.
            name="body_length",
        ),
        # Notes are always read as "this conversation's notes, newest first".
        Index(
            "ix_conversation_notes_workspace_conversation_created",
            "workspace_id",
            "conversation_id",
            "created_at",
        ),
        # One note per synced Quo artefact. Quo retries webhooks, and the voice
        # upsert is keyed on the same call id, so without this a redelivery
        # appends a duplicate summary to the rep's notes.
        Index(
            "uq_conversation_notes_source_ref",
            "workspace_id",
            "source_ref",
            unique=True,
            postgresql_where=("source_ref IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Null for machine-authored notes (Quo summaries), and retained when the
    # author leaves the workspace so the note keeps its timeline meaning.
    author_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default=NOTE_SOURCE_HUMAN, server_default=NOTE_SOURCE_HUMAN
    )
    # Provider-side identifier this note was synced from (the Quo call id).
    # Null for anything a human typed.
    source_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Notes describe customers by name, situation and property, so they are
    # customer PII and stay Fernet-encrypted like conversation bodies.
    body: Mapped[str] = mapped_column(EncryptedString(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
