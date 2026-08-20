"""Starter quote setup stays complete and non-destructive."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.catalog import CatalogItem
from app.models.workspace import Workspace
from app.schemas.pricing import PricingSettings
from app.services.workspaces.default_sales_setup import (
    STARTER_LANDSCAPE_CATALOG_ITEMS,
    STARTER_LANDSCAPE_SKUS,
    ensure_default_sales_setup,
)

pytestmark = pytest.mark.asyncio


def _db(existing_skus: list[str] | None = None) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = existing_skus or []
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    db.add_all = MagicMock()
    return db


def _workspace(settings: dict | None = None) -> Workspace:
    return Workspace(
        id=uuid.uuid4(),
        name="Fresh Workspace",
        slug=f"fresh-{uuid.uuid4().hex[:8]}",
        settings=settings or {},
    )


async def test_fresh_workspace_gets_priced_rows_for_every_landscape_package() -> None:
    db = _db()
    workspace = _workspace()

    changed = await ensure_default_sales_setup(db, workspace, created_by_id=41)

    assert changed is True
    pricing = PricingSettings.model_validate(workspace.settings["pricing"])
    assert pricing.tier_order == ["best", "better", "good"]

    referenced_skus = {
        item_id
        for tier in pricing.tiers
        for section in tier.sections
        for item_id in section.item_ids
    }
    assert referenced_skus == STARTER_LANDSCAPE_SKUS

    added_items: list[CatalogItem] = db.add_all.call_args.args[0]
    assert len(added_items) == len(STARTER_LANDSCAPE_CATALOG_ITEMS)
    assert {item.sku for item in added_items} == referenced_skus
    assert all(item.unit_price > 0 and item.is_active for item in added_items)
    assert all(item.created_by_id == 41 for item in added_items)


async def test_starter_setup_is_idempotent() -> None:
    db = _db(list(STARTER_LANDSCAPE_SKUS))
    workspace = _workspace()

    first = await ensure_default_sales_setup(db, workspace, created_by_id=41)
    second = await ensure_default_sales_setup(db, workspace, created_by_id=41)

    assert first is True
    assert second is False
    db.add_all.assert_not_called()


async def test_existing_custom_packages_are_not_replaced_or_polluted() -> None:
    custom_tiers = [
        {
            "key": "custom",
            "label": "CUSTOM",
            "sections": [{"title": "Custom", "item_ids": ["custom-sku"]}],
        }
    ]
    workspace = _workspace({"pricing": {"tier_order": ["custom"], "tiers": custom_tiers}})
    db = _db()

    changed = await ensure_default_sales_setup(db, workspace, created_by_id=41)

    assert changed is False
    assert workspace.settings["pricing"]["tiers"] == custom_tiers
    db.execute.assert_not_awaited()
    db.add_all.assert_not_called()
