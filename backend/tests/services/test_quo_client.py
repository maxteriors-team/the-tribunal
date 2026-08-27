"""Quo API client contract tests."""

from __future__ import annotations

import json

import httpx
import pytest

from app.services.quo.client import (
    QUO_API_VERSION,
    QUO_WEBHOOK_EVENTS,
    QuoApiError,
    QuoClient,
)

pytestmark = pytest.mark.asyncio


async def test_create_webhook_subscribes_one_target_for_all_resources() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            201,
            json={
                "data": {
                    "id": "12345",
                    "orgId": "OR_workspace",
                    "key": "whsec_signing_key",
                    "apiVersion": QUO_API_VERSION,
                }
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = QuoClient("quo_secret", client=http_client)
        credentials = await client.create_webhook(
            "https://api.example.com/webhooks/quo/integration-id"
        )

    assert credentials.webhook_id == "12345"
    assert credentials.organization_id == "OR_workspace"
    assert seen[0].url == "https://api.quo.com/webhooks"
    assert seen[0].headers["Authorization"] == "quo_secret"
    assert seen[0].headers["Quo-Api-Version"] == QUO_API_VERSION
    body = json.loads(seen[0].content)
    assert body == {
        "events": list(QUO_WEBHOOK_EVENTS),
        "url": "https://api.example.com/webhooks/quo/integration-id",
        "resourceIds": ["*"],
        "status": "enabled",
        "label": "The Tribunal",
    }


async def test_remove_webhook_disables_when_delete_fails() -> None:
    seen: list[tuple[str, str, dict[str, str] | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        seen.append((request.method, request.url.path, body))
        if request.method == "DELETE":
            return httpx.Response(500)
        return httpx.Response(200, json={"data": {"status": "disabled"}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = QuoClient("quo_secret", client=http_client)
        await client.remove_webhook("12345")

    assert seen == [
        ("DELETE", "/webhooks/12345", None),
        ("PATCH", "/webhooks/12345", {"status": "disabled"}),
    ]


async def test_create_webhook_rejects_missing_one_time_signing_key() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            201,
            json={
                "data": {
                    "id": "12345",
                    "orgId": "OR_workspace",
                    "apiVersion": QUO_API_VERSION,
                }
            },
        )
    )
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = QuoClient("quo_secret", client=http_client)
        with pytest.raises(QuoApiError, match="invalid webhook data"):
            await client.create_webhook("https://api.example.com/webhooks/quo/id")


async def test_get_user_uses_current_user_endpoint_without_webhook_version() -> None:
    user_id = "US_sender_123"
    response_data = {
        "id": user_id,
        "firstName": "Ada",
        "lastName": "Lovelace",
        "email": "ada@example.com",
    }
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": response_data})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = QuoClient("quo_secret", client=http_client)
        get_user = getattr(client, "get_user", None)
        assert callable(get_user), "QuoClient.get_user is not implemented"
        user = await get_user(user_id)

    assert user == response_data
    assert len(seen) == 1
    assert seen[0].method == "GET"
    assert seen[0].url == httpx.URL(f"https://api.quo.com/v1/users/{user_id}")
    assert "Quo-Api-Version" not in seen[0].headers
