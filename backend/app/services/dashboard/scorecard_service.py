"""Receptionist scorecard aggregation service.

Computes the owner-facing retention scorecard for a workspace over a date
range. The heavy lifting is split into two layers:

* :class:`ScorecardService` runs the workspace-scoped queries against
  ``call_outcomes``, ``messages``, ``appointments``, ``opportunities`` and
  ``contacts``, mapping each row into a small frozen dataclass.
* The module-level ``aggregate_*`` helpers turn those dataclasses into the
  response numbers. They are pure functions (no DB, no clock) so the metric
  maths — answer rate, missed-call recovery, after-hours coverage, average
  handle time, top reasons, daily new leads — can be unit-tested directly.
"""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment import Appointment
from app.models.call_outcome import CallOutcome
from app.models.contact import Contact
from app.models.conversation import (
    Conversation,
    Message,
    MessageChannel,
    MessageDirection,
)
from app.models.opportunity import Opportunity
from app.models.workspace import Workspace
from app.schemas.scorecard import CallReasonStat, DailyLeadCount, ReceptionistScorecard
from app.services.telephony.missed_call_textback import MISSED_CALL_OUTCOMES

logger = structlog.get_logger()

# Outcomes that count as a genuinely answered/handled call.
ANSWERED_OUTCOMES = frozenset({"completed", "appointment_booked", "lead_qualified"})
# Message delivery statuses that imply the call connected when no structured
# CallOutcome row exists yet.
ANSWERED_STATUSES = frozenset({"answered", "completed"})

# Business-hours window (local workspace time). Calls outside this window — or
# on weekends — count as "after hours".
BUSINESS_HOURS_START = time(8, 0)
BUSINESS_HOURS_END = time(18, 0)

# How many call reasons to surface.
TOP_REASONS_LIMIT = 6

DEFAULT_RANGE_DAYS = 30


@dataclass(slots=True, frozen=True)
class CallRow:
    """One voice call within the range with its (optional) outcome."""

    conversation_id: uuid.UUID
    contact_id: int | None
    created_at: datetime
    status: str
    channel: str
    duration_seconds: int | None
    outcome_type: str | None
    signals: dict[str, object]

    @property
    def is_answered(self) -> bool:
        if self.outcome_type is not None:
            return self.outcome_type in ANSWERED_OUTCOMES
        return self.status in ANSWERED_STATUSES

    @property
    def is_missed(self) -> bool:
        if self.channel == MessageChannel.VOICEMAIL.value:
            return True
        return (self.outcome_type or "") in MISSED_CALL_OUTCOMES


@dataclass(slots=True, frozen=True)
class TextbackRow:
    """An outbound SMS used to recover a missed call (text-back)."""

    conversation_id: uuid.UUID
    created_at: datetime


@dataclass(slots=True, frozen=True)
class InboundReplyRow:
    """An inbound SMS/voice reply, signalling the caller re-engaged."""

    conversation_id: uuid.UUID
    created_at: datetime


@dataclass(slots=True, frozen=True)
class AppointmentRow:
    """An appointment booked within the range."""

    contact_id: int | None
    created_at: datetime


@dataclass(slots=True, frozen=True)
class OpportunityRow:
    """An opportunity touched within the range, for booked/won revenue."""

    amount: float
    created_at: datetime
    status: str
    closed_date: date | None


@dataclass(slots=True, frozen=True)
class LeadRow:
    """A contact (lead) created within the range."""

    created_at: datetime


def _resolve_tz(workspace: Workspace) -> ZoneInfo:
    tz_name = (workspace.settings or {}).get("timezone") or "UTC"
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _is_after_hours(moment: datetime, tz: ZoneInfo) -> bool:
    """Return True when ``moment`` falls outside local business hours."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    local = moment.astimezone(tz)
    if local.weekday() >= 5:  # Saturday/Sunday
        return True
    return not (BUSINESS_HOURS_START <= local.time() < BUSINESS_HOURS_END)


def _extract_reasons(signals: dict[str, object]) -> list[str]:
    """Pull human call reasons from a CallOutcome ``signals`` blob."""
    for key in ("intents", "topics"):
        raw = signals.get(key)
        if isinstance(raw, list) and raw:
            return [str(item).strip() for item in raw if str(item).strip()]
    return []


def _compute_recovery(
    missed: list[CallRow],
    textbacks: list[TextbackRow],
    inbound_replies: list[InboundReplyRow],
    appointments: list[AppointmentRow],
) -> tuple[int, int]:
    """Return ``(textback_sent, recovered)`` counts for missed calls.

    A missed call counts as ``textback_sent`` when an outbound SMS followed it
    in the same conversation, and ``recovered`` when the caller re-engaged
    (a later inbound reply) or a later appointment was booked for the contact.
    """
    textback_by_conv: dict[uuid.UUID, list[datetime]] = {}
    for tb in textbacks:
        textback_by_conv.setdefault(tb.conversation_id, []).append(tb.created_at)
    reply_by_conv: dict[uuid.UUID, list[datetime]] = {}
    for reply in inbound_replies:
        reply_by_conv.setdefault(reply.conversation_id, []).append(reply.created_at)
    appts_by_contact: dict[int, list[datetime]] = {}
    for appt in appointments:
        if appt.contact_id is not None:
            appts_by_contact.setdefault(appt.contact_id, []).append(appt.created_at)

    textback_sent = 0
    recovered = 0
    for call in missed:
        if any(ts >= call.created_at for ts in textback_by_conv.get(call.conversation_id, [])):
            textback_sent += 1
        re_engaged = any(ts > call.created_at for ts in reply_by_conv.get(call.conversation_id, []))
        booked = call.contact_id is not None and any(
            ts >= call.created_at for ts in appts_by_contact.get(call.contact_id, [])
        )
        if re_engaged or booked:
            recovered += 1
    return textback_sent, recovered


def _local_date(moment: datetime, tz: ZoneInfo) -> date:
    """Return the workspace-local calendar date ``moment`` falls on."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(tz).date()


def _compute_leads_by_day(
    leads: list[LeadRow],
    start_date: date,
    end_date: date,
    tz: ZoneInfo,
) -> list[DailyLeadCount]:
    """Bucket leads onto workspace-local calendar days, zero-filling gaps.

    Every day in ``[start_date, end_date]`` gets an entry so the series is a
    continuous timeline — a quiet day reads as 0 rather than disappearing and
    silently compressing the chart.
    """
    counts: Counter[date] = Counter()
    for lead in leads:
        day = _local_date(lead.created_at, tz)
        # Guard against clock skew / rows fetched at a window edge landing
        # outside the requested range once converted to local time.
        if start_date <= day <= end_date:
            counts[day] += 1

    series: list[DailyLeadCount] = []
    day = start_date
    while day <= end_date:
        series.append(DailyLeadCount(date=day, count=counts.get(day, 0)))
        day += timedelta(days=1)
    return series


def _compute_after_hours(calls: list[CallRow], tz: ZoneInfo) -> tuple[int, int]:
    """Return ``(after_hours_calls, after_hours_answered)``."""
    after_hours_calls = 0
    after_hours_answered = 0
    for call in calls:
        if _is_after_hours(call.created_at, tz):
            after_hours_calls += 1
            if call.is_answered:
                after_hours_answered += 1
    return after_hours_calls, after_hours_answered


def aggregate_scorecard(
    *,
    start_date: date,
    end_date: date,
    calls: list[CallRow],
    textbacks: list[TextbackRow],
    inbound_replies: list[InboundReplyRow],
    appointments: list[AppointmentRow],
    opportunities: list[OpportunityRow],
    leads: list[LeadRow],
    tz: ZoneInfo,
    currency: str = "USD",
) -> ReceptionistScorecard:
    """Pure aggregation of fetched rows into the scorecard response."""
    calls_total = len(calls)
    calls_answered = sum(1 for c in calls if c.is_answered)
    missed = [c for c in calls if c.is_missed]
    missed_calls = len(missed)

    textback_sent, recovered = _compute_recovery(missed, textbacks, inbound_replies, appointments)
    after_hours_calls, after_hours_answered = _compute_after_hours(calls, tz)

    # --- Handle time ------------------------------------------------------
    handle_durations = [
        c.duration_seconds
        for c in calls
        if c.is_answered and c.duration_seconds is not None and c.duration_seconds > 0
    ]
    avg_handle_time = (
        round(sum(handle_durations) / len(handle_durations), 1) if handle_durations else None
    )

    # --- Top reasons ------------------------------------------------------
    reason_counter: Counter[str] = Counter()
    for call in calls:
        for reason in _extract_reasons(call.signals):
            reason_counter[reason] += 1
    top_reasons = [
        CallReasonStat(reason=reason, count=count)
        for reason, count in reason_counter.most_common(TOP_REASONS_LIMIT)
    ]

    # --- New leads --------------------------------------------------------
    new_leads_by_day = _compute_leads_by_day(leads, start_date, end_date, tz)
    new_leads_total = sum(d.count for d in new_leads_by_day)
    avg_new_leads_per_day = (
        round(new_leads_total / len(new_leads_by_day), 1) if new_leads_by_day else None
    )

    # --- Revenue ----------------------------------------------------------
    revenue_booked = round(sum(o.amount for o in opportunities), 2)
    deposits_booked = round(
        sum(o.amount for o in opportunities if o.status == "won" and o.closed_date is not None),
        2,
    )

    return ReceptionistScorecard(
        start_date=start_date,
        end_date=end_date,
        calls_total=calls_total,
        calls_answered=calls_answered,
        answer_rate=(round(calls_answered / calls_total * 100, 1) if calls_total else None),
        missed_calls=missed_calls,
        missed_calls_textback_sent=textback_sent,
        missed_calls_recovered=recovered,
        recovery_rate=(round(recovered / missed_calls * 100, 1) if missed_calls else None),
        appointments_booked=len(appointments),
        revenue_booked=revenue_booked,
        deposits_booked=deposits_booked,
        currency=currency,
        new_leads_total=new_leads_total,
        new_leads_by_day=new_leads_by_day,
        avg_new_leads_per_day=avg_new_leads_per_day,
        after_hours_calls=after_hours_calls,
        after_hours_answered=after_hours_answered,
        after_hours_coverage_rate=(
            round(after_hours_answered / after_hours_calls * 100, 1) if after_hours_calls else None
        ),
        avg_handle_time_seconds=avg_handle_time,
        top_call_reasons=top_reasons,
    )


def resolve_range(
    start_date: date | None,
    end_date: date | None,
    *,
    today: date | None = None,
) -> tuple[date, date]:
    """Normalise an optional date range, defaulting to the last 30 days."""
    today = today or datetime.now(UTC).date()
    resolved_end = end_date or today
    resolved_start = start_date or (resolved_end - timedelta(days=DEFAULT_RANGE_DAYS - 1))
    if resolved_start > resolved_end:
        resolved_start, resolved_end = resolved_end, resolved_start
    return resolved_start, resolved_end


class ScorecardService:
    """Builds the receptionist scorecard from workspace data."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.log = logger.bind(component="scorecard_service")

    async def get_scorecard(
        self,
        workspace: Workspace,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> ReceptionistScorecard:
        resolved_start, resolved_end = resolve_range(start_date, end_date)
        tz = _resolve_tz(workspace)
        # Inclusive day range → [start 00:00 UTC, end+1 00:00 UTC).
        window_start = datetime.combine(resolved_start, time.min, tzinfo=UTC)
        window_end = datetime.combine(resolved_end + timedelta(days=1), time.min, tzinfo=UTC)
        # The daily lead series is bucketed by local calendar day, so it needs a
        # window anchored to local midnight. Reusing the UTC window would clip a
        # partial day off each end for any non-UTC workspace — an owner in
        # UTC-5 would see the first day's evening leads missing entirely.
        leads_window_start = datetime.combine(resolved_start, time.min, tzinfo=tz)
        leads_window_end = datetime.combine(resolved_end + timedelta(days=1), time.min, tzinfo=tz)

        conv_select = select(Conversation.id).where(Conversation.workspace_id == workspace.id)

        calls = await self._fetch_calls(conv_select, window_start, window_end)
        textbacks = await self._fetch_textbacks(conv_select, window_start, window_end)
        replies = await self._fetch_inbound_replies(conv_select, window_start, window_end)
        appointments = await self._fetch_appointments(workspace.id, window_start, window_end)
        opportunities = await self._fetch_opportunities(workspace.id, window_start, window_end)
        leads = await self._fetch_leads(workspace.id, leads_window_start, leads_window_end)

        return aggregate_scorecard(
            start_date=resolved_start,
            end_date=resolved_end,
            calls=calls,
            textbacks=textbacks,
            inbound_replies=replies,
            appointments=appointments,
            opportunities=opportunities,
            leads=leads,
            tz=tz,
        )

    async def _fetch_calls(
        self,
        conv_select: Select[tuple[uuid.UUID]],
        window_start: datetime,
        window_end: datetime,
    ) -> list[CallRow]:
        result = await self.db.execute(
            select(
                Message.conversation_id,
                Conversation.contact_id,
                Message.created_at,
                Message.status,
                Message.channel,
                Message.duration_seconds,
                CallOutcome.outcome_type,
                CallOutcome.signals,
            )
            .select_from(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .outerjoin(CallOutcome, CallOutcome.message_id == Message.id)
            .where(
                Message.conversation_id.in_(conv_select),
                Message.channel.in_([MessageChannel.VOICE, MessageChannel.VOICEMAIL]),
                Message.created_at >= window_start,
                Message.created_at < window_end,
            )
        )
        return [
            CallRow(
                conversation_id=row.conversation_id,
                contact_id=row.contact_id,
                created_at=row.created_at,
                status=str(row.status),
                channel=str(row.channel),
                duration_seconds=row.duration_seconds,
                outcome_type=str(row.outcome_type) if row.outcome_type is not None else None,
                signals=dict(row.signals) if row.signals else {},
            )
            for row in result.all()
        ]

    async def _fetch_textbacks(
        self,
        conv_select: Select[tuple[uuid.UUID]],
        window_start: datetime,
        window_end: datetime,
    ) -> list[TextbackRow]:
        result = await self.db.execute(
            select(Message.conversation_id, Message.created_at).where(
                Message.conversation_id.in_(conv_select),
                Message.direction == MessageDirection.OUTBOUND,
                Message.channel == MessageChannel.SMS,
                Message.created_at >= window_start,
                Message.created_at < window_end,
            )
        )
        # The text-back worker sends an outbound SMS after a missed inbound
        # call; any outbound SMS following a missed call is treated as a
        # recovery touch (paired to the call by conversation + timestamp).
        return [
            TextbackRow(
                conversation_id=row.conversation_id,
                created_at=row.created_at,
            )
            for row in result.all()
        ]

    async def _fetch_inbound_replies(
        self,
        conv_select: Select[tuple[uuid.UUID]],
        window_start: datetime,
        window_end: datetime,
    ) -> list[InboundReplyRow]:
        result = await self.db.execute(
            select(Message.conversation_id, Message.created_at).where(
                Message.conversation_id.in_(conv_select),
                Message.direction == MessageDirection.INBOUND,
                Message.channel.in_([MessageChannel.SMS, MessageChannel.IMESSAGE]),
                Message.created_at >= window_start,
                Message.created_at < window_end,
            )
        )
        return [
            InboundReplyRow(conversation_id=row.conversation_id, created_at=row.created_at)
            for row in result.all()
        ]

    async def _fetch_appointments(
        self, workspace_id: uuid.UUID, window_start: datetime, window_end: datetime
    ) -> list[AppointmentRow]:
        result = await self.db.execute(
            select(Appointment.contact_id, Appointment.created_at).where(
                Appointment.workspace_id == workspace_id,
                Appointment.created_at >= window_start,
                Appointment.created_at < window_end,
            )
        )
        return [
            AppointmentRow(contact_id=row.contact_id, created_at=row.created_at)
            for row in result.all()
        ]

    async def _fetch_leads(
        self, workspace_id: uuid.UUID, window_start: datetime, window_end: datetime
    ) -> list[LeadRow]:
        """Fetch contacts created in the window — one row per new lead.

        Only ``created_at`` is selected: the daily count never touches the
        Fernet-encrypted PII columns (name/email/phone), so no decryption cost
        and no PII enters the aggregate.
        """
        result = await self.db.execute(
            select(Contact.created_at).where(
                Contact.workspace_id == workspace_id,
                Contact.created_at >= window_start,
                Contact.created_at < window_end,
            )
        )
        return [LeadRow(created_at=row.created_at) for row in result.all()]

    async def _fetch_opportunities(
        self, workspace_id: uuid.UUID, window_start: datetime, window_end: datetime
    ) -> list[OpportunityRow]:
        result = await self.db.execute(
            select(
                Opportunity.amount,
                Opportunity.created_at,
                Opportunity.status,
                Opportunity.closed_date,
            ).where(
                Opportunity.workspace_id == workspace_id,
                Opportunity.created_at >= window_start,
                Opportunity.created_at < window_end,
            )
        )
        return [
            OpportunityRow(
                amount=float(row.amount or 0),
                created_at=row.created_at,
                status=str(row.status),
                closed_date=row.closed_date,
            )
            for row in result.all()
        ]
