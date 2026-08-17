"""workspace-scoped contact AI memory

Revision ID: 20260817_contact_ai_memory
Revises: 20260813_repair_tasks
Create Date: 2026-08-17 00:00:00.000000

Adds one encrypted aggregate memory per contact plus encrypted, provenance-bearing
facts. Database triggers conservatively invalidate appointment/quote/opportunity
claims whenever their authoritative CRM source row changes, including bulk SQL
updates that bypass ORM service hooks.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260817_contact_ai_memory"
down_revision: str | Sequence[str] | None = "20260813_repair_tasks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "contact_ai_memories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", sa.BigInteger(), nullable=False),
        # EncryptedString is represented by TEXT in DDL and encrypts in the ORM.
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("summary_source_event_id", sa.String(length=255), nullable=True),
        sa.Column("summary_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_contact_ai_memories_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contacts.id"],
            name=op.f("fk_contact_ai_memories_contact_id_contacts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact_ai_memories")),
        sa.UniqueConstraint(
            "workspace_id",
            "contact_id",
            name="uq_contact_ai_memories_workspace_contact",
        ),
        sa.UniqueConstraint(
            "id",
            "workspace_id",
            "contact_id",
            name="uq_contact_ai_memories_id_workspace_contact",
        ),
    )
    op.create_index(
        "ix_contact_ai_memories_workspace_updated",
        "contact_ai_memories",
        ["workspace_id", sa.text("updated_at DESC")],
        unique=False,
    )

    op.create_table(
        "contact_ai_memory_facts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("memory_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", sa.BigInteger(), nullable=False),
        sa.Column("fact_type", sa.String(length=80), nullable=False),
        # EncryptedString is represented by TEXT in DDL and encrypts in the ORM.
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("provenance_event_id", sa.String(length=255), nullable=True),
        sa.Column("provenance_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_record_type", sa.String(length=40), nullable=True),
        sa.Column("source_record_id", sa.String(length=64), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("supersession_state", sa.String(length=20), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_contact_ai_memory_facts_confidence",
        ),
        sa.CheckConstraint(
            "supersession_state IN ('active', 'superseded', 'invalidated')",
            name="ck_contact_ai_memory_facts_supersession_state",
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > observed_at",
            name="ck_contact_ai_memory_facts_expiry",
        ),
        sa.ForeignKeyConstraint(
            ["memory_id", "workspace_id", "contact_id"],
            [
                "contact_ai_memories.id",
                "contact_ai_memories.workspace_id",
                "contact_ai_memories.contact_id",
            ],
            name="fk_contact_ai_memory_facts_scoped_memory",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["provenance_message_id"],
            ["messages.id"],
            name=op.f("fk_contact_ai_memory_facts_provenance_message_id_messages"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by_id"],
            ["contact_ai_memory_facts.id"],
            name=op.f("fk_contact_ai_memory_facts_superseded_by_id_contact_ai_memory_facts"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contact_ai_memory_facts")),
    )
    op.create_index(
        "ix_contact_ai_memory_facts_workspace_contact_active",
        "contact_ai_memory_facts",
        ["workspace_id", "contact_id", sa.text("observed_at DESC")],
        unique=False,
        postgresql_where=sa.text("supersession_state = 'active'"),
    )
    op.create_index(
        "ix_contact_ai_memory_facts_source",
        "contact_ai_memory_facts",
        ["workspace_id", "source_record_type", "source_record_id", "supersession_state"],
        unique=False,
    )
    op.create_index(
        "ix_contact_ai_memory_facts_event",
        "contact_ai_memory_facts",
        ["workspace_id", "contact_id", "provenance_event_id"],
        unique=False,
    )
    op.create_index(
        "ix_contact_ai_memory_facts_message",
        "contact_ai_memory_facts",
        ["provenance_message_id"],
        unique=False,
    )

    # Source rows are the authority. Invalidate any exact-source fact plus broad
    # mutable claims (appointment.*, quote.*, opportunity.*) on every INSERT,
    # UPDATE, or DELETE. This also catches Core/bulk SQL that skips ORM callbacks.
    op.execute(
        """
        CREATE FUNCTION invalidate_contact_ai_memory_source_facts()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            source_kind text := TG_ARGV[0];
            contact_column text := TG_ARGV[1];
            old_row jsonb;
            new_row jsonb;
            old_workspace uuid;
            new_workspace uuid;
            old_contact bigint;
            new_contact bigint;
            old_source_id text;
            new_source_id text;
            invalidated_at timestamptz := statement_timestamp();
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                old_row := to_jsonb(OLD);
                old_workspace := (old_row ->> 'workspace_id')::uuid;
                old_contact := NULLIF(old_row ->> contact_column, '')::bigint;
                old_source_id := old_row ->> 'id';
            END IF;

            IF TG_OP <> 'DELETE' THEN
                new_row := to_jsonb(NEW);
                new_workspace := (new_row ->> 'workspace_id')::uuid;
                new_contact := NULLIF(new_row ->> contact_column, '')::bigint;
                new_source_id := new_row ->> 'id';
            END IF;

            IF old_contact IS NOT NULL THEN
                UPDATE contact_ai_memory_facts
                SET supersession_state = 'invalidated',
                    superseded_at = invalidated_at,
                    updated_at = invalidated_at
                WHERE workspace_id = old_workspace
                  AND contact_id = old_contact
                  AND supersession_state = 'active'
                  AND (
                      (source_record_type = source_kind AND source_record_id = old_source_id)
                      OR fact_type LIKE source_kind || '.%'
                  );
            END IF;

            IF new_contact IS NOT NULL
               AND (old_workspace, old_contact, old_source_id)
                   IS DISTINCT FROM (new_workspace, new_contact, new_source_id) THEN
                UPDATE contact_ai_memory_facts
                SET supersession_state = 'invalidated',
                    superseded_at = invalidated_at,
                    updated_at = invalidated_at
                WHERE workspace_id = new_workspace
                  AND contact_id = new_contact
                  AND supersession_state = 'active'
                  AND (
                      (source_record_type = source_kind AND source_record_id = new_source_id)
                      OR fact_type LIKE source_kind || '.%'
                  );
            END IF;

            RETURN COALESCE(NEW, OLD);
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_appointments_invalidate_contact_ai_memory
        AFTER INSERT OR UPDATE OR DELETE ON appointments
        FOR EACH ROW EXECUTE FUNCTION invalidate_contact_ai_memory_source_facts(
            'appointment', 'contact_id'
        )
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_quotes_invalidate_contact_ai_memory
        AFTER INSERT OR UPDATE OR DELETE ON quotes
        FOR EACH ROW EXECUTE FUNCTION invalidate_contact_ai_memory_source_facts(
            'quote', 'contact_id'
        )
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_opportunities_invalidate_contact_ai_memory
        AFTER INSERT OR UPDATE OR DELETE ON opportunities
        FOR EACH ROW EXECUTE FUNCTION invalidate_contact_ai_memory_source_facts(
            'opportunity', 'primary_contact_id'
        )
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_opportunities_invalidate_contact_ai_memory ON opportunities"
    )
    op.execute("DROP TRIGGER IF EXISTS trg_quotes_invalidate_contact_ai_memory ON quotes")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_appointments_invalidate_contact_ai_memory ON appointments"
    )
    op.execute("DROP FUNCTION IF EXISTS invalidate_contact_ai_memory_source_facts()")

    op.drop_index("ix_contact_ai_memory_facts_message", table_name="contact_ai_memory_facts")
    op.drop_index("ix_contact_ai_memory_facts_event", table_name="contact_ai_memory_facts")
    op.drop_index("ix_contact_ai_memory_facts_source", table_name="contact_ai_memory_facts")
    op.drop_index(
        "ix_contact_ai_memory_facts_workspace_contact_active",
        table_name="contact_ai_memory_facts",
    )
    op.drop_table("contact_ai_memory_facts")

    op.drop_index("ix_contact_ai_memories_workspace_updated", table_name="contact_ai_memories")
    op.drop_table("contact_ai_memories")
