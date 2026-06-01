"""Tests for Cal.com requests through the shared provider HTTP client.

Covers the narrowed retry policy:
- 4xx responses are terminal (no retry).
- 5xx responses retry with exponential backoff + jitter.
- Network/timeout errors retry, then surface CalComError on exhaustion.
- Retry-After header is honored, accepting both delta-seconds and HTTP-date.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.services.calendar.calcom import (
    CalComError,
    CalComNotFoundError,
    CalComRateLimitError,
    CalComService,
    _parse_retry_after,
)


@pytest.fixture
def service() -> CalComService:
    return CalComService(api_key="test-key")


@pytest.fixture(autouse=True)
def _no_sleep() -> Iterator[AsyncMock]:
    """Make provider retry sleeps instant so retry loops run quickly."""
    with patch(
        "app.services.providers.http.asyncio.sleep", new=AsyncMock(return_value=None)
    ) as mock_sleep:
        yield mock_sleep


@pytest.fixture(autouse=True)
def _deterministic_jitter() -> Iterator[object]:
    """Pin shared provider jitter so retry assertions are deterministic."""
    with patch("app.services.providers.http.random.uniform", return_value=0.0) as mock_uniform:
        yield mock_uniform


def _client_from_responses(
    responses: list[httpx.Response | httpx.TransportError],
) -> tuple[httpx.AsyncClient, list[httpx.Request]]:
    """Return a raw client backed by MockTransport and capture requests."""
    requests: list[httpx.Request] = []
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        item = queue.pop(0)
        if isinstance(item, httpx.TransportError):
            raise item
        return item

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.cal.com/v2",
        headers={
            "Authorization": "Bearer test-key",
            "cal-api-version": "2024-08-13",
        },
    )
    return client, requests


# ---------------------------------------------------------------------------
# 4xx — no retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_4xx_client_error_is_not_retried(
    service: CalComService, _no_sleep: AsyncMock
) -> None:
    client, requests = _client_from_responses([httpx.Response(400, text="bad request")])
    try:
        with pytest.raises(CalComError) as excinfo:
            await service._request_with_retry("GET", "/x", client)
    finally:
        await client.aclose()

    assert "bad request" in str(excinfo.value)
    assert len(requests) == 1
    assert _no_sleep.await_count == 0


@pytest.mark.asyncio
async def test_404_raises_not_found_without_retry(service: CalComService) -> None:
    client, requests = _client_from_responses([httpx.Response(404)])
    try:
        with pytest.raises(CalComNotFoundError):
            await service._request_with_retry("GET", "/x", client)
    finally:
        await client.aclose()

    assert len(requests) == 1


# ---------------------------------------------------------------------------
# 5xx — retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_5xx_retries_then_succeeds(
    service: CalComService, _no_sleep: AsyncMock
) -> None:
    client, requests = _client_from_responses(
        [
            httpx.Response(500, text="boom"),
            httpx.Response(502, text="bad gateway"),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    try:
        result = await service._request_with_retry("GET", "/x", client)
    finally:
        await client.aclose()

    assert result == {"ok": True}
    assert len(requests) == 3
    assert _no_sleep.await_count == 2


@pytest.mark.asyncio
async def test_5xx_exhausts_retries_and_raises(service: CalComService) -> None:
    client, requests = _client_from_responses(
        [
            httpx.Response(503, text="unavailable"),
            httpx.Response(503, text="unavailable"),
            httpx.Response(503, text="unavailable"),
        ]
    )
    try:
        with pytest.raises(CalComError):
            await service._request_with_retry("GET", "/x", client)
    finally:
        await client.aclose()

    assert len(requests) == 3


# ---------------------------------------------------------------------------
# Network / timeout — retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_network_error_retries_then_succeeds(service: CalComService) -> None:
    client, requests = _client_from_responses(
        [
            httpx.ConnectError("connection refused"),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    try:
        result = await service._request_with_retry("GET", "/x", client)
    finally:
        await client.aclose()

    assert result == {"ok": True}
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_timeout_retries_then_exhausts(service: CalComService) -> None:
    client, requests = _client_from_responses(
        [
            httpx.ReadTimeout("timed out"),
            httpx.ReadTimeout("timed out"),
            httpx.ReadTimeout("timed out"),
        ]
    )
    try:
        with pytest.raises(CalComError, match="timeout"):
            await service._request_with_retry("GET", "/x", client)
    finally:
        await client.aclose()

    assert len(requests) == 3


@pytest.mark.asyncio
async def test_unrelated_exception_is_not_retried(service: CalComService) -> None:
    """RuntimeError (or any non-httpx exception) must bubble immediately."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise RuntimeError("unexpected")

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.cal.com/v2",
    )
    try:
        with pytest.raises(RuntimeError, match="unexpected"):
            await service._request_with_retry("GET", "/x", client)
    finally:
        await client.aclose()

    assert len(requests) == 1


# ---------------------------------------------------------------------------
# Retry-After header
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_after_integer_seconds_is_honored(
    service: CalComService, _no_sleep: AsyncMock
) -> None:
    client, _requests = _client_from_responses(
        [
            httpx.Response(429, headers={"retry-after": "7"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    try:
        result = await service._request_with_retry("GET", "/x", client)
    finally:
        await client.aclose()

    assert result == {"ok": True}
    _no_sleep.assert_awaited_once_with(7.0)


@pytest.mark.asyncio
async def test_retry_after_http_date_is_honored(
    service: CalComService, _no_sleep: AsyncMock
) -> None:
    future = datetime.now(UTC) + timedelta(seconds=12)
    http_date = format_datetime(future, usegmt=True)

    client, _requests = _client_from_responses(
        [
            httpx.Response(429, headers={"retry-after": http_date}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    try:
        result = await service._request_with_retry("GET", "/x", client)
    finally:
        await client.aclose()

    assert result == {"ok": True}
    _no_sleep.assert_awaited_once()
    assert _no_sleep.await_args is not None
    slept_for = _no_sleep.await_args.args[0]
    assert 0 <= slept_for <= 13


@pytest.mark.asyncio
async def test_retry_after_past_http_date_clamps_to_zero(
    service: CalComService, _no_sleep: AsyncMock
) -> None:
    past = datetime.now(UTC) - timedelta(seconds=30)
    http_date = format_datetime(past, usegmt=True)

    client, _requests = _client_from_responses(
        [
            httpx.Response(429, headers={"retry-after": http_date}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    try:
        await service._request_with_retry("GET", "/x", client)
    finally:
        await client.aclose()

    _no_sleep.assert_awaited_once_with(0.0)


@pytest.mark.asyncio
async def test_429_exhausts_retries_raises_rate_limit_error(service: CalComService) -> None:
    client, requests = _client_from_responses(
        [
            httpx.Response(429, headers={"retry-after": "1"}),
            httpx.Response(429, headers={"retry-after": "1"}),
            httpx.Response(429, headers={"retry-after": "1"}),
        ]
    )
    try:
        with pytest.raises(CalComRateLimitError):
            await service._request_with_retry("GET", "/x", client)
    finally:
        await client.aclose()

    assert len(requests) == 3


# ---------------------------------------------------------------------------
# Jitter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backoff_includes_random_jitter(
    service: CalComService, _no_sleep: AsyncMock
) -> None:
    """random.uniform(0, backoff_seconds) is added to the current backoff each retry."""
    with patch("app.services.providers.http.random.uniform", return_value=0.5) as mock_uniform:
        client, _requests = _client_from_responses(
            [
                httpx.Response(500),
                httpx.Response(500),
                httpx.Response(200, json={"ok": True}),
            ]
        )
        try:
            await service._request_with_retry("GET", "/x", client)
        finally:
            await client.aclose()

    sleeps = [call.args[0] for call in _no_sleep.await_args_list]
    assert sleeps == [1.0, 1.5]
    assert mock_uniform.call_count == 2


# ---------------------------------------------------------------------------
# _parse_retry_after — direct unit tests
# ---------------------------------------------------------------------------


def test_parse_retry_after_returns_fallback_when_missing() -> None:
    assert _parse_retry_after(None, fallback=4.0) == 4.0


def test_parse_retry_after_returns_fallback_when_empty() -> None:
    assert _parse_retry_after("   ", fallback=2.5) == 2.5


def test_parse_retry_after_parses_integer() -> None:
    assert _parse_retry_after("15", fallback=1.0) == 15.0


def test_parse_retry_after_parses_http_date() -> None:
    future = datetime.now(UTC) + timedelta(seconds=20)
    result = _parse_retry_after(format_datetime(future, usegmt=True), fallback=1.0)
    assert 18 <= result <= 21


def test_parse_retry_after_malformed_returns_fallback() -> None:
    assert _parse_retry_after("not a date", fallback=3.0) == 3.0
