"""Make email_events.provider_event_id unique for webhook idempotency.

Resend webhook deliveries are retried via Svix; without a unique constraint on
``provider_event_id`` (the per-event ``svix-id``), retries create duplicate
``EmailEvent`` rows and double-increment campaign counters.

This migration:
  * Deletes pre-existing duplicate rows, keeping the earliest occurrence.
  * Drops the non-unique index ``ix_email_events_provider_event_id``.
  * Adds a unique constraint ``uq_email_events_provider_event_id`` on
    ``provider_event_id`` (multiple NULLs remain allowed under Postgres).

Revision ID: eb03f4a5b6c7
Revises: ec02f3a4b5c6
Create Date: 2026-05-06
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "eb03f4a5b6c7"
down_revision: str | None = "ec02f3a4b5c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # De-duplicate any rows created before the unique constraint existed.
    # Keeps the earliest row per provider_event_id; ignores NULL ids.
    op.execute(
        """
        DELETE FROM email_events a
        USING email_events b
        WHERE a.provider_event_id IS NOT NULL
          AND a.provider_event_id = b.provider_event_id
          AND (
            a.occurred_at > b.occurred_at
            OR (a.occurred_at = b.occurred_at AND a.id > b.id)
          )
        """
    )

    op.drop_index("ix_email_events_provider_event_id", table_name="email_events")
    op.create_unique_constraint(
        "uq_email_events_provider_event_id",
        "email_events",
        ["provider_event_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_email_events_provider_event_id",
        "email_events",
        type_="unique",
    )
    op.create_index(
        "ix_email_events_provider_event_id",
        "email_events",
        ["provider_event_id"],
    )
