"""add lossless quote input and revision lineage

Revision ID: 20260818_quote_revisions
Revises: 20260817_contact_ai_memory
Create Date: 2026-08-18 00:00:00.000000

Protected customer decisions, conversion links, and payment records remain on the
source quote. A revised proposal stores its validated wizard input separately and
points to both its immediate source and root audit record.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260818_quote_revisions"
down_revision: str | Sequence[str] | None = "20260817_contact_ai_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "quotes",
        sa.Column("proposal_input", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("quotes", sa.Column("proposal_input_version", sa.Integer(), nullable=True))
    op.add_column(
        "quotes",
        sa.Column("proposal_version", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "quotes",
        sa.Column("revision_of_quote_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "quotes",
        sa.Column("revision_root_quote_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "quotes",
        sa.Column("revision_number", sa.Integer(), server_default="1", nullable=False),
    )

    op.create_check_constraint(
        "ck_quotes_proposal_version_positive",
        "quotes",
        "proposal_version >= 1",
    )
    op.create_check_constraint(
        "ck_quotes_revision_number_positive",
        "quotes",
        "revision_number >= 1",
    )
    op.create_check_constraint(
        "ck_quotes_revision_lineage_complete",
        "quotes",
        "(revision_of_quote_id IS NULL AND revision_root_quote_id IS NULL "
        "AND revision_number = 1) OR "
        "(revision_of_quote_id IS NOT NULL AND revision_root_quote_id IS NOT NULL "
        "AND revision_number > 1)",
    )
    op.create_check_constraint(
        "ck_quotes_revision_not_self",
        "quotes",
        "revision_of_quote_id IS NULL OR revision_of_quote_id <> id",
    )
    op.create_check_constraint(
        "ck_quotes_revision_root_not_self",
        "quotes",
        "revision_root_quote_id IS NULL OR revision_root_quote_id <> id",
    )
    op.create_foreign_key(
        "fk_quotes_revision_of_quote_id_quotes",
        "quotes",
        "quotes",
        ["revision_of_quote_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_quotes_revision_root_quote_id_quotes",
        "quotes",
        "quotes",
        ["revision_root_quote_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_quotes_revision_of_quote_id",
        "quotes",
        ["revision_of_quote_id"],
        unique=False,
    )
    op.create_index(
        "ix_quotes_revision_root_quote_id",
        "quotes",
        ["revision_root_quote_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_quotes_revision_root_quote_id", table_name="quotes")
    op.drop_index("ix_quotes_revision_of_quote_id", table_name="quotes")
    op.drop_constraint("fk_quotes_revision_root_quote_id_quotes", "quotes", type_="foreignkey")
    op.drop_constraint("fk_quotes_revision_of_quote_id_quotes", "quotes", type_="foreignkey")
    op.drop_constraint("ck_quotes_revision_root_not_self", "quotes", type_="check")
    op.drop_constraint("ck_quotes_revision_not_self", "quotes", type_="check")
    op.drop_constraint("ck_quotes_revision_lineage_complete", "quotes", type_="check")
    op.drop_constraint("ck_quotes_revision_number_positive", "quotes", type_="check")
    op.drop_constraint("ck_quotes_proposal_version_positive", "quotes", type_="check")
    op.drop_column("quotes", "revision_number")
    op.drop_column("quotes", "revision_root_quote_id")
    op.drop_column("quotes", "revision_of_quote_id")
    op.drop_column("quotes", "proposal_version")
    op.drop_column("quotes", "proposal_input_version")
    op.drop_column("quotes", "proposal_input")
