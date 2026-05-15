"""Add composite indexes for hot query paths.

Adds covering composite indexes that match the WHERE/ORDER BY shape of the
highest-traffic list and worker queries across the app:

- campaign_contacts(campaign_id, status) — campaign roster filtered by status
- appointments(workspace_id, scheduled_at) — calendar/agenda listings
- conversations(workspace_id, last_message_at DESC) — inbox feed
- messages(conversation_id, created_at) — thread paging
- auth_rate_limits(client_ip, created_at) — rate-limit window scan
- demo_requests(phone_number, created_at) + (client_ip, created_at) — abuse checks
- refresh_tokens(user_id, revoked, expires_at) — active-token lookups
- lead_magnet_leads(workspace_id, created_at) — workspace lead feed
- automation_executions(status, scheduled_for) — worker polling
- pending_actions(status, expires_at) — HITL expiration sweep
- human_nudges(status, due_date) — nudge dispatcher

Revision ID: c9e1a2b3d4f5
Revises: 9fed0162f415
Create Date: 2026-05-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c9e1a2b3d4f5"
down_revision: str | None = "9fed0162f415"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_campaign_contacts_campaign_status",
        "campaign_contacts",
        ["campaign_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_appointments_workspace_scheduled_at",
        "appointments",
        ["workspace_id", "scheduled_at"],
        unique=False,
    )
    op.create_index(
        "ix_conversations_workspace_last_message_at",
        "conversations",
        ["workspace_id", "last_message_at"],
        unique=False,
        postgresql_ops={"last_message_at": "DESC"},
    )
    op.create_index(
        "ix_messages_conversation_created_at",
        "messages",
        ["conversation_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_auth_rate_limits_client_ip_created_at",
        "auth_rate_limits",
        ["client_ip", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_demo_requests_phone_created_at",
        "demo_requests",
        ["phone_number", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_demo_requests_client_ip_created_at",
        "demo_requests",
        ["client_ip", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_refresh_tokens_user_revoked_expires",
        "refresh_tokens",
        ["user_id", "revoked", "expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_lead_magnet_leads_workspace_created_at",
        "lead_magnet_leads",
        ["workspace_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_automation_executions_status_scheduled_for",
        "automation_executions",
        ["status", "scheduled_for"],
        unique=False,
    )
    op.create_index(
        "ix_pending_actions_status_expires_at",
        "pending_actions",
        ["status", "expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_human_nudges_status_due_date",
        "human_nudges",
        ["status", "due_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_human_nudges_status_due_date", table_name="human_nudges")
    op.drop_index(
        "ix_pending_actions_status_expires_at", table_name="pending_actions"
    )
    op.drop_index(
        "ix_automation_executions_status_scheduled_for",
        table_name="automation_executions",
    )
    op.drop_index(
        "ix_lead_magnet_leads_workspace_created_at", table_name="lead_magnet_leads"
    )
    op.drop_index(
        "ix_refresh_tokens_user_revoked_expires", table_name="refresh_tokens"
    )
    op.drop_index(
        "ix_demo_requests_client_ip_created_at", table_name="demo_requests"
    )
    op.drop_index("ix_demo_requests_phone_created_at", table_name="demo_requests")
    op.drop_index(
        "ix_auth_rate_limits_client_ip_created_at", table_name="auth_rate_limits"
    )
    op.drop_index("ix_messages_conversation_created_at", table_name="messages")
    op.drop_index(
        "ix_conversations_workspace_last_message_at", table_name="conversations"
    )
    op.drop_index(
        "ix_appointments_workspace_scheduled_at", table_name="appointments"
    )
    op.drop_index(
        "ix_campaign_contacts_campaign_status", table_name="campaign_contacts"
    )
