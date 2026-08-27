#!/usr/bin/env python3
"""Dry-run or apply one bounded Quo historical import for one CRM workspace.

The exact production command is in ``docs/quo-historical-backfill.md``. It combines
the backend service's encryption key with Postgres's public proxy URL without putting
either secret in argv or output. Do not invoke this through a plain backend
``railway run``: its private ``DATABASE_URL`` cannot resolve from the local process.

Review the aggregate counts, take the existing encrypted production backup, then rerun
with ``--apply``. Windows are UTC, half-open [since, until), and limited to 31 days;
split larger imports into adjacent windows.
"""

from __future__ import annotations

import argparse
import asyncio
import hmac
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db.session import AsyncSessionLocal, engine  # noqa: E402
from app.models.workspace import WorkspaceIntegration  # noqa: E402
from app.services.quo.backfill import (  # noqa: E402
    QuoBackfillCounts,
    QuoBackfillError,
    QuoHistoricalBackfill,
    validate_backfill_window,
)
from app.services.quo.client import QuoApiError, QuoClient  # noqa: E402
from app.utils.phone import normalize_phone_safe  # noqa: E402


class QuoBackfillConfigError(RuntimeError):
    """The selected workspace lacks a usable, tenant-bound Quo integration."""


def _parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise argparse.ArgumentTypeError("expected an ISO 8601 timestamp with UTC offset") from None
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp must include a UTC offset")
    return parsed.astimezone(UTC)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import a bounded Quo history window; dry-run rollback is the default."
    )
    parser.add_argument("--workspace-id", type=uuid.UUID, required=True)
    parser.add_argument("--since", type=_parse_datetime, required=True)
    parser.add_argument("--until", type=_parse_datetime, required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="commit idempotent checkpoints; omitted means process and roll everything back",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    validate_backfill_window(args.since, args.until)
    mode = "apply" if args.apply else "dry-run"
    print(
        f"mode={mode} workspace={args.workspace_id} "
        f"since={args.since.isoformat()} until={args.until.isoformat()}"
    )

    try:
        async with AsyncSessionLocal() as db:
            integration = await db.scalar(
                select(WorkspaceIntegration).where(
                    WorkspaceIntegration.workspace_id == args.workspace_id,
                    WorkspaceIntegration.integration_type == "quo",
                    WorkspaceIntegration.is_active.is_(True),
                )
            )
            if integration is None:
                raise QuoBackfillConfigError("workspace has no active encrypted Quo integration")
            credentials = integration.safe_credentials()
            api_key, organization_id, phone_number_id, phone_number = _integration_credentials(
                credentials
)

            async with QuoClient(api_key) as client:
                remote_organization_id = await client.validate_api_key()
                if remote_organization_id is None or not hmac.compare_digest(
                    remote_organization_id, organization_id
):
                    raise QuoBackfillConfigError(
                        "stored Quo integration does not match the authenticated tenant"
)
                counts = await QuoHistoricalBackfill(
                    db,
                    workspace_id=args.workspace_id,
                    organization_id=organization_id,
                    phone_number_id=phone_number_id,
                    phone_number=phone_number,
                    client=client,
                    since=args.since,
                    until=args.until,
                    apply=args.apply,
                ).run()
    finally:
        await engine.dispose()

    _print_counts(counts, applied=args.apply)
    return 2 if _error_count(counts) else 0


def _integration_credentials(credentials: object) -> tuple[str, str, str, str]:
    if not isinstance(credentials, dict):
        raise QuoBackfillConfigError("workspace Quo credentials cannot be decrypted")
    api_key = credentials.get("api_key")
    organization_id = credentials.get("organization_id")
    phone_number_id = credentials.get("phone_number_id")
    phone_number = credentials.get("phone_number")
    normalized_phone = normalize_phone_safe(phone_number) if isinstance(phone_number, str) else None
    if not isinstance(api_key, str) or not api_key.strip():
        raise QuoBackfillConfigError("workspace Quo API credential is missing")
    if not isinstance(organization_id, str) or not organization_id.startswith("OR"):
        raise QuoBackfillConfigError("workspace Quo tenant binding is missing")
    if not isinstance(phone_number_id, str) or not phone_number_id.strip():
        raise QuoBackfillConfigError("workspace Quo sender selection is missing")
    if normalized_phone is None or normalized_phone != phone_number:
        raise QuoBackfillConfigError("workspace Quo sender number is invalid")
    return api_key, organization_id, phone_number_id, normalized_phone


def _print_counts(counts: QuoBackfillCounts, *, applied: bool) -> None:
    for name in ("contacts", "conversations", "texts", "calls"):
        resource = getattr(counts, name)
        print(
            f"{name}: seen={resource.seen} eligible={resource.eligible} "
            f"synced={resource.synced} skipped={resource.skipped} errors={resource.errors}"
        )
    print(f"api_errors={counts.api_errors}")
    print(f"result={'committed' if applied else 'rolled-back'}")


def _error_count(counts: QuoBackfillCounts) -> int:
    resources = (counts.contacts, counts.conversations, counts.texts, counts.calls)
    return counts.api_errors + sum(resource.errors for resource in resources)


def main() -> None:
    args = _parser().parse_args()
    try:
        exit_code = asyncio.run(_run(args))
    except (QuoBackfillConfigError, QuoBackfillError) as exc:
        print(f"aborted=config error={exc}", file=sys.stderr)
        raise SystemExit(1) from None
    except QuoApiError as exc:
        status = exc.status_code if exc.status_code is not None else "transport"
        print(f"aborted=quo-api status={status}", file=sys.stderr)
        raise SystemExit(1) from None
    except Exception as exc:  # Keep SQL/provider parameters out of operational output.
        print(f"aborted=internal type={type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
