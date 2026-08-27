"""Bounded, resumable Quo historical import built on the production sync path."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.quo.client import (
    QUO_HISTORICAL_API_VERSION,
    QuoApiError,
    QuoClient,
)
from app.services.quo.sync import QuoSyncError, QuoSyncService
from app.services.webhooks.quo import QuoWebhookEvent
from app.utils.phone import normalize_phone_safe

MAX_BACKFILL_RANGE = timedelta(days=31)
_CALL_LOOKBACK = timedelta(days=7)
_COMMIT_EVERY = 100
_AUTH_FAILURES = {401, 403}
_MESSAGE_EVENTS = {
    "incoming": {"received": "message.received"},
    "outgoing": {
        "queued": "message.queued",
        "sent": "message.sent",
        "delivered": "message.delivered",
        "undelivered": "message.undelivered",
    },
}
_CALL_STATUSES = {
    "completed": "answered",
    "answered": "answered",
    "forwarded": "forwarded",
    "missed": "unanswered",
    "no-answer": "unanswered",
    "busy": "unanswered",
    "failed": "unanswered",
    "canceled": "unanswered",
    "abandoned": "unanswered",
}


class QuoBackfillError(RuntimeError):
    """The historical import cannot continue without risking incorrect data."""


class QuoTenantMismatchError(QuoBackfillError):
    """Quo returned data outside the validated workspace integration."""


class QuoBackfillDataError(ValueError):
    """One provider resource is malformed and can be counted without PII."""


@dataclass(slots=True)
class ResourceCounts:
    seen: int = 0
    eligible: int = 0
    synced: int = 0
    skipped: int = 0
    errors: int = 0


@dataclass(slots=True)
class QuoBackfillCounts:
    contacts: ResourceCounts = field(default_factory=ResourceCounts)
    conversations: ResourceCounts = field(default_factory=ResourceCounts)
    texts: ResourceCounts = field(default_factory=ResourceCounts)
    calls: ResourceCounts = field(default_factory=ResourceCounts)
    api_errors: int = 0


class QuoHistoricalBackfill:
    """Import one recent UTC interval, committing in idempotent checkpoints."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        organization_id: str,
        phone_number_id: str,
        phone_number: str,
        client: QuoClient,
        since: datetime,
        until: datetime,
        apply: bool,
    ) -> None:
        validate_backfill_window(since, until)
        normalized_phone = normalize_phone_safe(phone_number)
        if not phone_number_id.strip() or normalized_phone is None:
            raise QuoBackfillError("stored Quo sender selection is invalid")
        self.db = db
        self.workspace_id = workspace_id
        self.organization_id = organization_id
        self.phone_number_id = phone_number_id
        self.phone_number = normalized_phone
        self.client = client
        self.since = since.astimezone(UTC)
        self.until = until.astimezone(UTC)
        self.apply = apply
        self.counts = QuoBackfillCounts()
        self.sync = QuoSyncService(
            db,
            workspace_id=workspace_id,
            organization_id=organization_id,
            phone_number_id=phone_number_id,
            phone_number=normalized_phone,
            client=client,
        )
        self._pending_writes = 0
        self._seen_conversation_ids: set[str] = set()
        self._seen_message_ids: set[str] = set()
        self._seen_call_ids: set[str] = set()

    async def run(self) -> QuoBackfillCounts:
        """Import only the selected line and rollback unless apply was explicit."""
        try:
            phone_numbers = await self._selected_phone_number()
            if phone_numbers:
                await self._import_conversations(phone_numbers)
            if self.apply:
                await self.db.commit()
            else:
                await self.db.rollback()
        except BaseException:
            await self.db.rollback()
            raise
        return self.counts

    async def _selected_phone_number(self) -> dict[str, str]:
        try:
            resources = await self.client.list_phone_numbers()
        except QuoApiError as exc:
            self._record_api_error(exc, self.counts.conversations)
            return {}

        selected = next((item for item in resources if item.id == self.phone_number_id), None)
        if selected is None or selected.phone_number != self.phone_number:
            raise QuoTenantMismatchError(
                "stored Quo sender does not match the authenticated phone-number list"
            )
        return {selected.id: selected.phone_number}

    async def _import_conversations(self, phone_numbers: dict[str, str]) -> None:
        for phone_number_ids in _chunks(list(phone_numbers), 100):
            try:
                conversations = self.client.iter_conversations(
                    phone_number_ids=phone_number_ids,
                    created_before=_isoformat(self.until),
                    updated_after=_isoformat(self.since - timedelta(microseconds=1)),
                )
                await self._consume_conversations(conversations, phone_numbers, phone_number_ids)
            except QuoApiError as exc:
                self._record_api_error(exc, self.counts.conversations)

    async def _consume_conversations(
        self,
        conversations: AsyncIterator[dict[str, Any]],
        phone_numbers: dict[str, str],
        requested_phone_ids: list[str],
    ) -> None:
        async for conversation in conversations:
            counts = self.counts.conversations
            counts.seen += 1
            try:
                conversation_id = _resource_id(conversation, "conversation")
                if conversation_id in self._seen_conversation_ids:
                    counts.skipped += 1
                    continue
                self._seen_conversation_ids.add(conversation_id)
                phone_number_id = _required_string(
                    conversation.get("phoneNumberId"), "conversation phone number ID"
                )
                if (
                    phone_number_id not in requested_phone_ids
                    or phone_number_id not in phone_numbers
                ):
                    raise QuoTenantMismatchError(
                        "Quo returned a conversation outside the validated phone-number scope"
                    )
                participant = _one_participant(conversation.get("participants"))
                counts.eligible += 1
                await self._import_messages(phone_number_id, participant)
                await self._import_calls(
                    phone_number_id,
                    phone_numbers[phone_number_id],
                    participant,
                )
            except QuoBackfillDataError:
                counts.errors += 1

    async def _import_messages(self, phone_number_id: str, participant: str) -> None:
        try:
            messages = self.client.iter_messages(
                phone_number_id=phone_number_id,
                participant=participant,
                created_after=_isoformat(self.since - timedelta(microseconds=1)),
                created_before=_isoformat(self.until),
            )
            async for resource in messages:
                await self._import_message(resource, phone_number_id)
        except QuoApiError as exc:
            self._record_api_error(exc, self.counts.texts)

    async def _import_message(
        self,
        resource: dict[str, Any],
        phone_number_id: str,
    ) -> None:
        counts = self.counts.texts
        counts.seen += 1
        try:
            _assert_phone_number_scope(resource, phone_number_id)
            resource_id = _resource_id(resource, "message")
            if resource_id in self._seen_message_ids:
                counts.skipped += 1
                return
            self._seen_message_ids.add(resource_id)
            if not _timestamp_in_window(resource.get("createdAt"), self.since, self.until):
                counts.skipped += 1
                return
            counts.eligible += 1
            await self._sync(
                _message_event(
                    resource,
                    organization_id=self.organization_id,
                    phone_number_id=phone_number_id,
                ),
                counts,
            )
        except QuoBackfillDataError:
            counts.errors += 1

    async def _import_calls(
        self,
        phone_number_id: str,
        workspace_phone: str,
        participant: str,
    ) -> None:
        try:
            calls = self.client.iter_calls(
                phone_number_id=phone_number_id,
                participant=participant,
                created_after=_isoformat(self.since - _CALL_LOOKBACK),
                created_before=_isoformat(self.until),
            )
            async for resource in calls:
                await self._import_call(
                    resource,
                    phone_number_id=phone_number_id,
                    workspace_phone=workspace_phone,
                    participant=participant,
                )
        except QuoApiError as exc:
            self._record_api_error(exc, self.counts.calls)

    async def _import_call(
        self,
        resource: dict[str, Any],
        *,
        phone_number_id: str,
        workspace_phone: str,
        participant: str,
    ) -> None:
        counts = self.counts.calls
        counts.seen += 1
        try:
            _assert_phone_number_scope(resource, phone_number_id)
            resource_id = _resource_id(resource, "call")
            if resource_id in self._seen_call_ids:
                counts.skipped += 1
                return
            self._seen_call_ids.add(resource_id)
            if not _timestamp_in_window(resource.get("completedAt"), self.since, self.until):
                counts.skipped += 1
                return
            counts.eligible += 1
            await self._sync(
                _call_event(
                    resource,
                    organization_id=self.organization_id,
                    phone_number_id=phone_number_id,
                    workspace_phone=workspace_phone,
                    participant=participant,
                ),
                counts,
            )
        except QuoBackfillDataError:
            counts.errors += 1

    async def _sync(self, event: QuoWebhookEvent, counts: ResourceCounts) -> bool:
        try:
            async with self.db.begin_nested():
                await self.sync.process(event, None)
        except QuoSyncError:
            counts.errors += 1
            return False

        counts.synced += 1
        self._pending_writes += 1
        if self.apply and self._pending_writes >= _COMMIT_EVERY:
            await self.db.commit()
            self._pending_writes = 0
        return True

    def _record_api_error(self, exc: QuoApiError, counts: ResourceCounts) -> None:
        if exc.status_code in _AUTH_FAILURES:
            raise exc
        counts.errors += 1
        self.counts.api_errors += 1


def validate_backfill_window(since: datetime, until: datetime) -> None:
    """Require an explicit, recent, timezone-aware half-open interval."""
    if since.tzinfo is None or until.tzinfo is None:
        raise QuoBackfillError("--since and --until must include a UTC offset")
    normalized_since = since.astimezone(UTC)
    normalized_until = until.astimezone(UTC)
    if normalized_since >= normalized_until:
        raise QuoBackfillError("--since must be earlier than --until")
    if normalized_until - normalized_since > MAX_BACKFILL_RANGE:
        raise QuoBackfillError("Quo backfill windows cannot exceed 31 days")
    if normalized_until > datetime.now(UTC) + timedelta(minutes=1):
        raise QuoBackfillError("--until cannot be in the future")


def _message_event(
    resource: dict[str, Any],
    *,
    organization_id: str,
    phone_number_id: str,
) -> QuoWebhookEvent:
    resource_id = _resource_id(resource, "message")
    direction = _required_string(resource.get("direction"), "message direction")
    status = _required_string(resource.get("status"), "message status")
    try:
        event_type = _MESSAGE_EVENTS[direction][status]
    except KeyError:
        raise QuoBackfillDataError("Quo message lifecycle is unsupported") from None
    sender = _phone(resource.get("from"), "message sender")
    recipients_value = resource.get("to")
    if not isinstance(recipients_value, list):
        raise QuoBackfillDataError("Quo message recipients are invalid")
    recipients = [_phone(value, "message recipient") for value in recipients_value]
    event_resource = {
        "id": resource_id,
        "phoneNumberId": phone_number_id,
        "direction": direction,
        "status": status,
        "body": resource.get("body"),
        "text": resource.get("body"),
        "from": sender,
        "to": recipients,
        "senderIdentifier": sender,
        "recipientIdentifiers": recipients,
        "media": resource.get("media", []),
        "createdAt": _isoformat(_provider_timestamp(resource.get("createdAt"), "message")),
    }
    if resource.get("userId") is not None:
        event_resource["userId"] = _required_string(resource["userId"], "message user ID")
    return _event(
        resource_id=resource_id,
        event_type=event_type,
        organization_id=organization_id,
        occurred_at=_provider_timestamp(resource.get("updatedAt"), "message update"),
        resource=event_resource,
        contact_ids=[],
    )


def _call_event(
    resource: dict[str, Any],
    *,
    organization_id: str,
    phone_number_id: str,
    workspace_phone: str,
    participant: str,
) -> QuoWebhookEvent:
    resource_id = _resource_id(resource, "call")
    direction = _required_string(resource.get("direction"), "call direction")
    provider_status = _required_string(resource.get("status"), "call status")
    try:
        status = _CALL_STATUSES[provider_status]
    except KeyError:
        raise QuoBackfillDataError("Quo call lifecycle is not completed") from None
    if direction == "incoming":
        sender, recipient = participant, workspace_phone
    elif direction == "outgoing":
        sender, recipient = workspace_phone, participant
    else:
        raise QuoBackfillDataError("Quo call direction is invalid")
    duration = resource.get("duration")
    if isinstance(duration, bool) or not isinstance(duration, int) or duration < 0:
        raise QuoBackfillDataError("Quo call duration is invalid")
    provider_participants = resource.get("participants")
    if not isinstance(provider_participants, list) or not provider_participants:
        raise QuoBackfillDataError("Quo call participants are invalid")
    normalized_participants = {_phone(value, "call participant") for value in provider_participants}
    if participant not in normalized_participants or not normalized_participants.issubset(
        {workspace_phone, participant}
    ):
        raise QuoBackfillDataError("Quo group call is unsupported")
    event_resource = {
        "id": resource_id,
        "phoneNumberId": phone_number_id,
        "direction": direction,
        "status": status,
        "duration": duration,
        "from": sender,
        "to": recipient,
        "participants": [{"phoneNumber": sender}, {"phoneNumber": recipient}],
        "createdAt": _isoformat(_provider_timestamp(resource.get("createdAt"), "call")),
    }
    return _event(
        resource_id=resource_id,
        event_type="call.completed",
        organization_id=organization_id,
        occurred_at=_provider_timestamp(resource.get("completedAt"), "call completion"),
        resource=event_resource,
        contact_ids=[],
    )


def _event(
    *,
    resource_id: str,
    event_type: str,
    organization_id: str,
    occurred_at: datetime,
    resource: dict[str, Any],
    contact_ids: list[str],
) -> QuoWebhookEvent:
    event_id = f"historical:{event_type}:{resource_id}"
    return QuoWebhookEvent(
        delivery_id=event_id,
        event_id=event_id,
        event_type=event_type,
        api_version=QUO_HISTORICAL_API_VERSION,
        organization_id=organization_id,
        created_at=_isoformat(occurred_at),
        data={
            "resource": resource,
            "context": {"orgId": organization_id, "contactIds": contact_ids},
            "links": {},
        },
    )


def _timestamp_in_window(value: object, since: datetime, until: datetime) -> bool:
    timestamp = _provider_timestamp(value, "resource")
    return since <= timestamp < until


def _provider_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise QuoBackfillDataError(f"Quo {label} timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise QuoBackfillDataError(f"Quo {label} timestamp is invalid") from None
    if parsed.tzinfo is None:
        raise QuoBackfillDataError(f"Quo {label} timestamp is invalid")
    return parsed.astimezone(UTC)


def _resource_id(resource: dict[str, Any], label: str) -> str:
    return _required_string(resource.get("id"), f"{label} ID")


def _required_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 255:
        raise QuoBackfillDataError(f"Quo {label} is invalid")
    return value.strip()


def _phone(value: object, label: str) -> str:
    normalized = normalize_phone_safe(value) if isinstance(value, str) else None
    if normalized is None:
        raise QuoBackfillDataError(f"Quo {label} is invalid")
    return normalized


def _one_participant(value: object) -> str:
    if not isinstance(value, list) or len(value) != 1:
        raise QuoBackfillDataError("Quo group conversation is unsupported")
    return _phone(value[0], "conversation participant")


def _assert_phone_number_scope(resource: dict[str, Any], expected_phone_number_id: str) -> None:
    if resource.get("phoneNumberId") != expected_phone_number_id:
        raise QuoTenantMismatchError(
            "Quo returned activity outside the validated phone-number scope"
        )


def _chunks(values: list[str], size: int) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _isoformat(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
