"""Photorealistic night-render of a rep's drawn lighting design (Phase 2).

Turns the composited design image (glowing lights drawn over the customer's
photo) into a photorealistic dusk photograph via the workspace's OpenAI image
model — the visual "closer" a rep shows a skeptical homeowner. Uses the
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

_SUPPORTED_MIME = {
    "image/png": "design.png",
    "image/jpeg": "design.jpg",
    "image/jpg": "design.jpg",
    "image/webp": "design.webp",
}

# Ported 1:1 from the in-house light-estimator ``defaultPrompt`` so the render
# matches what reps already trust. Kept under the OpenAI 1000-char prompt cap.
_LIGHTS = {
    "permanent": (
        "permanent LED track lighting mounted flush along the eaves and "
        "rooflines, with the same colors and spacing as the drawn dots"
    ),
    "seasonal": (
        "professional C9 Christmas lights along the rooflines, lit garland, "
        "glowing bushes and holiday decor exactly where they are drawn"
    ),
}


def default_render_prompt(mode: str) -> str:
    """Return the default night-render prompt for a seasonal/permanent design."""
    lights = _LIGHTS.get(mode, _LIGHTS["seasonal"])
    return (
        f"Turn this into a photorealistic professional night photograph of this "
        f"exact house with {lights}. Keep the architecture, windows, doors, "
        "rooflines, landscaping, and camera angle exactly the same. Replace the "
        "drawn glowing dots with realistic light bulbs casting a soft warm glow "
        "on the walls and roof. Dusk sky, magazine-quality holiday lighting "
        "installation photo."
    )


def _decode_design_image(image: str) -> tuple[bytes, str]:
    """Decode a base64 ``data:`` URL (or raw base64) into ``(bytes, filename)``.

    Raises :class:`ValidationError` for anything we can't turn into a supported
    image, so a malformed upload is a clean 400 rather than an OpenAI 4xx.
    """
    raw = image.strip()
    filename = "design.png"
    if raw.startswith("data:"):
        header, _, payload = raw.partition(",")
        if not payload:
            raise ValidationError("The design image was empty or malformed.")
        mime = header[5:].split(";", 1)[0].strip().lower()
        filename = _SUPPORTED_MIME.get(mime, "design.png")
        raw = payload

    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValidationError("The design image was not valid base64.") from exc

    if not data:
        raise ValidationError("The design image was empty.")
    if len(data) > _MAX_IMAGE_BYTES:
        raise ValidationError("The design image is too large to render.")
    return data, filename


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
    data, filename = _decode_design_image(image)
    prompt_text = (prompt or "").strip() or default_render_prompt(mode)

    try:
        client = await create_workspace_openai_client(db, workspace_id)
    except OpenAICredentialError as exc:
        logger.warning("estimate_render_no_credentials", workspace_id=str(workspace_id))
        raise ServiceUnavailableError(
            "AI render isn't available — connect an OpenAI credential for this workspace."
        ) from exc

    try:
        response = await client.images.edit(
            model=settings.openai_estimate_render_model,
            image=(filename, data, "application/octet-stream"),
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
