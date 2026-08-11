"""Durable worker that copies inbound MMS media into private object storage."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import and_, or_, select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.message_attachment import (
    MESSAGE_ATTACHMENT_FAILED,
    MESSAGE_ATTACHMENT_PENDING,
    MESSAGE_ATTACHMENT_PROCESSING,
    MESSAGE_ATTACHMENT_READY,
    MessageAttachment,
)
from app.services.messaging.media_ingestion import (
    MediaDownloadError,
    download_provider_media,
)
from app.services.messaging.media_storage import MMSMediaStorage, MMSStorageError
from app.workers.base import BaseWorker, WorkerRegistry

_BATCH_SIZE = 10
_MAX_ATTEMPTS = 8
_STALE_PROCESSING_AFTER = timedelta(minutes=5)
_RETRY_DELAYS = (
    timedelta(seconds=30),
    timedelta(minutes=2),
    timedelta(minutes=10),
    timedelta(hours=1),
    timedelta(hours=6),
    timedelta(days=1),
    timedelta(days=3),
)
_CONTENT_TYPE_EXTENSIONS = {
    "image/gif": ".gif",
    "image/heic": ".heic",
    "image/heif": ".heif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "video/3gpp": ".3gp",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
}


class MessageAttachmentWorker(BaseWorker):
    """Poll durable attachment rows and privately persist provider bytes."""

    POLL_INTERVAL_SECONDS = 2
    COMPONENT_NAME = "message_attachment"
    MAX_CONCURRENCY = 3

    def __init__(
        self,
        *,
        storage: MMSMediaStorage | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__()
        self._storage = storage
        self._http_client = http_client
        self._owns_http_client = http_client is None

    async def _on_start(self) -> None:
        if self._storage is None:
            self._storage = MMSMediaStorage.from_settings()
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0),
                limits=httpx.Limits(max_connections=6, max_keepalive_connections=3),
                follow_redirects=True,
                max_redirects=3,
            )

    async def _on_stop(self) -> None:
        if self._owns_http_client and self._http_client is not None:
            await self._http_client.aclose()

    async def _process_items(self) -> None:
        attachment_ids = await self._claim_due_attachments()
        if not attachment_ids:
            return
        await self.run_concurrently(
            self._process_attachment(attachment_id) for attachment_id in attachment_ids
        )

    async def _claim_due_attachments(self) -> list[uuid.UUID]:
        now = datetime.now(UTC)
        stale_before = now - _STALE_PROCESSING_AFTER
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(MessageAttachment)
                .where(
                    or_(
                        and_(
                            MessageAttachment.status == MESSAGE_ATTACHMENT_PENDING,
                            or_(
                                MessageAttachment.next_attempt_at.is_(None),
                                MessageAttachment.next_attempt_at <= now,
                            ),
                        ),
                        and_(
                            MessageAttachment.status == MESSAGE_ATTACHMENT_PROCESSING,
                            MessageAttachment.processing_started_at < stale_before,
                        ),
                    )
                )
                .order_by(MessageAttachment.created_at.asc())
                .limit(_BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
            attachments = list(result.scalars().all())
            for attachment in attachments:
                attachment.status = MESSAGE_ATTACHMENT_PROCESSING
                attachment.attempt_count += 1
                attachment.processing_started_at = now
                attachment.next_attempt_at = None
                attachment.error_code = None
                attachment.updated_at = now
            await db.commit()
            return [attachment.id for attachment in attachments]

    async def _process_attachment(self, attachment_id: uuid.UUID) -> None:
        async with AsyncSessionLocal() as db:
            attachment = await db.get(MessageAttachment, attachment_id)
            if attachment is None or attachment.status != MESSAGE_ATTACHMENT_PROCESSING:
                return

            try:
                downloaded = await download_provider_media(
                    client=self._required_http_client(),
                    source_url=attachment.source_url,
                    declared_content_type=attachment.provider_content_type,
                    max_bytes=settings.mms_storage_max_download_bytes,
                    expected_size_bytes=attachment.provider_size_bytes,
                    expected_sha256=attachment.provider_sha256,
                )
                object_key = _object_key(attachment, downloaded.content_type)
                stored = await asyncio.to_thread(
                    self._required_storage().upload_bytes,
                    object_key=object_key,
                    data=downloaded.data,
                    content_type=downloaded.content_type,
                )
            except MediaDownloadError as exc:
                self._apply_failure(attachment, code=exc.code, retryable=exc.retryable)
            except MMSStorageError:
                self._apply_failure(attachment, code="storage_unavailable", retryable=True)
            except Exception:
                self.logger.exception(
                    "message_attachment_processing_failed",
                    attachment_id=str(attachment.id),
                )
                self._apply_failure(attachment, code="unexpected_error", retryable=True)
            else:
                now = datetime.now(UTC)
                attachment.storage_key = stored.object_key
                attachment.content_type = downloaded.content_type
                attachment.size_bytes = stored.size_bytes
                attachment.sha256 = stored.sha256
                attachment.status = MESSAGE_ATTACHMENT_READY
                attachment.processing_started_at = None
                attachment.next_attempt_at = None
                attachment.processed_at = now
                attachment.error_code = None
                attachment.updated_at = now
                self.logger.info(
                    "message_attachment_ready",
                    attachment_id=str(attachment.id),
                    size_bytes=stored.size_bytes,
                    content_type=downloaded.content_type,
                )
            await db.commit()

    def _apply_failure(
        self,
        attachment: MessageAttachment,
        *,
        code: str,
        retryable: bool,
    ) -> None:
        now = datetime.now(UTC)
        attachment.processing_started_at = None
        attachment.error_code = code
        attachment.updated_at = now
        if retryable and attachment.attempt_count < _MAX_ATTEMPTS:
            attachment.status = MESSAGE_ATTACHMENT_PENDING
            delay_index = min(attachment.attempt_count - 1, len(_RETRY_DELAYS) - 1)
            attachment.next_attempt_at = now + _RETRY_DELAYS[delay_index]
            return

        attachment.status = MESSAGE_ATTACHMENT_FAILED
        attachment.next_attempt_at = None
        attachment.processed_at = now
        self.logger.warning(
            "message_attachment_failed",
            attachment_id=str(attachment.id),
            error_code=code,
            attempts=attachment.attempt_count,
        )

    def _required_storage(self) -> MMSMediaStorage:
        if self._storage is None:
            raise RuntimeError("Message attachment storage is not initialized")
        return self._storage

    def _required_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            raise RuntimeError("Message attachment HTTP client is not initialized")
        return self._http_client


def _object_key(attachment: MessageAttachment, content_type: str) -> str:
    extension = _CONTENT_TYPE_EXTENSIONS.get(content_type, ".bin")
    return (
        f"workspaces/{attachment.workspace_id}/messages/{attachment.message_id}/"
        f"attachments/{attachment.id}{extension}"
    )


_registry = WorkerRegistry(MessageAttachmentWorker)
