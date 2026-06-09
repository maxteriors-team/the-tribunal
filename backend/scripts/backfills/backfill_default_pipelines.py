#!/usr/bin/env python3
"""Backfill a default pipeline for every active workspace that lacks one.

Workspaces created before default-pipeline provisioning have no active pipeline,
so the ad-library promotion flow logs ``promotion_no_pipeline`` and the
opportunities board has no columns to render. This script idempotently ensures
each active workspace has the standard default pipeline + ordered stages.

Usage
-----

    # Dry-run (default of --dry-run: count work, write nothing):
    cd backend && uv run python scripts/backfills/backfill_default_pipelines.py \
        --env local --dry-run

    # Real run, all active workspaces:
    cd backend && uv run python scripts/backfills/backfill_default_pipelines.py --env local

    # Scope to a single workspace:
    cd backend && uv run python scripts/backfills/backfill_default_pipelines.py \
        --env local --workspace-id <uuid>

Safe to re-run: workspaces that already have an active pipeline are skipped.
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
    """Add the optional single-workspace scope flag."""
    parser.add_argument(
        "--workspace-id",
        type=str,
        metavar="UUID",
        help="Only backfill this workspace (default: every active workspace).",
    )


async def _run(ctx: ExecutionContext, workspace_id: uuid.UUID | None) -> int:
    """Ensure each active workspace has a default pipeline."""
    from sqlalchemy import select

    from app.db.session import AsyncSessionLocal
    from app.models.pipeline import Pipeline
    from app.models.workspace import Workspace
    from app.services.opportunities import ensure_default_pipeline

    ctx.announce("backfill default pipelines", workspace_id=str(workspace_id or "all"))
    ctx.confirm("backfill default pipelines")

    created = 0
    skipped = 0

    async with AsyncSessionLocal() as db:
        query = select(Workspace).where(Workspace.is_active.is_(True))
        if workspace_id is not None:
            query = query.where(Workspace.id == workspace_id)
        workspaces = (await db.execute(query.order_by(Workspace.created_at))).scalars().all()

        for workspace in workspaces:
            has_pipeline = (
                await db.execute(
                    select(Pipeline.id)
                    .where(
                        Pipeline.workspace_id == workspace.id,
                        Pipeline.is_active.is_(True),
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()

            if has_pipeline is not None:
                skipped += 1
                continue

            if ctx.dry_run:
                log_event(
                    logger,
                    logging.INFO,
                    "dry-run: would create default pipeline",
                    workspace_id=str(workspace.id),
                )
                created += 1
                continue

            pipeline = await ensure_default_pipeline(db, workspace.id)
            log_event(
                logger,
                logging.INFO,
                "default pipeline created",
                workspace_id=str(workspace.id),
                pipeline_id=str(pipeline.id),
            )
            created += 1

        if not ctx.dry_run:
            await db.commit()

        log_event(
            logger,
            logging.INFO,
            "backfill complete",
            provisioned=created,
            skipped=skipped,
            total=len(workspaces),
        )

    return EXIT_OK


def main() -> int:
    """Parse arguments and run the backfill."""
    ctx, args = bootstrap(
        description=__doc__ or "Backfill default pipelines.",
        writes=True,
        logger_name="backfill",
        configure=_configure,
    )
    workspace_id = uuid.UUID(args.workspace_id) if args.workspace_id else None
    return asyncio.run(_run(ctx, workspace_id))


if __name__ == "__main__":
    raise SystemExit(run(main))
