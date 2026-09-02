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

from sqlalchemy import Text, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

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


class MigrationAbortError(RuntimeError):
    """The migration cannot run safely against this environment."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Move lighting-project images into private storage; dry-run is the default."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="report candidates without uploads or database writes (default)",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="upload image bytes and persist rewritten project documents",
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


async def _candidate_projects(db: AsyncSession, args: argparse.Namespace) -> list[LightingProject]:
    statement = select(LightingProject).order_by(LightingProject.updated_at)
    if args.project_id is not None:
        statement = statement.where(LightingProject.id == args.project_id)
    else:
        statement = statement.where(
            cast(LightingProject.document, Text).contains("data:image")
        ).limit(args.limit)
    return [
        project
        for project in (await db.scalars(statement)).all()
        if "data:image" in json.dumps(project.document, separators=(",", ":"))
    ][: args.limit]


async def _stored_document(project: LightingProject) -> dict[str, object]:
    document = LandscapeDraftDocument.model_validate(project.document)
    stored = await store_document_images(
        document,
        workspace_id=project.workspace_id,
        project_id=project.id,
    )
    rewritten = document_for_storage(stored)
    if "data:image" in json.dumps(rewritten, separators=(",", ":")):
        raise LightingImageError("data URL remained after migration")
    return rewritten


def _validate_environment(args: argparse.Namespace) -> None:
    if args.limit <= 0:
        raise MigrationAbortError("--limit must be positive")
    if not settings.mms_storage_enabled:
        raise MigrationAbortError("object storage is not configured for this environment")


async def _run(args: argparse.Namespace) -> int:
    _validate_environment(args)
    mode = "apply" if args.apply else "dry-run"
    print(f"mode={mode} limit={args.limit} bucket={settings.mms_storage_bucket}")

    migrated = failed = 0
    freed_bytes = 0
    try:
        async with AsyncSessionLocal() as db:
            candidates = await _candidate_projects(db, args)
            print(f"candidates={len(candidates)}")
            candidate_ids = [project.id for project in candidates]
            dry_run_projects = {project.id: project for project in candidates}
            for candidate_id in candidate_ids:
                project = dry_run_projects[candidate_id]
                if args.apply:
                    # Re-read under a row lock before network I/O and commit. This
                    # prevents a concurrent autosave from being overwritten by a
                    # document selected before the user finished editing it.
                    project = await db.scalar(
                        select(LightingProject)
                        .where(LightingProject.id == candidate_id)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                    if project is None:
                        await db.rollback()
                        print(f"project={candidate_id} action=skipped reason=not-found")
                        continue
                    if "data:image" not in json.dumps(project.document, separators=(",", ":")):
                        await db.rollback()
                        print(f"project={project.id} action=skipped reason=already-migrated")
                        continue

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
                    rewritten = await _stored_document(project)
                except (ValueError, LightingImageError) as exc:
                    # One unparseable or unstorable row must not stop the batch.
                    print(f"{label} action=failed reason={type(exc).__name__}", file=sys.stderr)
                    await db.rollback()
                    failed += 1
                    continue

                project.document = rewritten
                project.version += 1
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
    except MigrationAbortError as exc:
        print(f"aborted=config error={exc}", file=sys.stderr)
        raise SystemExit(1) from None
    except Exception as exc:  # Keep SQL and credentials out of operational output.
        print(f"aborted=internal type={type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
