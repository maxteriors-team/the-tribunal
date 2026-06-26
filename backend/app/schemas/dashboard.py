"""Dashboard statistics schemas."""

from pydantic import BaseModel, Field

from app.schemas.lead_source import LeadSourceROIStats


class DashboardStats(BaseModel):
    """Core dashboard statistics."""

    total_contacts: int
    active_campaigns: int
    calls_today: int
    messages_sent: int
    # Change percentages (compared to previous period)
    contacts_change: str
    campaigns_change: str
    calls_change: str
    messages_change: str


class RecentActivity(BaseModel):
    """Recent activity item."""

    id: str
    type: str  # call, sms, campaign, booking
    contact: str
    initials: str
    action: str
    time: str
    duration: str | None = None


class CampaignStat(BaseModel):
    """Campaign statistics for dashboard."""

    id: str
    name: str
    type: str  # sms, voice, email
    progress: int
    sent: int
    total: int
    status: str


class AgentStat(BaseModel):
    """Agent statistics for dashboard."""

    id: str
    name: str
    calls: int
    messages: int
    success_rate: int


class TodayOverview(BaseModel):
    """Today's overview metrics."""

    completed: int
    pending: int
    failed: int


class AppointmentStats(BaseModel):
    """Appointment performance metrics for the dashboard."""

    appointments_today: int
    appointments_this_week: int
    show_up_rate_30d: float | None  # null when fewer than 5 completed+no_show in window
    no_shows_30d: int
    completed_30d: int


class RevenueAttributionStat(BaseModel):
    """Revenue attributed to a single AI agent, campaign, or prompt version."""

    id: str
    name: str
    won_value: float  # closed-won revenue traced to this attribution key
    pipeline_value: float  # open pipeline value traced to this attribution key
    won_count: int  # number of closed-won opportunities


class RevenueStats(BaseModel):
    """Dollar-denominated revenue/ROI ledger for the workspace.

    Traces closed-won opportunity revenue back to the AI touch chain (voice
    agent, prompt version, campaign) that booked the appointment behind the
    deal, alongside an ROI multiple versus estimated AI cost.
    """

    currency: str
    # Money rollups (all amounts in ``currency``)
    won_value: float  # all-time closed-won revenue
    won_value_this_month: float  # closed-won revenue this calendar month
    won_count: int
    pipeline_value: float  # sum of open opportunity amounts
    open_count: int
    lost_value: float
    lost_count: int
    # ROI inputs
    appointments_booked_this_month: int  # AI-attributed appointments this month
    estimated_ai_cost_this_month: float  # estimated AI spend this month
    roi_multiple: float | None  # won_value_this_month / cost; null when cost is 0
    # Attribution breakdowns (top contributors, sorted by won then pipeline)
    by_agent: list[RevenueAttributionStat]
    by_campaign: list[RevenueAttributionStat]
    by_prompt_version: list[RevenueAttributionStat]


class SpeedToLeadStats(BaseModel):
    """First-response (speed-to-lead) SLA performance for the dashboard."""

    window_days: int
    sla_seconds: int
    leads_measured: int
    within_sla: int
    pct_within_sla: float | None  # null when no leads measured in window
    avg_response_seconds: int | None
    median_response_seconds: int | None
    fastest_response_seconds: int | None


class ReviewsStats(BaseModel):
    """Reviews & reputation metrics for the dashboard."""

    average_rating: float  # mean star rating across collected reviews (0-5)
    total_reviews: int
    reputation_score: int  # 0-100, average rating dampened by volume
    new_count: int  # reviews awaiting operator triage
    public_reviews: int  # high ratings routed to public review sites
    private_feedback: int  # low ratings captured by the negative-feedback firewall
    requests_sent: int  # review-request SMS dispatched
    requests_rated: int  # review requests that received a rating
    response_rate: float  # requests_rated / requests_sent, as a percentage


class DealCoachDealStat(BaseModel):
    """One at-risk deal surfaced on the deal-coach dashboard card."""

    opportunity_id: str
    name: str
    deal_health: str  # healthy | watch | at_risk | critical
    top_risk: str  # the single highest-weighted risk factor
    amount_at_risk: float  # deal amount weighted by risk score
    currency: str


class DealCoachStats(BaseModel):
    """AI deal-coach pipeline-health metrics for the dashboard."""

    open_deals: int  # active open opportunities assessed
    at_risk_count: int  # deals in the at_risk bucket
    critical_count: int  # deals in the critical bucket
    watch_count: int  # deals in the watch bucket
    next_best_action_count: int  # deals with a recommended next-best action (watch+)
    total_amount_at_risk: float  # sum of risk-weighted deal amounts
    currency: str
    top_deals: list[DealCoachDealStat]  # most at-risk deals, highest risk first


class RoleplayStats(BaseModel):
    """Roleplay / practice-arena activity metrics for the dashboard."""

    total_runs: int  # all rehearsal runs
    runs_this_week: int  # rehearsal runs created in the last 7 days
    completed_runs: int  # runs that finished scoring
    avg_overall_score: float | None  # mean overall score of completed runs, null when none
    last_run_at: str | None  # relative time of the most recent run, null when none


class KnowledgeBaseStats(BaseModel):
    """Knowledge-base (CAG) usage metrics for the dashboard."""

    total_documents: int
    active_documents: int  # documents currently injectable into agent context
    total_chunks: int  # embedded + keyword-indexed slices
    total_tokens: int  # sum of token_count across active documents
    agents_with_knowledge: int  # distinct agents that have at least one document


class DashboardResponse(BaseModel):
    """Complete dashboard response."""

    stats: DashboardStats
    recent_activity: list[RecentActivity]
    campaign_stats: list[CampaignStat]
    agent_stats: list[AgentStat]
    today_overview: TodayOverview
    appointment_stats: AppointmentStats
    revenue_stats: RevenueStats
    speed_to_lead_stats: SpeedToLeadStats
    reviews_stats: ReviewsStats
    deal_coach_stats: DealCoachStats
    roleplay_stats: RoleplayStats
    knowledge_base_stats: KnowledgeBaseStats
    lead_source_roi_stats: LeadSourceROIStats = Field(default_factory=LeadSourceROIStats)
