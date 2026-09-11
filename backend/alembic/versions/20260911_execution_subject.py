"""Give automation executions a subject (entity-scoped runs).

An execution used to be implicitly *about a contact*. That is the right subject
for a welcome drip and the wrong one for most sequences that matter: a quote
revival ladder waking from a 30-day wait needs to ask "is **this** quote still
unsold?", and a contact-shaped run cannot answer that when one customer holds
three open quotes.

This adds ``(subject_type, subject_id)`` and backfills every existing row to
``('contact', contact_id)``, which is exactly what those rows already meant. No
behaviour changes on upgrade.

``subject_id`` is TEXT rather than BIGINT because subject ids are integers for
contacts and UUIDs for quotes, jobs and invoices; one honest string column beats
a nullable column per id type.

The new unique index runs *alongside* ``uq_automation_execution_contact`` rather
than replacing it. The old index still holds for contact-subject rows, and the
new one extends the same "process a subject at most once per polling automation"
guarantee to the other subject types. Rows with a NULL ``subject_id`` (polling
runs that never recorded a contact) are excluded, matching the old index's
tolerance for them.

Revision ID: 20260911_execution_subject
Revises: 20260910_roleplay_execution
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260911_execution_subject"
down_revision: str | None = "20260910_roleplay_execution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "automation_executions",
        sa.Column(
            "subject_type",
            sa.String(length=32),
            nullable=False,
            server_default="contact",
        ),
    )
    op.add_column(
        "automation_executions",
        sa.Column("subject_id", sa.Text(), nullable=True),
    )

    # Backfill: every existing row was about its contact. Rows with no contact
    # (polling runs that never resolved one) keep a NULL subject_id and are
    # excluded from the unique index below.
    op.execute(
        """
        UPDATE automation_executions
        SET subject_id = contact_id::text
        WHERE contact_id IS NOT NULL
          AND subject_id IS NULL
        """
    )

    op.create_index(
        "uq_automation_execution_subject",
        "automation_executions",
        ["automation_id", "subject_type", "subject_id"],
        unique=True,
        postgresql_where=sa.text("event_id IS NULL AND subject_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_automation_execution_subject",
        table_name="automation_executions",
    )
    op.drop_column("automation_executions", "subject_id")
    op.drop_column("automation_executions", "subject_type")
