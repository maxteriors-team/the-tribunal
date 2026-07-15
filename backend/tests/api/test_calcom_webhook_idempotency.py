"""Tests for Cal.com webhook idempotency / replay rejection.

Cal.com retries webhook deliveries on non-2xx responses (and occasionally
on timeouts even when the server eventually returned 200). The downstream
side effects in :mod:`app.api.webhooks.calcom_handlers` — confirmation
SMS to the contact, owner-notification email — are not idempotent on
their own, so the router claims a Redis-backed dedupe slot
(``SET NX EX 604800``) keyed on ``calcom:webhook:<id|trigger+uid+ts>``
before dispatching to the per-event handlers.

These tests exercise the router-level dedupe in isolation: the handler
dispatch table is monkeypatched to record invocations rather than touch
the database / SMS / email integrations.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.webhooks import calcom as calcom_module
from app.api.webhooks.calcom import (
    _IDEMPOTENCY_KEY_PREFIX,
    _IDEMPOTENCY_TTL_SECONDS,
    _build_idempotency_key,
    _claim_webhook_delivery,
)

# ---------------------------------------------------------------------------
# _build_idempotency_key — payload shape coverage
# ---------------------------------------------------------------------------


def test_build_key_prefers_outer_payload_id() -> None:
    """When Cal.com provides a top-level ``id``, use it verbatim."""
    payload: dict[str, Any] = {
        "id": "delivery-abc-123",
        "trigger": "BOOKING_CREATED",
        "createdAt": "2026-05-15T10:00:00Z",
        "data": {"uid": "booking-uid-xyz"},
    }

    key = _build_idempotency_key(payload)

    assert key == f"{_IDEMPOTENCY_KEY_PREFIX}delivery-abc-123"


def test_build_key_falls_back_to_trigger_uid_timestamp() -> None:
    """No outer id → composite key from trigger + uid + createdAt."""
    payload: dict[str, Any] = {
        "trigger": "BOOKING_CREATED",
        "createdAt": "2026-05-15T10:00:00Z",
        "data": {"uid": "booking-uid-xyz"},
    }

    key = _build_idempotency_key(payload)

    assert key == (
        f"{_IDEMPOTENCY_KEY_PREFIX}BOOKING_CREATED:booking-uid-xyz:"
        "2026-05-15T10:00:00Z"
    )


def test_build_key_supports_calcom_canonical_field_names() -> None:
    """Cal.com docs use ``triggerEvent`` + ``payload`` — accept those too."""
    payload: dict[str, Any] = {
        "triggerEvent": "BOOKING_RESCHEDULED",
        "createdAt": "2026-05-15T11:00:00Z",
        "payload": {"uid": "booking-uid-resched"},
    }

    key = _build_idempotency_key(payload)

    assert key == (
        f"{_IDEMPOTENCY_KEY_PREFIX}BOOKING_RESCHEDULED:"
        "booking-uid-resched:2026-05-15T11:00:00Z"
    )


def test_build_key_handles_flat_meeting_ended_payload() -> None:
    """MEETING_ENDED has booking fields at the top level, not nested."""
    payload: dict[str, Any] = {
        "triggerEvent": "MEETING_ENDED",
        "createdAt": "2026-05-15T12:00:00Z",
        "uid": "booking-uid-meet",
    }

    key = _build_idempotency_key(payload)

    assert key == (
        f"{_IDEMPOTENCY_KEY_PREFIX}MEETING_ENDED:"
        "booking-uid-meet:2026-05-15T12:00:00Z"
    )


def test_build_key_returns_none_when_no_usable_fields() -> None:
    """Garbage payload → None so the caller can fail open with a warning."""
    assert _build_idempotency_key({}) is None
    assert _build_idempotency_key({"trigger": "BOOKING_CREATED"}) is None
    assert _build_idempotency_key({"data": {"uid": "x"}}) is None


def test_ttl_is_seven_days() -> None:
    """Contract: the dedupe window must be 7 days (604800 seconds)."""
    assert _IDEMPOTENCY_TTL_SECONDS == 7 * 24 * 60 * 60
    assert _IDEMPOTENCY_TTL_SECONDS == 604800


# ---------------------------------------------------------------------------
# _claim_webhook_delivery — Redis interaction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_claim_uses_set_nx_ex_with_7d_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    """First delivery → SET NX EX 604800, returns True."""
    redis_client = MagicMock()
    redis_client.set = AsyncMock(return_value=True)
    monkeypatch.setattr(
        calcom_module, "get_redis", AsyncMock(return_value=redis_client)
    )

    claimed = await _claim_webhook_delivery("calcom:webhook:abc", log=MagicMock())

    assert claimed is True
    redis_client.set.assert_awaited_once_with(
        "calcom:webhook:abc", "1", nx=True, ex=604800
    )


@pytest.mark.asyncio
async def test_claim_returns_false_on_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    """redis-py returns ``None`` when NX prevents the write → caller skips."""
    redis_client = MagicMock()
    redis_client.set = AsyncMock(return_value=None)
    monkeypatch.setattr(
        calcom_module, "get_redis", AsyncMock(return_value=redis_client)
    )

    claimed = await _claim_webhook_delivery("calcom:webhook:abc", log=MagicMock())

    assert claimed is False


@pytest.mark.asyncio
async def test_claim_fails_open_on_redis_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Redis outage must NOT silently drop legitimate webhooks."""
    redis_client = MagicMock()
    redis_client.set = AsyncMock(side_effect=ConnectionError("redis down"))
    monkeypatch.setattr(
        calcom_module, "get_redis", AsyncMock(return_value=redis_client)
    )
    log = MagicMock()

    claimed = await _claim_webhook_delivery("calcom:webhook:abc", log=log)

    assert claimed is True
    log.warning.assert_called_once()
    # The warning carries a structured event name and the offending key.
    args, kwargs = log.warning.call_args
    assert args[0] == "calcom_idempotency_redis_unavailable"
    assert kwargs["key"] == "calcom:webhook:abc"


# ---------------------------------------------------------------------------
# Route integration — replay returns 200 without invoking handlers
# ---------------------------------------------------------------------------


def _make_request(payload: dict[str, Any]) -> MagicMock:
    """Build a minimal FastAPI ``Request`` stub."""
    request = MagicMock()
    request.json = AsyncMock(return_value=payload)
    return request


def _install_redis_mock(
    monkeypatch: pytest.MonkeyPatch, set_returns: list[Any]
) -> MagicMock:
    """Patch ``get_redis`` so ``set()`` returns each value in turn."""
    redis_client = MagicMock()
    redis_client.set = AsyncMock(side_effect=set_returns)
    monkeypatch.setattr(
        calcom_module, "get_redis", AsyncMock(return_value=redis_client)
    )
    return redis_client


def _disable_signature_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        calcom_module, "verify_calcom_webhook", AsyncMock(return_value=True)
    )


@pytest.mark.asyncio
async def test_first_delivery_invokes_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    _disable_signature_check(monkeypatch)
    _install_redis_mock(monkeypatch, set_returns=[True])
    handler = AsyncMock()
    monkeypatch.setitem(calcom_module._EVENT_DISPATCH, "BOOKING_CREATED", handler)

    payload = {
        "trigger": "BOOKING_CREATED",
        "createdAt": "2026-05-15T10:00:00Z",
        "data": {"uid": "booking-uid-1"},
    }
    response = await calcom_module.calcom_booking_webhook(_make_request(payload))

    assert response == {"status": "ok"}
    handler.assert_awaited_once()
    # First positional arg to the handler is the booking ``data`` dict.
    handler_data = handler.await_args.args[0]
    assert handler_data == {"uid": "booking-uid-1"}


@pytest.mark.asyncio
async def test_replay_is_rejected_without_invoking_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same payload delivered twice must only fire the handler once.

    The second delivery sees a populated Redis key and short-circuits with
    ``{"status": "ok", "deduped": "true"}`` — Cal.com gets a 200 so it
    stops retrying, but the SMS/email side effects do not run again.
    """
    _disable_signature_check(monkeypatch)
    # First call → key set (True). Second call → NX collision (None).
    _install_redis_mock(monkeypatch, set_returns=[True, None])
    handler = AsyncMock()
    monkeypatch.setitem(calcom_module._EVENT_DISPATCH, "BOOKING_CREATED", handler)

    payload = {
        "trigger": "BOOKING_CREATED",
        "createdAt": "2026-05-15T10:00:00Z",
        "data": {"uid": "booking-uid-replay"},
    }

    first = await calcom_module.calcom_booking_webhook(_make_request(payload))
    second = await calcom_module.calcom_booking_webhook(_make_request(payload))

    assert first == {"status": "ok"}
    assert second == {"status": "ok", "deduped": "true"}
    handler.assert_awaited_once()  # NOT twice.


@pytest.mark.asyncio
async def test_distinct_events_for_same_booking_are_not_deduped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BOOKING_CREATED then BOOKING_RESCHEDULED for the same uid must both fire.

    The composite key includes ``trigger`` and ``createdAt``, so distinct
    Cal.com events for the same booking get distinct dedupe slots.
    """
    _disable_signature_check(monkeypatch)
    redis_client = _install_redis_mock(monkeypatch, set_returns=[True, True])
    created_handler = AsyncMock()
    rescheduled_handler = AsyncMock()
    monkeypatch.setitem(
        calcom_module._EVENT_DISPATCH, "BOOKING_CREATED", created_handler
    )
    monkeypatch.setitem(
        calcom_module._EVENT_DISPATCH, "BOOKING_RESCHEDULED", rescheduled_handler
    )

    await calcom_module.calcom_booking_webhook(
        _make_request(
            {
                "trigger": "BOOKING_CREATED",
                "createdAt": "2026-05-15T10:00:00Z",
                "data": {"uid": "booking-uid-evolve"},
            }
        )
    )
    await calcom_module.calcom_booking_webhook(
        _make_request(
            {
                "trigger": "BOOKING_RESCHEDULED",
                "createdAt": "2026-05-15T10:05:00Z",
                "data": {"uid": "booking-uid-evolve"},
            }
        )
    )

    created_handler.assert_awaited_once()
    rescheduled_handler.assert_awaited_once()
    # Each Redis claim used a distinct key.
    keys_used = [call.args[0] for call in redis_client.set.await_args_list]
    assert len(keys_used) == 2
    assert keys_used[0] != keys_used[1]


@pytest.mark.asyncio
async def test_redis_outage_falls_open_and_processes_webhook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If Redis is unreachable the handler still runs (per-row guards remain)."""
    _disable_signature_check(monkeypatch)
    redis_client = MagicMock()
    redis_client.set = AsyncMock(side_effect=ConnectionError("redis down"))
    monkeypatch.setattr(
        calcom_module, "get_redis", AsyncMock(return_value=redis_client)
    )
    handler = AsyncMock()
    monkeypatch.setitem(calcom_module._EVENT_DISPATCH, "BOOKING_CREATED", handler)

    response = await calcom_module.calcom_booking_webhook(
        _make_request(
            {
                "trigger": "BOOKING_CREATED",
                "createdAt": "2026-05-15T10:00:00Z",
                "data": {"uid": "booking-uid-failopen"},
            }
        )
    )

    assert response == {"status": "ok"}
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_unhandled_trigger_still_claims_dedupe_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown trigger types must still consume the dedupe slot.

    Otherwise Cal.com's retry of an unsupported event would keep retrying
    forever — we want to return 200 once and stay quiet.
    """
    _disable_signature_check(monkeypatch)
    redis_client = _install_redis_mock(monkeypatch, set_returns=[True])

    response = await calcom_module.calcom_booking_webhook(
        _make_request(
            {
                "trigger": "BOOKING_NO_SHOW_UPDATED",
                "createdAt": "2026-05-15T10:00:00Z",
                "data": {"uid": "booking-uid-unhandled"},
            }
        )
    )

    assert response == {"status": "ok"}
    redis_client.set.assert_awaited_once()
