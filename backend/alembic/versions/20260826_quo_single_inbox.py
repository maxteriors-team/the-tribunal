"""Add durable Quo send claims and provider-scoped message identity.

Revision ID: 20260826_quo_inbox
Revises: 20260826_quo_voice
Create Date: 2026-08-26

Expand-only: creates one independent audit table and provider-scoped partial indexes.
No existing message, conversation, contact, or lead row is rewritten or deleted.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260826_quo_inbox"
down_revision: str | Sequence[str] | None = "20260826_quo_voice"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_QUO_MESSAGE_INDEX = "uq_messages_quo_provider"
_LEGACY_MESSAGE_INDEX = "uq_messages_legacy_provider_message_id"
_GLOBAL_MESSAGE_CONSTRAINT = "uq_messages_provider_message_id"
_RESTORE_MESSAGE_INDEX = "uq_messages_provider_message_id_restore"


def upgrade() -> None:
    """Add retry-safe Quo send claims without locking message writes."""
    op.create_table(
        "quo_send_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state", sa.String(length=20), server_default="sending", nullable=False),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("error_class", sa.String(length=100), nullable=True),
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
            "state IN ('sending', 'accepted', 'failed', 'unknown')",
            name="ck_quo_send_attempts_state",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_quo_send_attempts_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_quo_send_attempts_conversation_id_conversations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
            name="fk_quo_send_attempts_message_id_messages",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_quo_send_attempts"),
        sa.UniqueConstraint(
            "workspace_id",
            "client_request_id",
            name="uq_quo_send_attempts_workspace_request",
        ),
        sa.UniqueConstraint("message_id", name="uq_quo_send_attempts_message"),
        if_not_exists=True,
    )

    with op.get_context().autocommit_block():
        op.create_index(
            _QUO_MESSAGE_INDEX,
            "messages",
            ["source_provider", "provider_message_id"],
            unique=True,
            postgresql_where=sa.text("source_provider = 'quo' AND provider_message_id IS NOT NULL"),
            postgresql_concurrently=True,
            if_not_exists=True,
        )
        op.create_index(
            _LEGACY_MESSAGE_INDEX,
            "messages",
            ["provider_message_id"],
            unique=True,
            postgresql_where=sa.text(
                "source_provider IS DISTINCT FROM 'quo' AND provider_message_id IS NOT NULL"
            ),
            postgresql_concurrently=True,
            if_not_exists=True,
        )

    # Two overlapping unique arbiters make PostgreSQL races nondeterministic.
    # The replacement keeps legacy provider IDs globally unique while Quo uses
    # its provider-scoped arbiter. This is metadata-only; no row is rewritten.
    op.drop_constraint(
        _GLOBAL_MESSAGE_CONSTRAINT,
        "messages",
        type_="unique",
        if_exists=True,
    )


def downgrade() -> None:
    """Restore global provider identity, then remove Quo-specific storage."""
    with op.get_context().autocommit_block():
        op.create_index(
            _RESTORE_MESSAGE_INDEX,
            "messages",
            ["provider_message_id"],
            unique=True,
            postgresql_concurrently=True,
            if_not_exists=True,
        )

    op.execute(
        sa.text(
            "ALTER TABLE messages "
            f"ADD CONSTRAINT {_GLOBAL_MESSAGE_CONSTRAINT} "
            f"UNIQUE USING INDEX {_RESTORE_MESSAGE_INDEX}"
        )
    )

    with op.get_context().autocommit_block():
        op.drop_index(
            _QUO_MESSAGE_INDEX,
            table_name="messages",
            postgresql_concurrently=True,
            if_exists=True,
        )
        op.drop_index(
            _LEGACY_MESSAGE_INDEX,
            table_name="messages",
            postgresql_concurrently=True,
            if_exists=True,
        )

    op.drop_table("quo_send_attempts")
