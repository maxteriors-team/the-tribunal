"""Contract tests for Telnyx webhook payloads.

For every fixture under ``tests/contract/fixtures/telnyx/`` we:

1. Serialize the fixture to bytes.
2. Sign the body with a fresh ed25519 keypair and patch
   ``settings.telnyx_public_key`` to the matching public key.
3. POST to the real ``/webhooks/telnyx/<sms|voice>`` router under a
   FastAPI test app.
4. Assert ``200 {"status": "ok"}`` and that the correct per-event
   handler was dispatched with the parsed payload from the fixture.

The per-event handlers themselves write to the database, schedule AI
responses, and call back out to Telnyx — those side effects are covered
in ``tests/api/test_webhooks_telnyx_{call,message}_handlers.py``. Here
we only pin the *contract*: the wire-format shape × signature stack ×
router dispatch.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.api.webhooks import telnyx as telnyx_router_module
from app.api.webhooks.telnyx import router as telnyx_router
from app.core.config import settings as app_settings
from tests.contract._helpers import (
    TelnyxSigner,
    build_app,
    encode_body,
    http_client,
)
from tests.contract.fixtures import load_fixture

# --------------------------------------------------------------------------- #
# Shared per-test plumbing
# --------------------------------------------------------------------------- #


def _payload_from(fixture: dict[str, Any]) -> dict[str, Any]:
    """Pull the inner ``data.payload`` block — what handlers receive."""
    data = fixture["data"]
    payload = data["payload"]
    assert isinstance(payload, dict)
    return payload


def _event_type_from(fixture: dict[str, Any]) -> str:
    et = fixture["data"]["event_type"]
    assert isinstance(et, str)
    return et


@pytest.fixture
def patched_sms_handlers(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    """Replace SMS dispatch table entries with ``AsyncMock`` recorders."""
    handlers = {
        "message.received": AsyncMock(),
        "message.sent": AsyncMock(),
        "message.finalized": AsyncMock(),
    }
    for event_type, mock in handlers.items():
        monkeypatch.setitem(telnyx_router_module._SMS_HANDLERS, event_type, mock)
    return handlers


@pytest.fixture
def patched_voice_handlers(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    """Replace voice dispatch table entries with ``AsyncMock`` recorders."""
    handlers = {
        "call.initiated": AsyncMock(),
        "call.answered": AsyncMock(),
        "call.hangup": AsyncMock(),
        "call.machine.detection.ended": AsyncMock(),
    }
    for event_type, mock in handlers.items():
        monkeypatch.setitem(telnyx_router_module._VOICE_HANDLERS, event_type, mock)
    return handlers


async def _post_signed(
    *,
    fixture: dict[str, Any],
    signer: TelnyxSigner,
    path: str,
) -> tuple[int, dict[str, Any]]:
    """Sign *fixture* and POST it to *path* on the Telnyx test app."""
    app = build_app(telnyx_router, prefix="/webhooks/telnyx")
    body = encode_body(fixture)
    headers = {
        "content-type": "application/json",
        **signer.sign(body),
    }

    with patch.object(app_settings, "telnyx_public_key", signer.public_key_b64):
        async with http_client(app) as client:
            response = await client.post(path, content=body, headers=headers)

    return response.status_code, response.json()


# --------------------------------------------------------------------------- #
# Voice events
# --------------------------------------------------------------------------- #


async def test_call_initiated_payload_dispatches_to_handler(
    telnyx_signer: TelnyxSigner,
    patched_voice_handlers: dict[str, AsyncMock],
) -> None:
    fixture = load_fixture("telnyx", "call_initiated.json")
    assert _event_type_from(fixture) == "call.initiated"

    status, body = await _post_signed(
        fixture=fixture, signer=telnyx_signer, path="/webhooks/telnyx/voice"
    )

    assert status == 200
    assert body == {"status": "ok"}

    handler = patched_voice_handlers["call.initiated"]
    handler.assert_awaited_once()
    parsed_payload = handler.await_args.args[0]
    assert parsed_payload == _payload_from(fixture)
    # Contract: handler sees a normalized call_control_id and direction.
    assert parsed_payload["call_control_id"] == "v3:contract-call-control-001"
    assert parsed_payload["direction"] == "incoming"
    assert parsed_payload["state"] == "ringing"
    # Other voice handlers must NOT fire.
    patched_voice_handlers["call.answered"].assert_not_called()
    patched_voice_handlers["call.hangup"].assert_not_called()


async def test_call_answered_payload_dispatches_to_handler(
    telnyx_signer: TelnyxSigner,
    patched_voice_handlers: dict[str, AsyncMock],
) -> None:
    fixture = load_fixture("telnyx", "call_answered.json")
    assert _event_type_from(fixture) == "call.answered"

    status, body = await _post_signed(
        fixture=fixture, signer=telnyx_signer, path="/webhooks/telnyx/voice"
    )

    assert status == 200
    assert body == {"status": "ok"}

    handler = patched_voice_handlers["call.answered"]
    handler.assert_awaited_once()
    parsed_payload = handler.await_args.args[0]
    assert parsed_payload["state"] == "answered"
    assert parsed_payload["call_control_id"] == "v3:contract-call-control-001"


async def test_call_hangup_payload_dispatches_with_duration_and_cause(
    telnyx_signer: TelnyxSigner,
    patched_voice_handlers: dict[str, AsyncMock],
) -> None:
    fixture = load_fixture("telnyx", "call_hangup.json")
    assert _event_type_from(fixture) == "call.hangup"

    status, body = await _post_signed(
        fixture=fixture, signer=telnyx_signer, path="/webhooks/telnyx/voice"
    )

    assert status == 200
    assert body == {"status": "ok"}

    handler = patched_voice_handlers["call.hangup"]
    handler.assert_awaited_once()
    parsed_payload = handler.await_args.args[0]
    # The hangup handler relies on these exact field names.
    assert parsed_payload["hangup_cause"] == "NORMAL_CLEARING"
    assert parsed_payload["hangup_source"] == "caller"
    assert parsed_payload["duration_seconds"] == 85


async def test_recording_saved_payload_is_accepted_even_when_unhandled(
    telnyx_signer: TelnyxSigner,
    patched_voice_handlers: dict[str, AsyncMock],
) -> None:
    """``call.recording.saved`` is currently an unhandled event.

    The router must still return 200 (so Telnyx stops retrying) and the
    voice dispatch handlers must NOT fire. Recordings are picked up from
    the ``call.hangup`` payload's ``recordings`` array in production.
    """
    fixture = load_fixture("telnyx", "recording_saved.json")
    assert _event_type_from(fixture) == "call.recording.saved"

    status, body = await _post_signed(
        fixture=fixture, signer=telnyx_signer, path="/webhooks/telnyx/voice"
    )

    assert status == 200
    assert body == {"status": "ok"}

    for handler in patched_voice_handlers.values():
        handler.assert_not_called()

    # Contract: a recording fixture carries at least one URL the handler
    # can persist later. We pin the documented field shape so the
    # ingestion code keeps matching what Telnyx sends today.
    rec_payload = _payload_from(fixture)
    assert rec_payload["recording_urls"]["mp3"].endswith(".mp3")
    assert "recording_started_at" in rec_payload
    assert "recording_ended_at" in rec_payload


# --------------------------------------------------------------------------- #
# SMS events
# --------------------------------------------------------------------------- #


async def test_message_received_payload_dispatches_to_inbound_handler(
    telnyx_signer: TelnyxSigner,
    patched_sms_handlers: dict[str, AsyncMock],
) -> None:
    fixture = load_fixture("telnyx", "message_received.json")
    assert _event_type_from(fixture) == "message.received"

    status, body = await _post_signed(
        fixture=fixture, signer=telnyx_signer, path="/webhooks/telnyx/sms"
    )

    assert status == 200
    assert body == {"status": "ok"}

    handler = patched_sms_handlers["message.received"]
    handler.assert_awaited_once()
    parsed_payload = handler.await_args.args[0]
    assert parsed_payload["direction"] == "inbound"
    assert parsed_payload["text"] == "Hi, I'd like to book an appointment"
    assert parsed_payload["from"]["phone_number"] == "+14155552671"
    assert parsed_payload["to"][0]["phone_number"] == "+12125550101"
    # No outbound-status side effects.
    patched_sms_handlers["message.sent"].assert_not_called()
    patched_sms_handlers["message.finalized"].assert_not_called()


async def test_message_sent_payload_dispatches_to_delivery_handler(
    telnyx_signer: TelnyxSigner,
    patched_sms_handlers: dict[str, AsyncMock],
) -> None:
    """``message.sent`` is the first-leg-out status update."""
    fixture = load_fixture("telnyx", "message_sent.json")
    assert _event_type_from(fixture) == "message.sent"

    status, body = await _post_signed(
        fixture=fixture, signer=telnyx_signer, path="/webhooks/telnyx/sms"
    )

    assert status == 200
    assert body == {"status": "ok"}

    handler = patched_sms_handlers["message.sent"]
    handler.assert_awaited_once()
    parsed_payload = handler.await_args.args[0]
    assert parsed_payload["direction"] == "outbound"
    assert parsed_payload["to"][0]["status"] == "sent"


async def test_message_delivered_payload_dispatches_to_finalized_handler(
    telnyx_signer: TelnyxSigner,
    patched_sms_handlers: dict[str, AsyncMock],
) -> None:
    """Final-status ``delivered`` arrives as ``message.finalized``."""
    fixture = load_fixture("telnyx", "message_delivered.json")
    assert _event_type_from(fixture) == "message.finalized"

    status, body = await _post_signed(
        fixture=fixture, signer=telnyx_signer, path="/webhooks/telnyx/sms"
    )

    assert status == 200
    assert body == {"status": "ok"}

    handler = patched_sms_handlers["message.finalized"]
    handler.assert_awaited_once()
    parsed_payload = handler.await_args.args[0]
    assert parsed_payload["to"][0]["status"] == "delivered"
    assert parsed_payload["errors"] == []


async def test_message_failed_payload_carries_error_for_bounce_classification(
    telnyx_signer: TelnyxSigner,
    patched_sms_handlers: dict[str, AsyncMock],
) -> None:
    """A failed delivery surfaces the carrier error the classifier needs."""
    fixture = load_fixture("telnyx", "message_failed.json")
    assert _event_type_from(fixture) == "message.finalized"

    status, body = await _post_signed(
        fixture=fixture, signer=telnyx_signer, path="/webhooks/telnyx/sms"
    )

    assert status == 200
    assert body == {"status": "ok"}

    handler = patched_sms_handlers["message.finalized"]
    handler.assert_awaited_once()
    parsed_payload = handler.await_args.args[0]
    assert parsed_payload["to"][0]["status"] == "delivery_failed"
    # ``handle_delivery_status`` reads errors[0].code/detail — pin both.
    assert parsed_payload["errors"][0]["code"] == "30004"
    assert "not valid" in parsed_payload["errors"][0]["detail"]


# --------------------------------------------------------------------------- #
# Signature stack — negative case
# --------------------------------------------------------------------------- #


async def test_unsigned_telnyx_request_is_rejected(
    telnyx_signer: TelnyxSigner,
    patched_voice_handlers: dict[str, AsyncMock],
) -> None:
    """No signature header → 403, no dispatch."""
    fixture = load_fixture("telnyx", "call_initiated.json")
    body = encode_body(fixture)
    app = build_app(telnyx_router, prefix="/webhooks/telnyx")

    with patch.object(app_settings, "telnyx_public_key", telnyx_signer.public_key_b64):
        async with http_client(app) as client:
            response = await client.post(
                "/webhooks/telnyx/voice",
                content=body,
                headers={"content-type": "application/json"},
            )

    assert response.status_code == 403
    for handler in patched_voice_handlers.values():
        handler.assert_not_called()


async def test_tampered_telnyx_body_is_rejected(
    telnyx_signer: TelnyxSigner,
    patched_voice_handlers: dict[str, AsyncMock],
) -> None:
    """Signature valid for *original* body but body was changed → 403."""
    original = load_fixture("telnyx", "call_initiated.json")
    body_signed = encode_body(original)
    tampered = json.loads(body_signed.decode())
    tampered["data"]["payload"]["call_control_id"] = "v3:attacker-control-id"
    body_sent = encode_body(tampered)
    # Sign the ORIGINAL bytes, then POST the tampered bytes.
    headers = {"content-type": "application/json", **telnyx_signer.sign(body_signed)}

    app = build_app(telnyx_router, prefix="/webhooks/telnyx")
    with patch.object(app_settings, "telnyx_public_key", telnyx_signer.public_key_b64):
        async with http_client(app) as client:
            response = await client.post(
                "/webhooks/telnyx/voice", content=body_sent, headers=headers
            )

    assert response.status_code == 403
    for handler in patched_voice_handlers.values():
        handler.assert_not_called()
