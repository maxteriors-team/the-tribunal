"""Starter Price Book and landscape-package setup for new workspaces.

The quote builder prices catalog SKUs referenced by ``pricing.tiers`` in the
workspace JSON settings.  Creating only one side leaves a wizard that looks
configured but produces empty, $0 packages, so this module installs both sides
as one idempotent operation.
"""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from typing import Any, TypedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import CatalogItem
from app.models.workspace import Workspace


class StarterCatalogItem(TypedDict):
    """Fields used to construct one starter catalog row."""

    sku: str
    name: str
    description: str
    unit_price: Decimal
    attributes: dict[str, Any]


STARTER_LANDSCAPE_CATALOG_ITEMS: tuple[StarterCatalogItem, ...] = (
    {
        "sku": "starter-essential-transformer",
        "name": "Essential 150W Transformer",
        "description": "Installed 150W low-voltage transformer.",
        "unit_price": Decimal("504.00"),
        "attributes": {"transformer": True, "system_wattage": 150},
    },
    {
        "sku": "starter-essential-uplight",
        "name": "Essential Accent Uplight",
        "description": "Installed warm-white accent uplight.",
        "unit_price": Decimal("172.00"),
        "attributes": {"fixture_type": "uplight", "drawable": True, "wattage": 5},
    },
    {
        "sku": "starter-essential-path",
        "name": "Essential Path Light",
        "description": "Installed warm-white path light.",
        "unit_price": Decimal("376.00"),
        "attributes": {"fixture_type": "path_light", "drawable": True, "wattage": 4},
    },
    {
        "sku": "starter-professional-transformer",
        "name": "Professional 300W Transformer",
        "description": "Installed 300W low-voltage transformer.",
        "unit_price": Decimal("1072.00"),
        "attributes": {"transformer": True, "system_wattage": 300},
    },
    {
        "sku": "starter-professional-uplight",
        "name": "Professional Accent Uplight",
        "description": "Installed premium brass accent uplight.",
        "unit_price": Decimal("386.00"),
        "attributes": {"fixture_type": "uplight", "drawable": True, "wattage": 5},
    },
    {
        "sku": "starter-professional-path",
        "name": "Professional Path Light",
        "description": "Installed premium brass path light.",
        "unit_price": Decimal("376.00"),
        "attributes": {"fixture_type": "path_light", "drawable": True, "wattage": 4},
    },
    {
        "sku": "starter-estate-transformer",
        "name": "Estate Smart 300W Transformer",
        "description": "Installed 300W transformer with smart controls.",
        "unit_price": Decimal("2266.00"),
        "attributes": {"transformer": True, "system_wattage": 300},
    },
    {
        "sku": "starter-estate-uplight",
        "name": "Estate Color Uplight",
        "description": "Installed color-changing smart uplight.",
        "unit_price": Decimal("785.00"),
        "attributes": {"fixture_type": "uplight", "drawable": True, "wattage": 12},
    },
    {
        "sku": "starter-estate-path",
        "name": "Estate Color Path Light",
        "description": "Installed color-changing smart path light.",
        "unit_price": Decimal("1001.00"),
        "attributes": {"fixture_type": "path_light", "drawable": True, "wattage": 12},
    },
)

STARTER_LANDSCAPE_TIERS: tuple[dict[str, Any], ...] = (
    {
        "key": "best",
        "label": "BEST",
        "name": "Estate",
        "popular": False,
        "experience": "Smart color-changing fixtures and controls.",
        "warranty": "Premium system package",
        "sections": [
            {
                "title": "Estate fixtures",
                "item_ids": [
                    "starter-estate-transformer",
                    "starter-estate-uplight",
                    "starter-estate-path",
                ],
            }
        ],
    },
    {
        "key": "better",
        "label": "BETTER",
        "name": "Professional",
        "popular": True,
        "experience": "Premium brass fixtures for a durable, polished design.",
        "warranty": "Professional system package",
        "sections": [
            {
                "title": "Professional fixtures",
                "item_ids": [
                    "starter-professional-transformer",
                    "starter-professional-uplight",
                    "starter-professional-path",
                ],
            }
        ],
    },
    {
        "key": "good",
        "label": "GOOD",
        "name": "Essential",
        "popular": False,
        "experience": "A warm, reliable lighting foundation.",
        "warranty": "Essential system package",
        "sections": [
            {
                "title": "Essential fixtures",
                "item_ids": [
                    "starter-essential-transformer",
                    "starter-essential-uplight",
                    "starter-essential-path",
                ],
            }
        ],
    },
)

STARTER_LANDSCAPE_SKUS = frozenset(item["sku"] for item in STARTER_LANDSCAPE_CATALOG_ITEMS)


def _tier_item_ids(tiers: object) -> set[str]:
    """Return stable item keys referenced by a raw tier-settings value."""
    if not isinstance(tiers, list):
        return set()

    item_ids: set[str] = set()
    for tier in tiers:
        if not isinstance(tier, dict):
            continue
        sections = tier.get("sections")
        if not isinstance(sections, list):
            continue
        for section in sections:
            if not isinstance(section, dict):
                continue
            raw_ids = section.get("item_ids")
            if isinstance(raw_ids, list):
                item_ids.update(item_id for item_id in raw_ids if isinstance(item_id, str))
    return item_ids


def _ensure_starter_tiers(workspace: Workspace) -> tuple[list[dict[str, Any]], bool]:
    """Install starter tiers only when the workspace has no package configuration."""
    workspace_settings = (
        deepcopy(workspace.settings) if isinstance(workspace.settings, dict) else {}
    )
    raw_pricing = workspace_settings.get("pricing")
    pricing = deepcopy(raw_pricing) if isinstance(raw_pricing, dict) else {}
    tiers = pricing.get("tiers")

    if isinstance(tiers, list) and tiers:
        return tiers, False

    starter_tiers = deepcopy(list(STARTER_LANDSCAPE_TIERS))
    pricing["tier_order"] = ["best", "better", "good"]
    pricing["tiers"] = starter_tiers
    workspace_settings["pricing"] = pricing
    workspace.settings = workspace_settings
    return starter_tiers, True


async def ensure_default_sales_setup(
    db: AsyncSession,
    workspace: Workspace,
    *,
    created_by_id: int,
) -> bool:
    """Make an unconfigured workspace quote-ready without replacing custom setup.

    Returns ``True`` when tiers or catalog rows were added. Existing custom tiers
    are preserved. If those custom tiers do not resolve to active priced catalog
    rows, the frontend blocks the builder and sends the operator to the Price Book.
    """
    tiers, installed_tiers = _ensure_starter_tiers(workspace)
    referenced_ids = _tier_item_ids(tiers)

    # A custom package setup should never be polluted with unrelated starter SKUs.
    # Re-check starter-backed setups so onboarding remains safe after provisioning
    # and can repair a partially seeded transaction.
    starter_skus_to_ensure = referenced_ids.intersection(STARTER_LANDSCAPE_SKUS)
    if not installed_tiers and not starter_skus_to_ensure:
        return False

    result = await db.execute(
        select(CatalogItem.sku).where(
            CatalogItem.workspace_id == workspace.id,
            CatalogItem.sku.in_(starter_skus_to_ensure),
        )
    )
    existing_skus = {sku for sku in result.scalars().all() if sku}
    missing_items = [
        CatalogItem(
            workspace_id=workspace.id,
            created_by_id=created_by_id,
            sku=item["sku"],
            name=item["name"],
            description=item["description"],
            kind="service",
            unit_price=item["unit_price"],
            taxable=True,
            is_active=True,
            service_category="Landscape Lighting",
            attributes=deepcopy(item["attributes"]),
        )
        for item in STARTER_LANDSCAPE_CATALOG_ITEMS
        if item["sku"] in starter_skus_to_ensure and item["sku"] not in existing_skus
    ]
    if missing_items:
        db.add_all(missing_items)

    return installed_tiers or bool(missing_items)
