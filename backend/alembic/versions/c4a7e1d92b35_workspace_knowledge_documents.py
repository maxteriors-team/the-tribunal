"""Allow workspace-scoped knowledge documents.

Revision ID: c4a7e1d92b35
Revises: 7dc9d61efed7
Create Date: 2026-07-29 18:35:00.000000

Product-help content belongs to a workspace, not to one customer-facing agent.
The denormalized ``knowledge_chunks.agent_id`` column must be nullable with its
parent document so the existing hybrid retrieval indexes can serve that corpus.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4a7e1d92b35"
down_revision: str | None = "7dc9d61efed7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "knowledge_documents",
        "agent_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.alter_column(
        "knowledge_chunks",
        "agent_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )


def downgrade() -> None:
    # Workspace help is seeded from repository docs and can be regenerated.
    # Remove rows the previous NOT NULL schema cannot represent before restoring
    # that invariant; document deletion also cascades to its chunks.
    op.execute(sa.text("DELETE FROM knowledge_chunks WHERE agent_id IS NULL"))
    op.execute(sa.text("DELETE FROM knowledge_documents WHERE agent_id IS NULL"))
    op.alter_column(
        "knowledge_chunks",
        "agent_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.alter_column(
        "knowledge_documents",
        "agent_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
