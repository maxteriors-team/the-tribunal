#!/usr/bin/env python3
"""Backfill knowledge_chunks for existing KnowledgeDocument rows.

Chunks + embeds every (optionally workspace-scoped) knowledge document into the
``knowledge_chunks`` table. Idempotent: documents whose content hash + chunks are
already current are skipped unless ``--force`` is given. Each document is ingested
in its own transaction, so a single embedding failure aborts only that document.

Usage
-----

    # Dry-run (default behaviour of --dry-run: count work, write nothing):
    cd backend && uv run python scripts/backfills/backfill_knowledge_chunks.py \
        --env local --dry-run

    # Real run, all documents:
    cd backend && uv run python scripts/backfills/backfill_knowledge_chunks.py --env local

    # Scope to one workspace, re-embedding even unchanged content:
    cd backend && uv run python scripts/backfills/backfill_knowledge_chunks.py \
        --env local --workspace-id <uuid> --force

Options
-------
    --workspace-id  Only backfill documents in this workspace.
    --force         Re-chunk + re-embed even when the content hash is unchanged.
    --limit         Process at most N documents (useful for incremental runs).
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

from app.db.session import AsyncSessionLocal  # noqa: E402
from app.models.knowledge_document import KnowledgeDocument  # noqa: E402
from app.services.knowledge.ingestion_service import (  # noqa: E402
    IngestionError,
    knowledge_ingestion_service,
)
from scripts._harness import (  # noqa: E402
    EXIT_FAILURE,
    EXIT_OK,
    ExecutionContext,
    bootstrap,
    log_event,
    run,
)

logger = logging.getLogger("backfill")


def _add_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("knowledge backfill")
    group.add_argument(
        "--workspace-id",
        type=str,
        metavar="UUID",
        help="Only backfill documents in this workspace.",
    )
    group.add_argument(
        "--force",
        action="store_true",
        help="Re-chunk + re-embed even when the content hash is unchanged.",
    )
    group.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N documents.",
    )


async def _run(
    ctx: ExecutionContext,
    *,
    workspace_id: uuid.UUID | None,
    force: bool,
    limit: int | None,
) -> int:
    ctx.announce(
        "backfill knowledge chunks",
        workspace_id=str(workspace_id) if workspace_id else "ALL",
        force=force,
        limit=limit if limit is not None else "none",
    )
    ctx.confirm("backfill knowledge_chunks (re-chunk + embed)")

    stmt = select(KnowledgeDocument).order_by(KnowledgeDocument.created_at.asc())
    if workspace_id is not None:
        stmt = stmt.where(KnowledgeDocument.workspace_id == workspace_id)
    if limit is not None:
        stmt = stmt.limit(limit)

    async with AsyncSessionLocal() as db:
        documents = list((await db.execute(stmt)).scalars().all())

        if ctx.dry_run:
            log_event(
                logger,
                logging.INFO,
                "dry-run: would backfill knowledge documents",
                documents=len(documents),
                force=force,
            )
            return EXIT_OK

        indexed = 0
        skipped = 0
        failed = 0
        total_chunks = 0
        for doc in documents:
            try:
                result = await knowledge_ingestion_service.ingest_document(db, doc, force=force)
            except IngestionError as exc:
                failed += 1
                log_event(
                    logger,
                    logging.ERROR,
                    "document ingest failed",
                    document_id=str(doc.id),
                    error=str(exc),
                )
                continue
            if result.skipped:
                skipped += 1
            else:
                indexed += 1
                total_chunks += result.chunk_count

    log_event(
        logger,
        logging.INFO,
        "backfill complete",
        documents=len(documents),
        indexed=indexed,
        skipped=skipped,
        failed=failed,
        chunks=total_chunks,
    )
    return EXIT_FAILURE if failed else EXIT_OK


def main() -> int:
    ctx, args = bootstrap(
        description=__doc__ or "Backfill knowledge_chunks for existing documents.",
        writes=True,
        logger_name="backfill",
        configure=_add_args,
    )

    workspace_id = uuid.UUID(args.workspace_id) if args.workspace_id else None
    return asyncio.run(_run(ctx, workspace_id=workspace_id, force=args.force, limit=args.limit))


if __name__ == "__main__":
    raise SystemExit(run(main))
