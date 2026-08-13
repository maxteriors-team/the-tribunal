"""Tests for shared backend idempotency primitives."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.conversation import MessageStatus
from app.services.idempotency import (
    DEFAULT_IDEMPOTENCY_HEADER,
    DEFAULT_WEBHOOK_IDEMPOTENCY_TTL_SECONDS,
    OUTBOUND_IDEMPOTENCY_NAMESPACE,
    claim_redis_idempotency_key,
    derive_document_send_key,
    derive_outbound_key,
    derive_webhook_delivery_key,
    derive_worker_retry_key,
    encode_client_state,
    idempotency_headers,
    is_message_send_applied,
    redis_idempotency_key_exists,
    set_redis_idempotency_key,
    webhook_key_prefix,
)


def test_outbound_key_uses_legacy_namespace_and_is_stable() -> None:
    key = derive_outbound_key("reminder", 123, 60)

    assert key == uuid.uuid5(OUTBOUND_IDEMPOTENCY_NAMESPACE, "reminder:123:60")
    assert key == derive_outbound_key("reminder", "123", "60")
    assert key.version == 5


def test_distinct_outbound_scopes_do_not_collide() -> None:
    assert derive_outbound_key("reminder", 1) != derive_outbound_key("nudge_sms", 1)


def test_document_send_key_changes_with_the_revision() -> None:
    """An edited document must not reuse the key its original send burned.

    Resend rejects a replayed key whose body changed (409
    ``invalid_idempotent_request``) rather than de-duplicating it, so a key that
    ignores the revision makes "edit, then send again" undeliverable for the
    whole idempotency window.
    """
    first = derive_document_send_key("quote_send", 7, "2026-08-10T13:34:21", "a@example.com")
    edited = derive_document_send_key("quote_send", 7, "2026-08-10T13:35:09", "a@example.com")

    assert first != edited


def test_document_send_key_is_stable_for_an_unchanged_document() -> None:
    """Double-clicking Send must still collapse into one email."""
    args = ("quote_send", 7, "2026-08-10T13:34:21", "a@example.com")

    assert derive_document_send_key(*args) == derive_document_send_key(*args)
    # Distinct recipients of the same revision are distinct sends.
    assert derive_document_send_key(*args) != derive_document_send_key(
        "quote_send", 7, "2026-08-10T13:34:21", "b@example.com"
    )


def test_provider_application_helpers() -> None:
    key = uuid.uuid4()

    assert idempotency_headers(key) == {DEFAULT_IDEMPOTENCY_HEADER: str(key)}
    assert idempotency_headers(None) == {}
    assert encode_client_state(key)


def test_worker_retry_key_is_stable_text() -> None:
    assert derive_worker_retry_key("notify", uuid.UUID(int=1)) == (
        "notify:00000000-0000-0000-0000-000000000001"
    )
    assert derive_worker_retry_key("transcript_batch") == "transcript_batch"


def test_webhook_key_derivation_and_missing_fields() -> None:
    assert webhook_key_prefix("Resend") == "resend:webhook:"
    assert derive_webhook_delivery_key("resend", "email.delivered", "uid", "ts") == (
        "resend:webhook:email.delivered:uid:ts"
    )
    assert derive_webhook_delivery_key("resend", "email.delivered", None) is None
    assert derive_webhook_delivery_key("resend", "email.delivered", "") is None


@pytest.mark.parametrize(
    ("status", "applied"),
    [
        (MessageStatus.QUEUED, False),
        (MessageStatus.SENT, True),
        (MessageStatus.FAILED, True),
        ("queued", False),
        ("sent", True),
    ],
)
def test_message_apply_state(status: object, applied: bool) -> None:
    message = SimpleNamespace(status=status)

    assert is_message_send_applied(message) is applied  # type: ignore[arg-type]


async def test_redis_claim_uses_set_nx_ex() -> None:
    redis_client = MagicMock()
    redis_client.set = AsyncMock(return_value=True)
    redis_getter = AsyncMock(return_value=redis_client)

    claim = await claim_redis_idempotency_key(
        "resend:webhook:evt_1",
        log=MagicMock(),
        redis_getter=redis_getter,
    )

    assert claim.claimed is True
    assert claim.reason == "claimed"
    redis_client.set.assert_awaited_once_with(
        "resend:webhook:evt_1",
        "1",
        nx=True,
        ex=DEFAULT_WEBHOOK_IDEMPOTENCY_TTL_SECONDS,
    )


async def test_redis_claim_returns_duplicate_on_nx_collision() -> None:
    redis_client = MagicMock()
    redis_client.set = AsyncMock(return_value=None)

    claim = await claim_redis_idempotency_key(
        "resend:webhook:evt_1",
        log=MagicMock(),
        redis_getter=AsyncMock(return_value=redis_client),
    )

    assert claim.claimed is False
    assert claim.reason == "duplicate"


async def test_redis_claim_fails_open_on_redis_error() -> None:
    redis_client = MagicMock()
    redis_client.set = AsyncMock(side_effect=ConnectionError("redis down"))
    log = MagicMock()

    claim = await claim_redis_idempotency_key(
        "resend:webhook:evt_1",
        log=log,
        redis_getter=AsyncMock(return_value=redis_client),
        failure_event="resend_idempotency_redis_unavailable",
    )

    assert claim.claimed is True
    assert claim.reason == "redis_unavailable"
    log.warning.assert_called_once_with(
        "resend_idempotency_redis_unavailable",
        key="resend:webhook:evt_1",
        error="redis down",
    )


async def test_redis_delivery_marker_reads_and_sets_with_ttl() -> None:
    redis_client = MagicMock()
    redis_client.exists = AsyncMock(return_value=1)
    redis_client.set = AsyncMock(return_value=True)
    getter = AsyncMock(return_value=redis_client)
    log = MagicMock()

    assert await redis_idempotency_key_exists("job:recipient:7", log=log, redis_getter=getter)
    await set_redis_idempotency_key(
        "job:recipient:7", ttl_seconds=3600, log=log, redis_getter=getter
    )

    redis_client.exists.assert_awaited_once_with("job:recipient:7")
    redis_client.set.assert_awaited_once_with("job:recipient:7", "1", ex=3600)
