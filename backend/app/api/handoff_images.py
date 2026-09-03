"""Shared validation and concurrency boundaries for private handoff images."""

import uuid

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.contact_attachments import sanitize_filename
from app.models.field_service import Job
from app.models.job_handoff_image import JobHandoffImage
from app.models.quote import Quote
from app.models.quote_handoff_image import (
    MAX_HANDOFF_IMAGE_BYTES,
    QuoteHandoffImage,
)


def detect_handoff_image_type(data: bytes) -> str | None:
    """Return the canonical MIME type for supported image signatures."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


async def read_handoff_image_upload(file: UploadFile) -> tuple[str, str, bytes]:
    """Read and validate one upload without trusting client metadata."""
    data = await file.read(MAX_HANDOFF_IMAGE_BYTES + 1)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Uploaded image is empty",
        )
    if len(data) > MAX_HANDOFF_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Image exceeds the {MAX_HANDOFF_IMAGE_BYTES // (1024 * 1024)} MB limit",
        )

    detected_type = detect_handoff_image_type(data)
    if detected_type is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Use a JPEG, PNG, or WebP image",
        )
    if (file.content_type or "").lower() != detected_type:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Declared image type does not match file contents",
        )
    return sanitize_filename(file.filename), detected_type, data


async def lock_handoff_image_collection(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    quote_id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """Lock a quote first, then its linked job, so shared limits cannot race."""
    if (quote_id is None) == (job_id is None):
        raise ValueError("Provide exactly one handoff image parent")

    if quote_id is not None:
        locked_quote_id = await db.scalar(
            select(Quote.id)
            .where(Quote.id == quote_id, Quote.workspace_id == workspace_id)
            .with_for_update()
        )
        if locked_quote_id is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quote not found")
        linked_job_id = await db.scalar(
            select(Job.id)
            .where(Job.workspace_id == workspace_id, Job.source_quote_id == quote_id)
            .with_for_update()
        )
        return quote_id, linked_job_id

    snapshot = (
        await db.execute(
            select(Job.id, Job.source_quote_id).where(
                Job.id == job_id,
                Job.workspace_id == workspace_id,
            )
        )
    ).one_or_none()
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    source_quote_id = snapshot.source_quote_id
    if source_quote_id is not None:
        await db.scalar(
            select(Quote.id)
            .where(Quote.id == source_quote_id, Quote.workspace_id == workspace_id)
            .with_for_update()
        )
    locked_job = (
        await db.execute(
            select(Job.id, Job.source_quote_id)
            .where(Job.id == job_id, Job.workspace_id == workspace_id)
            .with_for_update()
        )
    ).one_or_none()
    if locked_job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if locked_job.source_quote_id != source_quote_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Job handoff changed; retry the upload",
        )
    return source_quote_id, job_id


async def count_handoff_images(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    quote_id: uuid.UUID | None,
    job_id: uuid.UUID | None,
) -> int:
    """Count quote- and job-owned images without loading their binary data."""
    total = 0
    if quote_id is not None:
        total += int(
            await db.scalar(
                select(func.count(QuoteHandoffImage.id)).where(
                    QuoteHandoffImage.workspace_id == workspace_id,
                    QuoteHandoffImage.quote_id == quote_id,
                )
            )
            or 0
        )
    if job_id is not None:
        total += int(
            await db.scalar(
                select(func.count(JobHandoffImage.id)).where(
                    JobHandoffImage.workspace_id == workspace_id,
                    JobHandoffImage.job_id == job_id,
                )
            )
            or 0
        )
    return total
