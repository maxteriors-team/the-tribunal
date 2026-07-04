"""Files & Media attachments on a contact record.

Upload, list, download, and delete files attached to a contact. Bytes are
stored in Postgres (``contact_attachments.data``) — uploads are capped at
``MAX_ATTACHMENT_BYTES`` and listings never load the bytes column.

Downloads are same-origin (cookie auth through the Next.js proxy), so image
thumbnails can point straight at the download URL. Only known-safe types are
served inline; everything else is forced to ``Content-Disposition: attachment``
so a stored HTML/SVG payload can't run in the app's origin.
"""

import re
import uuid

import structlog
from fastapi import APIRouter, HTTPException, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import load_only

from app.api.deps import DB, CurrentUser, WorkspaceAccess
from app.models.contact import Contact
from app.models.contact_attachment import ContactAttachment
from app.schemas.contact_attachment import (
    ContactAttachmentListResponse,
    ContactAttachmentResponse,
)

router = APIRouter()
logger = structlog.get_logger()

MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024  # 15 MB

# Types a browser may render inline without a script-execution risk.
# HTML, SVG, and XML are notably absent — they execute in our origin.
INLINE_SAFE_CONTENT_TYPES = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
        "image/heic",
        "image/heif",
        "application/pdf",
        "video/mp4",
        "video/quicktime",
        "video/webm",
        "audio/mpeg",
        "audio/mp4",
        "audio/wav",
        "text/plain",
    }
)

_FILENAME_SANITIZE_RE = re.compile(r"[^\w.\- ()]", flags=re.ASCII)


def sanitize_filename(raw: str | None) -> str:
    """Strip path segments and header-hostile characters from a filename."""
    name = (raw or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    name = _FILENAME_SANITIZE_RE.sub("_", name)
    # Guard against dotfiles / empty names after sanitizing.
    if not name or name.startswith("."):
        name = f"file{name}" if name else "file"
    return name[:255]


def content_disposition(filename: str, content_type: str) -> str:
    """``inline`` only for types that can't execute in our origin."""
    kind = "inline" if content_type in INLINE_SAFE_CONTENT_TYPES else "attachment"
    return f'{kind}; filename="{filename}"'


async def _get_contact(db: DB, workspace_id: uuid.UUID, contact_id: int) -> Contact:
    contact = (
        await db.execute(
            select(Contact).where(
                Contact.id == contact_id,
                Contact.workspace_id == workspace_id,
            )
        )
    ).scalar_one_or_none()
    if contact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")
    return contact


_METADATA_COLUMNS = (
    ContactAttachment.id,
    ContactAttachment.contact_id,
    ContactAttachment.filename,
    ContactAttachment.content_type,
    ContactAttachment.size_bytes,
    ContactAttachment.created_at,
)


@router.get(
    "/contacts/{contact_id}/attachments",
    response_model=ContactAttachmentListResponse,
)
async def list_contact_attachments(
    workspace_id: uuid.UUID,
    contact_id: int,
    workspace: WorkspaceAccess,
    db: DB,
) -> ContactAttachmentListResponse:
    """List attachment metadata for a contact, newest first. Never loads bytes."""
    await _get_contact(db, workspace.id, contact_id)
    rows = (
        (
            await db.execute(
                select(ContactAttachment)
                .options(load_only(*_METADATA_COLUMNS))
                .where(
                    ContactAttachment.workspace_id == workspace.id,
                    ContactAttachment.contact_id == contact_id,
                )
                .order_by(ContactAttachment.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return ContactAttachmentListResponse(
        attachments=[ContactAttachmentResponse.model_validate(row) for row in rows]
    )


@router.post(
    "/contacts/{contact_id}/attachments",
    response_model=ContactAttachmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_contact_attachment(
    workspace_id: uuid.UUID,
    contact_id: int,
    file: UploadFile,
    workspace: WorkspaceAccess,
    current_user: CurrentUser,
    db: DB,
) -> ContactAttachmentResponse:
    """Attach an uploaded file to a contact (max 15 MB)."""
    await _get_contact(db, workspace.id, contact_id)

    data = await file.read()
    if len(data) == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Uploaded file is empty",
        )
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"File exceeds the {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB limit",
        )

    attachment = ContactAttachment(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        contact_id=contact_id,
        filename=sanitize_filename(file.filename),
        content_type=(file.content_type or "application/octet-stream")[:127],
        size_bytes=len(data),
        data=data,
        uploaded_by_user_id=current_user.id,
    )
    db.add(attachment)
    await db.commit()
    await db.refresh(attachment)

    logger.info(
        "contact_attachment_uploaded",
        workspace_id=str(workspace.id),
        contact_id=contact_id,
        attachment_id=str(attachment.id),
        size_bytes=attachment.size_bytes,
    )
    return ContactAttachmentResponse.model_validate(attachment)


@router.get("/contacts/{contact_id}/attachments/{attachment_id}/download")
async def download_contact_attachment(
    workspace_id: uuid.UUID,
    contact_id: int,
    attachment_id: uuid.UUID,
    workspace: WorkspaceAccess,
    db: DB,
) -> Response:
    """Serve the attachment bytes (inline for safe types, download otherwise)."""
    attachment = (
        await db.execute(
            select(ContactAttachment).where(
                ContactAttachment.id == attachment_id,
                ContactAttachment.contact_id == contact_id,
                ContactAttachment.workspace_id == workspace.id,
            )
        )
    ).scalar_one_or_none()
    if attachment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")

    return Response(
        content=attachment.data,
        media_type=attachment.content_type,
        headers={
            "Content-Disposition": content_disposition(
                attachment.filename, attachment.content_type
            ),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.delete(
    "/contacts/{contact_id}/attachments/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_contact_attachment(
    workspace_id: uuid.UUID,
    contact_id: int,
    attachment_id: uuid.UUID,
    workspace: WorkspaceAccess,
    db: DB,
) -> None:
    """Remove an attachment from a contact."""
    attachment = (
        await db.execute(
            select(ContactAttachment)
            .options(load_only(ContactAttachment.id))
            .where(
                ContactAttachment.id == attachment_id,
                ContactAttachment.contact_id == contact_id,
                ContactAttachment.workspace_id == workspace.id,
            )
        )
    ).scalar_one_or_none()
    if attachment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")

    await db.delete(attachment)
    await db.commit()
    logger.info(
        "contact_attachment_deleted",
        workspace_id=str(workspace.id),
        contact_id=contact_id,
        attachment_id=str(attachment_id),
    )
