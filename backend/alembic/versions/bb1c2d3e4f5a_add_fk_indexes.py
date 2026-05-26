"""Add missing FK column indexes across models.

Revision ID: bb1c2d3e4f5a
Revises: 20260520_merge_post_heads
Create Date: 2026-05-15 12:00:00.000000

Note (2026-05-20): renamed from duplicate ``a9b0c1d2e3f4`` to ``bb1c2d3e4f5a``
to resolve a triple-collision on that revision id (the original is
``a9b0c1d2e3f4_add_assistant_conversation_tables.py``). Re-parented to chain
after ``20260520_merge_post_heads`` because the DDL touches tables
(``invitations``, ``opportunities``, ``message_tests``, etc.) created by
feature migrations that landed after ``z8a9b0c1d2e3``.

Adds indexes to foreign key columns that were missing them. FK columns
without indexes cause slow lookups, slow cascading deletes, and lock
contention. These indexes match `index=True` markers added to the ORM
models in the same commit.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bb1c2d3e4f5a"
down_revision: str | None = "20260520_merge_post_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (index_name, table_name, column_name)
_INDEXES: list[tuple[str, str, str]] = [
    ("ix_call_feedback_user_id", "call_feedback", "user_id"),
    ("ix_email_events_workspace_id", "email_events", "workspace_id"),
    ("ix_email_events_message_id", "email_events", "message_id"),
    ("ix_human_nudges_assigned_to_user_id", "human_nudges", "assigned_to_user_id"),
    (
        "ix_improvement_suggestions_source_version_id",
        "improvement_suggestions",
        "source_version_id",
    ),
    (
        "ix_improvement_suggestions_reviewed_by_id",
        "improvement_suggestions",
        "reviewed_by_id",
    ),
    (
        "ix_improvement_suggestions_created_version_id",
        "improvement_suggestions",
        "created_version_id",
    ),
    ("ix_workspace_invitations_invited_by_id", "workspace_invitations", "invited_by_id"),
    ("ix_lead_magnet_leads_source_offer_id", "lead_magnet_leads", "source_offer_id"),
    ("ix_message_tests_winning_variant_id", "message_tests", "winning_variant_id"),
    (
        "ix_message_tests_converted_to_campaign_id",
        "message_tests",
        "converted_to_campaign_id",
    ),
    ("ix_opportunities_closed_by_id", "opportunities", "closed_by_id"),
    ("ix_opportunity_activities_user_id", "opportunity_activities", "user_id"),
    ("ix_pending_actions_reviewed_by_id", "pending_actions", "reviewed_by_id"),
    ("ix_prompt_versions_created_by_id", "prompt_versions", "created_by_id"),
    ("ix_prompt_versions_parent_version_id", "prompt_versions", "parent_version_id"),
    ("ix_contact_tags_contact_id", "contact_tags", "contact_id"),
    ("ix_contact_tags_tag_id", "contact_tags", "tag_id"),
]


def upgrade() -> None:
    # Use ``IF NOT EXISTS`` so this bulk-index migration is idempotent against
    # earlier feature migrations that may have already created one of these
    # indexes (e.g. ``ec02f3a4b5c6_resend_email_tracking`` already creates
    # ``ix_email_events_message_id``). ``op.create_index`` doesn't expose an
    # ``if_not_exists`` flag, so we fall through to raw SQL.
    #
    # Wrap the CREATE INDEX in a ``DO`` block guarded by ``to_regclass`` so
    # rows referencing a table that was later renamed/dropped (e.g. the
    # ``invitations`` -> ``workspace_invitations`` rename) skip cleanly instead
    # of aborting the entire upgrade transaction.
    for index_name, table_name, column_name in _INDEXES:
        create_index_sql = (
            f'CREATE INDEX IF NOT EXISTS "{index_name}" '
            f'ON "{table_name}" ("{column_name}")'
        )
        op.execute(
            f"""
            DO $$
            BEGIN
                IF to_regclass('public.{table_name}') IS NOT NULL THEN
                    EXECUTE '{create_index_sql}';
                END IF;
            END $$;
            """
        )


def downgrade() -> None:
    for index_name, _table_name, _ in reversed(_INDEXES):
        op.execute(f'DROP INDEX IF EXISTS "{index_name}"')
