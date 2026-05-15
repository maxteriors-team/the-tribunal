"""Tests for the Resend webhook router (``app/api/webhooks/resend.py``).

Complements ``tests/api/test_resend_handlers.py`` (which covers the
event-dispatch / idempotency logic in
:mod:`app.api.webhooks.resend_handlers`) by exercising the HTTP boundary:

* Missing webhook secret → 503 (refuse to process unverified deliveries).
* Invalid Svix signature → 400.
* Valid signature → 200 ``{"status": "ok"}`` and ``handle_event`` is invoked
  with the parsed event plus the ``svix-id`` from headers.
* ``webhook-id`` header is honored as a fallback for ``svix-id``.
* ``handle_event`` is *not* called when verification fails.

All tests mock ``svix.webhooks.Webhook`` so we don't need to sign real
payloads, and override ``get_db`` so no database is required.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from svix.webhooks import WebhookVerificationError

from app.api.webhooks import resend as resend_module
from app.api.webhooks.resend import router as resend_router
from app.core.config import settings as app_settings
from app.db.session import get_db

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


def _make_app(db: AsyncMock | None = None) -> FastAPI:
    """Mount the resend router under ``/webhooks/resend`` with ``get_db`` stubbed."""
    app = FastAPI(lifespan=_test_lifespan)

    async def _override_db() -> AsyncIterator[AsyncMock]:
        yield db or AsyncMock()

    app.dependency_overrides[get_db] = _override_db
    # Match the real prefix used in ``app.main``.
    app.include_router(resend_router, prefix="/webhooks/resend")
    return app


def _make_event_payload(event_type: str = "email.delivered") -> dict[str, Any]:
    return {
        "type": event_type,
        "created_at": "2026-05-15T10:00:00Z",
        "data": {"email_id": "msg_abc123"},
    }


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=_make_app()),
        base_url="http://testserver",
    ) as ac:
        yield ac


# --------------------------------------------------------------------------- #
# Missing webhook secret → 503
# --------------------------------------------------------------------------- #


async def test_missing_webhook_secret_returns_503(client: AsyncClient) -> None:
    """If ``resend_webhook_secret`` is unset, we refuse to process the call."""
    with patch.object(app_settings, "resend_webhook_secret", ""):
        response = await client.post(
            "/webhooks/resend",
            content=json.dumps(_make_event_payload()),
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 503
    # Error wrapping is applied by the production exception handler, but the
    # router itself raises HTTPException(detail=...) which FastAPI serializes
    # to ``{"detail": ...}`` when no global handler is mounted on this app.
    body = response.json()
    assert "not configured" in json.dumps(body).lower()


# --------------------------------------------------------------------------- #
# Invalid signature → 400, no handler invocation
# --------------------------------------------------------------------------- #


async def test_invalid_signature_returns_400(client: AsyncClient) -> None:
    """A Svix verification failure must surface as 400 and never dispatch."""
    fake_wh = MagicMock()
    fake_wh.verify = MagicMock(side_effect=WebhookVerificationError("bad sig"))

    mock_handle = AsyncMock()
    with (
        patch.object(app_settings, "resend_webhook_secret", "whsec_test"),
        patch.object(resend_module, "Webhook", return_value=fake_wh),
        patch.object(resend_module, "handle_event", new=mock_handle),
    ):
        response = await client.post(
            "/webhooks/resend",
            content=json.dumps(_make_event_payload()),
            headers={
                "content-type": "application/json",
                "svix-id": "msg_test_1",
                "svix-timestamp": "1700000000",
                "svix-signature": "v1,not-a-real-sig",
            },
        )
    assert response.status_code == 400
    mock_handle.assert_not_called()


# --------------------------------------------------------------------------- #
# svix not installed → 500
# --------------------------------------------------------------------------- #


async def test_svix_not_available_returns_500(client: AsyncClient) -> None:
    """If the optional svix dep is missing at runtime, return a clear 500."""
    mock_handle = AsyncMock()
    with (
        patch.object(app_settings, "resend_webhook_secret", "whsec_test"),
        patch.object(resend_module, "SVIX_AVAILABLE", False),
        patch.object(resend_module, "handle_event", new=mock_handle),
    ):
        response = await client.post(
            "/webhooks/resend",
            content=json.dumps(_make_event_payload()),
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 500
    mock_handle.assert_not_called()


# --------------------------------------------------------------------------- #
# Happy path — verified signature → 200 + handler invoked
# --------------------------------------------------------------------------- #


async def test_valid_signature_dispatches_to_handler(client: AsyncClient) -> None:
    """Verified webhooks return ``{"status": "ok"}`` and call ``handle_event``."""
    event = _make_event_payload("email.delivered")
    fake_wh = MagicMock()
    fake_wh.verify = MagicMock(return_value=event)
    mock_handle = AsyncMock()

    with (
        patch.object(app_settings, "resend_webhook_secret", "whsec_test"),
        patch.object(resend_module, "Webhook", return_value=fake_wh),
        patch.object(resend_module, "handle_event", new=mock_handle),
    ):
        response = await client.post(
            "/webhooks/resend",
            content=json.dumps(event),
            headers={
                "content-type": "application/json",
                "svix-id": "msg_xyz_1",
                "svix-timestamp": "1700000000",
                "svix-signature": "v1,fake",
            },
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    mock_handle.assert_awaited_once()
    # handle_event(db, event, log, provider_event_id="msg_xyz_1")
    call = mock_handle.await_args
    assert call is not None
    assert call.args[1] == event  # parsed event payload
    assert call.kwargs.get("provider_event_id") == "msg_xyz_1"


async def test_webhook_id_header_used_as_fallback(client: AsyncClient) -> None:
    """When ``svix-id`` is absent, ``webhook-id`` is the idempotency key.

    Some Svix consumers proxy the headers under the standardized
    ``webhook-id`` name; the router accepts either.
    """
    event = _make_event_payload("email.opened")
    fake_wh = MagicMock()
    fake_wh.verify = MagicMock(return_value=event)
    mock_handle = AsyncMock()

    with (
        patch.object(app_settings, "resend_webhook_secret", "whsec_test"),
        patch.object(resend_module, "Webhook", return_value=fake_wh),
        patch.object(resend_module, "handle_event", new=mock_handle),
    ):
        response = await client.post(
            "/webhooks/resend",
            content=json.dumps(event),
            headers={
                "content-type": "application/json",
                # Note: no ``svix-id`` — only ``webhook-id``.
                "webhook-id": "wh_id_fallback",
            },
        )

    assert response.status_code == 200
    call = mock_handle.await_args
    assert call is not None
    assert call.kwargs["provider_event_id"] == "wh_id_fallback"


async def test_verify_falls_back_to_payload_when_svix_returns_non_dict(
    client: AsyncClient,
) -> None:
    """If ``Webhook.verify`` doesn't return a dict, we parse the raw payload."""
    event = _make_event_payload("email.clicked")
    fake_wh = MagicMock()
    # Old svix versions returned ``None`` on success — fall back to json.loads.
    fake_wh.verify = MagicMock(return_value=None)
    mock_handle = AsyncMock()

    with (
        patch.object(app_settings, "resend_webhook_secret", "whsec_test"),
        patch.object(resend_module, "Webhook", return_value=fake_wh),
        patch.object(resend_module, "handle_event", new=mock_handle),
    ):
        response = await client.post(
            "/webhooks/resend",
            content=json.dumps(event),
            headers={
                "content-type": "application/json",
                "svix-id": "msg_parse_fallback",
            },
        )

    assert response.status_code == 200
    # Parsed event still reached the handler — confirming the json.loads fallback.
    call = mock_handle.await_args
    assert call is not None
    assert call.args[1] == event


# --------------------------------------------------------------------------- #
# Direct unit coverage of ``_verify_signature``
# --------------------------------------------------------------------------- #


class TestVerifySignatureUnit:
    """Direct unit tests for the verification helper."""

    def test_no_secret_raises_503(self) -> None:
        from fastapi import HTTPException

        with (
            patch.object(app_settings, "resend_webhook_secret", ""),
            pytest.raises(HTTPException) as exc_info,
        ):
            resend_module._verify_signature(b"{}", {})
        assert exc_info.value.status_code == 503

    def test_svix_unavailable_raises_500(self) -> None:
        from fastapi import HTTPException

        with (
            patch.object(app_settings, "resend_webhook_secret", "whsec_test"),
            patch.object(resend_module, "SVIX_AVAILABLE", False),
            pytest.raises(HTTPException) as exc_info,
        ):
            resend_module._verify_signature(b"{}", {})
        assert exc_info.value.status_code == 500

    def test_bad_signature_raises_400(self) -> None:
        from fastapi import HTTPException

        fake_wh = MagicMock()
        fake_wh.verify = MagicMock(side_effect=WebhookVerificationError("nope"))
        with (
            patch.object(app_settings, "resend_webhook_secret", "whsec_test"),
            patch.object(resend_module, "Webhook", return_value=fake_wh),
            pytest.raises(HTTPException) as exc_info,
        ):
            resend_module._verify_signature(b"{}", {})
        assert exc_info.value.status_code == 400

    def test_valid_signature_returns_parsed_dict(self) -> None:
        event = {"type": "email.sent", "data": {}}
        fake_wh = MagicMock()
        fake_wh.verify = MagicMock(return_value=event)
        with (
            patch.object(app_settings, "resend_webhook_secret", "whsec_test"),
            patch.object(resend_module, "Webhook", return_value=fake_wh),
        ):
            result = resend_module._verify_signature(
                json.dumps(event).encode(), {"svix-id": "x"}
            )
        assert result == event
