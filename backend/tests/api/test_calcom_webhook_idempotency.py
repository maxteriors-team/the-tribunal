"""Tests for Cal.com webhook idempotency / replay rejection.

The router runs two independent replay defences, in this order:

1. **Durable signature ledger** (Postgres, :mod:`app.services.webhook_replay`).
   Cal.com's HMAC authenticates the body, not the delivery, so a captured
   ``(body, x-cal-signature-256)`` pair verifies forever. The router claims the
   signature before touching anything; a second sighting is a 409 and a ledger
   outage is a 503 (fail closed).
2. **Redis delivery dedupe** (``SET NX EX 604800`` on
   ``calcom:webhook:<id|trigger+uid+ts>``). Cal.com retries deliveries on
   non-2xx responses and occasionally on timeouts, and the downstream side
   effects in :mod:`app.api.webhooks.calcom_handlers` — confirmation SMS, owner
   email — are not idempotent on their own. A retried delivery gets a friendly
   200 + ``deduped``; an unreachable Redis is a 503 (also fail closed).

These tests exercise both layers in isolation: the handler dispatch table is
monkeypatched to record invocations rather than touch the database / SMS /
email integrations, and each layer is stubbed out while the other is under
test.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.webhooks import calcom as calcom_module
from app.api.webhooks.calcom import (
    _IDEMPOTENCY_KEY_PREFIX,
    _IDEMPOTENCY_TTL_SECONDS,
    _build_idempotency_key,
    _claim_webhook_delivery,
)
from app.services.webhook_replay import SignatureClaim, SignatureClaimOutcome

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

    assert key == (f"{_IDEMPOTENCY_KEY_PREFIX}BOOKING_CREATED:booking-uid-xyz:2026-05-15T10:00:00Z")


def test_build_key_supports_calcom_canonical_field_names() -> None:
    """Cal.com docs use ``triggerEvent`` + ``payload`` — accept those too."""
    payload: dict[str, Any] = {
        "triggerEvent": "BOOKING_RESCHEDULED",
        "createdAt": "2026-05-15T11:00:00Z",
        "payload": {"uid": "booking-uid-resched"},
    }

    key = _build_idempotency_key(payload)

    assert key == (
        f"{_IDEMPOTENCY_KEY_PREFIX}BOOKING_RESCHEDULED:booking-uid-resched:2026-05-15T11:00:00Z"
    )


def test_build_key_handles_flat_meeting_ended_payload() -> None:
    """MEETING_ENDED has booking fields at the top level, not nested."""
    payload: dict[str, Any] = {
        "triggerEvent": "MEETING_ENDED",
        "createdAt": "2026-05-15T12:00:00Z",
        "uid": "booking-uid-meet",
    }

    key = _build_idempotency_key(payload)

    assert key == (f"{_IDEMPOTENCY_KEY_PREFIX}MEETING_ENDED:booking-uid-meet:2026-05-15T12:00:00Z")


def test_build_key_returns_none_when_no_usable_fields() -> None:
    """Garbage payload → None so the caller can reject it with a 400."""
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
    monkeypatch.setattr(calcom_module, "get_redis", AsyncMock(return_value=redis_client))

    claimed = await _claim_webhook_delivery("calcom:webhook:abc", log=MagicMock())

    assert claimed is True
    redis_client.set.assert_awaited_once_with("calcom:webhook:abc", "1", nx=True, ex=604800)


@pytest.mark.asyncio
async def test_claim_returns_false_on_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    """redis-py returns ``None`` when NX prevents the write → caller skips."""
    redis_client = MagicMock()
    redis_client.set = AsyncMock(return_value=None)
    monkeypatch.setattr(calcom_module, "get_redis", AsyncMock(return_value=redis_client))

    claimed = await _claim_webhook_delivery("calcom:webhook:abc", log=MagicMock())

    assert claimed is False


@pytest.mark.asyncio
async def test_claim_fails_closed_on_redis_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Redis outage must NOT let an un-deduped delivery through.

    Fail closed with 503: Cal.com retries, and a retry that we *can* dedupe is
    strictly better than a delivery that re-fires confirmation SMS and owner
    email. (The shared helper reports the outage as ``claimed=True`` so each
    caller picks its own policy; this route picks refusal.)
    """
    redis_client = MagicMock()
    redis_client.set = AsyncMock(side_effect=ConnectionError("redis down"))
    monkeypatch.setattr(calcom_module, "get_redis", AsyncMock(return_value=redis_client))
    log = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        await _claim_webhook_delivery("calcom:webhook:abc", log=log)

    assert exc_info.value.status_code == 503
    log.warning.assert_called_once()
    # The warning carries a structured event name and the offending key.
    args, kwargs = log.warning.call_args
    assert args[0] == "calcom_idempotency_redis_unavailable"
    assert kwargs["key"] == "calcom:webhook:abc"


# ---------------------------------------------------------------------------
# Route integration — Redis dedupe layer
# ---------------------------------------------------------------------------


def _make_request(payload: dict[str, Any], *, signature: str = "sig-default") -> MagicMock:
    """Build a minimal FastAPI ``Request`` stub.

    ``headers`` is a real dict so ``_reject_replayed_signature`` reads the same
    verbatim value production would hand to the ledger.
    """
    request = MagicMock()
    request.json = AsyncMock(return_value=payload)
    request.headers = {"x-cal-signature-256": signature}
    return request


def _install_redis_mock(monkeypatch: pytest.MonkeyPatch, set_returns: list[Any]) -> MagicMock:
    """Patch ``get_redis`` so ``set()`` returns each value in turn."""
    redis_client = MagicMock()
    redis_client.set = AsyncMock(side_effect=set_returns)
    monkeypatch.setattr(calcom_module, "get_redis", AsyncMock(return_value=redis_client))
    return redis_client


def _disable_signature_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(calcom_module, "verify_calcom_webhook", AsyncMock(return_value=True))


def _disable_replay_ledger(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Stub the Postgres signature ledger into always saying "first sighting".

    Required by every test that targets the *Redis* dedupe layer: the ledger
    runs first, is backed by a real database, and would otherwise (a) write
    rows into the developer's DB and (b) 409 the second delivery before Redis
    is ever consulted — which would silently gut the layer under test.
    """
    claim = AsyncMock(return_value=SignatureClaim(outcome=SignatureClaimOutcome.CLAIMED))
    monkeypatch.setattr(calcom_module, "claim_webhook_signature", claim)
    return claim


@pytest.mark.asyncio
async def test_first_delivery_invokes_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    _disable_signature_check(monkeypatch)
    _disable_replay_ledger(monkeypatch)
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

    This targets the REDIS layer, so the durable signature ledger is stubbed
    out: it runs first and would 409 the second delivery before Redis is even
    consulted, leaving the behaviour under test unexercised.
    """
    _disable_signature_check(monkeypatch)
    _disable_replay_ledger(monkeypatch)
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
    _disable_replay_ledger(monkeypatch)
    redis_client = _install_redis_mock(monkeypatch, set_returns=[True, True])
    created_handler = AsyncMock()
    rescheduled_handler = AsyncMock()
    monkeypatch.setitem(calcom_module._EVENT_DISPATCH, "BOOKING_CREATED", created_handler)
    monkeypatch.setitem(calcom_module._EVENT_DISPATCH, "BOOKING_RESCHEDULED", rescheduled_handler)

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
async def test_redis_outage_fails_closed_with_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If Redis is unreachable we refuse the delivery instead of guessing.

    Previously this failed open "because the per-row guards remain" — but those
    guards only cover BOOKING_CREATED. 503 makes Cal.com retry the delivery
    once we can actually dedupe it.
    """
    _disable_signature_check(monkeypatch)
    _disable_replay_ledger(monkeypatch)
    redis_client = MagicMock()
    redis_client.set = AsyncMock(side_effect=ConnectionError("redis down"))
    monkeypatch.setattr(calcom_module, "get_redis", AsyncMock(return_value=redis_client))
    handler = AsyncMock()
    monkeypatch.setitem(calcom_module._EVENT_DISPATCH, "BOOKING_CREATED", handler)

    with pytest.raises(HTTPException) as exc_info:
        await calcom_module.calcom_booking_webhook(
            _make_request(
                {
                    "trigger": "BOOKING_CREATED",
                    "createdAt": "2026-05-15T10:00:00Z",
                    "data": {"uid": "booking-uid-failclosed"},
                }
            )
        )

    assert exc_info.value.status_code == 503
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_unhandled_trigger_still_claims_dedupe_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown trigger types must still consume the dedupe slot.

    Otherwise Cal.com's retry of an unsupported event would keep retrying
    forever — we want to return 200 once and stay quiet.
    """
    _disable_signature_check(monkeypatch)
    _disable_replay_ledger(monkeypatch)
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


# ---------------------------------------------------------------------------
# Route integration — durable signature ledger (replay rejection proper)
# ---------------------------------------------------------------------------


def _install_ledger_mock(
    monkeypatch: pytest.MonkeyPatch, outcomes: list[SignatureClaimOutcome]
) -> AsyncMock:
    """Patch ``claim_webhook_signature`` to return each outcome in turn."""
    claim = AsyncMock(side_effect=[SignatureClaim(outcome=outcome) for outcome in outcomes])
    monkeypatch.setattr(calcom_module, "claim_webhook_signature", claim)
    return claim


_LEDGER_PAYLOAD: dict[str, Any] = {
    "trigger": "BOOKING_CREATED",
    "createdAt": "2026-05-15T10:00:00Z",
    "data": {"uid": "booking-uid-ledger"},
}


@pytest.mark.asyncio
async def test_genuine_first_delivery_claims_signature_and_dispatches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First sighting of a signature → claimed, then normal dispatch."""
    _disable_signature_check(monkeypatch)
    claim = _install_ledger_mock(monkeypatch, [SignatureClaimOutcome.CLAIMED])
    _install_redis_mock(monkeypatch, set_returns=[True])
    handler = AsyncMock()
    monkeypatch.setitem(calcom_module._EVENT_DISPATCH, "BOOKING_CREATED", handler)

    response = await calcom_module.calcom_booking_webhook(
        _make_request(_LEDGER_PAYLOAD, signature="a" * 64)
    )

    assert response == {"status": "ok"}
    handler.assert_awaited_once()
    # The ledger gets the provider slug and the VERBATIM header value.
    provider, signature = claim.await_args.args
    assert provider == "calcom"
    assert signature == "a" * 64


@pytest.mark.asyncio
async def test_replayed_signature_is_rejected_with_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Second delivery of the same signature → 409, handler never re-runs.

    Cal.com's HMAC covers the body only, so a captured ``(body, signature)``
    pair stays valid forever; the ledger is what makes the *second* use of it
    fail. Redis is stubbed to claim both slots so the 409 can only come from
    the ledger.
    """
    _disable_signature_check(monkeypatch)
    _install_ledger_mock(
        monkeypatch,
        [SignatureClaimOutcome.CLAIMED, SignatureClaimOutcome.REPLAY],
    )
    _install_redis_mock(monkeypatch, set_returns=[True, True])
    handler = AsyncMock()
    monkeypatch.setitem(calcom_module._EVENT_DISPATCH, "BOOKING_CREATED", handler)

    first = await calcom_module.calcom_booking_webhook(
        _make_request(_LEDGER_PAYLOAD, signature="b" * 64)
    )

    with pytest.raises(HTTPException) as exc_info:
        await calcom_module.calcom_booking_webhook(
            _make_request(_LEDGER_PAYLOAD, signature="b" * 64)
        )

    assert first == {"status": "ok"}
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Duplicate Cal.com webhook signature"
    handler.assert_awaited_once()  # NOT twice.


@pytest.mark.asyncio
async def test_ledger_outage_returns_503_instead_of_passing_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreachable ledger must refuse the delivery, not wave it through.

    Fail closed: a delivery we cannot dedupe is exactly what the ledger exists
    to stop, and 503 makes Cal.com retry once Postgres is back.
    """
    _disable_signature_check(monkeypatch)
    _install_ledger_mock(monkeypatch, [SignatureClaimOutcome.LEDGER_UNAVAILABLE])
    redis_client = _install_redis_mock(monkeypatch, set_returns=[True])
    handler = AsyncMock()
    monkeypatch.setitem(calcom_module._EVENT_DISPATCH, "BOOKING_CREATED", handler)

    with pytest.raises(HTTPException) as exc_info:
        await calcom_module.calcom_booking_webhook(
            _make_request(_LEDGER_PAYLOAD, signature="c" * 64)
        )

    assert exc_info.value.status_code == 503
    handler.assert_not_awaited()
    # Refused before any downstream work, including the Redis claim.
    redis_client.set.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_idempotency_fields_returns_400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No usable delivery identity → 400 rather than an un-deduped dispatch.

    ``_build_idempotency_key`` returns ``None`` only for payloads real Cal.com
    never sends. Dispatching one anyway would re-fire side effects on every
    retry, since there is no key to claim.
    """
    _disable_signature_check(monkeypatch)
    _disable_replay_ledger(monkeypatch)
    redis_client = _install_redis_mock(monkeypatch, set_returns=[True])
    handler = AsyncMock()
    monkeypatch.setitem(calcom_module._EVENT_DISPATCH, "BOOKING_CREATED", handler)

    with pytest.raises(HTTPException) as exc_info:
        await calcom_module.calcom_booking_webhook(
            # No ``id``, no ``uid`` — nothing to key a dedupe slot on.
            _make_request({"trigger": "BOOKING_CREATED"}, signature="d" * 64)
        )

    assert exc_info.value.status_code == 400
    handler.assert_not_awaited()
    redis_client.set.assert_not_awaited()
