"""Add revenue_targets: one revenue goal (and funnel assumptions) per month.

Revision ID: 7dc9d61efed7
Revises: cacf6d2e5463
Create Date: 2026-07-29 12:37:52.184169

The dashboard reported trailing closed-won revenue with nothing to measure it
against. This table is the missing denominator: ``revenue_targets`` holds one
row per workspace per calendar month, so a seasonal trade can commit to $130K in
June and $45K in January and the pace report can backsolve either into the
leads / estimates / sold counts required to get there.

A table rather than a key under ``workspace.settings`` (the pattern
``app.services.quotes.pricing_config`` uses) because a target is data, not
configuration: rows accumulate into a history and last June's goal must stay
readable after this June's is set.

Purely additive — a new table with a cascading FK to ``workspaces``, no change
to any existing table, so it is safe on live data and the downgrade is a clean
drop.

Constraints worth their weight at the storage layer:

- ``uq_revenue_targets_workspace_month`` is load-bearing, not defensive: the
  service upserts ``ON CONFLICT`` against it, which is what makes "set June"
  idempotent under concurrent saves instead of writing two Junes.
- ``ck_revenue_targets_period_month_is_first_of_month`` keeps ``period_month``
  naming a month rather than a day. The service normalizes to the 1st on write;
  this refuses a row that arrived another way (a script, a manual INSERT), which
  would otherwise split one month's target into two rows that both look valid.
- The percent columns are the *divisors* of the backsolve, so their ranges are
  enforced here too — a zero or negative rate reaching the table would make
  "estimates required" meaningless rather than merely wrong.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7dc9d61efed7"
down_revision: str | None = "cacf6d2e5463"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WORKSPACE_INDEX = "ix_revenue_targets_workspace_id"


def upgrade() -> None:
    op.create_table(
        "revenue_targets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("period_month", sa.DATE(), nullable=False),
        sa.Column("revenue_goal", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("target_avg_job_value", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("target_close_rate", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column(
            "assumed_sat_rate",
            sa.Numeric(precision=5, scale=2),
            server_default="60",
            nullable=False,
        ),
        sa.Column("target_leads", sa.Integer(), nullable=True),
        sa.Column("estimate_capacity_per_month", sa.Integer(), nullable=True),
        sa.Column("crew_capacity_hours_per_week", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("backlog_alert_weeks", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "date_part('day', period_month) = 1",
            name=op.f("ck_revenue_targets_period_month_is_first_of_month"),
        ),
        sa.CheckConstraint(
            "revenue_goal >= 0",
            name=op.f("ck_revenue_targets_revenue_goal_nonnegative"),
        ),
        sa.CheckConstraint(
            "target_close_rate IS NULL OR (target_close_rate > 0 AND target_close_rate <= 100)",
            name=op.f("ck_revenue_targets_close_rate_percent_range"),
        ),
        sa.CheckConstraint(
            "assumed_sat_rate > 0 AND assumed_sat_rate <= 100",
            name=op.f("ck_revenue_targets_sat_rate_percent_range"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_revenue_targets_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_revenue_targets")),
        sa.UniqueConstraint(
            "workspace_id", "period_month", name="uq_revenue_targets_workspace_month"
        ),
    )
    op.create_index(op.f(WORKSPACE_INDEX), "revenue_targets", ["workspace_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f(WORKSPACE_INDEX), table_name="revenue_targets")
    op.drop_table("revenue_targets")
