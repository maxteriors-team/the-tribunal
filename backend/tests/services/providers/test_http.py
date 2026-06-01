"""Tests for the shared async provider HTTP client."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.providers.http import (
    REDACTED,
    AsyncProviderHTTPClient,
    ProviderAuthError,
    ProviderInvalidJSONError,
    ProviderResponseError,
    ProviderRetryPolicy,
    ProviderTransportError,
    redact_headers,
    redact_json,
)


@pytest.fixture(autouse=True)
def _no_sleep() -> Iterator[AsyncMock]:
    with patch(
        "app.services.providers.http.asyncio.sleep", new=AsyncMock(return_value=None)
    ) as mock_sleep:
        yield mock_sleep


def _provider_client(
    responses: list[httpx.Response | httpx.TransportError],
    *,
    logger: MagicMock | None = None,
) -> tuple[AsyncProviderHTTPClient, list[httpx.Request]]:
    requests: list[httpx.Request] = []
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        item = queue.pop(0)
        if isinstance(item, httpx.TransportError):
            raise item
        return item

    client = AsyncProviderHTTPClient(
        provider="example",
        base_url="https://provider.example/v1",
        headers={"Authorization": "Bearer secret"},
        retry_policy=ProviderRetryPolicy(max_attempts=3),
        logger=logger,
        transport=httpx.MockTransport(handler),
    )
    return client, requests


def test_redact_headers_removes_authorization() -> None:
    assert redact_headers({"Authorization": "Bearer secret", "X-Trace": "abc"}) == {
        "Authorization": REDACTED,
        "X-Trace": "abc",
    }


def test_redact_json_recurses_without_mutating_original() -> None:
    original = {
        "name": "safe",
        "token": "secret",
        "nested": [{"api_key": "secret", "value": 3}],
    }

    result = redact_json(original)

    assert result == {
        "name": "safe",
        "nested": [{"api_key": REDACTED, "value": 3}],
        "token": REDACTED,
    }
    assert original["token"] == "secret"


@pytest.mark.asyncio
async def test_retries_5xx_then_returns_json(_no_sleep: AsyncMock) -> None:
    client, requests = _provider_client(
        [
            httpx.Response(500, json={"error": "temporarily down"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    try:
        result = await client.get_json("/resource")
    finally:
        await client.aclose()

    assert result == {"ok": True}
    assert [request.url.path for request in requests] == ["/v1/resource", "/v1/resource"]
    _no_sleep.assert_awaited_once_with(1.0)


@pytest.mark.asyncio
async def test_4xx_is_typed_and_not_retried(_no_sleep: AsyncMock) -> None:
    client, requests = _provider_client([httpx.Response(401, json={"error": "bad auth"})])
    try:
        with pytest.raises(ProviderAuthError) as excinfo:
            await client.get_json("/resource")
    finally:
        await client.aclose()

    assert excinfo.value.status_code == 401
    assert excinfo.value.message == "bad auth"
    assert len(requests) == 1
    assert _no_sleep.await_count == 0


@pytest.mark.asyncio
async def test_transport_error_retries_then_raises_typed_error() -> None:
    client, requests = _provider_client(
        [
            httpx.ConnectError("no route"),
            httpx.ConnectError("no route"),
            httpx.ConnectError("no route"),
        ]
    )
    try:
        with pytest.raises(ProviderTransportError) as excinfo:
            await client.get_json("/resource")
    finally:
        await client.aclose()

    assert excinfo.value.retryable is True
    assert len(requests) == 3


@pytest.mark.asyncio
async def test_invalid_json_is_typed() -> None:
    client, _requests = _provider_client([httpx.Response(200, text="not-json")])
    try:
        with pytest.raises(ProviderInvalidJSONError):
            await client.get_json("/resource")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_failed_request_logs_redacted_url_without_query() -> None:
    logger = MagicMock()
    bound_logger = MagicMock()
    logger.bind.return_value = bound_logger
    client, _requests = _provider_client(
        [
            httpx.Response(
                400,
                json={
                    "error": "bad request",
                    "token": "body-secret",
                },
            )
        ],
        logger=logger,
    )

    try:
        with pytest.raises(ProviderResponseError):
            await client.get_json("/resource", params={"token": "query-secret"})
    finally:
        await client.aclose()

    bound_logger.warning.assert_called()
    log_kwargs = bound_logger.warning.call_args.kwargs
    assert log_kwargs["url"] == "https://provider.example/v1/resource"
    assert log_kwargs["response_body"] == '{"error": "bad request", "token": "[REDACTED]"}'
    assert "query-secret" not in str(log_kwargs)
    assert "body-secret" not in str(log_kwargs)
