"""Resend bounce/complaint suppression.

Recording an ``EmailEvent`` and bumping ``emails_bounced`` leaves the address
fully eligible for the next campaign, so a dead mailbox gets retried forever and
a spam complaint costs nothing. Complaint rate is the number mailbox providers
actually police, so these paths decide whether the sending domain survives.

The branch logic under test is "which provider events suppress a contact" — the
surrounding ORM plumbing is covered by the contract tests.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.email_event import EmailEventType
from app.services.webhooks.resend import ResendWebhookEvent, _apply_suppression


def _event(event_type: str, mapped: EmailEventType, data: dict[str, Any]) -> ResendWebhookEvent:
    return ResendWebhookEvent(
        event_type=event_type,
        data=data,
        occurred_at=datetime.now(UTC),
        provider_event_id="evt_1",
        provider_message_id="msg_1",
        mapped_event_type=mapped,
    )


def _message(contact_id: int | None) -> MagicMock:
    message = MagicMock()
    message.conversation.contact_id = contact_id
    return message


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mapped", "data", "expected_source"),
    [
        (
            EmailEventType.BOUNCED,
            {"bounce": {"type": "Permanent", "subType": "General"}},
            "hard_bounce",
        ),
        (EmailEventType.COMPLAINED, {}, "spam_complaint"),
        (EmailEventType.UNSUBSCRIBED, {}, "provider_unsubscribe"),
    ],
)
async def test_suppresses_contact(
    mapped: EmailEventType, data: dict[str, Any], expected_source: str
) -> None:
    db = MagicMock()
    with patch("app.services.webhooks.resend.record_email_opt_out", AsyncMock()) as record_opt_out:
        await _apply_suppression(db, mapped, _event("e", mapped, data), _message(77), MagicMock())

    record_opt_out.assert_awaited_once_with(db, 77, source=expected_source)


@pytest.mark.asyncio
@pytest.mark.parametrize("bounce_type", ["Transient", "Undetermined"])
async def test_soft_bounce_does_not_suppress(bounce_type: str) -> None:
    """A full mailbox is temporary. Opting them out would lose a real customer."""
    mapped = EmailEventType.BOUNCED
    event = _event("email.bounced", mapped, {"bounce": {"type": bounce_type}})

    with patch("app.services.webhooks.resend.record_email_opt_out", AsyncMock()) as record_opt_out:
        await _apply_suppression(MagicMock(), mapped, event, _message(77), MagicMock())

    record_opt_out.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data",
    [{}, {"bounce": None}, {"bounce": "Permanent"}],
    ids=["no_bounce_block", "null_bounce", "bounce_not_a_dict"],
)
async def test_malformed_bounce_payload_does_not_suppress(data: dict[str, Any]) -> None:
    """Provider payloads are untrusted input; a missing block must not crash."""
    mapped = EmailEventType.BOUNCED

    with patch("app.services.webhooks.resend.record_email_opt_out", AsyncMock()) as record_opt_out:
        await _apply_suppression(
            MagicMock(), mapped, _event("email.bounced", mapped, data), _message(77), MagicMock()
        )

    record_opt_out.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("mapped", [EmailEventType.DELIVERED, EmailEventType.OPENED])
async def test_benign_events_do_not_suppress(mapped: EmailEventType) -> None:
    with patch("app.services.webhooks.resend.record_email_opt_out", AsyncMock()) as record_opt_out:
        await _apply_suppression(
            MagicMock(), mapped, _event("e", mapped, {}), _message(77), MagicMock()
        )

    record_opt_out.assert_not_awaited()


@pytest.mark.asyncio
async def test_complaint_without_contact_is_logged_not_crashed() -> None:
    """Unlinked conversations happen; the webhook must still return cleanly."""
    mapped = EmailEventType.COMPLAINED
    log = MagicMock()

    with patch("app.services.webhooks.resend.record_email_opt_out", AsyncMock()) as record_opt_out:
        await _apply_suppression(MagicMock(), mapped, _event("e", mapped, {}), _message(None), log)

    record_opt_out.assert_not_awaited()
    log.warning.assert_called_once()


@pytest.mark.asyncio
async def test_missing_message_does_not_crash() -> None:
    mapped = EmailEventType.COMPLAINED

    with patch("app.services.webhooks.resend.record_email_opt_out", AsyncMock()) as record_opt_out:
        await _apply_suppression(MagicMock(), mapped, _event("e", mapped, {}), None, MagicMock())

    record_opt_out.assert_not_awaited()
