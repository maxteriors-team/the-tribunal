"""Security boundary tests for the Quo webhook route."""

from __future__ import annotations

import base64
import json
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from svix.webhooks import Webhook

from app.api.webhooks.quo import QUO_MAX_BODY_BYTES, router
from app.db.session import get_db
from app.services import webhook_replay
from app.services.quo.sync import QuoSyncError
from app.services.webhooks import quo as quo_service
from app.services.webhooks.pipeline import WebhookDispatchResult

pytestmark = pytest.mark.asyncio

SIGNING_KEY = "whsec_" + base64.b64encode(b"q" * 32).decode()
INTEGRATION_ID = uuid.UUID("f0b8e811-242e-4b33-81ca-7e75a98a916f")
ORGANIZATION_ID = "OR_workspace_a"


def _payload(*, organization_id: str = ORGANIZATION_ID) -> dict[str, Any]:
    return {
        "id": "EV_test_1",
        "apiVersion": "2026-03-30",
        "type": "message.received",
        "createdAt": "2026-08-26T12:00:00Z",
        "data": {
            "context": {"orgId": organization_id},
            "resource": {"id": "AC_redacted"},
        },
    }


def _signed_headers(
    body: bytes,
    *,
    delivery_id: str = "msg_delivery_1",
    timestamp: int | None = None,
) -> dict[str, str]:
    signed_at = timestamp or int(time.time())
    signature = Webhook(SIGNING_KEY).sign(
        delivery_id,
        datetime.fromtimestamp(signed_at, UTC),
        body.decode(),
    )
    return {
        "content-type": "application/json",
        "webhook-id": delivery_id,
        "webhook-timestamp": str(signed_at),
        "webhook-signature": signature,
    }


def _integration(*, active: bool = True) -> MagicMock:
    integration = MagicMock()
    integration.id = INTEGRATION_ID
    integration.workspace_id = uuid.UUID("56d07054-d36d-4596-8d54-46b351603c93")
    integration.is_active = active
    integration.safe_credentials.return_value = {
        "api_key": "quo_api_key",
        "organization_id": ORGANIZATION_ID,
        "webhook_id": "12345",
        "webhook_signing_key": SIGNING_KEY,
        "webhook_api_version": "2026-03-30",
    }
    return integration


def _database(integration: MagicMock | None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = integration
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.in_transaction.return_value = True
    return db


async def _client(db: MagicMock) -> AsyncIterator[AsyncClient]:
    app = FastAPI()

    async def override_db() -> AsyncIterator[MagicMock]:
        yield db

    app.dependency_overrides[get_db] = override_db
    app.include_router(router, prefix="/webhooks/quo")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client


async def _post(
    db: MagicMock,
    body: bytes,
    headers: dict[str, str] | None = None,
) -> Any:
    async for client in _client(db):
        return await client.post(
            f"/webhooks/quo/{INTEGRATION_ID}",
            content=body,
            headers=headers,
        )
    raise AssertionError("test client did not start")


async def test_valid_delivery_is_verified_claimed_and_dispatched() -> None:
    body = json.dumps(_payload(), separators=(",", ":")).encode()
    claim = webhook_replay.SignatureClaim(webhook_replay.SignatureClaimOutcome.CLAIMED)
    with (
        patch.object(
            quo_service,
            "claim_webhook_signature",
            new=AsyncMock(return_value=claim),
        ) as claim_mock,
        patch(
            "app.api.webhooks.quo.QuoSyncService.process",
            new=AsyncMock(return_value=WebhookDispatchResult.processed()),
        ) as sync_mock,
    ):
        response = await _post(_database(_integration()), body, _signed_headers(body))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    claim_mock.assert_awaited_once()
    sync_mock.assert_awaited_once()
    assert claim_mock.await_args is not None
    assert claim_mock.await_args.args[:2] == ("quo", "msg_delivery_1")


async def test_malformed_voice_resource_is_rejected_without_leaking_details() -> None:
    body = json.dumps(_payload(), separators=(",", ":")).encode()
    claim = webhook_replay.SignatureClaim(webhook_replay.SignatureClaimOutcome.CLAIMED)
    with (
        patch.object(
            quo_service,
            "claim_webhook_signature",
            new=AsyncMock(return_value=claim),
        ),
        patch(
            "app.api.webhooks.quo.QuoSyncService.process",
            new=AsyncMock(side_effect=QuoSyncError("raw provider details")),
        ),
    ):
        response = await _post(_database(_integration()), body, _signed_headers(body))

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid Quo webhook resource"}


async def test_tampered_delivery_is_rejected_before_dedupe() -> None:
    signed_body = json.dumps(_payload(), separators=(",", ":")).encode()
    tampered_body = json.dumps(
        _payload(organization_id="OR_tampered"), separators=(",", ":")
    ).encode()
    with patch.object(
        quo_service,
        "claim_webhook_signature",
        new=AsyncMock(),
    ) as claim_mock:
        response = await _post(
            _database(_integration()),
            tampered_body,
            _signed_headers(signed_body),
        )

    assert response.status_code == 400
    claim_mock.assert_not_awaited()


async def test_malformed_signature_is_rejected_before_dedupe() -> None:
    body = json.dumps(_payload(), separators=(",", ":")).encode()
    headers = _signed_headers(body)
    headers["webhook-signature"] = "v1,invalid"
    with patch.object(
        quo_service,
        "claim_webhook_signature",
        new=AsyncMock(),
    ) as claim_mock:
        response = await _post(_database(_integration()), body, headers)

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid Quo webhook signature"}
    claim_mock.assert_not_awaited()


async def test_stale_delivery_is_rejected_before_signature_dispatch() -> None:
    body = json.dumps(_payload(), separators=(",", ":")).encode()
    stale_at = int(time.time()) - 301
    with patch.object(
        quo_service,
        "claim_webhook_signature",
        new=AsyncMock(),
    ) as claim_mock:
        response = await _post(
            _database(_integration()),
            body,
            _signed_headers(body, timestamp=stale_at),
        )

    assert response.status_code == 400
    claim_mock.assert_not_awaited()


async def test_replayed_delivery_is_acknowledged_without_dispatch() -> None:
    body = json.dumps(_payload(), separators=(",", ":")).encode()
    replay = webhook_replay.SignatureClaim(webhook_replay.SignatureClaimOutcome.REPLAY)
    with patch.object(
        quo_service,
        "claim_webhook_signature",
        new=AsyncMock(return_value=replay),
    ):
        response = await _post(_database(_integration()), body, _signed_headers(body))

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "deduped": "true",
        "reason": "already_processed",
    }


async def test_inactive_integration_is_rejected_before_body_trust() -> None:
    body = json.dumps(_payload(), separators=(",", ":")).encode()
    response = await _post(_database(None), body)

    assert response.status_code == 404


@pytest.mark.parametrize("body", [b"{}", b"{not-json"])
async def test_signed_malformed_delivery_is_rejected(body: bytes) -> None:
    with patch.object(
        quo_service,
        "claim_webhook_signature",
        new=AsyncMock(),
    ) as claim_mock:
        response = await _post(_database(_integration()), body, _signed_headers(body))

    assert response.status_code == 400
    claim_mock.assert_not_awaited()


async def test_cross_workspace_organization_is_rejected_after_verification() -> None:
    body = json.dumps(_payload(organization_id="OR_workspace_b"), separators=(",", ":")).encode()
    with patch.object(
        quo_service,
        "claim_webhook_signature",
        new=AsyncMock(),
    ) as claim_mock:
        response = await _post(_database(_integration()), body, _signed_headers(body))

    assert response.status_code == 403
    claim_mock.assert_not_awaited()


async def test_oversized_delivery_is_rejected_before_verification() -> None:
    body = b"x" * (QUO_MAX_BODY_BYTES + 1)
    with patch.object(
        quo_service,
        "claim_webhook_signature",
        new=AsyncMock(),
    ) as claim_mock:
        response = await _post(_database(_integration()), body)

    assert response.status_code == 413
    claim_mock.assert_not_awaited()
