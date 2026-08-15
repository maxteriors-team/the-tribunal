"""HTTP-boundary tests for verified Meta Lead Ads webhook ingestion."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.webhooks import meta as meta_module
from app.api.webhooks.meta import router as meta_router
from app.core.config import settings as app_settings
from app.db.session import get_db
from app.services.lead_sources.meta_lead_ads_service import (
    MetaLeadAdsError,
    MetaLeadAdsValidationError,
    MetaLeadProcessResult,
)


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


def _make_app(db: AsyncMock | None = None) -> FastAPI:
    app = FastAPI(lifespan=_test_lifespan)

    async def _override_db() -> AsyncIterator[AsyncMock]:
        yield db or AsyncMock()

    app.dependency_overrides[get_db] = _override_db
    app.include_router(meta_router, prefix="/webhooks/meta")
    return app


def _payload() -> dict[str, object]:
    return {
        "object": "page",
        "entry": [
            {
                "id": "page-1",
                "changes": [
                    {
                        "field": "leadgen",
                        "value": {"page_id": "page-1", "leadgen_id": "lead-1"},
                    },
                    # A duplicated change in one delivery must process once.
                    {
                        "field": "leadgen",
                        "value": {"page_id": "page-1", "leadgen_id": "lead-1"},
                    },
                ],
            }
        ],
    }


def _signed_headers(secret: str, body: bytes) -> dict[str, str]:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return {
        "content-type": "application/json",
        "x-hub-signature-256": f"sha256={digest}",
    }


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=_make_app()), base_url="http://testserver"
    ) as value:
        yield value


async def test_verification_challenge_requires_exact_token(client: AsyncClient) -> None:
    with patch.object(app_settings, "meta_lead_ads_verify_token", "verify-me"):
        accepted = await client.get(
            "/webhooks/meta/leadgen",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "verify-me",
                "hub.challenge": "challenge-value",
            },
        )
        rejected = await client.get(
            "/webhooks/meta/leadgen",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong",
                "hub.challenge": "challenge-value",
            },
        )

    assert accepted.status_code == 200
    assert accepted.text == "challenge-value"
    assert rejected.status_code == 403


async def test_missing_app_secret_refuses_unverified_delivery(client: AsyncClient) -> None:
    body = json.dumps(_payload()).encode()
    with patch.object(app_settings, "meta_lead_ads_app_secret", ""):
        response = await client.post(
            "/webhooks/meta/leadgen", content=body, headers={"content-type": "application/json"}
        )
    assert response.status_code == 503


async def test_invalid_signature_never_processes_lead(client: AsyncClient) -> None:
    body = json.dumps(_payload()).encode()
    process = AsyncMock()
    with (
        patch.object(app_settings, "meta_lead_ads_app_secret", "secret"),
        patch.object(meta_module, "process_meta_lead", process),
    ):
        response = await client.post(
            "/webhooks/meta/leadgen",
            content=body,
            headers={
                "content-type": "application/json",
                "x-hub-signature-256": "sha256=bad",
            },
        )
    assert response.status_code == 401
    process.assert_not_awaited()


async def test_valid_delivery_deduplicates_and_commits_each_lead() -> None:
    db = AsyncMock()
    body = json.dumps(_payload()).encode()
    process = AsyncMock(return_value=MetaLeadProcessResult("created", 42))
    async with AsyncClient(
        transport=ASGITransport(app=_make_app(db)), base_url="http://testserver"
    ) as client:
        with (
            patch.object(app_settings, "meta_lead_ads_app_secret", "secret"),
            patch.object(meta_module, "process_meta_lead", process),
        ):
            response = await client.post(
                "/webhooks/meta/leadgen",
                content=body,
                headers=_signed_headers("secret", body),
            )

    assert response.status_code == 200
    assert response.json() == {"received": True, "processed": 1, "ignored": 0}
    process.assert_awaited_once_with(db, page_id="page-1", leadgen_id="lead-1")
    db.commit.assert_awaited_once()


async def test_invalid_lead_does_not_drop_later_events_in_the_delivery() -> None:
    db = AsyncMock()
    payload = {
        "object": "page",
        "entry": [
            {
                "id": "page-1",
                "changes": [
                    {
                        "field": "leadgen",
                        "value": {"page_id": "page-1", "leadgen_id": "invalid-lead"},
                    },
                    {
                        "field": "leadgen",
                        "value": {"page_id": "page-1", "leadgen_id": "valid-lead"},
                    },
                ],
            }
        ],
    }
    body = json.dumps(payload).encode()
    process = AsyncMock(
        side_effect=[
            MetaLeadAdsValidationError("disconnected page"),
            MetaLeadProcessResult("created", 42),
        ]
    )
    async with AsyncClient(
        transport=ASGITransport(app=_make_app(db)), base_url="http://testserver"
    ) as client:
        with (
            patch.object(app_settings, "meta_lead_ads_app_secret", "secret"),
            patch.object(meta_module, "process_meta_lead", process),
        ):
            response = await client.post(
                "/webhooks/meta/leadgen",
                content=body,
                headers=_signed_headers("secret", body),
            )

    assert response.status_code == 200
    assert response.json() == {"received": True, "processed": 1, "ignored": 1}
    assert process.await_count == 2
    db.rollback.assert_awaited_once()
    db.commit.assert_awaited_once()


async def test_retryable_graph_failure_returns_503_and_rolls_back() -> None:
    db = AsyncMock()
    body = json.dumps(_payload()).encode()
    process = AsyncMock(side_effect=MetaLeadAdsError("temporary"))
    async with AsyncClient(
        transport=ASGITransport(app=_make_app(db)), base_url="http://testserver"
    ) as client:
        with (
            patch.object(app_settings, "meta_lead_ads_app_secret", "secret"),
            patch.object(meta_module, "process_meta_lead", process),
        ):
            response = await client.post(
                "/webhooks/meta/leadgen",
                content=body,
                headers=_signed_headers("secret", body),
            )

    assert response.status_code == 503
    db.rollback.assert_awaited_once()


async def test_payload_size_cap_is_enforced_before_signature_processing(
    client: AsyncClient,
) -> None:
    with patch.object(app_settings, "meta_lead_ads_max_webhook_bytes", 4):
        response = await client.post(
            "/webhooks/meta/leadgen",
            content=b"12345",
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 413
