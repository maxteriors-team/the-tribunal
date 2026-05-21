"""add outbound compliance controls

Revision ID: 20260519_outbound_compliance_controls
Revises: 20260519_approval_pending_actions_nullable_agent
Create Date: 2026-05-19 00:00:01.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision: str = "20260519_outbound_compliance_controls"
down_revision: str | Sequence[str] | None = "20260519_approval_pending_actions_nullable_agent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "contacts",
        sa.Column("sms_consent_status", sa.String(50), nullable=False, server_default="unknown"),
    )
    op.add_column("contacts", sa.Column("sms_consent_source", sa.String(100), nullable=True))
    op.add_column(
        "contacts",
        sa.Column("sms_consent_collected_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("contacts", sa.Column("sms_consent_notes", sa.Text(), nullable=True))
    op.create_index(
        "ix_contacts_workspace_sms_consent_status",
        "contacts",
        ["workspace_id", "sms_consent_status"],
    )

    op.add_column("campaigns", sa.Column("max_messages_per_campaign", sa.Integer(), nullable=True))
    op.add_column("campaigns", sa.Column("quiet_hours_start", sa.Time(), nullable=True))
    op.add_column("campaigns", sa.Column("quiet_hours_end", sa.Time(), nullable=True))
    op.add_column("campaigns", sa.Column("quiet_hours_timezone", sa.String(50), nullable=True))

    op.add_column("global_opt_outs", sa.Column("source_type", sa.String(50), nullable=True))
    op.add_column("global_opt_outs", sa.Column("source_channel", sa.String(50), nullable=True))
    op.add_column("global_opt_outs", sa.Column("source_actor_type", sa.String(50), nullable=True))
    op.add_column("global_opt_outs", sa.Column("source_actor_id", sa.String(100), nullable=True))
    op.add_column(
        "global_opt_outs",
        sa.Column("source_context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    op.add_column("campaign_contacts", sa.Column("suppressed_reason", sa.String(100), nullable=True))
    op.add_column(
        "campaign_contacts",
        sa.Column("suppressed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "campaign_contacts",
        sa.Column("compliance_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "campaign_contacts",
        sa.Column("last_compliance_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    op.create_table(
        "outbound_action_audit_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "pending_action_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pending_actions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action_type", sa.String(100), nullable=False),
        sa.Column("action_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("compliance_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("decision", sa.String(50), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "contact_id",
            sa.BigInteger(),
            sa.ForeignKey("contacts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "campaign_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("campaigns.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_outbound_action_audit_workspace_created_at",
        "outbound_action_audit_logs",
        ["workspace_id", "created_at"],
    )
    op.create_index(
        "ix_outbound_action_audit_pending_action_id",
        "outbound_action_audit_logs",
        ["pending_action_id"],
    )
    op.create_index(
        "ix_outbound_action_audit_campaign_id",
        "outbound_action_audit_logs",
        ["campaign_id"],
    )
    op.create_index(
        "ix_outbound_action_audit_contact_id",
        "outbound_action_audit_logs",
        ["contact_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_outbound_action_audit_contact_id", table_name="outbound_action_audit_logs")
    op.drop_index("ix_outbound_action_audit_campaign_id", table_name="outbound_action_audit_logs")
    op.drop_index("ix_outbound_action_audit_pending_action_id", table_name="outbound_action_audit_logs")
    op.drop_index(
        "ix_outbound_action_audit_workspace_created_at",
        table_name="outbound_action_audit_logs",
    )
    op.drop_table("outbound_action_audit_logs")

    op.drop_column("campaign_contacts", "last_compliance_result")
    op.drop_column("campaign_contacts", "compliance_checked_at")
    op.drop_column("campaign_contacts", "suppressed_at")
    op.drop_column("campaign_contacts", "suppressed_reason")

    op.drop_column("global_opt_outs", "source_context")
    op.drop_column("global_opt_outs", "source_actor_id")
    op.drop_column("global_opt_outs", "source_actor_type")
    op.drop_column("global_opt_outs", "source_channel")
    op.drop_column("global_opt_outs", "source_type")

    op.drop_column("campaigns", "quiet_hours_timezone")
    op.drop_column("campaigns", "quiet_hours_end")
    op.drop_column("campaigns", "quiet_hours_start")
    op.drop_column("campaigns", "max_messages_per_campaign")

    op.drop_index("ix_contacts_workspace_sms_consent_status", table_name="contacts")
    op.drop_column("contacts", "sms_consent_notes")
    op.drop_column("contacts", "sms_consent_collected_at")
    op.drop_column("contacts", "sms_consent_source")
    op.drop_column("contacts", "sms_consent_status")
