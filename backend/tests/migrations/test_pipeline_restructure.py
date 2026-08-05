"""Integration tests for the ``c2e043d6bb65`` pipeline-restructure migration.

``make ci.migrations`` runs ``upgrade -> check -> downgrade -> upgrade`` against
an *empty* database, so it proves the SQL parses but never exercises the data
transform. These tests seed the old five-stage shape, run the migration's
``upgrade()`` and ``downgrade()`` bodies against a real Postgres connection, and
assert:

* the old default pipeline is reshaped into the six operator-facing stages;
* an untouched auto-created card is archived, not deleted;
* a human-touched card is moved to ``Qualified`` with an audit activity;
* a pipeline an operator customised is skipped entirely;
* ``downgrade()`` restores every field it rewrote.

Everything runs inside one transaction that is rolled back, so the developer
database is left untouched. The migration bodies are synchronous (they call
``op.get_bind()``), so each test drives them through ``AsyncConnection.run_sync``
— the project ships only the asyncpg driver.
"""

from __future__ import annotations

import importlib.util
import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "c2e043d6bb65_pipeline_restructure.py"
)

OLD_STAGES = [
    ("New", 0, 0, "active"),
    ("Qualified", 1, 25, "active"),
    ("Proposal", 2, 50, "active"),
    ("Won", 3, 100, "won"),
    ("Lost", 4, 0, "lost"),
]

NEW_STAGE_SHAPE = [
    ("Qualified", 0, 25),
    ("Visit/Demo Scheduled", 1, 45),
    ("Quote", 2, 60),
    ("Quote Sent / Follow Up", 3, 75),
    ("Won", 4, 100),
    ("Lost", 5, 0),
    ("Unqualified (archived)", 6, 0),
]


def _load_migration() -> ModuleType:
    """Import the migration by path — ``alembic/versions`` is not a package."""
    spec = importlib.util.spec_from_file_location("pipeline_restructure", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()


def _run_migration_step(conn: Connection, step: str) -> None:
    """Execute the migration's ``upgrade``/``downgrade`` with ``op`` bound to ``conn``."""
    context = MigrationContext.configure(conn)
    with Operations.context(context):
        getattr(migration, step)()


def _seed_workspace(conn: Connection) -> uuid.UUID:
    workspace_id = uuid.uuid4()
    conn.execute(
        sa.text(
            """
            INSERT INTO workspaces
                (id, name, slug, settings, is_active, created_at, updated_at)
            VALUES (:id, 'Restructure Test', :slug, '{}'::jsonb, true, now(), now())
            """
        ),
        {"id": workspace_id, "slug": f"restructure-{uuid.uuid4().hex[:8]}"},
    )
    return workspace_id


def _seed_pipeline(
    conn: Connection,
    workspace_id: uuid.UUID,
    *,
    name: str,
    stages: list[tuple[str, int, int, str]],
) -> tuple[uuid.UUID, dict[str, uuid.UUID]]:
    pipeline_id = uuid.uuid4()
    conn.execute(
        sa.text(
            """
            INSERT INTO pipelines (id, workspace_id, name, is_active, created_at, updated_at)
            VALUES (:id, :workspace_id, :name, true, now(), now())
            """
        ),
        {"id": pipeline_id, "workspace_id": workspace_id, "name": name},
    )
    stage_ids: dict[str, uuid.UUID] = {}
    for stage_name, order, probability, stage_type in stages:
        stage_id = uuid.uuid4()
        conn.execute(
            sa.text(
                """
                INSERT INTO pipeline_stages
                    (id, pipeline_id, name, "order", probability, stage_type,
                     created_at, updated_at)
                VALUES (:id, :pipeline_id, :name, :order, :probability, :stage_type,
                        now(), now())
                """
            ),
            {
                "id": stage_id,
                "pipeline_id": pipeline_id,
                "name": stage_name,
                "order": order,
                "probability": probability,
                "stage_type": stage_type,
            },
        )
        stage_ids[stage_name] = stage_id
    return pipeline_id, stage_ids


def _seed_opportunity(
    conn: Connection,
    workspace_id: uuid.UUID,
    pipeline_id: uuid.UUID,
    stage_id: uuid.UUID,
    *,
    name: str,
    source: str | None,
    amount: float | None = None,
    assigned_user_id: int | None = None,
    status: str = "open",
    probability: int = 0,
) -> uuid.UUID:
    opportunity_id = uuid.uuid4()
    conn.execute(
        sa.text(
            """
            INSERT INTO opportunities
                (id, workspace_id, pipeline_id, stage_id, name, source, amount,
                 assigned_user_id, status, probability, currency, is_active,
                 created_at, updated_at)
            VALUES (:id, :workspace_id, :pipeline_id, :stage_id, :name, :source, :amount,
                    :assigned_user_id, :status, :probability, 'USD', true, now(), now())
            """
        ),
        {
            "id": opportunity_id,
            "workspace_id": workspace_id,
            "pipeline_id": pipeline_id,
            "stage_id": stage_id,
            "name": name,
            "source": source,
            "amount": amount,
            "assigned_user_id": assigned_user_id,
            "status": status,
            "probability": probability,
        },
    )
    return opportunity_id


def _stage_shape(conn: Connection, pipeline_id: uuid.UUID) -> list[tuple[str, int, int]]:
    rows = conn.execute(
        sa.text(
            """
            SELECT name, "order", probability
            FROM pipeline_stages
            WHERE pipeline_id = :pipeline_id
            ORDER BY "order"
            """
        ),
        {"pipeline_id": pipeline_id},
    ).all()
    return [(row.name, row.order, row.probability) for row in rows]


def _opportunity_row(conn: Connection, opportunity_id: uuid.UUID) -> sa.Row[Any]:
    return conn.execute(
        sa.text(
            """
            SELECT stage_id, status::text AS status, is_active, probability, stage_changed_at
            FROM opportunities
            WHERE id = :id
            """
        ),
        {"id": opportunity_id},
    ).one()


class _Fixture:
    """Seeded database state plus the ids the assertions need."""

    def __init__(self, conn: Connection) -> None:
        self.conn = conn
        # Restore the pre-migration precondition. ``upgrade()`` leaves the scratch
        # table behind on purpose (only ``downgrade()`` drops it), so a developer
        # database that already ran ``make migrate`` still has it. The drop is
        # inside the test transaction, so the real table comes back on rollback.
        conn.execute(sa.text(f"DROP TABLE IF EXISTS {migration.BACKUP_TABLE}"))
        self.workspace_id = _seed_workspace(conn)
        self.pipeline_id, self.stage_ids = _seed_pipeline(
            conn, self.workspace_id, name="Sales Pipeline", stages=OLD_STAGES
        )
        # An operator-customised pipeline: same workspace, different stage names.
        self.custom_pipeline_id, self.custom_stage_ids = _seed_pipeline(
            conn,
            self.workspace_id,
            name="Custom Pipeline",
            stages=[
                ("New", 0, 0, "active"),
                ("Site Visit", 1, 40, "active"),
                ("Won", 2, 100, "won"),
            ],
        )

        new_stage = self.stage_ids["New"]
        # Auto-created and never touched -> archived.
        self.auto_card = _seed_opportunity(
            conn,
            self.workspace_id,
            self.pipeline_id,
            new_stage,
            name="Untouched inbound lead",
            source="lead_form",
        )
        # Human-touched (has an owner and an amount) -> promoted to Qualified.
        self.touched_card = _seed_opportunity(
            conn,
            self.workspace_id,
            self.pipeline_id,
            new_stage,
            name="Real deal",
            source="lead_form",
            amount=2500,
            status="open",
        )
        # Manually created -> promoted to Qualified even with no amount.
        self.manual_card = _seed_opportunity(
            conn,
            self.workspace_id,
            self.pipeline_id,
            new_stage,
            name="Manual deal",
            source="manual",
        )
        # Already past New -> follows its renamed stage without a row rewrite.
        self.proposal_card = _seed_opportunity(
            conn,
            self.workspace_id,
            self.pipeline_id,
            self.stage_ids["Proposal"],
            name="Quoted deal",
            source="manual",
            amount=900,
            probability=50,
        )
        # In the custom pipeline's "New" -> must not be touched at all.
        self.custom_card = _seed_opportunity(
            conn,
            self.workspace_id,
            self.custom_pipeline_id,
            self.custom_stage_ids["New"],
            name="Custom pipeline lead",
            source="lead_form",
        )


@pytest_asyncio.fixture
async def run_seeded() -> AsyncIterator[Callable[[Callable[[_Fixture], None]], Any]]:
    """Run a sync test body against a seeded transaction that is always rolled back.

    Uses its own ``NullPool`` engine rather than ``app.db.session.engine``: the
    shared engine pools connections bound to whichever event loop opened them,
    and pytest-asyncio gives each test a fresh loop.
    """
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with engine.connect() as async_conn:
            transaction = await async_conn.begin()
            try:

                async def run(body: Callable[[_Fixture], None]) -> None:
                    await async_conn.run_sync(lambda conn: body(_Fixture(conn)))

                yield run
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


RunSeeded = Callable[[Callable[[_Fixture], None]], Any]


async def test_upgrade_reshapes_default_pipeline(run_seeded: RunSeeded) -> None:
    def body(seeded: _Fixture) -> None:
        conn = seeded.conn
        _run_migration_step(conn, "upgrade")

        assert _stage_shape(conn, seeded.pipeline_id) == NEW_STAGE_SHAPE

        # The renamed rows kept their ids, so cards followed their column for free.
        assert (
            conn.execute(
                sa.text("SELECT name FROM pipeline_stages WHERE id = :id"),
                {"id": seeded.stage_ids["Proposal"]},
            ).scalar_one()
            == "Quote"
        )
        assert _opportunity_row(conn, seeded.proposal_card).stage_id == seeded.stage_ids["Proposal"]

    await run_seeded(body)


async def test_upgrade_archives_untouched_auto_created_card(run_seeded: RunSeeded) -> None:
    def body(seeded: _Fixture) -> None:
        conn = seeded.conn
        _run_migration_step(conn, "upgrade")

        row = _opportunity_row(conn, seeded.auto_card)
        assert row.status == "abandoned"
        assert row.is_active is False
        # Parked, not deleted: the row survives and still points at its old column.
        assert row.stage_id == seeded.stage_ids["New"]
        assert (
            conn.execute(
                sa.text("SELECT count(*) FROM opportunities WHERE id = :id"),
                {"id": seeded.auto_card},
            ).scalar_one()
            == 1
        )

    await run_seeded(body)


async def test_upgrade_promotes_touched_cards_with_audit_trail(run_seeded: RunSeeded) -> None:
    def body(seeded: _Fixture) -> None:
        conn = seeded.conn
        _run_migration_step(conn, "upgrade")

        for card in (seeded.touched_card, seeded.manual_card):
            row = _opportunity_row(conn, card)
            assert row.stage_id == seeded.stage_ids["Qualified"]
            assert row.status == "open"
            assert row.is_active is True
            assert row.probability == 25
            assert row.stage_changed_at is not None

            activity = conn.execute(
                sa.text(
                    """
                    SELECT activity_type, user_id, old_value, new_value
                    FROM opportunity_activities
                    WHERE opportunity_id = :id
                    """
                ),
                {"id": card},
            ).one()
            assert activity.activity_type == "stage_changed"
            assert activity.user_id is None
            assert (activity.old_value, activity.new_value) == ("New", "Qualified")

    await run_seeded(body)


async def test_upgrade_skips_operator_customised_pipeline(run_seeded: RunSeeded) -> None:
    def body(seeded: _Fixture) -> None:
        conn = seeded.conn
        _run_migration_step(conn, "upgrade")

        assert _stage_shape(conn, seeded.custom_pipeline_id) == [
            ("New", 0, 0),
            ("Site Visit", 1, 40),
            ("Won", 2, 100),
        ]
        row = _opportunity_row(conn, seeded.custom_card)
        assert row.stage_id == seeded.custom_stage_ids["New"]
        assert row.status == "open"
        assert row.is_active is True

    await run_seeded(body)


async def test_downgrade_restores_previous_state(run_seeded: RunSeeded) -> None:
    def body(seeded: _Fixture) -> None:
        conn = seeded.conn
        cards = (
            seeded.auto_card,
            seeded.touched_card,
            seeded.manual_card,
            seeded.proposal_card,
            seeded.custom_card,
        )
        before_stages = _stage_shape(conn, seeded.pipeline_id)
        before_opportunities = {card: tuple(_opportunity_row(conn, card)) for card in cards}

        _run_migration_step(conn, "upgrade")
        _run_migration_step(conn, "downgrade")

        assert _stage_shape(conn, seeded.pipeline_id) == before_stages
        for card, before in before_opportunities.items():
            assert tuple(_opportunity_row(conn, card)) == before

        # The stages upgrade() invented and the activities it wrote are both
        # gone, and so is the scratch table.
        assert (
            conn.execute(
                sa.text(
                    """
                    SELECT count(*) FROM pipeline_stages
                    WHERE pipeline_id = :pipeline_id
                      AND name IN ('Visit/Demo Scheduled', 'Quote Sent / Follow Up')
                    """
                ),
                {"pipeline_id": seeded.pipeline_id},
            ).scalar_one()
            == 0
        )
        assert (
            conn.execute(
                sa.text(
                    """
                    SELECT count(*) FROM opportunity_activities a
                    JOIN opportunities o ON o.id = a.opportunity_id
                    WHERE o.workspace_id = :workspace_id
                    """
                ),
                {"workspace_id": seeded.workspace_id},
            ).scalar_one()
            == 0
        )
        assert sa.inspect(conn).has_table(migration.BACKUP_TABLE) is False

    await run_seeded(body)
