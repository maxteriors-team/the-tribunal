"""Add referral partner public intake profiles, links, and logos.

Revision ID: 20260902_referral_partner_intake
Revises: 20260901_job_timer_phases
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.core.encryption import EncryptedString

revision: str = "20260902_referral_partner_intake"
down_revision: str | None = "20260901_job_timer_phases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "referral_partners",
        sa.Column(
            "intake_status",
            sa.String(length=50),
            server_default="not_requested",
            nullable=False,
        ),
    )
    op.add_column(
        "referral_partners", sa.Column("intake_link_created_at", sa.DateTime(timezone=True))
    )
    op.add_column("referral_partners", sa.Column("intake_submitted_at", sa.DateTime(timezone=True)))
    op.add_column("referral_partners", sa.Column("intake_revoked_at", sa.DateTime(timezone=True)))
    op.add_column("referral_partners", sa.Column("website_url", sa.String(length=2048)))
    op.add_column("referral_partners", sa.Column("business_description", sa.Text()))
    op.add_column("referral_partners", sa.Column("services", sa.Text()))
    op.add_column("referral_partners", sa.Column("service_area", sa.String(length=500)))
    op.add_column("referral_partners", sa.Column("offer_headline", sa.String(length=200)))
    op.add_column("referral_partners", sa.Column("offer_description", sa.Text()))
    op.add_column(
        "referral_partners",
        sa.Column("offer_type", sa.String(length=50), server_default="none", nullable=False),
    )
    op.add_column("referral_partners", sa.Column("offer_value", sa.Numeric(12, 2)))
    op.add_column("referral_partners", sa.Column("offer_terms", sa.Text()))
    op.create_unique_constraint(
        "uq_referral_partners_id_workspace",
        "referral_partners",
        ["id", "workspace_id"],
    )

    op.create_table(
        "referral_partner_intake_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("referral_partner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("token", EncryptedString(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["referral_partner_id", "workspace_id"],
            ["referral_partners.id", "referral_partners.workspace_id"],
            name="fk_referral_partner_intake_links_scoped_partner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_referral_partner_intake_links_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_referral_partner_intake_links")),
    )
    op.create_index(
        "ix_referral_partner_intake_links_partner_active",
        "referral_partner_intake_links",
        ["workspace_id", "referral_partner_id", "revoked_at", "expires_at"],
    )
    op.create_index(
        op.f("ix_referral_partner_intake_links_referral_partner_id"),
        "referral_partner_intake_links",
        ["referral_partner_id"],
    )
    op.create_index(
        op.f("ix_referral_partner_intake_links_token_digest"),
        "referral_partner_intake_links",
        ["token_digest"],
        unique=True,
    )
    op.create_index(
        op.f("ix_referral_partner_intake_links_workspace_id"),
        "referral_partner_intake_links",
        ["workspace_id"],
    )

    op.create_table(
        "referral_partner_logos",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("referral_partner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=32), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "content_type IN ('image/jpeg', 'image/png', 'image/webp')",
            name=op.f("ck_referral_partner_logos_content_type"),
        ),
        sa.CheckConstraint(
            "size_bytes > 0 AND size_bytes <= 2097152",
            name=op.f("ck_referral_partner_logos_size_bytes"),
        ),
        sa.ForeignKeyConstraint(
            ["referral_partner_id", "workspace_id"],
            ["referral_partners.id", "referral_partners.workspace_id"],
            name="fk_referral_partner_logos_scoped_partner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_referral_partner_logos_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_referral_partner_logos")),
    )
    op.create_index(
        op.f("ix_referral_partner_logos_referral_partner_id"),
        "referral_partner_logos",
        ["referral_partner_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_referral_partner_logos_workspace_id"),
        "referral_partner_logos",
        ["workspace_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_referral_partner_logos_workspace_id"),
        table_name="referral_partner_logos",
    )
    op.drop_index(
        op.f("ix_referral_partner_logos_referral_partner_id"),
        table_name="referral_partner_logos",
    )
    op.drop_table("referral_partner_logos")

    op.drop_index(
        op.f("ix_referral_partner_intake_links_workspace_id"),
        table_name="referral_partner_intake_links",
    )
    op.drop_index(
        op.f("ix_referral_partner_intake_links_token_digest"),
        table_name="referral_partner_intake_links",
    )
    op.drop_index(
        op.f("ix_referral_partner_intake_links_referral_partner_id"),
        table_name="referral_partner_intake_links",
    )
    op.drop_index(
        "ix_referral_partner_intake_links_partner_active",
        table_name="referral_partner_intake_links",
    )
    op.drop_table("referral_partner_intake_links")

    op.drop_constraint(
        "uq_referral_partners_id_workspace",
        "referral_partners",
        type_="unique",
    )
    op.drop_column("referral_partners", "offer_terms")
    op.drop_column("referral_partners", "offer_value")
    op.drop_column("referral_partners", "offer_type")
    op.drop_column("referral_partners", "offer_description")
    op.drop_column("referral_partners", "offer_headline")
    op.drop_column("referral_partners", "service_area")
    op.drop_column("referral_partners", "services")
    op.drop_column("referral_partners", "business_description")
    op.drop_column("referral_partners", "website_url")
    op.drop_column("referral_partners", "intake_revoked_at")
    op.drop_column("referral_partners", "intake_submitted_at")
    op.drop_column("referral_partners", "intake_link_created_at")
    op.drop_column("referral_partners", "intake_status")
