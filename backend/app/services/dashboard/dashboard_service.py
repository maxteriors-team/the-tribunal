"""Dashboard statistics service."""

import json
import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.db.redis import get_redis
from app.models.agent import Agent
from app.models.appointment import Appointment
from app.models.campaign import Campaign
from app.models.contact import Contact
from app.models.conversation import Conversation, Message
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_document import KnowledgeDocument
from app.models.opportunity import Opportunity
from app.models.prompt_version import PromptVersion
from app.models.roleplay import RehearsalRun, RehearsalStatus
from app.models.workspace import Workspace
from app.schemas.dashboard import (
    AgentStat,
    AppointmentStats,
    CampaignStat,
    DashboardResponse,
    DashboardStats,
    DealCoachDealStat,
    DealCoachStats,
    KnowledgeBaseStats,
    RecentActivity,
    RevenueAttributionStat,
    RevenueStats,
    ReviewsStats,
    RoleplayStats,
    SpeedToLeadStats,
    TodayOverview,
)
from app.schemas.lead_source import LeadSourceROIStats
from app.services.dashboard.lead_source_roi_service import compute_lead_source_roi
from app.services.opportunities.deal_coach_service import _days_since, assess_risk
from app.services.reviews.review_service import ReviewService
from app.services.sla.speed_to_lead import (
    compute_sla_metrics,
    get_speed_to_lead_settings,
)

logger = structlog.get_logger()

CACHE_TTL = 300  # 5 minutes

# Max contributors returned in each revenue attribution breakdown.
REVENUE_BREAKDOWN_LIMIT = 8


def _format_time_ago(dt: datetime) -> str:
    """Format a datetime as a relative time string."""
    now = datetime.now(UTC)
    diff = now - dt
    if diff.total_seconds() < 60:
        return "just now"
    if diff.total_seconds() < 3600:
        minutes = int(diff.total_seconds() / 60)
        return f"{minutes} min ago"
    if diff.total_seconds() < 86400:
        hours = int(diff.total_seconds() / 3600)
        return f"{hours} hour{'s' if hours > 1 else ''} ago"
    days = int(diff.total_seconds() / 86400)
    return f"{days} day{'s' if days > 1 else ''} ago"


def _get_initials(name: str) -> str:
    """Get initials from a name."""
    parts = name.split()
    if len(parts) >= 2:
        return f"{parts[0][0]}{parts[1][0]}".upper()
    if parts:
        return parts[0][:2].upper()
    return "??"


def _calculate_change(current: int, previous: int) -> str:
    """Calculate percentage change between two values."""
    if previous > 0:
        change_pct = int(((current - previous) / previous) * 100)
        return f"{'+' if change_pct >= 0 else ''}{change_pct}%"
    return f"+{current}" if current > 0 else "0"


def _get_message_action(msg: Message) -> tuple[str, str | None]:
    """Get action description and duration for a message."""
    if msg.channel == "voice":
        if msg.direction == "inbound":
            action = "incoming call"
        else:
            action = "completed call" if msg.status == "completed" else "placed call"
        duration = (
            f"{msg.duration_seconds // 60}:{msg.duration_seconds % 60:02d}"
            if msg.duration_seconds
            else None
        )
    else:
        if msg.direction == "inbound":
            action = "replied to SMS"
        else:
            action = "sent SMS" if msg.is_ai else "received SMS"
        duration = None
    return action, duration


class DashboardService:
    """Service for computing and caching dashboard statistics."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.log = logger.bind(component="dashboard_service")

    async def get_core_stats(self, workspace: Workspace) -> DashboardStats:
        """Get core dashboard statistics."""
        now = datetime.now(UTC)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_start = today_start - timedelta(days=1)
        week_ago = now - timedelta(days=7)
        two_weeks_ago = now - timedelta(days=14)

        total_contacts_result = await self.db.execute(
            select(func.count()).select_from(Contact).where(Contact.workspace_id == workspace.id)
        )
        total_contacts = total_contacts_result.scalar() or 0

        contacts_last_week_result = await self.db.execute(
            select(func.count())
            .select_from(Contact)
            .where(
                Contact.workspace_id == workspace.id,
                Contact.created_at < week_ago,
                Contact.created_at >= two_weeks_ago,
            )
        )
        contacts_last_week = contacts_last_week_result.scalar() or 0

        contacts_this_week_result = await self.db.execute(
            select(func.count())
            .select_from(Contact)
            .where(
                Contact.workspace_id == workspace.id,
                Contact.created_at >= week_ago,
            )
        )
        contacts_this_week = contacts_this_week_result.scalar() or 0

        active_campaigns_result = await self.db.execute(
            select(func.count())
            .select_from(Campaign)
            .where(
                Campaign.workspace_id == workspace.id,
                Campaign.status.in_(["running", "scheduled"]),
            )
        )
        active_campaigns = active_campaigns_result.scalar() or 0

        campaigns_this_week_result = await self.db.execute(
            select(func.count())
            .select_from(Campaign)
            .where(
                Campaign.workspace_id == workspace.id,
                Campaign.created_at >= week_ago,
            )
        )
        campaigns_this_week = campaigns_this_week_result.scalar() or 0

        campaigns_last_week_result = await self.db.execute(
            select(func.count())
            .select_from(Campaign)
            .where(
                Campaign.workspace_id == workspace.id,
                Campaign.created_at < week_ago,
                Campaign.created_at >= two_weeks_ago,
            )
        )
        campaigns_last_week = campaigns_last_week_result.scalar() or 0

        campaigns_diff = campaigns_this_week - campaigns_last_week
        campaigns_change = f"{'+' if campaigns_diff >= 0 else ''}{campaigns_diff}"

        workspace_conversations = (
            select(Conversation.id).where(Conversation.workspace_id == workspace.id).subquery()
        )

        calls_today_result = await self.db.execute(
            select(func.count())
            .select_from(Message)
            .where(
                Message.conversation_id.in_(select(workspace_conversations)),
                Message.channel == "voice",
                Message.created_at >= today_start,
            )
        )
        calls_today = calls_today_result.scalar() or 0

        calls_yesterday_result = await self.db.execute(
            select(func.count())
            .select_from(Message)
            .where(
                Message.conversation_id.in_(select(workspace_conversations)),
                Message.channel == "voice",
                Message.created_at >= yesterday_start,
                Message.created_at < today_start,
            )
        )
        calls_yesterday = calls_yesterday_result.scalar() or 0

        messages_sent_result = await self.db.execute(
            select(func.count())
            .select_from(Message)
            .where(
                Message.conversation_id.in_(select(workspace_conversations)),
                Message.channel == "sms",
                Message.direction == "outbound",
            )
        )
        messages_sent = messages_sent_result.scalar() or 0

        messages_this_week_result = await self.db.execute(
            select(func.count())
            .select_from(Message)
            .where(
                Message.conversation_id.in_(select(workspace_conversations)),
                Message.channel == "sms",
                Message.direction == "outbound",
                Message.created_at >= week_ago,
            )
        )
        messages_this_week = messages_this_week_result.scalar() or 0

        messages_last_week_result = await self.db.execute(
            select(func.count())
            .select_from(Message)
            .where(
                Message.conversation_id.in_(select(workspace_conversations)),
                Message.channel == "sms",
                Message.direction == "outbound",
                Message.created_at < week_ago,
                Message.created_at >= two_weeks_ago,
            )
        )
        messages_last_week = messages_last_week_result.scalar() or 0

        return DashboardStats(
            total_contacts=total_contacts,
            active_campaigns=active_campaigns,
            calls_today=calls_today,
            messages_sent=messages_sent,
            contacts_change=_calculate_change(contacts_this_week, contacts_last_week),
            campaigns_change=campaigns_change,
            calls_change=_calculate_change(calls_today, calls_yesterday),
            messages_change=_calculate_change(messages_this_week, messages_last_week),
        )

    async def get_recent_activity(self, workspace: Workspace) -> list[RecentActivity]:
        """Get recent activity feed."""
        recent_messages_result = await self.db.execute(
            select(Message, Conversation)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(Conversation.workspace_id == workspace.id)
            .order_by(Message.created_at.desc())
            .limit(10)
        )
        recent_messages = recent_messages_result.all()

        contact_ids = {conv.contact_id for _, conv in recent_messages if conv.contact_id}
        contact_names: dict[int, str] = {}
        if contact_ids:
            contacts_result = await self.db.execute(
                select(Contact).where(Contact.id.in_(contact_ids))
            )
            for contact in contacts_result.scalars():
                contact_names[contact.id] = contact.full_name

        recent_activity: list[RecentActivity] = []
        for msg, conv in recent_messages:
            contact_name = (
                contact_names.get(conv.contact_id, "Unknown") if conv.contact_id else "Unknown"
            )
            action, duration = _get_message_action(msg)
            recent_activity.append(
                RecentActivity(
                    id=str(msg.id),
                    type="call" if msg.channel == "voice" else "sms",
                    contact=contact_name,
                    initials=_get_initials(contact_name),
                    action=action,
                    time=_format_time_ago(msg.created_at),
                    duration=duration,
                )
            )

        return recent_activity

    async def get_campaign_stats(self, workspace: Workspace) -> list[CampaignStat]:
        """Get active campaign statistics."""
        active_campaigns_result = await self.db.execute(
            select(Campaign)
            .where(
                Campaign.workspace_id == workspace.id,
                Campaign.status.in_(["running", "scheduled", "paused"]),
            )
            .order_by(Campaign.updated_at.desc())
            .limit(5)
        )
        campaigns = active_campaigns_result.scalars().all()

        campaign_stats: list[CampaignStat] = []
        for campaign in campaigns:
            total = campaign.total_contacts or 1
            sent = campaign.messages_sent
            progress = min(100, int((sent / total) * 100)) if total > 0 else 0
            campaign_stats.append(
                CampaignStat(
                    id=str(campaign.id),
                    name=campaign.name,
                    type="sms",
                    progress=progress,
                    sent=sent,
                    total=campaign.total_contacts,
                    status=campaign.status,
                )
            )

        return campaign_stats

    async def get_agent_stats(self, workspace: Workspace) -> list[AgentStat]:
        """Get agent performance statistics."""
        agents_result = await self.db.execute(
            select(Agent)
            .where(
                Agent.workspace_id == workspace.id,
                Agent.is_active.is_(True),
            )
            .order_by(Agent.total_calls.desc())
            .limit(5)
        )
        agents = agents_result.scalars().all()

        agent_stats: list[AgentStat] = []
        for agent in agents:
            total_interactions = agent.total_calls + agent.total_messages
            success_rate = 90 if total_interactions > 0 else 0
            agent_stats.append(
                AgentStat(
                    id=str(agent.id),
                    name=agent.name,
                    calls=agent.total_calls,
                    messages=agent.total_messages,
                    success_rate=success_rate,
                )
            )

        return agent_stats

    async def get_today_overview(self, workspace: Workspace) -> TodayOverview:
        """Get today's overview metrics."""
        now = datetime.now(UTC)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        workspace_conversations = (
            select(Conversation.id).where(Conversation.workspace_id == workspace.id).subquery()
        )

        completed_result = await self.db.execute(
            select(func.count())
            .select_from(Message)
            .where(
                Message.conversation_id.in_(select(workspace_conversations)),
                Message.created_at >= today_start,
                Message.status.in_(["delivered", "completed", "sent"]),
            )
        )
        completed = completed_result.scalar() or 0

        pending_result = await self.db.execute(
            select(func.count())
            .select_from(Message)
            .where(
                Message.conversation_id.in_(select(workspace_conversations)),
                Message.created_at >= today_start,
                Message.status.in_(["queued", "sending"]),
            )
        )
        pending = pending_result.scalar() or 0

        failed_result = await self.db.execute(
            select(func.count())
            .select_from(Message)
            .where(
                Message.conversation_id.in_(select(workspace_conversations)),
                Message.created_at >= today_start,
                Message.status == "failed",
            )
        )
        failed = failed_result.scalar() or 0

        return TodayOverview(
            completed=completed,
            pending=pending,
            failed=failed,
        )

    async def get_appointment_stats(self, workspace: Workspace) -> AppointmentStats:
        """Get appointment performance metrics."""
        now = datetime.now(UTC)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        week_end = now + timedelta(days=7)
        thirty_days_ago = now - timedelta(days=30)

        today_result = await self.db.execute(
            select(func.count())
            .select_from(Appointment)
            .where(
                Appointment.workspace_id == workspace.id,
                Appointment.scheduled_at >= today_start,
                Appointment.scheduled_at < today_end,
                Appointment.status == "scheduled",
            )
        )
        appointments_today = today_result.scalar() or 0

        week_result = await self.db.execute(
            select(func.count())
            .select_from(Appointment)
            .where(
                Appointment.workspace_id == workspace.id,
                Appointment.scheduled_at >= now,
                Appointment.scheduled_at < week_end,
                Appointment.status == "scheduled",
            )
        )
        appointments_this_week = week_result.scalar() or 0

        completed_result = await self.db.execute(
            select(func.count())
            .select_from(Appointment)
            .where(
                Appointment.workspace_id == workspace.id,
                Appointment.scheduled_at >= thirty_days_ago,
                Appointment.status == "completed",
            )
        )
        completed_30d = completed_result.scalar() or 0

        no_shows_result = await self.db.execute(
            select(func.count())
            .select_from(Appointment)
            .where(
                Appointment.workspace_id == workspace.id,
                Appointment.scheduled_at >= thirty_days_ago,
                Appointment.status == "no_show",
            )
        )
        no_shows_30d = no_shows_result.scalar() or 0

        total_outcomes = completed_30d + no_shows_30d
        show_up_rate_30d: float | None = None
        if total_outcomes >= 5:
            show_up_rate_30d = round(completed_30d / total_outcomes * 100, 1)

        return AppointmentStats(
            appointments_today=appointments_today,
            appointments_this_week=appointments_this_week,
            show_up_rate_30d=show_up_rate_30d,
            no_shows_30d=no_shows_30d,
            completed_30d=completed_30d,
        )

    async def get_revenue_stats(self, workspace: Workspace) -> RevenueStats:
        """Compute the dollar-denominated revenue/ROI ledger.

        Aggregates ``opportunity.amount`` by status and traces closed-won /
        open pipeline back to the AI touch chain (voice agent, prompt version,
        campaign) that booked the appointment behind the deal. Pairs the result
        with an estimated AI cost to produce an ROI multiple.
        """
        settings = get_settings()
        now = datetime.now(UTC)
        month_start = now.replace(hour=0, minute=0, second=0, microsecond=0, day=1)

        # --- Status rollup: sum(amount) + count grouped by status -----------
        rollup_result = await self.db.execute(
            select(
                Opportunity.status,
                func.count(),
                func.coalesce(func.sum(Opportunity.amount), 0),
            )
            .where(Opportunity.workspace_id == workspace.id)
            .group_by(Opportunity.status)
        )
        won_value = 0.0
        won_count = 0
        pipeline_value = 0.0
        open_count = 0
        lost_value = 0.0
        lost_count = 0
        for status, count, amount in rollup_result.all():
            amount_f = float(amount or 0)
            if status == "won":
                won_value = amount_f
                won_count = count
            elif status == "open":
                pipeline_value = amount_f
                open_count = count
            elif status == "lost":
                lost_value = amount_f
                lost_count = count

        # --- Closed-won revenue this calendar month -------------------------
        won_month_result = await self.db.execute(
            select(func.coalesce(func.sum(Opportunity.amount), 0)).where(
                Opportunity.workspace_id == workspace.id,
                Opportunity.status == "won",
                Opportunity.closed_date >= month_start.date(),
            )
        )
        won_value_this_month = float(won_month_result.scalar() or 0)

        by_agent, by_campaign, by_prompt_version = await self._get_revenue_attribution(workspace)

        # --- Estimated AI cost this month -----------------------------------
        workspace_conversations = (
            select(Conversation.id).where(Conversation.workspace_id == workspace.id).subquery()
        )
        ai_calls_result = await self.db.execute(
            select(func.count())
            .select_from(Message)
            .where(
                Message.conversation_id.in_(select(workspace_conversations)),
                Message.channel == "voice",
                Message.is_ai.is_(True),
                Message.created_at >= month_start,
            )
        )
        ai_calls = ai_calls_result.scalar() or 0

        ai_sms_result = await self.db.execute(
            select(func.count())
            .select_from(Message)
            .where(
                Message.conversation_id.in_(select(workspace_conversations)),
                Message.channel == "sms",
                Message.direction == "outbound",
                Message.is_ai.is_(True),
                Message.created_at >= month_start,
            )
        )
        ai_sms = ai_sms_result.scalar() or 0

        estimated_ai_cost = round(
            ai_calls * settings.ai_cost_per_call_usd + ai_sms * settings.ai_cost_per_sms_usd, 2
        )
        roi_multiple: float | None = None
        if estimated_ai_cost > 0:
            roi_multiple = round(won_value_this_month / estimated_ai_cost, 1)

        # --- AI-attributed appointments booked this month -------------------
        appts_booked_result = await self.db.execute(
            select(func.count())
            .select_from(Appointment)
            .where(
                Appointment.workspace_id == workspace.id,
                Appointment.agent_id.isnot(None),
                Appointment.created_at >= month_start,
            )
        )
        appointments_booked_this_month = appts_booked_result.scalar() or 0

        return RevenueStats(
            currency="USD",
            won_value=round(won_value, 2),
            won_value_this_month=round(won_value_this_month, 2),
            won_count=won_count,
            pipeline_value=round(pipeline_value, 2),
            open_count=open_count,
            lost_value=round(lost_value, 2),
            lost_count=lost_count,
            appointments_booked_this_month=appointments_booked_this_month,
            estimated_ai_cost_this_month=estimated_ai_cost,
            roi_multiple=roi_multiple,
            by_agent=by_agent,
            by_campaign=by_campaign,
            by_prompt_version=by_prompt_version,
        )

    async def _get_revenue_attribution(
        self, workspace: Workspace
    ) -> tuple[
        list[RevenueAttributionStat],
        list[RevenueAttributionStat],
        list[RevenueAttributionStat],
    ]:
        """Trace open/won opportunity revenue to its first AI touch.

        Returns ``(by_agent, by_campaign, by_prompt_version)``. An opportunity
        is attributed to the agent/campaign/prompt version of the earliest
        AI-booked appointment for its primary contact; ranking to a single
        appointment per contact avoids double-counting amounts.
        """
        appt_ranked = (
            select(
                Appointment.contact_id.label("contact_id"),
                Appointment.agent_id.label("agent_id"),
                Appointment.campaign_id.label("campaign_id"),
                Message.prompt_version_id.label("prompt_version_id"),
                func.row_number()
                .over(
                    partition_by=Appointment.contact_id,
                    order_by=Appointment.scheduled_at.asc(),
                )
                .label("rn"),
            )
            .select_from(Appointment)
            .outerjoin(Message, Message.id == Appointment.message_id)
            .where(
                Appointment.workspace_id == workspace.id,
                Appointment.agent_id.isnot(None),
            )
            .subquery()
        )
        first_touch = (
            select(
                appt_ranked.c.contact_id,
                appt_ranked.c.agent_id,
                appt_ranked.c.campaign_id,
                appt_ranked.c.prompt_version_id,
            )
            .where(appt_ranked.c.rn == 1)
            .subquery()
        )
        attribution_result = await self.db.execute(
            select(
                first_touch.c.agent_id,
                first_touch.c.campaign_id,
                first_touch.c.prompt_version_id,
                Opportunity.status,
                Opportunity.amount,
            )
            .select_from(Opportunity)
            .join(first_touch, first_touch.c.contact_id == Opportunity.primary_contact_id)
            .where(
                Opportunity.workspace_id == workspace.id,
                Opportunity.primary_contact_id.isnot(None),
                Opportunity.status.in_(["open", "won"]),
            )
        )

        agent_acc: dict[str, dict[str, float]] = {}
        campaign_acc: dict[str, dict[str, float]] = {}
        prompt_acc: dict[str, dict[str, float]] = {}

        def _accumulate(
            acc: dict[str, dict[str, float]], key: object, status: str, amount: float
        ) -> None:
            if key is None:
                return
            bucket = acc.setdefault(str(key), {"won": 0.0, "pipeline": 0.0, "won_count": 0.0})
            if status == "won":
                bucket["won"] += amount
                bucket["won_count"] += 1
            elif status == "open":
                bucket["pipeline"] += amount

        for agent_id, campaign_id, prompt_version_id, status, amount in attribution_result.all():
            amount_f = float(amount or 0)
            _accumulate(agent_acc, agent_id, status, amount_f)
            _accumulate(campaign_acc, campaign_id, status, amount_f)
            _accumulate(prompt_acc, prompt_version_id, status, amount_f)

        # --- Resolve display names for the attribution keys -----------------
        agent_names: dict[str, str] = {}
        if agent_acc:
            agent_rows = await self.db.execute(
                select(Agent.id, Agent.name).where(Agent.id.in_([uuid.UUID(k) for k in agent_acc]))
            )
            agent_names = {str(aid): name for aid, name in agent_rows.all()}

        campaign_names: dict[str, str] = {}
        if campaign_acc:
            campaign_rows = await self.db.execute(
                select(Campaign.id, Campaign.name).where(
                    Campaign.id.in_([uuid.UUID(k) for k in campaign_acc])
                )
            )
            campaign_names = {str(cid): name for cid, name in campaign_rows.all()}

        prompt_names: dict[str, str] = {}
        if prompt_acc:
            prompt_rows = await self.db.execute(
                select(PromptVersion.id, PromptVersion.version_number, Agent.name)
                .join(Agent, Agent.id == PromptVersion.agent_id)
                .where(PromptVersion.id.in_([uuid.UUID(k) for k in prompt_acc]))
            )
            prompt_names = {
                str(pid): f"{name} v{version}" for pid, version, name in prompt_rows.all()
            }

        def _build(
            acc: dict[str, dict[str, float]], names: dict[str, str], fallback: str
        ) -> list[RevenueAttributionStat]:
            rows = [
                RevenueAttributionStat(
                    id=key,
                    name=names.get(key, fallback),
                    won_value=round(bucket["won"], 2),
                    pipeline_value=round(bucket["pipeline"], 2),
                    won_count=int(bucket["won_count"]),
                )
                for key, bucket in acc.items()
            ]
            rows.sort(key=lambda r: (r.won_value, r.pipeline_value), reverse=True)
            return rows[:REVENUE_BREAKDOWN_LIMIT]

        by_agent = _build(agent_acc, agent_names, "Unknown agent")
        by_campaign = _build(campaign_acc, campaign_names, "Unknown campaign")
        by_prompt_version = _build(prompt_acc, prompt_names, "Unknown prompt")

        return by_agent, by_campaign, by_prompt_version

    async def get_speed_to_lead_stats(self, workspace: Workspace) -> SpeedToLeadStats:
        """Compute first-response SLA performance over the configured window."""
        config = get_speed_to_lead_settings(workspace)
        metrics = await compute_sla_metrics(
            self.db,
            workspace.id,
            sla_seconds=config.sla_seconds,
            window_days=config.badge_window_days,
        )
        return SpeedToLeadStats(
            window_days=metrics.window_days,
            sla_seconds=metrics.sla_seconds,
            leads_measured=metrics.leads_measured,
            within_sla=metrics.within_sla,
            pct_within_sla=metrics.pct_within_sla,
            avg_response_seconds=metrics.avg_response_seconds,
            median_response_seconds=metrics.median_response_seconds,
            fastest_response_seconds=metrics.fastest_response_seconds,
        )

    async def get_reviews_stats(self, workspace: Workspace) -> ReviewsStats:
        """Get reviews & reputation metrics for the dashboard."""
        summary = await ReviewService(self.db).get_summary(workspace.id)
        return ReviewsStats(
            average_rating=summary.average_rating,
            total_reviews=summary.total_reviews,
            reputation_score=summary.reputation_score,
            new_count=summary.new_count,
            public_reviews=summary.public_reviews,
            private_feedback=summary.private_feedback,
            requests_sent=summary.requests_sent,
            requests_rated=summary.requests_rated,
            response_rate=summary.response_rate,
        )

    async def get_deal_coach_stats(self, workspace: Workspace) -> DealCoachStats:
        """Assess open-deal health and surface the most at-risk deals.

        Reuses the canonical deterministic ``assess_risk`` heuristic so the
        dashboard buckets match the deal-coach list view exactly. A deal earns
        a recommended next-best action once it crosses the ``watch`` threshold.
        """
        now = datetime.now(UTC)
        result = await self.db.execute(
            select(Opportunity)
            .where(
                Opportunity.workspace_id == workspace.id,
                Opportunity.status == "open",
                Opportunity.is_active.is_(True),
            )
            .options(
                selectinload(Opportunity.stage),
                selectinload(Opportunity.primary_contact),
            )
        )
        opportunities = result.scalars().unique().all()

        at_risk_count = 0
        critical_count = 0
        watch_count = 0
        total_amount_at_risk = 0.0
        currency = "USD"
        scored: list[tuple[int, float, DealCoachDealStat]] = []
        for opp in opportunities:
            contact = opp.primary_contact
            days_since = _days_since(contact.last_engaged_at if contact else None, now=now)
            days_in_stage = _days_since(opp.stage_changed_at, now=now)
            overdue = bool(
                opp.expected_close_date is not None and opp.expected_close_date < now.date()
            )
            assessment = assess_risk(
                days_since_last_contact=days_since,
                days_in_stage=days_in_stage,
                engagement_score=contact.engagement_score if contact else 0,
                lead_score=contact.lead_score if contact else 0,
                last_sentiment=None,
                awaiting_reply=False,
                objections=[],
                expected_close_overdue=overdue,
            )
            if assessment.health == "critical":
                critical_count += 1
            elif assessment.health == "at_risk":
                at_risk_count += 1
            elif assessment.health == "watch":
                watch_count += 1

            amount = float(opp.amount) if opp.amount is not None else None
            amount_at_risk = (amount or 0.0) * (assessment.risk_score / 100.0)
            if assessment.health in ("watch", "at_risk", "critical"):
                total_amount_at_risk += amount_at_risk
                currency = opp.currency or currency
                scored.append(
                    (
                        assessment.risk_score,
                        amount or 0.0,
                        DealCoachDealStat(
                            opportunity_id=str(opp.id),
                            name=opp.name,
                            deal_health=assessment.health,
                            top_risk=assessment.top_risk,
                            amount_at_risk=round(amount_at_risk, 2),
                            currency=opp.currency or "USD",
                        ),
                    )
                )

        scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
        top_deals = [row[2] for row in scored[:5]]
        next_best_action_count = watch_count + at_risk_count + critical_count

        return DealCoachStats(
            open_deals=len(opportunities),
            at_risk_count=at_risk_count,
            critical_count=critical_count,
            watch_count=watch_count,
            next_best_action_count=next_best_action_count,
            total_amount_at_risk=round(total_amount_at_risk, 2),
            currency=currency,
            top_deals=top_deals,
        )

    async def get_roleplay_stats(self, workspace: Workspace) -> RoleplayStats:
        """Get roleplay / practice-arena activity metrics for the dashboard."""
        week_ago = datetime.now(UTC) - timedelta(days=7)

        agg_result = await self.db.execute(
            select(
                func.count(),
                func.count().filter(RehearsalRun.created_at >= week_ago),
                func.count().filter(RehearsalRun.status == RehearsalStatus.COMPLETED.value),
                func.avg(RehearsalRun.overall_score).filter(RehearsalRun.overall_score.isnot(None)),
                func.max(RehearsalRun.created_at),
            ).where(RehearsalRun.workspace_id == workspace.id)
        )
        total_runs, runs_this_week, completed_runs, avg_score, last_run = agg_result.one()

        return RoleplayStats(
            total_runs=int(total_runs or 0),
            runs_this_week=int(runs_this_week or 0),
            completed_runs=int(completed_runs or 0),
            avg_overall_score=round(float(avg_score), 1) if avg_score is not None else None,
            last_run_at=_format_time_ago(last_run) if last_run is not None else None,
        )

    async def get_knowledge_base_stats(self, workspace: Workspace) -> KnowledgeBaseStats:
        """Get knowledge-base (CAG) usage metrics for the dashboard."""
        doc_result = await self.db.execute(
            select(
                func.count(),
                func.count().filter(KnowledgeDocument.is_active.is_(True)),
                func.coalesce(
                    func.sum(KnowledgeDocument.token_count).filter(
                        KnowledgeDocument.is_active.is_(True)
                    ),
                    0,
                ),
                func.count(func.distinct(KnowledgeDocument.agent_id)),
            ).where(KnowledgeDocument.workspace_id == workspace.id)
        )
        total_documents, active_documents, total_tokens, agents_with_knowledge = doc_result.one()

        chunks_result = await self.db.execute(
            select(func.count())
            .select_from(KnowledgeChunk)
            .where(KnowledgeChunk.workspace_id == workspace.id)
        )
        total_chunks = chunks_result.scalar() or 0

        return KnowledgeBaseStats(
            total_documents=int(total_documents or 0),
            active_documents=int(active_documents or 0),
            total_chunks=int(total_chunks),
            total_tokens=int(total_tokens or 0),
            agents_with_knowledge=int(agents_with_knowledge or 0),
        )

    async def get_lead_source_roi_stats(self, workspace: Workspace) -> LeadSourceROIStats:
        """Rank acquisition channels by ad spend and closed-won jobs."""
        return await compute_lead_source_roi(self.db, workspace.id)

    async def get_full_dashboard(self, workspace: Workspace) -> DashboardResponse:
        """Get full dashboard data with Redis caching (5-minute TTL)."""
        cache_key = f"dashboard:stats:{workspace.id}"

        try:
            redis = await get_redis()
            cached_data = await redis.get(cache_key)
            if cached_data:
                self.log.debug("cache_hit", workspace_id=workspace.id)
                return DashboardResponse(**json.loads(cached_data))
        except Exception as e:
            self.log.warning("cache_read_failed", workspace_id=workspace.id, error=e)

        self.log.debug("cache_miss", workspace_id=workspace.id)

        stats = await self.get_core_stats(workspace)
        recent_activity = await self.get_recent_activity(workspace)
        campaign_stats = await self.get_campaign_stats(workspace)
        agent_stats = await self.get_agent_stats(workspace)
        today_overview = await self.get_today_overview(workspace)
        appointment_stats = await self.get_appointment_stats(workspace)
        revenue_stats = await self.get_revenue_stats(workspace)
        speed_to_lead_stats = await self.get_speed_to_lead_stats(workspace)
        reviews_stats = await self.get_reviews_stats(workspace)
        deal_coach_stats = await self.get_deal_coach_stats(workspace)
        roleplay_stats = await self.get_roleplay_stats(workspace)
        knowledge_base_stats = await self.get_knowledge_base_stats(workspace)
        lead_source_roi_stats = await self.get_lead_source_roi_stats(workspace)

        response = DashboardResponse(
            stats=stats,
            recent_activity=recent_activity,
            campaign_stats=campaign_stats,
            agent_stats=agent_stats,
            today_overview=today_overview,
            appointment_stats=appointment_stats,
            revenue_stats=revenue_stats,
            speed_to_lead_stats=speed_to_lead_stats,
            reviews_stats=reviews_stats,
            deal_coach_stats=deal_coach_stats,
            roleplay_stats=roleplay_stats,
            knowledge_base_stats=knowledge_base_stats,
            lead_source_roi_stats=lead_source_roi_stats,
        )

        try:
            redis = await get_redis()
            await redis.setex(
                cache_key,
                CACHE_TTL,
                json.dumps(response.model_dump(mode="json")),
            )
            self.log.debug("cached", workspace_id=workspace.id, ttl=CACHE_TTL)
        except Exception as e:
            self.log.warning("cache_write_failed", workspace_id=workspace.id, error=e)

        return response
