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
from datetime import UTC, date, datetime, time, timedelta
from statistics import median

from fastapi import HTTPException
from fastapi import status as http_status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.scope import apply_workspace_scope
from app.models.lead_source import LeadSource, LeadSourceType
from app.models.opportunity import Opportunity
from app.models.quote import Quote
from app.models.user import User
from app.schemas.reporting import SalesPerformanceBreakdownRow, SalesPerformanceReport
from app.services.dashboard.lead_source_roi_service import source_type_label
from app.services.reporting.reporting_service import _require_single_currency

# Report name used in the multi-currency refusal message.
REPORT_NAME = "Sales performance"

# Quote lifecycle slices this report cares about (see ``QUOTE_STATUSES``).
_DRAFT_STATUS = "draft"
_APPROVED_STATUS = "approved"
# A customer decision was actually made. ``sent`` is deliberately absent.
_DECIDED_STATUSES = frozenset({"approved", "declined", "expired"})

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
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
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
    return fact.lead_source_type.value, source_type_label(fact.lead_source_type)


def _service_identity(fact: QuoteFact) -> tuple[str | None, str]:
    """Group key/label for the quote's dominant service line."""
    if fact.primary_service is None:
        return None, UNCATEGORIZED_SERVICE_LABEL
    return fact.primary_service, fact.primary_service


def assemble_sales_performance(
    facts: Iterable[QuoteFact], *, date_from: date, date_to: date
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

    return SalesPerformanceReport(
        date_from=date_from,
        date_to=date_to,
        currency=currency,
        quotes_issued=metrics.quotes_issued,
        quotes_approved=metrics.quotes_approved,
        revenue_approved=metrics.revenue_approved,
        avg_job_value=metrics.avg_job_value,
        median_job_value=metrics.median_job_value,
        attach_rate=metrics.attach_rate,
        avg_attach_value=metrics.avg_attach_value,
        close_rate=metrics.close_rate,
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
        start, end = resolve_window(date_from, date_to)
        facts = await self._load_facts(workspace_id, start, end)
        return assemble_sales_performance(facts, date_from=start, date_to=end)

    async def _load_facts(
        self, workspace_id: uuid.UUID, date_from: date, date_to: date
    ) -> list[QuoteFact]:
        """Load the cohort's quotes with their closer and attributed channel."""
        # Half-open [start, end) over the timestamptz column so the whole of the
        # final day counts, whatever time of day the quote was created.
        start = datetime.combine(date_from, time.min, tzinfo=UTC)
        end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=UTC)

        query = (
            apply_workspace_scope(
                select(
                    Quote.status,
                    Quote.total,
                    Quote.attach_count,
                    Quote.attach_value,
                    Quote.currency,
                    Quote.primary_service,
                    Quote.created_by_id,
                    User.full_name,
                    LeadSource.source_type,
                ),
                Quote,
                workspace_id,
            )
            .outerjoin(User, User.id == Quote.created_by_id)
            # Same attribution path the lead-source ROI dashboard ranks on: the
            # opportunity's snapshotted ``lead_source_id`` -> ``LeadSource``
            # (see ``app.services.dashboard.lead_source_roi_service``). Outer
            # joins throughout so an unattributed or unowned quote still counts
            # toward the totals instead of vanishing from the report.
            .outerjoin(
                Opportunity,
                (Opportunity.id == Quote.opportunity_id)
                & (Opportunity.workspace_id == workspace_id),
            )
            .outerjoin(LeadSource, LeadSource.id == Opportunity.lead_source_id)
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
