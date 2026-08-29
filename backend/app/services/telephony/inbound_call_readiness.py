"""Fail-closed prerequisites for AI-first inbound phone routing."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from ipaddress import ip_address
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.agent import Agent
from app.models.phone_number import PhoneNumber, PhoneNumberProvider
from app.services.ai.openai_credentials import (
    OpenAICredentialError,
    resolve_openai_credentials,
)
from app.utils.phone import normalize_phone_safe


@dataclass(frozen=True, slots=True)
class ReadinessCheck:
    """One bounded prerequisite suitable for an authenticated API response."""

    code: str
    ready: bool
    message: str


@dataclass(frozen=True, slots=True)
class InboundCallReadiness:
    """Resolved agent plus every prerequisite result."""

    agent: Agent | None
    checks: tuple[ReadinessCheck, ...]

    @property
    def ready(self) -> bool:
        """Return true only when every prerequisite passed."""
        return all(check.ready for check in self.checks)


def _check(code: str, ready: bool, ready_message: str, blocked_message: str) -> ReadinessCheck:
    return ReadinessCheck(
        code=code,
        ready=ready,
        message=ready_message if ready else blocked_message,
    )


def _is_public_https_url(value: str) -> bool:
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        return False

    try:
        return ip_address(hostname).is_global
    except ValueError:
        # simplification: DNS is not resolved here; staged calls prove reachability.
        reserved_suffixes = (
            ".local",
            ".localhost",
            ".internal",
            ".test",
            ".invalid",
            ".example",
        )
        return "." in hostname and not hostname.endswith(reserved_suffixes)


async def evaluate_inbound_call_readiness(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    phone_number: PhoneNumber,
    assigned_agent_id: uuid.UUID | None,
    fallback_number: str | None,
    transfer_destination_number: str | None,
) -> InboundCallReadiness:
    """Evaluate activation/runtime prerequisites without disclosing foreign rows."""
    agent: Agent | None = None
    if assigned_agent_id is not None:
        result = await db.execute(
            select(Agent).where(
                Agent.id == assigned_agent_id,
                Agent.workspace_id == workspace_id,
            )
        )
        agent = result.scalar_one_or_none()

    effective_transfer_number = transfer_destination_number
    if effective_transfer_number is None and agent is not None:
        effective_transfer_number = agent.transfer_destination_number

    try:
        credential_context = await resolve_openai_credentials(db, workspace_id, require_fresh=True)
        openai_ready = credential_context.source.startswith("workspace_")
    except OpenAICredentialError:
        openai_ready = False

    provider_configured = bool(
        settings.telnyx_api_key
        and _is_public_https_url(settings.api_base_url)
        and (settings.telnyx_public_key or settings.telnyx_webhook_secret)
    )
    checks = [
        _check(
            "pilot_workspace",
            workspace_id in settings.inbound_voice_pilot_workspace_ids,
            "Workspace is enabled for the inbound pilot.",
            "Inbound AI calling is not enabled for this workspace.",
        ),
        _check(
            "phone_number",
            phone_number.workspace_id == workspace_id
            and phone_number.provider == PhoneNumberProvider.TELNYX
            and phone_number.is_active
            and phone_number.voice_enabled
            and bool(phone_number.telnyx_phone_number_id),
            "Phone number is active and voice-capable.",
            "Phone number is not ready for Telnyx voice calls.",
        ),
        _check(
            "agent",
            bool(agent and agent.is_active and agent.channel_mode in {"voice", "both"}),
            "Voice agent is active.",
            "Choose an active voice-capable agent in this workspace.",
        ),
        _check(
            "agent_provider",
            bool(agent and agent.voice_provider == "openai" and agent.voice_id),
            "Voice agent uses OpenAI Realtime.",
            "Choose an OpenAI Realtime voice agent with a configured voice.",
        ),
        _check(
            "fallback_number",
            bool(fallback_number and normalize_phone_safe(fallback_number) == fallback_number),
            "Emergency fallback number is configured.",
            "Configure a valid emergency fallback number.",
        ),
        _check(
            "transfer_destination",
            bool(
                effective_transfer_number
                and normalize_phone_safe(effective_transfer_number) == effective_transfer_number
            ),
            "Human transfer destination is configured.",
            "Configure a valid human transfer destination.",
        ),
        _check(
            "openai_credentials",
            openai_ready,
            "Workspace OpenAI credentials are usable.",
            "Connect usable OpenAI credentials for this workspace.",
        ),
        _check(
            "telnyx_runtime",
            provider_configured,
            "Telnyx runtime and webhook verification are configured.",
            "Complete the production Telnyx runtime configuration.",
        ),
        _check(
            "telnyx_connection",
            bool(settings.telnyx_connection_id),
            "Telnyx Voice API connection is configured.",
            "Set the Telnyx Voice API connection ID before activation.",
        ),
    ]

    return InboundCallReadiness(agent=agent, checks=tuple(checks))
