"""Tests for private S3-compatible MMS object storage."""

from hashlib import sha256
from unittest.mock import Mock, patch

import pytest
from botocore.config import Config
from botocore.exceptions import ClientError

from app.core.config import Settings
from app.services.messaging.media_storage import (
    MMSMediaStorage,
    MMSStorageError,
    MMSStorageNotConfiguredError,
)

_SECRET_KEY = "s" * 32


def _settings(**overrides: object) -> Settings:
    return Settings(secret_key=_SECRET_KEY, _env_file=None, **overrides)  # type: ignore[arg-type]


def _configured_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "mms_storage_bucket": "crm-media-test",
        "mms_storage_endpoint_url": "https://storage.railway.app",
        "mms_storage_access_key_id": "test-access-key",
        "mms_storage_secret_access_key": "test-secret-key",
        "mms_storage_region": "auto",
    }
    values.update(overrides)
    return _settings(**values)


def _storage(*, client: Mock | None = None, max_bytes: int = 1024) -> tuple[MMSMediaStorage, Mock]:
    resolved_client = client or Mock()
    return (
        MMSMediaStorage(
            client=resolved_client,
            bucket="crm-media-test",
            max_bytes=max_bytes,
            presign_ttl_seconds=300,
        ),
        resolved_client,
    )


def _client_error(operation: str) -> ClientError:
    return ClientError(
        error_response={"Error": {"Code": "InternalError", "Message": "failed"}},
        operation_name=operation,
    )


def test_from_settings_requires_complete_configuration() -> None:
    with pytest.raises(MMSStorageNotConfiguredError, match="not configured"):
        MMSMediaStorage.from_settings(_settings())


@patch("app.services.messaging.media_storage.boto3.client")
def test_from_settings_builds_explicit_private_s3_client(client_factory: Mock) -> None:
    client_factory.return_value = Mock()

    MMSMediaStorage.from_settings(_configured_settings(mms_storage_addressing_style="path"))

    client_factory.assert_called_once()
    args, kwargs = client_factory.call_args
    assert args == ("s3",)
    assert kwargs["endpoint_url"] == "https://storage.railway.app"
    assert kwargs["aws_access_key_id"] == "test-access-key"
    assert kwargs["aws_secret_access_key"] == "test-secret-key"
    assert kwargs["region_name"] == "auto"
    assert isinstance(kwargs["config"], Config)
    assert kwargs["config"].signature_version == "s3v4"
    assert kwargs["config"].s3 == {"addressing_style": "path"}


def test_upload_bytes_writes_private_object_with_digest_metadata() -> None:
    storage, client = _storage()
    body = b"fake-image-bytes"
    expected_digest = sha256(body).hexdigest()

    stored = storage.upload_bytes(
        object_key="workspaces/ws/messages/msg/photo.jpg",
        data=body,
        content_type="image/jpeg",
    )

    client.put_object.assert_called_once_with(
        Bucket="crm-media-test",
        Key="workspaces/ws/messages/msg/photo.jpg",
        Body=body,
        ContentLength=len(body),
        ContentType="image/jpeg",
        Metadata={"sha256": expected_digest},
    )
    assert "ACL" not in client.put_object.call_args.kwargs
    assert stored.object_key == "workspaces/ws/messages/msg/photo.jpg"
    assert stored.size_bytes == len(body)
    assert stored.sha256 == expected_digest


@pytest.mark.parametrize(
    ("data", "content_type", "expected_error"),
    [
        (b"", "image/jpeg", "cannot be empty"),
        (b"too-large", "image/jpeg", "exceeds the 4-byte"),
        (b"ok", " ", "content type cannot be blank"),
    ],
)
def test_upload_bytes_rejects_invalid_media(
    data: bytes,
    content_type: str,
    expected_error: str,
) -> None:
    storage, client = _storage(max_bytes=4)

    with pytest.raises(ValueError, match=expected_error):
        storage.upload_bytes(
            object_key="workspaces/ws/messages/msg/photo.jpg",
            data=data,
            content_type=content_type,
        )

    client.put_object.assert_not_called()


@pytest.mark.parametrize(
    "object_key",
    ["", "/absolute/photo.jpg", "../photo.jpg", "folder//photo.jpg", "folder\\photo.jpg"],
)
def test_storage_rejects_unsafe_object_keys(object_key: str) -> None:
    storage, client = _storage()

    with pytest.raises(ValueError, match="normalized relative path"):
        storage.upload_bytes(object_key=object_key, data=b"ok", content_type="image/jpeg")

    client.put_object.assert_not_called()


def test_upload_wraps_provider_error() -> None:
    client = Mock()
    client.put_object.side_effect = _client_error("PutObject")
    storage, _ = _storage(client=client)

    with pytest.raises(MMSStorageError, match="upload failed"):
        storage.upload_bytes(
            object_key="workspaces/ws/messages/msg/photo.jpg",
            data=b"ok",
            content_type="image/jpeg",
        )


def test_create_download_url_uses_short_lived_private_get() -> None:
    client = Mock()
    client.generate_presigned_url.return_value = (
        "https://crm-media-test.storage.railway.app/photo.jpg?signature=redacted"
    )
    storage, _ = _storage(client=client)

    url = storage.create_download_url(object_key="workspaces/ws/messages/msg/photo.jpg")

    assert url.startswith("https://")
    client.generate_presigned_url.assert_called_once_with(
        "get_object",
        Params={
            "Bucket": "crm-media-test",
            "Key": "workspaces/ws/messages/msg/photo.jpg",
        },
        ExpiresIn=300,
    )


def test_create_download_url_rejects_empty_provider_result() -> None:
    client = Mock()
    client.generate_presigned_url.return_value = ""
    storage, _ = _storage(client=client)

    with pytest.raises(MMSStorageError, match="empty URL"):
        storage.create_download_url(object_key="workspaces/ws/messages/msg/photo.jpg")


def test_delete_uses_private_bucket_and_is_wrapped() -> None:
    client = Mock()
    storage, _ = _storage(client=client)

    storage.delete(object_key="workspaces/ws/messages/msg/photo.jpg")

    client.delete_object.assert_called_once_with(
        Bucket="crm-media-test",
        Key="workspaces/ws/messages/msg/photo.jpg",
    )
