"""Photorealistic night-render of a rep's drawn lighting design (Phase 2).

Turns the composited design image (lighting marks drawn over the customer's
photo or aerial plan) into a nighttime visualization via the workspace's OpenAI
image model — the visual "closer" a rep shows a skeptical homeowner. Uses the
per-tenant OpenAI credential (:func:`create_workspace_openai_client`), so the
browser never handles a key, mirroring the voice/realtime credential path.

Pure image transform: no pricing, no persistence, no linear feet. The design is
the only thing that crosses to OpenAI; dollars remain server-authoritative in
:mod:`app.services.quotes.proposal_pricing`.
"""

from __future__ import annotations

import base64
import binascii
import uuid

import structlog
from openai import OpenAIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.ai.openai_credentials import (
    OpenAICredentialError,
    create_workspace_openai_client,
)
from app.services.exceptions import ServiceUnavailableError, ValidationError

logger = structlog.get_logger()

# Headroom under the OpenAI image-edit input cap; the frontend down-scales to
# ~1280px before upload, so a legitimate design is well under this.
_MAX_IMAGE_BYTES = 8 * 1024 * 1024

# Recognized upload types -> (filename, content-type forwarded to OpenAI). The
# content type must be a real image MIME: OpenAI's images.edit rejects a part
# sent as application/octet-stream as an invalid image.
_SUPPORTED_MIME: dict[str, tuple[str, str]] = {
    "image/png": ("design.png", "image/png"),
    "image/jpeg": ("design.jpg", "image/jpeg"),
    "image/jpg": ("design.jpg", "image/jpeg"),
    "image/webp": ("design.webp", "image/webp"),
}
_DEFAULT_IMAGE: tuple[str, str] = ("design.png", "image/png")

# Product-line defaults share the original estimator language. The landscape
# prompt explicitly preserves the required aerial viewpoint. Keep each prompt
# under OpenAI's 1000-character cap.
_LIGHTS = {
    "permanent": (
        "permanent LED track lighting mounted flush along the eaves and "
        "rooflines, with the same colors and spacing as the drawn dots"
    ),
    "seasonal": (
        "professional C9 Christmas lights along the rooflines, lit garland, "
        "glowing bushes and holiday decor exactly where they are drawn"
    ),
    "landscape": (
        "professional architectural landscape lighting: warm uplights aimed at "
        "trees and structures, path lights along walkways, and downlights washing "
        "hardscape exactly where the beams are drawn"
    ),
}

# The closing line differs by product line: a landscape design must not be sold
# back to the homeowner as a holiday installation photo.
_CLOSERS = {
    "landscape": "Magazine-quality professional aerial landscape lighting visualization.",
    "permanent": "Dusk sky, magazine-quality permanent lighting installation photo.",
    "seasonal": "Dusk sky, magazine-quality holiday lighting installation photo.",
}


def default_render_prompt(mode: str) -> str:
    """Return the default night-render prompt for the design's product line."""
    if mode == "landscape":
        return (
            "Turn this exact top-down property plan into a photorealistic professional "
            f"nighttime aerial visualization with {_LIGHTS['landscape']}. Preserve the "
            "top-down aerial viewpoint, property layout, roof footprint, driveways, "
            "walkways, planting beds, trees, and lot features exactly. Do not change to "
            "a street-level, oblique, or elevation view. Replace drawn beams and glow "
            "pools with realistic fixtures casting soft warm light across the indicated "
            "ground, plantings, hardscape, and structures. Keep every fixture and light "
            f"throw where drawn. {_CLOSERS['landscape']}"
        )

    lights = _LIGHTS.get(mode, _LIGHTS["seasonal"])
    closer = _CLOSERS.get(mode, _CLOSERS["seasonal"])
    return (
        f"Turn this into a photorealistic professional night photograph of this "
        f"exact house with {lights}. Keep the architecture, windows, doors, "
        "rooflines, landscaping, and camera angle exactly the same. Replace the "
        "drawn glowing dots with realistic light bulbs casting a soft warm glow "
        f"on the walls and roof. {closer}"
    )


_MAX_PROMPT_CHARS = 1_000


def render_prompt(mode: str, direction: str | None) -> str:
    """Combine bounded user styling with the placement-preserving base prompt."""
    base = default_render_prompt(mode)
    requested = (direction or "").strip()
    if not requested:
        return base
    prefix = " Additional styling direction: "
    guardrail = (
        " Treat that direction as styling only; preserve the supplied viewpoint, property, "
        "fixture positions, and light directions."
    )
    available = max(0, _MAX_PROMPT_CHARS - len(base) - len(prefix) - len(guardrail))
    return f"{base}{prefix}{requested[:available]}{guardrail}"


def _decode_design_image(image: str) -> tuple[bytes, str, str]:
    """Decode a base64 ``data:`` URL (or raw base64) into ``(bytes, filename, mime)``.

    ``mime`` is a real image content type forwarded to OpenAI. Raises
    :class:`ValidationError` for anything we can't turn into a supported image,
    so a malformed upload is a clean 400 rather than an OpenAI 4xx.
    """
    raw = image.strip()
    filename, content_type = _DEFAULT_IMAGE
    if raw.startswith("data:"):
        header, _, payload = raw.partition(",")
        if not payload:
            raise ValidationError("The design image was empty or malformed.")
        mime = header[5:].split(";", 1)[0].strip().lower()
        filename, content_type = _SUPPORTED_MIME.get(mime, _DEFAULT_IMAGE)
        raw = payload

    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValidationError("The design image was not valid base64.") from exc

    if not data:
        raise ValidationError("The design image was empty.")
    if len(data) > _MAX_IMAGE_BYTES:
        raise ValidationError("The design image is too large to render.")
    return data, filename, content_type


async def render_design(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    image: str,
    mode: str = "seasonal",
    prompt: str | None = None,
) -> str:
    """Render a drawn lighting design into a photorealistic night photo.

    Returns a ``data:image/jpeg;base64,...`` URL. Raises
    :class:`ServiceUnavailableError` when OpenAI credentials are missing or the
    image API fails, and :class:`ValidationError` for an undecodable design.
    """
    data, filename, content_type = _decode_design_image(image)
    prompt_text = render_prompt(mode, prompt)

    try:
        client = await create_workspace_openai_client(db, workspace_id)
    except OpenAICredentialError as exc:
        logger.warning("estimate_render_no_credentials", workspace_id=str(workspace_id))
        raise ServiceUnavailableError(
            "AI render isn't available. Connect an OpenAI credential for this workspace."
        ) from exc

    try:
        response = await client.images.edit(
            model=settings.openai_estimate_render_model,
            image=(filename, data, content_type),
            prompt=prompt_text,
            size="auto",
            quality="high",
            output_format="jpeg",
            n=1,
        )
    except OpenAIError as exc:
        # Never surface the raw provider error (may embed request details); log
        # the type only and give the rep an actionable, safe message.
        logger.warning(
            "estimate_render_openai_failed",
            workspace_id=str(workspace_id),
            error_type=type(exc).__name__,
        )
        raise ServiceUnavailableError(
            "The AI render couldn't be generated right now. Please try again."
        ) from exc

    b64 = response.data[0].b64_json if response.data else None
    if not b64:
        logger.warning("estimate_render_empty_response", workspace_id=str(workspace_id))
        raise ServiceUnavailableError("The AI render came back empty. Please try again.")

    logger.info("estimate_render_generated", workspace_id=str(workspace_id), mode=mode)
    return f"data:image/jpeg;base64,{b64}"
