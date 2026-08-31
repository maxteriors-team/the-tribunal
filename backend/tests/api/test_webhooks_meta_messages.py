"""HTTP-boundary tests for verified Messenger/Instagram DM ingestion."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.webhooks import meta as meta_module
from app.api.webhooks.meta import _message_events
from app.api.webhooks.meta import router as meta_router
from app.core.config import settings as app_settings
from app.db.session import get_db
from app.models.conversation import MessageChannel
from app.services.lead_sources.meta_lead_ads_service import (
    MetaLeadAdsError,
    MetaLeadAdsValidationError,
)

APP_SECRET = "meta-app-secret"


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


def _make_app() -> FastAPI:
    app = FastAPI(lifespan=_test_lifespan)

    async def _override_db() -> AsyncIterator[AsyncMock]:
        yield AsyncMock()

    app.dependency_overrides[get_db] = _override_db
    app.include_router(meta_router, prefix="/webhooks/meta")
    return app


def _messaging(**message: Any) -> dict[str, Any]:
    """One Messenger delivery carrying a single inbound text."""
    return {
        "object": "page",
        "entry": [
            {
                "id": "page-1",
                "time": 1583173667623,
                "messaging": [
                    {
                        "sender": {"id": "psid-1"},
                        "recipient": {"id": "page-1"},
                        "timestamp": 1583173666767,
                        "message": {"mid": "m_1", "text": "hi there", **message},
                    }
                ],
            }
        ],
    }


def _signed_headers(body: bytes) -> dict[str, str]:
    digest = hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return {
        "content-type": "application/json",
        "x-hub-signature-256": f"sha256={digest}",
    }


def _first_event(payload: dict[str, Any]) -> dict[str, Any]:
    """The single ``messaging`` entry in a payload built by :func:`_messaging`.

    Reaching through the nested literal inline needs a chain of ``cast``s or
    ``type: ignore``s to type-check; naming the access once keeps the tests both
    readable and honestly typed.
    """
    events = payload["entry"][0]["messaging"]
    assert isinstance(events, list)
    event = events[0]
    assert isinstance(event, dict)
    return event


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=_make_app()), base_url="http://testserver"
    ) as value:
        yield value


async def _post(client: AsyncClient, payload: dict[str, Any]) -> Any:
    body = json.dumps(payload).encode()
    with patch.object(app_settings, "meta_lead_ads_app_secret", APP_SECRET):
        return await client.post(
            "/webhooks/meta/messages", content=body, headers=_signed_headers(body)
        )


# --- parsing -----------------------------------------------------------------


def test_parses_a_messenger_text_message() -> None:
    events = _message_events(_messaging())
    assert len(events) == 1
    event = events[0]
    assert (event.account_id, event.psid, event.message_id) == ("page-1", "psid-1", "m_1")
    assert event.text == "hi there"
    assert event.channel is MessageChannel.MESSENGER


def test_instagram_object_maps_to_the_instagram_channel() -> None:
    payload = _messaging()
    payload["object"] = "instagram"
    assert _message_events(payload)[0].channel is MessageChannel.INSTAGRAM


def test_echoes_of_our_own_sends_are_dropped() -> None:
    """Ingesting an echo would make the AI reply to itself, forever."""
    assert _message_events(_messaging(is_echo=True)) == []


def test_delivery_and_read_receipts_are_dropped() -> None:
    for field in ("delivery", "read", "reaction"):
        payload = _messaging()
        event = _first_event(payload)
        del event["message"]
        event[field] = {"mids": ["m_1"]}
        assert _message_events(payload) == [], field


def test_attachment_only_and_empty_messages_are_dropped() -> None:
    payload = _messaging()
    _first_event(payload)["message"] = {
        "mid": "m_1",
        "attachments": [{"type": "image", "payload": {"url": "https://example.test/x.jpg"}}],
    }
    assert _message_events(payload) == []


def test_duplicate_message_ids_in_one_delivery_collapse() -> None:
    payload = _messaging()
    payload["entry"][0]["messaging"].append(dict(_first_event(payload)))
    assert len(_message_events(payload)) == 1


def test_page_talking_to_itself_is_dropped() -> None:
    payload = _messaging()
    _first_event(payload)["sender"] = {"id": "page-1"}
    assert _message_events(payload) == []


def test_entry_id_wins_over_a_forged_recipient() -> None:
    """The entry is what Meta signed; a forged recipient must not redirect a DM."""
    payload = _messaging()
    _first_event(payload)["recipient"] = {"id": "someone-elses-page"}
    assert _message_events(payload)[0].account_id == "page-1"


def test_unknown_object_types_are_ignored() -> None:
    payload = _messaging()
    payload["object"] = "whatsapp_business_account"
    assert _message_events(payload) == []


def test_message_text_is_capped() -> None:
    payload = _messaging(text="x" * 50_000)
    assert len(_message_events(payload)[0].text) == meta_module._MAX_MESSAGE_CHARS


# --- HTTP boundary -----------------------------------------------------------


async def test_unsigned_delivery_is_rejected(client: AsyncClient) -> None:
    body = json.dumps(_messaging()).encode()
    with patch.object(app_settings, "meta_lead_ads_app_secret", APP_SECRET):
        response = await client.post(
            "/webhooks/meta/messages",
            content=body,
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 401


async def test_forged_signature_is_rejected(client: AsyncClient) -> None:
    body = json.dumps(_messaging()).encode()
    forged = hmac.new(b"not-the-secret", body, hashlib.sha256).hexdigest()
    with patch.object(app_settings, "meta_lead_ads_app_secret", APP_SECRET):
        response = await client.post(
            "/webhooks/meta/messages",
            content=body,
            headers={
                "content-type": "application/json",
                "x-hub-signature-256": f"sha256={forged}",
            },
        )
    assert response.status_code == 401


async def test_signed_delivery_is_processed(client: AsyncClient) -> None:
    with patch.object(meta_module, "process_meta_message", AsyncMock(return_value=True)) as spy:
        response = await _post(client, _messaging())
    assert response.status_code == 200
    assert response.json() == {"received": True, "processed": 1, "ignored": 0}
    assert spy.await_count == 1


async def test_duplicate_delivery_counts_as_ignored(client: AsyncClient) -> None:
    """Meta replays the same ``mid``; a replay must not be reported as new."""
    with patch.object(meta_module, "process_meta_message", AsyncMock(return_value=False)):
        response = await _post(client, _messaging())
    assert response.json() == {"received": True, "processed": 0, "ignored": 1}


async def test_unmapped_page_is_absorbed_not_retried(client: AsyncClient) -> None:
    """A Page no workspace owns cannot be fixed by Meta resending it."""
    failure = AsyncMock(side_effect=MetaLeadAdsValidationError("no integration"))
    with patch.object(meta_module, "process_meta_message", failure):
        response = await _post(client, _messaging())
    assert response.status_code == 200
    assert response.json()["ignored"] == 1


async def test_transient_failure_asks_meta_to_retry(client: AsyncClient) -> None:
    failure = AsyncMock(side_effect=MetaLeadAdsError("graph down"))
    with patch.object(meta_module, "process_meta_message", failure):
        response = await _post(client, _messaging())
    assert response.status_code == 503


async def test_oversized_body_is_rejected(client: AsyncClient) -> None:
    body = json.dumps(_messaging(text="x" * 400_000)).encode()
    with (
        patch.object(app_settings, "meta_lead_ads_app_secret", APP_SECRET),
        patch.object(app_settings, "meta_lead_ads_max_webhook_bytes", 1024),
    ):
        response = await client.post(
            "/webhooks/meta/messages", content=body, headers=_signed_headers(body)
        )
    assert response.status_code == 413


async def test_verification_challenge_requires_the_exact_token(client: AsyncClient) -> None:
    with patch.object(app_settings, "meta_lead_ads_verify_token", "verify-me"):
        accepted = await client.get(
            "/webhooks/meta/messages",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "verify-me",
                "hub.challenge": "challenge-value",
            },
        )
        rejected = await client.get(
            "/webhooks/meta/messages",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong",
                "hub.challenge": "challenge-value",
            },
        )
    assert accepted.status_code == 200
    assert accepted.text == "challenge-value"
    assert rejected.status_code == 403
