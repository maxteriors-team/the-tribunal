"""``jobber-sync`` — pull Jobber team members into a workspace's technicians.

Usage::

    # Token via env (preferred — keeps it out of shell history):
    JOBBER_ACCESS_TOKEN=... jobber-sync technicians --workspace acme

    # Drop newly-imported techs into a crew, deactivate ones gone from Jobber:
    jobber-sync technicians --workspace acme \\
        --token "$TOKEN" --default-crew "Field" --deactivate-missing

    # Preview without writing (rolls back the transaction):
    jobber-sync technicians --workspace acme --dry-run

Jobber has no "crew" concept, so this syncs technicians only; ``--default-crew``
ensures a *local* crew exists for new technicians. Exit code is non-zero on
configuration/API errors so it is CI/cron friendly.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from collections.abc import Awaitable, Callable

import structlog
from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal, engine
from app.models.workspace import Workspace
from app.services.jobber.client import JobberApiError, JobberClient
from app.services.jobber.sync import JobberTechnicianSync

logger = structlog.get_logger()


def _resolve_token(arg_token: str | None) -> str:
    """Token precedence: ``--token`` > ``JOBBER_ACCESS_TOKEN`` > settings."""
    return arg_token or os.environ.get("JOBBER_ACCESS_TOKEN") or settings.jobber_access_token


async def _run_technicians(args: argparse.Namespace) -> int:
    token = _resolve_token(args.token)
    if not token:
        print(
            "error: no Jobber access token (set --token or JOBBER_ACCESS_TOKEN)",
            file=sys.stderr,
        )
        return 2

    async with AsyncSessionLocal() as db:
        workspace = (
            await db.execute(select(Workspace).where(Workspace.slug == args.workspace))
        ).scalar_one_or_none()
        if workspace is None:
            print(f"error: no workspace with slug {args.workspace!r}", file=sys.stderr)
            return 2

        sync = JobberTechnicianSync(db, workspace.id)

        default_crew_id: uuid.UUID | None = None
        if args.default_crew:
            crew = await sync.ensure_crew(args.default_crew)
            default_crew_id = crew.id

        client = JobberClient(token, api_version=args.api_version)
        try:
            result = await sync.sync(
                client.iter_users(),
                default_crew_id=default_crew_id,
                deactivate_missing=args.deactivate_missing,
            )
        except JobberApiError as exc:
            await db.rollback()
            print(f"error: {exc}", file=sys.stderr)
            return 1
        finally:
            await client.aclose()

        if args.dry_run:
            await db.rollback()
        else:
            await db.commit()

        payload = {
            "workspace": workspace.slug,
            "dry_run": args.dry_run,
            **result.as_dict(),
        }
        print(json.dumps(payload, indent=2))
        # Mapping skips are surfaced but don't fail the run; API/config errors do.
        return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jobber-sync",
        description="Sync Jobber team members into CRM technicians.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    techs = sub.add_parser(
        "technicians",
        help="Pull Jobber users into the workspace's technicians.",
    )
    techs.add_argument(
        "--workspace",
        required=True,
        help="Target workspace slug (e.g. 'acme').",
    )
    techs.add_argument(
        "--token",
        default=None,
        help="Jobber OAuth2 access token (else JOBBER_ACCESS_TOKEN / settings).",
    )
    techs.add_argument(
        "--api-version",
        default=settings.jobber_api_version,
        help=f"Jobber GraphQL schema version (default: {settings.jobber_api_version}).",
    )
    techs.add_argument(
        "--default-crew",
        default=None,
        metavar="NAME",
        help="Ensure this local crew exists and assign newly-created techs to it.",
    )
    techs.add_argument(
        "--deactivate-missing",
        action="store_true",
        help="Mark Jobber-sourced techs no longer in Jobber as inactive.",
    )
    techs.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute changes and roll back without writing.",
    )
    techs.set_defaults(func=_run_technicians)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    handler: Callable[[argparse.Namespace], Awaitable[int]] = args.func

    async def _runner() -> int:
        try:
            return await handler(args)
        finally:
            await engine.dispose()

    return asyncio.run(_runner())


if __name__ == "__main__":
    raise SystemExit(main())
