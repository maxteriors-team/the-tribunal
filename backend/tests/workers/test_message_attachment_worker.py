"""Tests for durable inbound MMS attachment processing."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.models.message_attachment import (
    MESSAGE_ATTACHMENT_FAILED,
    MESSAGE_ATTACHMENT_PENDING,
    MESSAGE_ATTACHMENT_PROCESSING,
    MESSAGE_ATTACHMENT_READY,
    MessageAttachment,
)
from app.services.messaging.media_storage import MMSMediaStorage, MMSStorageError, StoredMedia
from app.workers import message_attachment_worker as worker_module
from app.workers.message_attachment_worker import MessageAttachmentWorker, _object_key


class _SessionContext:
    def __init__(self, db: MagicMock) -> None:
        self._db = db

    async def __aenter__(self) -> MagicMock:
        return self._db

    async def __aexit__(self, *exc: object) -> None:
        return None


def _attachment(*, attempt_count: int = 1) -> MessageAttachment:
    return MessageAttachment(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        provider_position=0,
        source_url="https://media.telnyx.com/inbound/photo.jpg",
        provider_content_type="image/jpeg",
        provider_size_bytes=5,
        provider_sha256=None,
        filename="mms-1.jpg",
        status=MESSAGE_ATTACHMENT_PROCESSING,
        attempt_count=attempt_count,
        processing_started_at=datetime.now(UTC),
    )


async def _http_client(
    *,
    status_code: int = 200,
    content: bytes = b"photo",
) -> httpx.AsyncClient:
    async def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            headers={"Content-Type": "image/jpeg"},
            content=content,
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


async def test_worker_copies_provider_bytes_to_private_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attachment = _attachment()
    db = MagicMock()
    db.get = AsyncMock(return_value=attachment)
    db.commit = AsyncMock()
    monkeypatch.setattr(worker_module, "AsyncSessionLocal", lambda: _SessionContext(db))

    storage = MagicMock(spec=MMSMediaStorage)
    expected_key = _object_key(attachment, "image/jpeg")
    storage.upload_bytes.return_value = StoredMedia(
        object_key=expected_key,
        size_bytes=5,
        sha256="digest",
    )
    client = await _http_client()
    worker = MessageAttachmentWorker(storage=storage, http_client=client)

    try:
        await worker._process_attachment(attachment.id)
    finally:
        await client.aclose()

    storage.upload_bytes.assert_called_once_with(
        object_key=expected_key,
        data=b"photo",
        content_type="image/jpeg",
    )
    assert attachment.status == MESSAGE_ATTACHMENT_READY
    assert attachment.storage_key == expected_key
    assert attachment.content_type == "image/jpeg"
    assert attachment.size_bytes == 5
    assert attachment.sha256 == "digest"
    assert attachment.processed_at is not None
    assert attachment.error_code is None
    db.commit.assert_awaited_once()


async def test_worker_retries_transient_storage_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attachment = _attachment(attempt_count=2)
    db = MagicMock()
    db.get = AsyncMock(return_value=attachment)
    db.commit = AsyncMock()
    monkeypatch.setattr(worker_module, "AsyncSessionLocal", lambda: _SessionContext(db))

    storage = MagicMock(spec=MMSMediaStorage)
    storage.upload_bytes.side_effect = MMSStorageError("unavailable")
    client = await _http_client()
    worker = MessageAttachmentWorker(storage=storage, http_client=client)
    before = datetime.now(UTC)

    try:
        await worker._process_attachment(attachment.id)
    finally:
        await client.aclose()

    assert attachment.status == MESSAGE_ATTACHMENT_PENDING
    assert attachment.error_code == "storage_unavailable"
    assert attachment.next_attempt_at is not None
    assert attachment.next_attempt_at > before + timedelta(minutes=1)
    assert attachment.processing_started_at is None
    db.commit.assert_awaited_once()


async def test_worker_marks_permanent_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attachment = _attachment()
    attachment.provider_sha256 = "0" * 64
    db = MagicMock()
    db.get = AsyncMock(return_value=attachment)
    db.commit = AsyncMock()
    monkeypatch.setattr(worker_module, "AsyncSessionLocal", lambda: _SessionContext(db))

    storage = MagicMock(spec=MMSMediaStorage)
    client = await _http_client()
    worker = MessageAttachmentWorker(storage=storage, http_client=client)

    try:
        await worker._process_attachment(attachment.id)
    finally:
        await client.aclose()

    storage.upload_bytes.assert_not_called()
    assert attachment.status == MESSAGE_ATTACHMENT_FAILED
    assert attachment.error_code == "provider_sha256_mismatch"
    assert attachment.processed_at is not None
    assert attachment.next_attempt_at is None


def test_worker_stops_retrying_after_attempt_budget() -> None:
    attachment = _attachment(attempt_count=8)
    worker = MessageAttachmentWorker(storage=MagicMock(spec=MMSMediaStorage))

    worker._apply_failure(attachment, code="storage_unavailable", retryable=True)

    assert attachment.status == MESSAGE_ATTACHMENT_FAILED
    assert attachment.next_attempt_at is None
    assert attachment.processed_at is not None
