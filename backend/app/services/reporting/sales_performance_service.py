"""Workspace-scoped sales performance reporting.

The CRM already reports how the receptionist answered (``app.schemas.scorecard``)
and how jobs performed once sold (:class:`~app.services.reporting.ReportingService`),
but nothing reported how the *selling* went. This module closes that gap from
:class:`~app.models.quote.Quote`, whose denormalized ``primary_service`` /
``attach_count`` / ``attach_value`` triple makes attach reporting a single scan.

Definitions that matter when reading the numbers:

- **Cohort** — quotes *created* inside ``[date_from, date_to]`` (inclusive, UTC
  days). Cohorting on creation is what makes ``close_rate`` honest: a quote and
  the decision it eventually earned stay in the same bucket, so the rate answers
  "of what we quoted in June, how much closed?" rather than mixing June's
  approvals with May's quotes.
- **Issued** — every cohort quote that left ``draft``. A draft has never reached
  a customer, so it is not a sales attempt and is excluded from every metric.
- **Decided** — ``approved`` / ``declined`` / ``expired``. A still-``sent`` quote
  is undecided, not a loss, so it is excluded from the close-rate denominator;
  counting it would drag the rate down purely for quoting recently.

Money math uses ``float`` rounded to two decimals and rates are ratios in 0..1
rounded to four, matching :mod:`app.services.reporting.reporting_service`
(``margin``). Mixed-currency workspaces are refused rather than silently summed,
via the same ``_require_single_currency`` guard the other reports use.

The aggregation itself is a pure function (:func:`assemble_sales_performance`)
over :class:`QuoteFact` rows, mirroring
:func:`app.services.dashboard.lead_source_roi_service.assemble_roi_stats`, so
every rate, median and grouping rule is unit-testable without a database.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from statistics import median
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.scope import apply_workspace_scope
from app.models.appointment import Appointment, AppointmentStatus
from app.models.contact import Contact
from app.models.field_service import Job, JobStatus
from app.models.lead_source import LeadSource, LeadSourceType
from app.models.opportunity import Opportunity
from app.models.quote import Quote
from app.models.user import User
from app.schemas.reporting import SalesPerformanceBreakdownRow, SalesPerformanceReport
from app.services.quotes.quote_expiry import effective_status
from app.services.reporting.booked_revenue import get_booked_revenue_totals
from app.services.reporting.reporting_service import _require_single_currency
from app.services.reporting.time_windows import (
    get_workspace_reporting_timezone,
    local_date_bounds_utc,
)

# Report name used in the multi-currency refusal message.
REPORT_NAME = "Sales performance"

# Quote lifecycle slices this report cares about (see ``QUOTE_STATUSES``).
_DRAFT_STATUS = "draft"
_APPROVED_STATUS = "approved"
_SOURCE_LABELS = {
    LeadSourceType.FACEBOOK_ADS: "Facebook Ads",
    LeadSourceType.GOOGLE_ADS: "Google Ads",
    LeadSourceType.PHONE_RADIO: "Phone / Radio",
    LeadSourceType.REFERRAL_PARTNER: "Referral Partner",
    LeadSourceType.REPEAT_CUSTOMER: "Repeat Customer",
    LeadSourceType.TRUCK_WRAP: "Truck Wrap",
    LeadSourceType.YARD_SIGN: "Yard Sign",
    LeadSourceType.CANVASS_NEIGHBOR: "Jobsite Canvass",
}
# A customer decision was actually made. ``sent`` is deliberately absent.
_DECIDED_STATUSES = frozenset({"approved", "declined", "expired"})

# Deal status that counts a contact in the cohort as converted.
_WON_STATUS = "won"

# Bucket labels for rows with no group value, so a breakdown never hides volume.
UNASSIGNED_CLOSER_LABEL = "Unassigned"
UNATTRIBUTED_SOURCE_LABEL = "Unattributed"
UNCATEGORIZED_SERVICE_LABEL = "Uncategorized"


@dataclass(frozen=True)
class QuoteFact:
    """One quote flattened to the fields sales reporting aggregates over.

    Deliberately plain data (no ORM, no session) so the maths can be exercised
    with fabricated rows.
    """

    status: str
    total: float
    attach_count: int
    attach_value: float
    currency: str | None = None
    primary_service: str | None = None
    closer_id: int | None = None
    closer_name: str | None = None
    lead_source_type: LeadSourceType | None = None


@dataclass(frozen=True)
class ConversionFacts:
    """The contact cohort behind ``conversion_rate``.

    Cohorted on **contact creation** inside the window, counting a won deal
    whenever it lands — the same shape as the quote cohort, where a quote and
    the decision it later earned stay in one bucket. The consequence is that a
    recent window understates conversion (deals still in flight cannot have
    closed yet), which is why the rate always ships with its denominator.
    """

    contacts_created: int = 0
    contacts_converted: int = 0


@dataclass(frozen=True)
class AttendanceFacts:
    """Appointment volume and decided outcomes in the window.

    Only ``completed`` and ``no_show`` are decisions. A ``scheduled``
    appointment is unknown attendance and a ``cancelled`` one is a call-off, so
    neither belongs in the fraction — folding them in would report a workspace
    that simply has not marked anything as one that gets stood up.
    """

    booked: int = 0
    completed: int = 0
    no_show: int = 0


def show_up_rate(facts: AttendanceFacts) -> float | None:
    """Attended share of decided appointments, or ``None`` when none decided."""
    decided = facts.completed + facts.no_show
    if decided <= 0:
        return None
    return round(facts.completed / decided, 4)


def conversion_rate(facts: ConversionFacts) -> float | None:
    """Won-deal share of the contact cohort, or ``None`` with no contacts.

    ``None`` rather than ``0``: a window in which nobody was created has an
    unreadable conversion rate, not a failed one.
    """
    if facts.contacts_created <= 0:
        return None
    return round(facts.contacts_converted / facts.contacts_created, 4)


@dataclass(frozen=True)
class _Metrics:
    """Computed metrics for one set of issued quotes (whole report or group)."""

    quotes_issued: int
    quotes_approved: int
    revenue_approved: float
    avg_job_value: float | None
    median_job_value: float | None
    attach_rate: float | None
    avg_attach_value: float | None
    close_rate: float | None


def current_month_window(today: date | None = None) -> tuple[date, date]:
    """Return the first and last day of ``today``'s calendar month."""
    reference = today or datetime.now(UTC).date()
    first = reference.replace(day=1)
    # Jump into the next month from a safe day, then step back one day.
    last = (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    return first, last


def resolve_window(
    date_from: date | None,
    date_to: date | None,
    *,
    today: date | None = None,
) -> tuple[date, date]:
    """Fill missing window edges from the current calendar month.

    Raises:
        HTTPException: 422 when the window is inverted, rather than silently
            reporting on an empty range that reads like "no sales".
    """
    month_start, month_end = current_month_window(today)
    start = date_from or month_start
    end = date_to or month_end
    if end < start:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"date_to ({end.isoformat()}) is before date_from ({start.isoformat()}).",
        )
    return start, end


def _compute(facts: Sequence[QuoteFact]) -> _Metrics:
    """Roll a set of *issued* quotes up into the report's metrics.

    Every ratio is ``None`` rather than ``0`` when its denominator is empty, so
    "nobody quoted anything" is never rendered as "0% close rate".
    """
    approved = [fact for fact in facts if fact.status == _APPROVED_STATUS]
    decided = sum(1 for fact in facts if fact.status in _DECIDED_STATUSES)
    totals = [fact.total for fact in approved]
    # Attach value is only meaningful where something actually attached; folding
    # in the single-service quotes would report an average nobody ever sells.
    attach_values = [fact.attach_value for fact in approved if fact.attach_value > 0]
    with_attach = sum(1 for fact in approved if fact.attach_count > 0)

    return _Metrics(
        quotes_issued=len(facts),
        quotes_approved=len(approved),
        revenue_approved=round(sum(totals), 2),
        avg_job_value=round(sum(totals) / len(totals), 2) if totals else None,
        median_job_value=round(median(totals), 2) if totals else None,
        attach_rate=round(with_attach / len(approved), 4) if approved else None,
        avg_attach_value=(
            round(sum(attach_values) / len(attach_values), 2) if attach_values else None
        ),
        close_rate=round(len(approved) / decided, 4) if decided else None,
    )


def _row(key: str | None, label: str, facts: Sequence[QuoteFact]) -> SalesPerformanceBreakdownRow:
    metrics = _compute(facts)
    return SalesPerformanceBreakdownRow(
        key=key,
        label=label,
        quotes_issued=metrics.quotes_issued,
        quotes_approved=metrics.quotes_approved,
        revenue_approved=metrics.revenue_approved,
        avg_job_value=metrics.avg_job_value,
        attach_rate=metrics.attach_rate,
        close_rate=metrics.close_rate,
    )


def _breakdown(
    facts: Sequence[QuoteFact],
    identity: Callable[[QuoteFact], tuple[str | None, str]],
) -> list[SalesPerformanceBreakdownRow]:
    """Group ``facts`` by ``identity`` and rank the resulting rows.

    Ordered by approved revenue, then issued volume, then label — deterministic
    even when several groups tie at zero.
    """
    groups: dict[str | None, tuple[str, list[QuoteFact]]] = {}
    for fact in facts:
        key, label = identity(fact)
        groups.setdefault(key, (label, []))[1].append(fact)

    rows = [_row(key, label, group) for key, (label, group) in groups.items()]
    rows.sort(key=lambda row: (-row.revenue_approved, -row.quotes_issued, row.label))
    return rows


def _closer_identity(fact: QuoteFact) -> tuple[str | None, str]:
    """Group key/label for the user who created the quote."""
    if fact.closer_id is None:
        return None, UNASSIGNED_CLOSER_LABEL
    # Fall back to the id, never the email — user emails are encrypted PII.
    return str(fact.closer_id), fact.closer_name or f"User #{fact.closer_id}"


def _lead_source_identity(fact: QuoteFact) -> tuple[str | None, str]:
    """Group key/label for the acquisition channel behind the quote."""
    if fact.lead_source_type is None:
        return None, UNATTRIBUTED_SOURCE_LABEL
    return fact.lead_source_type.value, _SOURCE_LABELS.get(
        fact.lead_source_type,
        fact.lead_source_type.value.replace("_", " ").title(),
    )


def _service_identity(fact: QuoteFact) -> tuple[str | None, str]:
    """Group key/label for the quote's dominant service line."""
    if fact.primary_service is None:
        return None, UNCATEGORIZED_SERVICE_LABEL
    return fact.primary_service, fact.primary_service


def assemble_sales_performance(
    facts: Iterable[QuoteFact],
    *,
    date_from: date,
    date_to: date,
    conversion: ConversionFacts | None = None,
    attendance: AttendanceFacts | None = None,
    booked_jobs: int | None = None,
    booked_revenue: float | None = None,
    jobs_completed: int = 0,
) -> SalesPerformanceReport:
    """Build the report from cohort quotes.

    Pure (no I/O): drafts are filtered here rather than in SQL so the "a draft is
    not a sales attempt" rule lives in one testable place.
    """
    issued = [fact for fact in facts if fact.status != _DRAFT_STATUS]
    currency = _require_single_currency(
        {fact.currency for fact in issued if fact.currency}, REPORT_NAME
    )
    metrics = _compute(issued)
    contact_cohort = conversion or ConversionFacts()
    appointments = attendance or AttendanceFacts()
    resolved_booked_jobs = metrics.quotes_approved if booked_jobs is None else booked_jobs
    resolved_booked_revenue = metrics.revenue_approved if booked_revenue is None else booked_revenue

    return SalesPerformanceReport(
        date_from=date_from,
        date_to=date_to,
        currency=currency,
        booked_jobs=resolved_booked_jobs,
        booked_revenue=round(resolved_booked_revenue, 2),
        avg_booked_value=(
            round(resolved_booked_revenue / resolved_booked_jobs, 2)
            if resolved_booked_jobs
            else None
        ),
        quotes_issued=metrics.quotes_issued,
        quotes_approved=metrics.quotes_approved,
        revenue_approved=metrics.revenue_approved,
        avg_job_value=metrics.avg_job_value,
        median_job_value=metrics.median_job_value,
        attach_rate=metrics.attach_rate,
        avg_attach_value=metrics.avg_attach_value,
        close_rate=metrics.close_rate,
        contacts_created=contact_cohort.contacts_created,
        contacts_converted=contact_cohort.contacts_converted,
        conversion_rate=conversion_rate(contact_cohort),
        appointments_booked=appointments.booked,
        appointments_completed=appointments.completed,
        appointments_no_show=appointments.no_show,
        jobs_completed=jobs_completed,
        show_up_rate=show_up_rate(appointments),
        by_closer=_breakdown(issued, _closer_identity),
        by_lead_source=_breakdown(issued, _lead_source_identity),
        by_primary_service=_breakdown(issued, _service_identity),
    )


class SalesPerformanceService:
    """Average job value, attach rate and close rate for a workspace."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def sales_performance(
        self,
        workspace_id: uuid.UUID,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> SalesPerformanceReport:
        """Report sales performance over ``[date_from, date_to]``.

        Both edges are inclusive dates and default to the current calendar month.
        """
        timezone_name = await get_workspace_reporting_timezone(self.db, workspace_id)
        local_today = datetime.now(ZoneInfo(timezone_name)).date()
        start, end = resolve_window(date_from, date_to, today=local_today)
        facts = await self._load_facts(workspace_id, start, end, timezone_name=timezone_name)
        conversion = await self._load_conversion(
            workspace_id, start, end, timezone_name=timezone_name
        )
        attendance = await self._load_attendance(
            workspace_id, start, end, timezone_name=timezone_name
        )
        jobs_completed = await self._load_jobs_completed(
            workspace_id, start, end, timezone_name=timezone_name
        )
        booked = await get_booked_revenue_totals(
            self.db,
            workspace_id,
            start,
            end,
            timezone_name=timezone_name,
        )
        return assemble_sales_performance(
            facts,
            date_from=start,
            date_to=end,
            conversion=conversion,
            attendance=attendance,
            booked_jobs=booked.count,
            booked_revenue=float(booked.revenue),
            jobs_completed=jobs_completed,
        )

    async def _load_attendance(
        self,
        workspace_id: uuid.UUID,
        date_from: date,
        date_to: date,
        *,
        timezone_name: str,
    ) -> AttendanceFacts:
        """Count attended vs missed appointments *scheduled* inside the window.

        Cohorted on ``scheduled_at`` rather than on when someone got around to
        marking it, so the rate answers "of the visits booked for July, how many
        happened?".
        """
        start, end = local_date_bounds_utc(date_from, date_to, timezone_name)

        row = (
            await self.db.execute(
                select(
                    func.count(Appointment.id),
                    func.count(Appointment.id).filter(
                        Appointment.status == AppointmentStatus.COMPLETED
                    ),
                    func.count(Appointment.id).filter(
                        Appointment.status == AppointmentStatus.NO_SHOW
                    ),
                ).where(
                    Appointment.workspace_id == workspace_id,
                    Appointment.scheduled_at >= start,
                    Appointment.scheduled_at < end,
                )
            )
        ).one()

        return AttendanceFacts(
            booked=int(row[0] or 0),
            completed=int(row[1] or 0),
            no_show=int(row[2] or 0),
        )

    async def _load_jobs_completed(
        self,
        workspace_id: uuid.UUID,
        date_from: date,
        date_to: date,
        *,
        timezone_name: str,
    ) -> int:
        """Count completed jobs scheduled inside the selected local-date window."""
        start, end = local_date_bounds_utc(date_from, date_to, timezone_name)
        result = await self.db.execute(
            select(func.count(Job.id)).where(
                Job.workspace_id == workspace_id,
                Job.status == JobStatus.COMPLETED,
                Job.scheduled_start >= start,
                Job.scheduled_start < end,
            )
        )
        return int(result.scalar_one() or 0)

    async def _load_conversion(
        self,
        workspace_id: uuid.UUID,
        date_from: date,
        date_to: date,
        *,
        timezone_name: str,
    ) -> ConversionFacts:
        """Count new contacts and how many later booked work.

        An approved quote is canonical; a legacy/manual won opportunity still
        counts when no approved quote exists.
        """
        start, end = local_date_bounds_utc(date_from, date_to, timezone_name)

        won_deal = (
            select(Opportunity.id)
            .where(
                Opportunity.workspace_id == workspace_id,
                Opportunity.primary_contact_id == Contact.id,
                Opportunity.status == _WON_STATUS,
            )
            .exists()
        )
        approved_quote = (
            select(Quote.id)
            .where(
                Quote.workspace_id == workspace_id,
                Quote.contact_id == Contact.id,
                Quote.status == _APPROVED_STATUS,
            )
            .exists()
        )

        row = (
            await self.db.execute(
                select(
                    func.count(Contact.id),
                    func.count(Contact.id).filter(won_deal | approved_quote),
                ).where(
                    Contact.workspace_id == workspace_id,
                    Contact.created_at >= start,
                    Contact.created_at < end,
                )
            )
        ).one()

        return ConversionFacts(
            contacts_created=int(row[0] or 0),
            contacts_converted=int(row[1] or 0),
        )

    async def _load_facts(
        self,
        workspace_id: uuid.UUID,
        date_from: date,
        date_to: date,
        *,
        timezone_name: str,
    ) -> list[QuoteFact]:
        """Load the workspace-local quote cohort and attributed channel."""
        start, end = local_date_bounds_utc(date_from, date_to, timezone_name)
        opportunity_source = aliased(LeadSource)
        contact_source = aliased(LeadSource)

        query = (
            apply_workspace_scope(
                select(
                    # A quote past its expiry date is a *decision*, not an
                    # undecided quote — but nothing sweeps it to ``expired``
                    # until a quote screen is opened, so the report derives it.
                    effective_status().label("status"),
                    Quote.total,
                    Quote.attach_count,
                    Quote.attach_value,
                    Quote.currency,
                    Quote.primary_service,
                    Quote.created_by_id,
                    User.full_name,
                    func.coalesce(opportunity_source.source_type, contact_source.source_type).label(
                        "lead_source_type"
                    ),
                ),
                Quote,
                workspace_id,
            )
            .outerjoin(User, User.id == Quote.created_by_id)
            .outerjoin(
                Opportunity,
                (Opportunity.id == Quote.opportunity_id)
                & (Opportunity.workspace_id == workspace_id),
            )
            .outerjoin(
                Contact,
                (Contact.id == Quote.contact_id) & (Contact.workspace_id == workspace_id),
            )
            .outerjoin(
                opportunity_source,
                opportunity_source.id == Opportunity.lead_source_id,
            )
            .outerjoin(
                contact_source,
                contact_source.id == Contact.first_touch_lead_source_id,
            )
            .where(Quote.created_at >= start, Quote.created_at < end)
        )

        rows = (await self.db.execute(query)).all()
        return [
            QuoteFact(
                status=quote_status,
                total=float(total or 0),
                attach_count=int(attach_count or 0),
                attach_value=float(attach_value or 0),
                currency=currency,
                primary_service=primary_service,
                closer_id=closer_id,
                closer_name=closer_name,
                lead_source_type=source_type,
            )
            for (
                quote_status,
                total,
                attach_count,
                attach_value,
                currency,
                primary_service,
                closer_id,
                closer_name,
                source_type,
            ) in rows
        ]
