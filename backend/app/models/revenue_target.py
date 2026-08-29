"""Owner-set monthly revenue targets.

The dashboard has always reported *trailing* revenue (``won_value`` in
:mod:`app.services.dashboard.dashboard_service`) with nothing to measure it
against, so an owner could see what sold but never whether the month was on
pace. This table is that missing denominator.

It is a table, not a key under ``workspace.settings`` (the pattern
:mod:`app.services.quotes.pricing_config` uses), because a target is **data**,
not configuration: there is one row per calendar month, rows accumulate into a
history, and last June's goal must stay readable after this June's is set.
Home-service work is seasonal — $130K in June and $45K in January — so a single
scalar "monthly goal" on the workspace would be wrong eleven months a year.

Every planning field except ``revenue_goal`` is nullable: an owner can commit to
a number on day one and fill in the funnel assumptions later. Consumers must
therefore treat a null (or a non-positive) assumption as "unknown" and report
nothing, never zero — see
:func:`app.services.reporting.revenue_target_service.backsolve_funnel`.

Money is ``Numeric`` in major units, matching :mod:`app.models.invoice` and
:mod:`app.models.opportunity`; percent fields are 0..100 (not 0..1 ratios), which
is what the operator types into the form.
"""

import uuid
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DATE,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.tenancy import WorkspaceScoped

if TYPE_CHECKING:
    from app.models.workspace import Workspace

# Share of leads that turn into a *sat* estimate — trade jargon for an estimate
# actually run in front of the customer, as opposed to a lead that never books,
# cancels, or is a no-show. It is the one funnel stage a CRM cannot infer
# reliably (an unbooked lead leaves no artifact), so it is an owner-editable
# assumption with an industry-typical default rather than a derived metric.
DEFAULT_ASSUMED_SAT_RATE = 60.0

# The upsert in the revenue-target service targets this constraint by name, so
# it is spelled in full (the ``uq`` naming convention only applies to unnamed
# constraints). Check constraints take bare names and let
# ``app.db.base.NAMING_CONVENTION`` prefix them with ``ck_revenue_targets_``,
# matching :mod:`app.models.lead_source`.
UQ_WORKSPACE_MONTH = "uq_revenue_targets_workspace_month"
CK_PERIOD_MONTH_FIRST_DAY = "period_month_is_first_of_month"
CK_REVENUE_GOAL_NON_NEGATIVE = "revenue_goal_nonnegative"
CK_CLOSE_RATE_PERCENT = "close_rate_percent_range"
CK_SAT_RATE_PERCENT = "sat_rate_percent_range"


class RevenueTarget(Base, WorkspaceScoped):
    """One workspace's revenue goal and funnel assumptions for one month."""

    __tablename__ = "revenue_targets"
    __table_args__ = (
        # One target per workspace per month. Upserts key on this pair, so it is
        # load-bearing rather than merely defensive.
        UniqueConstraint("workspace_id", "period_month", name=UQ_WORKSPACE_MONTH),
        # ``period_month`` names a month, not a day. The service normalizes any
        # date to the 1st before writing; this refuses a row that reached the
        # table another way, which would otherwise split one month's target into
        # two rows that both look valid.
        CheckConstraint("date_part('day', period_month) = 1", name=CK_PERIOD_MONTH_FIRST_DAY),
        CheckConstraint("revenue_goal >= 0", name=CK_REVENUE_GOAL_NON_NEGATIVE),
        # Percent columns are the *divisors* in the funnel backsolve. Bounding
        # them here keeps an out-of-range value from turning into a nonsense
        # required-lead count downstream.
        CheckConstraint(
            "target_close_rate IS NULL OR (target_close_rate > 0 AND target_close_rate <= 100)",
            name=CK_CLOSE_RATE_PERCENT,
        ),
        CheckConstraint(
            "assumed_sat_rate > 0 AND assumed_sat_rate <= 100",
            name=CK_SAT_RATE_PERCENT,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # First day of the target month (e.g. 2026-06-01 for June 2026).
    period_month: Mapped[date] = mapped_column(DATE, nullable=False)

    # The commitment: revenue the workspace intends to sell in this month.
    revenue_goal: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)

    # --- Funnel assumptions used to backsolve the goal into stage counts ---
    # Mean ticket the goal assumes; jobs needed = revenue_goal / this.
    target_avg_job_value: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    # Percent (0..100] of sat estimates that close; estimates = jobs / this.
    target_close_rate: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    # Percent (0..100] of leads that become a sat estimate; leads = estimates / this.
    assumed_sat_rate: Mapped[float] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        default=DEFAULT_ASSUMED_SAT_RATE,
        server_default="60",
    )
    # An owner's own lead number. When set it *overrides* the backsolved lead
    # requirement — a hand-set target beats a derived one.
    target_leads: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- Delivery capacity, so a goal can be checked against reality ---
    # Estimates the workspace can actually run in a month.
    estimate_capacity_per_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Sellable crew hours per week.
    crew_capacity_hours_per_week: Mapped[float | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    # Booked-out backlog (in weeks) at which the owner wants to be warned —
    # too long and leads go cold, too short and crews idle.
    backlog_alert_weeks: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    workspace: Mapped["Workspace"] = relationship("Workspace")

    def __repr__(self) -> str:
        return (
            f"<RevenueTarget(id={self.id}, workspace_id={self.workspace_id}, "
            f"period_month={self.period_month}, revenue_goal={self.revenue_goal})>"
        )
