#!/usr/bin/env python3
"""Seed the operator product-help corpus into workspaces.

Reads the markdown under ``backend/docs/help`` and upserts it as workspace-level
``KnowledgeDocument`` rows (``agent_id IS NULL``, ``doc_type='product_help'``),
then chunks + embeds them so the assistant's ``search_help`` tool can retrieve
them. Without this the assistant answers product how-to questions from model
priors, which its own prompt forbids.

Idempotent: documents are matched on slug, and unchanged content is not
re-embedded unless ``--force`` is passed. Each workspace is synced in its own
transaction, so one embedding failure cannot half-index another workspace.

Usage
-----

    # Dry-run (count the work, write nothing):
    cd backend && uv run python scripts/seeds/seed_product_help.py --env local --dry-run

    # Real run, every workspace:
    cd backend && uv run python scripts/seeds/seed_product_help.py --env local

    # One workspace, re-embedding even unchanged content:
    cd backend && uv run python scripts/seeds/seed_product_help.py \
        --env local --workspace-id <uuid> --force

Options
-------
    --workspace-id  Only seed this workspace (default: every active workspace).
    --force         Re-chunk + re-embed even when the content hash is unchanged.
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

from sqlalchemy import select  # noqa: E402

from app.db.session import AsyncSessionLocal, transaction_boundary  # noqa: E402
from app.models.workspace import Workspace  # noqa: E402
from app.services.knowledge.ingestion_service import IngestionError  # noqa: E402
from app.services.knowledge.product_help import (  # noqa: E402
    ProductHelpError,
    load_help_documents,
    sync_product_help,
)
from scripts._harness import (  # noqa: E402
    EXIT_FAILURE,
    EXIT_OK,
    ExecutionContext,
    bootstrap,
    log_event,
    run,
)

logger = logging.getLogger("seed")


def _add_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("product help seed")
    group.add_argument(
        "--workspace-id",
        type=str,
        metavar="UUID",
        help="Only seed this workspace (default: every active workspace).",
    )
    group.add_argument(
        "--force",
        action="store_true",
        help="Re-chunk + re-embed even when the content hash is unchanged.",
    )


async def _run(
    ctx: ExecutionContext,
    *,
    workspace_id: uuid.UUID | None,
    force: bool,
) -> int:
    documents = load_help_documents()
    ctx.announce(
        "seed product help corpus",
        workspace_id=str(workspace_id) if workspace_id else "ALL",
        documents=len(documents),
        force=force,
    )
    ctx.confirm("seed product help documents (chunk + embed)")

    stmt = select(Workspace.id).where(Workspace.is_active.is_(True))
    if workspace_id is not None:
        stmt = stmt.where(Workspace.id == workspace_id)

    async with AsyncSessionLocal() as db:
        workspace_ids = list((await db.execute(stmt)).scalars().all())

        if ctx.dry_run:
            log_event(
                logger,
                logging.INFO,
                "dry-run: would seed product help",
                workspaces=len(workspace_ids),
                documents=len(documents),
                force=force,
            )
            return EXIT_OK

        seeded = 0
        failed = 0
        for target in workspace_ids:
            try:
                async with transaction_boundary(db):
                    result = await sync_product_help(
                        db,
                        target,
                        documents=documents,
                        force=force,
                    )
            except IngestionError as exc:
                failed += 1
                log_event(
                    logger,
                    logging.ERROR,
                    "workspace help sync failed",
                    workspace_id=str(target),
                    error=str(exc),
                )
                continue
            seeded += 1
            log_event(
                logger,
                logging.INFO,
                "workspace help synced",
                workspace_id=str(target),
                created=result.created,
                updated=result.updated,
                indexed=result.indexed,
                skipped=result.skipped,
            )

    log_event(
        logger,
        logging.INFO,
        "seed complete",
        workspaces=len(workspace_ids),
        seeded=seeded,
        failed=failed,
        documents=len(documents),
    )
    return EXIT_FAILURE if failed else EXIT_OK


def main() -> int:
    ctx, args = bootstrap(
        description=__doc__ or "Seed the product-help corpus into workspaces.",
        writes=True,
        logger_name="seed",
        configure=_add_args,
    )

    workspace_id = uuid.UUID(args.workspace_id) if args.workspace_id else None
    try:
        return asyncio.run(_run(ctx, workspace_id=workspace_id, force=args.force))
    except ProductHelpError as exc:
        log_event(logger, logging.ERROR, "help corpus unavailable", error=str(exc))
        return EXIT_FAILURE


if __name__ == "__main__":
    raise SystemExit(run(main))
