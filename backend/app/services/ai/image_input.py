"""Shared validation and content-part builders for user-supplied image inputs.

Customer images flow into AI conversations as base64 ``data:`` URLs. They are
never written to the unauthenticated ``/static`` directory and are not
persisted to the database; they are forwarded inline to OpenAI for the current
turn only, so the app controls exactly which images are shared and when.

This module is intentionally dependency-free (stdlib only) so both Pydantic
schemas and service code can import it without creating import cycles.
"""

from __future__ import annotations

import base64
import binascii
from typing import Any

# Decoded-image size cap. Realtime/vision models reject very large inputs and
# unbounded base64 would let a public embed caller exhaust memory.
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB decoded

ALLOWED_IMAGE_MIME_TYPES: frozenset[str] = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/gif",
    }
)

# Defensive cap on the raw data-URL string before any decoding work. base64
# inflates bytes by ~4/3; add a small margin for the ``data:<mime>;base64,``
# header.
_MAX_DATA_URL_CHARS = (MAX_IMAGE_BYTES * 4) // 3 + 256


class ImageValidationError(ValueError):
    """Raised when a supplied image data URL is missing, malformed, or too large."""


def validate_image_data_url(value: str) -> str:
    """Validate a base64 image ``data:`` URL and return it normalized.

    Enforces a MIME allowlist and a decoded-size cap so callers can forward
    customer images to OpenAI without trusting unbounded input. Raises
    :class:`ImageValidationError` on any problem.
    """
    if not isinstance(value, str):
        raise ImageValidationError("Image must be a base64 data URL string")

    data_url = value.strip()
    if not data_url:
        raise ImageValidationError("Image data URL is empty")
    if len(data_url) > _MAX_DATA_URL_CHARS:
        raise ImageValidationError("Image exceeds the maximum allowed size")
    if not data_url.startswith("data:"):
        raise ImageValidationError("Image must be a data URL (data:<mime>;base64,...)")

    header, separator, payload = data_url.partition(",")
    if not separator or not payload or ";base64" not in header:
        raise ImageValidationError("Image must be base64-encoded")

    mime = header[len("data:") :].split(";", 1)[0].strip().lower()
    if mime not in ALLOWED_IMAGE_MIME_TYPES:
        allowed = ", ".join(sorted(ALLOWED_IMAGE_MIME_TYPES))
        raise ImageValidationError(
            f"Unsupported image type '{mime or 'unknown'}'. Allowed: {allowed}"
        )

    try:
        decoded = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ImageValidationError("Image payload is not valid base64") from exc

    if not decoded:
        raise ImageValidationError("Image payload is empty")
    if len(decoded) > MAX_IMAGE_BYTES:
        raise ImageValidationError("Image exceeds the maximum allowed size")

    return f"data:{mime};base64,{payload}"


def build_chat_image_content_part(data_url: str) -> dict[str, Any]:
    """Build an OpenAI Chat Completions ``image_url`` content part from a data URL."""
    return {"type": "image_url", "image_url": {"url": data_url}}


def build_chat_user_message_with_image(text: str, data_url: str | None) -> dict[str, Any]:
    """Build a Chat Completions ``user`` message, attaching an image when present.

    With no image the content stays a plain string (the common case), so
    text-only callers and their assertions are unaffected. With an image the
    content becomes the multimodal parts array vision models expect.
    """
    if not data_url:
        return {"role": "user", "content": text}

    content: list[dict[str, Any]] = []
    if text:
        content.append({"type": "text", "text": text})
    content.append(build_chat_image_content_part(data_url))
    return {"role": "user", "content": content}
