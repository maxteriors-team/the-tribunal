"""Denormalize attach metrics onto quotes.

Revision ID: cacf6d2e5463
Revises: 71c97e2a8a94
Create Date: 2026-07-29 11:30:19.764763

"Average job value" and "attach rate" previously needed a join from ``quotes``
into ``quote_line_items`` plus a group-by per quote just to learn what service a
quote was for. ``quotes.primary_service`` / ``attach_count`` / ``attach_value``
carry that answer inline, re-derived by the quote service on every save, so
reporting is one indexed scan.

``quote_line_items.service_category`` is the snapshot those metrics group on,
copied from the picked ``catalog_items`` row. Intentionally a plain VARCHAR with
no foreign key: price-book items get re-categorized and deleted while a quote is
a historical record of what was sold, so a FK would either block those deletes or
blank out settled history.

Purely additive and safe on live data: the two new NOT NULL columns land with
server defaults (no table rewrite, no downtime), and both new nullable columns
read as "uncategorized" until backfilled.

The backfill is best-effort by design (step 1 below), because the category column
it feeds on did not exist until this migration:

1. Recover each historical line's category by matching its name against the
   workspace's price book. Only *unambiguous* matches are used \u2014 a name must
   resolve to exactly one non-null category within that workspace \u2014 so a
   duplicated or conflicting price-book name leaves the line uncategorized
   rather than guessing a category that reporting would then treat as fact.
2. Recompute the three quote columns from whatever step 1 recovered, using the
   same rule as ``app.services.quotes.attach_metrics.compute_attach_metrics``:
   the largest summed category wins, ties break by the largest single line and
   then alphabetically. Quotes with no recoverable category keep the column
   defaults (NULL / 0 / 0), which reporting reads as unknown, not as zero attach.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "cacf6d2e5463"
down_revision: str | None = "71c97e2a8a94"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRIMARY_SERVICE_INDEX = "ix_quotes_primary_service"

# Step 1: recover line categories from the price book by unambiguous name match.
# ``HAVING count(DISTINCT ...) = 1`` is the guard that keeps an ambiguous name
# (two "Gutter Guard" items filed under different categories) out of the result.
BACKFILL_LINE_CATEGORIES = """
WITH catalog_names AS (
    SELECT
        ci.workspace_id                 AS workspace_id,
        lower(btrim(ci.name))           AS name_key,
        min(btrim(ci.service_category)) AS service_category
    FROM catalog_items ci
    WHERE ci.service_category IS NOT NULL
      AND btrim(ci.service_category) <> ''
      AND btrim(ci.name) <> ''
    GROUP BY ci.workspace_id, lower(btrim(ci.name))
    HAVING count(DISTINCT btrim(ci.service_category)) = 1
)
UPDATE quote_line_items li
SET service_category = cn.service_category
FROM quotes q, catalog_names cn
WHERE li.quote_id = q.id
  AND cn.workspace_id = q.workspace_id
  AND lower(btrim(li.name)) = cn.name_key
  AND li.service_category IS NULL
"""

# Step 2: recompute the denormalized triple from the recovered line categories.
BACKFILL_QUOTE_METRICS = """
WITH category_totals AS (
    SELECT
        li.quote_id            AS quote_id,
        btrim(li.service_category) AS category,
        sum(li.total)          AS category_total,
        max(li.total)          AS largest_line
    FROM quote_line_items li
    WHERE li.service_category IS NOT NULL
      AND btrim(li.service_category) <> ''
    GROUP BY li.quote_id, btrim(li.service_category)
),
ranked AS (
    SELECT
        ct.*,
        row_number() OVER (
            PARTITION BY ct.quote_id
            ORDER BY ct.category_total DESC, ct.largest_line DESC, ct.category ASC
        ) AS rank
    FROM category_totals ct
),
primary_pick AS (
    SELECT quote_id, category FROM ranked WHERE rank = 1
),
metrics AS (
    SELECT
        p.quote_id AS quote_id,
        p.category AS primary_service,
        count(*) FILTER (WHERE ct.category <> p.category) AS attach_count,
        coalesce(sum(ct.category_total) FILTER (WHERE ct.category <> p.category), 0)
            AS attach_value
    FROM primary_pick p
    JOIN category_totals ct ON ct.quote_id = p.quote_id
    GROUP BY p.quote_id, p.category
)
UPDATE quotes q
SET primary_service = m.primary_service,
    attach_count    = m.attach_count,
    attach_value    = m.attach_value
FROM metrics m
WHERE q.id = m.quote_id
"""


def upgrade() -> None:
    op.add_column(
        "quote_line_items",
        sa.Column("service_category", sa.String(length=60), nullable=True),
    )
    op.add_column("quotes", sa.Column("primary_service", sa.String(length=60), nullable=True))
    op.add_column(
        "quotes",
        sa.Column("attach_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "quotes",
        sa.Column(
            "attach_value",
            sa.Numeric(precision=12, scale=2),
            server_default="0",
            nullable=False,
        ),
    )
    op.create_index(PRIMARY_SERVICE_INDEX, "quotes", ["primary_service"], unique=False)

    # Backfill after the index exists so the metrics UPDATE lands on an indexed
    # column; both statements are no-ops on an empty or uncategorized database.
    op.execute(sa.text(BACKFILL_LINE_CATEGORIES))
    op.execute(sa.text(BACKFILL_QUOTE_METRICS))


def downgrade() -> None:
    op.drop_index(PRIMARY_SERVICE_INDEX, table_name="quotes")
    op.drop_column("quotes", "attach_value")
    op.drop_column("quotes", "attach_count")
    op.drop_column("quotes", "primary_service")
    op.drop_column("quote_line_items", "service_category")
