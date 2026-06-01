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
    derive_outbound_key,
    derive_webhook_delivery_key,
    derive_worker_retry_key,
    encode_client_state,
    idempotency_headers,
    is_message_send_applied,
    webhook_key_prefix,
)


def test_outbound_key_uses_legacy_namespace_and_is_stable() -> None:
    key = derive_outbound_key("reminder", 123, 60)

    assert key == uuid.uuid5(OUTBOUND_IDEMPOTENCY_NAMESPACE, "reminder:123:60")
    assert key == derive_outbound_key("reminder", "123", "60")
    assert key.version == 5


def test_distinct_outbound_scopes_do_not_collide() -> None:
    assert derive_outbound_key("reminder", 1) != derive_outbound_key("nudge_sms", 1)


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
    assert webhook_key_prefix("CalCom") == "calcom:webhook:"
    assert derive_webhook_delivery_key("calcom", "BOOKING_CREATED", "uid", "ts") == (
        "calcom:webhook:BOOKING_CREATED:uid:ts"
    )
    assert derive_webhook_delivery_key("calcom", "BOOKING_CREATED", None) is None
    assert derive_webhook_delivery_key("calcom", "BOOKING_CREATED", "") is None


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
        "calcom:webhook:evt_1",
        log=MagicMock(),
        redis_getter=redis_getter,
    )

    assert claim.claimed is True
    assert claim.reason == "claimed"
    redis_client.set.assert_awaited_once_with(
        "calcom:webhook:evt_1",
        "1",
        nx=True,
        ex=DEFAULT_WEBHOOK_IDEMPOTENCY_TTL_SECONDS,
    )


async def test_redis_claim_returns_duplicate_on_nx_collision() -> None:
    redis_client = MagicMock()
    redis_client.set = AsyncMock(return_value=None)

    claim = await claim_redis_idempotency_key(
        "calcom:webhook:evt_1",
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
        "calcom:webhook:evt_1",
        log=log,
        redis_getter=AsyncMock(return_value=redis_client),
        failure_event="calcom_idempotency_redis_unavailable",
    )

    assert claim.claimed is True
    assert claim.reason == "redis_unavailable"
    log.warning.assert_called_once_with(
        "calcom_idempotency_redis_unavailable",
        key="calcom:webhook:evt_1",
        error="redis down",
    )
