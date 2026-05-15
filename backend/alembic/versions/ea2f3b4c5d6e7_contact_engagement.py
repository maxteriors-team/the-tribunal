"""Add contact engagement tracking fields.

Adds last_engaged_at and engagement_score to contacts for recency-weighted
engagement signal tracking.

Revision ID: ea2f3b4c5d6e7
Revises: db01e2f3a4b5
Create Date: 2026-04-15
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "ea2f3b4c5d6e7"
down_revision: str | None = "db01e2f3a4b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add engagement fields to contacts table."""
    op.add_column(
        "contacts",
        sa.Column("last_engaged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "contacts",
        sa.Column(
            "engagement_score",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_index(
        "ix_contacts_last_engaged_at",
        "contacts",
        ["last_engaged_at"],
        unique=False,
    )


def downgrade() -> None:
    """Remove engagement fields from contacts table."""
    op.drop_index("ix_contacts_last_engaged_at", table_name="contacts")
    op.drop_column("contacts", "engagement_score")
    op.drop_column("contacts", "last_engaged_at")
