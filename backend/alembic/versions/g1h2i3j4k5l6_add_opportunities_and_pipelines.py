"""Add opportunities and pipelines tables."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "g1h2i3j4k5l6"
down_revision: str | None = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade database schema."""
    # Create pipeline table
    op.create_table(
        "pipelines",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pipelines_workspace_id", "pipelines", ["workspace_id"], unique=False
    )
    op.create_index(
        "ix_pipelines_is_active", "pipelines", ["is_active"], unique=False
    )

    # Create pipeline_stages table
    op.create_table(
        "pipeline_stages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pipeline_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("probability", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stage_type", sa.String(50), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["pipeline_id"], ["pipelines.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pipeline_stages_pipeline_id",
        "pipeline_stages",
        ["pipeline_id"],
        unique=False,
    )

    # Create opportunities table
    op.create_table(
        "opportunities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pipeline_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stage_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("primary_contact_id", sa.BigInteger(), nullable=True),
        sa.Column("assigned_user_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("probability", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expected_close_date", sa.Date(), nullable=True),
        sa.Column("closed_date", sa.Date(), nullable=True),
        sa.Column("closed_by_id", sa.Integer(), nullable=True),
        sa.Column("stage_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(100), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["pipeline_id"], ["pipelines.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["stage_id"], ["pipeline_stages.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["primary_contact_id"], ["contacts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["assigned_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["closed_by_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_opportunities_workspace_id",
        "opportunities",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        "ix_opportunities_pipeline_id",
        "opportunities",
        ["pipeline_id"],
        unique=False,
    )
    op.create_index(
        "ix_opportunities_stage_id", "opportunities", ["stage_id"], unique=False
    )
    op.create_index(
        "ix_opportunities_primary_contact_id",
        "opportunities",
        ["primary_contact_id"],
        unique=False,
    )
    op.create_index(
        "ix_opportunities_assigned_user_id",
        "opportunities",
        ["assigned_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_opportunities_is_active", "opportunities", ["is_active"], unique=False
    )

    # Create opportunity_contacts association table
    op.create_table(
        "opportunity_contacts",
        sa.Column("opportunity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["opportunity_id"], ["opportunities.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("opportunity_id", "contact_id"),
    )

    # Create opportunity_line_items table
    op.create_table(
        "opportunity_line_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("opportunity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("discount", sa.Numeric(precision=10, scale=2), nullable=False, server_default="0"),
        sa.Column("total", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["opportunity_id"], ["opportunities.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_opportunity_line_items_opportunity_id",
        "opportunity_line_items",
        ["opportunity_id"],
        unique=False,
    )

    # Create opportunity_activities table
    op.create_table(
        "opportunity_activities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("opportunity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("activity_type", sa.String(100), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["opportunity_id"], ["opportunities.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_opportunity_activities_opportunity_id",
        "opportunity_activities",
        ["opportunity_id"],
        unique=False,
    )
    op.create_index(
        "ix_opportunity_activities_activity_type",
        "opportunity_activities",
        ["activity_type"],
        unique=False,
    )
    op.create_index(
        "ix_opportunity_activities_created_at",
        "opportunity_activities",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade database schema."""
    # Drop all tables in reverse order
    op.drop_index(
        "ix_opportunity_activities_created_at",
        table_name="opportunity_activities",
    )
    op.drop_index(
        "ix_opportunity_activities_activity_type",
        table_name="opportunity_activities",
    )
    op.drop_index(
        "ix_opportunity_activities_opportunity_id",
        table_name="opportunity_activities",
    )
    op.drop_table("opportunity_activities")

    op.drop_index(
        "ix_opportunity_line_items_opportunity_id",
        table_name="opportunity_line_items",
    )
    op.drop_table("opportunity_line_items")

    op.drop_table("opportunity_contacts")

    op.drop_index("ix_opportunities_is_active", table_name="opportunities")
    op.drop_index("ix_opportunities_assigned_user_id", table_name="opportunities")
    op.drop_index("ix_opportunities_primary_contact_id", table_name="opportunities")
    op.drop_index("ix_opportunities_stage_id", table_name="opportunities")
    op.drop_index("ix_opportunities_pipeline_id", table_name="opportunities")
    op.drop_index("ix_opportunities_workspace_id", table_name="opportunities")
    op.drop_table("opportunities")

    op.drop_index("ix_pipeline_stages_pipeline_id", table_name="pipeline_stages")
    op.drop_table("pipeline_stages")

    op.drop_index("ix_pipelines_is_active", table_name="pipelines")
    op.drop_index("ix_pipelines_workspace_id", table_name="pipelines")
    op.drop_table("pipelines")
