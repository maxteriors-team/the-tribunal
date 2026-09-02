"""Schemas for job time tracking, expenses, and profitability.

Money is expressed as ``float`` in major units (matching invoice/quote schemas);
server-computed fields (line ``duration_hours``, the whole profitability payload)
are response-only and never accepted from clients.
"""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------- #
# Time entries
# --------------------------------------------------------------------------- #
class ClockInRequest(BaseModel):
    """Start the clock on a job (open-ended time entry).

    ``rate`` is ignored (forced to 0) for callers without ``billing:read``, so a
    field technician's clock-in is a plain start/stop and cannot poison the
    workspace's labour costs.
    """

    technician_id: uuid.UUID | None = None
    rate: float = Field(default=0.0, ge=0, description="Hourly cost rate")
    note: str | None = None


class TimeEntryCreate(BaseModel):
    """Log a completed time entry with an explicit start and end.

    ``rate`` is ignored (forced to 0) for callers without ``billing:read``.
    """

    technician_id: uuid.UUID | None = None
    started_at: datetime
    ended_at: datetime
    rate: float = Field(default=0.0, ge=0)
    note: str | None = None


class TimeEntryResponse(BaseModel):
    """A time entry as returned by the API.

    **Money is redacted for callers without ``billing:read``.** A field
    technician keeps full read access to this endpoint — they need it to see
    whether a timer is running and to clock in/out — but ``rate`` and
    ``labor_cost`` are served as ``0`` to them, so no cost data crosses the wire
    even to someone reading the raw response. See
    :meth:`app.services.jobs.costing_service.JobCostingService._time_entry_response`.
    """

    id: uuid.UUID
    job_id: uuid.UUID
    technician_id: uuid.UUID | None = None
    started_at: datetime
    ended_at: datetime | None = None
    stop_reason: Literal["paused", "ended", "manual"] | None = None
    # True only when the signed-in user created this entry; used for timer controls.
    is_mine: bool = False
    # Redacted to 0 for callers without billing:read.
    rate: float
    note: str | None = None
    # Server-computed: hours between start and end (0 while the clock runs).
    # Operational, not money — always served.
    duration_hours: float
    # Server-computed: duration_hours * rate (0 while the clock runs).
    # Redacted to 0 for callers without billing:read.
    labor_cost: float
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ContactJobTimeEntryResponse(BaseModel):
    """Price-free job time shown on the associated client's profile."""

    id: uuid.UUID
    job_id: uuid.UUID
    job_title: str
    technician_name: str | None = None
    started_at: datetime
    ended_at: datetime | None = None
    stop_reason: Literal["paused", "ended", "manual"] | None = None
    duration_hours: float


class ContactJobTimeSummaryResponse(BaseModel):
    """Saved job-time history for one client, with no labor pricing."""

    total_hours: float
    entry_count: int
    entries: list[ContactJobTimeEntryResponse]


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
    sums expenses; ``material_cost`` sums stock consumed on the job from the
    inventory ledger (net of anything returned). ``margin`` is
    ``profit / revenue`` (null when revenue is 0).
    """

    job_id: uuid.UUID
    currency: str
    revenue: float
    labor_cost: float
    expense_cost: float
    # Stock consumed on the job, valued from the inventory ledger. Kept distinct
    # from an expense in the free-form "materials" category: consuming stock
    # never writes a JobExpense, so the two never double-count.
    material_cost: float = 0.0
    total_cost: float
    profit: float
    margin: float | None = None
    # Convenience rollups for the UI header.
    total_hours: float
    open_timer: bool
