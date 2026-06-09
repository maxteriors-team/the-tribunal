"""add phone_messages table for take-a-message voice tool

Revision ID: 20260609_phone_messages
Revises: d1e2f3a4b5c6
Create Date: 2026-06-09

Adds the ``phone_messages`` table that backs the ``take_message`` voice tool:
structured messages a caller asks the AI receptionist to relay to a human
(name, callback number, reason/topic, urgency, preferred callback time, and a
free-text message), linked to the call's message + conversation/contact.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260609_phone_messages"
down_revision: str | Sequence[str] | None = "d1e2f3a4b5c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the phone_messages table."""
    op.create_table(
        "phone_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("contact_id", sa.BigInteger(), nullable=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("caller_name", sa.String(length=200), nullable=True),
        sa.Column("callback_number", sa.String(length=32), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("urgency", sa.String(length=20), nullable=False),
        sa.Column("preferred_callback_time", sa.String(length=200), nullable=True),
        sa.Column("message_body", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_phone_messages_workspace_id"), "phone_messages", ["workspace_id"]
    )
    op.create_index(
        op.f("ix_phone_messages_message_id"), "phone_messages", ["message_id"]
    )
    op.create_index(
        op.f("ix_phone_messages_conversation_id"), "phone_messages", ["conversation_id"]
    )
    op.create_index(
        op.f("ix_phone_messages_contact_id"), "phone_messages", ["contact_id"]
    )
    op.create_index(op.f("ix_phone_messages_agent_id"), "phone_messages", ["agent_id"])
    op.create_index(op.f("ix_phone_messages_urgency"), "phone_messages", ["urgency"])
    op.create_index(op.f("ix_phone_messages_status"), "phone_messages", ["status"])
    op.create_index(
        op.f("ix_phone_messages_created_at"), "phone_messages", ["created_at"]
    )


def downgrade() -> None:
    """Drop the phone_messages table."""
    op.drop_index(op.f("ix_phone_messages_created_at"), table_name="phone_messages")
    op.drop_index(op.f("ix_phone_messages_status"), table_name="phone_messages")
    op.drop_index(op.f("ix_phone_messages_urgency"), table_name="phone_messages")
    op.drop_index(op.f("ix_phone_messages_agent_id"), table_name="phone_messages")
    op.drop_index(op.f("ix_phone_messages_contact_id"), table_name="phone_messages")
    op.drop_index(op.f("ix_phone_messages_conversation_id"), table_name="phone_messages")
    op.drop_index(op.f("ix_phone_messages_message_id"), table_name="phone_messages")
    op.drop_index(op.f("ix_phone_messages_workspace_id"), table_name="phone_messages")
    op.drop_table("phone_messages")
