from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock

import httpx
import pytest

from app.services.quo.backfill import QuoBackfillError, validate_backfill_window
from app.services.quo.client import QUO_WEBHOOK_API_VERSION, QuoApiError, QuoClient

FIXTURE_PATH = Path(__file__).parents[2] / "fixtures" / "quo" / "historical_pages.json"


def _fixture() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(FIXTURE_PATH.read_text()))


@pytest.mark.asyncio
async def test_historical_endpoints_paginate_on_v1_without_dated_header() -> None:
    fixture = _fixture()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        token = request.url.params.get("pageToken")
        if path == "/webhooks":
            return httpx.Response(200, json={"data": [{"orgId": "ORfixture"}]})
        if path == "/v1/phone-numbers":
            return httpx.Response(200, json=fixture["phone_numbers"])
        pages = fixture[path.removeprefix("/v1/").replace("messages", "messages")]
        page_index = 1 if token else 0
        return httpx.Response(200, json=pages[page_index])

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = QuoClient("fixture-key", client=http_client)

    assert await client.validate_api_key() == "ORfixture"
    assert len(await client.list_phone_numbers()) == 1
    contacts = [contact async for contact in client.iter_contacts()]
    conversations = [
        conversation
        async for conversation in client.iter_conversations(
            phone_number_ids=["PNfixture"],
            created_before="2026-08-08T00:00:00Z",
            updated_after="2026-08-01T00:00:00Z",
        )
    ]
    messages = [
        message
        async for message in client.iter_messages(
            phone_number_id="PNfixture",
            participant="+14155552672",
            created_after="2026-08-01T00:00:00Z",
            created_before="2026-08-08T00:00:00Z",
        )
    ]
    calls = [
        call
        async for call in client.iter_calls(
            phone_number_id="PNfixture",
            participant="+14155552672",
            created_after="2026-07-25T00:00:00Z",
            created_before="2026-08-08T00:00:00Z",
        )
    ]

    assert [item["id"] for item in contacts] == ["CTfixture", "CToutside"]
    assert [item["id"] for item in conversations] == ["CNfixture"]
    assert [item["id"] for item in messages] == ["ACmessage-in", "ACmessage-out"]
    assert [item["id"] for item in calls] == ["ACcall"]

    webhook_request = requests[0]
    assert webhook_request.headers["Quo-Api-Version"] == QUO_WEBHOOK_API_VERSION
    historical_requests = [request for request in requests if request.url.path.startswith("/v1/")]
    assert historical_requests
    assert all("Quo-Api-Version" not in request.headers for request in historical_requests)
    assert [
        request.url.params.get("pageToken")
        for request in requests
        if request.url.path == "/v1/contacts"
    ] == [None, "contacts-page-2"]
    assert [
        request.url.params.get("pageToken")
        for request in requests
        if request.url.path == "/v1/messages"
    ] == [None, "messages-page-2"]
    assert all(
        request.url.params.get("maxResults")
        == ("50" if request.url.path.endswith("contacts") else "100")
        for request in historical_requests
        if request.url.path != "/v1/phone-numbers"
    )

    await http_client.aclose()


def test_backfill_window_requires_two_bounded_utc_dates() -> None:
    since = datetime(2026, 7, 1, tzinfo=UTC)
    validate_backfill_window(since, since + timedelta(days=31))

    with pytest.raises(QuoBackfillError, match="earlier"):
        validate_backfill_window(since, since)
    with pytest.raises(QuoBackfillError, match="31 days"):
        validate_backfill_window(since, since + timedelta(days=31, seconds=1))
    with pytest.raises(QuoBackfillError, match="UTC offset"):
        validate_backfill_window(since.replace(tzinfo=None), since)


@pytest.mark.asyncio
async def test_api_errors_keep_provider_pii_out_of_exception_text() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"message": "Customer Fixture +14155552672 is forbidden"},
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = QuoClient("fixture-key", client=http_client)

    with pytest.raises(QuoApiError) as exc_info:
        await client.list_phone_numbers()
    assert exc_info.value.status_code == 403
    assert "Customer Fixture" not in str(exc_info.value)
    assert "+14155552672" not in str(exc_info.value)

    await http_client.aclose()


@pytest.mark.asyncio
async def test_rate_limit_retry_honors_provider_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "0.25"})
        return httpx.Response(200, json={"data": []})

    sleep = AsyncMock()
    monkeypatch.setattr("app.services.quo.client.asyncio.sleep", sleep)
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = QuoClient("fixture-key", client=http_client)

    assert await client.list_phone_numbers() == []
    assert attempts == 2
    assert any(call.args == (0.25,) for call in sleep.await_args_list)

    await http_client.aclose()
