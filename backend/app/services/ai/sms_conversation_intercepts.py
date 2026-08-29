"""Deterministic SMS guards for callbacks, disengagement, and human handoff.

These intents are intentionally handled before the language model.  A customer who
asks for a normal phone call must not be pushed through the appointment/calendar
workflow, and an upset or disengaging customer must not be trapped in a repeated
qualification loop.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.conversation import Conversation, Message
from app.models.human_nudge import HumanNudge
from app.models.opportunity import Opportunity
from app.services.ai.message_context_builder import get_workspace_timezone
from app.services.notifications import notify_workspace_event

logger = structlog.get_logger()

SmsInterceptIntent = Literal[
    "callback_request",
    "customer_will_call",
    "frustrated",
    "disengaged",
    "busy",
]


@dataclass(frozen=True, slots=True)
class SmsInterceptResult:
    """A deterministic reply that bypasses normal LLM generation."""

    intent: SmsInterceptIntent
    response_text: str
    pause_ai_after_reply: bool
    disable_followups_after_reply: bool


_CUSTOMER_WILL_CALL_PATTERNS = (
    re.compile(
        r"\b(?:i(?:'|’)?ll|i\s+will|i(?:'|’)?m\s+going\s+to|i\s+am\s+going\s+to)\s+"
        r"(?:just\s+)?call\b",
        re.IGNORECASE,
    ),
    re.compile(r"\blet\s+me\s+call\b", re.IGNORECASE),
)

_CALLBACK_REQUEST_PATTERNS = (
    re.compile(r"\b(?:please\s+)?call\s+me\b", re.IGNORECASE),
    re.compile(r"\bgive\s+me\s+(?:a\s+)?call\b", re.IGNORECASE),
    re.compile(r"\b(?:can|could|would)\s+(?:you|someone|somebody)\s+call\s+me\b", re.IGNORECASE),
    re.compile(r"\bhave\s+(?:someone|somebody|the\s+team)\s+call\s+me\b", re.IGNORECASE),
    re.compile(r"\b(?:phone|ring)\s+me\b", re.IGNORECASE),
)

_NEGATED_CALLBACK_PATTERN = re.compile(
    r"\b(?:do\s+not|don['’]?t|dont|never|stop)\s+(?:phone|ring|call(?:ing)?)\s+me\b",
    re.IGNORECASE,
)
_EXPLICIT_OPTOUT_PATTERN = re.compile(
    r"(?:^\s*(?:stop|stopall|unsubscribe|opt\s*out|optout)\s*[.!]*\s*$|"
    r"\b(?:stop\s+(?:texting|messaging|contacting)|remove\s+me|take\s+me\s+off|"
    r"leave\s+me\s+alone|no\s+more\s+messages|don['’]?t\s+want\b.*\bmessages|"
    r"quit\s+(?:texting|messaging|sending))\b)",
    re.IGNORECASE,
)

_DISENGAGED_PATTERNS = (
    re.compile(r"^\s*never\s*mind\b", re.IGNORECASE),
    re.compile(r"^\s*nevermind\b", re.IGNORECASE),
    re.compile(r"^\s*no\s*,?\s*(?:thank\s+you|thanks)\b", re.IGNORECASE),
    re.compile(r"\bnot\s+interested\b", re.IGNORECASE),
)

_BUSY_PATTERNS = (
    re.compile(r"\bbusy\s+(?:right\s+)?now\b", re.IGNORECASE),
    re.compile(r"\b(?:cannot|can['’]?t)\s+(?:talk|speak)\s+(?:right\s+)?now\b", re.IGNORECASE),
    re.compile(r"\b(?:talk|speak)\s+(?:to\s+you\s+)?later\b", re.IGNORECASE),
    re.compile(r"\blet\s+you\s+know\s+later\b", re.IGNORECASE),
)

_FRUSTRATION_PATTERNS = (
    re.compile(r"\b(?:to|too)\s+much\s+hassle\b", re.IGNORECASE),
    re.compile(r"\b(?:this|so)\s+much\s+hassle\b", re.IGNORECASE),
    re.compile(r"\bway\s+(?:to|too)\s+much\b", re.IGNORECASE),
    re.compile(r"\b(?:this\s+much|too)\s+(?:complicated|involved|difficult)\b", re.IGNORECASE),
    re.compile(r"\bmade?\s+this\s+(?:too\s+)?(?:complicated|difficult)\b", re.IGNORECASE),
    re.compile(r"\balready\s+(?:said|told|answered)\b", re.IGNORECASE),
    re.compile(r"\bwrong\s+business\b", re.IGNORECASE),
    re.compile(r"\bjust\s+(?:to|trying\s+to)\s+(?:talk|speak)\b", re.IGNORECASE),
    re.compile(r"\bare\s+you\s+(?:a|an)\s+(?:real\s+)?business\b", re.IGNORECASE),
)

_WEEKDAY_INDEX = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
_CALLBACK_TIME_PATTERN = re.compile(
    r"\b(?:at\s+)?(?P<hour>1[0-2]|0?[1-9])(?:[:.](?P<minute>[0-5]\d))?\s*"
    r"(?P<meridiem>a\.?m\.?|p\.?m\.?)\b",
    re.IGNORECASE,
)
_CALLBACK_WEEKDAY_PATTERN = re.compile(
    rf"\b(?P<weekday>{'|'.join(_WEEKDAY_INDEX)})\b",
    re.IGNORECASE,
)


def classify_sms_intercept_intent(body: str) -> SmsInterceptIntent | None:
    """Classify only high-confidence intents that are unsafe to leave to the LLM."""

    text = " ".join((body or "").split())
    if not text:
        return None

    # Let the existing compliance opt-out path handle "don't call me" and similar
    # requests.  Without this check, the substring "call me" would do the opposite.
    intent: SmsInterceptIntent | None = None
    can_intercept = not _EXPLICIT_OPTOUT_PATTERN.search(
        text
    ) and not _NEGATED_CALLBACK_PATTERN.search(text)
    if can_intercept:
        if any(pattern.search(text) for pattern in _CUSTOMER_WILL_CALL_PATTERNS):
            intent = "customer_will_call"
        elif any(pattern.search(text) for pattern in _DISENGAGED_PATTERNS):
            intent = "disengaged"
        elif any(pattern.search(text) for pattern in _FRUSTRATION_PATTERNS):
            intent = "frustrated"
        elif any(pattern.search(text) for pattern in _CALLBACK_REQUEST_PATTERNS):
            intent = "callback_request"
        elif any(pattern.search(text) for pattern in _BUSY_PATTERNS):
            intent = "busy"
    return intent


def parse_callback_due_at(
    body: str,
    *,
    timezone: str,
    now: datetime | None = None,
) -> datetime | None:
    """Parse a callback reminder time without invoking appointment/calendar tools."""

    normalized = " ".join((body or "").lower().split())
    time_match = _CALLBACK_TIME_PATTERN.search(normalized)
    weekday_match = _CALLBACK_WEEKDAY_PATTERN.search(normalized)
    has_relative_day = "today" in normalized or "tomorrow" in normalized
    if time_match is None and weekday_match is None and not has_relative_day:
        return None

    try:
        tz = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo("America/New_York")

    reference = now or datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    local_now = reference.astimezone(tz)

    # A date without a time becomes a 9 AM reminder for the responsible person.
    hour = 9
    minute = 0
    if time_match is not None:
        hour = int(time_match.group("hour")) % 12
        if time_match.group("meridiem").lower().startswith("p"):
            hour += 12
        minute = int(time_match.group("minute") or 0)

    if "tomorrow" in normalized:
        day_offset = 1
    elif "today" in normalized:
        day_offset = 0
    elif weekday_match is not None:
        target_weekday = _WEEKDAY_INDEX[weekday_match.group("weekday").lower()]
        day_offset = (target_weekday - local_now.weekday()) % 7
    else:
        day_offset = 0

    target_date = local_now.date() + timedelta(days=day_offset)
    local_target = datetime(
        target_date.year,
        target_date.month,
        target_date.day,
        hour,
        minute,
        tzinfo=tz,
    )
    if local_target <= local_now:
        if time_match is None and day_offset == 0:
            return reference.astimezone(UTC)
        # An explicit weekday means the next occurrence; a bare/"today" time means
        # the next day rather than creating an already-overdue reminder.
        days_forward = 7 if weekday_match is not None and "today" not in normalized else 1
        local_target += timedelta(days=days_forward)
    return local_target.astimezone(UTC)


def _display_phone(phone: str | None) -> str:
    """Return a friendly US phone number when possible, otherwise the stored value."""

    if not phone:
        return "our main number"
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return phone


async def intercept_sms_conversation(
    db: AsyncSession,
    *,
    conversation: Conversation,
    inbound_message: Message,
) -> SmsInterceptResult | None:
    """Handle a callback/stop/handoff intent without invoking booking or an LLM."""

    body = inbound_message.body or ""
    intent = classify_sms_intercept_intent(body)
    if intent is None:
        return None

    if intent == "customer_will_call":
        assigned_to_user_id = await _upsert_operator_nudge(
            db,
            conversation=conversation,
            inbound_message=inbound_message,
            nudge_type="customer_will_call",
            title_prefix="Customer plans to call",
            message_prefix="Customer said they will call the business",
        )
        await _notify_operator(
            db,
            conversation=conversation,
            inbound_message=inbound_message,
            title="Customer plans to call",
            body=f'Customer message: "{body[:240]}"',
            event_type="customer_will_call",
            assigned_to_user_id=assigned_to_user_id,
        )
        return SmsInterceptResult(
            intent=intent,
            response_text=(
                f"Sounds good. Call us at {_display_phone(conversation.workspace_phone)} when "
                "you're free. If we miss you, leave a message or text us here and the team will "
                "get back to you."
            ),
            pause_ai_after_reply=True,
            disable_followups_after_reply=True,
        )

    if intent == "disengaged":
        return SmsInterceptResult(
            intent=intent,
            response_text="Understood. Thanks for letting us know. Have a good day.",
            pause_ai_after_reply=True,
            disable_followups_after_reply=True,
        )

    if intent == "busy":
        return SmsInterceptResult(
            intent=intent,
            response_text=(
                "No problem - I'll stop here. Text or call us when you're ready, and we'll pick "
                "it up from there."
            ),
            pause_ai_after_reply=False,
            disable_followups_after_reply=True,
        )

    if intent == "callback_request":
        assigned_to_user_id = await _upsert_operator_nudge(
            db,
            conversation=conversation,
            inbound_message=inbound_message,
            nudge_type="callback_request",
            title_prefix="Callback requested",
            message_prefix="Customer requested a phone callback by SMS",
        )
        await _notify_operator(
            db,
            conversation=conversation,
            inbound_message=inbound_message,
            title="Customer requested a callback",
            body=f'Call request: "{body[:240]}"',
            event_type="callback_request",
            assigned_to_user_id=assigned_to_user_id,
        )
        return SmsInterceptResult(
            intent=intent,
            response_text=(
                "Absolutely - I've asked our team to call this number. They can see the details "
                "you sent."
            ),
            pause_ai_after_reply=True,
            disable_followups_after_reply=True,
        )

    assigned_to_user_id = await _upsert_operator_nudge(
        db,
        conversation=conversation,
        inbound_message=inbound_message,
        nudge_type="ai_handoff",
        title_prefix="AI handoff needed",
        message_prefix="Customer expressed frustration with the automated conversation",
    )
    await _notify_operator(
        db,
        conversation=conversation,
        inbound_message=inbound_message,
        title="Customer needs a human response",
        body=f'AI was paused after this message: "{body[:240]}"',
        event_type="ai_handoff",
        assigned_to_user_id=assigned_to_user_id,
    )
    return SmsInterceptResult(
        intent="frustrated",
        response_text=(
            "You're right - this became more complicated than it should have. I've stopped the "
            "automated questions and alerted a team member. You don't need to repeat anything."
        ),
        pause_ai_after_reply=True,
        disable_followups_after_reply=True,
    )


async def _upsert_operator_nudge(
    db: AsyncSession,
    *,
    conversation: Conversation,
    inbound_message: Message,
    nudge_type: str,
    title_prefix: str,
    message_prefix: str,
) -> int | None:
    """Create one callback/handoff task and return its responsible team member."""

    dedup_key = f"sms:{nudge_type}:{conversation.id}"
    result = await db.execute(
        select(HumanNudge).where(
            HumanNudge.dedup_key == dedup_key,
            HumanNudge.workspace_id == conversation.workspace_id,
        )
    )
    nudge = result.scalar_one_or_none()
    now = datetime.now(UTC)
    due_date = now
    if nudge_type in {"callback_request", "customer_will_call"}:
        timezone = await get_workspace_timezone(conversation.workspace_id, db)
        parsed_due_date = parse_callback_due_at(
            inbound_message.body or "",
            timezone=timezone,
            now=now,
        )
        if parsed_due_date is not None:
            due_date = parsed_due_date

    contact_name = await _contact_name(db, conversation)
    assigned_to_user_id = await _assigned_team_member_id(db, conversation)
    title = f"{title_prefix}: {contact_name}"
    message = f'{message_prefix}: "{(inbound_message.body or "")[:500]}"'

    if nudge is None:
        db.add(
            HumanNudge(
                workspace_id=conversation.workspace_id,
                contact_id=conversation.contact_id,
                nudge_type=nudge_type,
                title=title,
                message=message,
                suggested_action="call",
                priority="high",
                due_date=due_date,
                status="pending",
                assigned_to_user_id=assigned_to_user_id,
                dedup_key=dedup_key,
            )
        )
    else:
        nudge.title = title
        nudge.message = message
        nudge.priority = "high"
        nudge.due_date = due_date
        nudge.status = "pending"
        nudge.snoozed_until = None
        nudge.assigned_to_user_id = assigned_to_user_id
    await db.flush()
    return assigned_to_user_id


async def _assigned_team_member_id(
    db: AsyncSession,
    conversation: Conversation,
) -> int | None:
    """Use the current open deal owner; fall back to a workspace-wide nudge."""

    if conversation.contact_id is None:
        return None
    result = await db.execute(
        select(Opportunity.assigned_user_id)
        .where(
            Opportunity.workspace_id == conversation.workspace_id,
            Opportunity.primary_contact_id == conversation.contact_id,
            Opportunity.status == "open",
            Opportunity.is_active.is_(True),
            Opportunity.assigned_user_id.is_not(None),
        )
        .order_by(Opportunity.updated_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _contact_name(db: AsyncSession, conversation: Conversation) -> str:
    if conversation.contact_id is not None:
        result = await db.execute(
            select(Contact).where(
                Contact.id == conversation.contact_id,
                Contact.workspace_id == conversation.workspace_id,
            )
        )
        contact = result.scalar_one_or_none()
        if contact is not None and contact.full_name:
            return contact.full_name
    return conversation.contact_phone or "customer"


async def _notify_operator(
    db: AsyncSession,
    *,
    conversation: Conversation,
    inbound_message: Message,
    title: str,
    body: str,
    event_type: str,
    assigned_to_user_id: int | None = None,
) -> None:
    """Best-effort push/email alert; notification failure must not block the reply."""

    try:
        await notify_workspace_event(
            db,
            workspace_id=conversation.workspace_id,
            notification_type="message",
            title=title,
            target_user_ids=[assigned_to_user_id] if assigned_to_user_id is not None else None,
            body=body,
            data={
                "type": event_type,
                "conversationId": str(conversation.id),
                "screen": f"/(tabs)/messages/{conversation.id}",
            },
            channel_id="messages",
            email_subject=title,
            email_heading=title,
            email_intro=body,
            dedupe_key=f"{event_type}:{inbound_message.id}",
        )
    except Exception as exc:  # noqa: BLE001 - alerts must not block customer handling
        logger.warning(
            "sms_intercept_notification_failed",
            conversation_id=str(conversation.id),
            intent=event_type,
            error_type=type(exc).__name__,
        )
