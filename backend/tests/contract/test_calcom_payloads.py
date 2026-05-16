"""Contract tests for Cal.com webhook payloads.

For each fixture under ``tests/contract/fixtures/calcom/``:

1. Serialize the fixture to bytes.
2. Sign the body with HMAC-SHA256 using a test secret and patch
   ``settings.calcom_webhook_secret`` to match.
3. POST to ``/webhooks/calcom/booking`` under a FastAPI test app.
4. Assert ``200 {"status": "ok"}`` and that the correct per-trigger
   handler in ``calcom._EVENT_DISPATCH`` was invoked with the parsed
   ``data`` block from the fixture.

The router's Redis-backed idempotency layer is mocked to always claim
the slot (first delivery) so dispatch can run. Replay behaviour is
covered exhaustively in ``tests/api/test_calcom_webhook_idempotency.py``.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.webhooks import calcom as calcom_router_module
from app.api.webhooks.calcom import router as calcom_router
from app.core.config import settings as app_settings
from tests.contract._helpers import (
    CALCOM_TEST_SIGNING_KEY,
    build_app,
    encode_body,
    http_client,
    sign_calcom,
)
from tests.contract.fixtures import load_fixture

# --------------------------------------------------------------------------- #
# Plumbing
# --------------------------------------------------------------------------- #


@pytest.fixture
def patched_calcom_handlers(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    """Replace each ``_EVENT_DISPATCH`` entry with an ``AsyncMock`` recorder."""
    handlers = {
        "BOOKING_CREATED": AsyncMock(),
        "BOOKING_RESCHEDULED": AsyncMock(),
        "BOOKING_CANCELLED": AsyncMock(),
        "MEETING_ENDED": AsyncMock(),
    }
    for trigger, mock in handlers.items():
        monkeypatch.setitem(calcom_router_module._EVENT_DISPATCH, trigger, mock)
    return handlers


@pytest.fixture
def stub_redis_claims_slot(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Make ``get_redis().set(..., nx=True, ...)`` return True (slot claimed).

    Each test gets a fresh Redis stub so the dedupe layer never blocks a
    legitimate first delivery in the contract suite.
    """
    redis_client = MagicMock()
    redis_client.set = AsyncMock(return_value=True)
    monkeypatch.setattr(calcom_router_module, "get_redis", AsyncMock(return_value=redis_client))
    return redis_client


async def _post_signed(fixture: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Sign *fixture* with the test secret and POST to /webhooks/calcom/booking."""
    app = build_app(calcom_router, prefix="/webhooks/calcom")
    body = encode_body(fixture)
    headers = {"content-type": "application/json", **sign_calcom(body)}

    with patch.object(app_settings, "calcom_webhook_secret", CALCOM_TEST_SIGNING_KEY):
        async with http_client(app) as client:
            response = await client.post("/webhooks/calcom/booking", content=body, headers=headers)

    return response.status_code, response.json()


# --------------------------------------------------------------------------- #
# Happy-path dispatch
# --------------------------------------------------------------------------- #


async def test_booking_created_dispatches_to_handler(
    patched_calcom_handlers: dict[str, AsyncMock],
    stub_redis_claims_slot: MagicMock,
) -> None:
    fixture = load_fixture("calcom", "booking_created.json")
    assert fixture["trigger"] == "BOOKING_CREATED"

    status, body = await _post_signed(fixture)

    assert status == 200
    assert body == {"status": "ok"}

    handler = patched_calcom_handlers["BOOKING_CREATED"]
    handler.assert_awaited_once()
    # First positional arg is the ``data`` block (NOT the outer payload).
    data = handler.await_args.args[0]
    assert data["uid"] == "calcom-contract-booking-created-001"
    assert data["status"] == "ACCEPTED"
    assert data["attendees"][0]["email"] == "client@example.com"
    assert data["attendees"][0]["phoneNumber"] == "+14155552671"

    # The router must have claimed exactly one Redis dedupe slot.
    stub_redis_claims_slot.set.assert_awaited_once()
    redis_key, redis_value = stub_redis_claims_slot.set.await_args.args
    assert redis_key.startswith("calcom:webhook:")
    assert redis_value == "1"

    # Other event handlers must remain idle.
    for trigger in ("BOOKING_RESCHEDULED", "BOOKING_CANCELLED", "MEETING_ENDED"):
        patched_calcom_handlers[trigger].assert_not_called()


async def test_booking_rescheduled_dispatches_with_reschedule_uid(
    patched_calcom_handlers: dict[str, AsyncMock],
    stub_redis_claims_slot: MagicMock,
) -> None:
    fixture = load_fixture("calcom", "booking_rescheduled.json")
    assert fixture["trigger"] == "BOOKING_RESCHEDULED"

    status, body = await _post_signed(fixture)

    assert status == 200
    assert body == {"status": "ok"}

    handler = patched_calcom_handlers["BOOKING_RESCHEDULED"]
    handler.assert_awaited_once()
    data = handler.await_args.args[0]
    # ``rescheduleUid`` is the bridge between old → new booking the handler uses.
    assert data["rescheduleUid"] == "calcom-contract-booking-created-001"
    assert data["uid"] == "calcom-contract-booking-resched-001"
    assert data["startTime"] == "2026-06-02T16:00:00.000Z"


async def test_booking_cancelled_dispatches_with_cancellation_metadata(
    patched_calcom_handlers: dict[str, AsyncMock],
    stub_redis_claims_slot: MagicMock,
) -> None:
    fixture = load_fixture("calcom", "booking_cancelled.json")
    assert fixture["trigger"] == "BOOKING_CANCELLED"

    status, body = await _post_signed(fixture)

    assert status == 200
    assert body == {"status": "ok"}

    handler = patched_calcom_handlers["BOOKING_CANCELLED"]
    handler.assert_awaited_once()
    data = handler.await_args.args[0]
    assert data["status"] == "CANCELLED"
    assert data["cancellationReason"] == "Need to reschedule"
    assert data["cancelledBy"] == "client@example.com"


async def test_meeting_ended_dispatches_with_no_show_flags(
    patched_calcom_handlers: dict[str, AsyncMock],
    stub_redis_claims_slot: MagicMock,
) -> None:
    """``MEETING_ENDED`` carries ``noShowHost`` + per-attendee ``noShow`` flags."""
    fixture = load_fixture("calcom", "meeting_ended.json")
    assert fixture["trigger"] == "MEETING_ENDED"

    status, body = await _post_signed(fixture)

    assert status == 200
    assert body == {"status": "ok"}

    handler = patched_calcom_handlers["MEETING_ENDED"]
    handler.assert_awaited_once()
    data = handler.await_args.args[0]
    assert data["noShowHost"] is False
    assert data["attendees"][0]["noShow"] is False
    assert data["uid"] == "calcom-contract-meeting-ended-001"


# --------------------------------------------------------------------------- #
# Signature stack — negative cases
# --------------------------------------------------------------------------- #


async def test_missing_calcom_signature_returns_403(
    patched_calcom_handlers: dict[str, AsyncMock],
    stub_redis_claims_slot: MagicMock,
) -> None:
    """No ``x-cal-signature-256`` header → 403, no dispatch."""
    fixture = load_fixture("calcom", "booking_created.json")
    body = encode_body(fixture)
    app = build_app(calcom_router, prefix="/webhooks/calcom")

    with patch.object(app_settings, "calcom_webhook_secret", CALCOM_TEST_SIGNING_KEY):
        async with http_client(app) as client:
            response = await client.post(
                "/webhooks/calcom/booking",
                content=body,
                headers={"content-type": "application/json"},
            )

    assert response.status_code == 403
    for handler in patched_calcom_handlers.values():
        handler.assert_not_called()


async def test_tampered_calcom_body_is_rejected(
    patched_calcom_handlers: dict[str, AsyncMock],
    stub_redis_claims_slot: MagicMock,
) -> None:
    """Body changed after signing → HMAC fails verification → 403."""
    fixture = load_fixture("calcom", "booking_created.json")
    body_signed = encode_body(fixture)
    tampered = json.loads(body_signed.decode())
    tampered["data"]["attendees"][0]["email"] = "attacker@evil.example"
    body_sent = encode_body(tampered)

    headers = {"content-type": "application/json", **sign_calcom(body_signed)}
    app = build_app(calcom_router, prefix="/webhooks/calcom")

    with patch.object(app_settings, "calcom_webhook_secret", CALCOM_TEST_SIGNING_KEY):
        async with http_client(app) as client:
            response = await client.post(
                "/webhooks/calcom/booking", content=body_sent, headers=headers
            )

    assert response.status_code == 403
    for handler in patched_calcom_handlers.values():
        handler.assert_not_called()
