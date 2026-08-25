from __future__ import annotations

import csv
import json
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[3]
DOCS = ROOT / "docs"
SNAPSHOT_DATE = "2026-08-21"

FIELDS = [
    "record_status",
    "record_type",
    "service_line",
    "internal_sku",
    "supplier_item_name",
    "tribunal_item_name",
    "category",
    "stock_uom",
    "purchase_uom",
    "units_per_purchase",
    "current_purchase_price",
    "current_unit_cost",
    "cost_confidence",
    "source_quantity",
    "source_subtotal",
    "quantity_on_hand",
    "ownership",
    "consumption_behavior",
    "package_option",
    "package_tags",
    "item_tags",
    "vendor",
    "vendor_sku",
    "external_variant_id",
    "pricing_behavior",
    "bom_rule",
    "source_url",
    "notes",
]

PACKAGE = "Permanent Holiday Lighting — RGBW+2 DEEP Pebble"
PACKAGE_TAGS = "permanent_holiday;rgbw2;deep_pebble"
MINLEON_BASE = "https://minleonpermanentlighting.com/products/"
SPREADSHEET_FORMULA_PREFIXES = ("=", "+", "-", "@")


def fetch_product(handle: str) -> dict:
    request = Request(f"{MINLEON_BASE}{handle}.js", headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=30) as response:  # noqa: S310 -- fixed HTTPS vendor URL
        payload = json.load(response)
    if not isinstance(payload, dict) or not isinstance(payload.get("variants"), list):
        raise ValueError(f"Unexpected product response for {handle}")
    return payload


def validate_spreadsheet_cells(rows: list[dict[str, str]]) -> None:
    expected_fields = set(FIELDS)
    for row_number, row in enumerate(rows, start=2):
        if set(row) != expected_fields:
            raise ValueError(f"Inventory row {row_number} does not match the output schema")
        for field, value in row.items():
            if not isinstance(value, str):
                raise ValueError(f"Inventory row {row_number} field {field} must be text")
            if value.lstrip().startswith(SPREADSHEET_FORMULA_PREFIXES):
                raise ValueError(
                    f"Inventory row {row_number} field {field} starts with a "
                    "spreadsheet formula prefix"
                )


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    validate_spreadsheet_cells(rows)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)


def permanent_holiday_rows() -> list[dict[str, str]]:
    handles = {
        "kits": "100-ft-rgb-starter-pack-minleon-permanent-lighting-demo-kit",
        "power_t": "minleon-permanent-lighting-rgb-power-t",
        "basic_t": "minleon-permanent-lighting-rgb-basic-4-pin-t",
        "booster": "minleon-permanent-lighting-rgb-signal-booster",
        "power_supply": "minleon-permanent-lighting-power-supply",
    }
    products = {key: fetch_product(handle) for key, handle in handles.items()}
    rows: list[dict[str, str]] = []
    color_codes = {
        "White": "W",
        "Sand": "S",
        "Light Brown": "LB",
        "Brown": "BR",
        "Grey": "G",
        "Black": "BK",
    }

    kit_variants = [
        variant
        for variant in products["kits"]["variants"]
        if variant.get("option3") == "Dual Port Wec"
    ]
    if len(kit_variants) != 24:
        raise ValueError(f"Expected 24 Dual Port WEC variants, got {len(kit_variants)}")

    for variant in kit_variants:
        length = int(variant["option1"].split()[0])
        color = variant["option2"]
        price = variant["price"] / 100
        internal_sku = f"KIT-CC-{length}{color_codes[color]}-D"
        note = (
            f"SNAPSHOT {SNAPSHOT_DATE}: live Dual Port WEC variant and price verified; "
            "on-hand quantity not provided"
        )
        if variant["sku"] != internal_sku:
            note += (
                f"; supplier SKU is duplicated/mislabeled as {variant['sku']}, so the internal SKU "
                "and Shopify variant ID prevent merging"
            )
        rows.append(
            {
                "record_status": "NEEDS_PHYSICAL_COUNT",
                "record_type": "inventory_item",
                "service_line": "permanent_holiday",
                "internal_sku": internal_sku,
                "supplier_item_name": (
                    f"RGBW+2 DEEP Pebble Complete Kit — {length} ft / {color} / Dual Port WEC"
                ),
                "tribunal_item_name": (
                    f"Minleon RGBW+2 DEEP Pebble System — {length} ft, {color}, Dual Port WEC"
                ),
                "category": "complete_kit",
                "stock_uom": "kit",
                "purchase_uom": "kit",
                "units_per_purchase": "1",
                "current_purchase_price": f"{price:.2f}",
                "current_unit_cost": f"{price:.5f}",
                "cost_confidence": "SNAPSHOT",
                "source_quantity": "",
                "source_subtotal": "",
                "quantity_on_hand": "",
                "ownership": "sold_to_customer",
                "consumption_behavior": "consume",
                "package_option": PACKAGE,
                "package_tags": PACKAGE_TAGS,
                "item_tags": (
                    "permanent;holiday-lighting;Minleon;RGBW+2;DEEP-Pebble;dual-port-WEC;"
                    f"{length}-ft;{color.lower().replace(' ', '-')};complete-kit"
                ),
                "vendor": "Minleon Permanent Lighting",
                "vendor_sku": variant["sku"],
                "external_variant_id": str(variant["id"]),
                "pricing_behavior": "inventory_cost",
                "bom_rule": "Choose one complete kit per system",
                "source_url": f"{MINLEON_BASE}{handles['kits']}",
                "notes": note,
            }
        )

    def add_color_variants(
        key: str,
        tribunal_name: str,
        category: str,
        item_tags: str,
        bom_rule: str,
        internal_skus: dict[str, str] | None = None,
        note: str = "",
    ) -> None:
        for variant in products[key]["variants"]:
            color = variant["option1"]
            price = variant["price"] / 100
            rows.append(
                {
                    "record_status": "NEEDS_PHYSICAL_COUNT",
                    "record_type": "inventory_item",
                    "service_line": "permanent_holiday",
                    "internal_sku": (internal_skus or {}).get(color, variant["sku"]),
                    "supplier_item_name": f"{products[key]['title']} — {color}",
                    "tribunal_item_name": f"{tribunal_name} — {color}",
                    "category": category,
                    "stock_uom": "each",
                    "purchase_uom": "each",
                    "units_per_purchase": "1",
                    "current_purchase_price": f"{price:.2f}",
                    "current_unit_cost": f"{price:.5f}",
                    "cost_confidence": "SNAPSHOT",
                    "source_quantity": "",
                    "source_subtotal": "",
                    "quantity_on_hand": "",
                    "ownership": "sold_to_customer",
                    "consumption_behavior": "consume",
                    "package_option": PACKAGE,
                    "package_tags": PACKAGE_TAGS,
                    "item_tags": (
                        f"permanent;holiday-lighting;Minleon;RGBW+2;{item_tags};"
                        f"{color.lower().replace(' ', '-')}"
                    ),
                    "vendor": "Minleon Permanent Lighting",
                    "vendor_sku": variant["sku"],
                    "external_variant_id": str(variant["id"]),
                    "pricing_behavior": "inventory_cost",
                    "bom_rule": bom_rule,
                    "source_url": f"{MINLEON_BASE}{handles[key]}",
                    "notes": (
                        f"SNAPSHOT {SNAPSHOT_DATE}: live variant and price verified; "
                        f"on-hand quantity not provided{note}"
                    ),
                }
            )

    add_color_variants(
        "power_t",
        "Minleon RGBW Power-T",
        "power_injection",
        "Power-T;power-injection",
        "As required after 200 lights; one is included in the 400-ft kit",
    )
    add_color_variants(
        "basic_t",
        "Minleon RGBW Basic 4-Wire T",
        "splitter",
        "4-wire-T;splitter",
        "As required by branch layout; complete kits include quantities based on kit length",
    )
    add_color_variants(
        "booster",
        "Minleon RGBW Signal Booster Kit",
        "signal_booster",
        "signal-booster;sender;receiver",
        "One sender/receiver kit per spacer jump up to 200 ft",
        internal_skus={"Black": "RGB+SR-B", "White": "RGB+SR-W", "Sand": "RGB+SR-S"},
        note=(
            "; White and Sand share supplier SKU RGB+SRW, so the internal color SKU and Shopify "
            "variant ID prevent merging"
        ),
    )

    supply = next(
        variant
        for variant in products["power_supply"]["variants"]
        if variant["id"] == 46626313797799
    )
    price = supply["price"] / 100
    rows.append(
        {
            "record_status": "NEEDS_PHYSICAL_COUNT",
            "record_type": "inventory_item",
            "service_line": "permanent_holiday",
            "internal_sku": supply["sku"],
            "supplier_item_name": "Minleon 5 Amp Power Supply",
            "tribunal_item_name": "Minleon 24V 5A RGBW Power Supply",
            "category": "power_supply",
            "stock_uom": "each",
            "purchase_uom": "each",
            "units_per_purchase": "1",
            "current_purchase_price": f"{price:.2f}",
            "current_unit_cost": f"{price:.5f}",
            "cost_confidence": "SNAPSHOT",
            "source_quantity": "",
            "source_subtotal": "",
            "quantity_on_hand": "",
            "ownership": "sold_to_customer",
            "consumption_behavior": "consume",
            "package_option": PACKAGE,
            "package_tags": PACKAGE_TAGS,
            "item_tags": (
                "permanent;holiday-lighting;Minleon;RGBW;power-supply;24V;5A;120W;power-injection"
            ),
            "vendor": "Minleon Permanent Lighting",
            "vendor_sku": supply["sku"],
            "external_variant_id": str(supply["id"]),
            "pricing_behavior": "inventory_cost",
            "bom_rule": (
                "As required for controller or Power-T injection; included in the 400-ft kit"
            ),
            "source_url": f"{MINLEON_BASE}{handles['power_supply']}?variant=46626313797799",
            "notes": (
                f"SNAPSHOT {SNAPSHOT_DATE}: selected 5A variant and price verified; "
                "on-hand quantity not provided"
            ),
        }
    )
    rows.append(
        {
            "record_status": "NEEDS_PHYSICAL_COUNT",
            "record_type": "inventory_item",
            "service_line": "permanent_holiday",
            "internal_sku": "B08282SQPT",
            "supplier_item_name": (
                "Gratury IP67 Waterproof ABS Junction Box — Grey 11.4 x 7.5 x 5.5 in"
            ),
            "tribunal_item_name": "Permanent Lighting Controller Enclosure — IP67 Grey",
            "category": "controller_enclosure",
            "stock_uom": "each",
            "purchase_uom": "each",
            "units_per_purchase": "1",
            "current_purchase_price": "24.99",
            "current_unit_cost": "24.99000",
            "cost_confidence": "SNAPSHOT",
            "source_quantity": "",
            "source_subtotal": "",
            "quantity_on_hand": "",
            "ownership": "sold_to_customer",
            "consumption_behavior": "consume",
            "package_option": PACKAGE,
            "package_tags": PACKAGE_TAGS,
            "item_tags": (
                "permanent;holiday-lighting;controller-enclosure;IP67;grey;ABS;mandatory;"
                "one-per-system;amazon"
            ),
            "vendor": "Amazon",
            "vendor_sku": "B08282SQPT",
            "external_variant_id": "",
            "pricing_behavior": "inventory_cost",
            "bom_rule": "Required quantity 1 per permanent-lighting system",
            "source_url": "https://www.amazon.com/dp/B08282SQPT",
            "notes": (
                "NEEDS_ELECTRICAL_COMPLIANCE_VERIFICATION: listing does not confirm UL/NRTL "
                "approval for line-voltage equipment; drilled entries require rated cable glands"
            ),
        }
    )

    if len(rows) != 35 or len({row["internal_sku"] for row in rows}) != 35:
        raise ValueError("Permanent holiday inventory must contain 35 unique rows")
    return rows


def landscape_rows() -> list[dict[str, str]]:
    with (DOCS / "google-sheets-landscape-inventory-upload.csv").open(
        newline="", encoding="utf-8"
    ) as file:
        source = list(csv.DictReader(file))
    rows = []
    for row in source:
        strip_light = row["internal_sku"] == "59272804"
        notes = row["notes"]
        if strip_light:
            notes += "; per-foot unit cost remains blank until the 40-ft purchase unit is confirmed"
        rows.append(
            {
                "record_status": row["record_status"],
                "record_type": "inventory_item",
                "service_line": "landscape",
                "internal_sku": row["internal_sku"],
                "supplier_item_name": row["supplier_item_name"],
                "tribunal_item_name": row["tribunal_item_name"],
                "category": row["category"],
                "stock_uom": row["stock_uom"],
                "purchase_uom": row["purchase_uom"],
                "units_per_purchase": row["units_per_purchase"],
                "current_purchase_price": row["current_unit_cost"],
                "current_unit_cost": "" if strip_light else row["current_unit_cost"],
                "cost_confidence": "NEEDS_VERIFICATION" if strip_light else "SOURCE_DERIVED",
                "source_quantity": row["source_quantity"],
                "source_subtotal": row["source_subtotal"],
                "quantity_on_hand": row["quantity_on_hand"],
                "ownership": row["ownership"],
                "consumption_behavior": row["consumption_behavior"],
                "package_option": row["package_option"],
                "package_tags": row["package_tags"],
                "item_tags": (
                    f"landscape;FX-Luminaire;{row['category'].replace('_', '-')};"
                    f"{row['package_tags'].replace(';', ';')}"
                ),
                "vendor": row["vendor"],
                "vendor_sku": row["vendor_sku"],
                "external_variant_id": "",
                "pricing_behavior": "inventory_cost",
                "bom_rule": "",
                "source_url": "",
                "notes": notes,
            }
        )
    return rows


def bistro_rows() -> list[dict[str, str]]:
    with (DOCS / "google-sheets-bistro-inventory-upload.csv").open(
        newline="", encoding="utf-8"
    ) as file:
        source = list(csv.DictReader(file))
    return [
        {
            "record_status": row["record_status"],
            "record_type": "inventory_item",
            "service_line": "bistro",
            "internal_sku": row["internal_sku"],
            "supplier_item_name": row["supplier_item_name"],
            "tribunal_item_name": row["tribunal_item_name"],
            "category": row["category"],
            "stock_uom": row["stock_uom"],
            "purchase_uom": row["purchase_uom"],
            "units_per_purchase": row["units_per_purchase"],
            "current_purchase_price": row["current_purchase_price"],
            "current_unit_cost": row["current_unit_cost"],
            "cost_confidence": (
                "NEEDS_VERIFICATION"
                if row["verification_note"].startswith("NEEDS_")
                else "SNAPSHOT"
            ),
            "source_quantity": "",
            "source_subtotal": "",
            "quantity_on_hand": row["quantity_on_hand"],
            "ownership": row["ownership"],
            "consumption_behavior": row["consumption_behavior"],
            "package_option": row["package_option"],
            "package_tags": row["package_tags"],
            "item_tags": row["item_tags"],
            "vendor": row["vendor"],
            "vendor_sku": row["vendor_sku"],
            "external_variant_id": "",
            "pricing_behavior": "inventory_cost",
            "bom_rule": "",
            "source_url": row["source_url"],
            "notes": f"{row['specifications']}; {row['verification_note']}",
        }
        for row in source
    ]


def christmas_rows() -> list[dict[str, str]]:
    with (DOCS / "google-sheets-christmas-inventory-upload.csv").open(
        newline="", encoding="utf-8"
    ) as file:
        source = list(csv.DictReader(file))
    return [
        {
            "record_status": row["record_status"],
            "record_type": row["record_type"],
            "service_line": "christmas",
            "internal_sku": row["internal_sku"],
            "supplier_item_name": row["inventory_item"],
            "tribunal_item_name": row["tribunal_item_name"],
            "category": row["category"],
            "stock_uom": row["unit"],
            "purchase_uom": row["unit"],
            "units_per_purchase": "1",
            "current_purchase_price": (
                row["current_unit_cost"] if row["record_type"] == "inventory_item" else ""
            ),
            "current_unit_cost": row["current_unit_cost"],
            "cost_confidence": row["cost_confidence"],
            "source_quantity": "",
            "source_subtotal": "",
            "quantity_on_hand": row["quantity_on_hand"],
            "ownership": row["ownership"],
            "consumption_behavior": row["consumption_behavior"],
            "package_option": row["package_option"],
            "package_tags": row["package_tags"],
            "item_tags": row["item_tags"],
            "vendor": row["vendor"],
            "vendor_sku": row["vendor_sku"],
            "external_variant_id": "",
            "pricing_behavior": row["pricing_behavior"],
            "bom_rule": "",
            "source_url": "",
            "notes": row["notes"],
        }
        for row in source
    ]


def main() -> None:
    permanent = permanent_holiday_rows()
    write_csv(DOCS / "google-sheets-permanent-holiday-inventory-upload.csv", permanent)

    rows = landscape_rows() + bistro_rows() + permanent + christmas_rows()
    if len(rows) != 95 or len({row["internal_sku"] for row in rows}) != 95:
        raise ValueError("Combined inventory must contain 95 unique rows")
    if sum(row["record_type"] == "cost_rule" for row in rows) != 3:
        raise ValueError("Combined inventory must contain exactly three non-stock cost rules")
    if any(row["quantity_on_hand"] for row in rows):
        raise ValueError("Physical counts must remain blank")
    write_csv(DOCS / "google-sheets-all-inventory-upload.csv", rows)


if __name__ == "__main__":
    main()
