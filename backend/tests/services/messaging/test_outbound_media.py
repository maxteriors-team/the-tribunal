"""Outbound MMS image boundary and private-storage tests."""

import base64
import uuid
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from app.schemas.contact import SendMessageToContactRequest
from app.services.messaging.media_storage import MMSStorageError, StoredMedia
from app.services.messaging.outbound_media import (
    MAX_OUTBOUND_IMAGE_BYTES,
    OutboundImageValidationError,
    decode_image_data_url,
    store_outbound_image,
)


def _data_url(content_type: str, data: bytes) -> str:
    return f"data:{content_type};base64,{base64.b64encode(data).decode()}"


def test_send_message_request_allows_image_without_caption() -> None:
    data_url = _data_url("image/jpeg", b"\xff\xd8\xffsafe-image")

    request = SendMessageToContactRequest(image_data_url=data_url)

    assert request.body == ""
    assert request.image_data_url == data_url


def test_send_message_request_requires_text_or_image() -> None:
    with pytest.raises(ValidationError, match="message or image attachment"):
        SendMessageToContactRequest(body="   ")


def test_decode_outbound_image_accepts_matching_jpeg() -> None:
    data = b"\xff\xd8\xff" + b"safe-image"

    decoded, content_type = decode_image_data_url(_data_url("image/jpeg", data))

    assert decoded == data
    assert content_type == "image/jpeg"


def test_decode_outbound_image_rejects_spoofed_content_type() -> None:
    with pytest.raises(OutboundImageValidationError, match="contents do not match"):
        decode_image_data_url(_data_url("image/jpeg", b"not-an-image"))


def test_decode_outbound_image_rejects_carrier_oversize_payload() -> None:
    oversized = b"\xff\xd8\xff" + b"x" * MAX_OUTBOUND_IMAGE_BYTES

    with pytest.raises(OutboundImageValidationError, match="exceeds 600 KB"):
        decode_image_data_url(_data_url("image/jpeg", oversized))


async def test_store_outbound_image_uses_workspace_scoped_private_object() -> None:
    workspace_id = uuid.uuid4()
    data = b"\xff\xd8\xffprivate-photo"
    storage = MagicMock()
    storage.upload_bytes.return_value = StoredMedia(
        object_key="stored-key",
        size_bytes=len(data),
        sha256="a" * 64,
    )
    storage.create_download_url.return_value = "https://storage.example/signed-photo"

    media = await store_outbound_image(
        workspace_id=workspace_id,
        data_url=_data_url("image/jpeg", data),
        storage=storage,
    )

    upload = storage.upload_bytes.call_args.kwargs
    assert upload["object_key"].startswith(f"workspaces/{workspace_id}/outbound-attachments/")
    assert upload["object_key"].endswith(".jpg")
    assert upload["data"] == data
    assert upload["content_type"] == "image/jpeg"
    assert media.storage_key == "stored-key"
    assert media.provider_url == "https://storage.example/signed-photo"
    assert media.filename == "photo.jpg"


async def test_store_outbound_image_deletes_object_when_presigning_fails() -> None:
    workspace_id = uuid.uuid4()
    data = b"\xff\xd8\xffprivate-photo"
    storage = MagicMock()
    storage.upload_bytes.return_value = StoredMedia(
        object_key="stored-key",
        size_bytes=len(data),
        sha256="a" * 64,
    )
    storage.create_download_url.side_effect = MMSStorageError("presign failed")

    with pytest.raises(MMSStorageError, match="presign failed"):
        await store_outbound_image(
            workspace_id=workspace_id,
            data_url=_data_url("image/jpeg", data),
            storage=storage,
        )

    storage.delete.assert_called_once_with(
        object_key=storage.upload_bytes.call_args.kwargs["object_key"]
    )
