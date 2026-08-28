"""Schemas for operational reporting (AR aging, job profitability, sales, capacity).

These are read-only roll-ups computed on the fly from invoices, job costing,
quotes, jobs and appointments; no new tables back them. Money is in major units
(matching invoices/quotes) and rates are ratios in 0..1, not percentages — the
one exception is the capacity report's ``utilization_pct``, a 0..100 percent
matching the owner-entered rate fields on
:class:`app.models.revenue_target.RevenueTarget`.

Any number whose denominator is missing is ``None``, never ``0``: an owner who
never entered a crew capacity must be told the gauge is unreadable, not shown a
full tank.
"""

from datetime import date

from pydantic import BaseModel, Field

# Cost of goods sold is computed from the inventory ledger, so its schemas are
# defined in :mod:`app.schemas.inventory` and re-exported here: ``/reports/cogs``
# sits next to ar-aging and job-pnl, but there must be exactly one COGSReport
# model in the OpenAPI contract.
from app.schemas.inventory import COGSBreakdownRow, COGSGroupBy, COGSReport

# Declared explicitly because the COGS names above are re-exports rather than
# local definitions: without ``__all__`` they read as dead imports to both a
# reader and to static analysis (CodeQL flags them), and the redundant-alias
# idiom that normally signals a re-export is only honoured in ``__init__.py``.
__all__ = [
    "ARAgingBucket",
    "ARAgingReport",
    "AttributionGapReport",
    "BacklogReport",
    "COGSBreakdownRow",
    "COGSGroupBy",
    "COGSReport",
    "EstimateCapacityReport",
    "JobPnLSummary",
    "SalesPerformanceBreakdownRow",
    "SalesPerformanceReport",
]


class ARAgingBucket(BaseModel):
    """One aging bucket of outstanding receivables."""

    label: str = Field(..., description="Bucket label, e.g. 'Current' or '31-60'")
    amount: float = Field(..., description="Outstanding balance in this bucket")
    count: int = Field(..., description="Number of invoices in this bucket")


class ARAgingReport(BaseModel):
    """Accounts-receivable aging as of a given date."""

    as_of: date
    currency: str
    total_outstanding: float
    total_invoices: int
    buckets: list[ARAgingBucket]


class JobPnLSummary(BaseModel):
    """Aggregate job profitability over a period.

    Revenue is the sum of the distinct invoices linked to the jobs in range
    (so two jobs sharing one invoice are not double-counted); cost is tracked
    labor (hours x rate) plus logged expenses plus materials consumed.
    """

    date_from: date | None
    date_to: date | None
    currency: str
    job_count: int = Field(..., description="Jobs considered in the period")
    billable_job_count: int = Field(..., description="Jobs with a linked invoice")
    revenue: float
    labor_cost: float
    expense_cost: float
    # Stock consumed on the period's jobs, from the inventory ledger. Distinct
    # from an expense categorized "materials" — consuming stock never writes a
    # JobExpense, so the two cannot double-count.
    material_cost: float = 0.0
    total_cost: float
    profit: float
    margin: float | None = Field(None, description="profit / revenue, or null when revenue is 0")
    total_hours: float


class SalesPerformanceBreakdownRow(BaseModel):
    """One grouped slice of sales performance.

    The same shape is reused for every breakdown dimension (closer, lead source,
    primary service) so a client can render them all with one component.
    """

    key: str | None = Field(
        None,
        description=(
            "Stable group identifier (user id, lead-source type, or service "
            "category); null for the unassigned/unattributed/uncategorized bucket"
        ),
    )
    label: str = Field(..., description="Human-readable group name")
    quotes_issued: int = Field(..., description="Quotes in this group that left draft")
    quotes_approved: int = Field(..., description="Quotes in this group the customer approved")
    revenue_approved: float = Field(..., description="Summed total of this group's approved quotes")
    avg_job_value: float | None = Field(
        None, description="Mean approved quote total, or null with no approvals"
    )
    attach_rate: float | None = Field(
        None,
        description=(
            "Share (0..1) of approved quotes carrying at least one attached "
            "service, or null with no approvals"
        ),
    )
    close_rate: float | None = Field(
        None,
        description=(
            "approved / (approved + declined + expired) as a 0..1 ratio, or null "
            "when nothing in this group was decided"
        ),
    )


class SalesPerformanceCloserRow(SalesPerformanceBreakdownRow):
    """One rep's totals, plus the same metrics split across their service lines.

    The drill-down is nested rather than returned as a second flat list keyed by
    ``(closer, service)``: the pairing is what makes it readable ("Dana closes
    gutters at 60% but lighting at 12%"), and a flat list forces every client to
    re-group it. Sub-rows are ranked by approved revenue like every other
    breakdown, and their ``quotes_issued`` sums to the parent's, so a rep's
    services always account for all of their quoted volume.
    """

    by_service: list[SalesPerformanceBreakdownRow] = Field(
        default_factory=list,
        description=(
            "This rep's performance split by the dominant service line of each "
            "quote; the uncategorized bucket carries a null key"
        ),
    )


class SalesPerformanceReport(BaseModel):
    """Sales performance over a quote cohort.

    Quotes are cohorted by creation date inside the inclusive window, so a quote
    and the decision it later earned are reported together. Drafts never count
    (they never reached a customer) and still-``sent`` quotes are undecided, so
    they are excluded from the close-rate denominator rather than counted as
    losses. Every rate is null instead of zero when its denominator is empty.
    """

    date_from: date = Field(..., description="Inclusive start of the cohort/window")
    date_to: date = Field(..., description="Inclusive end of the cohort/window")
    currency: str = Field(..., description="Currency of every money field in this report")
    booked_jobs: int = Field(
        ..., description="Approved quotes booked in the window plus legacy unquoted wins"
    )
    booked_revenue: float = Field(..., description="Canonical revenue booked in the window")
    avg_booked_value: float | None = Field(
        None, description="Mean canonical booking value, or null with no bookings"
    )
    quotes_issued: int = Field(..., description="Cohort quotes that left draft")
    quotes_approved: int = Field(..., description="Cohort quotes the customer approved")
    revenue_approved: float = Field(
        ..., description="Approved value eventually earned by the quote cohort"
    )
    avg_job_value: float | None = Field(
        None, description="Mean approved quote total, or null with no approvals"
    )
    median_job_value: float | None = Field(
        None,
        description=(
            "Median approved quote total (outlier-resistant companion to "
            "avg_job_value), or null with no approvals"
        ),
    )
    attach_rate: float | None = Field(
        None,
        description=(
            "Share (0..1) of approved quotes with at least one attached service "
            "beyond the primary one, or null with no approvals"
        ),
    )
    avg_attach_value: float | None = Field(
        None,
        description=(
            "Mean attached-service revenue across approved quotes that actually "
            "attached something, or null when none did"
        ),
    )
    close_rate: float | None = Field(
        None,
        description=(
            "approved / (approved + declined + expired) as a 0..1 ratio; null "
            "when no cohort quote has been decided yet"
        ),
    )
    contacts_created: int = Field(
        0,
        ge=0,
        description="Contacts created in the window — the denominator of conversion_rate",
    )
    contacts_converted: int = Field(
        0,
        ge=0,
        description="Those contacts that have since reached a won deal",
    )
    conversion_rate: float | None = Field(
        None,
        description=(
            "contacts_converted / contacts_created as a 0..1 ratio, or null when "
            "no contact was created in the window. Cohorted on contact creation "
            "and counting a win whenever it lands, so a recent window "
            "understates conversion: deals still in flight cannot have closed yet."
        ),
    )
    appointments_booked: int = Field(
        0,
        ge=0,
        description="Appointments scheduled inside the selected window",
    )
    appointments_completed: int = Field(
        0,
        ge=0,
        description="Window appointments the customer attended",
    )
    appointments_no_show: int = Field(
        0,
        ge=0,
        description="Window appointments the customer missed",
    )
    jobs_completed: int = Field(
        0,
        ge=0,
        description="Completed jobs scheduled inside the selected window",
    )
    show_up_rate: float | None = Field(
        None,
        description=(
            "completed / (completed + no_show) as a 0..1 ratio, or null when no "
            "appointment in the window has been marked either way. Scheduled and "
            "cancelled appointments are in neither side of the fraction: an "
            "unmarked appointment is unknown attendance, not an absence."
        ),
    )
    by_closer: list[SalesPerformanceCloserRow] = Field(
        ...,
        description=(
            "Performance grouped by the user who created the quote, each row "
            "carrying its own per-service drill-down"
        ),
    )
    by_lead_source: list[SalesPerformanceBreakdownRow] = Field(
        ...,
        description=(
            "Performance grouped by the acquisition channel attributed to the quote's opportunity"
        ),
    )
    by_primary_service: list[SalesPerformanceBreakdownRow] = Field(
        ..., description="Performance grouped by the quote's dominant service line"
    )


class BacklogReport(BaseModel):
    """Sold-but-undelivered work, expressed in weeks of crew capacity.

    The forward-looking counterpart to :class:`JobPnLSummary`: how much work is
    on the books, not what past work earned. ``backlog_weeks`` is the headline —
    the number that decides whether the next dollar goes to marketing.

    Hours are estimated (``Job`` has no duration column): a job's booked window
    when it has one, otherwise ``default_job_hours``. Read
    ``assumed_duration_job_count`` alongside ``job_count`` to see how much of the
    total is measured versus assumed.
    """

    as_of: date = Field(..., description="Date this snapshot of open work was taken")
    backlog_hours: float = Field(
        ..., description="Estimated hours of sold work not yet completed or cancelled"
    )
    weekly_capacity_hours: float | None = Field(
        None,
        description=(
            "Sellable crew hours per week used as the divisor; null when the "
            "workspace has never set one"
        ),
    )
    backlog_weeks: float | None = Field(
        None,
        description=(
            "backlog_hours / weekly_capacity_hours — weeks of work booked; null "
            "when capacity is unset, never 0"
        ),
    )
    job_count: int = Field(..., ge=0, description="Open jobs counted into the backlog")
    unscheduled_job_count: int = Field(
        ...,
        ge=0,
        description=(
            "Open jobs with no time window yet — work sold but not on the "
            "calendar, a separate operational risk from the backlog's size"
        ),
    )
    assumed_duration_job_count: int = Field(
        ...,
        ge=0,
        description="Jobs sized by default_job_hours because they have no usable window",
    )
    default_job_hours: float = Field(
        ..., description="Hours assumed for a job with no usable scheduled window"
    )
    alert_weeks: float | None = Field(
        None,
        description=(
            "Booked-out weeks the owner asked to be warned below "
            "(RevenueTarget.backlog_alert_weeks); null when unset"
        ),
    )
    below_alert_threshold: bool | None = Field(
        None,
        description=(
            "True when backlog_weeks has fallen under alert_weeks — the dry-spell "
            "warning that should trigger marketing spend. Null when either is unknown."
        ),
    )


class EstimateCapacityReport(BaseModel):
    """A month's booked estimates against the estimates it can actually run.

    The hire trigger. One full-time closer tops out near 60-80 estimates a
    month, so utilization sustained above ``at_capacity_threshold_pct`` means
    more leads would only push the calendar further out: the next dollar belongs
    in headcount, not ad spend.

    ``utilization_pct`` is a percent (0..100, matching the target's rate fields),
    not a 0..1 ratio, and is null rather than 0 when no capacity is stored.
    """

    period_month: date = Field(..., description="First day of the reported month")
    booked: int = Field(
        ..., ge=0, description="Appointments occupying the month's estimate calendar"
    )
    capacity: int | None = Field(
        None,
        description=(
            "Estimates the workspace says it can run this month "
            "(RevenueTarget.estimate_capacity_per_month); null when unset"
        ),
    )
    utilization_pct: float | None = Field(
        None, description="booked / capacity as a percent; null when capacity is unset"
    )
    at_capacity: bool | None = Field(
        None,
        description=(
            "True when utilization_pct has reached at_capacity_threshold_pct; "
            "null when capacity is unset, because 'not full' cannot be claimed "
            "off a ceiling nobody set"
        ),
    )
    at_capacity_threshold_pct: float = Field(
        ..., description="Utilization percent treated as full (below 100 on purpose)"
    )


class AttributionGapReport(BaseModel):
    """Structured first-touch coverage for contacts created in a date range."""

    date_from: date = Field(..., description="Inclusive contact-created start date")
    date_to: date = Field(..., description="Inclusive contact-created end date")
    total_contacts: int = Field(..., ge=0)
    unattributed_contacts: int = Field(..., ge=0)
    attributed_contacts: int = Field(..., ge=0)
    gap_rate: float | None = Field(
        None,
        description="Unattributed share in 0..1, or null when no contacts were created",
    )
