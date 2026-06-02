#!/usr/bin/env python3
"""Backfill PromptVersionStats for a date range.

Usage
-----

    uv run python scripts/backfills/backfill_prompt_stats.py --env local --days 30
    uv run python scripts/backfills/backfill_prompt_stats.py \
        --env local --start 2025-01-01 --end 2025-01-31
    uv run python scripts/backfills/backfill_prompt_stats.py --env local --dry-run --days 7

Options
-------
    --days      Number of days to backfill (default: 30; ignored when --start is given)
    --start     Start date in YYYY-MM-DD format
    --end       End date in YYYY-MM-DD format (default: yesterday)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

# --- harness bootstrap: locate ``backend/`` so ``app`` + ``scripts`` import ----
_BACKEND_DIR = next(
    p / "backend"
    for p in Path(__file__).resolve().parents
    if (p / "backend" / "scripts" / "_harness.py").is_file()
)
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.workers.prompt_stats_worker import PromptStatsWorker  # noqa: E402
from scripts._harness import (  # noqa: E402
    EXIT_OK,
    ExecutionContext,
    bootstrap,
    log_event,
    run,
)

logger = logging.getLogger("backfill")


def _add_dates(parser: argparse.ArgumentParser) -> None:
    """Add date-range arguments to the argument parser."""
    group = parser.add_argument_group("date range")
    group.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of days to backfill (default: 30; ignored when --start is given)",
    )
    group.add_argument(
        "--start",
        type=str,
        metavar="YYYY-MM-DD",
        help="Start date in YYYY-MM-DD format",
    )
    group.add_argument(
        "--end",
        type=str,
        metavar="YYYY-MM-DD",
        help="End date in YYYY-MM-DD format (default: yesterday)",
    )


async def _run(ctx: ExecutionContext, start_date: date, end_date: date) -> int:
    """Async core: announce, confirm, then run (or skip) the backfill."""
    ctx.announce("backfill prompt stats", start=str(start_date), end=str(end_date))
    ctx.confirm("backfill PromptVersionStats")

    if ctx.dry_run:
        log_event(
            logger,
            logging.INFO,
            "dry-run: would backfill prompt stats",
            start=str(start_date),
            end=str(end_date),
            days=(end_date - start_date).days + 1,
        )
        return EXIT_OK

    worker = PromptStatsWorker()
    total = await worker.backfill(start_date, end_date)
    log_event(
        logger,
        logging.INFO,
        "backfill complete",
        processed=total,
        start=str(start_date),
        end=str(end_date),
    )
    return EXIT_OK


def main() -> int:
    """Parse arguments, resolve the date range, and run the backfill."""
    ctx, args = bootstrap(
        description=__doc__ or "Backfill PromptVersionStats for a date range.",
        writes=True,
        logger_name="backfill",
        configure=_add_dates,
    )

    # Resolve date range
    if args.start:
        start_date = date.fromisoformat(args.start)
    else:
        start_date = date.today() - timedelta(days=args.days)

    end_date = date.fromisoformat(args.end) if args.end else date.today() - timedelta(days=1)

    return asyncio.run(_run(ctx, start_date, end_date))


if __name__ == "__main__":
    raise SystemExit(run(main))
