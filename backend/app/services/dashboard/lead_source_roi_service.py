"""Lead-source ROI computation for the dashboard.

Ranks acquisition channels (Facebook Ads, Google Ads, Organic, Phone/Radio,
and an "other" catch-all) by ad spend and closed-won jobs so operators can see
which lead source is actually winning.

Only channels that produced at least one closed-won job can win; ad spend with
no attributed jobs is a loss, never a winner. Among winner-eligible channels the
ranking dimension is chosen in priority order:

1. If any eligible channel has recorded spend, rank by ROI multiple
   (revenue / spend); a channel with jobs but no spend is treated as the most
   efficient possible source and sorts first.
2. Otherwise, if any eligible channel has closed-won revenue, rank by revenue.
3. Otherwise, rank by closed-won job count.
4. If no channel has closed-won jobs, there is no winner.

Spend with no attributed jobs and jobs with no spend are both handled
gracefully (cost-per-job and ROI stay ``None`` when undefined).
"""

import uuid
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_source import LeadSource, LeadSourceSpendEntry, LeadSourceType
from app.models.opportunity import Opportunity
from app.schemas.lead_source import (
    AttributionConfidenceLevel,
    AttributionConfidenceSummary,
    LeadSourceROIStats,
    LeadSourceWinnerSummary,
    SourceROIRow,
)

# Channels surfaced in the ranked table, in display order. ``other`` is only
# included when it has activity (handled below).
RANKED_SOURCE_TYPES: list[LeadSourceType] = [
    LeadSourceType.FACEBOOK_ADS,
    LeadSourceType.GOOGLE_ADS,
    LeadSourceType.ORGANIC,
    LeadSourceType.PHONE_RADIO,
]

SOURCE_TYPE_LABELS: dict[LeadSourceType, str] = {
    LeadSourceType.FACEBOOK_ADS: "Facebook Ads",
    LeadSourceType.GOOGLE_ADS: "Google Ads",
    LeadSourceType.ORGANIC: "Organic",
    LeadSourceType.PHONE_RADIO: "Phone / Radio",
    LeadSourceType.OTHER: "Other",
}

DEFAULT_CURRENCY = "USD"


@dataclass
class _ChannelAgg:
    """Mutable accumulator for one channel while scanning query rows."""

    spend: float = 0.0
    closed_won_jobs: int = 0
    closed_won_revenue: float = 0.0
    attributed_jobs: int = 0
    confidence_scores: list[float] = field(default_factory=list)


def _confidence_level(average: float | None) -> AttributionConfidenceLevel:
    """Bucket a 0..1 average confidence into a human-readable level."""
    if average is None:
        return AttributionConfidenceLevel.UNKNOWN
    if average >= 0.95:
        return AttributionConfidenceLevel.EXACT
    if average >= 0.8:
        return AttributionConfidenceLevel.HIGH
    if average >= 0.5:
        return AttributionConfidenceLevel.MEDIUM
    if average > 0:
        return AttributionConfidenceLevel.LOW
    return AttributionConfidenceLevel.UNKNOWN


def _build_confidence(agg: _ChannelAgg, total_closed_won_jobs: int) -> AttributionConfidenceSummary:
    average = (
        sum(agg.confidence_scores) / len(agg.confidence_scores) if agg.confidence_scores else None
    )
    return AttributionConfidenceSummary(
        average_score=round(average, 3) if average is not None else None,
        level=_confidence_level(average),
        attributed_closed_won_jobs=agg.attributed_jobs,
        total_closed_won_jobs=total_closed_won_jobs,
    )


async def compute_lead_source_roi(db: AsyncSession, workspace_id: uuid.UUID) -> LeadSourceROIStats:
    """Compute ranked lead-source ROI for a workspace dashboard."""
    aggregates: dict[LeadSourceType, _ChannelAgg] = {}

    def bucket(source_type: LeadSourceType) -> _ChannelAgg:
        return aggregates.setdefault(source_type, _ChannelAgg())

    # --- Spend per channel ---------------------------------------------------
    spend_result = await db.execute(
        select(
            LeadSource.source_type,
            func.coalesce(func.sum(LeadSourceSpendEntry.amount), 0),
        )
        .join(LeadSource, LeadSource.id == LeadSourceSpendEntry.lead_source_id)
        .where(LeadSourceSpendEntry.workspace_id == workspace_id)
        .group_by(LeadSource.source_type)
    )
    for source_type, total in spend_result.all():
        bucket(source_type).spend = float(total or 0)

    # --- Closed-won jobs/revenue per channel ---------------------------------
    # Attributed jobs join to a lead source; unattributed won jobs still count
    # toward the workspace total so the confidence ratio is honest.
    won_result = await db.execute(
        select(
            LeadSource.source_type,
            func.count(),
            func.coalesce(func.sum(Opportunity.amount), 0),
            func.avg(Opportunity.attribution_confidence),
            func.count(Opportunity.attribution_confidence),
        )
        .join(LeadSource, LeadSource.id == Opportunity.lead_source_id)
        .where(
            Opportunity.workspace_id == workspace_id,
            Opportunity.status == "won",
        )
        .group_by(LeadSource.source_type)
    )
    for source_type, count, revenue, avg_conf, conf_count in won_result.all():
        agg = bucket(source_type)
        agg.closed_won_jobs = int(count or 0)
        agg.attributed_jobs = int(count or 0)
        agg.closed_won_revenue = float(revenue or 0)
        if avg_conf is not None and conf_count:
            # Replay the average as N identical scores so multi-channel means
            # stay weighted by job count without storing every row.
            agg.confidence_scores = [float(avg_conf)] * int(conf_count)

    total_won_result = await db.execute(
        select(func.count()).where(
            Opportunity.workspace_id == workspace_id,
            Opportunity.status == "won",
        )
    )
    total_closed_won_jobs = int(total_won_result.scalar() or 0)

    return assemble_roi_stats(aggregates, total_closed_won_jobs)


def assemble_roi_stats(
    aggregates: dict[LeadSourceType, "_ChannelAgg"], total_closed_won_jobs: int
) -> LeadSourceROIStats:
    """Build ranked ROI rows + winner from per-channel aggregates.

    Pure function (no I/O) so the ranking, cost-per-job, ROI, and confidence
    logic can be unit-tested with fabricated aggregates.
    """
    # --- Assemble rows -------------------------------------------------------
    display_types = list(RANKED_SOURCE_TYPES)
    if LeadSourceType.OTHER in aggregates and (
        aggregates[LeadSourceType.OTHER].spend > 0
        or aggregates[LeadSourceType.OTHER].closed_won_jobs > 0
    ):
        display_types.append(LeadSourceType.OTHER)

    rows: list[SourceROIRow] = []
    for source_type in display_types:
        agg = aggregates.get(source_type, _ChannelAgg())
        jobs = agg.closed_won_jobs
        spend = round(agg.spend, 2)
        revenue = round(agg.closed_won_revenue, 2)
        cost_per_job = round(spend / jobs, 2) if jobs > 0 and spend > 0 else None
        revenue_per_job = round(revenue / jobs, 2) if jobs > 0 else None
        roi_multiple = round(revenue / spend, 2) if spend > 0 else None
        rows.append(
            SourceROIRow(
                rank=1,  # provisional; assigned after sorting
                source_type=source_type,
                source_name=SOURCE_TYPE_LABELS[source_type],
                lead_source_id=None,
                spend=spend,
                closed_won_jobs=jobs,
                closed_won_revenue=revenue,
                cost_per_closed_won_job=cost_per_job,
                revenue_per_closed_won_job=revenue_per_job,
                roi_multiple=roi_multiple,
                net_revenue=round(revenue - spend, 2),
                currency=DEFAULT_CURRENCY,
                attribution_confidence=_build_confidence(agg, total_closed_won_jobs),
            )
        )

    total_spend = round(sum(r.spend for r in rows), 2)
    total_revenue = round(sum(r.closed_won_revenue for r in rows), 2)
    total_jobs = sum(r.closed_won_jobs for r in rows)

    # --- Decide ranking dimension -------------------------------------------
    # Only channels that actually produced closed-won jobs can win. Spend with
    # zero jobs is a loss, never a winner, so the ranking dimension is chosen
    # from eligible channels alone.
    eligible = [r for r in rows if r.closed_won_jobs > 0]
    rank_by: Literal["roi", "closed_won_revenue", "closed_won_jobs", "none"]
    if not eligible:
        rank_by = "none"
    elif any(r.spend > 0 for r in eligible):
        rank_by = "roi"
    elif any(r.closed_won_revenue > 0 for r in eligible):
        rank_by = "closed_won_revenue"
    else:
        rank_by = "closed_won_jobs"

    def sort_key(row: SourceROIRow) -> tuple[float, float, float, int]:
        # Channels with jobs always outrank empty/loss-only channels.
        eligible_flag = 1.0 if row.closed_won_jobs > 0 else 0.0
        if rank_by == "roi":
            primary = _roi_rank_value(row)
            return (eligible_flag, primary, row.closed_won_revenue, row.closed_won_jobs)
        if rank_by == "closed_won_revenue":
            return (eligible_flag, row.closed_won_revenue, 0.0, row.closed_won_jobs)
        if rank_by == "closed_won_jobs":
            return (eligible_flag, float(row.closed_won_jobs), row.closed_won_revenue, 0)
        return (eligible_flag, 0.0, 0.0, 0)

    rows.sort(key=sort_key, reverse=True)
    for index, row in enumerate(rows, start=1):
        row.rank = index

    # --- Winner --------------------------------------------------------------
    has_winner = rank_by != "none" and bool(rows) and rows[0].closed_won_jobs > 0
    if has_winner:
        winner_row = rows[0]
        winner_row.is_winner = True
        winner = LeadSourceWinnerSummary(
            has_winner=True,
            source_type=winner_row.source_type,
            source_name=winner_row.source_name,
            lead_source_id=winner_row.lead_source_id,
            rank_by=rank_by,
            spend=winner_row.spend,
            closed_won_jobs=winner_row.closed_won_jobs,
            closed_won_revenue=winner_row.closed_won_revenue,
            roi_multiple=winner_row.roi_multiple,
            net_revenue=winner_row.net_revenue,
            currency=DEFAULT_CURRENCY,
            reason=_winner_reason(winner_row),
            attribution_confidence=winner_row.attribution_confidence,
        )
    elif total_spend > 0:
        # Money is going out but nothing has closed yet — be explicit so the
        # card never implies a 0x channel is "winning".
        winner = LeadSourceWinnerSummary(
            reason="Ad spend recorded, but no closed-won jobs attributed yet — no winner."
        )
    else:
        winner = LeadSourceWinnerSummary()

    return LeadSourceROIStats(
        currency=DEFAULT_CURRENCY,
        rows=rows,
        winner=winner,
        total_spend=total_spend,
        total_closed_won_jobs=total_jobs,
        total_closed_won_revenue=total_revenue,
        source_types_ranked=RANKED_SOURCE_TYPES,
    )


def _roi_rank_value(row: SourceROIRow) -> float:
    """Sortable ROI for a winner-eligible row.

    A channel with closed-won jobs but no tracked spend is the most efficient
    possible source (free customers), so it sorts above any paid channel.
    """
    if row.closed_won_jobs > 0 and row.spend == 0:
        return float("inf")
    return row.roi_multiple or 0.0


def _winner_reason(row: SourceROIRow) -> str:
    """Explain why this channel won, from its own numbers."""
    if row.spend > 0 and row.roi_multiple is not None:
        return f"Best return: {row.roi_multiple:.1f}x on {row.closed_won_jobs} closed-won job(s)."
    if row.spend == 0 and row.closed_won_revenue > 0:
        return (
            f"{row.closed_won_jobs} closed-won job(s) at no tracked ad spend — "
            "your most efficient source."
        )
    return f"Most closed-won jobs ({row.closed_won_jobs}). Add spend to compare ROI."
