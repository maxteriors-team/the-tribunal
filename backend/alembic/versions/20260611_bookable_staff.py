"""bookable staff pool + skill/round-robin assignment

Revision ID: 20260611_bookable_staff
Revises: 20260611_inbound_screening
Create Date: 2026-06-11 00:00:00.000000

Adds multi-staff round-robin and skill-based appointment routing:

- ``bookable_staff`` table: pool of bookable staff/resources scoped to a
  workspace and (optionally) an agent, each with their own Cal.com event type,
  skill tags, and round-robin distribution counters.
- ``agents.assignment_strategy``: how the booking tool picks a staff member
  (``single`` | ``round_robin`` | ``skill_based``).
- ``appointments.bookable_staff_id``: records which staff member a booking was
  routed to (set by the booking tool and the Cal.com webhook).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260611_bookable_staff"
down_revision: str | Sequence[str] | None = "20260611_inbound_screening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bookable_staff",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("calcom_event_type_id", sa.Integer(), nullable=True),
        sa.Column(
            "skills",
            postgresql.ARRAY(sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("assignment_count", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("last_assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_bookable_staff_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_bookable_staff_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bookable_staff")),
    )
    op.create_index(
        op.f("ix_bookable_staff_workspace_id"),
        "bookable_staff",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_bookable_staff_agent_id"),
        "bookable_staff",
        ["agent_id"],
        unique=False,
    )
    op.create_index(
        "ix_bookable_staff_workspace_agent_active",
        "bookable_staff",
        ["workspace_id", "agent_id", "is_active"],
        unique=False,
    )
    op.create_index(
        "ix_bookable_staff_calcom_event_type_id",
        "bookable_staff",
        ["calcom_event_type_id"],
        unique=False,
    )

    op.add_column(
        "agents",
        sa.Column(
            "assignment_strategy",
            sa.String(length=20),
            server_default="single",
            nullable=False,
        ),
    )

    op.add_column(
        "appointments",
        sa.Column("bookable_staff_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        op.f("ix_appointments_bookable_staff_id"),
        "appointments",
        ["bookable_staff_id"],
        unique=False,
    )
    op.create_foreign_key(
        op.f("fk_appointments_bookable_staff_id_bookable_staff"),
        "appointments",
        "bookable_staff",
        ["bookable_staff_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_appointments_bookable_staff_id_bookable_staff"),
        "appointments",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_appointments_bookable_staff_id"), table_name="appointments")
    op.drop_column("appointments", "bookable_staff_id")

    op.drop_column("agents", "assignment_strategy")

    op.drop_index("ix_bookable_staff_calcom_event_type_id", table_name="bookable_staff")
    op.drop_index("ix_bookable_staff_workspace_agent_active", table_name="bookable_staff")
    op.drop_index(op.f("ix_bookable_staff_agent_id"), table_name="bookable_staff")
    op.drop_index(op.f("ix_bookable_staff_workspace_id"), table_name="bookable_staff")
    op.drop_table("bookable_staff")
