"""Unified outbound delivery service for text, email, and push channels."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign import Campaign, CampaignContact
from app.models.contact import Contact
from app.models.conversation import Message, MessageStatus
from app.models.user import User
from app.services.compliance.outbound_compliance import (
    OutboundComplianceRequest,
    OutboundComplianceResult,
    OutboundComplianceService,
)
from app.services.idempotency import derive_outbound_key
from app.services.rate_limiting.opt_out_manager import OptOutManager
from app.services.telephony.text_provider import TextMessageProvider, get_text_message_provider

logger = structlog.get_logger()

TEXT_CHANNELS: frozenset[OutboundDeliveryChannel]


class OutboundDeliveryChannel(StrEnum):
    """Supported outbound channels."""

    SMS = "sms"
    IMESSAGE = "imessage"
    EMAIL = "email"
    PUSH = "push"


TEXT_CHANNELS = frozenset({OutboundDeliveryChannel.SMS, OutboundDeliveryChannel.IMESSAGE})


class OutboundDeliveryStatus(StrEnum):
    """Normalized outbound delivery result status."""

    SENT = "sent"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


@dataclass(slots=True, frozen=True)
class OutboundDeliveryRequest:
    """Typed request for one outbound delivery attempt."""

    workspace_id: uuid.UUID
    channel: OutboundDeliveryChannel
    to: str | None = None
    body: str | None = None
    from_: str | None = None
    subject: str | None = None
    html: str | None = None
    text: str | None = None
    title: str | None = None
    data: Mapping[str, Any] | None = None
    notification_type: str | None = None
    channel_id: str | None = None
    user_id: int | None = None
    user: User | None = None
    contact: Contact | None = None
    campaign: Campaign | None = None
    campaign_contact: CampaignContact | None = None
    agent_id: uuid.UUID | None = None
    campaign_id: uuid.UUID | None = None
    phone_number_id: uuid.UUID | None = None
    provider_preference: str | None = None
    mac_relay_service: str | None = None
    idempotency_key: uuid.UUID | None = None
    idempotency_scope: str | None = None
    idempotency_parts: tuple[object, ...] = ()
    action_type: str = "outbound_delivery"
    require_sms_consent: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class OutboundDeliveryResult:
    """Normalized outcome for one outbound delivery attempt."""

    channel: OutboundDeliveryChannel
    status: OutboundDeliveryStatus
    provider: str | None = None
    provider_message_id: str | None = None
    message: Message | None = None
    idempotency_key: uuid.UUID | None = None
    reason: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    @property
    def delivered(self) -> bool:
        """Return True when the provider accepted the outbound send."""
        return self.status is OutboundDeliveryStatus.SENT


class TextProviderFactory(Protocol):
    """Factory for provider-neutral text message senders."""

    def __call__(
        self,
        preferred_provider: str | None = None,
        *,
        mac_relay_service: str | None = None,
    ) -> TextMessageProvider:
        """Return a text provider for the requested preference."""
        ...


class EmailDeliveryProvider(Protocol):
    """Provider contract for outbound email sends."""

    async def send_email(
        self,
        params: dict[str, Any],
        *,
        idempotency_key: uuid.UUID | None = None,
    ) -> dict[str, Any] | None:
        """Send one email and return provider response metadata."""
        ...


class PushDeliveryProvider(Protocol):
    """Provider contract for outbound push notifications."""

    async def send_to_user(
        self,
        db: AsyncSession,
        user_id: int,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
        notification_type: str | None = None,
        channel_id: str | None = None,
    ) -> bool:
        """Send push notification to one user's registered devices."""
        ...

    async def send_to_workspace_members(
        self,
        db: AsyncSession,
        workspace_id: str,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
        notification_type: str | None = None,
        channel_id: str | None = None,
    ) -> bool:
        """Send push notification to workspace members."""
        ...


class ResendEmailDeliveryProvider:
    """Email provider adapter backed by the existing Resend helper."""

    async def send_email(
        self,
        params: dict[str, Any],
        *,
        idempotency_key: uuid.UUID | None = None,
    ) -> dict[str, Any] | None:
        """Send one email via Resend."""
        from app.services import email as email_service

        return await email_service._send(params, idempotency_key=idempotency_key)


@dataclass(slots=True, frozen=True)
class _ComplianceDecision:
    allowed: bool
    reason: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)


class OutboundDeliveryService:
    """Unified delivery facade for SMS, iMessage, email, and push sends."""

    def __init__(
        self,
        *,
        text_provider_factory: TextProviderFactory = get_text_message_provider,
        email_provider: EmailDeliveryProvider | None = None,
        push_provider: PushDeliveryProvider | None = None,
        opt_out_manager: OptOutManager | None = None,
        compliance_service: OutboundComplianceService | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._text_provider_factory = text_provider_factory
        self._email_provider = email_provider or ResendEmailDeliveryProvider()
        if push_provider is None:
            from app.services.push_notifications import push_notification_service

            push_provider = push_notification_service
        self._push_provider = push_provider
        self._opt_out_manager = opt_out_manager or OptOutManager()
        self._compliance_service = compliance_service or OutboundComplianceService(
            self._opt_out_manager
        )
        self._clock = clock or (lambda: datetime.now(UTC))
        self._log = logger.bind(component="outbound_delivery")

    async def deliver(
        self,
        db: AsyncSession,
        request: OutboundDeliveryRequest,
    ) -> OutboundDeliveryResult:
        """Run compliance gates, send through the selected provider, and normalize the result."""
        started = time.perf_counter()
        idempotency_key = self._resolve_idempotency_key(request)
        log = self._log.bind(
            workspace_id=str(request.workspace_id),
            channel=request.channel.value,
            action_type=request.action_type,
            idempotency_key=str(idempotency_key) if idempotency_key else None,
        )

        try:
            compliance = await self._check_compliance(db, request)
        except Exception as exc:
            elapsed_ms = _elapsed_ms(started)
            log.exception(
                "outbound_compliance_failed",
                error=str(exc),
                elapsed_ms=elapsed_ms,
            )
            return OutboundDeliveryResult(
                channel=request.channel,
                status=OutboundDeliveryStatus.FAILED,
                idempotency_key=idempotency_key,
                reason="compliance_exception",
                details={"error": str(exc), "elapsed_ms": elapsed_ms},
            )

        if not compliance.allowed:
            elapsed_ms = _elapsed_ms(started)
            log.info(
                "outbound_delivery_blocked",
                reason=compliance.reason,
                elapsed_ms=elapsed_ms,
            )
            return OutboundDeliveryResult(
                channel=request.channel,
                status=OutboundDeliveryStatus.BLOCKED,
                idempotency_key=idempotency_key,
                reason=compliance.reason,
                details={**dict(compliance.details), "elapsed_ms": elapsed_ms},
            )

        try:
            if request.channel in TEXT_CHANNELS:
                result = await self._deliver_text(db, request, idempotency_key)
            elif request.channel is OutboundDeliveryChannel.EMAIL:
                result = await self._deliver_email(request, idempotency_key)
            elif request.channel is OutboundDeliveryChannel.PUSH:
                result = await self._deliver_push(db, request, idempotency_key)
            else:  # pragma: no cover - StrEnum exhaustiveness guard
                result = OutboundDeliveryResult(
                    channel=request.channel,
                    status=OutboundDeliveryStatus.FAILED,
                    idempotency_key=idempotency_key,
                    reason="unsupported_channel",
                )
        except Exception as exc:
            elapsed_ms = _elapsed_ms(started)
            log.exception(
                "outbound_delivery_failed",
                error=str(exc),
                elapsed_ms=elapsed_ms,
            )
            return OutboundDeliveryResult(
                channel=request.channel,
                status=OutboundDeliveryStatus.FAILED,
                idempotency_key=idempotency_key,
                reason="provider_exception",
                details={"error": str(exc), "elapsed_ms": elapsed_ms},
            )

        elapsed_ms = _elapsed_ms(started)
        log.info(
            "outbound_delivery_completed",
            status=result.status.value,
            provider=result.provider,
            provider_message_id=result.provider_message_id,
            reason=result.reason,
            elapsed_ms=elapsed_ms,
        )
        return _with_elapsed(result, elapsed_ms)

    def _resolve_idempotency_key(
        self,
        request: OutboundDeliveryRequest,
    ) -> uuid.UUID | None:
        if request.idempotency_key is not None:
            return request.idempotency_key
        if request.idempotency_scope is None:
            return None
        return derive_outbound_key(request.idempotency_scope, *request.idempotency_parts)

    async def _check_compliance(
        self,
        db: AsyncSession,
        request: OutboundDeliveryRequest,
    ) -> _ComplianceDecision:
        if request.channel in TEXT_CHANNELS:
            return await self._check_text_compliance(db, request)
        if request.channel is OutboundDeliveryChannel.EMAIL:
            return self._check_email_compliance(request)
        if request.channel is OutboundDeliveryChannel.PUSH:
            return self._check_push_compliance(request)
        return _ComplianceDecision(allowed=False, reason="unsupported_channel")

    async def _check_text_compliance(
        self,
        db: AsyncSession,
        request: OutboundDeliveryRequest,
    ) -> _ComplianceDecision:
        recipient = self._text_recipient(request)
        if not recipient:
            return _ComplianceDecision(allowed=False, reason="missing_text_recipient")

        if request.user is not None and not request.user.notification_sms:
            return _ComplianceDecision(
                allowed=False,
                reason="recipient_sms_disabled",
                details={"user_id": request.user.id},
            )

        if await self._opt_out_manager.check_opt_out(request.workspace_id, recipient, db):
            self._apply_campaign_suppression(request, "global_opt_out")
            return _ComplianceDecision(
                allowed=False,
                reason="global_opt_out",
                details={"recipient": recipient},
            )

        if request.contact is not None and request.require_sms_consent:
            consent_status = request.contact.sms_consent_status or "unknown"
            if consent_status != OutboundComplianceService.OPTED_IN:
                self._apply_campaign_suppression(
                    request,
                    "missing_sms_consent",
                    {"sms_consent_status": consent_status},
                )
                return _ComplianceDecision(
                    allowed=False,
                    reason="missing_sms_consent",
                    details={"sms_consent_status": consent_status},
                )

        if request.campaign is not None and request.contact is not None:
            result = await self._compliance_service.evaluate(
                OutboundComplianceRequest(
                    workspace_id=request.workspace_id,
                    campaign=request.campaign,
                    campaign_contact=request.campaign_contact,
                    contact=request.contact,
                    channel=request.channel.value,
                    action_type=request.action_type,
                    now=self._clock(),
                    require_sms_consent=request.require_sms_consent,
                ),
                db,
            )
            if request.campaign_contact is not None:
                self._compliance_service.apply_suppression(
                    request.campaign_contact,
                    result,
                    self._clock(),
                )
            if not result.allowed:
                return _ComplianceDecision(
                    allowed=False,
                    reason=result.reason,
                    details=result.details,
                )

        return _ComplianceDecision(allowed=True)

    def _check_email_compliance(self, request: OutboundDeliveryRequest) -> _ComplianceDecision:
        recipient = request.to or (request.user.email if request.user is not None else None)
        if not recipient:
            return _ComplianceDecision(allowed=False, reason="missing_email_recipient")
        if request.user is not None and not request.user.notification_email:
            return _ComplianceDecision(
                allowed=False,
                reason="recipient_email_disabled",
                details={"user_id": request.user.id},
            )
        if not request.subject:
            return _ComplianceDecision(allowed=False, reason="missing_email_subject")
        if not request.html and not request.text and not request.body:
            return _ComplianceDecision(allowed=False, reason="missing_email_content")
        return _ComplianceDecision(allowed=True)

    def _check_push_compliance(self, request: OutboundDeliveryRequest) -> _ComplianceDecision:
        if not request.title or not request.body:
            return _ComplianceDecision(allowed=False, reason="missing_push_content")
        if request.user is not None:
            if not request.user.is_active:
                return _ComplianceDecision(
                    allowed=False,
                    reason="recipient_inactive",
                    details={"user_id": request.user.id},
                )
            if not request.user.notification_push:
                return _ComplianceDecision(
                    allowed=False,
                    reason="recipient_push_disabled",
                    details={"user_id": request.user.id},
                )
            pref_attr = _push_preference_attr(request.notification_type)
            if pref_attr is not None and not getattr(request.user, pref_attr, True):
                return _ComplianceDecision(
                    allowed=False,
                    reason="recipient_push_type_disabled",
                    details={
                        "user_id": request.user.id,
                        "notification_type": request.notification_type,
                    },
                )
        return _ComplianceDecision(allowed=True)

    async def _deliver_text(
        self,
        db: AsyncSession,
        request: OutboundDeliveryRequest,
        idempotency_key: uuid.UUID | None,
    ) -> OutboundDeliveryResult:
        recipient = self._text_recipient(request)
        sender = request.from_
        if not recipient:
            return OutboundDeliveryResult(
                channel=request.channel,
                status=OutboundDeliveryStatus.BLOCKED,
                idempotency_key=idempotency_key,
                reason="missing_text_recipient",
            )
        if not sender:
            return OutboundDeliveryResult(
                channel=request.channel,
                status=OutboundDeliveryStatus.BLOCKED,
                idempotency_key=idempotency_key,
                reason="missing_text_sender",
            )
        if not request.body:
            return OutboundDeliveryResult(
                channel=request.channel,
                status=OutboundDeliveryStatus.BLOCKED,
                idempotency_key=idempotency_key,
                reason="missing_text_body",
            )

        provider_preference = self._text_provider_preference(request)
        provider = self._text_provider_factory(
            provider_preference,
            mac_relay_service=request.mac_relay_service,
        )
        try:
            message = await provider.send_message(
                to_number=recipient,
                from_number=sender,
                body=request.body,
                db=db,
                workspace_id=request.workspace_id,
                agent_id=request.agent_id,
                campaign_id=request.campaign_id,
                phone_number_id=request.phone_number_id,
                idempotency_key=idempotency_key,
            )
        finally:
            await provider.close()

        failed = message.status in {MessageStatus.FAILED, MessageStatus.FAILED.value}
        return OutboundDeliveryResult(
            channel=request.channel,
            status=OutboundDeliveryStatus.FAILED if failed else OutboundDeliveryStatus.SENT,
            provider=provider_preference or "telnyx",
            provider_message_id=message.provider_message_id,
            message=message,
            idempotency_key=idempotency_key,
            reason=message.error_message if failed else None,
            details={"message_id": str(message.id)},
        )

    async def _deliver_email(
        self,
        request: OutboundDeliveryRequest,
        idempotency_key: uuid.UUID | None,
    ) -> OutboundDeliveryResult:
        from app.services.email import _from_address

        recipient = request.to or (request.user.email if request.user is not None else None)
        if not recipient:
            return OutboundDeliveryResult(
                channel=request.channel,
                status=OutboundDeliveryStatus.BLOCKED,
                idempotency_key=idempotency_key,
                reason="missing_email_recipient",
            )

        params: dict[str, Any] = {
            "from": request.from_ or _from_address(),
            "to": [recipient],
            "subject": request.subject,
        }
        html = request.html or request.body
        text = request.text
        if html:
            params["html"] = html
        if text:
            params["text"] = text

        response = await self._email_provider.send_email(params, idempotency_key=idempotency_key)
        if response is None:
            return OutboundDeliveryResult(
                channel=request.channel,
                status=OutboundDeliveryStatus.FAILED,
                provider="resend",
                idempotency_key=idempotency_key,
                reason="provider_failed",
            )
        provider_message_id = response.get("id")
        return OutboundDeliveryResult(
            channel=request.channel,
            status=OutboundDeliveryStatus.SENT,
            provider="resend",
            provider_message_id=str(provider_message_id) if provider_message_id else None,
            idempotency_key=idempotency_key,
        )

    async def _deliver_push(
        self,
        db: AsyncSession,
        request: OutboundDeliveryRequest,
        idempotency_key: uuid.UUID | None,
    ) -> OutboundDeliveryResult:
        if not request.title or not request.body:
            return OutboundDeliveryResult(
                channel=request.channel,
                status=OutboundDeliveryStatus.BLOCKED,
                idempotency_key=idempotency_key,
                reason="missing_push_content",
            )

        payload = dict(request.data or {})
        if idempotency_key is not None:
            payload.setdefault("idempotencyKey", str(idempotency_key))

        sent = False
        if request.user_id is not None:
            sent = await self._push_provider.send_to_user(
                db,
                user_id=request.user_id,
                title=request.title,
                body=request.body,
                data=payload,
                notification_type=request.notification_type,
                channel_id=request.channel_id,
            )
        else:
            sent = await self._push_provider.send_to_workspace_members(
                db,
                workspace_id=str(request.workspace_id),
                title=request.title,
                body=request.body,
                data=payload,
                notification_type=request.notification_type,
                channel_id=request.channel_id,
            )

        return OutboundDeliveryResult(
            channel=request.channel,
            status=OutboundDeliveryStatus.SENT if sent else OutboundDeliveryStatus.SKIPPED,
            provider="expo",
            idempotency_key=idempotency_key,
            reason=None if sent else "no_push_recipient",
        )

    def _text_recipient(self, request: OutboundDeliveryRequest) -> str | None:
        if request.to:
            return request.to
        if request.contact is not None:
            return request.contact.phone_number
        if request.user is not None:
            return request.user.phone_number
        return None

    def _text_provider_preference(self, request: OutboundDeliveryRequest) -> str | None:
        if request.provider_preference:
            return request.provider_preference
        if request.channel is OutboundDeliveryChannel.IMESSAGE:
            return "mac_relay"
        return None

    def _apply_campaign_suppression(
        self,
        request: OutboundDeliveryRequest,
        reason: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        if request.campaign_contact is None:
            return
        result = OutboundComplianceResult(
            allowed=False,
            reason=reason,
            details=dict(details or {}),
        )
        self._compliance_service.apply_suppression(
            request.campaign_contact,
            result,
            self._clock(),
        )


def _push_preference_attr(notification_type: str | None) -> str | None:
    if notification_type == "call":
        return "notification_push_calls"
    if notification_type == "message":
        return "notification_push_messages"
    if notification_type == "voicemail":
        return "notification_push_voicemail"
    if notification_type == "appointment":
        return "notification_push_appointments"
    return None


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _with_elapsed(result: OutboundDeliveryResult, elapsed_ms: int) -> OutboundDeliveryResult:
    return OutboundDeliveryResult(
        channel=result.channel,
        status=result.status,
        provider=result.provider,
        provider_message_id=result.provider_message_id,
        message=result.message,
        idempotency_key=result.idempotency_key,
        reason=result.reason,
        details={**dict(result.details), "elapsed_ms": elapsed_ms},
    )


outbound_delivery_service = OutboundDeliveryService()

__all__ = [
    "OutboundDeliveryChannel",
    "OutboundDeliveryRequest",
    "OutboundDeliveryResult",
    "OutboundDeliveryService",
    "OutboundDeliveryStatus",
    "outbound_delivery_service",
]
