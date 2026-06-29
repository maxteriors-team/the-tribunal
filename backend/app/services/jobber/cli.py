"""``jobber-sync`` — pull Jobber records into a workspace.

Two subcommands:

``technicians`` keeps the workspace's technicians in step with Jobber ``users``
(repeatable). ``import`` runs the **one-time historical migration** of Jobber
clients (+ properties), jobs, and open invoices into the CRM so Jobber can be
retired — idempotent, so it is safe to dry-run then re-run for real.

Usage::

    # Technicians (token via env keeps it out of shell history):
    JOBBER_ACCESS_TOKEN=... jobber-sync technicians --workspace acme

    # One-time import — preview first (rolls back), then run for real:
    jobber-sync import --workspace acme --dry-run
    jobber-sync import --workspace acme --token "$TOKEN"

    # Import from a captured Jobber export instead of a live token (the same
    # importer code path; only the data source differs):
    jobber-sync import --workspace acme --from-file jobber_export.json --dry-run

The ``--from-file`` JSON has the shape
``{"clients": [...], "jobs": [...], "invoices": [...]}`` where each list holds
raw Jobber GraphQL nodes (same shape the live client yields). Exit code is
non-zero on configuration/API errors so it is CI/cron friendly.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal, engine
from app.models.workspace import Workspace
from app.services.jobber.client import JobberApiError, JobberClient
from app.services.jobber.importer import JobberImporter
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


async def _resolve_workspace(db: Any, slug: str) -> Workspace | None:
    result = await db.execute(select(Workspace).where(Workspace.slug == slug))
    workspace: Workspace | None = result.scalar_one_or_none()
    return workspace


def _load_feed_file(path: str) -> dict[str, list[dict[str, Any]]]:
    """Read a captured Jobber export ``{clients, jobs, invoices}`` from disk."""
    raw = json.loads(Path(path).read_text())
    if not isinstance(raw, dict):
        raise ValueError("--from-file must contain a JSON object")
    return {key: list(raw.get(key) or []) for key in ("clients", "jobs", "invoices")}


async def _run_import(args: argparse.Namespace) -> int:
    # Source the feed: either a captured export file or the live Jobber client.
    client: JobberClient | None = None
    if args.from_file:
        try:
            feed = _load_feed_file(args.from_file)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"error: could not read --from-file: {exc}", file=sys.stderr)
            return 2
        clients_src: Any = feed["clients"]
        jobs_src: Any = feed["jobs"]
        invoices_src: Any = feed["invoices"]
    else:
        token = _resolve_token(args.token)
        if not token:
            print(
                "error: no Jobber access token (set --token / JOBBER_ACCESS_TOKEN) "
                "or pass --from-file",
                file=sys.stderr,
            )
            return 2
        client = JobberClient(token, api_version=args.api_version)
        clients_src = client.iter_clients()
        jobs_src = client.iter_jobs()
        invoices_src = client.iter_invoices()

    async with AsyncSessionLocal() as db:
        workspace = await _resolve_workspace(db, args.workspace)
        if workspace is None:
            print(f"error: no workspace with slug {args.workspace!r}", file=sys.stderr)
            if client is not None:
                await client.aclose()
            return 2

        # Capture scalars before commit/rollback: a rollback expires the ORM
        # object, so reading ``workspace.slug`` afterwards would trigger a lazy
        # reload (a fresh connection checkout) outside the async greenlet.
        workspace_slug = workspace.slug
        importer = JobberImporter(db, workspace.id)
        try:
            # Order matters: contacts/locations first so jobs + invoices can
            # resolve their foreign keys against already-imported records.
            await importer.import_clients(clients_src)
            await importer.import_jobs(jobs_src)
            await importer.import_invoices(invoices_src)
        except JobberApiError as exc:
            await db.rollback()
            print(f"error: {exc}", file=sys.stderr)
            return 1
        finally:
            if client is not None:
                await client.aclose()

        if args.dry_run:
            await db.rollback()
        else:
            await db.commit()

        payload = {
            "workspace": workspace_slug,
            "dry_run": args.dry_run,
            "source": "file" if args.from_file else "jobber",
            **importer.result.as_dict(),
        }
        print(json.dumps(payload, indent=2))
        return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jobber-sync",
        description="Sync Jobber team members and import Jobber business records.",
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

    imp = sub.add_parser(
        "import",
        help="One-time import of Jobber clients, properties, jobs, and invoices.",
    )
    imp.add_argument("--workspace", required=True, help="Target workspace slug (e.g. 'acme').")
    imp.add_argument(
        "--token",
        default=None,
        help="Jobber OAuth2 access token (else JOBBER_ACCESS_TOKEN / settings).",
    )
    imp.add_argument(
        "--api-version",
        default=settings.jobber_api_version,
        help=f"Jobber GraphQL schema version (default: {settings.jobber_api_version}).",
    )
    imp.add_argument(
        "--from-file",
        default=None,
        metavar="PATH",
        help="Import from a captured Jobber export JSON instead of a live token.",
    )
    imp.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute changes and roll back without writing.",
    )
    imp.set_defaults(func=_run_import)
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
