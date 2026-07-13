#!/usr/bin/env python3
"""Backfill a pipeline opportunity for existing contacts that have no open card.

The auto-pipeline feature opens an Opportunity for every *new* inbound lead so it
lands on the Opportunities board. Contacts captured before the feature shipped
have no card, so this script idempotently opens one (in the workspace's default
pipeline / first stage) for each active-workspace contact that has no open
opportunity.

Reuses :func:`app.services.opportunities.open_lead_opportunity`, so it honors the
same per-workspace ``auto_pipeline.enabled`` gate and the same "never two open
cards per contact" dedupe as the live funnels. Workspaces with auto-pipeline
disabled are skipped.

Usage
-----

    # Dry-run (default of --dry-run: count work, write nothing):
    cd backend && uv run python scripts/backfills/backfill_lead_opportunities.py \
        --env local --dry-run

    # Real run, all active workspaces:
    cd backend && uv run python scripts/backfills/backfill_lead_opportunities.py --env local

    # Scope to a single workspace, cap per-workspace work:
    cd backend && uv run python scripts/backfills/backfill_lead_opportunities.py \
        --env local --workspace-id <uuid> --limit 500

Safe to re-run: contacts that already have an open card are skipped.
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
        help="Only backfill this workspace (default: every active workspace).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Cap the number of contacts backfilled per workspace (default: no cap).",
    )


async def _run(
    ctx: ExecutionContext,
    workspace_id: uuid.UUID | None,
    limit: int | None,
) -> int:
    """Open a pipeline card for every contact lacking an open opportunity."""
    from sqlalchemy import exists, select

    from app.db.session import AsyncSessionLocal
    from app.models.contact import Contact
    from app.models.opportunity import Opportunity
    from app.models.workspace import Workspace
    from app.services.opportunities import auto_pipeline_enabled, open_lead_opportunity

    ctx.announce(
        "backfill lead opportunities",
        workspace_id=str(workspace_id or "all"),
        limit=limit if limit is not None else "none",
    )
    ctx.confirm("backfill lead opportunities")

    created = 0
    skipped_disabled = 0
    workspaces_touched = 0

    async with AsyncSessionLocal() as db:
        ws_query = select(Workspace).where(Workspace.is_active.is_(True))
        if workspace_id is not None:
            ws_query = ws_query.where(Workspace.id == workspace_id)
        workspaces = (await db.execute(ws_query.order_by(Workspace.created_at))).scalars().all()

        for workspace in workspaces:
            if not auto_pipeline_enabled(workspace):
                skipped_disabled += 1
                continue

            # Contacts in this workspace with no *open* opportunity.
            has_open_card = (
                exists()
                .where(
                    Opportunity.primary_contact_id == Contact.id,
                    Opportunity.workspace_id == workspace.id,
                    Opportunity.status == "open",
                )
                .correlate(Contact)
            )
            contact_query = (
                select(Contact)
                .where(Contact.workspace_id == workspace.id, ~has_open_card)
                .order_by(Contact.created_at)
            )
            if limit is not None:
                contact_query = contact_query.limit(limit)
            contacts = (await db.execute(contact_query)).scalars().all()

            if not contacts:
                continue
            workspaces_touched += 1

            for contact in contacts:
                if ctx.dry_run:
                    created += 1
                    continue
                opportunity = await open_lead_opportunity(
                    db, workspace.id, contact, source="backfill"
                )
                if opportunity is not None:
                    created += 1

            if not ctx.dry_run:
                await db.commit()
                log_event(
                    logger,
                    logging.INFO,
                    "workspace backfilled",
                    workspace_id=str(workspace.id),
                    contacts=len(contacts),
                )

        log_event(
            logger,
            logging.INFO,
            "backfill complete",
            cards_created=created,
            workspaces_touched=workspaces_touched,
            workspaces_total=len(workspaces),
            skipped_disabled=skipped_disabled,
            dry_run=ctx.dry_run,
        )

    return EXIT_OK


def main() -> int:
    """Parse arguments and run the backfill."""
    ctx, args = bootstrap(
        description=__doc__ or "Backfill lead opportunities.",
        writes=True,
        logger_name="backfill",
        configure=_configure,
    )
    workspace_id = uuid.UUID(args.workspace_id) if args.workspace_id else None
    return asyncio.run(_run(ctx, workspace_id, args.limit))


if __name__ == "__main__":
    raise SystemExit(run(main))
