"""Receptionist scorecard schemas.

The scorecard is the owner-facing retention surface: for a chosen date range it
summarises how the AI receptionist performed — how many calls were answered,
how many were missed (and recovered via the text-back/voicemail follow-up),
how much pipeline/revenue was booked, what callers wanted, after-hours
coverage, and the average time spent handling a call.
"""

from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field


class CallReasonStat(BaseModel):
    """A single call reason and how often it came up in the range."""

    reason: str
    count: int


class DailyLeadCount(BaseModel):
    """New leads captured on one calendar day (workspace-local)."""

    date: date
    count: int


class TechnicianActivityScorecardRow(BaseModel):
    """Recorded activity for one technician in the selected local-date range.

    These fields are context only, not a quality, compensation, or ranking signal.
    """

    id: UUID
    name: str
    active: bool
    assigned_jobs: int
    completed_job_time_entries: int
    job_logged_seconds: int
    attendance_worked_seconds: int
    attendance_paused_seconds: int


class OfficeRepScorecardRow(BaseModel):
    """Admin/CSR profile activity for the selected local-date range."""

    user_id: int
    name: str
    role: str
    avatar_url: str | None
    attendance_days: int = Field(ge=0)
    attendance_worked_seconds: int = Field(ge=0)
    booked_jobs: int = Field(ge=0)
    cancelled_jobs: int = Field(ge=0)
    cancellation_rate: float | None = Field(ge=0, le=100)
    responses_measured: int = Field(ge=0)
    avg_response_time_seconds: float | None = Field(ge=0)


class ReceptionistScorecard(BaseModel):
    """Aggregated receptionist performance for a workspace over a date range."""

    # Window (inclusive start date, inclusive end date) the metrics cover.
    start_date: date
    end_date: date

    # --- Call volume / answering -------------------------------------------
    calls_total: int
    calls_answered: int
    answer_rate: float | None  # answered / total * 100; null when no calls

    # --- Missed calls + recovery (ties to the text-back/voicemail tasks) ---
    missed_calls: int
    missed_calls_textback_sent: int  # missed calls that triggered a text-back SMS
    missed_calls_recovered: int  # missed calls where the caller re-engaged/booked
    recovery_rate: float | None  # recovered / missed * 100; null when no misses

    # --- Booking outcomes ---------------------------------------------------
    appointments_booked: int  # appointments created in the range
    revenue_booked: float  # approved quotes + legacy unquoted won deals
    deposits_booked: float  # quote deposits actually marked paid in the range
    currency: str

    # --- New lead intake ----------------------------------------------------
    # "Lead" is a contacts row, counted by ``created_at`` — the same definition
    # the Contacts page stat cards use for "new leads". No status/source filter,
    # so a bulk import (e.g. Jobber) lands every imported client on its import
    # day rather than its original acquisition day.
    new_leads_total: int
    # One entry per calendar day in the range, ascending, zero-filled so a day
    # with no leads is an explicit 0 instead of a gap in the series.
    new_leads_by_day: list[DailyLeadCount]
    avg_new_leads_per_day: float | None  # null when the range covers no days

    # --- After-hours coverage ----------------------------------------------
    after_hours_calls: int
    after_hours_answered: int
    after_hours_coverage_rate: float | None  # answered / calls after hours * 100

    # --- Handle time --------------------------------------------------------
    avg_handle_time_seconds: float | None  # avg duration of answered calls

    # --- Top call reasons ---------------------------------------------------
    top_call_reasons: list[CallReasonStat]
