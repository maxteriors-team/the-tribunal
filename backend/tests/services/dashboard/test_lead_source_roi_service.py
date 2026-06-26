"""Unit tests for lead-source ROI ranking.

These exercise the pure ``assemble_roi_stats`` function directly with fabricated
per-channel aggregates, so the ranking / cost-per-job / ROI / confidence maths
is covered without a database.
"""

from app.models.lead_source import LeadSourceType
from app.schemas.lead_source import AttributionConfidenceLevel
from app.services.dashboard.lead_source_roi_service import (
    _ChannelAgg,
    assemble_roi_stats,
)


def _agg(
    *,
    spend: float = 0.0,
    jobs: int = 0,
    revenue: float = 0.0,
    confidence: float | None = None,
) -> _ChannelAgg:
    agg = _ChannelAgg(
        spend=spend,
        closed_won_jobs=jobs,
        closed_won_revenue=revenue,
        attributed_jobs=jobs,
    )
    if confidence is not None and jobs > 0:
        agg.confidence_scores = [confidence] * jobs
    return agg


def _row_for(stats, source_type: LeadSourceType):
    return next(r for r in stats.rows if r.source_type == source_type)


def test_ranks_by_roi_when_spend_present():
    aggregates = {
        LeadSourceType.FACEBOOK_ADS: _agg(spend=5000, jobs=8, revenue=42000, confidence=0.9),
        LeadSourceType.GOOGLE_ADS: _agg(spend=3000, jobs=4, revenue=16000, confidence=0.8),
    }

    stats = assemble_roi_stats(aggregates, total_closed_won_jobs=12)

    assert stats.winner.has_winner is True
    assert stats.winner.rank_by == "roi"
    # Facebook: 42000/5000 = 8.4x beats Google: 16000/3000 = 5.33x.
    assert stats.winner.source_type == LeadSourceType.FACEBOOK_ADS
    assert stats.winner.roi_multiple == 8.4
    assert stats.rows[0].source_type == LeadSourceType.FACEBOOK_ADS
    assert stats.rows[0].rank == 1
    assert stats.rows[0].is_winner is True
    # Totals roll up across channels.
    assert stats.total_spend == 8000
    assert stats.total_closed_won_revenue == 58000
    assert stats.total_closed_won_jobs == 12


def test_cost_per_job_and_roi_blank_without_spend():
    aggregates = {
        LeadSourceType.PHONE_RADIO: _agg(spend=0, jobs=2, revenue=6000),
    }

    stats = assemble_roi_stats(aggregates, total_closed_won_jobs=2)

    row = _row_for(stats, LeadSourceType.PHONE_RADIO)
    assert row.spend == 0
    assert row.cost_per_closed_won_job is None
    assert row.roi_multiple is None
    assert row.revenue_per_closed_won_job == 3000
    # No spend anywhere → rank by revenue, not ROI.
    assert stats.winner.rank_by == "closed_won_revenue"
    assert stats.winner.source_type == LeadSourceType.PHONE_RADIO


def test_ranks_by_jobs_when_no_revenue_or_spend():
    aggregates = {
        LeadSourceType.ORGANIC: _agg(spend=0, jobs=3, revenue=0),
    }

    stats = assemble_roi_stats(aggregates, total_closed_won_jobs=3)

    assert stats.winner.rank_by == "closed_won_jobs"
    assert stats.winner.source_type == LeadSourceType.ORGANIC
    assert "Add spend" in stats.winner.reason


def test_spend_without_jobs_has_no_winner():
    # Money going out, nothing closed: the high-spend channel must NOT win.
    aggregates = {
        LeadSourceType.FACEBOOK_ADS: _agg(spend=1500.5, jobs=0, revenue=0),
    }

    stats = assemble_roi_stats(aggregates, total_closed_won_jobs=0)

    assert stats.winner.has_winner is False
    assert stats.winner.rank_by == "none"
    assert all(r.is_winner is False for r in stats.rows)
    # Spend still surfaces in the table and totals.
    assert stats.total_spend == 1500.5
    assert _row_for(stats, LeadSourceType.FACEBOOK_ADS).spend == 1500.5
    # The reason makes the "no winner despite spend" state explicit.
    assert "no winner" in stats.winner.reason.lower()


def test_free_channel_with_jobs_outranks_paid_channel():
    # Organic produces jobs for free (infinite ROI) and should beat paid FB.
    aggregates = {
        LeadSourceType.FACEBOOK_ADS: _agg(spend=1000, jobs=2, revenue=5000),
        LeadSourceType.ORGANIC: _agg(spend=0, jobs=5, revenue=20000),
    }

    stats = assemble_roi_stats(aggregates, total_closed_won_jobs=7)

    assert stats.winner.has_winner is True
    assert stats.winner.source_type == LeadSourceType.ORGANIC
    assert stats.winner.roi_multiple is None
    assert "efficient" in stats.winner.reason
    # Empty channels still sink below both producers.
    assert stats.rows[0].source_type == LeadSourceType.ORGANIC
    assert stats.rows[1].source_type == LeadSourceType.FACEBOOK_ADS


def test_no_winner_when_no_activity():
    stats = assemble_roi_stats({}, total_closed_won_jobs=0)

    assert stats.winner.has_winner is False
    assert stats.winner.rank_by == "none"
    # The four ranked channels still render as zeroed rows.
    assert {r.source_type for r in stats.rows} == set(stats.source_types_ranked)
    assert all(r.is_winner is False for r in stats.rows)


def test_confidence_summary_buckets_and_ratio():
    aggregates = {
        LeadSourceType.FACEBOOK_ADS: _agg(spend=1000, jobs=3, revenue=9000, confidence=0.97),
    }

    stats = assemble_roi_stats(aggregates, total_closed_won_jobs=5)

    row = _row_for(stats, LeadSourceType.FACEBOOK_ADS)
    conf = row.attribution_confidence
    assert conf.level == AttributionConfidenceLevel.EXACT
    assert conf.attributed_closed_won_jobs == 3
    # Two of the five won jobs are unattributed at the workspace level.
    assert conf.total_closed_won_jobs == 5
    assert conf.average_score == 0.97


def test_other_channel_only_shown_with_activity():
    # No activity on "other" → it stays out of the table.
    stats_empty = assemble_roi_stats(
        {LeadSourceType.FACEBOOK_ADS: _agg(spend=100, jobs=1, revenue=500)},
        total_closed_won_jobs=1,
    )
    assert LeadSourceType.OTHER not in {r.source_type for r in stats_empty.rows}

    # Activity on "other" → it appears.
    stats_active = assemble_roi_stats(
        {LeadSourceType.OTHER: _agg(spend=200, jobs=1, revenue=800)},
        total_closed_won_jobs=1,
    )
    assert LeadSourceType.OTHER in {r.source_type for r in stats_active.rows}
