"""Tests for ``app.api.webhooks.telnyx_parser``.

Covers:

- :func:`verify_and_parse` — verifies the Telnyx signature via
  ``verify_telnyx_webhook`` and decodes the JSON body. Returns
  ``(event_type, event_payload)`` on success, or ``None`` if the JSON
  body cannot be parsed. Raises whatever
  :func:`app.core.webhook_security.verify_telnyx_webhook` raises on a
  bad signature.
- :func:`extract_phone_numbers` — normalizes the ``from`` / ``to`` shapes
  that Telnyx variously sends as a bare string, an object with
  ``phone_number``, or a list of such objects (voice vs SMS payloads).

Real-shape fixtures are loaded from ``tests/fixtures/webhooks/telnyx/``.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.webhooks import telnyx_parser as parser_module
from app.api.webhooks.telnyx_parser import extract_phone_numbers, verify_and_parse
from tests.fixtures.webhooks import load_fixture

# --------------------------------------------------------------------------- #
# extract_phone_numbers — shape handling
# --------------------------------------------------------------------------- #


def test_extract_phone_numbers_voice_payload() -> None:
    """Voice ``call.initiated`` sends ``from``/``to`` as bare strings."""
    payload = load_fixture("telnyx", "call_initiated.json")["data"]["payload"]

    from_n, to_n = extract_phone_numbers(payload)

    # E.164 round-trip — normalize_phone_safe returns the same string.
    assert from_n == "+14155552672"
    assert to_n == "+12125550100"


def test_extract_phone_numbers_sms_payload() -> None:
    """SMS ``message.received`` sends ``from`` as an object and ``to`` as a list."""
    payload = load_fixture("telnyx", "sms_inbound.json")["data"]["payload"]

    from_n, to_n = extract_phone_numbers(payload)

    assert from_n == "+14155552671"
    assert to_n == "+12125550101"


def test_extract_phone_numbers_handles_dict_from() -> None:
    """``from`` may be a dict with ``phone_number`` (SMS-style)."""
    payload: dict[str, Any] = {
        "from": {"phone_number": "+15551111111"},
        "to": [{"phone_number": "+15552222222"}],
    }

    from_n, to_n = extract_phone_numbers(payload)

    assert from_n == "+15551111111"
    assert to_n == "+15552222222"


def test_extract_phone_numbers_handles_dict_to_no_list() -> None:
    payload: dict[str, Any] = {
        "from": "+15551111111",
        "to": {"phone_number": "+15552222222"},
    }

    from_n, to_n = extract_phone_numbers(payload)

    assert from_n == "+15551111111"
    assert to_n == "+15552222222"


def test_extract_phone_numbers_handles_empty_to_list() -> None:
    """Empty ``to`` list → empty string (caller must validate downstream)."""
    payload: dict[str, Any] = {
        "from": "+15551111111",
        "to": [],
    }

    from_n, to_n = extract_phone_numbers(payload)

    assert from_n == "+15551111111"
    assert to_n == ""


def test_extract_phone_numbers_handles_missing_keys() -> None:
    """Garbage payload must not crash — empty strings out."""
    from_n, to_n = extract_phone_numbers({})

    assert from_n == ""
    assert to_n == ""


def test_extract_phone_numbers_preserves_unnormalizable_value() -> None:
    """If normalize_phone_safe returns None the raw value is kept."""
    payload: dict[str, Any] = {
        "from": "anonymous",
        "to": "private",
    }

    from_n, to_n = extract_phone_numbers(payload)

    # ``normalize_phone_safe`` cannot parse "anonymous"/"private" — but
    # the parser keeps the raw value rather than dropping it on the floor.
    assert from_n == "anonymous"
    assert to_n == "private"


# --------------------------------------------------------------------------- #
# verify_and_parse — wraps signature verification + JSON decode
# --------------------------------------------------------------------------- #


def _request_with_body(body: bytes) -> MagicMock:
    """FastAPI ``Request`` stub that returns ``body`` from ``.json()``."""
    request = MagicMock()
    request.json = AsyncMock(
        side_effect=lambda: json.loads(body.decode("utf-8")),
    )
    return request


async def test_verify_and_parse_returns_event_type_and_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = load_fixture("telnyx", "call_initiated.json")
    body = json.dumps(fixture).encode()

    monkeypatch.setattr(parser_module, "verify_telnyx_webhook", AsyncMock(return_value=True))
    log = MagicMock()

    result = await verify_and_parse(_request_with_body(body), log)

    assert result is not None
    event_type, event_payload = result
    assert event_type == "call.initiated"
    assert event_payload["call_control_id"] == "v3:call-control-id-initiated-001"
    assert event_payload["from"] == "+14155552672"


async def test_verify_and_parse_propagates_signature_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bad signature must raise — must NOT silently return None."""
    monkeypatch.setattr(
        parser_module,
        "verify_telnyx_webhook",
        AsyncMock(side_effect=HTTPException(status_code=403, detail="bad sig")),
    )
    request = MagicMock()
    request.json = AsyncMock(return_value={})
    log = MagicMock()

    with pytest.raises(HTTPException) as excinfo:
        await verify_and_parse(request, log)

    assert excinfo.value.status_code == 403
    # We never reached the JSON decode path.
    request.json.assert_not_called()


async def test_verify_and_parse_returns_none_on_invalid_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(parser_module, "verify_telnyx_webhook", AsyncMock(return_value=True))
    request = MagicMock()
    request.json = AsyncMock(side_effect=ValueError("not json"))
    log = MagicMock()

    result = await verify_and_parse(request, log)

    assert result is None
    log.error.assert_called_once_with("invalid_json_payload")


async def test_verify_and_parse_defaults_when_data_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Payload without ``data`` key still returns a tuple of empty defaults."""
    monkeypatch.setattr(parser_module, "verify_telnyx_webhook", AsyncMock(return_value=True))
    request = MagicMock()
    request.json = AsyncMock(return_value={"meta": {}})
    log = MagicMock()

    result = await verify_and_parse(request, log)

    assert result == ("", {})


async def test_verify_and_parse_with_sms_inbound_fixture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = load_fixture("telnyx", "sms_inbound.json")
    body = json.dumps(fixture).encode()

    monkeypatch.setattr(parser_module, "verify_telnyx_webhook", AsyncMock(return_value=True))
    log = MagicMock()

    result = await verify_and_parse(_request_with_body(body), log)

    assert result is not None
    event_type, payload = result
    assert event_type == "message.received"
    assert payload["text"] == "Hi, I'd like to book an appointment"
    assert payload["from"]["phone_number"] == "+14155552671"
