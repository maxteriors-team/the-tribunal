"""Real-Postgres proof that a malformed settings blob cannot kill the quote workers.

Both quote sequences narrow their fetch with a SQL predicate on the workspace
settings JSONB. That predicate spans **every** workspace, so its failure mode is
global: if one row makes the expression raise, the fetch aborts and both
sequences stop for every tenant — silently, because the worker heartbeat keeps
``/readyz`` green while each tick dies.

A mocked session cannot prove anything here, because the raise happens inside
the database. These tests insert genuinely malformed rows and run the real ORM
predicate against real Postgres.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text

from app.db.session import AsyncSessionLocal, engine
from app.models.workspace import Workspace
from app.services.quotes.followup_config import SETTINGS_KEY as POST_ESTIMATE_KEY
from app.services.quotes.revival_config import SETTINGS_KEY as REVIVAL_KEY

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# Values a hand-edit, a migration, or an older client could leave behind.
# ``CAST(... AS BOOLEAN)`` raises on every one of these except 1/null/false.
MALFORMED = ['"yes"', '"maybe"', "{}", "[]", "1", "null", "false"]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    """Dispose the shared asyncpg pool around each test.

    pytest-asyncio gives each test a fresh event loop; without disposing, the
    engine's pool can hold connections bound to a closed loop.
    """
    await engine.dispose()
    yield
    await engine.dispose()


async def _insert(db, slug: str, key: str, stored: str) -> None:
    await db.execute(
        text(
            "INSERT INTO workspaces (id, name, slug, settings, is_active,"
            " created_at, updated_at) VALUES (gen_random_uuid(), :n, :s,"
            f' \'{{"{key}": {{"enabled": {stored}}}}}\'::jsonb, true, now(), now())'
        ),
        {"n": "predicate probe", "s": slug},
    )


@pytest.mark.parametrize(
    ("key", "column_key"),
    [
        ("post_estimate", POST_ESTIMATE_KEY),
        ("revival", REVIVAL_KEY),
    ],
)
async def test_enabled_predicate_never_raises_on_hand_edited_json(
    key: str, column_key: str
) -> None:
    """Garbage must read as not-enabled instead of aborting the whole fetch."""
    slugs = [f"predicate-probe-{uuid.uuid4().hex[:12]}" for _ in MALFORMED]
    enabled_slug = f"predicate-probe-{uuid.uuid4().hex[:12]}"

    async with AsyncSessionLocal() as db:
        try:
            for slug, stored in zip(slugs, MALFORMED, strict=True):
                await _insert(db, slug, column_key, stored)
            await _insert(db, enabled_slug, column_key, "true")
            await db.commit()

            # The exact predicate both workers' fetches use.
            matched = (
                (
                    await db.execute(
                        select(Workspace.slug).where(
                            Workspace.settings[column_key]["enabled"].astext == "true",
                            Workspace.slug.in_([*slugs, enabled_slug]),
                        )
                    )
                )
                .scalars()
                .all()
            )

            assert list(matched) == [enabled_slug], (
                "only a real JSON true may enable the sequence, and malformed values must not raise"
            )
        finally:
            await db.execute(
                text("DELETE FROM workspaces WHERE slug = ANY(:s)"),
                {"s": [*slugs, enabled_slug]},
            )
            await db.commit()
