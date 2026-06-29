"""Schemas for job time tracking, expenses, and profitability.

Money is expressed as ``float`` in major units (matching invoice/quote schemas);
server-computed fields (line ``duration_hours``, the whole profitability payload)
are response-only and never accepted from clients.
"""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------- #
# Time entries
# --------------------------------------------------------------------------- #
class ClockInRequest(BaseModel):
    """Start the clock on a job (open-ended time entry)."""

    technician_id: uuid.UUID | None = None
    rate: float = Field(default=0.0, ge=0, description="Hourly cost rate")
    note: str | None = None


class TimeEntryCreate(BaseModel):
    """Log a completed time entry with an explicit start and end."""

    technician_id: uuid.UUID | None = None
    started_at: datetime
    ended_at: datetime
    rate: float = Field(default=0.0, ge=0)
    note: str | None = None


class TimeEntryResponse(BaseModel):
    """A time entry as returned by the API."""

    id: uuid.UUID
    job_id: uuid.UUID
    technician_id: uuid.UUID | None = None
    started_at: datetime
    ended_at: datetime | None = None
    rate: float
    note: str | None = None
    # Server-computed: hours between start and end (0 while the clock runs).
    duration_hours: float
    # Server-computed: duration_hours * rate (0 while the clock runs).
    labor_cost: float
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- #
# Expenses
# --------------------------------------------------------------------------- #
class JobExpenseCreate(BaseModel):
    """Record a cost incurred on a job."""

    description: str = Field(min_length=1, max_length=255)
    amount: float = Field(gt=0)
    category: str | None = Field(default=None, max_length=50)
    incurred_on: date | None = None
    note: str | None = None


class JobExpenseResponse(BaseModel):
    """A job expense as returned by the API."""

    id: uuid.UUID
    job_id: uuid.UUID
    description: str
    amount: float
    category: str | None = None
    incurred_on: date | None = None
    note: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- #
# Profitability
# --------------------------------------------------------------------------- #
class JobProfitability(BaseModel):
    """Computed P&L for a single job.

    ``revenue`` comes from the linked invoice's total (0 when unlinked).
    ``labor_cost`` sums completed time entries (hours * rate); ``expense_cost``
    sums expenses. ``margin`` is ``profit / revenue`` (null when revenue is 0).
    """

    job_id: uuid.UUID
    currency: str
    revenue: float
    labor_cost: float
    expense_cost: float
    total_cost: float
    profit: float
    margin: float | None = None
    # Convenience rollups for the UI header.
    total_hours: float
    open_timer: bool
