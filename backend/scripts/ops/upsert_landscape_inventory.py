"""Review or create the approved zero-stock landscape inventory item master.

Dry-run is the default. ``--apply`` is required to write, and every read/write is
scoped to one workspace. This operation creates item-master rows only: it never
imports source quantities, supplier costs, stock levels, or ledger movements.

Local review only in this phase::

    python -m scripts.ops.upsert_landscape_inventory --workspace <slug-or-uuid>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from collections import Counter, defaultdict
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.catalog import CatalogItem
from app.models.inventory import DEFAULT_VALUATION_METHOD, InventoryItem
from app.models.workspace import Workspace


@dataclass(frozen=True, slots=True)
class LandscapeInventoryDefinition:
    sku: str
    name: str
    tribunal_name: str
    match_status: str
    review_group: str = "mapped"
    name_role_difference: bool = False
    catalog_link: bool = False


LANDSCAPE_INVENTORY: tuple[LandscapeInventoryDefinition, ...] = (
    LandscapeInventoryDefinition(
        "59009035",
        "DX-300-M 300w Transformer w/ Astronomical Timer Matte Gray",
        "DX 300W Transformer",
        "EXACT_COMPONENT",
    ),
    LandscapeInventoryDefinition(
        "59009050",
        "EX-150-SS 150w Transformer Stainless Steel",
        "EX 150W Transformer",
        "EXACT_COMPONENT",
    ),
    LandscapeInventoryDefinition(
        "59203512",
        "M-PL-1LED-FB Path Light Black",
        "Modern Path Light",
        "EXACT_COMPONENT",
    ),
    LandscapeInventoryDefinition(
        "59205842",
        "TM-LED-20W-18R-FB Path Light Black",
        "Pathway Light",
        "EXACT_COMPONENT",
    ),
    LandscapeInventoryDefinition(
        "59213082",
        "CA-51-P4WFL-FB CORA ACCENT BLACK",
        "ZD Down Light",
        "EXACT_COMPONENT_NAME_REVIEW",
        name_role_difference=True,
    ),
    LandscapeInventoryDefinition(
        "59213092",
        "CA-51-E6WWF-FB CORA ACCENT BLACK",
        "ZD Uplight | Accent Uplight",
        "EXACT_COMPONENT",
    ),
    LandscapeInventoryDefinition(
        "59213350",
        "CN-51-E6WFL-CW-FB CORA IN-GRADE BLACK",
        "CORA In-Grade | ZD In-Grade Uplight",
        "USER_CONFIRMED_PACKAGE_CONFIG_DRIFT",
        review_group="unresolved",
    ),
    LandscapeInventoryDefinition(
        "59213632",
        "HC-LED-TA-FB Top Assembly Black",
        "ZDC Path Light | ZD Path Light — top assembly",
        "EXACT_COMPONENT",
    ),
    LandscapeInventoryDefinition(
        "59213710",
        "CN-73-E9-W-FL-LG-FB CORA WELL BLACK",
        "CORA Well Light",
        "USER_CONFIRMED_PLACEHOLDER_MATCH",
        review_group="unresolved",
    ),
    LandscapeInventoryDefinition(
        "59214042",
        "EA-51-E-4W-FL-BC EVO ACCENT BLACK COMP",
        "EVO Accent Uplight",
        "EXACT_COMPONENT",
    ),
    LandscapeInventoryDefinition(
        "59272804",
        "SRP-40-W 40 ft Strip Light Warm White",
        "Warm White Strip Light",
        "USER_CONFIRMED_MISSING_FROM_TRIBUNAL",
        review_group="unresolved",
    ),
    LandscapeInventoryDefinition(
        "59303512",
        "M-PL-ZD-1LED-FB Path Light Black",
        "ZD Modern Path Light",
        "EXACT_COMPONENT",
    ),
    LandscapeInventoryDefinition(
        "59304101",
        "VO-ZD-1LED-RD-SS ROUND FACE",
        "Silver Wall Light",
        "USER_CONFIRMED_MISSING_FROM_TRIBUNAL",
        review_group="unresolved",
    ),
    LandscapeInventoryDefinition(
        "59306832",
        "PO-ZD-1LED-RD-FB Wall Light Black",
        "FX PO ZD Round Core-Drilled Wall Light — Black",
        "EXACT_CATALOG_AND_COMPONENT",
        catalog_link=True,
    ),
    LandscapeInventoryDefinition(
        "59308530",
        "ZD MR-16 5-Watt Warm Flood LED Lamp",
        "ZD MR16 5W Lamp",
        "EXACT_COMPONENT",
    ),
    LandscapeInventoryDefinition(
        "59311122",
        "P-ZD-1LED-18RA-FB Path Light 18 in Riser Black",
        "ZD Path Light — 18in riser",
        "EXACT_COMPONENT",
    ),
    LandscapeInventoryDefinition(
        "59320292",
        "NP-ZD-9LED-LS-FB Up Light Black",
        "ZD Narrow Beam Accent",
        "USER_CONFIRMED_NEAR_MATCH_59320262",
        review_group="unresolved",
    ),
    LandscapeInventoryDefinition(
        "59400232",
        "NP-ZDC-FB Up Light Black",
        "ZDC Color Uplight",
        "EXACT_COMPONENT",
    ),
    LandscapeInventoryDefinition(
        "59403532",
        "M-PL-ZDC-FB Path Light Black",
        "ZDC Modern Color Path Light",
        "EXACT_COMPONENT",
    ),
    LandscapeInventoryDefinition(
        "59407330",
        "LL-ZDC-BS UNDERWATER LIGHT",
        "FX LL ZDC Underwater Light — Brass",
        "EXACT_CATALOG_AND_COMPONENT",
        catalog_link=True,
    ),
    LandscapeInventoryDefinition(
        "59409010",
        "WIFI-MOD-2 Luxor Wi-Fi Module",
        "Luxor WiFi Module",
        "EXACT_COMPONENT",
    ),
    LandscapeInventoryDefinition(
        "59409312",
        "LUX-300-M LUXOR 2.0 300W XFMR",
        "Luxor Smart 300W Transformer",
        "EXACT_COMPONENT",
    ),
    LandscapeInventoryDefinition(
        "59412322",
        "G-ZDC-18RA-FB 18 in Riser Black",
        "ZDC Path Light — 18in riser",
        "EXACT_COMPONENT_NAME_REVIEW",
        name_role_difference=True,
    ),
    LandscapeInventoryDefinition(
        "59413032",
        "XA-70-ZDC-WF-FB ACCENT LIGHT BLACK",
        "ZDC Down Light",
        "EXACT_COMPONENT_NAME_REVIEW",
        name_role_difference=True,
    ),
)
APPROVED_SKUS = tuple(definition.sku for definition in LANDSCAPE_INVENTORY)
CATALOG_LINK_SKUS = tuple(
    definition.sku for definition in LANDSCAPE_INVENTORY if definition.catalog_link
)
INVENTORY_ID_NAMESPACE = uuid.UUID("0041ec87-d510-4c8b-9a90-77570849dba8")


@dataclass(frozen=True, slots=True)
class ImportResult:
    workspace_name: str
    workspace_slug: str
    created: int
    kept: int
    linked: int
    kept_links: int
    blocked_links: int
    manifest_lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CatalogLinkDecision:
    status: str
    catalog_item_id: uuid.UUID | None = None
    linked: int = 0
    kept: int = 0
    blocked: int = 0


def inventory_item_id(workspace_id: uuid.UUID, sku: str) -> uuid.UUID:
    """Return a stable ID so dry-run and apply show the same proposed row."""
    return uuid.uuid5(INVENTORY_ID_NAMESPACE, f"{workspace_id}:{sku}")


def inventory_item_payload(
    workspace_id: uuid.UUID,
    definition: LandscapeInventoryDefinition,
    *,
    catalog_item_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Return only item-master fields; stock and cost exist only in the ledger."""
    return {
        "id": inventory_item_id(workspace_id, definition.sku),
        "workspace_id": workspace_id,
        "catalog_item_id": catalog_item_id,
        "name": definition.name,
        "sku": definition.sku,
        "unit_of_measure": "each",
        "is_active": True,
        "valuation_method": DEFAULT_VALUATION_METHOD,
        "supplier_name": "FX Luminaire",
        "supplier_sku": definition.sku,
        "notes": None,
    }


def _manifest_line(
    definition: LandscapeInventoryDefinition,
    *,
    action: str,
    item_id: uuid.UUID,
    catalog_link_status: str,
) -> str:
    preview: dict[str, Any] = {
        "id": str(item_id),
        "sku": definition.sku,
        "existing_metadata": "preserved",
    }
    if action == "create":
        preview = {
            "id": str(item_id),
            "sku": definition.sku,
            "name": definition.name,
            "supplier_name": "FX Luminaire",
            "supplier_sku": definition.sku,
            "unit_of_measure": "each",
            "valuation_method": DEFAULT_VALUATION_METHOD,
            "is_active": True,
            "quantity_on_hand": "0.0000",
            "avg_unit_cost": "0.0000",
            "total_value": "0.00",
            "notes": None,
        }
    return (
        f"- {action} {definition.sku} review={definition.review_group} "
        f"match={definition.match_status} catalog_link={catalog_link_status} "
        f"tribunal_name={json.dumps(definition.tribunal_name, ensure_ascii=False)} "
        f"data={json.dumps(preview, sort_keys=True, ensure_ascii=False)}"
    )


def _index_inventory_items(rows: list[InventoryItem]) -> dict[str, InventoryItem]:
    by_sku: dict[str, InventoryItem] = {}
    for item in rows:
        if item.sku in by_sku:
            raise SystemExit(f"Duplicate inventory rows found for SKU {item.sku}; resolve manually")
        if item.sku is not None:
            by_sku[item.sku] = item
    return by_sku


def _catalog_link_decision(
    definition: LandscapeInventoryDefinition,
    item: InventoryItem | None,
    matches: list[CatalogItem],
    owner_by_catalog_id: dict[uuid.UUID | None, InventoryItem],
) -> CatalogLinkDecision:
    if not definition.catalog_link:
        return CatalogLinkDecision("not_applicable")
    if len(matches) != 1:
        status = "catalog_missing" if not matches else "catalog_ambiguous"
        return CatalogLinkDecision(status, blocked=1)

    catalog_item_id = matches[0].id
    owner = owner_by_catalog_id.get(catalog_item_id)
    if item is not None and item.catalog_item_id == catalog_item_id:
        return CatalogLinkDecision("kept", kept=1)
    if item is not None and item.catalog_item_id is not None:
        return CatalogLinkDecision("existing_link_preserved", blocked=1)
    if owner is not None and owner is not item:
        return CatalogLinkDecision(f"owned_by:{owner.sku or owner.id}", blocked=1)
    return CatalogLinkDecision("link", catalog_item_id=catalog_item_id, linked=1)


async def _build_import(db: AsyncSession, workspace_ref: str) -> ImportResult:
    clauses = [Workspace.slug == workspace_ref]
    with suppress(ValueError):
        clauses.append(Workspace.id == uuid.UUID(workspace_ref))
    workspace = (await db.execute(select(Workspace).where(or_(*clauses)))).scalar_one_or_none()
    if workspace is None:
        raise SystemExit(f"Workspace not found: {workspace_ref!r}")

    item_rows = (
        (
            await db.execute(
                select(InventoryItem).where(
                    InventoryItem.workspace_id == workspace.id,
                    InventoryItem.sku.in_(APPROVED_SKUS),
                )
            )
        )
        .scalars()
        .all()
    )
    items_by_sku = _index_inventory_items(list(item_rows))

    catalog_rows = (
        (
            await db.execute(
                select(CatalogItem).where(
                    CatalogItem.workspace_id == workspace.id,
                    CatalogItem.sku.in_(CATALOG_LINK_SKUS),
                )
            )
        )
        .scalars()
        .all()
    )
    catalog_by_sku: dict[str, list[CatalogItem]] = defaultdict(list)
    for catalog_item in catalog_rows:
        if catalog_item.sku is not None:
            catalog_by_sku[catalog_item.sku].append(catalog_item)

    catalog_ids = [row.id for row in catalog_rows]
    catalog_owners = (
        (
            await db.execute(
                select(InventoryItem).where(
                    InventoryItem.workspace_id == workspace.id,
                    InventoryItem.catalog_item_id.in_(catalog_ids),
                )
            )
        )
        .scalars()
        .all()
        if catalog_ids
        else []
    )
    owner_by_catalog_id = {item.catalog_item_id: item for item in catalog_owners}

    created = linked = kept_links = blocked_links = 0
    manifest_lines: list[str] = []
    for definition in LANDSCAPE_INVENTORY:
        item = items_by_sku.get(definition.sku)
        action = "create" if item is None else "keep"
        created += item is None
        link = _catalog_link_decision(
            definition,
            item,
            catalog_by_sku[definition.sku],
            owner_by_catalog_id,
        )
        linked += link.linked
        kept_links += link.kept
        blocked_links += link.blocked

        if item is None:
            item = InventoryItem(**inventory_item_payload(workspace.id, definition))
            db.add(item)
            items_by_sku[definition.sku] = item
        if link.catalog_item_id is not None:
            item.catalog_item_id = link.catalog_item_id

        manifest_lines.append(
            _manifest_line(
                definition,
                action=action,
                item_id=item.id,
                catalog_link_status=link.status,
            )
        )

    await db.flush()
    return ImportResult(
        workspace_name=workspace.name,
        workspace_slug=workspace.slug,
        created=created,
        kept=len(LANDSCAPE_INVENTORY) - created,
        linked=linked,
        kept_links=kept_links,
        blocked_links=blocked_links,
        manifest_lines=tuple(manifest_lines),
    )


def _print_result(result: ImportResult, *, apply: bool) -> None:
    review_counts = Counter(definition.review_group for definition in LANDSCAPE_INVENTORY)
    name_review_count = sum(definition.name_role_difference for definition in LANDSCAPE_INVENTORY)
    mode = "APPLIED" if apply else "DRY RUN — ROLLED BACK"
    print(f"{mode} for workspace '{result.workspace_name}' ({result.workspace_slug})")
    print(
        "Summary: "
        f"definitions={len(LANDSCAPE_INVENTORY)} create={result.created} keep={result.kept} "
        f"link={result.linked} keep_link={result.kept_links} "
        f"blocked_link={result.blocked_links} mapped={review_counts['mapped']} "
        f"unresolved={review_counts['unresolved']} name_role_review={name_review_count}"
    )
    print("Stock policy: ledger_writes=0 stock_level_writes=0 source_quantity_imported=0")
    for line in result.manifest_lines:
        print(line)


async def upsert(workspace_ref: str, *, apply: bool) -> ImportResult:
    """Run one atomic import; a dry run executes and then rolls back the same writes."""
    async with AsyncSessionLocal() as db:
        transaction = await db.begin()
        try:
            result = await _build_import(db, workspace_ref)
            if apply:
                await transaction.commit()
            else:
                await transaction.rollback()
        except BaseException:
            if transaction.is_active:
                await transaction.rollback()
            raise

    _print_result(result, apply=apply)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, help="Workspace slug or UUID")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Create missing zero-stock item-master rows (default is a rolled-back dry run)",
    )
    args = parser.parse_args()
    asyncio.run(upsert(args.workspace, apply=args.apply))


if __name__ == "__main__":
    main()
