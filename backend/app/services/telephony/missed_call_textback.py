"""Automatic SMS text-back for missed inbound calls.

When an inbound call is not answered/completed (no answer, busy, rejected, or
voicemail), this service sends a single follow-up SMS inviting the caller to
book in. The reply re-enters the AI SMS conversation (the conversation is left
``ai_enabled`` with an assigned agent), so the text bot continues qualifying
and booking.

Behaviour is gated per workspace via ``workspace.settings["missed_call_textback"]``:

    {
        "enabled": true,
        "template": "Sorry we missed you — want me to book you in?",
        "quiet_hours_start": "21:00",
        "quiet_hours_end": "08:00",
        "timezone": "America/New_York"
    }

Safety rails:

* **Idempotent** — the outbound send is keyed on the Telnyx ``call_control_id``
  so duplicate ``call.hangup`` webhook deliveries never produce a second text.
* **Opt-out aware** — global opt-out (:class:`OptOutManager`) is enforced and a
  recent inbound opt-out keyword (:mod:`app.services.ai.opt_out_detector`)
  suppresses the text.
* **Quiet hours** — sends are skipped when the workspace is inside its
  configured quiet-hours window.
"""

from __future__ import annotations

import contextlib
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.contact import Contact
from app.models.conversation import Conversation, Message, MessageChannel, MessageDirection
from app.models.phone_number import PhoneNumber
from app.models.workspace import Workspace
from app.services.ai.opt_out_detector import has_potential_opt_out_keywords
from app.services.automations.events import EVENT_MISSED_CALL, emit_automation_event
from app.services.outbound.delivery import (
    OutboundDeliveryChannel,
    OutboundDeliveryRequest,
    OutboundDeliveryStatus,
    outbound_delivery_service,
)
from app.services.rate_limiting.opt_out_manager import OptOutManager

logger = structlog.get_logger()

# Settings key under ``workspace.settings`` holding the feature configuration.
SETTINGS_KEY = "missed_call_textback"

# Default copy for the missed-call follow-up text.
DEFAULT_TEMPLATE = "Sorry we missed you — want me to book you in?"

# Call outcomes (from CallOutcomeClassifier) that count as "missed" inbound
# calls and should trigger the text-back. A 5s+ NORMAL_CLEARING call is a real
# conversation and produces ``outcome=None`` upstream, so it is never sent.
MISSED_CALL_OUTCOMES = frozenset({"no_answer", "busy", "rejected", "voicemail"})

# Idempotency scope: combined with the call_control_id this yields a stable
# UUID so duplicate webhooks collapse onto one outbound Message row.
IDEMPOTENCY_SCOPE = "missed_call_textback"

_opt_out_manager = OptOutManager()


@dataclass(slots=True, frozen=True)
class MissedCallTextbackSettings:
    """Per-workspace configuration for missed-call text-back."""

    enabled: bool = False
    template: str = DEFAULT_TEMPLATE
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None
    timezone: str | None = None


def get_missed_call_textback_settings(workspace: Workspace) -> MissedCallTextbackSettings:
    """Return the missed-call text-back settings for a workspace (defaults when unset)."""
    raw = (workspace.settings or {}).get(SETTINGS_KEY, {})
    if not isinstance(raw, dict):
        raw = {}
    template = raw.get("template") or DEFAULT_TEMPLATE
    return MissedCallTextbackSettings(
        enabled=bool(raw.get("enabled", False)),
        template=str(template),
        quiet_hours_start=raw.get("quiet_hours_start"),
        quiet_hours_end=raw.get("quiet_hours_end"),
        timezone=raw.get("timezone"),
    )


def _parse_clock(value: str | None) -> time | None:
    """Parse an ``HH:MM`` (or ``HH:MM:SS``) string into a :class:`time`."""
    if not value:
        return None
    try:
        parts = [int(p) for p in str(value).split(":")]
    except ValueError:
        return None
    if not parts:
        return None
    hour = parts[0]
    minute = parts[1] if len(parts) > 1 else 0
    second = parts[2] if len(parts) > 2 else 0
    if not (0 <= hour < 24 and 0 <= minute < 60 and 0 <= second < 60):
        return None
    return time(hour, minute, second)


def is_within_quiet_hours(
    config: MissedCallTextbackSettings,
    workspace: Workspace,
    now: datetime | None = None,
) -> bool:
    """Return True when ``now`` falls inside the workspace quiet-hours window."""
    start = _parse_clock(config.quiet_hours_start)
    end = _parse_clock(config.quiet_hours_end)
    if start is None or end is None:
        return False

    timezone_name = config.timezone or (workspace.settings or {}).get("timezone") or "UTC"
    reference = now or datetime.now(UTC)
    try:
        local_now = reference.astimezone(ZoneInfo(timezone_name))
    except ZoneInfoNotFoundError:
        local_now = reference.astimezone(ZoneInfo("UTC"))

    local_time = local_now.time()
    if start <= end:
        return start <= local_time < end
    # Window wraps past midnight (e.g. 21:00 -> 08:00).
    return local_time >= start or local_time < end


def render_textback_template(template: str, contact: Contact | None) -> str:
    """Render ``{placeholder}`` tokens in the template using contact data."""
    first_name = contact.first_name if contact and contact.first_name else ""
    last_name = (contact.last_name if contact else None) or ""
    full_name = " ".join(filter(None, [first_name, last_name]))
    replacements: dict[str, str] = {
        "first_name": first_name,
        "last_name": last_name,
        "full_name": full_name,
        "company_name": (contact.company_name if contact else None) or "",
    }
    rendered = template
    for placeholder, value in replacements.items():
        with contextlib.suppress(Exception):
            pattern = re.compile(rf"\{{{placeholder}\}}", re.IGNORECASE)
            rendered = pattern.sub(value, rendered)
    return rendered.strip()


async def _recent_inbound_opt_out(
    db: AsyncSession,
    conversation_id: uuid.UUID,
) -> bool:
    """Return True when the latest inbound text in the conversation looks like an opt-out."""
    result = await db.execute(
        select(Message.body)
        .where(
            Message.conversation_id == conversation_id,
            Message.direction == MessageDirection.INBOUND,
            Message.channel.in_((MessageChannel.SMS, MessageChannel.IMESSAGE)),
        )
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    body = result.scalar_one_or_none()
    if not body:
        return False
    return has_potential_opt_out_keywords(body)


async def _resolve_agent_id(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    workspace_phone: str,
    conversation: Conversation,
) -> uuid.UUID | None:
    """Pick the agent that should own the SMS follow-up conversation."""
    if conversation.assigned_agent_id is not None:
        return conversation.assigned_agent_id
    result = await db.execute(
        select(PhoneNumber.assigned_agent_id).where(
            PhoneNumber.workspace_id == workspace_id,
            PhoneNumber.is_active.is_(True),
            (PhoneNumber.phone_number == workspace_phone)
            | (PhoneNumber.mac_relay_sender_id == workspace_phone),
        )
    )
    return result.scalar_one_or_none()


async def send_missed_call_textback(  # noqa: PLR0911, PLR0912
    call_control_id: str,
    call_outcome: str,
    log: Any,
    *,
    now: datetime | None = None,
) -> bool:
    """Send a missed-call follow-up SMS for an unanswered inbound call.

    Called from the Telnyx voice hangup / machine-detection handlers. Returns
    True only when an SMS was actually delivered to the provider.
    """
    from app.db.session import AsyncSessionLocal

    log = log.bind(call_control_id=call_control_id, call_outcome=call_outcome)

    if call_outcome not in MISSED_CALL_OUTCOMES:
        log.info("missed_call_textback_outcome_skipped")
        return False

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Message)
            .options(selectinload(Message.conversation))
            .where(Message.provider_message_id == call_control_id)
        )
        message = result.scalar_one_or_none()
        if message is None:
            log.warning("missed_call_textback_message_not_found")
            return False

        if message.direction != MessageDirection.INBOUND:
            log.info("missed_call_textback_not_inbound", direction=str(message.direction))
            return False

        conversation = message.conversation
        if conversation is None:
            log.warning("missed_call_textback_no_conversation")
            return False

        workspace_id = conversation.workspace_id
        contact_phone = conversation.contact_phone
        workspace_phone = conversation.workspace_phone

        workspace = await db.get(Workspace, workspace_id)
        if workspace is None:
            log.warning("missed_call_textback_workspace_not_found")
            return False

        config = get_missed_call_textback_settings(workspace)
        if not config.enabled:
            log.info("missed_call_textback_disabled", workspace_id=str(workspace_id))
            return False

        if is_within_quiet_hours(config, workspace, now):
            log.info("missed_call_textback_quiet_hours", workspace_id=str(workspace_id))
            return False

        # Opt-out: persistent global opt-out list takes precedence; a recent
        # inbound opt-out keyword also suppresses the text.
        if await _opt_out_manager.check_opt_out(workspace_id, contact_phone, db):
            log.info("missed_call_textback_opted_out", workspace_id=str(workspace_id))
            return False
        if await _recent_inbound_opt_out(db, conversation.id):
            log.info("missed_call_textback_recent_opt_out", workspace_id=str(workspace_id))
            return False

        contact: Contact | None = None
        if conversation.contact_id is not None:
            contact = await db.get(Contact, conversation.contact_id)

        body = render_textback_template(config.template, contact)
        if not body:
            log.warning("missed_call_textback_empty_body")
            return False

        agent_id = await _resolve_agent_id(db, workspace_id, workspace_phone, conversation)

        delivery = await outbound_delivery_service.deliver(
            db,
            OutboundDeliveryRequest(
                workspace_id=workspace_id,
                channel=OutboundDeliveryChannel.SMS,
                to=contact_phone,
                from_=workspace_phone,
                body=body,
                contact=contact,
                agent_id=agent_id,
                idempotency_scope=IDEMPOTENCY_SCOPE,
                idempotency_parts=(call_control_id,),
                action_type=IDEMPOTENCY_SCOPE,
                # The caller just dialled this business, so inbound text-back is
                # permitted without a prior opt-in. Global opt-out is still
                # enforced above and inside the delivery compliance gate.
                require_sms_consent=False,
            ),
        )

        if delivery.status is OutboundDeliveryStatus.BLOCKED:
            log.info("missed_call_textback_blocked", reason=delivery.reason)
            return False
        if not delivery.delivered or delivery.message is None:
            log.warning("missed_call_textback_send_failed", reason=delivery.reason)
            return False

        # Keep the conversation in AI SMS mode so the caller's reply re-enters
        # the bot and continues qualifying/booking.
        await _enter_ai_sms_mode(db, conversation, agent_id)

        # Fire the missed-call automation trigger (best-effort; committed below).
        await emit_automation_event(
            db,
            workspace_id=workspace_id,
            event_type=EVENT_MISSED_CALL,
            contact_id=conversation.contact_id,
            payload={
                "call_control_id": call_control_id,
                "call_outcome": call_outcome,
                "contact_phone": contact_phone,
            },
        )
        await db.commit()

        await _notify_textback_sent(
            db,
            workspace=workspace,
            contact=contact,
            contact_phone=contact_phone,
            body=body,
            call_control_id=call_control_id,
            log=log,
        )

        log.info(
            "missed_call_textback_sent",
            workspace_id=str(workspace_id),
            message_id=str(delivery.message.id),
        )
        return True


async def _notify_textback_sent(
    db: AsyncSession,
    *,
    workspace: Workspace,
    contact: Contact | None,
    contact_phone: str,
    body: str,
    call_control_id: str,
    log: Any,
) -> None:
    """Push + email workspace members that a missed-call text-back went out."""
    from app.services.notifications import notify_workspace_event

    who = (contact.full_name if contact and contact.full_name else None) or contact_phone
    title = "Missed-call text-back sent"
    message = f"We auto-texted {who} after a missed call."
    try:
        await notify_workspace_event(
            db,
            workspace_id=workspace.id,
            notification_type="missed_call_textback",
            title=title,
            body=message,
            data={
                "type": "missed_call_textback",
                "contactPhone": contact_phone,
                "screen": "/(tabs)/conversations",
            },
            channel_id="messages",
            email_subject=title,
            email_heading="Missed-Call Text-Back Sent",
            email_intro=message,
            email_details={
                "Contact": who,
                "Phone": contact_phone,
                "Message sent": body,
            },
            dedupe_key=call_control_id,
        )
    except Exception as exc:
        log.warning("missed_call_textback_notification_failed", error=str(exc))


async def _enter_ai_sms_mode(
    db: AsyncSession,
    conversation: Conversation,
    agent_id: uuid.UUID | None,
) -> None:
    """Ensure the conversation will route the caller's reply back into the AI bot."""
    fresh = await db.get(Conversation, conversation.id)
    if fresh is None:
        return
    changed = False
    if fresh.channel == MessageChannel.VOICE.value:
        fresh.channel = MessageChannel.SMS.value
        changed = True
    if not fresh.ai_enabled:
        fresh.ai_enabled = True
        changed = True
    if fresh.ai_paused:
        fresh.ai_paused = False
        changed = True
    if fresh.assigned_agent_id is None and agent_id is not None:
        fresh.assigned_agent_id = agent_id
        changed = True
    if changed:
        await db.commit()
