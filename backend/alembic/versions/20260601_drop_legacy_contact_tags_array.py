"""drop legacy contacts.tags array after normalized tag backfill

Revision ID: 20260601_drop_contact_tags
Revises: 20260521_outbound_missions
Create Date: 2026-06-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260601_drop_contact_tags"
down_revision: str | Sequence[str] | None = "20260521_outbound_missions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_BACKFILL_TAGS_SQL = """
    INSERT INTO tags (id, workspace_id, name, color, created_at, updated_at)
    SELECT
        gen_random_uuid(),
        legacy.workspace_id,
        legacy.tag_name,
        '#6366f1',
        NOW(),
        NOW()
    FROM (
        SELECT DISTINCT c.workspace_id, btrim(tag_value) AS tag_name
        FROM contacts AS c
        CROSS JOIN LATERAL unnest(c.tags) AS tag_value
        WHERE c.tags IS NOT NULL
            AND array_length(c.tags, 1) > 0
            AND btrim(tag_value) <> ''
    ) AS legacy
    ON CONFLICT (workspace_id, name) DO NOTHING
"""

_BACKFILL_CONTACT_TAGS_SQL = """
    INSERT INTO contact_tags (id, contact_id, tag_id, created_at)
    SELECT
        gen_random_uuid(),
        c.id,
        t.id,
        NOW()
    FROM contacts AS c
    CROSS JOIN LATERAL unnest(c.tags) AS tag_value
    JOIN tags AS t
        ON t.workspace_id = c.workspace_id
        AND t.name = btrim(tag_value)
    WHERE c.tags IS NOT NULL
        AND array_length(c.tags, 1) > 0
        AND btrim(tag_value) <> ''
    ON CONFLICT (contact_id, tag_id) DO NOTHING
"""

_RESTORE_CONTACT_TAGS_SQL = """
    UPDATE contacts AS c
    SET tags = restored.tag_names
    FROM (
        SELECT
            ct.contact_id,
            array_agg(t.name ORDER BY lower(t.name), t.name) AS tag_names
        FROM contact_tags AS ct
        JOIN tags AS t ON t.id = ct.tag_id
        GROUP BY ct.contact_id
    ) AS restored
    WHERE restored.contact_id = c.id
"""


def upgrade() -> None:
    """Backfill remaining array tags into normalized tables, then drop the array."""
    op.execute(_BACKFILL_TAGS_SQL)
    op.execute(_BACKFILL_CONTACT_TAGS_SQL)
    op.drop_column("contacts", "tags")


def downgrade() -> None:
    """Restore the legacy array from normalized tags for rollback safety."""
    op.add_column(
        "contacts",
        sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=True),
    )
    op.execute(_RESTORE_CONTACT_TAGS_SQL)
