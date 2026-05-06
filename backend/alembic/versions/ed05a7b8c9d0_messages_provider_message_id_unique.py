"""Make messages.provider_message_id unique for inbound SMS idempotency.

Telnyx retries inbound SMS webhooks on non-2xx responses (and occasionally on
network blips), so without a unique constraint on ``provider_message_id`` each
retry creates a duplicate ``Message`` row, double-increments
``Conversation.unread_count``, re-fires the AI response, and re-sends push
notifications.

This migration:
  * Deletes pre-existing duplicate rows, keeping the earliest occurrence per
    ``provider_message_id`` (NULL ids are left untouched — multiple NULLs are
    allowed under Postgres unique semantics).
  * Drops the non-unique index ``ix_messages_provider_message_id``.
  * Adds a unique constraint ``uq_messages_provider_message_id`` on
    ``provider_message_id``.

Revision ID: ed05a7b8c9d0
Revises: eb03f4a5b6c7
Create Date: 2026-05-06
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ed05a7b8c9d0"
down_revision: str | None = "eb03f4a5b6c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # De-duplicate any rows created before the unique constraint existed.
    # Keeps the earliest row per provider_message_id; ignores NULL ids.
    op.execute(
        """
        DELETE FROM messages a
        USING messages b
        WHERE a.provider_message_id IS NOT NULL
          AND a.provider_message_id = b.provider_message_id
          AND (
            a.created_at > b.created_at
            OR (a.created_at = b.created_at AND a.id > b.id)
          )
        """
    )

    op.drop_index("ix_messages_provider_message_id", table_name="messages")
    op.create_unique_constraint(
        "uq_messages_provider_message_id",
        "messages",
        ["provider_message_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_messages_provider_message_id",
        "messages",
        type_="unique",
    )
    op.create_index(
        "ix_messages_provider_message_id",
        "messages",
        ["provider_message_id"],
    )
