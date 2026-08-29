"""Add conversation notes.

Expand-only: creates a dedicated table without modifying existing records.

``Contact.notes`` already exists but is a single overwritable blob with no
author and no history, so two reps on the same account silently clobber each
other. These notes are per-conversation, attributed and timestamped, and carry
synced Quo call summaries alongside what a rep typed.

Revision ID: 20260829_conversation_notes
Revises: 20260828_handoff_images
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260829_conversation_notes"
down_revision: str | Sequence[str] | None = "20260828_handoff_images"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirrors MAX_NOTE_BODY_CHARS * 4 in app.models.conversation_note. The column
# holds Fernet ciphertext, so this bounds storage; the readable plaintext limit
# is enforced in the Pydantic schema.
_MAX_BODY_CIPHERTEXT_CHARS = 20_000


def upgrade() -> None:
    """Create the conversation_notes table."""
    op.create_table(
        "conversation_notes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        # Null for machine-authored notes, and preserved (SET NULL) when the
        # author leaves so the note keeps its place in the timeline.
        sa.Column("author_user_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=20), server_default="human", nullable=False),
        sa.Column("source_ref", sa.String(length=128), nullable=True),
        # EncryptedString persists Fernet ciphertext in an ordinary TEXT column.
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source IN ('human', 'quo_summary')",
            name=op.f("ck_conversation_notes_source"),
        ),
        sa.CheckConstraint(
            f"char_length(body) BETWEEN 1 AND {_MAX_BODY_CIPHERTEXT_CHARS}",
            name=op.f("ck_conversation_notes_body_length"),
        ),
        sa.ForeignKeyConstraint(
            ["author_user_id"],
            ["users.id"],
            name=op.f("fk_conversation_notes_author_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_conversation_notes_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_conversation_notes_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_notes")),
    )
    op.create_index(
        op.f("ix_conversation_notes_author_user_id"),
        "conversation_notes",
        ["author_user_id"],
    )
    op.create_index(
        op.f("ix_conversation_notes_conversation_id"),
        "conversation_notes",
        ["conversation_id"],
    )
    op.create_index(
        op.f("ix_conversation_notes_workspace_id"),
        "conversation_notes",
        ["workspace_id"],
    )
    # Serves the only read path: one conversation's notes, in time order.
    op.create_index(
        "ix_conversation_notes_workspace_conversation_created",
        "conversation_notes",
        ["workspace_id", "conversation_id", "created_at"],
    )
    # One note per synced Quo artefact. Quo retries webhooks, so without this a
    # redelivery appends a duplicate summary to the rep's notes. Partial, so
    # hand-typed notes (source_ref IS NULL) are never constrained.
    op.create_index(
        "uq_conversation_notes_source_ref",
        "conversation_notes",
        ["workspace_id", "source_ref"],
        unique=True,
        postgresql_where=sa.text("source_ref IS NOT NULL"),
    )


def downgrade() -> None:
    """Drop the conversation_notes table.

    Destructive by nature: this table is the only home for rep-authored notes,
    so downgrading discards them. Take a backup first if any exist.
    """
    op.drop_index("uq_conversation_notes_source_ref", table_name="conversation_notes")
    op.drop_index(
        "ix_conversation_notes_workspace_conversation_created",
        table_name="conversation_notes",
    )
    op.drop_index(op.f("ix_conversation_notes_workspace_id"), table_name="conversation_notes")
    op.drop_index(op.f("ix_conversation_notes_conversation_id"), table_name="conversation_notes")
    op.drop_index(op.f("ix_conversation_notes_author_user_id"), table_name="conversation_notes")
    op.drop_table("conversation_notes")
