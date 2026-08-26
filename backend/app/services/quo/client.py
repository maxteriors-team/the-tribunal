"""Async client for Quo's versioned, workspace-scoped REST API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

QUO_API_BASE_URL = "https://api.quo.com"
# Current version verified against Quo's versioned API docs on 2026-08-26:
# https://www.quo.com/docs/2026-03-30/introduction
QUO_API_VERSION = "2026-03-30"
QUO_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0)
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
    "contact.updated",
    "contact.deleted",
)


class QuoApiError(RuntimeError):
    """Quo rejected a request or returned an unusable response."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)


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
            "Quo-Api-Version": QUO_API_VERSION,
        }
        self._base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=QUO_TIMEOUT,
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = await self._client.request(
                method,
                f"{self._base_url}{path}",
                headers=self._headers,
                json=json,
            )
        except httpx.HTTPError:
            # The original exception retains the authenticated request.
            raise QuoApiError("Quo API request failed") from None

        if response.status_code >= 400:
            # Provider bodies can contain request metadata and are intentionally omitted.
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

    async def validate_api_key(self) -> str | None:
        """Validate the key and return an organization ID when one exists."""
        payload = await self._request("GET", "/webhooks")
        webhooks = payload.get("data")
        if not isinstance(webhooks, list):
            raise QuoApiError("Quo API returned an invalid response")

        for webhook in webhooks:
            if not isinstance(webhook, dict):
                continue
            organization_id = webhook.get("orgId")
            if isinstance(organization_id, str) and organization_id.startswith("OR"):
                return organization_id
        return None

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
