"""Schemas for contact Files & Media attachments."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ContactAttachmentResponse(BaseModel):
    """Attachment metadata — bytes are served by the download endpoint."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    contact_id: int
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime


class ContactAttachmentListResponse(BaseModel):
    """All attachments on one contact, newest first."""

    attachments: list[ContactAttachmentResponse]
