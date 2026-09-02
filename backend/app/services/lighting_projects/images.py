"""Private object storage for lighting-project images.

The design document is a JSONB column. Embedding base64 photos in it put 82 MB
of image bytes into a 164 MB database on a 500 MB volume, and base64 PNG/JPEG
does not compress, so the only real fix is keeping the bytes out. Images are
written to the same private bucket MMS media uses and referenced from the
document by ``lighting-image:{object_key}``.

Reads mint a short-lived signed URL into a sibling ``resolved_*`` field. The
browser loads that URL with ``crossOrigin="anonymous"`` and draws it onto the
export canvas, which only works because the bucket answers with
``Access-Control-Allow-Origin`` — see ``scripts/ops/set_bucket_cors.py``.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import suppress
from typing import Any, cast

from app.core.config import settings
from app.schemas.lighting_project import (
    LIGHTING_IMAGE_REF_PREFIX,
    LandscapeDraftDocument,
    lighting_image_key,
)
from app.services.messaging.media_storage import (
    MMSMediaStorage,
    MMSStorageError,
    MMSStorageNotConfiguredError,
)
from app.services.messaging.outbound_media import (
    IMAGE_EXTENSIONS,
    OutboundImageValidationError,
    decode_image_data_url,
)

logger = logging.getLogger(__name__)

# A designer session outlives a single request: the editor holds a project in
# React Query cache and re-decodes a shot's photo whenever the canvas remounts.
# The default 300s MMS presign would 403 mid-session, so lighting URLs get the
# configured maximum (1 hour). Active editing refetches on every autosave
# version bump, which re-mints them.
# simplification: an idle session resumed after an hour reloads broken images
# until the next refetch. Upgrade path is a retry-on-error refetch in the editor.
LIGHTING_IMAGE_URL_TTL_SECONDS = 3600

# The frontend downscales to 1600px JPEG before upload (~250-500 KB), so this is
# a defensive ceiling, not a target. Bounded well under the schema's 8 MB data
# URL cap and the bucket wrapper's own max-bytes check.
MAX_LIGHTING_IMAGE_BYTES = 6 * 1024 * 1024

# Serialized names of the read-only fields that must never reach the database.
_RESOLVED_KEYS = frozenset(
    {"resolvedUrl", "resolved_url", "resolvedImageUrl", "resolved_image_url"}
)


class LightingImageError(RuntimeError):
    """A lighting-project image could not be stored."""


def workspace_image_prefix(workspace_id: uuid.UUID) -> str:
    """Every object this workspace may read. The tenant boundary for resolution."""
    return f"workspaces/{workspace_id}/lighting-projects/"


def _object_key(workspace_id: uuid.UUID, project_id: uuid.UUID, extension: str) -> str:
    return f"{workspace_image_prefix(workspace_id)}{project_id}/{uuid.uuid4().hex}{extension}"


async def store_lighting_image(
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    data_url: str,
    storage: MMSMediaStorage | None = None,
) -> str:
    """Validate one image data URL, store the bytes, and return its reference.

    Returns the ``lighting-image:{key}`` value to persist in the document.
    """
    try:
        data, content_type = decode_image_data_url(data_url, max_bytes=MAX_LIGHTING_IMAGE_BYTES)
    except OutboundImageValidationError as exc:
        raise LightingImageError(str(exc)) from exc

    object_key = _object_key(workspace_id, project_id, IMAGE_EXTENSIONS[content_type])
    media_storage = storage or MMSMediaStorage.from_settings()
    try:
        await asyncio.to_thread(
            media_storage.upload_bytes,
            object_key=object_key,
            data=data,
            content_type=content_type,
        )
    except (MMSStorageError, ValueError) as exc:
        raise LightingImageError("Lighting image upload failed") from exc
    return f"{LIGHTING_IMAGE_REF_PREFIX}{object_key}"


def resolve_lighting_image_url(
    value: str | None,
    *,
    workspace_id: uuid.UUID,
    storage: MMSMediaStorage,
) -> str | None:
    """Sign one stored reference for the browser, or return ``None``.

    Returns ``None`` for inline data URLs (nothing to resolve) and for any key
    outside this workspace's prefix. That prefix check is the tenant boundary:
    the reference arrives from the client, so without it an authenticated user
    could name another workspace's object and be handed a signed URL for it.
    """
    key = lighting_image_key(value)
    if key is None or not key.startswith(workspace_image_prefix(workspace_id)):
        return None
    try:
        return storage.create_download_url(
            object_key=key, expires_in=LIGHTING_IMAGE_URL_TTL_SECONDS
        )
    except (MMSStorageError, ValueError):
        # A broken signer must not take the whole project down; the image just
        # fails to render and the rest of the drawing still loads.
        logger.warning("lighting image URL signing failed", exc_info=True)
        return None


def _storage_or_none() -> MMSMediaStorage | None:
    if not settings.mms_storage_enabled:
        return None
    try:
        return MMSMediaStorage.from_settings()
    except MMSStorageNotConfiguredError:
        return None


def resolve_document_images(
    document: LandscapeDraftDocument, *, workspace_id: uuid.UUID
) -> LandscapeDraftDocument:
    """Fill every ``resolved_*`` field in one document, in place.

    Documents that hold only data URLs are returned untouched, so this is safe
    on a deployment with no bucket configured and on unmigrated rows.
    """
    if not _document_has_stored_images(document):
        return document
    storage = _storage_or_none()
    if storage is None:
        return document

    for shot in document.shots:
        shot.photo.resolved_url = resolve_lighting_image_url(
            shot.photo.data_url, workspace_id=workspace_id, storage=storage
        )
        for plan_image in shot.design.plan_images or []:
            plan_image.resolved_url = resolve_lighting_image_url(
                plan_image.data_url, workspace_id=workspace_id, storage=storage
            )
        for annotation in shot.design.annotations or []:
            annotation.resolved_image_url = resolve_lighting_image_url(
                annotation.image_data_url, workspace_id=workspace_id, storage=storage
            )
    return document


async def store_document_images(
    document: LandscapeDraftDocument,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    storage: MMSMediaStorage | None = None,
) -> LandscapeDraftDocument:
    """Move every inline image in one document into the bucket, in place.

    Always clears ``resolved_*`` first so a client echoing back a signed URL can
    never persist an expiring URL into the JSONB column. When storage is not
    configured the document keeps its data URLs and still validates.
    """
    _clear_resolved_urls(document)
    if not _document_has_data_urls(document):
        return document
    media_storage = storage or _storage_or_none()
    if media_storage is None:
        return document

    # Only references minted by *this* call may be rolled back. An image the
    # document already referenced belongs to the saved project, so deleting it
    # on a later failure would destroy a drawing the user still has.
    minted: list[str] = []

    async def _stored(value: str | None) -> str | None:
        if value is None or not value.startswith("data:image/"):
            return value
        reference = await store_lighting_image(
            workspace_id=workspace_id,
            project_id=project_id,
            data_url=value,
            storage=media_storage,
        )
        minted.append(reference)
        return reference

    try:
        for shot in document.shots:
            photo_value = await _stored(shot.photo.data_url)
            if photo_value is not None:
                shot.photo.data_url = photo_value
            for plan_image in shot.design.plan_images or []:
                plan_value = await _stored(plan_image.data_url)
                if plan_value is not None:
                    plan_image.data_url = plan_value
            for annotation in shot.design.annotations or []:
                annotation.image_data_url = await _stored(annotation.image_data_url)
    except LightingImageError:
        await _discard(minted, storage=media_storage)
        raise
    return document


async def _discard(references: list[str], *, storage: MMSMediaStorage) -> None:
    """Best-effort cleanup so a failed save does not leave objects nothing points at."""
    for reference in references:
        key = lighting_image_key(reference)
        if key is None:
            continue
        with suppress(MMSStorageError, ValueError):
            await asyncio.to_thread(storage.delete, object_key=key)


def _image_values(document: LandscapeDraftDocument) -> list[str | None]:
    values: list[str | None] = []
    for shot in document.shots:
        values.append(shot.photo.data_url)
        values.extend(image.data_url for image in shot.design.plan_images or [])
        values.extend(note.image_data_url for note in shot.design.annotations or [])
    return values


def _document_has_stored_images(document: LandscapeDraftDocument) -> bool:
    return any(lighting_image_key(value) is not None for value in _image_values(document))


def _document_has_data_urls(document: LandscapeDraftDocument) -> bool:
    values = _image_values(document)
    return any(value is not None and value.startswith("data:image/") for value in values)


def document_for_storage(document: LandscapeDraftDocument) -> dict[str, Any]:
    """Serialize one document for the JSONB column with no resolved URLs in it.

    ``resolved_*`` is a per-response field holding a URL that expires in an hour.
    Persisting one would put a dead link in the database and grow the column
    again. Clearing then stripping makes that impossible at the only place that
    writes, rather than relying on every caller to remember.
    """
    _clear_resolved_urls(document)
    dumped = document.model_dump(mode="json", by_alias=True)
    return cast("dict[str, Any]", _without_resolved_keys(dumped))


def _without_resolved_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_resolved_keys(item)
            for key, item in value.items()
            if key not in _RESOLVED_KEYS
        }
    if isinstance(value, list):
        return [_without_resolved_keys(item) for item in value]
    return value


def _clear_resolved_urls(document: LandscapeDraftDocument) -> None:
    for shot in document.shots:
        shot.photo.resolved_url = None
        for plan_image in shot.design.plan_images or []:
            plan_image.resolved_url = None
        for annotation in shot.design.annotations or []:
            annotation.resolved_image_url = None
