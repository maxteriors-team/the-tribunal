"""Dashboard statistics schemas."""

from pydantic import BaseModel


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
