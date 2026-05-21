"""Mac relay text provider backed by a self-hosted imsg daemon."""

import uuid
from typing import Any, Literal, cast

import httpx

from app.core.config import settings
from app.models.conversation import MessageChannel
from app.services.telephony.telnyx import TelnyxSMSService
from app.utils.phone import normalize_phone_e164

MacRelayServiceName = Literal["imessage", "sms", "auto"]
_ALLOWED_MAC_RELAY_SERVICES: set[str] = {"imessage", "sms", "auto"}


class MacRelayMessageService(TelnyxSMSService):
    """Text sender that delegates delivery to a Mac-hosted iMessage relay."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        service: MacRelayServiceName = "imessage",
    ) -> None:
        """Initialize the Mac relay provider.

        Args:
            base_url: Base URL of the self-hosted Mac relay daemon.
            token: Shared bearer token for relay authentication.
            service: imsg transport selection: ``imessage``, ``sms``, or ``auto``.
        """
        super().__init__(
            api_key=token,
            message_channel=MessageChannel.IMESSAGE,
            conversation_channel=MessageChannel.IMESSAGE.value,
            service_name="mac_relay_message",
            provider_payload_type="imessage",
        )
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.service = service

    @property
    def client(self) -> httpx.AsyncClient:
        """Get or create HTTP client for the relay daemon."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )
        return self._client

    def _normalize_outbound_to(self, to_number: str) -> str:
        """Normalize relay recipients to E.164 for stable conversations."""
        return normalize_phone_e164(to_number)

    def _normalize_outbound_from(self, from_number: str) -> str:
        """Allow Mac relay senders to be phone aliases or Apple ID emails."""
        sender = from_number.strip()
        if "@" in sender:
            return sender.lower()
        return normalize_phone_e164(sender)

    def _build_message_payload(
        self,
        *,
        to_number: str,
        from_number: str,
        body: str,
        idempotency_key: uuid.UUID,
    ) -> dict[str, str]:
        """Build the relay daemon send payload."""
        return {
            "to": to_number,
            "from": from_number,
            "text": body,
            "service": self.service,
            "client_message_id": str(idempotency_key),
        }

    async def _post_message(
        self,
        payload: dict[str, str],
        idempotency_key: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """POST to the Mac relay and normalize its response to Telnyx shape."""
        response = await self.client.post("/v1/messages", json=payload)
        self.logger.info("mac_relay_response", status_code=response.status_code)
        response.raise_for_status()
        try:
            raw: dict[str, Any] = response.json()
        except (ValueError, TypeError):
            self.logger.error("mac_relay_invalid_json", status_code=response.status_code)
            raw = {}

        relay_id = raw.get("id") or raw.get("message_id") or payload.get("client_message_id")
        provider_message_id = _prefix_mac_relay_id(str(relay_id))
        return {"data": {"id": provider_message_id, "raw": raw}}


def _prefix_mac_relay_id(message_id: str) -> str:
    """Return a globally unique provider id for Mac relay-originated messages."""
    if message_id.startswith("mac-relay:"):
        return message_id
    return f"mac-relay:{message_id}"


def _coerce_mac_relay_service(service: str) -> MacRelayServiceName:
    """Validate the configured imsg transport mode."""
    if service in _ALLOWED_MAC_RELAY_SERVICES:
        return cast(MacRelayServiceName, service)
    return "imessage"


def build_configured_mac_relay_service() -> MacRelayMessageService:
    """Build a relay service from application settings."""
    return MacRelayMessageService(
        base_url=settings.mac_relay_base_url,
        token=settings.mac_relay_token,
        service=_coerce_mac_relay_service(settings.mac_relay_default_service),
    )
