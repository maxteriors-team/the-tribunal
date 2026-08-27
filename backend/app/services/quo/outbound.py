"""Retry-safe, text-only manual sending through Quo's OpenPhone API."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import (
    Conversation,
    Message,
    MessageDirection,
    MessageStatus,
)
from app.models.quo_send_attempt import QuoSendAttempt, QuoSendAttemptState
from app.services.providers.http import (
    AsyncProviderHTTPClient,
    ProviderHTTPError,
    ProviderInvalidJSONError,
    ProviderRetryPolicy,
)
from app.services.quo.reconciliation import QuoMessageSnapshot, reconcile_quo_message
from app.utils.phone import normalize_phone_safe

QUO_OUTBOUND_BASE_URL = "https://api.openphone.com"
QUO_OUTBOUND_PATH = "/v1/messages"
_QUO_RESPONSE_STATUSES = {
    "queued": MessageStatus.QUEUED,
    "sending": MessageStatus.SENDING,
    "sent": MessageStatus.SENT,
    "failed": MessageStatus.FAILED,
    "delivered": MessageStatus.DELIVERED,
}


class QuoOutboundError(RuntimeError):
    """Base class for sanitized outbound outcomes."""


class QuoSendRejectedError(QuoOutboundError):
    """Quo definitively rejected this client request."""


class QuoSendStatusUnknownError(QuoOutboundError):
    """Provider acceptance cannot safely be determined or retried."""


class QuoRequestConflictError(QuoOutboundError):
    """A client request UUID was reused for another conversation."""


class QuoMediaUnsupportedError(QuoOutboundError):
    """Quo manual sending is text-only."""


class QuoProviderResponseUnknownError(QuoOutboundError):
    """Quo returned success without a usable provider message identity."""


@dataclass(frozen=True, slots=True)
class QuoAcceptedResource:
    """Validated provider acceptance payload awaiting reconciliation."""

    provider_message_id: str
    resource: dict[str, Any]


@dataclass(frozen=True, slots=True)
class QuoSendClaim:
    """A new network claim or an accepted replay's canonical message."""

    attempt: QuoSendAttempt
    replay_message: Message | None = None


class QuoOutboundSender:
    """One-attempt Quo transport with an exact, text-only request contract."""

    def __init__(
        self,
        api_key: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        normalized_key = api_key.strip()
        if not normalized_key or len(normalized_key) > 2048:
            raise ValueError("A valid Quo API key is required")
        self._http = AsyncProviderHTTPClient(
            provider="quo",
            base_url=QUO_OUTBOUND_BASE_URL,
            headers={"Authorization": normalized_key},
            retry_policy=ProviderRetryPolicy(max_attempts=1),
            transport=transport,
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def send_text(
        self,
        *,
        content: str,
        from_number: str,
        to_number: str,
        media: list[str] | None = None,
    ) -> QuoAcceptedResource:
        if media:
            raise QuoMediaUnsupportedError("Quo manual messaging is text-only")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Message content is required")
        sender = normalize_phone_safe(from_number)
        recipient = normalize_phone_safe(to_number)
        if sender is None or recipient is None:
            raise ValueError("Quo message participants must be valid phone numbers")

        payload = await self._http.post_json(
            QUO_OUTBOUND_PATH,
            json={"content": content, "from": sender, "to": [recipient]},
        )
        resource_value = payload.get("data", payload)
        if not isinstance(resource_value, dict):
            raise QuoProviderResponseUnknownError("Quo acceptance response was incomplete")
        provider_message_id = resource_value.get("id")
        if (
            not isinstance(provider_message_id, str)
            or not provider_message_id.strip()
            or len(provider_message_id) > 255
        ):
            raise QuoProviderResponseUnknownError("Quo acceptance response was incomplete")
        return QuoAcceptedResource(
            provider_message_id=provider_message_id.strip(),
            resource=dict(resource_value),
        )


async def _existing_claim(
    db: AsyncSession,
    *,
    existing: QuoSendAttempt,
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
) -> QuoSendClaim:
    if existing.conversation_id != conversation_id:
        raise QuoRequestConflictError("Client request ID is already bound to another conversation")
    if existing.state == QuoSendAttemptState.ACCEPTED:
        message = await db.scalar(
            select(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Message.id == existing.message_id,
                Message.source_provider == "quo",
                Conversation.workspace_id == workspace_id,
            )
        )
        if message is not None:
            return QuoSendClaim(attempt=existing, replay_message=message)
        raise QuoSendStatusUnknownError("Accepted Quo request has no canonical timeline message")
    if existing.state == QuoSendAttemptState.FAILED:
        raise QuoSendRejectedError("Quo previously rejected this request")
    raise QuoSendStatusUnknownError("Quo request status is unknown; wait for the timeline")


async def get_quo_send_replay(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    client_request_id: uuid.UUID,
) -> QuoSendClaim | None:
    """Resolve an existing request before evaluating rules for a new send."""
    existing = await db.scalar(
        select(QuoSendAttempt).where(
            QuoSendAttempt.workspace_id == workspace_id,
            QuoSendAttempt.client_request_id == client_request_id,
        )
    )
    if existing is None:
        return None
    return await _existing_claim(
        db,
        existing=existing,
        workspace_id=workspace_id,
        conversation_id=conversation_id,
    )


async def claim_quo_send_attempt(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    client_request_id: uuid.UUID,
) -> QuoSendClaim:
    """Commit one workspace-scoped claim before any provider network I/O."""
    attempt = QuoSendAttempt(
        workspace_id=workspace_id,
        conversation_id=conversation_id,
        client_request_id=client_request_id,
        state=QuoSendAttemptState.SENDING,
    )
    db.add(attempt)
    try:
        await db.commit()
        return QuoSendClaim(attempt=attempt)
    except IntegrityError as exc:
        conflict_error = exc
        await db.rollback()

    existing = await db.scalar(
        select(QuoSendAttempt).where(
            QuoSendAttempt.workspace_id == workspace_id,
            QuoSendAttempt.client_request_id == client_request_id,
        )
    )
    if existing is None:
        raise conflict_error
    return await _existing_claim(
        db,
        existing=existing,
        workspace_id=workspace_id,
        conversation_id=conversation_id,
    )


async def execute_quo_send(
    db: AsyncSession,
    *,
    attempt: QuoSendAttempt,
    sender: QuoOutboundSender,
    content: str,
    from_number: str,
    to_number: str,
) -> QuoAcceptedResource:
    """Make exactly one provider attempt and persist only sanitized uncertainty."""
    try:
        return await sender.send_text(
            content=content,
            from_number=from_number,
            to_number=to_number,
        )
    except ProviderHTTPError as exc:
        error_class = _provider_error_class(exc)
        if _is_definitive_rejection(exc):
            await _finish_attempt(
                db,
                attempt=attempt,
                state=QuoSendAttemptState.FAILED,
                error_class=error_class,
            )
            raise QuoSendRejectedError("Quo rejected this message") from None
        await _finish_attempt(
            db,
            attempt=attempt,
            state=QuoSendAttemptState.UNKNOWN,
            error_class=error_class,
        )
        raise QuoSendStatusUnknownError("Quo delivery status is unknown") from None
    except QuoProviderResponseUnknownError:
        await _finish_attempt(
            db,
            attempt=attempt,
            state=QuoSendAttemptState.UNKNOWN,
            error_class="invalid_response",
        )
        raise QuoSendStatusUnknownError("Quo delivery status is unknown") from None


async def reconcile_accepted_quo_send(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    conversation: Conversation,
    attempt: QuoSendAttempt,
    accepted: QuoAcceptedResource,
    content: str,
    from_number: str,
    to_number: str,
    sender_user_id: int | None,
    sender_display_name: str | None,
) -> Message:
    """Atomically canonicalize provider acceptance and link its durable claim."""
    occurred_at = _provider_datetime(accepted.resource.get("createdAt"))
    raw_status = accepted.resource.get("status")
    message_status = (
        _QUO_RESPONSE_STATUSES.get(raw_status, MessageStatus.QUEUED)
        if isinstance(raw_status, str)
        else MessageStatus.QUEUED
    )
    provider_sender_user_id = accepted.resource.get("userId")
    if (
        not isinstance(provider_sender_user_id, str)
        or not provider_sender_user_id.strip()
        or len(provider_sender_user_id) > 255
    ):
        provider_sender_user_id = None
    snapshot = QuoMessageSnapshot(
        provider_message_id=accepted.provider_message_id,
        conversation_id=conversation.id,
        direction=MessageDirection.OUTBOUND,
        sender=from_number,
        recipient=to_number,
        body=content,
        status=message_status,
        occurred_at=occurred_at,
        sent_at=(
            occurred_at
            if message_status in {MessageStatus.SENT, MessageStatus.FAILED, MessageStatus.DELIVERED}
            else None
        ),
        delivered_at=occurred_at if message_status == MessageStatus.DELIVERED else None,
        sender_user_id=sender_user_id,
        provider_sender_user_id=provider_sender_user_id,
        sender_display_name=sender_display_name,
    )
    try:
        reconciled = await reconcile_quo_message(
            db,
            workspace_id=workspace_id,
            conversation=conversation,
            snapshot=snapshot,
            attempt=attempt,
        )
    except Exception:
        await db.rollback()
        attempt.state = QuoSendAttemptState.UNKNOWN
        attempt.error_class = "reconciliation"
        await db.commit()
        raise QuoSendStatusUnknownError("Quo delivery status is unknown") from None
    await db.commit()
    return reconciled.message


async def _finish_attempt(
    db: AsyncSession,
    *,
    attempt: QuoSendAttempt,
    state: QuoSendAttemptState,
    error_class: str,
) -> None:
    attempt.state = state
    attempt.error_class = error_class
    await db.commit()


def _is_definitive_rejection(exc: ProviderHTTPError) -> bool:
    status_code = exc.status_code
    return status_code is not None and 400 <= status_code < 500 and status_code != 429


def _provider_datetime(value: object) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                return parsed.astimezone(UTC)
        except ValueError:
            return datetime.now(UTC)
    return datetime.now(UTC)


def _provider_error_class(exc: ProviderHTTPError) -> str:
    if isinstance(exc, ProviderInvalidJSONError):
        return "invalid_response"
    if exc.status_code == 429:
        return "rate_limited"
    if exc.status_code is not None and 500 <= exc.status_code < 600:
        return "provider_5xx"
    if exc.status_code is not None and 400 <= exc.status_code < 500:
        return "provider_rejected"
    return "transport"
