"""Schemas for operational reporting (AR aging, job profitability, sales).

These are read-only roll-ups computed on the fly from invoices, job costing and
quotes; no new tables back them. Money is in major units (matching
invoices/quotes) and rates are ratios in 0..1, not percentages.
"""

from datetime import date

from pydantic import BaseModel, Field


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
    labor (hours x rate) plus logged expenses.
    """

    date_from: date | None
    date_to: date | None
    currency: str
    job_count: int = Field(..., description="Jobs considered in the period")
    billable_job_count: int = Field(..., description="Jobs with a linked invoice")
    revenue: float
    labor_cost: float
    expense_cost: float
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


class SalesPerformanceReport(BaseModel):
    """Sales performance over a quote cohort.

    Quotes are cohorted by creation date inside the inclusive window, so a quote
    and the decision it later earned are reported together. Drafts never count
    (they never reached a customer) and still-``sent`` quotes are undecided, so
    they are excluded from the close-rate denominator rather than counted as
    losses. Every rate is null instead of zero when its denominator is empty.
    """

    date_from: date = Field(..., description="Inclusive start of the cohort window")
    date_to: date = Field(..., description="Inclusive end of the cohort window")
    currency: str = Field(..., description="Currency of every money field in this report")
    quotes_issued: int = Field(..., description="Cohort quotes that left draft")
    quotes_approved: int = Field(..., description="Cohort quotes the customer approved")
    revenue_approved: float = Field(..., description="Summed total of the approved quotes")
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
    by_closer: list[SalesPerformanceBreakdownRow] = Field(
        ..., description="Performance grouped by the user who created the quote"
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
