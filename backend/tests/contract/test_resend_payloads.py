"""Contract tests for Resend webhook payloads.

For each fixture under ``tests/contract/fixtures/resend/``:

1. Serialize the fixture to bytes.
2. Sign the body with a fresh Svix ``whsec_`` secret and patch
   ``settings.resend_webhook_secret`` to match.
3. POST to ``/webhooks/resend`` under a FastAPI test app.
4. Assert ``200 {"status": "ok"}`` and that ``handle_event`` was invoked
   with the verified event plus the ``svix-id`` as the idempotency key.

The downstream event processing — campaign counters, message status
transitions, ``EmailEvent`` row creation — is covered in
``tests/api/test_resend_handlers.py``. Here we pin the wire-format
contract for the four event types we care about plus the Svix
signature stack.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.api.webhooks import resend as resend_router_module
from app.api.webhooks.resend import router as resend_router
from app.core.config import settings as app_settings
from tests.contract._helpers import (
    ResendSigner,
    build_app,
    encode_body,
    http_client,
)
from tests.contract.fixtures import load_fixture

# --------------------------------------------------------------------------- #
# Plumbing
# --------------------------------------------------------------------------- #


@pytest.fixture
def stub_handle_event(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Replace ``resend_handlers.handle_event`` with an ``AsyncMock`` recorder."""
    mock = AsyncMock(return_value=None)
    monkeypatch.setattr(resend_router_module, "handle_event", mock)
    return mock


async def _post_signed(
    *, fixture: dict[str, Any], signer: ResendSigner
) -> tuple[int, dict[str, Any]]:
    """Sign *fixture* with *signer* and POST to /webhooks/resend."""
    app = build_app(resend_router, prefix="/webhooks/resend")
    body = encode_body(fixture)
    headers = {"content-type": "application/json", **signer.sign(body)}

    with patch.object(app_settings, "resend_webhook_secret", signer.secret):
        async with http_client(app) as client:
            response = await client.post("/webhooks/resend", content=body, headers=headers)

    return response.status_code, response.json()


def _assert_handle_event_called_with(
    handle_event: AsyncMock, *, expected_type: str, expected_email_id: str, msg_id: str
) -> dict[str, Any]:
    """Common assertion: ``handle_event(db, event, log, provider_event_id=svix_id)``."""
    handle_event.assert_awaited_once()
    call = handle_event.await_args
    # call.args == (db, event, log)
    event = call.args[1]
    assert isinstance(event, dict)
    assert event["type"] == expected_type
    assert event["data"]["email_id"] == expected_email_id
    # svix-id flows through as ``provider_event_id`` keyword arg.
    assert call.kwargs.get("provider_event_id") == msg_id
    return event


# --------------------------------------------------------------------------- #
# Each event type → 200 + dispatch
# --------------------------------------------------------------------------- #


async def test_email_sent_payload_dispatches_to_handle_event(
    resend_signer: ResendSigner, stub_handle_event: AsyncMock
) -> None:
    fixture = load_fixture("resend", "email_sent.json")
    assert fixture["type"] == "email.sent"

    status, body = await _post_signed(fixture=fixture, signer=resend_signer)

    assert status == 200
    assert body == {"status": "ok"}
    event = _assert_handle_event_called_with(
        stub_handle_event,
        expected_type="email.sent",
        expected_email_id="ae2014de-c168-4c61-8267-contract0001",
        msg_id=resend_signer.msg_id,
    )
    # Contract: ``data.to`` is a list — the handler relies on iterable shape.
    assert isinstance(event["data"]["to"], list)
    assert event["data"]["to"] == ["client@example.com"]


async def test_email_delivered_payload_dispatches_to_handle_event(
    resend_signer: ResendSigner, stub_handle_event: AsyncMock
) -> None:
    fixture = load_fixture("resend", "email_delivered.json")
    assert fixture["type"] == "email.delivered"

    status, body = await _post_signed(fixture=fixture, signer=resend_signer)

    assert status == 200
    assert body == {"status": "ok"}
    _assert_handle_event_called_with(
        stub_handle_event,
        expected_type="email.delivered",
        expected_email_id="ae2014de-c168-4c61-8267-contract0001",
        msg_id=resend_signer.msg_id,
    )


async def test_email_bounced_payload_carries_bounce_metadata(
    resend_signer: ResendSigner, stub_handle_event: AsyncMock
) -> None:
    """A bounce event must include the ``bounce`` block the handler stores."""
    fixture = load_fixture("resend", "email_bounced.json")
    assert fixture["type"] == "email.bounced"

    status, body = await _post_signed(fixture=fixture, signer=resend_signer)

    assert status == 200
    assert body == {"status": "ok"}
    event = _assert_handle_event_called_with(
        stub_handle_event,
        expected_type="email.bounced",
        expected_email_id="ae2014de-c168-4c61-8267-contract0002",
        msg_id=resend_signer.msg_id,
    )
    bounce = event["data"]["bounce"]
    assert bounce["type"] == "Permanent"
    assert bounce["subType"] == "General"
    assert "hard bounce" in bounce["message"]


async def test_email_opened_payload_dispatches_to_handle_event(
    resend_signer: ResendSigner, stub_handle_event: AsyncMock
) -> None:
    fixture = load_fixture("resend", "email_opened.json")
    assert fixture["type"] == "email.opened"

    status, body = await _post_signed(fixture=fixture, signer=resend_signer)

    assert status == 200
    assert body == {"status": "ok"}
    _assert_handle_event_called_with(
        stub_handle_event,
        expected_type="email.opened",
        expected_email_id="ae2014de-c168-4c61-8267-contract0001",
        msg_id=resend_signer.msg_id,
    )


# --------------------------------------------------------------------------- #
# Signature stack — negative cases
# --------------------------------------------------------------------------- #


async def test_unsigned_resend_request_returns_400(
    resend_signer: ResendSigner, stub_handle_event: AsyncMock
) -> None:
    """No Svix headers → Svix verification raises → 400, no dispatch."""
    fixture = load_fixture("resend", "email_delivered.json")
    body = encode_body(fixture)
    app = build_app(resend_router, prefix="/webhooks/resend")

    with patch.object(app_settings, "resend_webhook_secret", resend_signer.secret):
        async with http_client(app) as client:
            response = await client.post(
                "/webhooks/resend",
                content=body,
                headers={"content-type": "application/json"},
            )

    assert response.status_code == 400
    stub_handle_event.assert_not_called()


async def test_tampered_resend_body_is_rejected(
    resend_signer: ResendSigner, stub_handle_event: AsyncMock
) -> None:
    """Body changed after signing → Svix HMAC mismatch → 400, no dispatch."""
    fixture = load_fixture("resend", "email_delivered.json")
    body_signed = encode_body(fixture)
    headers = {"content-type": "application/json", **resend_signer.sign(body_signed)}
    # Send a different body than the one we signed.
    body_sent = encode_body({**fixture, "type": "email.bounced"})

    app = build_app(resend_router, prefix="/webhooks/resend")
    with patch.object(app_settings, "resend_webhook_secret", resend_signer.secret):
        async with http_client(app) as client:
            response = await client.post("/webhooks/resend", content=body_sent, headers=headers)

    assert response.status_code == 400
    stub_handle_event.assert_not_called()


async def test_missing_resend_secret_returns_503(
    resend_signer: ResendSigner, stub_handle_event: AsyncMock
) -> None:
    """No ``resend_webhook_secret`` configured → 503, no dispatch."""
    fixture = load_fixture("resend", "email_sent.json")
    body = encode_body(fixture)
    headers = {"content-type": "application/json", **resend_signer.sign(body)}
    app = build_app(resend_router, prefix="/webhooks/resend")

    with patch.object(app_settings, "resend_webhook_secret", ""):
        async with http_client(app) as client:
            response = await client.post("/webhooks/resend", content=body, headers=headers)

    assert response.status_code == 503
    stub_handle_event.assert_not_called()
