"""Organize inventory items by service category.

Revision ID: 20260903_inventory_services
Revises: 20260903_technician_scoreboard
Create Date: 2026-09-03

The column is additive and nullable. Existing operator categories are never
replaced: linked price-book categories are copied first, then known imported
SKUs fill only rows that are still uncategorized.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260903_inventory_services"
down_revision: str | None = "20260903_technician_scoreboard"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IMPORTED_SERVICE_SKUS: dict[str, tuple[str, ...]] = {
    "Bistro Lighting": (
        "B0DSPYBYM8",
        "B0B6NJ1GSK",
        "255C",
        "515C",
        "105P",
        "056P",
        "062P",
        "B0C1F3ZVXS",
        "B0CHMQW45X",
        "BISTRO-PERM-POLE-CONCRETE",
        "B0FC6DTCX2",
    ),
    "Christmas Lighting": (
        "XMAS-5MM-WW-70-4",
        "XMAS-5MM-RED-70-4",
        "XMAS-5MM-GREEN-70-4",
        "XMAS-5MM-BLUE-70-4",
        "XMAS-5MM-YELLOW-70-4",
        "XMAS-5MM-ORANGE-70-4",
        "XMAS-C9-WW-SB-BULB",
        "XMAS-C9-SOCKET-GRN-15",
        "XMAS-C9-TOUGH-CLIP",
        "XMAS-WIRE-GREEN-NOSOCKET",
        "XMAS-PLUG-MALE-GREEN-10A",
        "XMAS-PLUG-FEMALE-GREEN-10A",
        "XMAS-TIMER-HD-DIGITAL-2",
        "XMAS-GARLAND-PRELIT-9",
        "XMAS-WREATH-PRELIT-36-100",
        "XMAS-WREATH-PRELIT-48-200",
        "XMAS-WREATH-PRELIT-60-400",
        "XMAS-WREATH-PRELIT-72-600",
        "XMAS-BOW-15X28",
        "XMAS-BOW-18X52",
        "XMAS-C7-SOCKET-GRN-24",
        "XMAS-C7-WW-SMD-BULB",
    ),
    "Landscape Lighting": (
        "59009035",
        "59009050",
        "59203512",
        "59205842",
        "59213082",
        "59213092",
        "59213350",
        "59213632",
        "59213710",
        "59214042",
        "59272804",
        "59303512",
        "59304101",
        "59306832",
        "59308530",
        "59311122",
        "59320292",
        "59400232",
        "59403532",
        "59407330",
        "59409010",
        "59409312",
        "59412322",
        "59413032",
    ),
    "Permanent Holiday Lighting": (
        "KIT-CC-100W-D",
        "KIT-CC-100S-D",
        "KIT-CC-100LB-D",
        "KIT-CC-100BR-D",
        "KIT-CC-100G-D",
        "KIT-CC-100BK-D",
        "KIT-CC-150W-D",
        "KIT-CC-150S-D",
        "KIT-CC-150LB-D",
        "KIT-CC-150BR-D",
        "KIT-CC-150G-D",
        "KIT-CC-150BK-D",
        "KIT-CC-200W-D",
        "KIT-CC-200S-D",
        "KIT-CC-200LB-D",
        "KIT-CC-200BR-D",
        "KIT-CC-200G-D",
        "KIT-CC-200BK-D",
        "KIT-CC-400W-D",
        "KIT-CC-400S-D",
        "KIT-CC-400LB-D",
        "KIT-CC-400BR-D",
        "KIT-CC-400G-D",
        "KIT-CC-400BK-D",
        "RGB+PT-12B",
        "RGB+PT-12W",
        "RGB+PT-12S",
        "RGB+BMT-4WB",
        "RGB+BMT-4WW",
        "RGB+BMT-4WS",
        "RGB+SR-B",
        "RGB+SR-W",
        "RGB+SR-S",
        "RGB+5A-24V",
        "B08282SQPT",
    ),
}


def upgrade() -> None:
    """Add service grouping and safely classify existing known inventory."""
    op.add_column(
        "inventory_items",
        sa.Column("service_category", sa.String(length=60), nullable=True),
    )

    # A linked price-book item is the strongest existing source of service truth.
    op.execute(
        """
        UPDATE inventory_items AS inventory
        SET service_category = NULLIF(BTRIM(catalog.service_category), '')
        FROM catalog_items AS catalog
        WHERE inventory.catalog_item_id = catalog.id
          AND inventory.workspace_id = catalog.workspace_id
          AND inventory.service_category IS NULL
          AND NULLIF(BTRIM(catalog.service_category), '') IS NOT NULL
        """
    )

    inventory_items = sa.table(
        "inventory_items",
        sa.column("sku", sa.String(length=100)),
        sa.column("service_category", sa.String(length=60)),
    )
    connection = op.get_bind()
    for category, skus in _IMPORTED_SERVICE_SKUS.items():
        connection.execute(
            sa.update(inventory_items)
            .where(
                inventory_items.c.service_category.is_(None),
                inventory_items.c.sku.in_(skus),
            )
            .values(service_category=category)
        )


def downgrade() -> None:
    """Remove service grouping only in disposable rollback-test databases."""
    # Production rollback should use a forward fix or a verified backup because
    # dropping this column discards operator-assigned service categories.
    op.drop_column("inventory_items", "service_category")
