"""Fold a drifted ``service_category`` spelling onto its canonical name.

``service_category`` is free-form text by design — an operator must be able to
type a new service without a migration — and every report groups on the exact
string. So two spellings of one service silently split it in half: a rep's
close rate for landscape lighting lands in two rows that each look like a
smaller, noisier business than the real one.

Only the aliases declared in :data:`CATEGORY_ALIASES` are folded. A category
nobody declared is left exactly as typed: this script corrects known drift, it
never guesses that two similar-looking names mean the same service.

Dry-run is the default and ``--apply`` is required to write. Everything is
scoped to one workspace and runs in a single transaction.

    python -m scripts.ops.normalize_service_categories --workspace <slug-or-uuid>
    python -m scripts.ops.normalize_service_categories --workspace <slug-or-uuid> --apply
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from contextlib import suppress
from dataclasses import dataclass, field

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import AsyncSessionLocal
from app.models.catalog import CatalogItem
from app.models.quote import Quote
from app.models.workspace import Workspace
from app.services.quotes.attach_metrics import compute_attach_metrics

# Drifted spelling (matched case-insensitively, after trimming) -> canonical
# name. The canonical side must match what onboarding seeds in
# ``app/services/workspaces/default_sales_setup.py``; that is the spelling a
# workspace starts life with, so it is the one everything else has to agree
# with.
CATEGORY_ALIASES: dict[str, str] = {"landscape": "Landscape Lighting"}


@dataclass(slots=True)
class NormalizeResult:
    workspace_name: str
    catalog_updated: int = 0
    line_items_updated: int = 0
    quotes_recomputed: int = 0
    manifest: list[str] = field(default_factory=list)


def canonical_for(raw: str | None) -> str | None:
    """Return the canonical spelling for ``raw``, or None to leave it alone.

    Returns None for a value that is already canonical, so a caller can treat
    "no rename" and "not a declared alias" identically: both mean don't write.
    """
    if raw is None:
        return None
    cleaned = raw.strip()
    canonical = CATEGORY_ALIASES.get(cleaned.casefold())
    if canonical is None or canonical == cleaned:
        return None
    return canonical


async def _resolve_workspace(db: AsyncSession, workspace_ref: str) -> Workspace:
    clauses = [Workspace.slug == workspace_ref]
    with suppress(ValueError):
        clauses.append(Workspace.id == uuid.UUID(workspace_ref))
    workspace = (await db.execute(select(Workspace).where(or_(*clauses)))).scalar_one_or_none()
    if workspace is None:
        raise SystemExit(f"Workspace not found: {workspace_ref!r}")
    return workspace


async def _normalize(db: AsyncSession, workspace_ref: str) -> NormalizeResult:
    workspace = await _resolve_workspace(db, workspace_ref)
    result = NormalizeResult(workspace_name=workspace.name)

    catalog_items = (
        (
            await db.execute(
                select(CatalogItem).where(
                    CatalogItem.workspace_id == workspace.id,
                    CatalogItem.service_category.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for item in catalog_items:
        canonical = canonical_for(item.service_category)
        if canonical is None:
            continue
        result.manifest.append(
            f"- catalog  {item.sku or item.id} {item.service_category!r} -> {canonical!r}"
        )
        item.service_category = canonical
        result.catalog_updated += 1

    # Line items carry a *snapshot* of the category, deliberately not a FK, so
    # they must be corrected in place — a quote whose line still reads the old
    # spelling keeps reporting under a service the price book no longer has.
    quotes = (
        (
            await db.execute(
                select(Quote)
                .where(Quote.workspace_id == workspace.id)
                .options(selectinload(Quote.line_items))
            )
        )
        .scalars()
        .all()
    )
    for quote in quotes:
        renamed = 0
        for line in quote.line_items:
            canonical = canonical_for(line.service_category)
            if canonical is None:
                continue
            result.manifest.append(
                f"- line     {quote.number} {line.service_category!r} -> "
                f"{canonical!r} ({line.name})"
            )
            line.service_category = canonical
            renamed += 1
        if not renamed:
            continue
        result.line_items_updated += renamed

        # Derived fields are recomputed from the corrected lines rather than
        # renamed in place, so they can never disagree with the rule that
        # produces them everywhere else.
        primary, attach_count, attach_value = compute_attach_metrics(quote.line_items)
        if (primary, attach_count, attach_value) != (
            quote.primary_service,
            quote.attach_count,
            quote.attach_value,
        ):
            result.manifest.append(
                f"- quote    {quote.number} primary {quote.primary_service!r} -> {primary!r}"
            )
            quote.primary_service = primary
            quote.attach_count = attach_count
            quote.attach_value = attach_value
            result.quotes_recomputed += 1

    return result


async def normalize(workspace_ref: str, *, apply: bool) -> NormalizeResult:
    async with AsyncSessionLocal() as db:
        transaction = await db.begin()
        try:
            result = await _normalize(db, workspace_ref)
            await db.flush()
            if apply:
                await transaction.commit()
        finally:
            # Covers the dry run, any exception, and ``SystemExit`` from an
            # unresolvable workspace — which is not an ``Exception``, so an
            # ``except Exception`` here would leave the transaction open.
            if transaction.is_active:
                await transaction.rollback()

    print(f"Workspace: {result.workspace_name}")
    print(f"Aliases:   {CATEGORY_ALIASES}")
    for line in result.manifest:
        print(line)
    print(
        f"catalog updated: {result.catalog_updated} | "
        f"line items updated: {result.line_items_updated} | "
        f"quotes recomputed: {result.quotes_recomputed}"
    )
    print("APPLIED" if apply else "DRY RUN — ROLLED BACK (pass --apply to write)")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, help="Workspace slug or UUID")
    parser.add_argument("--apply", action="store_true", help="Write the changes")
    args = parser.parse_args()
    asyncio.run(normalize(args.workspace, apply=args.apply))


if __name__ == "__main__":
    main()
