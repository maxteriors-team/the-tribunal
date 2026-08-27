"""Async client for Quo's versioned, workspace-scoped REST API."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote

import httpx

from app.utils.phone import normalize_phone_safe

QUO_API_BASE_URL = "https://api.quo.com"
# Dated endpoints verified against Quo's versioned API docs on 2026-08-26:
# https://www.quo.com/docs/2026-03-30/introduction
QUO_WEBHOOK_API_VERSION = "2026-03-30"
QUO_CONTACT_API_VERSION = QUO_WEBHOOK_API_VERSION
# Historical list endpoints are only supported by Quo's path-versioned v1 API:
# https://www.quo.com/docs/mdx/api-reference/{contacts,messages,calls}/list-*.md
QUO_HISTORICAL_API_VERSION = "v1"
# Backwards-compatible name used by webhook parsing and stored integration metadata.
QUO_API_VERSION = QUO_WEBHOOK_API_VERSION
QUO_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0)
_MIN_REQUEST_INTERVAL_SECONDS = 0.1  # Quo documents a 10 request/second limit.
_MAX_RATE_LIMIT_RETRIES = 5
_MAX_RETRY_DELAY_SECONDS = 300.0
_MAX_PAGES = 10_000
QUO_WEBHOOK_EVENTS = (
    "message.received",
    "message.delivered",
    "message.failed",
    "message.undelivered",
    "call.ringing",
    "call.answered",
    "call.completed",
    "call.missed",
    "call.forwarded",
    "call.menu.selected",
    "call.recording.completed",
    "call.transcript.completed",
    "call.summary.completed",
    "call.voicemail.completed",
)


class QuoApiError(RuntimeError):
    """Quo rejected a request or returned an unusable response."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class QuoPhoneNumber:
    """Validated sender metadata safe to expose outside credential storage."""

    id: str
    phone_number: str
    provider_label: str | None = None

    def as_public_dict(self) -> dict[str, str | None]:
        return {
            "id": self.id,
            "phone_number": self.phone_number,
            "provider_label": self.provider_label,
        }


@dataclass(frozen=True, slots=True)
class QuoWebhookCredentials:
    """Secret metadata returned exactly once when Quo creates a webhook."""

    webhook_id: str
    signing_key: str
    organization_id: str
    api_version: str

    def as_encrypted_credentials(self) -> dict[str, str]:
        return {
            "webhook_id": self.webhook_id,
            "webhook_signing_key": self.signing_key,
            "organization_id": self.organization_id,
            "webhook_api_version": self.api_version,
        }


class QuoClient:
    """Small Quo client that never logs credentials or provider response bodies."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = QUO_API_BASE_URL,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        normalized_key = api_key.strip()
        if not normalized_key:
            raise QuoApiError("A Quo API key is required")

        self._headers = {
            "Accept": "application/json",
            "Authorization": normalized_key,
            "Content-Type": "application/json",
        }
        self._base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=QUO_TIMEOUT,
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
        )
        self._request_lock = asyncio.Lock()
        self._next_request_at = 0.0

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        api_version: str | None = QUO_WEBHOOK_API_VERSION,
    ) -> dict[str, Any]:
        headers = dict(self._headers)
        if api_version is not None:
            headers["Quo-Api-Version"] = api_version

        response: httpx.Response | None = None
        for attempt in range(_MAX_RATE_LIMIT_RETRIES + 1):
            await self._wait_for_request_slot()
            try:
                response = await self._client.request(
                    method,
                    f"{self._base_url}{path}",
                    headers=headers,
                    params=params,
                    json=json,
                )
            except httpx.HTTPError:
                # The original exception retains the authenticated request.
                raise QuoApiError("Quo API request failed") from None

            if response.status_code != 429 or attempt == _MAX_RATE_LIMIT_RETRIES:
                break
            await asyncio.sleep(_retry_delay_seconds(response, attempt))

        if response is None:  # pragma: no cover - the bounded loop always sends once
            raise QuoApiError("Quo API request failed")
        if response.status_code >= 400:
            # Provider bodies can contain customer data and are intentionally omitted.
            raise QuoApiError(
                f"Quo API returned HTTP {response.status_code}",
                status_code=response.status_code,
            )
        if response.status_code == 204 or not response.content:
            return {}

        try:
            payload = response.json()
        except ValueError:
            raise QuoApiError(
                "Quo API returned invalid JSON",
                status_code=response.status_code,
            ) from None
        if not isinstance(payload, dict):
            raise QuoApiError("Quo API returned an invalid response")
        return payload

    async def _wait_for_request_slot(self) -> None:
        async with self._request_lock:
            delay = self._next_request_at - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            self._next_request_at = time.monotonic() + _MIN_REQUEST_INTERVAL_SECONDS

    async def _paginate(
        self,
        path: str,
        *,
        params: dict[str, Any],
        page_size: int,
    ) -> AsyncIterator[dict[str, Any]]:
        page_token: str | None = None
        seen_tokens: set[str] = set()

        for _page_number in range(_MAX_PAGES):
            query = {**params, "maxResults": page_size}
            if page_token is not None:
                query["pageToken"] = page_token
            payload = await self._request(
                "GET",
                path,
                params=query,
                api_version=None,  # /v1 pins the historical API; dated headers are unsupported.
            )
            data = payload.get("data")
            next_page_token = payload.get("nextPageToken")
            if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
                raise QuoApiError("Quo API returned invalid pagination data")
            if next_page_token is not None and not isinstance(next_page_token, str):
                raise QuoApiError("Quo API returned invalid pagination data")

            for item in data:
                yield item

            if not next_page_token:
                return
            if next_page_token in seen_tokens:
                raise QuoApiError("Quo API repeated a pagination token")
            seen_tokens.add(next_page_token)
            page_token = next_page_token

        raise QuoApiError("Quo API pagination exceeded the safety limit")

    async def list_phone_numbers(self) -> list[QuoPhoneNumber]:
        """Return only validated, normalized sender choices from Quo."""
        payload = await self._request(
            "GET",
            f"/{QUO_HISTORICAL_API_VERSION}/phone-numbers",
            api_version=None,
        )
        data = payload.get("data")
        if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
            raise QuoApiError("Quo API returned invalid phone number data")

        phone_numbers = [_parse_phone_number(item) for item in data]
        by_id: dict[str, QuoPhoneNumber] = {}
        for phone_number in phone_numbers:
            existing = by_id.get(phone_number.id)
            if existing is not None and existing != phone_number:
                raise QuoApiError("Quo API returned conflicting phone number data")
            by_id[phone_number.id] = phone_number
        return list(by_id.values())

    def iter_contacts(self) -> AsyncIterator[dict[str, Any]]:
        """Iterate every v1 contact page; callers must apply their date bound."""
        return self._paginate(
            f"/{QUO_HISTORICAL_API_VERSION}/contacts",
            params={},
            page_size=50,
        )

    def iter_conversations(
        self,
        *,
        phone_number_ids: list[str],
        created_before: str,
        updated_after: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Iterate conversations that can contain activity in the requested window."""
        return self._paginate(
            f"/{QUO_HISTORICAL_API_VERSION}/conversations",
            params={
                "phoneNumbers": phone_number_ids,
                "createdBefore": created_before,
                "updatedAfter": updated_after,
                "excludeInactive": False,
            },
            page_size=100,
        )

    def iter_messages(
        self,
        *,
        phone_number_id: str,
        participant: str,
        created_after: str,
        created_before: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Iterate historical texts through v1; the dated webhook API cannot list them."""
        return self._paginate(
            f"/{QUO_HISTORICAL_API_VERSION}/messages",
            params={
                "phoneNumberId": phone_number_id,
                "participants": [participant],
                "createdAfter": created_after,
                "createdBefore": created_before,
            },
            page_size=100,
        )

    def iter_calls(
        self,
        *,
        phone_number_id: str,
        participant: str,
        created_after: str,
        created_before: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Iterate historical calls through the path-versioned v1 API."""
        return self._paginate(
            f"/{QUO_HISTORICAL_API_VERSION}/calls",
            params={
                "phoneNumberId": phone_number_id,
                "participants": [participant],
                "createdAfter": created_after,
                "createdBefore": created_before,
            },
            page_size=100,
        )

    async def validate_api_key(self) -> str | None:
        """Validate the key and return an organization ID when one exists."""
        payload = await self._request("GET", "/webhooks")
        webhooks = payload.get("data")
        if not isinstance(webhooks, list):
            raise QuoApiError("Quo API returned an invalid response")

        organization_ids = {
            organization_id
            for webhook in webhooks
            if isinstance(webhook, dict)
            and isinstance((organization_id := webhook.get("orgId")), str)
            and organization_id.startswith("OR")
        }
        if len(organization_ids) > 1:
            raise QuoApiError("Quo API returned conflicting tenant data")
        return next(iter(organization_ids), None)

    async def create_webhook(self, target_url: str) -> QuoWebhookCredentials:
        """Create one enabled webhook for all Quo phone numbers and contacts."""
        payload = await self._request(
            "POST",
            "/webhooks",
            json={
                "events": list(QUO_WEBHOOK_EVENTS),
                "url": target_url,
                "resourceIds": ["*"],
                "status": "enabled",
                "label": "The Tribunal",
            },
        )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise QuoApiError("Quo API returned invalid webhook data")

        webhook_id = data.get("id")
        signing_key = data.get("key")
        organization_id = data.get("orgId")
        api_version = data.get("apiVersion")
        if (
            not isinstance(webhook_id, str)
            or not webhook_id.isdigit()
            or not isinstance(signing_key, str)
            or not signing_key.startswith("whsec_")
            or not isinstance(organization_id, str)
            or not organization_id.startswith("OR")
            or api_version != QUO_API_VERSION
        ):
            raise QuoApiError("Quo API returned invalid webhook data")

        return QuoWebhookCredentials(
            webhook_id=webhook_id,
            signing_key=signing_key,
            organization_id=organization_id,
            api_version=api_version,
        )

    async def get_contact(self, contact_id: str) -> dict[str, Any]:
        """Fetch one contact and reject mismatched provider identities."""
        normalized_id = contact_id.strip()
        if not normalized_id or len(normalized_id) > 255:
            raise QuoApiError("A valid Quo contact ID is required")

        payload = await self._request(
            "GET",
            f"/contacts/{quote(normalized_id, safe='')}",
            api_version=QUO_CONTACT_API_VERSION,
        )
        data = payload.get("data")
        if not isinstance(data, dict) or data.get("id") != normalized_id:
            raise QuoApiError("Quo API returned invalid contact data")
        return data

    async def get_user(self, user_id: str) -> dict[str, Any]:
        """Fetch one Quo user from the path-versioned identity endpoint."""
        normalized_id = user_id.strip()
        if not normalized_id or len(normalized_id) > 255:
            raise QuoApiError("A valid Quo user ID is required")

        payload = await self._request(
            "GET",
            f"/{QUO_HISTORICAL_API_VERSION}/users/{quote(normalized_id, safe='')}",
            api_version=None,
        )
        data = payload.get("data")
        if not isinstance(data, dict) or data.get("id") != normalized_id:
            raise QuoApiError("Quo API returned invalid user data")
        return data

    async def delete_webhook(self, webhook_id: str) -> None:
        """Delete a Quo webhook. A missing webhook is already cleaned up."""
        try:
            await self._request("DELETE", f"/webhooks/{webhook_id}")
        except QuoApiError as exc:
            if exc.status_code != 404:
                raise

    async def disable_webhook(self, webhook_id: str) -> None:
        """Disable a Quo webhook when deletion is temporarily unavailable."""
        await self._request(
            "PATCH",
            f"/webhooks/{webhook_id}",
            json={"status": "disabled"},
        )

    async def remove_webhook(self, webhook_id: str) -> None:
        """Delete the webhook, falling back to disabling it."""
        try:
            await self.delete_webhook(webhook_id)
        except QuoApiError:
            await self.disable_webhook(webhook_id)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> QuoClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()


def _parse_phone_number(resource: dict[str, Any]) -> QuoPhoneNumber:
    phone_number_id = resource.get("id")
    raw_number = resource.get("number", resource.get("phoneNumber"))
    if (
        not isinstance(phone_number_id, str)
        or not phone_number_id.strip()
        or len(phone_number_id) > 255
    ):
        raise QuoApiError("Quo API returned invalid phone number data")
    phone_number = normalize_phone_safe(raw_number) if isinstance(raw_number, str) else None
    if phone_number is None:
        raise QuoApiError("Quo API returned invalid phone number data")

    raw_label = resource.get("name", resource.get("label"))
    provider_label = raw_label.strip() if isinstance(raw_label, str) else None
    if provider_label is not None and (not provider_label or len(provider_label) > 100):
        provider_label = None
    return QuoPhoneNumber(
        id=phone_number_id.strip(),
        phone_number=phone_number,
        provider_label=provider_label,
    )


def _retry_delay_seconds(response: httpx.Response, attempt: int) -> float:
    raw_delay = response.headers.get("Retry-After") or response.headers.get("X-RateLimit-Reset")
    delay: float | None = None
    if raw_delay is not None:
        try:
            delay = float(raw_delay)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(raw_delay)
            except (TypeError, ValueError):
                retry_at = None
            if retry_at is not None:
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=UTC)
                delay = (retry_at - datetime.now(UTC)).total_seconds()

    if delay is None:
        delay = float(2**attempt)
    return min(max(delay, 0.0), _MAX_RETRY_DELAY_SECONDS)
