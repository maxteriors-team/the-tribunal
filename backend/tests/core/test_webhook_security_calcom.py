"""Tests for Cal.com webhook verification in ``verify_calcom_webhook``.

Cal.com signs the raw body only (HMAC-SHA256) and does NOT send an
``x-cal-timestamp`` header, so verification must hinge on the signature and must
NOT require a timestamp — requiring one 403s every real Cal.com webhook. When a
timestamp header happens to be present we still apply a best-effort staleness
window. Replay protection proper is handled by the Redis idempotency dedupe in
``app/api/webhooks/calcom.py``. The dev escape hatch is
``settings.skip_webhook_verification``.
"""

import hashlib
import hmac
import time

import pytest
from fastapi import HTTPException, Request

from app.core.config import settings
from app.core.webhook_security import verify_calcom_webhook

_SECRET = "test-calcom-secret"


def _sign(body: bytes, secret: str = _SECRET) -> str:
    """Return the ``x-cal-signature-256`` value for ``body``."""
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _make_request(headers: dict[str, str], body: bytes = b"{}") -> Request:
    """Build a minimal ASGI ``Request`` carrying ``headers`` and ``body``."""
    encoded_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1")) for key, value in headers.items()
    ]
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/webhooks/calcom",
        "headers": encoded_headers,
    }

    sent = {"done": False}

    async def receive() -> dict[str, object]:
        if sent["done"]:
            return {"type": "http.disconnect"}
        sent["done"] = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope=scope, receive=receive)


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force production-mode verification with a known secret."""
    monkeypatch.setattr(settings, "skip_webhook_verification", False)
    monkeypatch.setattr(settings, "calcom_webhook_secret", _SECRET)


class TestMissingTimestampHeader:
    """Cal.com does not send ``x-cal-timestamp``; its absence must NOT 403."""

    async def test_missing_timestamp_accepted_with_valid_signature(self) -> None:
        # Real Cal.com webhooks carry only x-cal-signature-256. A valid
        # signature and no timestamp must pass — this is the exact shape of
        # production traffic that a hard timestamp requirement was rejecting.
        body = b'{"event":"BOOKING_CREATED"}'
        request = _make_request(
            {"x-cal-signature-256": _sign(body)},
            body=body,
        )

        assert await verify_calcom_webhook(request) is True

    async def test_empty_timestamp_accepted_with_valid_signature(self) -> None:
        body = b'{"event":"BOOKING_CREATED"}'
        request = _make_request(
            {
                "x-cal-signature-256": _sign(body),
                "x-cal-timestamp": "",
            },
            body=body,
        )

        assert await verify_calcom_webhook(request) is True

    async def test_missing_signature_still_rejected(self) -> None:
        """The signature is the real auth and remains mandatory."""
        request = _make_request({}, body=b'{"event":"BOOKING_CREATED"}')

        with pytest.raises(HTTPException) as exc_info:
            await verify_calcom_webhook(request)

        assert exc_info.value.status_code == 403
        assert "signature" in exc_info.value.detail.lower()

    async def test_invalid_signature_rejected_without_timestamp(self) -> None:
        body = b'{"event":"BOOKING_CREATED"}'
        request = _make_request(
            {"x-cal-signature-256": "deadbeef" * 8},
            body=body,
        )

        with pytest.raises(HTTPException) as exc_info:
            await verify_calcom_webhook(request)

        assert exc_info.value.status_code == 403
        assert "signature" in exc_info.value.detail.lower()

    async def test_skip_flag_bypasses_verification(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Dev escape hatch still wins: no timestamp, no signature, still accepts."""
        monkeypatch.setattr(settings, "skip_webhook_verification", True)
        request = _make_request({}, body=b"{}")

        assert await verify_calcom_webhook(request) is True


class TestTimestampStaleness:
    """When the header is present, the existing staleness window still applies."""

    async def test_valid_recent_timestamp_accepted(self) -> None:
        body = b'{"event":"BOOKING_CREATED"}'
        request = _make_request(
            {
                "x-cal-signature-256": _sign(body),
                "x-cal-timestamp": str(int(time.time())),
            },
            body=body,
        )

        assert await verify_calcom_webhook(request) is True

    async def test_stale_timestamp_rejected(self) -> None:
        body = b'{"event":"BOOKING_CREATED"}'
        # 10 minutes old — outside the 5-minute replay window.
        stale_ts = str(int(time.time()) - 600)
        request = _make_request(
            {
                "x-cal-signature-256": _sign(body),
                "x-cal-timestamp": stale_ts,
            },
            body=body,
        )

        with pytest.raises(HTTPException) as exc_info:
            await verify_calcom_webhook(request)

        assert exc_info.value.status_code == 403
        assert "too old" in exc_info.value.detail.lower()

    async def test_non_numeric_timestamp_rejected(self) -> None:
        body = b'{"event":"BOOKING_CREATED"}'
        request = _make_request(
            {
                "x-cal-signature-256": _sign(body),
                "x-cal-timestamp": "not-a-number",
            },
            body=body,
        )

        with pytest.raises(HTTPException) as exc_info:
            await verify_calcom_webhook(request)

        assert exc_info.value.status_code == 403
        assert "invalid" in exc_info.value.detail.lower()
