"""Schemas for operational reporting (AR aging + job profitability).

These are read-only roll-ups computed on the fly from invoices and job costing;
no new tables back them. Money is in major units (matching invoices/quotes).
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
