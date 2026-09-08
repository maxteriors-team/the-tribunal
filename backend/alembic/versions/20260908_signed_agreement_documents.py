"""Add the e-signature ceremony to quotes and the signed agreement document store.

Revision ID: 20260908_signed_agreements
Revises: 20260904_proposal_payments
Create Date: 2026-09-08

Additive only. Every existing approved quote keeps its NULL signature columns,
which is the honest representation of a one-click acceptance made before the
ceremony existed -- backfilling them would fabricate consent events.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260908_signed_agreements"
down_revision: str | Sequence[str] | None = "20260904_proposal_payments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # server_default is required, not cosmetic: the column is NOT NULL and the
    # table has live rows, so without it this ALTER fails on any real database.
    op.add_column(
        "quotes",
        sa.Column("terms_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("quotes", sa.Column("signed_name", sa.String(length=120), nullable=True))
    op.add_column("quotes", sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True))
    # TEXT, not INET: the value is Fernet-encrypted at rest by EncryptedString,
    # so the database stores ciphertext and cannot use an IP-typed column.
    op.add_column("quotes", sa.Column("signed_ip", sa.Text(), nullable=True))
    op.add_column(
        "quotes", sa.Column("econsent_accepted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "quotes",
        sa.Column("cancellation_acknowledged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("quotes", sa.Column("signed_terms_snapshot", sa.Text(), nullable=True))

    op.create_check_constraint(
        "ck_quotes_terms_version_positive", "quotes", "terms_version >= 1"
    )
    # All five signature facts, or none. A half-recorded ceremony rendered into a
    # legal PDF asserts a consent event the data cannot support.
    op.create_check_constraint(
        "ck_quotes_signature_complete",
        "quotes",
        "(signed_name IS NULL AND signed_at IS NULL AND signed_ip IS NULL "
        "AND econsent_accepted_at IS NULL AND cancellation_acknowledged_at IS NULL) OR "
        "(signed_name IS NOT NULL AND signed_at IS NOT NULL AND signed_ip IS NOT NULL "
        "AND econsent_accepted_at IS NOT NULL AND cancellation_acknowledged_at IS NOT NULL)",
    )

    op.create_table(
        "signed_agreement_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quote_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=127), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("terms_version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        # RESTRICT: deleting a quote must not silently destroy the evidence that
        # a contract was formed.
        sa.ForeignKeyConstraint(["quote_id"], ["quotes.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("quote_id", name="uq_signed_agreement_documents_quote"),
    )
    op.create_index(
        "ix_signed_agreement_documents_workspace_id",
        "signed_agreement_documents",
        ["workspace_id"],
    )
    op.create_index(
        "ix_signed_agreement_documents_quote_id",
        "signed_agreement_documents",
        ["quote_id"],
    )
    op.create_index(
        "ix_signed_agreement_documents_workspace_generated",
        "signed_agreement_documents",
        ["workspace_id", "generated_at"],
    )


def downgrade() -> None:
    # Dropping this table destroys signed agreements irrecoverably -- they exist
    # nowhere else. Reversibility is kept because CI proves up/down/up, but a
    # production downgrade past this revision needs a dump taken first.
    op.drop_index(
        "ix_signed_agreement_documents_workspace_generated",
        table_name="signed_agreement_documents",
    )
    op.drop_index(
        "ix_signed_agreement_documents_quote_id", table_name="signed_agreement_documents"
    )
    op.drop_index(
        "ix_signed_agreement_documents_workspace_id", table_name="signed_agreement_documents"
    )
    op.drop_table("signed_agreement_documents")

    op.drop_constraint("ck_quotes_signature_complete", "quotes", type_="check")
    op.drop_constraint("ck_quotes_terms_version_positive", "quotes", type_="check")
    op.drop_column("quotes", "signed_terms_snapshot")
    op.drop_column("quotes", "cancellation_acknowledged_at")
    op.drop_column("quotes", "econsent_accepted_at")
    op.drop_column("quotes", "signed_ip")
    op.drop_column("quotes", "signed_at")
    op.drop_column("quotes", "signed_name")
    op.drop_column("quotes", "terms_version")
