"""link bookable staff to a login

Revision ID: 3c451b655d90
Revises: 20260811_lighting_handoff
Create Date: 2026-08-12 18:28:26.622262

Mirrors ``technicians.user_id``: an optional link from a bookable staff row to
the login that person signs in with. Without it an appointment has no path back
to a user, so "show me the appointments I'm booked on" is unanswerable and the
calendar cannot scope reads for the field tier.

Additive and nullable, on live ``bookable_staff`` data: existing rows keep
working unlinked, and privileged callers see exactly what they saw before.
``SET NULL`` keeps the staff row (and its booking history) when a login is
deleted, matching the technician roster.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "3c451b655d90"
down_revision: str | Sequence[str] | None = "20260811_lighting_handoff"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("bookable_staff", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_bookable_staff_user_id"), "bookable_staff", ["user_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_bookable_staff_user_id_users"),
        "bookable_staff",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_bookable_staff_user_id_users"), "bookable_staff", type_="foreignkey"
    )
    op.drop_index(op.f("ix_bookable_staff_user_id"), table_name="bookable_staff")
    op.drop_column("bookable_staff", "user_id")
