"""Dashboard statistics service."""

import json
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.redis import get_redis
from app.models.agent import Agent
from app.models.appointment import Appointment
from app.models.campaign import Campaign
from app.models.contact import Contact
from app.models.conversation import Conversation, Message
from app.models.workspace import Workspace
from app.schemas.dashboard import (
    AgentStat,
    AppointmentStats,
    CampaignStat,
    DashboardResponse,
    DashboardStats,
    RecentActivity,
    TodayOverview,
)

logger = structlog.get_logger()

CACHE_TTL = 300  # 5 minutes


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

        response = DashboardResponse(
            stats=stats,
            recent_activity=recent_activity,
            campaign_stats=campaign_stats,
            agent_stats=agent_stats,
            today_overview=today_overview,
            appointment_stats=appointment_stats,
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
