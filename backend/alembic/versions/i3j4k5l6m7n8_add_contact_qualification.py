"""Add contact qualification fields.

Adds is_qualified, qualification_signals (JSONB), and qualified_at to contacts table
for automated lead qualification tracking.

Revision ID: i3j4k5l6m7n8
Revises: h2i3j4k5l6m7
Create Date: 2025-01-06
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "i3j4k5l6m7n8"
down_revision: str | None = "h2i3j4k5l6m7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add qualification fields to contacts table."""
    # Add is_qualified column with default False
    op.add_column(
        "contacts",
        sa.Column("is_qualified", sa.Boolean(), nullable=False, server_default="false"),
    )

    # Add qualification_signals JSONB column
    op.add_column(
        "contacts",
        sa.Column("qualification_signals", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    # Add qualified_at timestamp column
    op.add_column(
        "contacts",
        sa.Column("qualified_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Create index on is_qualified for filtering qualified leads
    op.create_index(
        "ix_contacts_is_qualified",
        "contacts",
        ["is_qualified"],
        unique=False,
    )


def downgrade() -> None:
    """Remove qualification fields from contacts table."""
    op.drop_index("ix_contacts_is_qualified", table_name="contacts")
    op.drop_column("contacts", "qualified_at")
    op.drop_column("contacts", "qualification_signals")
    op.drop_column("contacts", "is_qualified")
