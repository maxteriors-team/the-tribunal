"""Add SMS link click tracking.

Adds short_links and link_clicks tables for tracking clicks on shortened
URLs embedded in outbound SMS, plus a links_clicked counter on campaigns.

Revision ID: a9b0c1d2e3f5
Revises: z8a9b0c1d2e3
Create Date: 2026-04-15
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "a9b0c1d2e3f5"
down_revision: str | None = "z8a9b0c1d2e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create short_links and link_clicks tables and campaign counter."""
    op.add_column(
        "campaigns",
        sa.Column(
            "links_clicked",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    op.create_table(
        "short_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("short_code", sa.String(length=16), nullable=False),
        sa.Column("target_url", sa.Text(), nullable=False),
        sa.Column("contact_id", sa.BigInteger(), nullable=True),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("click_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_clicked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["campaigns.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["message_id"], ["messages.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_short_links_short_code",
        "short_links",
        ["short_code"],
        unique=True,
    )
    op.create_index(
        "ix_short_links_workspace_id", "short_links", ["workspace_id"], unique=False
    )
    op.create_index(
        "ix_short_links_contact_id", "short_links", ["contact_id"], unique=False
    )
    op.create_index(
        "ix_short_links_campaign_id", "short_links", ["campaign_id"], unique=False
    )
    op.create_index(
        "ix_short_links_message_id", "short_links", ["message_id"], unique=False
    )

    op.create_table(
        "link_clicks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("short_link_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("clicked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("referer", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["short_link_id"], ["short_links.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_link_clicks_short_link_id",
        "link_clicks",
        ["short_link_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop link tracking tables and campaign counter."""
    op.drop_index("ix_link_clicks_short_link_id", table_name="link_clicks")
    op.drop_table("link_clicks")
    op.drop_index("ix_short_links_message_id", table_name="short_links")
    op.drop_index("ix_short_links_campaign_id", table_name="short_links")
    op.drop_index("ix_short_links_contact_id", table_name="short_links")
    op.drop_index("ix_short_links_workspace_id", table_name="short_links")
    op.drop_index("ix_short_links_short_code", table_name="short_links")
    op.drop_table("short_links")
    op.drop_column("campaigns", "links_clicked")
