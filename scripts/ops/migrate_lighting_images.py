#!/usr/bin/env python3
"""Move base64 images out of ``lighting_projects.document`` into the private bucket.

Embedding data URLs in this JSONB column put ~82 MB of image bytes into a 164 MB
database on a 500 MB volume. Postgres compression returns nothing on base64
PNG/JPEG, so the bytes have to leave the database. This rewrites each document's
images as ``lighting-image:{object_key}`` references pointing at objects written
to the same bucket MMS media uses.

**The read path must already be deployed.** A row holding a key is a hard 500 on
any backend release whose schema still rejects non-``data:`` image values, and
the installation plan silently 404s. Verify ``/version`` first. Once keys are
written the deploy is forward-only: roll back by restoring the pre-``--apply``
encrypted dump, never by redeploying older code.

Dry run is the default and writes nothing. ``--apply`` commits **per row**, so an
interrupted run leaves every completed row consistent. Use ``--limit`` to work in
small batches and ``VACUUM`` between them — the rewrite writes a new row version
before the old one can be reclaimed, so a single pass over every row transiently
grows the table, which a 68%-full volume cannot absorb.

    cd backend && railway run --service the-tribunal-api -- \\
        uv run python ../scripts/ops/migrate_lighting_images.py --limit 5
    ... review, back up, then rerun with --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

from sqlalchemy import select

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings  # noqa: E402
from app.db.session import AsyncSessionLocal, engine  # noqa: E402
from app.models.lighting_project import LightingProject  # noqa: E402
from app.schemas.lighting_project import LandscapeDraftDocument  # noqa: E402
from app.services.lighting_projects.images import (  # noqa: E402
    LightingImageError,
    document_for_storage,
    store_document_images,
)


class MigrationAbort(RuntimeError):
    """The migration cannot run safely against this environment."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Move lighting-project images into private storage; dry-run is the default."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the rewritten documents; omitted means report only",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="maximum rows to process in this batch (default 5; vacuum between batches)",
    )
    parser.add_argument(
        "--project-id",
        type=uuid.UUID,
        default=None,
        help="migrate exactly one project, for a first cautious run",
    )
    return parser


def _document_bytes(document: object) -> int:
    return len(json.dumps(document, separators=(",", ":")))


def _inline_image_bytes(document: object) -> int:
    """Roughly how much of this document is base64 image payload."""
    raw = json.dumps(document, separators=(",", ":"))
    total = 0
    cursor = raw.find("data:image")
    while cursor != -1:
        end = raw.find('"', cursor)
        total += (end if end != -1 else len(raw)) - cursor
        cursor = raw.find("data:image", cursor + 1)
    return total


async def _run(args: argparse.Namespace) -> int:
    if args.limit <= 0:
        raise MigrationAbort("--limit must be positive")
    if not settings.mms_storage_enabled:
        raise MigrationAbort("object storage is not configured for this environment")

    mode = "apply" if args.apply else "dry-run"
    print(f"mode={mode} limit={args.limit} bucket={settings.mms_storage_bucket}")

    migrated = failed = 0
    freed_bytes = 0
    try:
        async with AsyncSessionLocal() as db:
            statement = select(LightingProject).order_by(LightingProject.updated_at)
            if args.project_id is not None:
                statement = statement.where(LightingProject.id == args.project_id)
            candidates = [
                project
                for project in (await db.scalars(statement)).all()
                if "data:image" in json.dumps(project.document, separators=(",", ":"))
            ][: args.limit]

            print(f"candidates={len(candidates)}")
            for project in candidates:
                before = _document_bytes(project.document)
                inline = _inline_image_bytes(project.document)
                label = (
                    f"project={project.id} workspace={project.workspace_id} "
                    f"bytes={before} inline_image_bytes={inline}"
                )
                if not args.apply:
                    print(f"{label} action=would-migrate")
                    migrated += 1
                    freed_bytes += inline
                    continue

                try:
                    document = LandscapeDraftDocument.model_validate(project.document)
                    stored = await store_document_images(
                        document,
                        workspace_id=project.workspace_id,
                        project_id=project.id,
                    )
                except (ValueError, LightingImageError) as exc:
                    # One unparseable or unstorable row must not stop the batch.
                    print(f"{label} action=failed reason={type(exc).__name__}", file=sys.stderr)
                    await db.rollback()
                    failed += 1
                    continue

                rewritten = document_for_storage(stored)
                if "data:image" in json.dumps(rewritten, separators=(",", ":")):
                    print(f"{label} action=failed reason=data-url-remained", file=sys.stderr)
                    await db.rollback()
                    failed += 1
                    continue

                project.document = rewritten
                # Commit per row so an interrupted run leaves finished rows done.
                await db.commit()
                after = _document_bytes(rewritten)
                freed_bytes += before - after
                migrated += 1
                print(f"{label} after_bytes={after} action=migrated")
    finally:
        await engine.dispose()

    print(f"migrated={migrated} failed={failed} freed_bytes={freed_bytes}")
    print(f"result={'committed' if args.apply else 'no-writes'}")
    return 2 if failed else 0


def main() -> None:
    args = _parser().parse_args()
    try:
        exit_code = asyncio.run(_run(args))
    except MigrationAbort as exc:
        print(f"aborted=config error={exc}", file=sys.stderr)
        raise SystemExit(1) from None
    except Exception as exc:  # Keep SQL and credentials out of operational output.
        print(f"aborted=internal type={type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
