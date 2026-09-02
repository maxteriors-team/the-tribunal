"""Boundary tests for moving lighting-project images into private storage."""

import base64
import uuid
from unittest.mock import MagicMock

import pytest

from app.schemas.lighting_project import (
    LIGHTING_IMAGE_REF_PREFIX,
    LandscapeDraftDocument,
    lighting_image_key,
)
from app.services.lighting_projects.images import (
    LIGHTING_IMAGE_URL_TTL_SECONDS,
    MAX_LIGHTING_IMAGE_BYTES,
    LightingImageError,
    resolve_document_images,
    resolve_lighting_image_url,
    store_document_images,
    store_lighting_image,
    workspace_image_prefix,
)
from app.services.messaging.media_storage import MMSStorageError, StoredMedia

PNG = b"\x89PNG\r\n\x1a\n" + b"pixels"
JPEG = b"\xff\xd8\xff" + b"pixels"


def _data_url(content_type: str, data: bytes) -> str:
    return f"data:{content_type};base64,{base64.b64encode(data).decode()}"


def _storage() -> MagicMock:
    storage = MagicMock()
    storage.upload_bytes.return_value = StoredMedia(object_key="k", size_bytes=1, sha256="d")
    storage.create_download_url.return_value = "https://bucket.example/signed"
    return storage


def _document(*, photo: str, plan_image: str | None = None, annotation: str | None = None) -> dict:
    design: dict = {"calibration": None, "runs": [], "items": []}
    if plan_image is not None:
        design["planImages"] = [
            {
                "id": "plan-1",
                "dataUrl": plan_image,
                "name": "detail.png",
                "at": {"x": 1, "y": 2},
                "widthPx": 10,
                "heightPx": 10,
            }
        ]
    if annotation is not None:
        design["annotations"] = [
            {"id": "note-1", "type": "photo", "at": {"x": 1, "y": 1}, "imageDataUrl": annotation}
        ]
    return {
        "version": 2,
        "projectType": "landscape",
        "activeShotId": "shot-1",
        "shots": [
            {
                "id": "shot-1",
                "photo": {"dataUrl": photo, "width": 100, "height": 80},
                "design": design,
                "dusk": 0.3,
            }
        ],
        "updatedAt": "2026-01-01T00:00:00+00:00",
    }


async def test_store_lighting_image_writes_a_workspace_and_project_scoped_object() -> None:
    workspace_id, project_id = uuid.uuid4(), uuid.uuid4()
    storage = _storage()

    reference = await store_lighting_image(
        workspace_id=workspace_id,
        project_id=project_id,
        data_url=_data_url("image/png", PNG),
        storage=storage,
    )

    key = lighting_image_key(reference)
    assert key is not None
    assert key.startswith(f"{workspace_image_prefix(workspace_id)}{project_id}/")
    assert key.endswith(".png")
    assert storage.upload_bytes.call_args.kwargs["content_type"] == "image/png"
    assert storage.upload_bytes.call_args.kwargs["data"] == PNG


async def test_store_lighting_image_rejects_a_spoofed_content_type() -> None:
    with pytest.raises(LightingImageError, match="do not match"):
        await store_lighting_image(
            workspace_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            data_url=_data_url("image/png", b"not-really-a-png"),
            storage=_storage(),
        )


async def test_store_lighting_image_rejects_an_oversized_payload() -> None:
    oversized = b"\xff\xd8\xff" + b"x" * MAX_LIGHTING_IMAGE_BYTES

    with pytest.raises(LightingImageError, match="exceeds"):
        await store_lighting_image(
            workspace_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            data_url=_data_url("image/jpeg", oversized),
            storage=_storage(),
        )


def test_resolve_signs_only_keys_inside_the_callers_own_workspace() -> None:
    workspace_id, intruder_workspace_id = uuid.uuid4(), uuid.uuid4()
    storage = _storage()
    own = f"{LIGHTING_IMAGE_REF_PREFIX}{workspace_image_prefix(workspace_id)}p/a.png"
    foreign = f"{LIGHTING_IMAGE_REF_PREFIX}{workspace_image_prefix(intruder_workspace_id)}p/a.png"

    assert resolve_lighting_image_url(own, workspace_id=workspace_id, storage=storage) is not None
    assert resolve_lighting_image_url(foreign, workspace_id=workspace_id, storage=storage) is None
    assert storage.create_download_url.call_count == 1
    assert storage.create_download_url.call_args.kwargs["expires_in"] == (
        LIGHTING_IMAGE_URL_TTL_SECONDS
    )


def test_resolve_leaves_inline_data_urls_alone() -> None:
    storage = _storage()

    assert (
        resolve_lighting_image_url(
            _data_url("image/png", PNG), workspace_id=uuid.uuid4(), storage=storage
        )
        is None
    )
    storage.create_download_url.assert_not_called()


def test_resolve_document_images_survives_a_signing_failure() -> None:
    workspace_id = uuid.uuid4()
    storage = _storage()
    storage.create_download_url.side_effect = MMSStorageError("signer down")
    reference = f"{LIGHTING_IMAGE_REF_PREFIX}{workspace_image_prefix(workspace_id)}p/a.png"
    document = LandscapeDraftDocument.model_validate(_document(photo=reference))

    resolved = resolve_document_images(document, workspace_id=workspace_id)

    assert resolved.shots[0].photo.resolved_url is None
    assert resolved.shots[0].photo.data_url == reference


def test_resolve_document_images_fills_every_image_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    workspace_id = uuid.uuid4()
    storage = _storage()
    monkeypatch.setattr("app.services.lighting_projects.images._storage_or_none", lambda: storage)
    reference = f"{LIGHTING_IMAGE_REF_PREFIX}{workspace_image_prefix(workspace_id)}p/a.png"
    document = LandscapeDraftDocument.model_validate(
        _document(photo=reference, plan_image=reference, annotation=reference)
    )

    resolved = resolve_document_images(document, workspace_id=workspace_id)

    shot = resolved.shots[0]
    assert shot.photo.resolved_url == "https://bucket.example/signed"
    assert shot.design.plan_images[0].resolved_url == "https://bucket.example/signed"
    assert shot.design.annotations[0].resolved_image_url == "https://bucket.example/signed"
    # A half-migrated document must resolve what it can and leave the rest.
    assert lighting_image_key(shot.photo.data_url) is not None


async def test_store_document_images_persists_keys_not_bytes() -> None:
    workspace_id, project_id = uuid.uuid4(), uuid.uuid4()
    storage = _storage()
    document = LandscapeDraftDocument.model_validate(
        _document(
            photo=_data_url("image/jpeg", JPEG),
            plan_image=_data_url("image/png", PNG),
            annotation=_data_url("image/png", PNG),
        )
    )

    stored = await store_document_images(
        document, workspace_id=workspace_id, project_id=project_id, storage=storage
    )

    serialized = stored.model_dump_json(by_alias=True)
    assert "data:image" not in serialized
    assert lighting_image_key(stored.shots[0].photo.data_url) is not None
    assert lighting_image_key(stored.shots[0].design.plan_images[0].data_url) is not None
    assert lighting_image_key(stored.shots[0].design.annotations[0].image_data_url) is not None
    assert storage.upload_bytes.call_count == 3


async def test_store_document_images_strips_client_supplied_resolved_urls() -> None:
    """A client echoes the whole document back; an expiring URL must never persist."""
    workspace_id = uuid.uuid4()
    reference = f"{LIGHTING_IMAGE_REF_PREFIX}{workspace_image_prefix(workspace_id)}p/a.png"
    payload = _document(photo=reference)
    payload["shots"][0]["photo"]["resolvedUrl"] = "https://bucket.example/expiring"
    document = LandscapeDraftDocument.model_validate(payload)

    stored = await store_document_images(
        document, workspace_id=workspace_id, project_id=uuid.uuid4(), storage=_storage()
    )

    assert stored.shots[0].photo.resolved_url is None
    assert "https://bucket.example/expiring" not in stored.model_dump_json(by_alias=True)


async def test_store_document_images_rolls_back_only_what_it_just_wrote() -> None:
    workspace_id = uuid.uuid4()
    storage = _storage()
    existing_key = f"{workspace_image_prefix(workspace_id)}p/already-saved.png"
    document = LandscapeDraftDocument.model_validate(
        _document(
            photo=f"{LIGHTING_IMAGE_REF_PREFIX}{existing_key}",
            plan_image=_data_url("image/png", PNG),
            annotation=_data_url("image/png", b"not-really-a-png"),
        )
    )

    with pytest.raises(LightingImageError):
        await store_document_images(
            document, workspace_id=workspace_id, project_id=uuid.uuid4(), storage=storage
        )

    deleted = {call.kwargs["object_key"] for call in storage.delete.call_args_list}
    assert existing_key not in deleted, "an already-saved image must never be deleted"
    assert len(deleted) == 1, "the plan image written moments ago should be cleaned up"
