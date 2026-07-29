#!/usr/bin/env python3
"""Backfill Service Plans for quotes approved before the feature shipped.

Approving a quote now provisions the Service Plans the client signed up for — a
Care Plan at the tier they picked, or the Christmas install + takedown pair.
Clients who approved *before* that shipped have the signup sitting in their
proposal snapshot and no plan to show for it, which is invisible lost recurring
revenue: nobody is scheduled to service their lighting or hang their lights.

This script replays the provisioner over already-approved quotes. It reuses
:class:`app.services.recurring_jobs.ServicePlanProvisioner`, so a backfilled plan
is byte-for-byte what a fresh approval would have created — one code path, no
second definition of what a signup means. Season anchors come from each
workspace's own pricing config, and the plan cursors are computed from the
quote's original ``approved_at``, so an old signup still lands on the next
upcoming season rather than in the past.

Safe to re-run: the provisioner is idempotent per quote, guarded by the partial
unique index on ``(source_quote_id, plan_type, title)``. A quote that already has
its plans is skipped, and a race with a concurrent approval loses cleanly.

Usage
-----

    # Dry-run (default of --dry-run: count work, write nothing):
    cd backend && uv run python scripts/backfills/backfill_service_plans.py \
        --env local --dry-run

    # Real run, every workspace:
    cd backend && uv run python scripts/backfills/backfill_service_plans.py --env local

    # Scope to one workspace, cap the work:
    cd backend && uv run python scripts/backfills/backfill_service_plans.py \
        --env local --workspace-id <uuid> --limit 500
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import uuid
from pathlib import Path

# --- harness bootstrap: locate ``backend/`` so ``app`` + ``scripts`` import ----
_BACKEND_DIR = next(
    p / "backend"
    for p in Path(__file__).resolve().parents
    if (p / "backend" / "scripts" / "_harness.py").is_file()
)
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from scripts._harness import (  # noqa: E402
    EXIT_OK,
    ExecutionContext,
    bootstrap,
    log_event,
    run,
)

logger = logging.getLogger("backfill")


def _configure(parser: argparse.ArgumentParser) -> None:
    """Add the optional scope + safety-cap flags."""
    parser.add_argument(
        "--workspace-id",
        type=str,
        metavar="UUID",
        help="Only backfill this workspace (default: every workspace).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Cap the number of approved quotes processed (default: no cap).",
    )


async def _run(
    ctx: ExecutionContext,
    workspace_id: uuid.UUID | None,
    limit: int | None,
) -> int:
    """Provision Service Plans for every approved quote that has none."""
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models.quote import Quote
    from app.models.recurring_job import RecurringJobTemplate
    from app.services.recurring_jobs import ServicePlanProvisioner

    ctx.announce(
        "backfill service plans",
        workspace_id=str(workspace_id or "all"),
        limit=limit if limit is not None else "none",
    )
    ctx.confirm("backfill service plans")

    quotes_scanned = 0
    quotes_provisioned = 0
    plans_created = 0

    async with AsyncSessionLocal() as db:
        # Only approved quotes carrying a proposal snapshot can describe a
        # signup, and one that already has a plan needs no second look.
        already_provisioned = select(RecurringJobTemplate.source_quote_id).where(
            RecurringJobTemplate.source_quote_id.is_not(None)
        )
        query = (
            select(Quote)
            .where(
                Quote.status == "approved",
                Quote.proposal_document.is_not(None),
                Quote.contact_id.is_not(None),
                Quote.id.not_in(already_provisioned),
            )
            .order_by(Quote.approved_at)
        )
        if workspace_id is not None:
            query = query.where(Quote.workspace_id == workspace_id)
        if limit is not None:
            query = query.limit(limit)
        quotes = (await db.execute(query)).scalars().all()

        provisioner = ServicePlanProvisioner(db)
        for quote in quotes:
            quotes_scanned += 1
            if ctx.dry_run:
                continue
            created = await provisioner.provision_from_quote(quote)
            if not created:
                continue
            await db.commit()
            quotes_provisioned += 1
            plans_created += len(created)
            log_event(
                logger,
                logging.INFO,
                "quote backfilled",
                quote_id=str(quote.id),
                workspace_id=str(quote.workspace_id),
                plans=len(created),
            )

        log_event(
            logger,
            logging.INFO,
            "backfill complete",
            quotes_scanned=quotes_scanned,
            quotes_provisioned=quotes_provisioned,
            plans_created=plans_created,
            dry_run=ctx.dry_run,
        )

    return EXIT_OK


def main() -> int:
    """Parse arguments and run the backfill."""
    ctx, args = bootstrap(
        description=__doc__ or "Backfill service plans.",
        writes=True,
        logger_name="backfill",
        configure=_configure,
    )
    workspace_id = uuid.UUID(args.workspace_id) if args.workspace_id else None
    return asyncio.run(_run(ctx, workspace_id, args.limit))


if __name__ == "__main__":
    raise SystemExit(run(main))
