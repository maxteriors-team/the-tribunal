"""pipeline restructure

Reshapes the default sales pipeline from ``New / Qualified / Proposal / Won /
Lost`` to the six operator-facing stages ``Qualified · Visit/Demo Scheduled ·
Quote · Quote Sent / Follow Up · Won · Lost``, and lands the opportunities that
were sitting in ``New``.

Only pipelines whose stage-name set is *exactly* the old default are touched;
anything an operator customised through Manage Stages is skipped untouched.

Stage rows are renamed and reordered in place, never deleted: ``stage_id`` stays
stable so opportunities follow their column with zero row rewrites, and
``PipelineStage.opportunities`` declares ``cascade="all, delete-orphan"``, which
makes deleting a stage through the ORM a data-loss trap. Everything here is Core
SQL for that reason.

Opportunities in the old ``New`` stage split two ways:
  * auto-created and never touched (inbound source, no amount, no owner, no line
    items, no activities, still open) -> ``abandoned`` + ``is_active = false``;
  * everything else -> moved to ``Qualified`` with a ``stage_changed`` activity.

Nothing is deleted from ``opportunities``. ``pipeline_restructure_backup``
records the prior state of every row this migration writes so ``downgrade()``
restores it exactly; it is dropped on downgrade.

Revision ID: c2e043d6bb65
Revises: 01126145aada
Create Date: 2026-08-04 20:03:13.586319

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c2e043d6bb65"
down_revision: str | Sequence[str] | None = "01126145aada"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


BACKUP_TABLE = "pipeline_restructure_backup"

# Only pipelines with exactly this stage-name set are eligible.
OLD_DEFAULT_STAGE_NAMES = ["Lost", "New", "Proposal", "Qualified", "Won"]

# Where the old "New" column is parked: renamed and pushed past the real stages
# so the board reads as the operator's six-stage pipeline.
PARKED_STAGE_NAME = "Unqualified (archived)"
PARKED_STAGE_ORDER = 6

# Inbound funnels that open a card without a human deciding to (see
# app/services/opportunities/lead_opportunity.py call sites).
AUTO_CREATED_SOURCES = ["lead_form", "offer", "embed", "inbound_sms", "inbound_call"]

STAGE_CHANGE_DESCRIPTION = (
    "Pipeline restructure: moved from New to Qualified when the pipeline stages were reshaped."
)

# Existing stages: old name -> (new name, order, probability).
_STAGE_UPDATES = [
    ("Qualified", "Qualified", 0, 25),
    ("Proposal", "Quote", 2, 60),
    ("Won", "Won", 4, 100),
    ("Lost", "Lost", 5, 0),
]

# Stages the six-stage pipeline adds: (name, order, probability).
_STAGE_INSERTS = [
    ("Visit/Demo Scheduled", 1, 45),
    ("Quote Sent / Follow Up", 3, 75),
]


def _matching_pipeline_ids(conn: sa.Connection) -> list[uuid.UUID]:
    """Pipelines whose stages are exactly the untouched old default set."""
    rows = conn.execute(
        sa.text(
            """
            SELECT s.pipeline_id
            FROM pipeline_stages s
            GROUP BY s.pipeline_id
            HAVING count(*) = :expected_count
               AND array_agg(DISTINCT s.name::text ORDER BY s.name::text) = :names
            """
        ).bindparams(
            sa.bindparam("expected_count", len(OLD_DEFAULT_STAGE_NAMES)),
            sa.bindparam("names", OLD_DEFAULT_STAGE_NAMES, type_=sa.ARRAY(sa.Text)),
        )
    ).all()
    return [row.pipeline_id for row in rows]


def _create_backup_table(conn: sa.Connection) -> None:
    conn.execute(
        sa.text(
            f"""
            CREATE TABLE {BACKUP_TABLE} (
                id uuid PRIMARY KEY,
                kind varchar(20) NOT NULL,
                row_id uuid NOT NULL,
                stage_id uuid,
                status varchar(20),
                is_active boolean,
                probability integer,
                name varchar(255),
                "order" integer,
                stage_changed_at timestamptz,
                created_by_migration boolean NOT NULL DEFAULT false
            )
            """
        )
    )


def _backup_stage(conn: sa.Connection, row: sa.Row, *, created_by_migration: bool) -> None:
    conn.execute(
        sa.text(
            f"""
            INSERT INTO {BACKUP_TABLE}
                (id, kind, row_id, name, "order", probability, created_by_migration)
            VALUES (:id, 'stage', :row_id, :name, :order, :probability, :created_by_migration)
            """
        ),
        {
            "id": uuid.uuid4(),
            "row_id": row.id,
            "name": row.name,
            "order": row.order,
            "probability": row.probability,
            "created_by_migration": created_by_migration,
        },
    )


def _restructure_stages(conn: sa.Connection, pipeline_id: uuid.UUID) -> dict[str, uuid.UUID]:
    """Rename/reorder the old stages in place and add the two new ones.

    Returns the pipeline's stage ids keyed by their *old* name.
    """
    stages = conn.execute(
        sa.text(
            """
            SELECT id, name, "order", probability
            FROM pipeline_stages
            WHERE pipeline_id = :pipeline_id
            """
        ),
        {"pipeline_id": pipeline_id},
    ).all()
    by_old_name = {row.name: row for row in stages}

    for row in stages:
        _backup_stage(conn, row, created_by_migration=False)

    for old_name, new_name, order, probability in _STAGE_UPDATES:
        conn.execute(
            sa.text(
                """
                UPDATE pipeline_stages
                SET name = :name, "order" = :order, probability = :probability,
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {
                "id": by_old_name[old_name].id,
                "name": new_name,
                "order": order,
                "probability": probability,
            },
        )

    # "New" is renamed and parked, never deleted: the row is what makes the
    # downgrade exact, and deleting a stage risks the delete-orphan cascade.
    conn.execute(
        sa.text(
            """
            UPDATE pipeline_stages
            SET name = :name, "order" = :order, updated_at = now()
            WHERE id = :id
            """
        ),
        {
            "id": by_old_name["New"].id,
            "name": PARKED_STAGE_NAME,
            "order": PARKED_STAGE_ORDER,
        },
    )

    for name, order, probability in _STAGE_INSERTS:
        inserted = conn.execute(
            sa.text(
                """
                INSERT INTO pipeline_stages
                    (id, pipeline_id, name, "order", probability, stage_type,
                     created_at, updated_at)
                VALUES (:id, :pipeline_id, :name, :order, :probability, 'active', now(), now())
                RETURNING id, name, "order", probability
                """
            ),
            {
                "id": uuid.uuid4(),
                "pipeline_id": pipeline_id,
                "name": name,
                "order": order,
                "probability": probability,
            },
        ).one()
        _backup_stage(conn, inserted, created_by_migration=True)

    return {row.name: row.id for row in stages}


def _backup_opportunities(conn: sa.Connection, opportunity_ids: Sequence[uuid.UUID]) -> None:
    if not opportunity_ids:
        return
    conn.execute(
        sa.text(
            f"""
            INSERT INTO {BACKUP_TABLE}
                (id, kind, row_id, stage_id, status, is_active, probability, stage_changed_at)
            SELECT gen_random_uuid(), 'opportunity', o.id, o.stage_id, o.status::text,
                   o.is_active, o.probability, o.stage_changed_at
            FROM opportunities o
            WHERE o.id = ANY(:ids)
            """
        ).bindparams(sa.bindparam("ids", list(opportunity_ids), type_=sa.ARRAY(sa.Uuid))),
    )


def _split_new_stage_opportunities(
    conn: sa.Connection,
    *,
    new_stage_id: uuid.UUID,
    qualified_stage_id: uuid.UUID,
) -> None:
    """Archive untouched auto-created cards; promote everything else to Qualified."""
    select_archivable = sa.text(
        """
        SELECT o.id
        FROM opportunities o
        WHERE o.stage_id = :stage_id
          AND o.status = 'open'
          AND o.source = ANY(:sources)
          AND o.amount IS NULL
          AND o.assigned_user_id IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM opportunity_line_items li WHERE li.opportunity_id = o.id
          )
          AND NOT EXISTS (
              SELECT 1 FROM opportunity_activities a WHERE a.opportunity_id = o.id
          )
        """
    ).bindparams(
        sa.bindparam("stage_id", new_stage_id),
        sa.bindparam("sources", AUTO_CREATED_SOURCES, type_=sa.ARRAY(sa.Text)),
    )
    archivable = list(conn.execute(select_archivable).scalars().all())

    _backup_opportunities(conn, archivable)
    if archivable:
        # stage_id is deliberately left pointing at the parked stage: the card is
        # closed out, not moved, and the row itself is never deleted.
        conn.execute(
            sa.text(
                """
                UPDATE opportunities
                SET status = 'abandoned', is_active = false, updated_at = now()
                WHERE id = ANY(:ids)
                """
            ).bindparams(sa.bindparam("ids", archivable, type_=sa.ARRAY(sa.Uuid))),
        )

    select_promotable = sa.text(
        """
        SELECT o.id
        FROM opportunities o
        WHERE o.stage_id = :stage_id
          AND NOT (o.id = ANY(:archived))
        """
    ).bindparams(
        sa.bindparam("stage_id", new_stage_id),
        sa.bindparam("archived", archivable, type_=sa.ARRAY(sa.Uuid)),
    )
    promotable = list(conn.execute(select_promotable).scalars().all())

    if not promotable:
        return

    _backup_opportunities(conn, promotable)
    conn.execute(
        sa.text(
            """
            UPDATE opportunities
            SET stage_id = :qualified_stage_id, probability = 25,
                stage_changed_at = now(), updated_at = now()
            WHERE id = ANY(:ids)
            """
        ).bindparams(
            sa.bindparam("qualified_stage_id", qualified_stage_id),
            sa.bindparam("ids", promotable, type_=sa.ARRAY(sa.Uuid)),
        ),
    )
    conn.execute(
        sa.text(
            """
            INSERT INTO opportunity_activities
                (id, opportunity_id, user_id, activity_type, old_value, new_value,
                 description, created_at)
            SELECT gen_random_uuid(), o.id, NULL, 'stage_changed', 'New', 'Qualified',
                   :description, now()
            FROM opportunities o
            WHERE o.id = ANY(:ids)
            """
        ).bindparams(
            sa.bindparam("description", STAGE_CHANGE_DESCRIPTION),
            sa.bindparam("ids", promotable, type_=sa.ARRAY(sa.Uuid)),
        ),
    )


def upgrade() -> None:
    conn = op.get_bind()
    _create_backup_table(conn)

    for pipeline_id in _matching_pipeline_ids(conn):
        stage_ids_by_old_name = _restructure_stages(conn, pipeline_id)
        _split_new_stage_opportunities(
            conn,
            new_stage_id=stage_ids_by_old_name["New"],
            qualified_stage_id=stage_ids_by_old_name["Qualified"],
        )


def downgrade() -> None:
    conn = op.get_bind()
    if not sa.inspect(conn).has_table(BACKUP_TABLE):
        # upgrade() never ran against this database (fresh CI schema).
        return

    # Activity rows this migration wrote — matched on the exact description it
    # stamped, so operator-created activities are never touched.
    conn.execute(
        sa.text(
            """
            DELETE FROM opportunity_activities
            WHERE activity_type = 'stage_changed'
              AND user_id IS NULL
              AND description = :description
            """
        ).bindparams(sa.bindparam("description", STAGE_CHANGE_DESCRIPTION)),
    )

    conn.execute(
        sa.text(
            f"""
            UPDATE opportunities o
            SET stage_id = b.stage_id,
                status = b.status::opportunity_status,
                is_active = b.is_active,
                probability = b.probability,
                stage_changed_at = b.stage_changed_at,
                updated_at = now()
            FROM {BACKUP_TABLE} b
            WHERE b.kind = 'opportunity' AND b.row_id = o.id
            """
        )
    )

    # Core DELETE, not the ORM: the delete-orphan cascade would take the stage's
    # opportunities with it. These two stages were created by upgrade() and hold
    # no cards, and the FK is ON DELETE SET NULL regardless.
    conn.execute(
        sa.text(
            f"""
            DELETE FROM pipeline_stages s
            USING {BACKUP_TABLE} b
            WHERE b.kind = 'stage' AND b.created_by_migration AND b.row_id = s.id
            """
        )
    )

    conn.execute(
        sa.text(
            f"""
            UPDATE pipeline_stages s
            SET name = b.name, "order" = b."order", probability = b.probability,
                updated_at = now()
            FROM {BACKUP_TABLE} b
            WHERE b.kind = 'stage' AND NOT b.created_by_migration AND b.row_id = s.id
            """
        )
    )

    op.drop_table(BACKUP_TABLE)
