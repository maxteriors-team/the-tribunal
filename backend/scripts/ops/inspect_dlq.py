#!/usr/bin/env python3
"""Inspect and replay rows in the ``failed_jobs`` dead-letter queue.

Subcommands:

    list                 Show recent DLQ rows, newest first.
    show <id>            Print one row in full (payload + error).
    replay <id>          Mark a row as ``retried`` (records intent — the
                         actual replay is the operator's responsibility,
                         since each worker owns its own retry mechanics).
    abandon <id>         Mark a row as ``abandoned`` so it stops showing
                         up in ``list --status pending`` triage views.
    purge --status ...   Delete rows in a terminal status (use sparingly).

Examples:

    uv run python scripts/ops/inspect_dlq.py list --env local
    uv run python scripts/ops/inspect_dlq.py list --env local --worker nudge_worker --status pending
    uv run python scripts/ops/inspect_dlq.py show 7a4f...c1 --env local
    uv run python scripts/ops/inspect_dlq.py replay 7a4f...c1 --env local
    uv run python scripts/ops/inspect_dlq.py abandon 7a4f...c1 --env local
    uv run python scripts/ops/inspect_dlq.py purge --status retried --env local --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

# --- harness bootstrap: locate ``backend/`` so ``app`` + ``scripts`` import ----
_BACKEND_DIR = next(
    p / "backend"
    for p in Path(__file__).resolve().parents
    if (p / "backend" / "scripts" / "_harness.py").is_file()
)
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from sqlalchemy import delete, desc, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.db.session import AsyncSessionLocal  # noqa: E402
from app.models.failed_job import (  # noqa: E402
    FAILED_JOB_STATUS_ABANDONED,
    FAILED_JOB_STATUS_PENDING,
    FAILED_JOB_STATUS_RETRIED,
    FAILED_JOB_STATUSES,
    FailedJob,
)
from scripts._harness import (  # noqa: E402
    EXIT_FAILURE,
    EXIT_OK,
    EXIT_USAGE,
    ExecutionContext,
    add_standard_arguments,
    from_args,
    log_event,
    run,
)

logger = logging.getLogger("dlq")


def _fmt_dt(value: datetime | None) -> str:
    if value is None:
        return "-"
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%SZ")


def _short_id(row_id: uuid.UUID) -> str:
    return str(row_id).split("-", 1)[0]


async def _load(session: AsyncSession, row_id: str) -> FailedJob | None:
    try:
        parsed = uuid.UUID(row_id)
    except ValueError:
        log_event(logger, logging.ERROR, "invalid UUID", row_id=row_id)
        return None
    return await session.get(FailedJob, parsed)


async def cmd_list(args: argparse.Namespace, ctx: ExecutionContext) -> int:
    log_event(logger, logging.INFO, "listing DLQ rows", env=ctx.env.value)
    async with AsyncSessionLocal() as session:
        query = select(FailedJob).order_by(desc(FailedJob.last_failed_at))
        if args.status:
            query = query.where(FailedJob.status == args.status)
        if args.worker:
            query = query.where(FailedJob.worker_name == args.worker)
        query = query.limit(args.limit)
        rows = (await session.execute(query)).scalars().all()

    if not rows:
        print("No DLQ rows match the filters.")
        return EXIT_OK

    if args.json:
        print(
            json.dumps(
                [
                    {
                        "id": str(r.id),
                        "worker_name": r.worker_name,
                        "item_key": r.item_key,
                        "status": r.status,
                        "attempts": r.attempts,
                        "first_failed_at": _fmt_dt(r.first_failed_at),
                        "last_failed_at": _fmt_dt(r.last_failed_at),
                        "error": r.error,
                    }
                    for r in rows
                ],
                indent=2,
            )
        )
        return EXIT_OK

    header = (
        f"{'id':<10} {'worker':<28} {'item_key':<28} "
        f"{'status':<10} {'att':>4} {'last_failed_at':<20}  error"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        error_snippet = (row.error or "").splitlines()[0][:80] if row.error else ""
        print(
            f"{_short_id(row.id):<10} "
            f"{row.worker_name[:28]:<28} "
            f"{row.item_key[:28]:<28} "
            f"{row.status:<10} "
            f"{row.attempts:>4} "
            f"{_fmt_dt(row.last_failed_at):<20}  "
            f"{error_snippet}"
        )
    return EXIT_OK


async def cmd_show(args: argparse.Namespace, ctx: ExecutionContext) -> int:
    log_event(logger, logging.INFO, "fetching DLQ row", env=ctx.env.value, id=args.id)
    async with AsyncSessionLocal() as session:
        row = await _load(session, args.id)
        if row is None:
            log_event(logger, logging.ERROR, "DLQ row not found", id=args.id)
            return EXIT_FAILURE
        out = {
            "id": str(row.id),
            "worker_name": row.worker_name,
            "item_key": row.item_key,
            "status": row.status,
            "attempts": row.attempts,
            "first_failed_at": _fmt_dt(row.first_failed_at),
            "last_failed_at": _fmt_dt(row.last_failed_at),
            "error": row.error,
            "payload": row.payload,
        }
        print(json.dumps(out, indent=2, default=str))
    return EXIT_OK


async def _set_status(row_id: str, new_status: str, ctx: ExecutionContext) -> int:
    ctx.confirm(f"mark DLQ row {row_id[:8]}… as {new_status}")

    async with AsyncSessionLocal() as session:
        row = await _load(session, row_id)
        if row is None:
            log_event(logger, logging.ERROR, "DLQ row not found", id=row_id)
            return EXIT_FAILURE

        if ctx.dry_run:
            log_event(
                logger,
                logging.INFO,
                "dry-run: would update status",
                id=str(row.id),
                current_status=row.status,
                new_status=new_status,
            )
            return EXIT_OK

        row.status = new_status
        await session.commit()
        log_event(
            logger,
            logging.INFO,
            "updated status",
            id=_short_id(row.id),
            new_status=new_status,
        )
    return EXIT_OK


async def cmd_replay(args: argparse.Namespace, ctx: ExecutionContext) -> int:
    # We don't actually re-invoke the worker function here — args/kwargs in
    # the payload may include live sessions/services that can't be revived
    # cross-process. Marking the row as "retried" records the operator's
    # intent; the worker that owns the item is responsible for re-enqueueing.
    ctx.announce("replay DLQ row", id=args.id)
    return await _set_status(args.id, FAILED_JOB_STATUS_RETRIED, ctx)


async def cmd_abandon(args: argparse.Namespace, ctx: ExecutionContext) -> int:
    ctx.announce("abandon DLQ row", id=args.id)
    return await _set_status(args.id, FAILED_JOB_STATUS_ABANDONED, ctx)


async def cmd_purge(args: argparse.Namespace, ctx: ExecutionContext) -> int:
    if args.status == FAILED_JOB_STATUS_PENDING and not args.force:
        log_event(
            logger,
            logging.ERROR,
            "refusing to purge pending rows without --force",
            status=args.status,
        )
        return EXIT_USAGE

    ctx.announce("purge DLQ rows", status=args.status)
    ctx.confirm(f"purge all DLQ rows with status={args.status}")

    if ctx.dry_run:
        async with AsyncSessionLocal() as session:
            count_rows = (
                (await session.execute(select(FailedJob).where(FailedJob.status == args.status)))
                .scalars()
                .all()
            )
            log_event(
                logger,
                logging.INFO,
                "dry-run: would delete rows",
                status=args.status,
                count=len(count_rows),
            )
        return EXIT_OK

    async with AsyncSessionLocal() as session:
        result = await session.execute(delete(FailedJob).where(FailedJob.status == args.status))
        await session.commit()
        deleted = int(getattr(result, "rowcount", 0) or 0)
    log_event(logger, logging.INFO, "purged DLQ rows", status=args.status, deleted=deleted)
    return EXIT_OK


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect and replay rows in the failed_jobs DLQ.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="List recent DLQ rows.")
    p_list.add_argument("--status", choices=FAILED_JOB_STATUSES, default=None)
    p_list.add_argument("--worker", help="Filter by worker_name.")
    p_list.add_argument("--limit", type=int, default=50)
    p_list.add_argument("--json", action="store_true", help="Emit JSON.")
    add_standard_arguments(p_list, writes=False, default_env=None)
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="Show one DLQ row in full.")
    p_show.add_argument("id")
    add_standard_arguments(p_show, writes=False, default_env=None)
    p_show.set_defaults(func=cmd_show)

    p_replay = sub.add_parser("replay", help="Mark a row as retried (operator records intent).")
    p_replay.add_argument("id")
    add_standard_arguments(p_replay, writes=True, default_env=None)
    p_replay.set_defaults(func=cmd_replay)

    p_abandon = sub.add_parser("abandon", help="Mark a row as abandoned.")
    p_abandon.add_argument("id")
    add_standard_arguments(p_abandon, writes=True, default_env=None)
    p_abandon.set_defaults(func=cmd_abandon)

    p_purge = sub.add_parser("purge", help="Delete rows in a given terminal status.")
    p_purge.add_argument("--status", choices=FAILED_JOB_STATUSES, required=True)
    p_purge.add_argument(
        "--force",
        action="store_true",
        help="Required to purge status=pending.",
    )
    add_standard_arguments(p_purge, writes=True, default_env=None)
    p_purge.set_defaults(func=cmd_purge)

    return parser


def main() -> int:
    """Parse arguments and dispatch to the appropriate subcommand."""
    parser = _build_parser()
    args = parser.parse_args()
    ctx = from_args(args, logger_name="dlq")
    return int(asyncio.run(args.func(args, ctx)))


if __name__ == "__main__":
    raise SystemExit(run(main))
