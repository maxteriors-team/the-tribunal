"""External Cal.com checks used by the realtor onboarding flow."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from app.services.onboarding.exceptions import (
    OnboardingExternalServiceError,
    OnboardingUnprocessableError,
)

logger = structlog.get_logger()

_CALCOM_URL_RE = re.compile(r"^https?://(?:app\.)?cal\.com/([^/?#]+)/([^/?#]+)")
_CALCOM_V1_BASE = "https://api.cal.com/v1"
_CALCOM_V2_BASE = "https://api.cal.com/v2"


@dataclass(slots=True, frozen=True)
class ParsedCalcomUrl:
    """Parsed Cal.com event-type URL components."""

    username: str
    slug: str


@dataclass(slots=True, frozen=True)
class CalcomEventTypeLookup:
    """Resolved Cal.com event type metadata."""

    event_type_id: int
    slug: str
    username: str


@dataclass(slots=True, frozen=True)
class CalcomVerification:
    """Result of verifying a Cal.com API key."""

    valid: bool
    username: str | None


CalcomClientFactory = Callable[[], AbstractAsyncContextManager[httpx.AsyncClient]]


@asynccontextmanager
async def default_calcom_client_factory() -> AsyncIterator[httpx.AsyncClient]:
    """Yield the default HTTP client for Cal.com API calls."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        yield client


def parse_calcom_booking_url(url: str) -> ParsedCalcomUrl:
    """Parse a Cal.com booking URL into username and event slug."""
    match = _CALCOM_URL_RE.match(url.strip())
    if match is None:
        raise OnboardingUnprocessableError(
            "URL does not match expected Cal.com format: "
            "https://cal.com/{username}/{slug} or "
            "https://app.cal.com/{username}/{slug}"
        )
    return ParsedCalcomUrl(username=match.group(1), slug=match.group(2))


def _extract_event_types(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Return event type dictionaries from known Cal.com v2 response shapes."""
    data = body.get("data", [])
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        event_groups = data.get("eventTypeGroups", []) or []
        return [item for item in event_groups if isinstance(item, dict)]
    return []


def _matched_event_type_id(
    event_types: list[dict[str, Any]],
    slug: str,
) -> int | None:
    """Return the integer event type ID whose slug matches the booking URL."""
    for event_type in event_types:
        if event_type.get("slug") != slug:
            continue
        event_type_id = event_type.get("id")
        if isinstance(event_type_id, int):
            return event_type_id
        if isinstance(event_type_id, str) and event_type_id.isdigit():
            return int(event_type_id)
    return None


async def resolve_calcom_event_type_id(
    *,
    url: str,
    api_key: str,
    client_factory: CalcomClientFactory = default_calcom_client_factory,
) -> CalcomEventTypeLookup:
    """Resolve a Cal.com booking URL to an event type ID using the v2 API."""
    parsed = parse_calcom_booking_url(url)

    try:
        async with client_factory() as client:
            response = await client.get(
                f"{_CALCOM_V2_BASE}/event-types",
                params={"username": parsed.username, "slug": parsed.slug},
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "cal-api-version": "2024-08-13",
                },
            )
    except (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError) as exc:
        logger.error("calcom_parse_url_network_error", error=str(exc))
        raise OnboardingExternalServiceError(
            "Could not reach Cal.com — check your API key"
        ) from exc

    if response.status_code == 401:
        raise OnboardingExternalServiceError("Could not reach Cal.com — check your API key")

    if response.status_code != 200:
        logger.warning(
            "calcom_event_type_lookup_failed",
            status_code=response.status_code,
            username=parsed.username,
            slug=parsed.slug,
        )
        raise OnboardingExternalServiceError("Could not reach Cal.com — check your API key")

    body = response.json()
    if not isinstance(body, dict):
        raise OnboardingExternalServiceError("Could not reach Cal.com — check your API key")

    matched_id = _matched_event_type_id(_extract_event_types(body), parsed.slug)
    if matched_id is None:
        raise OnboardingUnprocessableError(
            f"No event type with slug '{parsed.slug}' found for Cal.com user '{parsed.username}'. "
            "Double-check the URL."
        )

    logger.info(
        "calcom_url_parsed",
        username=parsed.username,
        slug=parsed.slug,
        event_type_id=matched_id,
    )

    return CalcomEventTypeLookup(
        event_type_id=matched_id,
        slug=parsed.slug,
        username=parsed.username,
    )


async def verify_calcom_api_key(
    api_key: str,
    client_factory: CalcomClientFactory = default_calcom_client_factory,
) -> CalcomVerification:
    """Verify a Cal.com API key by calling the v1 /me endpoint."""
    try:
        async with client_factory() as client:
            response = await client.get(
                f"{_CALCOM_V1_BASE}/me",
                params={"apiKey": api_key},
            )
    except (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError) as exc:
        logger.error("calcom_verify_network_error", error=str(exc))
        raise OnboardingExternalServiceError(
            "Could not reach Cal.com — check your network connection"
        ) from exc

    if response.status_code == 401:
        return CalcomVerification(valid=False, username=None)

    if response.status_code != 200:
        logger.warning(
            "calcom_verify_unexpected_status",
            status_code=response.status_code,
        )
        raise OnboardingExternalServiceError(
            "Could not reach Cal.com — check your network connection"
        )

    body = response.json()
    if not isinstance(body, dict):
        raise OnboardingExternalServiceError(
            "Could not reach Cal.com — check your network connection"
        )

    user_data = body.get("user") or body.get("data") or body
    username: str | None = None
    if isinstance(user_data, dict):
        raw_username = user_data.get("username")
        username = raw_username if isinstance(raw_username, str) and raw_username else None

    logger.info("calcom_key_verified", username=username)
    return CalcomVerification(valid=True, username=username)
