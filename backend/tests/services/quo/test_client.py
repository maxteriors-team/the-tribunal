"""Tests for the minimal Quo API client."""

from __future__ import annotations

import httpx
import pytest

from app.services.quo.client import QUO_API_VERSION, QuoApiError, QuoClient


async def test_validate_api_key_uses_current_contract_and_returns_organization_id() -> None:
    api_key = "quo_test_secret_key"

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url == httpx.URL("https://api.quo.com/webhooks")
        assert request.headers["Authorization"] == api_key
        assert request.headers["Quo-Api-Version"] == QUO_API_VERSION == "2026-03-30"
        assert request.headers["Accept"] == "application/json"
        return httpx.Response(200, json={"data": [{"orgId": "OR123"}]})

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client,
        QuoClient(api_key, client=http_client) as quo,
    ):
        assert await quo.validate_api_key() == "OR123"


async def test_validate_api_key_accepts_an_account_without_webhooks() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json={"data": []}))

    async with (
        httpx.AsyncClient(transport=transport) as http_client,
        QuoClient("quo_test_key", client=http_client) as quo,
    ):
        assert await quo.validate_api_key() is None


async def test_client_errors_never_include_key_or_provider_body() -> None:
    api_key = "quo_do_not_expose"
    provider_body = f"rejected {api_key}"
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(401, json={"message": provider_body})
    )

    async with (
        httpx.AsyncClient(transport=transport) as http_client,
        QuoClient(api_key, client=http_client) as quo,
    ):
        with pytest.raises(QuoApiError) as exc_info:
            await quo.validate_api_key()

    rendered_error = repr(exc_info.value)
    assert exc_info.value.status_code == 401
    assert api_key not in rendered_error
    assert provider_body not in rendered_error
