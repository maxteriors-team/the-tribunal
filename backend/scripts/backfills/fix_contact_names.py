#!/usr/bin/env python3
"""Fix contact names by splitting first and last names.

This script finds contacts where both first and last names are in the
``first_name`` field and splits them properly into ``first_name`` and
``last_name`` fields.

Usage
-----

    # Dry-run (default — preview only, no writes):
    cd backend && uv run python scripts/backfills/fix_contact_names.py \
        --env local --dry-run --workspace-name "Marian Grout Real Estate"

    # Real run:
    cd backend && uv run python scripts/backfills/fix_contact_names.py \
        --env local --workspace-name "Marian Grout Real Estate"
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
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
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.models.contact import Contact  # noqa: E402
from app.models.workspace import Workspace  # noqa: E402
from scripts._harness import (  # noqa: E402
    EXIT_OK,
    ExecutionContext,
    ScriptAbortError,
    bootstrap,
    log_event,
    run,
)

logger = logging.getLogger("backfill")


def _add_workspace_arg(parser: argparse.ArgumentParser) -> None:
    """Add the --workspace-name argument to the parser."""
    parser.add_argument(
        "--workspace-name",
        type=str,
        default="Marian Grout Real Estate",
        help="Name of the workspace to fix (default: 'Marian Grout Real Estate')",
    )


def split_full_name(full_name: str) -> tuple[str, str | None]:
    """Split a full name into first and last name.

    Returns a ``(first_name, last_name)`` tuple.  ``last_name`` is ``None``
    when the input contains only a single token.
    """
    full_name = re.sub(r"\s+", " ", full_name.strip())
    if not full_name:
        return ("Unknown", None)
    parts = full_name.split(" ", 1)
    if len(parts) == 1:
        return (parts[0], None)
    return (parts[0], parts[1])


async def fix_workspace_contacts(
    session: AsyncSession,
    workspace_id: str,
    *,
    dry_run: bool = True,
) -> tuple[int, int]:
    """Fix contact names for a specific workspace.

    Parameters
    ----------
    session:
        Active async database session.
    workspace_id:
        UUID of the target workspace.
    dry_run:
        When ``True`` log what *would* change and skip the commit.

    Returns
    -------
    (total_contacts, fixed_contacts)
    """
    stmt = select(Contact).where(Contact.workspace_id == workspace_id)
    result = await session.execute(stmt)
    contacts = result.scalars().all()

    total_contacts = len(contacts)
    fixed_contacts = 0

    log_event(logger, logging.INFO, "scanning contacts", total=total_contacts)

    for contact in contacts:
        needs_fixing = " " in contact.first_name and not contact.last_name
        if not needs_fixing:
            continue

        old_first = contact.first_name
        old_last = contact.last_name or "(empty)"
        new_first, new_last = split_full_name(contact.first_name)

        log_event(
            logger,
            logging.INFO,
            "contact needs fix",
            contact_id=str(contact.id),
            old_first=old_first,
            old_last=old_last,
            new_first=new_first,
            new_last=new_last or "(empty)",
            dry_run=dry_run,
        )

        contact.first_name = new_first
        contact.last_name = new_last
        fixed_contacts += 1

    if not dry_run and fixed_contacts > 0:
        await session.commit()
        log_event(logger, logging.INFO, "committed name fixes", fixed=fixed_contacts)
    elif fixed_contacts > 0:
        log_event(
            logger,
            logging.INFO,
            "dry-run: would update contacts",
            fixed=fixed_contacts,
        )
    else:
        log_event(logger, logging.INFO, "no contacts need fixing")

    return total_contacts, fixed_contacts


async def _run(ctx: ExecutionContext, workspace_name: str) -> int:
    """Async core: locate workspace, announce intent, and apply fixes."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    ctx.announce("fix contact names", workspace=workspace_name)
    ctx.confirm(f"rewrite contact names in workspace '{workspace_name}'")

    engine = create_async_engine(settings.database_url, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with async_session() as session:
            stmt = select(Workspace).where(Workspace.name.ilike(f"%{workspace_name}%"))
            result = await session.execute(stmt)
            workspace = result.scalar_one_or_none()

            if workspace is None:
                log_event(
                    logger,
                    logging.ERROR,
                    "workspace not found",
                    workspace_name=workspace_name,
                )
                # List available workspaces to help the operator
                all_stmt = select(Workspace)
                all_result = await session.execute(all_stmt)
                for ws in all_result.scalars().all():
                    log_event(
                        logger,
                        logging.INFO,
                        "available workspace",
                        name=ws.name,
                        id=str(ws.id),
                    )
                raise ScriptAbortError(f"workspace '{workspace_name}' not found")

            log_event(
                logger,
                logging.INFO,
                "found workspace",
                name=workspace.name,
                id=str(workspace.id),
            )

            total, fixed = await fix_workspace_contacts(
                session,
                str(workspace.id),
                dry_run=ctx.dry_run,
            )

            log_event(
                logger,
                logging.INFO,
                "summary",
                total=total,
                fixed=fixed,
                unchanged=total - fixed,
                dry_run=ctx.dry_run,
            )
    finally:
        await engine.dispose()

    return EXIT_OK


def main() -> int:
    """Parse arguments and run the contact-name fix."""
    ctx, args = bootstrap(
        description=__doc__ or "Fix contact names by splitting first and last names.",
        writes=True,
        logger_name="backfill",
        configure=_add_workspace_arg,
    )
    return asyncio.run(_run(ctx, args.workspace_name))


if __name__ == "__main__":
    raise SystemExit(run(main))
