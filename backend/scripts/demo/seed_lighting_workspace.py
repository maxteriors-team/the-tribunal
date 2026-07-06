"""Seed a workspace with the Maxteriors landscape-lighting sales config.

Ports the uploaded wizard's ``CONFIG`` object (Sales-tools/index.html) into the
per-workspace data model:

  * ``workspace.settings["pricing"]`` — tax, Wisetack financing, cash/check
    pricing, commission, Good/Better/Best tiers, Care Plan, savings, bistro.
  * ``catalog_items`` — the 20-fixture price book, keyed by the wizard's stable
    fixture ids (stored as ``sku``), each carrying its ``transformer`` attribute
    and internal SKU bill-of-materials for the fulfillment sheet.

Idempotent: re-running updates catalog items in place (matched by sku) and
overwrites the ``pricing`` settings block. Nothing else in the workspace is
touched. "Fork the data, not the code": a second lighting brand is this script
with different numbers, pointed at its own workspace.

Run:
    cd backend && uv run python -m scripts.demo.seed_lighting_workspace --workspace <slug-or-uuid>
"""

from __future__ import annotations

import argparse
import asyncio
import uuid

from sqlalchemy import or_, select

from app.db.session import AsyncSessionLocal
from app.models.catalog import CatalogItem
from app.models.workspace import Workspace
from app.schemas.pricing import PricingSettings
from app.services.quotes.pricing_config import SETTINGS_KEY

# ─── Fixture catalog (net prices — the engine grosses up at quote time) ──────
# name, net price, transformer?, [(sku, description, qty), ...]
FIXTURES: dict[str, dict] = {
    "best-luxor": {
        "name": "Luxor Smart 300W Transformer",
        "price": 2266,
        "transformer": True,
        "parts": [
            ("59409312", "Luxor 300W Transformer", 1),
            ("59409010", "Luxor WiFi Module", 1),
        ],
    },
    "best-zdc-up": {
        "name": "ZDC Color Uplight",
        "price": 785,
        "parts": [("59400232", "NP ZDC FB Up Light Black", 1)],
    },
    "best-zdc-down": {
        "name": "ZDC Down Light",
        "price": 963,
        "parts": [
            ("59413032", "ZDC Down Light", 1),
            ("BM-050-C-AB", "Mounting Bracket", 1),
        ],
    },
    "best-zdc-mod-path": {
        "name": "ZDC Modern Color Path Light",
        "price": 805,
        "parts": [("59403532", "ZDC Modern Color Path Light Black", 1)],
    },
    "best-zdc-path2": {
        "name": "ZDC Path Light",
        "price": 1001,
        "parts": [
            ("59412322", "ZDC Path Light Body Black", 1),
            ("59213632", "HC-LED-TA-FB Top Assembly Black", 1),
        ],
    },
    "best-zd-up": {
        "name": "ZD Uplight",
        "price": 411,
        "parts": [
            ("59213092", "CORA Accent Black", 1),
            ("59308530", "MR16 Lamp", 1),
        ],
    },
    "best-zd-narrow": {
        "name": "ZD Narrow Beam Accent",
        "price": 556,
        "parts": [("59320262", "ZD Narrow Beam Accent Light", 1)],
    },
    "best-zd-mod-path": {
        "name": "ZD Modern Path Light",
        "price": 566,
        "parts": [("59303512", "M PL ZD 1LED FB Path Light Black", 1)],
    },
    "best-zd-path": {
        "name": "ZD Path Light",
        "price": 580,
        "parts": [
            ("59213632", "Path Light Top Assembly", 1),
            ("59311122", "18in Riser Path Light", 1),
        ],
    },
    "best-zd-down": {
        "name": "ZD Down Light",
        "price": 528,
        "parts": [
            ("59213082", "ZD Down Light Body", 1),
            ("59308530", "ZD MR-16 5W Lamp", 1),
        ],
    },
    "best-cora-in-grade": {
        "name": "ZD In-Grade Uplight",
        "price": 436,
        "parts": [
            ("59213370", "CORA In-Grade Black", 1),
            ("59308530", "MR16 Lamp", 1),
        ],
    },
    "better-dx": {
        "name": "DX 300W Transformer",
        "price": 1072,
        "transformer": True,
        "parts": [("59009035", "DX 300W Transformer", 1)],
    },
    "better-well": {
        "name": "Well Light",
        "price": 514,
        "parts": [("CN-73", "Well Light", 1)],
    },
    "better-accent": {
        "name": "Accent Uplight",
        "price": 386,
        "parts": [("59213092", "Cora Accent Black", 1)],
    },
    "better-path": {
        "name": "Pathway Light",
        "price": 376,
        "parts": [("59205842", "TM Path Light Body", 1)],
    },
    "better-mod-path": {
        "name": "Modern Path Light",
        "price": 511,
        "parts": [("59203512", "Modern Path Light", 1)],
    },
    "better-cora-in-grade": {
        "name": "In-Grade Uplight",
        "price": 447,
        "parts": [("59213370", "CORA In-Grade Black", 1)],
    },
    "ess-ex": {
        "name": "EX 150W Transformer",
        "price": 504,
        "transformer": True,
        "parts": [("59009050", "EX 150W Transformer", 1)],
    },
    "ess-accent": {
        "name": "EVO Accent Uplight",
        "price": 172,
        "parts": [("59214042", "EVO Accent Black Complete", 1)],
    },
    "ess-path": {
        "name": "Pathway Light",
        "price": 376,
        "parts": [("59205842", "TM Path Light Body", 1)],
    },
}

# ─── Pricing config (the wizard's CONFIG minus the catalog) ──────────────────
PRICING: dict = {
    "tax": {"enabled": False, "rate": 0.06, "method": "Exclusive", "label": "Sales Tax"},
    "financing": {
        "enabled": True,
        "provider": "Wisetack",
        "max_amount": 25000,
        "terms": [6, 12, 24],
        "default_term": 24,
        "apr": 0.0,
        "fee_buffer": 0.11,
        "headline": "Own the night now — 0% APR for up to 24 months.",
        "body": (
            "Through our partner Wisetack, your project can be split into easy "
            "monthly payments at 0% APR — no interest, ever. Choose the term "
            "that fits your budget. Checking your options takes about a minute, "
            "is a soft credit check, and won\u2019t affect your credit score."
        ),
        "points": [
            "One-minute application — right from your phone",
            "Soft check — no impact on your credit score",
            "0% APR — no interest, no prepayment fees, no late fees",
        ],
        "disclaimer": (
            "Estimated payment for illustration only, assuming approved credit. "
            "0% APR financing for up to 24 months is subject to credit approval; "
            "your terms may vary. Payment options through Wisetack are provided "
            "by its lending partners. See wisetack.com/faqs."
        ),
    },
    "cash_discount": {
        "enabled": True,
        "card_reserve_rate": 0.03,
        "label": "Cash / Check Pricing",
    },
    "commission": {
        "enabled": True,
        "rate": 0.12,
        "in_price": False,
        "label": "Sales Commission",
    },
    "tier_order": ["best", "better", "essential"],
    "tiers": [
        {
            "key": "best",
            "label": "Best — The Premier",
            "tab": "Best",
            "tab_sub": "The Premier",
            "marker": "\u2605",
            "card_tier": "Best",
            "name": "The Premier",
            "warranty": "9-Year Fixture Warranty",
            "experience": (
                "The full canvas. Color-changing fixtures, WiFi app control, and "
                "smart home integration. Your home, transformed."
            ),
            "points": [
                "Color change — 16 million possibilities from your phone",
                "Smart home ready: Lutron, Savant, Control4",
                "Aircraft aluminum — built to last a lifetime",
            ],
            "value_tag": "\u2605 Maximum Value",
            "sections": [
                {"title": "Smart Transformer", "item_ids": ["best-luxor"]},
                {
                    "title": "ZDC Color Fixtures",
                    "item_ids": [
                        "best-zdc-up",
                        "best-zdc-down",
                        "best-zdc-mod-path",
                        "best-zdc-path2",
                    ],
                },
                {
                    "title": "ZD Standard Fixtures",
                    "item_ids": [
                        "best-zd-up",
                        "best-zd-narrow",
                        "best-zd-mod-path",
                        "best-zd-path",
                        "best-zd-down",
                        "best-cora-in-grade",
                    ],
                },
            ],
        },
        {
            "key": "better",
            "label": "Better — The Professional",
            "tab": "Better",
            "tab_sub": "The Professional",
            "marker": "\u25c6",
            "card_tier": "Better",
            "name": "The Professional",
            "warranty": "6-Year Fixture Warranty",
            "experience": (
                "Architectural drama that stops people at the curb. Premium brass "
                "fixtures, programmable control, ready to upgrade."
            ),
            "points": [
                "Architectural uplighting on every focal point",
                "Black brass construction — timeless, durable",
                "Upgradeable to full smart control anytime",
            ],
            "popular": True,
            "sections": [
                {"title": "Transformer", "item_ids": ["better-dx"]},
                {
                    "title": "Fixtures",
                    "item_ids": [
                        "better-well",
                        "better-accent",
                        "better-path",
                        "better-mod-path",
                        "better-cora-in-grade",
                    ],
                },
            ],
        },
        {
            "key": "essential",
            "label": "Good — The Starter",
            "tab": "Good",
            "tab_sub": "The Starter",
            "marker": "\u25cf",
            "card_tier": "Good",
            "name": "The Starter",
            "warranty": "4-Year Fixture Warranty",
            "experience": (
                "Your home gets noticed. Key areas lit beautifully, cleanly "
                "installed, with room to grow."
            ),
            "points": [
                "Key area coverage — entry, trees, focal points",
                "Clean, professional installation",
                "Expandable as your vision grows",
            ],
            "sections": [
                {"title": "Transformer", "item_ids": ["ess-ex"]},
                {"title": "Fixtures", "item_ids": ["ess-accent", "ess-path"]},
            ],
        },
    ],
    "care_plan": {
        "free_fixtures": 10,
        "tiers": [
            {
                "key": "essential",
                "name": "Essential",
                "base": 179,
                "per_fixture": 15,
                "visits": 1,
                "repair_discount": 0,
                "blurb": "1 maintenance visit a year \u00b7 cleaning, re-aiming, system check",
            },
            {
                "key": "premier",
                "name": "Premier",
                "base": 299,
                "per_fixture": 25,
                "visits": 2,
                "repair_discount": 0.10,
                "blurb": "2 visits a year \u00b7 10% off any repairs",
                "popular": True,
            },
            {
                "key": "elite",
                "name": "Elite",
                "base": 499,
                "per_fixture": 40,
                "visits": 4,
                "repair_discount": 0.15,
                "blurb": "4 visits a year \u00b7 15% off any repairs \u00b7 priority service",
            },
        ],
    },
    "savings": {
        "per_visit_value": 179,
        "avoided_repair_per_fixture": 28,
        "assumed_repair_spend_per_fixture": 40,
    },
    "bistro": {
        "enabled": True,
        "minimum": 2307,
        "tiers": [
            {
                "key": "easy",
                "name": "Easy",
                "desc": "Straight runs, low height",
                "per_ft": 14.86,
                "classic_per_ft": 11.63,
            },
            {
                "key": "medium",
                "name": "Medium",
                "desc": "Some angles, 8\u201312 ft height",
                "per_ft": 18.11,
                "classic_per_ft": 15.50,
            },
            {
                "key": "complex",
                "name": "Complex",
                "desc": "Rooflines, high or irregular",
                "per_ft": 28.22,
                "classic_per_ft": 20.68,
            },
        ],
        "color": {
            "name": "Color Changing Bistro Lights",
            "subtitle": (
                "Minleon RGBW+2 \u00b7 color-changing string lights for patios, "
                "pergolas & entertaining areas"
            ),
            "hardware": 577,
            "strand_lengths": [50, 40, 20, 10, 4, 2],
        },
        "classic": {
            "name": "Classic Bistro Lights",
            "subtitle": (
                "S14 vintage warm-white LED \u00b7 remote-controlled dimmable string lights"
            ),
            "hardware": 35,
            "min_footage": 200,
            "bulb_spacing_ft": 2,
        },
    },
    # Permanent holiday lighting — placeholder rates the operator tunes later.
    "permanent": {
        "enabled": True,
        "per_ft": 32,
        "controller_base": 299,
        "per_channel": 45,
        "included_channels": 1,
        "minimum": 0,
        "label": "Permanent Holiday Lighting",
    },
    # Seasonal Christmas lighting — placeholder rates the operator tunes later.
    "christmas": {
        "enabled": True,
        "roofline_per_ft": 6,
        "tree_rates": [
            {"key": "small", "name": "Small tree (up to 8 ft)", "price": 120},
            {"key": "medium", "name": "Medium tree (8\u201315 ft)", "price": 260},
            {"key": "large", "name": "Large tree (15\u201325 ft)", "price": 520},
        ],
        "bush_rates": [
            {"key": "small", "name": "Small bush / shrub", "price": 35},
            {"key": "large", "name": "Large bush / shrub", "price": 65},
        ],
        "wreath_rates": [
            {"key": "standard", "name": "Wreath (up to 36 in)", "price": 85},
            {"key": "large", "name": "Large wreath (over 36 in)", "price": 150},
        ],
        "takedown_enabled": True,
        "takedown_rate": 0.25,
        "storage_price": 0,
        "minimum": 0,
        "label": "Christmas Lighting",
    },
}


async def seed(workspace_ref: str) -> None:
    # Validate the whole blob against the schema before touching the DB.
    validated = PricingSettings(**PRICING)

    async with AsyncSessionLocal() as db:
        # Resolve workspace by slug, or by UUID when the ref parses as one.
        clauses = [Workspace.slug == workspace_ref]
        try:
            clauses.append(Workspace.id == uuid.UUID(workspace_ref))
        except ValueError:
            pass
        workspace = (await db.execute(select(Workspace).where(or_(*clauses)))).scalar_one_or_none()
        if workspace is None:
            raise SystemExit(f"Workspace not found: {workspace_ref!r}")

        # ── Catalog upsert (matched by sku = the wizard's stable fixture id) ──
        existing = {
            item.sku: item
            for item in (
                await db.execute(
                    select(CatalogItem).where(
                        CatalogItem.workspace_id == workspace.id,
                        CatalogItem.sku.in_(FIXTURES.keys()),
                    )
                )
            ).scalars()
        }
        created = updated = 0
        for key, fx in FIXTURES.items():
            components = [
                {"sku": sku, "description": desc, "qty": qty} for sku, desc, qty in fx["parts"]
            ]
            attributes = {"transformer": True} if fx.get("transformer") else None
            item = existing.get(key)
            if item is None:
                db.add(
                    CatalogItem(
                        workspace_id=workspace.id,
                        name=fx["name"],
                        sku=key,
                        kind="product",
                        unit_price=fx["price"],
                        taxable=True,
                        is_active=True,
                        attributes=attributes,
                        components=components,
                    )
                )
                created += 1
            else:
                item.name = fx["name"]
                item.kind = "product"
                item.unit_price = fx["price"]
                item.is_active = True
                item.attributes = attributes
                item.components = components
                updated += 1

        # ── Pricing settings (overwrite the whole block, validated above) ──
        settings = dict(workspace.settings or {})
        settings[SETTINGS_KEY] = validated.model_dump(mode="json")
        workspace.settings = settings

        await db.commit()
        print(
            f"Seeded workspace '{workspace.name}' ({workspace.id}): "
            f"{created} catalog items created, {updated} updated, pricing config written."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace",
        required=True,
        help="Workspace slug or UUID to seed with the lighting sales config",
    )
    args = parser.parse_args()
    asyncio.run(seed(args.workspace))


if __name__ == "__main__":
    main()
