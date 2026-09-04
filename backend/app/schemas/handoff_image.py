"""Safe metadata responses for private quote and job handoff images."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class HandoffImageResponse(BaseModel):
    """Handoff image metadata; file bytes remain download-only."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source: Literal["quote", "job"]
    filename: str
    content_type: Literal["image/jpeg", "image/png", "image/webp"]
    size_bytes: int
    created_at: datetime


class HandoffImageListResponse(BaseModel):
    """Image metadata plus the server-enforced upload limits."""

    images: list[HandoffImageResponse]
    max_images: int
    max_image_bytes: int
