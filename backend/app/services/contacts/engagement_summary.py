"""Contact engagement summary service.

Provides aggregated engagement counts for a single contact across
messages, calls, and appointments — without loading full rows.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment import Appointment
from app.models.call_outcome import CallOutcome
from app.models.contact import Contact
from app.models.conversation import Conversation, Message
from app.schemas.contact import ContactEngagementSummary
from app.utils.phone import normalize_phone_safe

ANSWERED_OUTCOMES = frozenset(
    {"completed", "appointment_booked", "lead_qualified", "voicemail"}
)


async def get_engagement_summary(
    db: AsyncSession,
    contact: Contact,
    workspace_id: uuid.UUID,
) -> ContactEngagementSummary:
    """Compute aggregated engagement stats for a contact."""
    now = datetime.now(UTC)
    since_7d = now - timedelta(days=7)
    since_30d = now - timedelta(days=30)

    normalized_phone = (
        normalize_phone_safe(contact.phone_number) if contact.phone_number else None
    )

    conv_conditions = [Conversation.contact_id == contact.id]
    if contact.phone_number:
        conv_conditions.append(Conversation.contact_phone == contact.phone_number)
    if normalized_phone:
        conv_conditions.append(Conversation.contact_phone == normalized_phone)

    conv_id_subq = (
        select(Conversation.id)
        .where(
            Conversation.workspace_id == workspace_id,
            or_(*conv_conditions),
        )
        .scalar_subquery()
    )

    # Combine all message-level aggregates into a single SELECT with conditional
    # aggregates. AsyncSession is NOT safe for concurrent statements on a single
    # connection (raises InvalidRequestError), so we issue one query per round-trip
    # rather than gathering multiple `db.scalar()` calls in parallel.
    is_outbound_non_voice = (Message.direction == "outbound") & (
        Message.channel != "voice"
    )
    is_inbound_non_voice = (Message.direction == "inbound") & (
        Message.channel != "voice"
    )
    is_voice = Message.channel == "voice"

    msg_stats_stmt = select(
        func.count(case((is_outbound_non_voice, 1))).label("total_sent"),
        func.count(case((is_inbound_non_voice, 1))).label("total_received"),
        func.count(case((is_voice, 1))).label("total_calls"),
        func.count(case((Message.created_at >= since_7d, 1))).label("events_7d"),
        func.count(case((Message.created_at >= since_30d, 1))).label("events_30d"),
        func.max(Message.created_at).label("last_msg_at"),
    ).where(Message.conversation_id.in_(conv_id_subq))

    msg_row = (await db.execute(msg_stats_stmt)).one()
    total_sent: int | None = msg_row.total_sent
    total_received: int | None = msg_row.total_received
    total_calls: int | None = msg_row.total_calls
    events_7d: int | None = msg_row.events_7d
    events_30d: int | None = msg_row.events_30d
    last_msg_at: datetime | None = msg_row.last_msg_at

    # Calls answered requires a join against CallOutcome, so it stays as its own
    # statement (still sequential — no asyncio.gather).
    total_calls_answered = await db.scalar(
        select(func.count())
        .select_from(Message)
        .join(CallOutcome, CallOutcome.message_id == Message.id)
        .where(
            Message.conversation_id.in_(conv_id_subq),
            Message.channel == "voice",
            CallOutcome.outcome_type.in_(ANSWERED_OUTCOMES),
        )
    )

    # Appointments live on a separate table — combine count + max in one query.
    appt_row = (
        await db.execute(
            select(
                func.count(Appointment.id).label("total"),
                func.max(Appointment.created_at).label("last_appt_at"),
            ).where(
                Appointment.workspace_id == workspace_id,
                Appointment.contact_id == contact.id,
            )
        )
    ).one()
    total_appointments: int | None = appt_row.total
    last_appt_at: datetime | None = appt_row.last_appt_at

    channel_rows = (
        await db.execute(
            select(Message.channel)
            .where(Message.conversation_id.in_(conv_id_subq))
            .distinct()
        )
    ).scalars().all()
    raw_channels = {c for c in channel_rows if c}
    channels_used: list[str] = []
    if "sms" in raw_channels:
        channels_used.append("sms")
    if raw_channels & {"voice", "voicemail"}:
        channels_used.append("voice")
    if "email" in raw_channels:
        channels_used.append("email")

    last_activity_at: datetime | None = None
    for candidate in (last_msg_at, last_appt_at):
        if candidate is None:
            continue
        if last_activity_at is None or candidate > last_activity_at:
            last_activity_at = candidate

    return ContactEngagementSummary(
        total_messages_sent=int(total_sent or 0),
        total_messages_received=int(total_received or 0),
        total_calls=int(total_calls or 0),
        total_calls_answered=int(total_calls_answered or 0),
        total_appointments=int(total_appointments or 0),
        events_last_7d=int(events_7d or 0),
        events_last_30d=int(events_30d or 0),
        last_activity_at=last_activity_at,
        channels_used=channels_used,
    )
