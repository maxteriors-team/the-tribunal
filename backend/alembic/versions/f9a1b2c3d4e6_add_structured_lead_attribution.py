"""add structured lead attribution

Revision ID: f9a1b2c3d4e6
Revises: a0e8a88f7801
Create Date: 2026-06-25 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f9a1b2c3d4e6"
down_revision: str | None = "a0e8a88f7801"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_LEAD_SOURCE_TYPE = sa.Enum(
    "facebook_ads",
    "google_ads",
    "organic",
    "phone_radio",
    "other",
    name="leadsourcetype",
    native_enum=False,
    create_constraint=False,
    length=50,
)


def upgrade() -> None:
    op.add_column(
        "lead_sources",
        sa.Column("source_type", _LEAD_SOURCE_TYPE, nullable=False, server_default="other"),
    )
    op.create_index(
        "ix_lead_sources_workspace_source_type",
        "lead_sources",
        ["workspace_id", "source_type"],
        unique=False,
    )

    op.create_table(
        "lead_source_campaigns",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("platform_campaign_id", sa.String(length=255), nullable=True),
        sa.Column("platform_campaign_name", sa.String(length=255), nullable=True),
        sa.Column("utm_campaign", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "campaign_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("started_on", sa.Date(), nullable=True),
        sa.Column("ended_on", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["lead_source_id"],
            ["lead_sources.id"],
            name=op.f("fk_lead_source_campaigns_lead_source_id_lead_sources"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_lead_source_campaigns_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lead_source_campaigns")),
        sa.UniqueConstraint(
            "lead_source_id",
            "platform_campaign_id",
            name="uq_lead_source_campaigns_source_platform_id",
        ),
    )
    op.create_index(
        op.f("ix_lead_source_campaigns_lead_source_id"),
        "lead_source_campaigns",
        ["lead_source_id"],
        unique=False,
    )
    op.create_index(
        "ix_lead_source_campaigns_workspace_source",
        "lead_source_campaigns",
        ["workspace_id", "lead_source_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_lead_source_campaigns_workspace_id"),
        "lead_source_campaigns",
        ["workspace_id"],
        unique=False,
    )

    op.create_table(
        "lead_source_spend_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_source_campaign_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("spend_starts_on", sa.Date(), nullable=False),
        sa.Column("spend_ends_on", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "amount >= 0",
            name=op.f("ck_lead_source_spend_entries_amount_nonnegative"),
        ),
        sa.CheckConstraint(
            "spend_ends_on >= spend_starts_on",
            name=op.f("ck_lead_source_spend_entries_valid_date_range"),
        ),
        sa.ForeignKeyConstraint(
            ["lead_source_campaign_id"],
            ["lead_source_campaigns.id"],
            name=op.f("fk_lead_source_spend_entries_lead_source_campaign_id_lead_source_campaigns"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["lead_source_id"],
            ["lead_sources.id"],
            name=op.f("fk_lead_source_spend_entries_lead_source_id_lead_sources"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_lead_source_spend_entries_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lead_source_spend_entries")),
    )
    op.create_index(
        op.f("ix_lead_source_spend_entries_lead_source_campaign_id"),
        "lead_source_spend_entries",
        ["lead_source_campaign_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_lead_source_spend_entries_lead_source_id"),
        "lead_source_spend_entries",
        ["lead_source_id"],
        unique=False,
    )
    op.create_index(
        "ix_lead_source_spend_entries_source_dates",
        "lead_source_spend_entries",
        ["lead_source_id", "spend_starts_on", "spend_ends_on"],
        unique=False,
    )
    op.create_index(
        "ix_lead_source_spend_entries_workspace_dates",
        "lead_source_spend_entries",
        ["workspace_id", "spend_starts_on", "spend_ends_on"],
        unique=False,
    )
    op.create_index(
        op.f("ix_lead_source_spend_entries_workspace_id"),
        "lead_source_spend_entries",
        ["workspace_id"],
        unique=False,
    )

    op.add_column(
        "contacts",
        sa.Column("first_touch_lead_source_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "contacts",
        sa.Column(
            "first_touch_lead_source_campaign_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
    )
    op.add_column(
        "contacts",
        sa.Column("first_touch_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "contacts",
        sa.Column("latest_touch_lead_source_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "contacts",
        sa.Column(
            "latest_touch_lead_source_campaign_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
    )
    op.add_column(
        "contacts",
        sa.Column("latest_touch_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("contacts", sa.Column("attribution_confidence", sa.Float(), nullable=True))
    op.add_column("contacts", sa.Column("utm_source", sa.String(length=255), nullable=True))
    op.add_column("contacts", sa.Column("utm_medium", sa.String(length=255), nullable=True))
    op.add_column("contacts", sa.Column("utm_campaign", sa.String(length=255), nullable=True))
    op.add_column("contacts", sa.Column("utm_content", sa.String(length=255), nullable=True))
    op.add_column("contacts", sa.Column("utm_term", sa.String(length=255), nullable=True))
    op.add_column("contacts", sa.Column("gclid", sa.String(length=255), nullable=True))
    op.add_column("contacts", sa.Column("fbclid", sa.String(length=255), nullable=True))
    op.add_column("contacts", sa.Column("landing_page", sa.String(length=2048), nullable=True))
    op.add_column("contacts", sa.Column("referrer", sa.String(length=2048), nullable=True))
    op.create_foreign_key(
        op.f("fk_contacts_first_touch_lead_source_campaign_id_lead_source_campaigns"),
        "contacts",
        "lead_source_campaigns",
        ["first_touch_lead_source_campaign_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_contacts_first_touch_lead_source_id_lead_sources"),
        "contacts",
        "lead_sources",
        ["first_touch_lead_source_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_contacts_latest_touch_lead_source_campaign_id_lead_source_campaigns"),
        "contacts",
        "lead_source_campaigns",
        ["latest_touch_lead_source_campaign_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_contacts_latest_touch_lead_source_id_lead_sources"),
        "contacts",
        "lead_sources",
        ["latest_touch_lead_source_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_contacts_first_touch_lead_source_campaign_id"),
        "contacts",
        ["first_touch_lead_source_campaign_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_contacts_first_touch_lead_source_id"),
        "contacts",
        ["first_touch_lead_source_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_contacts_latest_touch_lead_source_campaign_id"),
        "contacts",
        ["latest_touch_lead_source_campaign_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_contacts_latest_touch_lead_source_id"),
        "contacts",
        ["latest_touch_lead_source_id"],
        unique=False,
    )

    op.add_column(
        "opportunities",
        sa.Column("lead_source_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "opportunities",
        sa.Column("lead_source_campaign_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "opportunities",
        sa.Column("attribution_confidence", sa.Float(), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_opportunities_lead_source_campaign_id_lead_source_campaigns"),
        "opportunities",
        "lead_source_campaigns",
        ["lead_source_campaign_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_opportunities_lead_source_id_lead_sources"),
        "opportunities",
        "lead_sources",
        ["lead_source_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_opportunities_lead_source_campaign_id"),
        "opportunities",
        ["lead_source_campaign_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_opportunities_lead_source_id"),
        "opportunities",
        ["lead_source_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_opportunities_lead_source_id"), table_name="opportunities")
    op.drop_index(op.f("ix_opportunities_lead_source_campaign_id"), table_name="opportunities")
    op.drop_constraint(
        op.f("fk_opportunities_lead_source_id_lead_sources"),
        "opportunities",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_opportunities_lead_source_campaign_id_lead_source_campaigns"),
        "opportunities",
        type_="foreignkey",
    )
    op.drop_column("opportunities", "attribution_confidence")
    op.drop_column("opportunities", "lead_source_campaign_id")
    op.drop_column("opportunities", "lead_source_id")

    op.drop_index(op.f("ix_contacts_latest_touch_lead_source_id"), table_name="contacts")
    op.drop_index(op.f("ix_contacts_latest_touch_lead_source_campaign_id"), table_name="contacts")
    op.drop_index(op.f("ix_contacts_first_touch_lead_source_id"), table_name="contacts")
    op.drop_index(op.f("ix_contacts_first_touch_lead_source_campaign_id"), table_name="contacts")
    op.drop_constraint(
        op.f("fk_contacts_latest_touch_lead_source_id_lead_sources"),
        "contacts",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_contacts_latest_touch_lead_source_campaign_id_lead_source_campaigns"),
        "contacts",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_contacts_first_touch_lead_source_id_lead_sources"),
        "contacts",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_contacts_first_touch_lead_source_campaign_id_lead_source_campaigns"),
        "contacts",
        type_="foreignkey",
    )
    op.drop_column("contacts", "referrer")
    op.drop_column("contacts", "landing_page")
    op.drop_column("contacts", "fbclid")
    op.drop_column("contacts", "gclid")
    op.drop_column("contacts", "utm_term")
    op.drop_column("contacts", "utm_content")
    op.drop_column("contacts", "utm_campaign")
    op.drop_column("contacts", "utm_medium")
    op.drop_column("contacts", "utm_source")
    op.drop_column("contacts", "attribution_confidence")
    op.drop_column("contacts", "latest_touch_at")
    op.drop_column("contacts", "latest_touch_lead_source_campaign_id")
    op.drop_column("contacts", "latest_touch_lead_source_id")
    op.drop_column("contacts", "first_touch_at")
    op.drop_column("contacts", "first_touch_lead_source_campaign_id")
    op.drop_column("contacts", "first_touch_lead_source_id")

    op.drop_index(
        op.f("ix_lead_source_spend_entries_workspace_id"), table_name="lead_source_spend_entries"
    )
    op.drop_index(
        "ix_lead_source_spend_entries_workspace_dates",
        table_name="lead_source_spend_entries",
    )
    op.drop_index(
        "ix_lead_source_spend_entries_source_dates",
        table_name="lead_source_spend_entries",
    )
    op.drop_index(
        op.f("ix_lead_source_spend_entries_lead_source_id"), table_name="lead_source_spend_entries"
    )
    op.drop_index(
        op.f("ix_lead_source_spend_entries_lead_source_campaign_id"),
        table_name="lead_source_spend_entries",
    )
    op.drop_table("lead_source_spend_entries")

    op.drop_index(op.f("ix_lead_source_campaigns_workspace_id"), table_name="lead_source_campaigns")
    op.drop_index("ix_lead_source_campaigns_workspace_source", table_name="lead_source_campaigns")
    op.drop_index(
        op.f("ix_lead_source_campaigns_lead_source_id"), table_name="lead_source_campaigns"
    )
    op.drop_table("lead_source_campaigns")

    op.drop_index("ix_lead_sources_workspace_source_type", table_name="lead_sources")
    op.drop_column("lead_sources", "source_type")
