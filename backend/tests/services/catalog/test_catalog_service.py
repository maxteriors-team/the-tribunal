"""Real-DB integration tests for :class:`CatalogService`.

These hit Postgres (the named ``catalog_item_kind`` enum, ``ilike`` search, and
workspace scoping behave differently under a real engine than under mocks), so
they are marked ``integration`` and deselected by default. Run with
``pytest -m integration``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal, engine
from app.models.workspace import Workspace
from app.schemas.catalog import CatalogItemCreate, CatalogItemUpdate
from app.services.catalog import CatalogService

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool() -> AsyncIterator[None]:
    """Dispose the shared asyncpg pool around each test (fresh event loop)."""
    await engine.dispose()
    yield
    await engine.dispose()


async def _make_workspace(db: AsyncSession) -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name="Catalog Co", slug=f"cat-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    return ws


async def test_create_and_get_round_trip() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = CatalogService(db)

        created = await svc.create_item(
            ws.id,
            CatalogItemCreate(
                name="Standard service call",
                description="First hour on site",
                sku="SVC-001",
                kind="service",
                unit_price=95.0,
                taxable=True,
            ),
            created_by_id=None,
        )
        assert created.name == "Standard service call"
        assert created.unit_price == 95.0
        assert created.kind == "service"
        assert created.is_active is True

        fetched = await svc.get_item(ws.id, created.id)
        assert fetched.id == created.id
        assert fetched.sku == "SVC-001"


async def test_list_filters_and_search() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = CatalogService(db)

        await svc.create_item(ws.id, CatalogItemCreate(name="Labor hour", unit_price=80.0))
        await svc.create_item(
            ws.id, CatalogItemCreate(name="LED fixture", kind="product", unit_price=45.0)
        )
        await svc.create_item(
            ws.id, CatalogItemCreate(name="Transformer", kind="product", unit_price=220.0)
        )

        # Alphabetical (case-insensitive collation), active-only by default.
        all_items = await svc.list_items(ws.id)
        assert [i.name for i in all_items.items] == ["Labor hour", "LED fixture", "Transformer"]
        assert all_items.total == 3

        products = await svc.list_items(ws.id, kind="product")
        assert {i.name for i in products.items} == {"LED fixture", "Transformer"}

        # Search matches name (case-insensitive).
        hits = await svc.list_items(ws.id, search="led")
        assert [i.name for i in hits.items] == ["LED fixture"]


async def test_archive_hides_from_default_list() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = CatalogService(db)

        item = await svc.create_item(
            ws.id, CatalogItemCreate(name="Seasonal special", unit_price=10.0)
        )
        await svc.update_item(ws.id, item.id, CatalogItemUpdate(is_active=False))

        assert (await svc.list_items(ws.id)).total == 0
        # Management view can still see archived items.
        with_inactive = await svc.list_items(ws.id, include_inactive=True)
        assert with_inactive.total == 1


async def test_update_changes_only_provided_fields() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = CatalogService(db)

        item = await svc.create_item(
            ws.id, CatalogItemCreate(name="Tune-up", unit_price=120.0, taxable=True)
        )
        updated = await svc.update_item(ws.id, item.id, CatalogItemUpdate(unit_price=135.0))
        assert updated.unit_price == 135.0
        assert updated.name == "Tune-up"  # unchanged
        assert updated.taxable is True  # unchanged


async def test_delete_removes_item() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = CatalogService(db)

        item = await svc.create_item(ws.id, CatalogItemCreate(name="One-off", unit_price=5.0))
        await svc.delete_item(ws.id, item.id)
        assert (await svc.list_items(ws.id, include_inactive=True)).total == 0


async def test_workspace_isolation() -> None:
    async with AsyncSessionLocal() as db:
        ws_a = await _make_workspace(db)
        ws_b = await _make_workspace(db)
        svc = CatalogService(db)

        item_a = await svc.create_item(ws_a.id, CatalogItemCreate(name="A only", unit_price=1.0))

        # ws_b cannot see or fetch ws_a's item.
        assert (await svc.list_items(ws_b.id)).total == 0
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            await svc.get_item(ws_b.id, item_a.id)
