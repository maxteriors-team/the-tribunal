"""Receptionist scorecard aggregation service.

Computes the owner-facing retention scorecard for a workspace over a date
range. The heavy lifting is split into two layers:

* :class:`ScorecardService` runs workspace-scoped queries for calls, messages,
  appointments, contacts, canonical booked revenue, and paid deposits.
* The module-level ``aggregate_*`` helpers turn those values into response
  numbers. They are pure functions (no DB, no clock) so the metric maths —
  answer rate, missed-call recovery, after-hours coverage, average handle time,
  top reasons, daily new leads — can be unit-tested directly.
"""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment import Appointment
from app.models.attendance import (
    ATTENDANCE_STATUS_COMPLETE,
    AttendanceEntry,
    AttendancePause,
)
from app.models.call_outcome import CallOutcome
from app.models.contact import Contact
from app.models.conversation import (
    Conversation,
    Message,
    MessageChannel,
    MessageDirection,
)
from app.models.field_service import Job, JobAssignment, Technician
from app.models.job_costing import TimeEntry
from app.models.quote import Quote
from app.models.workspace import Workspace
from app.schemas.scorecard import (
    CallReasonStat,
    DailyLeadCount,
    ReceptionistScorecard,
    TechnicianActivityScorecardRow,
)
from app.services.reporting.booked_revenue import get_booked_revenue_totals
from app.services.reporting.time_windows import local_date_bounds_utc
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
class LeadRow:
    """A contact (lead) created within the range."""

    created_at: datetime


@dataclass(slots=True, frozen=True)
class _AttendanceDurationRow:
    """Completed attendance interval used by the scorecard-only aggregator."""

    user_id: int
    started_at: datetime
    ended_at: datetime
    paused_seconds: int


def _aggregate_attendance_seconds(
    rows: list[_AttendanceDurationRow],
) -> tuple[dict[int, int], dict[int, int]]:
    """Return pause-adjusted worked and paused seconds grouped by user."""
    worked_totals: Counter[int] = Counter()
    paused_totals: Counter[int] = Counter()
    for row in rows:
        gross_seconds = max(0, int((row.ended_at - row.started_at).total_seconds()))
        paused_seconds = min(gross_seconds, max(0, row.paused_seconds))
        worked_totals[row.user_id] += gross_seconds - paused_seconds
        paused_totals[row.user_id] += paused_seconds
    return dict(worked_totals), dict(paused_totals)


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
    revenue_booked: float,
    deposits_collected: float,
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

    # Money values are queried from the canonical booking/deposit ledgers.
    revenue_booked = round(revenue_booked, 2)
    deposits_booked = round(deposits_collected, 2)

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
    """Builds supervisor scorecards from workspace-scoped activity data."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.log = logger.bind(component="scorecard_service")

    async def get_scorecard(
        self,
        workspace: Workspace,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> ReceptionistScorecard:
        tz = _resolve_tz(workspace)
        resolved_start, resolved_end = resolve_range(
            start_date,
            end_date,
            today=datetime.now(tz).date(),
        )
        window_start, window_end = local_date_bounds_utc(resolved_start, resolved_end, tz.key)

        conv_select = select(Conversation.id).where(Conversation.workspace_id == workspace.id)

        calls = await self._fetch_calls(conv_select, window_start, window_end)
        textbacks = await self._fetch_textbacks(conv_select, window_start, window_end)
        replies = await self._fetch_inbound_replies(conv_select, window_start, window_end)
        appointments = await self._fetch_appointments(workspace.id, window_start, window_end)
        leads = await self._fetch_leads(workspace.id, window_start, window_end)
        booked = await get_booked_revenue_totals(
            self.db,
            workspace.id,
            resolved_start,
            resolved_end,
            timezone_name=tz.key,
        )
        deposits_collected = await self._fetch_deposits_collected(
            workspace.id, window_start, window_end
        )

        return aggregate_scorecard(
            start_date=resolved_start,
            end_date=resolved_end,
            calls=calls,
            textbacks=textbacks,
            inbound_replies=replies,
            appointments=appointments,
            revenue_booked=float(booked.revenue),
            deposits_collected=deposits_collected,
            leads=leads,
            tz=tz,
        )

    async def get_technician_activity(
        self,
        workspace: Workspace,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[TechnicianActivityScorecardRow]:
        """Return alphabetical, non-ranked activity context for every technician."""
        tz = _resolve_tz(workspace)
        resolved_start, resolved_end = resolve_range(
            start_date,
            end_date,
            today=datetime.now(tz).date(),
        )
        window_start, window_end = local_date_bounds_utc(
            resolved_start,
            resolved_end,
            tz.key,
        )

        technician_result = await self.db.execute(
            select(Technician)
            .where(Technician.workspace_id == workspace.id)
            .order_by(func.lower(Technician.name), Technician.id)
        )
        technicians = list(technician_result.scalars().all())
        if not technicians:
            return []

        technician_ids = [technician.id for technician in technicians]
        assigned_job_ids: dict[uuid.UUID, set[uuid.UUID]] = {
            technician_id: set() for technician_id in technician_ids
        }

        # Direct dispatch tags and crew-routed jobs are both assignments in the
        # field-service schedule. Sets prevent a job using both paths from being
        # counted twice for the same technician.
        direct_assignments = await self.db.execute(
            select(JobAssignment.technician_id, JobAssignment.job_id)
            .join(Job, Job.id == JobAssignment.job_id)
            .where(
                Job.workspace_id == workspace.id,
                JobAssignment.technician_id.in_(technician_ids),
                Job.scheduled_start >= window_start,
                Job.scheduled_start < window_end,
            )
        )
        for technician_id, job_id in direct_assignments.all():
            assigned_job_ids[technician_id].add(job_id)

        crew_assignments = await self.db.execute(
            select(Technician.id, Job.id)
            .select_from(Technician)
            .join(Job, Job.crew_id == Technician.crew_id)
            .where(
                Technician.workspace_id == workspace.id,
                Technician.id.in_(technician_ids),
                Technician.crew_id.is_not(None),
                Job.workspace_id == workspace.id,
                Job.scheduled_start >= window_start,
                Job.scheduled_start < window_end,
            )
        )
        for technician_id, job_id in crew_assignments.all():
            assigned_job_ids[technician_id].add(job_id)

        completed_time_entries: Counter[uuid.UUID] = Counter()
        job_logged_seconds: Counter[uuid.UUID] = Counter()
        time_entries = await self.db.execute(
            select(
                TimeEntry.technician_id,
                TimeEntry.started_at,
                TimeEntry.ended_at,
            ).where(
                TimeEntry.workspace_id == workspace.id,
                TimeEntry.technician_id.in_(technician_ids),
                TimeEntry.started_at >= window_start,
                TimeEntry.started_at < window_end,
                TimeEntry.ended_at.is_not(None),
            )
        )
        for technician_id, entry_started_at, entry_ended_at in time_entries.all():
            if entry_ended_at is None:
                continue
            completed_time_entries[technician_id] += 1
            job_logged_seconds[technician_id] += max(
                0,
                int((entry_ended_at - entry_started_at).total_seconds()),
            )

        user_ids = [
            technician.user_id for technician in technicians if technician.user_id is not None
        ]
        attendance_by_user: dict[int, int] = {}
        paused_by_user: dict[int, int] = {}
        if user_ids:
            pause_totals = (
                select(
                    AttendancePause.entry_id.label("entry_id"),
                    func.sum(
                        func.extract(
                            "epoch",
                            AttendancePause.ended_at - AttendancePause.started_at,
                        )
                    ).label("paused_seconds"),
                )
                .where(AttendancePause.ended_at.is_not(None))
                .group_by(AttendancePause.entry_id)
                .subquery()
            )
            attendance_result = await self.db.execute(
                select(
                    AttendanceEntry.user_id,
                    AttendanceEntry.started_at,
                    AttendanceEntry.ended_at,
                    func.coalesce(pause_totals.c.paused_seconds, 0),
                )
                .outerjoin(pause_totals, pause_totals.c.entry_id == AttendanceEntry.id)
                .where(
                    AttendanceEntry.workspace_id == workspace.id,
                    AttendanceEntry.user_id.in_(user_ids),
                    AttendanceEntry.started_at >= window_start,
                    AttendanceEntry.started_at < window_end,
                    AttendanceEntry.status == ATTENDANCE_STATUS_COMPLETE,
                    AttendanceEntry.ended_at.is_not(None),
                )
            )
            attendance_rows = [
                _AttendanceDurationRow(
                    user_id=user_id,
                    started_at=entry_started_at,
                    ended_at=entry_ended_at,
                    paused_seconds=int(paused_seconds),
                )
                for user_id, entry_started_at, entry_ended_at, paused_seconds in (
                    attendance_result.all()
                )
                if entry_ended_at is not None
            ]
            attendance_by_user, paused_by_user = _aggregate_attendance_seconds(attendance_rows)

        return [
            TechnicianActivityScorecardRow(
                id=technician.id,
                name=technician.name,
                active=technician.is_active,
                assigned_jobs=len(assigned_job_ids[technician.id]),
                completed_job_time_entries=completed_time_entries[technician.id],
                job_logged_seconds=job_logged_seconds[technician.id],
                attendance_worked_seconds=(
                    attendance_by_user.get(technician.user_id, 0)
                    if technician.user_id is not None
                    else 0
                ),
                attendance_paused_seconds=(
                    paused_by_user.get(technician.user_id, 0)
                    if technician.user_id is not None
                    else 0
                ),
            )
            for technician in technicians
        ]

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

    async def _fetch_deposits_collected(
        self, workspace_id: uuid.UUID, window_start: datetime, window_end: datetime
    ) -> float:
        """Sum deposits actually marked paid inside the local reporting window."""
        deposit_value = func.coalesce(
            Quote.deposit_amount_fixed,
            Quote.total * Quote.deposit_percentage / 100,
            0,
        )
        value = (
            await self.db.execute(
                select(func.coalesce(func.sum(deposit_value), 0)).where(
                    Quote.workspace_id == workspace_id,
                    Quote.deposit_paid_at >= window_start,
                    Quote.deposit_paid_at < window_end,
                )
            )
        ).scalar_one()
        return float(value or 0)
