"""Validation and private storage for operator-supplied outbound MMS images."""

from __future__ import annotations

import asyncio
import base64
import binascii
import uuid
from contextlib import suppress
from dataclasses import dataclass

from app.services.messaging.media_storage import MMSMediaStorage, MMSStorageError

# Telnyx documents 600 KB as the carrier-safe image ceiling. Keeping the API
# boundary at that limit avoids messages that work on one carrier and fail on another.
MAX_OUTBOUND_IMAGE_BYTES = 600 * 1024
MAX_OUTBOUND_IMAGE_DATA_URL_CHARS = (MAX_OUTBOUND_IMAGE_BYTES * 4) // 3 + 64

_IMAGE_EXTENSIONS = {
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


class OutboundImageValidationError(ValueError):
    """An outbound image failed bounded type or content validation."""


@dataclass(frozen=True, slots=True)
class OutboundMedia:
    """Private object metadata ready for Telnyx and timeline persistence."""

    attachment_id: uuid.UUID
    provider_url: str
    storage_key: str
    content_type: str
    size_bytes: int
    sha256: str
    filename: str


def decode_outbound_image_data_url(data_url: str) -> tuple[bytes, str]:
    """Decode one bounded image data URL after checking its real file signature."""
    if not isinstance(data_url, str) or not data_url:
        raise OutboundImageValidationError("Image attachment is empty")
    if len(data_url) > MAX_OUTBOUND_IMAGE_DATA_URL_CHARS:
        raise OutboundImageValidationError("Image attachment exceeds 600 KB")

    header, separator, encoded = data_url.partition(",")
    if not separator or not encoded or not header.startswith("data:"):
        raise OutboundImageValidationError("Image attachment must be a base64 data URL")

    media_type, *parameters = header[5:].split(";")
    content_type = media_type.strip().lower()
    if parameters != ["base64"] or content_type not in _IMAGE_EXTENSIONS:
        raise OutboundImageValidationError("Use a JPEG, PNG, GIF, or WebP image")

    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise OutboundImageValidationError("Image attachment is not valid base64") from exc

    if not data:
        raise OutboundImageValidationError("Image attachment is empty")
    if len(data) > MAX_OUTBOUND_IMAGE_BYTES:
        raise OutboundImageValidationError("Image attachment exceeds 600 KB")
    if not _matches_image_signature(data, content_type):
        raise OutboundImageValidationError("Image contents do not match the selected file type")

    return data, content_type


async def store_outbound_image(
    *,
    workspace_id: uuid.UUID,
    data_url: str,
    storage: MMSMediaStorage | None = None,
) -> OutboundMedia:
    """Validate and store one image privately, returning its short-lived provider URL."""
    data, content_type = decode_outbound_image_data_url(data_url)
    attachment_id = uuid.uuid4()
    extension = _IMAGE_EXTENSIONS[content_type]
    object_key = f"workspaces/{workspace_id}/outbound-attachments/{attachment_id}{extension}"
    media_storage = storage or MMSMediaStorage.from_settings()

    stored = await asyncio.to_thread(
        media_storage.upload_bytes,
        object_key=object_key,
        data=data,
        content_type=content_type,
    )
    try:
        provider_url = media_storage.create_download_url(object_key=object_key)
    except MMSStorageError:
        with suppress(MMSStorageError):
            await asyncio.to_thread(media_storage.delete, object_key=object_key)
        raise

    return OutboundMedia(
        attachment_id=attachment_id,
        provider_url=provider_url,
        storage_key=stored.object_key,
        content_type=content_type,
        size_bytes=stored.size_bytes,
        sha256=stored.sha256,
        filename=f"photo{extension}",
    )


def _matches_image_signature(data: bytes, content_type: str) -> bool:
    if content_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if content_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/gif":
        return data.startswith((b"GIF87a", b"GIF89a"))
    if content_type == "image/webp":
        return len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP"
    return False
