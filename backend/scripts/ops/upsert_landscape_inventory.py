"""Review or create the zero-stock inventory item master for every service line.

Definitions come from the reviewed intake sheet
``docs/google-sheets-all-inventory-upload.csv``. Only ``record_type=inventory_item``
rows are imported; ``cost_rule`` rows describe assembly costing, not stock, and are
skipped.

Dry-run is the default. ``--apply`` is required to write, and every read/write is
scoped to one workspace. This operation creates item-master rows only: it never
imports source quantities, supplier costs, stock levels, or ledger movements, and
it never invents a supplier for a row whose sheet vendor is blank.

    python -m scripts.ops.upsert_landscape_inventory --workspace <slug-or-uuid>
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import uuid
from collections import Counter, defaultdict
from contextlib import suppress
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.catalog import CatalogItem
from app.models.inventory import (
    DEFAULT_VALUATION_METHOD,
    InventoryItem,
    InventoryLedgerEntry,
    InventoryStockLevel,
)
from app.models.workspace import Workspace

INVENTORY_CSV = (
    Path(__file__).resolve().parents[3] / "docs" / "google-sheets-all-inventory-upload.csv"
)
STOCK_RECORD_TYPE = "inventory_item"
KNOWN_RECORD_TYPES = frozenset({STOCK_RECORD_TYPE, "cost_rule"})
REQUIRED_COLUMNS = frozenset(
    {
        "record_status",
        "record_type",
        "service_line",
        "internal_sku",
        "supplier_item_name",
        "tribunal_item_name",
        "stock_uom",
        "vendor",
        "vendor_sku",
    }
)
# Mirrors the InventoryItem column widths; the sheet is data, so it is checked
# at the boundary instead of failing mid-flush against a half-built import.
MAX_LENGTHS = {
    "internal_sku": 100,
    "tribunal_item_name": 255,
    "supplier_item_name": 255,
    "stock_uom": 30,
    "vendor": 255,
    "vendor_sku": 100,
}
# The sheet spells the same "sold by the foot" unit two ways across service
# lines. Inventory counts only stay comparable under one spelling, so the
# import canonicalises it; anything not listed here passes through untouched.
STOCK_UOM_ALIASES = {"linear_ft": "ft"}
# The defect signature of an earlier sheet revision: two candidate names in one
# field, e.g. `ZD Uplight | Accent Uplight`. Used to tell a stale imported name
# apart from a name an operator deliberately typed.
PIPED_NAME = re.compile(r"^[^|]+\|[^|]+$")


# Approved by the operator for the landscape review rows only: every landscape
# row in the sheet carries the `FX-Luminaire` item tag and the review manifest
# records this supplier. It is never applied to another service line, and a
# vendor present in the sheet always wins over it.
LANDSCAPE_SUPPLIER = "FX Luminaire"


@dataclass(frozen=True, slots=True)
class ReviewOverride:
    """A human review outcome that the intake sheet does not carry."""

    match_status: str
    review_group: str = "mapped"
    name_role_difference: bool = False
    catalog_link: bool = False
    unit_of_measure: str | None = None
    # Every member of LANDSCAPE_REVIEW is an FX Luminaire row, so the reviewed
    # supplier is the default here rather than repeated on all 24 entries.
    supplier_name: str | None = LANDSCAPE_SUPPLIER


# Outcomes of the landscape review recorded in
# docs/landscape-inventory-review-manifest.md. Rows absent here are graded from
# the sheet's own record_status and never receive a reviewed supplier.
LANDSCAPE_REVIEW: dict[str, ReviewOverride] = {
    "59009035": ReviewOverride("EXACT_COMPONENT"),
    "59009050": ReviewOverride("EXACT_COMPONENT"),
    "59203512": ReviewOverride("EXACT_COMPONENT"),
    "59205842": ReviewOverride("EXACT_COMPONENT"),
    "59213082": ReviewOverride("EXACT_COMPONENT_NAME_REVIEW", name_role_difference=True),
    "59213092": ReviewOverride("EXACT_COMPONENT"),
    "59213350": ReviewOverride("USER_CONFIRMED_PACKAGE_CONFIG_DRIFT", review_group="unresolved"),
    "59213632": ReviewOverride("EXACT_COMPONENT"),
    "59213710": ReviewOverride("USER_CONFIRMED_PLACEHOLDER_MATCH", review_group="unresolved"),
    "59214042": ReviewOverride("EXACT_COMPONENT"),
    # Stays one `each`: the review withheld approval for per-foot valuation of
    # the 40 ft strip-light package, so the sheet's `ft` is not adopted yet.
    "59272804": ReviewOverride(
        "USER_CONFIRMED_MISSING_FROM_TRIBUNAL",
        review_group="unresolved",
        unit_of_measure="each",
    ),
    "59303512": ReviewOverride("EXACT_COMPONENT"),
    "59304101": ReviewOverride("USER_CONFIRMED_MISSING_FROM_TRIBUNAL", review_group="unresolved"),
    "59306832": ReviewOverride("EXACT_CATALOG_AND_COMPONENT", catalog_link=True),
    "59308530": ReviewOverride("EXACT_COMPONENT"),
    "59311122": ReviewOverride("EXACT_COMPONENT"),
    "59320292": ReviewOverride("USER_CONFIRMED_NEAR_MATCH_59320262", review_group="unresolved"),
    "59400232": ReviewOverride("EXACT_COMPONENT"),
    "59403532": ReviewOverride("EXACT_COMPONENT"),
    "59407330": ReviewOverride("EXACT_CATALOG_AND_COMPONENT", catalog_link=True),
    "59409010": ReviewOverride("EXACT_COMPONENT"),
    "59409312": ReviewOverride("EXACT_COMPONENT"),
    "59412322": ReviewOverride("EXACT_COMPONENT_NAME_REVIEW", name_role_difference=True),
    "59413032": ReviewOverride("EXACT_COMPONENT_NAME_REVIEW", name_role_difference=True),
}
INVENTORY_ID_NAMESPACE = uuid.UUID("0041ec87-d510-4c8b-9a90-77570849dba8")


@dataclass(frozen=True, slots=True)
class InventoryDefinition:
    sku: str
    name: str
    supplier_item_name: str
    service_line: str
    unit_of_measure: str
    supplier_name: str | None
    supplier_sku: str | None
    match_status: str
    review_group: str
    name_role_difference: bool = False
    catalog_link: bool = False


@dataclass(frozen=True, slots=True)
class ImportResult:
    workspace_name: str
    workspace_slug: str
    definitions: int
    created: int
    updated: int
    skipped: int
    linked: int
    kept_links: int
    blocked_links: int
    review_counts: dict[str, int]
    service_line_counts: dict[str, int]
    name_role_review: int
    missing_supplier: tuple[str, ...]
    manifest_lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CatalogLinkDecision:
    status: str
    catalog_item_id: uuid.UUID | None = None
    linked: int = 0
    kept: int = 0
    blocked: int = 0


def _cell(row: dict[str, str], column: str) -> str:
    return (row.get(column) or "").strip()


def _validate_row(row: dict[str, str], line_no: int) -> None:
    record_type = _cell(row, "record_type")
    if record_type not in KNOWN_RECORD_TYPES:
        raise SystemExit(
            f"{INVENTORY_CSV.name} line {line_no}: unknown record_type {record_type!r}"
        )
    for column in ("internal_sku", "tribunal_item_name", "supplier_item_name", "stock_uom"):
        if not _cell(row, column):
            raise SystemExit(f"{INVENTORY_CSV.name} line {line_no}: {column} is required")
    for column, limit in MAX_LENGTHS.items():
        value = _cell(row, column)
        if len(value) > limit:
            raise SystemExit(
                f"{INVENTORY_CSV.name} line {line_no}: {column} is {len(value)} chars (max {limit})"
            )


@cache
def load_definitions(source: Path = INVENTORY_CSV) -> tuple[InventoryDefinition, ...]:
    """Parse the reviewed intake sheet into stock definitions, or fail loudly."""
    with source.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or ())
        if missing:
            raise SystemExit(f"{source.name}: missing columns {sorted(missing)}")
        rows = list(reader)

    definitions: list[InventoryDefinition] = []
    seen: set[str] = set()
    for line_no, row in enumerate(rows, start=2):
        _validate_row(row, line_no)
        if _cell(row, "record_type") != STOCK_RECORD_TYPE:
            continue
        sku = _cell(row, "internal_sku")
        if sku in seen:
            raise SystemExit(f"{source.name} line {line_no}: duplicate internal_sku {sku!r}")
        seen.add(sku)
        override = LANDSCAPE_REVIEW.get(sku)
        record_status = _cell(row, "record_status")
        definitions.append(
            InventoryDefinition(
                sku=sku,
                name=_cell(row, "tribunal_item_name"),
                supplier_item_name=_cell(row, "supplier_item_name"),
                service_line=_cell(row, "service_line"),
                unit_of_measure=(override and override.unit_of_measure)
                or STOCK_UOM_ALIASES.get(_cell(row, "stock_uom"), _cell(row, "stock_uom")),
                # Sheet vendor wins; otherwise only a reviewed supplier applies.
                # A row with neither stays blank — no supplier is invented here.
                supplier_name=_cell(row, "vendor")
                or (override.supplier_name if override else None),
                supplier_sku=_cell(row, "vendor_sku") or None,
                match_status=override.match_status if override else record_status,
                review_group=(
                    override.review_group if override else record_status.lower() or "unreviewed"
                ),
                name_role_difference=bool(override and override.name_role_difference),
                catalog_link=bool(override and override.catalog_link),
            )
        )

    reviewed_missing = sorted(LANDSCAPE_REVIEW.keys() - seen)
    if reviewed_missing:
        raise SystemExit(f"{source.name}: reviewed SKUs absent from the sheet {reviewed_missing}")
    return tuple(definitions)


def inventory_item_id(workspace_id: uuid.UUID, sku: str) -> uuid.UUID:
    """Return a stable ID so dry-run and apply show the same proposed row."""
    return uuid.uuid5(INVENTORY_ID_NAMESPACE, f"{workspace_id}:{sku}")


def inventory_item_payload(
    workspace_id: uuid.UUID,
    definition: InventoryDefinition,
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
        "unit_of_measure": definition.unit_of_measure,
        "is_active": True,
        "valuation_method": DEFAULT_VALUATION_METHOD,
        "supplier_name": definition.supplier_name,
        "supplier_sku": definition.supplier_sku,
        "notes": None,
    }


def _manifest_line(
    definition: InventoryDefinition,
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
            "supplier_name": definition.supplier_name,
            "supplier_sku": definition.supplier_sku,
            "unit_of_measure": definition.unit_of_measure,
            "valuation_method": DEFAULT_VALUATION_METHOD,
            "is_active": True,
            "quantity_on_hand": "0.0000",
            "avg_unit_cost": "0.0000",
            "total_value": "0.00",
            "notes": None,
        }
    return (
        f"- {action} [{definition.service_line}] {definition.sku} "
        f"review={definition.review_group} match={definition.match_status} "
        f"supplier={'MISSING' if definition.supplier_name is None else 'sheet'} "
        f"catalog_link={catalog_link_status} "
        f"supplier_item_name={json.dumps(definition.supplier_item_name, ensure_ascii=False)} "
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
    definition: InventoryDefinition,
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


def _reconcile_existing(
    item: InventoryItem,
    definition: InventoryDefinition,
    *,
    has_stock_history: bool,
) -> bool:
    """Adopt sheet corrections an operator cannot have made themselves.

    Returns whether anything changed. Operator edits always win; only the two
    known import defects are repaired.
    """
    corrected = False

    # A unit may only be corrected while the item has never held stock:
    # rewriting it under a counted balance would silently reinterpret every
    # recorded quantity (150 ft becoming 150 each).
    if item.unit_of_measure != definition.unit_of_measure and not has_stock_history:
        item.unit_of_measure = definition.unit_of_measure
        corrected = True

    # A stored name is only replaced while it still carries the sheet defect
    # this import fixed: two candidate names crammed into one field with a `|`.
    # A name an operator deliberately typed never looks like that.
    if PIPED_NAME.match(item.name):
        item.name = definition.name
        corrected = True

    return corrected


async def _build_import(db: AsyncSession, workspace_ref: str) -> ImportResult:
    definitions = load_definitions()
    approved_skus = [definition.sku for definition in definitions]
    catalog_link_skus = [definition.sku for definition in definitions if definition.catalog_link]

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
                    InventoryItem.sku.in_(approved_skus),
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
                    CatalogItem.sku.in_(catalog_link_skus),
                )
            )
        )
        .scalars()
        .all()
        if catalog_link_skus
        else []
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

    # A unit correction in the sheet may only be adopted while an item has never
    # held stock: rewriting the unit under an existing balance would silently
    # reinterpret every counted quantity (150 ft becoming 150 each). Items with
    # any ledger or stock-level history keep the unit they were counted in.
    item_ids = [item.id for item in item_rows]
    moved_item_ids: set[uuid.UUID] = set()
    if item_ids:
        for table in (InventoryLedgerEntry, InventoryStockLevel):
            rows = (
                await db.execute(
                    select(table.item_id).where(
                        table.workspace_id == workspace.id,
                        table.item_id.in_(item_ids),
                    )
                )
            ).scalars()
            moved_item_ids.update(rows)

    created = updated = skipped = linked = kept_links = blocked_links = 0
    manifest_lines: list[str] = []
    for definition in definitions:
        item = items_by_sku.get(definition.sku)
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
            action = "create"
            created += 1
            item = InventoryItem(**inventory_item_payload(workspace.id, definition))
            db.add(item)
            items_by_sku[definition.sku] = item
        else:
            corrected = _reconcile_existing(
                item,
                definition,
                has_stock_history=item.id in moved_item_ids,
            )
            if link.catalog_item_id is not None or corrected:
                action = "update"
                updated += 1
            else:
                action = "skip"
                skipped += 1
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
        definitions=len(definitions),
        created=created,
        updated=updated,
        skipped=skipped,
        linked=linked,
        kept_links=kept_links,
        blocked_links=blocked_links,
        review_counts=dict(Counter(item.review_group for item in definitions)),
        service_line_counts=dict(Counter(item.service_line for item in definitions)),
        name_role_review=sum(item.name_role_difference for item in definitions),
        missing_supplier=tuple(item.sku for item in definitions if item.supplier_name is None),
        manifest_lines=tuple(manifest_lines),
    )


def _print_result(result: ImportResult, *, apply: bool) -> None:
    mode = "APPLIED" if apply else "DRY RUN — ROLLED BACK"
    print(f"{mode} for workspace '{result.workspace_name}' ({result.workspace_slug})")
    print(f"Source: {INVENTORY_CSV.name} (record_type=inventory_item only; cost_rule rows skipped)")
    print(
        "Summary: "
        f"definitions={result.definitions} create={result.created} update={result.updated} "
        f"skip={result.skipped} link={result.linked} keep_link={result.kept_links} "
        f"blocked_link={result.blocked_links}"
    )
    print(
        "Service lines: "
        + " ".join(f"{line}={count}" for line, count in sorted(result.service_line_counts.items()))
    )
    print(
        "Review: "
        + " ".join(f"{group}={count}" for group, count in sorted(result.review_counts.items()))
        + f" name_role_review={result.name_role_review}"
    )
    print(
        "Stock policy: ledger_writes=0 stock_level_writes=0 source_quantity_imported=0 notes=null"
    )
    print(f"Supplier missing (left blank, needs a human value): {len(result.missing_supplier)}")
    for sku in result.missing_supplier:
        print(f"  ! supplier_name blank: {sku}")
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
