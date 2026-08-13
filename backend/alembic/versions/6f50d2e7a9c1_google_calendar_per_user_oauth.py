"""replace Cal.com fields with per-user Google Calendar OAuth

Revision ID: 6f50d2e7a9c1
Revises: cd83463b55d8
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.core.encryption import EncryptedString

revision: str = "6f50d2e7a9c1"
down_revision: str | None = "cd83463b55d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "google_calendar_connections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("google_account_id", sa.String(length=255), nullable=False),
        sa.Column("google_email", sa.String(length=320), nullable=False),
        sa.Column("calendar_id", sa.String(length=1024), nullable=False),
        sa.Column("access_token", EncryptedString(), nullable=True),
        sa.Column("refresh_token", EncryptedString(), nullable=False),
        sa.Column("access_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("granted_scopes", sa.String(length=2048), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_google_calendar_connections_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_google_calendar_connections")),
        sa.UniqueConstraint("user_id", name="uq_google_calendar_connections_user_id"),
    )
    op.create_index(
        op.f("ix_google_calendar_connections_user_id"),
        "google_calendar_connections",
        ["user_id"],
        unique=False,
    )

    op.add_column("appointments", sa.Column("google_calendar_event_id", sa.String(1024)))
    op.add_column("appointments", sa.Column("google_calendar_event_url", sa.String(2048)))
    op.add_column("appointments", sa.Column("meeting_url", sa.String(2048)))
    op.create_index(
        op.f("ix_appointments_google_calendar_event_id"),
        "appointments",
        ["google_calendar_event_id"],
        unique=False,
    )

    op.drop_index("ix_appointments_calcom_booking_uid", table_name="appointments")
    op.drop_column("appointments", "calcom_booking_uid")
    op.drop_column("appointments", "calcom_booking_id")
    op.drop_column("appointments", "calcom_event_type_id")
    op.drop_index("ix_bookable_staff_calcom_event_type_id", table_name="bookable_staff")
    op.drop_column("bookable_staff", "calcom_event_type_id")
    op.drop_column("agents", "calcom_event_type_id")


def downgrade() -> None:
    op.add_column("agents", sa.Column("calcom_event_type_id", sa.Integer()))
    op.add_column("bookable_staff", sa.Column("calcom_event_type_id", sa.Integer()))
    op.create_index(
        "ix_bookable_staff_calcom_event_type_id",
        "bookable_staff",
        ["calcom_event_type_id"],
        unique=False,
    )
    op.add_column("appointments", sa.Column("calcom_event_type_id", sa.Integer()))
    op.add_column("appointments", sa.Column("calcom_booking_id", sa.Integer()))
    op.add_column("appointments", sa.Column("calcom_booking_uid", sa.String(length=255)))
    op.create_index(
        "ix_appointments_calcom_booking_uid",
        "appointments",
        ["calcom_booking_uid"],
        unique=False,
    )

    op.drop_index(op.f("ix_appointments_google_calendar_event_id"), table_name="appointments")
    op.drop_column("appointments", "meeting_url")
    op.drop_column("appointments", "google_calendar_event_url")
    op.drop_column("appointments", "google_calendar_event_id")
    op.drop_index(
        op.f("ix_google_calendar_connections_user_id"),
        table_name="google_calendar_connections",
    )
    op.drop_table("google_calendar_connections")
