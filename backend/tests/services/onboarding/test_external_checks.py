"""Unit tests for external Cal.com onboarding checks."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest

from app.services.onboarding.exceptions import (
    OnboardingExternalServiceError,
    OnboardingUnprocessableError,
)
from app.services.onboarding.external_checks import (
    parse_calcom_booking_url,
    resolve_calcom_event_type_id,
    verify_calcom_api_key,
)


def _client_factory(handler: httpx.MockTransport) -> object:
    @asynccontextmanager
    async def factory() -> AsyncIterator[httpx.AsyncClient]:
        async with httpx.AsyncClient(transport=handler) as client:
            yield client

    return factory


def test_parse_calcom_booking_url_accepts_app_subdomain() -> None:
    parsed = parse_calcom_booking_url("https://app.cal.com/jane-agent/consultation?month=2026-06")

    assert parsed.username == "jane-agent"
    assert parsed.slug == "consultation"


def test_parse_calcom_booking_url_rejects_non_calcom_url() -> None:
    with pytest.raises(OnboardingUnprocessableError) as exc_info:
        parse_calcom_booking_url("https://example.com/jane/consultation")

    assert "expected Cal.com format" in exc_info.value.message


async def test_resolve_calcom_event_type_id_uses_v2_lookup() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": [
                    {"id": 123, "slug": "listing-consult"},
                    {"id": 456, "slug": "buyer-call"},
                ],
            },
        )

    result = await resolve_calcom_event_type_id(
        url="https://cal.com/jane/listing-consult",
        api_key="cal_test_key",
        client_factory=_client_factory(httpx.MockTransport(handler)),
    )

    assert result.event_type_id == 123
    assert result.username == "jane"
    assert result.slug == "listing-consult"
    assert requests[0].url.params["username"] == "jane"
    assert requests[0].url.params["slug"] == "listing-consult"
    assert requests[0].headers["authorization"] == "Bearer cal_test_key"
    assert requests[0].headers["cal-api-version"] == "2024-08-13"


async def test_resolve_calcom_event_type_id_maps_unauthorized_to_external_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid"})

    with pytest.raises(OnboardingExternalServiceError) as exc_info:
        await resolve_calcom_event_type_id(
            url="https://cal.com/jane/listing-consult",
            api_key="bad_key",
            client_factory=_client_factory(httpx.MockTransport(handler)),
        )

    assert exc_info.value.message == "Could not reach Cal.com — check your API key"


async def test_resolve_calcom_event_type_id_rejects_missing_slug() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": 456, "slug": "buyer-call"}]})

    with pytest.raises(OnboardingUnprocessableError) as exc_info:
        await resolve_calcom_event_type_id(
            url="https://cal.com/jane/listing-consult",
            api_key="cal_test_key",
            client_factory=_client_factory(httpx.MockTransport(handler)),
        )

    assert "No event type with slug 'listing-consult'" in exc_info.value.message


async def test_verify_calcom_api_key_returns_username() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"user": {"username": "jane"}})

    result = await verify_calcom_api_key(
        "cal_test_key",
        client_factory=_client_factory(httpx.MockTransport(handler)),
    )

    assert result.valid is True
    assert result.username == "jane"


async def test_verify_calcom_api_key_returns_invalid_for_401() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid"})

    result = await verify_calcom_api_key(
        "bad_key",
        client_factory=_client_factory(httpx.MockTransport(handler)),
    )

    assert result.valid is False
    assert result.username is None
