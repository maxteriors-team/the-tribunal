"""Safely add the approved FX specialty fixtures to one workspace.

Dry-run is the default. ``--apply`` is required to write. Unlike the demo seed,
this script merges only two catalog rows and the Premier ``Specialty Fixtures``
section; every unrelated price-book item and pricing setting is preserved.

Run after deploying the matching fixture types:

    python -m scripts.ops.upsert_fx_specialty_fixtures --workspace <slug-or-uuid>
    python -m scripts.ops.upsert_fx_specialty_fixtures --workspace <slug-or-uuid> --apply
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import uuid
from contextlib import suppress
from typing import Any

from sqlalchemy import or_, select

from app.db.session import AsyncSessionLocal
from app.models.catalog import CatalogItem
from app.models.workspace import Workspace
from app.schemas.pricing import PricingSettings
from app.services.quotes.pricing_config import SETTINGS_KEY
from scripts.demo.seed_lighting_workspace import ELECTRICAL_SPECS, FIXTURES

SPECIALTY_SKUS = ("59306832", "59407330")
PREMIER_TIER_KEY = "best"
SPECIALTY_SECTION_TITLE = "Specialty Fixtures"


def specialty_catalog_payload(sku: str) -> dict[str, Any]:
    """Return the canonical, validated catalog payload for one approved SKU."""
    if sku not in SPECIALTY_SKUS:
        raise ValueError(f"Unsupported specialty SKU: {sku}")
    fixture = FIXTURES[sku]
    attributes = dict(fixture.get("attributes", {}))
    attributes.update(ELECTRICAL_SPECS[sku])
    components = [
        {"sku": part_sku, "description": description, "qty": qty}
        for part_sku, description, qty in fixture["parts"]
    ]
    return {
        "name": fixture["name"],
        "description": fixture["description"],
        "sku": sku,
        "kind": "product",
        "unit_price": fixture["price"],
        "taxable": True,
        "is_active": True,
        # Must match the spelling onboarding seeds in ``default_sales_setup``:
        # the field is free-form text and every report groups on the exact
        # string, so a second spelling here splits one service across two rows.
        "service_category": "Landscape Lighting",
        "attributes": attributes,
        "components": components,
    }


def merge_premier_specialty_section(pricing: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Merge the specialty SKUs into Premier without changing other settings."""
    merged = copy.deepcopy(pricing)
    tiers = merged.get("tiers")
    if not isinstance(tiers, list):
        raise ValueError("Workspace pricing has no tier list")

    premier = next(
        (tier for tier in tiers if isinstance(tier, dict) and tier.get("key") == PREMIER_TIER_KEY),
        None,
    )
    if premier is None:
        raise ValueError("Workspace pricing has no Premier ('best') tier")

    sections = premier.get("sections")
    if not isinstance(sections, list):
        raise ValueError("Premier pricing tier has no sections list")

    section = next(
        (
            candidate
            for candidate in sections
            if isinstance(candidate, dict) and candidate.get("title") == SPECIALTY_SECTION_TITLE
        ),
        None,
    )
    changed = False
    if section is None:
        section = {"title": SPECIALTY_SECTION_TITLE, "item_ids": []}
        sections.append(section)
        changed = True

    item_ids = section.get("item_ids")
    if not isinstance(item_ids, list):
        raise ValueError("Specialty Fixtures section has no item_ids list")
    for sku in SPECIALTY_SKUS:
        if sku not in item_ids:
            item_ids.append(sku)
            changed = True

    PricingSettings(**merged)
    return merged, changed


async def upsert(workspace_ref: str, *, apply: bool) -> None:
    async with AsyncSessionLocal() as db:
        clauses = [Workspace.slug == workspace_ref]
        with suppress(ValueError):
            clauses.append(Workspace.id == uuid.UUID(workspace_ref))
        workspace = (await db.execute(select(Workspace).where(or_(*clauses)))).scalar_one_or_none()
        if workspace is None:
            raise SystemExit(f"Workspace not found: {workspace_ref!r}")
        workspace_name = workspace.name
        workspace_slug = workspace.slug

        pricing = (workspace.settings or {}).get(SETTINGS_KEY)
        if not isinstance(pricing, dict):
            raise SystemExit("Workspace has no editable pricing configuration")
        merged_pricing, pricing_changed = merge_premier_specialty_section(pricing)

        rows = (
            (
                await db.execute(
                    select(CatalogItem).where(
                        CatalogItem.workspace_id == workspace.id,
                        CatalogItem.sku.in_(SPECIALTY_SKUS),
                    )
                )
            )
            .scalars()
            .all()
        )
        by_sku: dict[str, CatalogItem] = {}
        for row in rows:
            if row.sku in by_sku:
                raise SystemExit(
                    f"Duplicate catalog rows found for SKU {row.sku}; resolve manually"
                )
            if row.sku:
                by_sku[row.sku] = row

        actions: list[str] = []
        for sku in SPECIALTY_SKUS:
            payload = specialty_catalog_payload(sku)
            item = by_sku.get(sku)
            actions.append(f"{'update' if item else 'create'} {sku}: {payload['name']}")
            if not apply:
                continue
            if item is None:
                db.add(
                    CatalogItem(
                        workspace_id=workspace.id,
                        is_attachable=True,
                        attach_targets=[],
                        **payload,
                    )
                )
                continue
            merged_attributes = dict(item.attributes or {})
            merged_attributes.update(payload.pop("attributes"))
            for field, value in payload.items():
                setattr(item, field, value)
            item.attributes = merged_attributes

        actions.append(
            f"{'update' if pricing_changed else 'keep'} Premier/{SPECIALTY_SECTION_TITLE}: "
            + ", ".join(SPECIALTY_SKUS)
        )
        if apply:
            settings = dict(workspace.settings or {})
            settings[SETTINGS_KEY] = merged_pricing
            workspace.settings = settings
            await db.commit()
        else:
            await db.rollback()

        mode = "APPLIED" if apply else "DRY RUN"
        print(f"{mode} for workspace '{workspace_name}' ({workspace_slug})")
        for action in actions:
            print(f"- {action}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, help="Workspace slug or UUID")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the two catalog rows and Premier section (default is dry-run)",
    )
    args = parser.parse_args()
    asyncio.run(upsert(args.workspace, apply=args.apply))


if __name__ == "__main__":
    main()
