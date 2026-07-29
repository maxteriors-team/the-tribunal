"""Schemas for monthly revenue targets and month-pace reporting.

Two halves:

- the **target** shapes, which read and write
  :class:`app.models.revenue_target.RevenueTarget` (one row per month, upserted
  by ``period_month``);
- the **pace** shapes, a read-only roll-up that answers "is this month on
  track?" by pairing the target with the month's actuals.

Conventions follow the neighbouring reports (:mod:`app.schemas.reporting`):
money is ``float`` in major units, and any number whose denominator is missing
is ``None`` rather than ``0`` — "we never set an average job value" must not
render as "we need 0 estimates".

Percent fields (``target_close_rate``, ``assumed_sat_rate``) are 0..100, not
0..1 ratios, matching what an operator types into the goal form. They are the
divisors of the funnel backsolve, so they reject 0 at the boundary; the maths
guards against a non-positive value anyway for rows written another way.
"""

import uuid
from datetime import date, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.revenue_target import DEFAULT_ASSUMED_SAT_RATE

# Ceiling on a single bulk upsert: five years of months. Enough to plan several
# seasons ahead in one call, small enough that the statement stays bounded.
MAX_BULK_TARGETS = 60


class RevenueTargetBase(BaseModel):
    """Client-settable fields of a month's revenue target."""

    revenue_goal: float = Field(
        ge=0, description="Revenue the workspace intends to sell this month, in major units"
    )
    target_avg_job_value: float | None = Field(
        default=None,
        gt=0,
        description="Mean ticket the goal assumes; jobs needed = revenue_goal / this",
    )
    target_close_rate: float | None = Field(
        default=None,
        gt=0,
        le=100,
        description="Percent of sat estimates that close; estimates needed = jobs / this",
    )
    assumed_sat_rate: float = Field(
        default=DEFAULT_ASSUMED_SAT_RATE,
        gt=0,
        le=100,
        description=(
            "Percent of leads that become a sat (run) estimate; leads needed = "
            "estimates / this. An assumption, not a measured metric — an unbooked "
            "lead leaves no artifact in the CRM to count."
        ),
    )
    target_leads: int | None = Field(
        default=None,
        ge=0,
        description=(
            "The owner's own lead target. When set it overrides the backsolved "
            "lead requirement; leave null to derive it from the goal."
        ),
    )
    estimate_capacity_per_month: int | None = Field(
        default=None, ge=0, description="Estimates the workspace can actually run in a month"
    )
    crew_capacity_hours_per_week: float | None = Field(
        default=None, ge=0, description="Sellable crew hours available per week"
    )
    backlog_alert_weeks: float | None = Field(
        default=None, ge=0, description="Booked-out backlog (weeks) at which to warn the owner"
    )


class RevenueTargetUpsert(RevenueTargetBase):
    """Set (or replace) the target for one month.

    ``period_month`` may be any day inside the month; the service normalizes it
    to the 1st before writing, so ``2026-06-14`` and ``2026-06-01`` address the
    same row rather than creating two targets for June.
    """

    period_month: date = Field(
        description="Any date inside the target month; normalized to the 1st on write"
    )


class RevenueTargetBulkUpsert(BaseModel):
    """Set a whole season (or year) of targets in one call."""

    targets: list[RevenueTargetUpsert] = Field(min_length=1, max_length=MAX_BULK_TARGETS)

    @model_validator(mode="after")
    def _reject_duplicate_months(self) -> Self:
        """Refuse a payload that names the same month twice.

        Both entries would key to the same row, so one would silently win. That
        is a client bug worth surfacing, not a merge to guess at.
        """
        months = [target.period_month.replace(day=1) for target in self.targets]
        if len(set(months)) != len(months):
            duplicates = sorted({month.isoformat() for month in months if months.count(month) > 1})
            raise ValueError(f"Duplicate target months in payload: {', '.join(duplicates)}")
        return self


class RevenueTargetResponse(RevenueTargetBase):
    """A stored monthly target as returned by the API."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    period_month: date
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RevenueTargetList(BaseModel):
    """Targets for a workspace, oldest month first."""

    items: list[RevenueTargetResponse]
    total: int


PaceStageName = Literal["leads", "estimates", "sold"]


class PaceStage(BaseModel):
    """One funnel stage's actual-vs-required counts for the month.

    ``required`` is backsolved from the revenue goal (see
    :func:`app.services.reporting.revenue_target_service.backsolve_funnel`) and
    is ``None`` whenever an assumption it depends on is missing, so a stage
    never claims a requirement the owner never expressed.
    """

    stage: PaceStageName
    actual: int = Field(description="Count recorded in this workspace so far this month")
    required: float | None = Field(
        default=None, description="Whole-month requirement implied by the goal; null when unknown"
    )
    required_to_date: float | None = Field(
        default=None, description="Requirement pro-rated to days elapsed; null when unknown"
    )
    gap: float | None = Field(
        default=None,
        description=(
            "required - actual for the whole month; positive means behind, null when unknown"
        ),
    )


class RevenuePace(BaseModel):
    """Whether a month is on pace to hit its revenue goal.

    Projection is deliberately linear (sold-to-date scaled by the share of the
    month elapsed): it is the model an owner can check in their head, and any
    seasonality is already expressed by setting a different goal per month.

    Every field that divides is guarded — a month with no elapsed days projects
    ``None``, and a month with no stored target reports ``has_target: false``
    with actuals still populated, so the dashboard can prompt for a goal instead
    of erroring.
    """

    period_month: date = Field(description="First day of the month being reported")
    as_of: date = Field(description="Date the pace was computed against")
    has_target: bool = Field(description="False when no target row exists for this month")
    currency: str = Field(description="Currency of every money field in this report")
    revenue_goal: float | None = Field(default=None, description="Null when no target is set")
    revenue_sold_to_date: float = Field(
        description="Closed-won opportunity value with a close date inside the month so far"
    )
    days_elapsed: int = Field(description="Days of the month counted, including today")
    days_in_month: int
    projected_month_end: float | None = Field(
        default=None,
        description=(
            "Linear pace: sold_to_date / days_elapsed * days_in_month; null before the month starts"
        ),
    )
    gap_to_goal: float | None = Field(
        default=None, description="revenue_goal - revenue_sold_to_date; still to sell this month"
    )
    projected_gap_to_goal: float | None = Field(
        default=None,
        description="revenue_goal - projected_month_end; negative means the pace clears the goal",
    )
    on_pace: bool | None = Field(
        default=None, description="True when the projection reaches the goal; null when unknowable"
    )
    stages: list[PaceStage] = Field(description="Actual vs required for leads, estimates and sold")
    estimate_capacity_per_month: int | None = Field(
        default=None, description="Estimates the workspace says it can run in a month"
    )
    estimates_over_capacity: float | None = Field(
        default=None,
        description=(
            "Required estimates minus stated capacity; positive means the goal "
            "cannot be delivered without more capacity. Null when either is unset."
        ),
    )
