"""Add durable, deduplicated rehearsal execution (legacy reports untouched).

Revision ID: 20260910_roleplay_execution
Revises: 6652913f227b
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260910_roleplay_execution"
down_revision = "6652913f227b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rehearsal_runs", sa.Column("idempotency_key", postgresql.UUID(), nullable=True))
    op.add_column("rehearsal_runs", sa.Column("request_fingerprint", sa.String(64), nullable=True))
    op.add_column(
        "rehearsal_runs", sa.Column("execution_context", postgresql.JSONB(), nullable=True)
    )
    op.add_column("rehearsal_runs", sa.Column("pending_action", sa.String(20), nullable=True))
    op.add_column("rehearsal_runs", sa.Column("processing_token", postgresql.UUID(), nullable=True))
    op.add_column(
        "rehearsal_runs", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "rehearsal_runs",
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "rehearsal_runs",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "rehearsal_runs",
        sa.Column("retryable", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_unique_constraint(
        "uq_rehearsal_request", "rehearsal_runs", ["workspace_id", "idempotency_key"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_rehearsal_request", "rehearsal_runs", type_="unique")
    for column in (
        "retryable",
        "attempt_count",
        "processing_started_at",
        "processing_token",
        "deleted_at",
        "pending_action",
        "execution_context",
        "request_fingerprint",
        "idempotency_key",
    ):
        op.drop_column("rehearsal_runs", column)
