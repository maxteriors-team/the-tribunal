"""Add idempotency_key column + unique index to messages.

Adds a per-row ``idempotency_key`` (UUID, NOT NULL, UNIQUE) on
``messages`` so outbound senders (SMS via TelnyxSMSService, voice via
TelnyxVoiceService) can survive a worker crash between the DB row insert
and the Telnyx API call without double-sending. Workers compute a stable
UUID5 from a domain entity (appointment + offset, campaign_contact,
drip enrollment step, pending_action) and look the row up before issuing
a new Telnyx request; the key is also forwarded to Telnyx as the
``X-Idempotency-Key`` header (or ``client_state`` on Call Control) so
the provider also rejects duplicates if the local row was somehow lost.

Backfills any pre-existing rows with random UUIDs before adding the
NOT NULL / UNIQUE constraints. Existing rows aren't tied to any worker
retry path, so a fresh random key is the safe default.

Revision ID: e0f1a2b3c4d5
Revises: b4819c8748a9
Create Date: 2026-05-15 12:30:00.000000

Note (2026-05-20): ``down_revision`` originally pointed at the dangling rev
``d9e8c7b6a5f4`` (never created), so ``alembic upgrade head`` could not
resolve the graph. Re-pointed at ``b4819c8748a9`` (the merge that was the
head at the time this migration was authored, May 15 2026).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e0f1a2b3c4d5"
down_revision: str | None = "b4819c8748a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add the column as nullable so we can backfill existing rows.
    op.add_column(
        "messages",
        sa.Column(
            "idempotency_key",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )

    # 2. Backfill: any pre-existing message row gets a fresh random UUID.
    # ``gen_random_uuid()`` is provided by the ``pgcrypto`` extension which
    # Postgres 13+ ships in core; create it idempotently in case the DB
    # was provisioned without it.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute(
        "UPDATE messages SET idempotency_key = gen_random_uuid() " "WHERE idempotency_key IS NULL"
    )

    # 3. Enforce NOT NULL now that every row has a value.
    op.alter_column("messages", "idempotency_key", nullable=False)

    # 4. Indexes + unique constraint. Keep them as two separate objects so
    # the model-level ``index=True`` declaration and the explicit
    # ``UniqueConstraint`` in ``__table_args__`` both round-trip cleanly
    # against this schema.
    op.create_index(
        "ix_messages_idempotency_key",
        "messages",
        ["idempotency_key"],
    )
    op.create_unique_constraint(
        "uq_messages_idempotency_key",
        "messages",
        ["idempotency_key"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_messages_idempotency_key", "messages", type_="unique")
    op.drop_index("ix_messages_idempotency_key", table_name="messages")
    op.drop_column("messages", "idempotency_key")
