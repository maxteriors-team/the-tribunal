"""Lead-source ROI computation for the dashboard.

Ranks acquisition channels by ad spend and canonical booked jobs so operators
can see which lead source is actually winning. A booked job is an approved quote;
legacy/manual won opportunities without approved quotes remain included once.
The four paid/organic channels (Facebook Ads, Google Ads, Organic, Phone/Radio)
always render, even at zero, so a missing channel reads as "no results" rather
than "not tracked". Other channels render once they have spend or a booking.

Only channels that produced a booked job can win. Ranking uses ROI when spend is
tracked, then revenue, then booking count. Spend without bookings and bookings
without spend are both handled without inventing zero-cost or zero-return values.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_source import LeadSource, LeadSourceSpendEntry, LeadSourceType
from app.schemas.lead_source import (
    AttributionConfidenceLevel,
    AttributionConfidenceSummary,
    LeadSourceROIStats,
    LeadSourceWinnerSummary,
    SourceROIRow,
)
from app.services.reporting.booked_revenue import get_booked_revenue_by_attribution
from app.services.reporting.time_windows import get_workspace_reporting_timezone

# Channels always surfaced in the ranked table, in display order.
RANKED_SOURCE_TYPES: list[LeadSourceType] = [
    LeadSourceType.FACEBOOK_ADS,
    LeadSourceType.GOOGLE_ADS,
    LeadSourceType.ORGANIC,
    LeadSourceType.PHONE_RADIO,
]

# Every remaining channel, in enum declaration order. These render only when
# they have spend or booked jobs. Derived rather than hand-listed so a new
# ``LeadSourceType`` member starts reporting ROI without editing this module.
ACTIVITY_GATED_SOURCE_TYPES: list[LeadSourceType] = [
    source_type for source_type in LeadSourceType if source_type not in RANKED_SOURCE_TYPES
]

SOURCE_TYPE_LABELS: dict[LeadSourceType, str] = {
    LeadSourceType.FACEBOOK_ADS: "Facebook Ads",
    LeadSourceType.GOOGLE_ADS: "Google Ads",
    LeadSourceType.ORGANIC: "Organic",
    LeadSourceType.PHONE_RADIO: "Phone / Radio",
    LeadSourceType.REFERRAL_PARTNER: "Referral Partner",
    LeadSourceType.REPEAT_CUSTOMER: "Repeat Customer",
    LeadSourceType.TRUCK_WRAP: "Truck Wrap",
    LeadSourceType.YARD_SIGN: "Yard Sign",
    LeadSourceType.CANVASS_NEIGHBOR: "Jobsite Canvass",
    LeadSourceType.OTHER: "Other",
}

DEFAULT_CURRENCY = "USD"


def source_type_label(source_type: LeadSourceType) -> str:
    """Human label for a channel.

    Falls back to a title-cased value so an unmapped future enum member degrades
    to an ugly label instead of raising ``KeyError`` and 500ing the dashboard.
    """
    return SOURCE_TYPE_LABELS.get(source_type) or source_type.value.replace("_", " ").title()


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

    # --- Canonical booked jobs/revenue per channel --------------------------
    timezone_name = await get_workspace_reporting_timezone(db, workspace_id)
    today = datetime.now(ZoneInfo(timezone_name)).date()
    source_rows = (
        await db.execute(
            select(LeadSource.id, LeadSource.source_type).where(
                LeadSource.workspace_id == workspace_id
            )
        )
    ).all()
    source_types_by_id: dict[uuid.UUID, LeadSourceType] = {}
    for source_id, source_type in source_rows:
        source_types_by_id[source_id] = source_type

    bookings = await get_booked_revenue_by_attribution(
        db,
        workspace_id,
        date(1900, 1, 1),
        today,
        timezone_name=timezone_name,
    )
    total_closed_won_jobs = sum(item.count for item in bookings)
    for item in bookings:
        if item.lead_source_id is None:
            continue
        source_type = source_types_by_id.get(item.lead_source_id)
        if source_type is None:
            continue
        agg = bucket(source_type)
        agg.closed_won_jobs += item.count
        agg.attributed_jobs += item.count
        agg.closed_won_revenue += float(item.revenue)
        if item.count and item.revenue:
            average_confidence = float(item.weighted_confidence / item.revenue)
            agg.confidence_scores.extend([average_confidence] * item.count)

    return assemble_roi_stats(aggregates, total_closed_won_jobs)


def assemble_roi_stats(
    aggregates: dict[LeadSourceType, "_ChannelAgg"], total_closed_won_jobs: int
) -> LeadSourceROIStats:
    """Build ranked ROI rows + winner from per-channel aggregates.

    Pure function (no I/O) so the ranking, cost-per-job, ROI, and confidence
    logic can be unit-tested with fabricated aggregates.
    """

    # --- Assemble rows -------------------------------------------------------
    def has_activity(source_type: LeadSourceType) -> bool:
        agg = aggregates.get(source_type)
        return agg is not None and (agg.spend > 0 or agg.closed_won_jobs > 0)

    display_types = list(RANKED_SOURCE_TYPES)
    display_types.extend(t for t in ACTIVITY_GATED_SOURCE_TYPES if has_activity(t))

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
                source_name=source_type_label(source_type),
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
    # Only channels that actually produced booked jobs can win. Spend with
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
            reason="Ad spend recorded, but no booked jobs attributed yet — no winner."
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

    A channel with booked jobs but no tracked spend is the most efficient
    possible source (free customers), so it sorts above any paid channel.
    """
    if row.closed_won_jobs > 0 and row.spend == 0:
        return float("inf")
    return row.roi_multiple or 0.0


def _winner_reason(row: SourceROIRow) -> str:
    """Explain why this channel won, from its own numbers."""
    if row.spend > 0 and row.roi_multiple is not None:
        return f"Best return: {row.roi_multiple:.1f}x on {row.closed_won_jobs} booked job(s)."
    if row.spend == 0 and row.closed_won_revenue > 0:
        return (
            f"{row.closed_won_jobs} booked job(s) at no tracked ad spend — "
            "your most efficient source."
        )
    return f"Most booked jobs ({row.closed_won_jobs}). Add spend to compare ROI."
