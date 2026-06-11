"""Today Queue — the ordered morning mission list for a workspace.

Composes existing organs (approvals, nudges, the ad-library machine, draft
campaigns, cold-start setup gaps) into one prioritized list so the daily loop
becomes: open the app → see today's ordered mission queue → approve → done.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment import Appointment, AppointmentStatus
from app.models.campaign import Campaign, CampaignContact, CampaignStatus
from app.models.contact import Contact
from app.models.conversation import Conversation, ConversationStatus
from app.models.human_nudge import HumanNudge
from app.models.offer import Offer
from app.models.outbound_mission import OutboundMission
from app.models.pending_action import PendingAction
from app.models.phone_number import PhoneNumber
from app.models.tag import ContactTag, Tag
from app.models.workspace import Workspace
from app.schemas.today_queue import TodayQueueItem, TodayQueueResponse
from app.services.ad_intelligence.monitors import AD_MONITOR_KEY, is_active_monitor
from app.workers.outbound_auto_draft_worker import AUTOPILOT_SETTINGS_KEY

logger = structlog.get_logger()

# Mission ordering: higher priority sorts first.
PRIORITY_REPLIES_WAITING = 110
PRIORITY_APPOINTMENTS_TODAY = 105
PRIORITY_APPROVALS = 100
PRIORITY_HOT_NUDGES = 90
PRIORITY_PROSPECT_BATCH = 80
PRIORITY_DRAFT_CAMPAIGN = 70
PRIORITY_SETUP_GAP = 60

_TOP_DESCRIPTIONS = 3
_MAX_DRAFT_CAMPAIGNS = 3
_PROSPECT_WINDOW_HOURS = 24

# Descriptive ad-signal tags surfaced on the prospect-batch card.
_SIGNAL_TAG_NAMES = ("ad-library", "stale-creative", "long-runner", "no-testing")

_NUDGE_PRIORITY_ORDER = case(
    (HumanNudge.priority == "high", 3),
    (HumanNudge.priority == "medium", 2),
    else_=1,
)


class TodayQueueService:
    """Builds the ordered mission queue for a workspace."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.log = logger.bind(component="today_queue_service")

    async def get_today_queue(self, workspace_id: uuid.UUID) -> TodayQueueResponse:
        """Return the ordered mission items for today."""
        now = datetime.now(UTC)
        items: list[TodayQueueItem] = []

        replies = await self._replies_waiting_item(workspace_id)
        if replies is not None:
            items.append(replies)

        appointments = await self._appointments_today_item(workspace_id, now)
        if appointments is not None:
            items.append(appointments)

        approvals = await self._approvals_item(workspace_id)
        if approvals is not None:
            items.append(approvals)

        nudges = await self._hot_nudges_item(workspace_id, now)
        if nudges is not None:
            items.append(nudges)

        batch = await self._prospect_batch_item(workspace_id, now)
        if batch is not None:
            items.append(batch)

        items.extend(await self._draft_campaign_items(workspace_id))
        items.extend(await self._setup_gap_items(workspace_id))

        items.sort(key=lambda item: item.priority, reverse=True)
        return TodayQueueResponse(items=items, generated_at=now)

    # ── replies waiting on a human ────────────────────────────────────

    async def _replies_waiting_item(self, workspace_id: uuid.UUID) -> TodayQueueItem | None:
        """Active conversations where the AI will not answer and the lead spoke last.

        Mirrors the responder gate (``not ai_enabled or ai_paused`` => the AI
        stays silent), so each row here is literal dead air until a human
        replies.
        """
        base_filter = (
            Conversation.workspace_id == workspace_id,
            Conversation.status == ConversationStatus.ACTIVE,
            Conversation.last_message_direction == "inbound",
            (Conversation.ai_paused.is_(True)) | (Conversation.ai_enabled.is_(False)),
        )

        count_result = await self.db.execute(
            select(func.count()).select_from(Conversation).where(*base_filter)
        )
        count = count_result.scalar() or 0
        if count == 0:
            return None

        top_result = await self.db.execute(
            select(
                Conversation.contact_id,
                Contact.first_name,
                Contact.last_name,
                Conversation.last_message_preview,
            )
            .join(Contact, Contact.id == Conversation.contact_id, isouter=True)
            .where(*base_filter)
            .order_by(Conversation.last_message_at.asc())
            .limit(_TOP_DESCRIPTIONS)
        )
        rows = top_result.all()
        names = [
            " ".join(part for part in (first, last) if part) or "Unknown contact"
            for _, first, last, _ in rows
        ]
        previews = [p for *_, p in rows if p]
        contact_ids = [cid for cid, *_ in rows if cid is not None]

        body_parts: list[str] = []
        if names:
            body_parts.append("Waiting on you: " + ", ".join(names))
        if previews:
            body_parts.append(_truncate(previews[0]))

        href = f"/contacts/{contact_ids[0]}" if count == 1 and contact_ids else "/contacts"
        return TodayQueueItem(
            id=f"replies_waiting:{workspace_id}",
            kind="replies_waiting",
            priority=PRIORITY_REPLIES_WAITING,
            title=f"{count} conversation{'s' if count != 1 else ''} waiting on a human reply",
            body=" • ".join(body_parts) or "The AI is paused and the lead spoke last.",
            count=count,
            cta_label="Reply now",
            href=href,
            payload={"contact_ids": contact_ids, "names": names},
        )

    # ── appointments today ────────────────────────────────────────────

    async def _appointments_today_item(
        self, workspace_id: uuid.UUID, now: datetime
    ) -> TodayQueueItem | None:
        end_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        base_filter = (
            Appointment.workspace_id == workspace_id,
            Appointment.status == AppointmentStatus.SCHEDULED,
            Appointment.scheduled_at >= now,
            Appointment.scheduled_at < end_of_today,
        )

        count_result = await self.db.execute(
            select(func.count()).select_from(Appointment).where(*base_filter)
        )
        count = count_result.scalar() or 0
        if count == 0:
            return None

        top_result = await self.db.execute(
            select(Appointment.scheduled_at, Contact.first_name, Contact.last_name)
            .join(Contact, Contact.id == Appointment.contact_id)
            .where(*base_filter)
            .order_by(Appointment.scheduled_at.asc())
            .limit(_TOP_DESCRIPTIONS)
        )
        slots = [
            f"{scheduled_at.strftime('%H:%M')} — "
            + (" ".join(part for part in (first, last) if part) or "Unknown contact")
            for scheduled_at, first, last in top_result.all()
        ]

        return TodayQueueItem(
            id=f"appointments_today:{workspace_id}",
            kind="appointments_today",
            priority=PRIORITY_APPOINTMENTS_TODAY,
            title=f"{count} appointment{'s' if count != 1 else ''} on the calendar today",
            body=" • ".join(slots) or "Booked calls still ahead today.",
            count=count,
            cta_label="See calendar",
            href="/calendar",
            payload={"slots": slots},
        )

    # ── approvals ─────────────────────────────────────────────────────

    async def _approvals_item(self, workspace_id: uuid.UUID) -> TodayQueueItem | None:
        count_result = await self.db.execute(
            select(func.count())
            .select_from(PendingAction)
            .where(
                PendingAction.workspace_id == workspace_id,
                PendingAction.status == "pending",
            )
        )
        count = count_result.scalar() or 0
        if count == 0:
            return None

        top_result = await self.db.execute(
            select(PendingAction.description)
            .where(
                PendingAction.workspace_id == workspace_id,
                PendingAction.status == "pending",
            )
            .order_by(PendingAction.created_at.desc())
            .limit(_TOP_DESCRIPTIONS)
        )
        descriptions = [row[0] for row in top_result.all()]

        return TodayQueueItem(
            id=f"approvals:{workspace_id}",
            kind="approvals",
            priority=PRIORITY_APPROVALS,
            title=f"{count} approval{'s' if count != 1 else ''} waiting",
            body=" • ".join(_truncate(d) for d in descriptions),
            count=count,
            cta_label="Review approvals",
            href="/pending-actions",
            payload={"descriptions": descriptions},
        )

    # ── hot nudges ────────────────────────────────────────────────────

    async def _hot_nudges_item(
        self, workspace_id: uuid.UUID, now: datetime
    ) -> TodayQueueItem | None:
        end_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        base_filter = (
            HumanNudge.workspace_id == workspace_id,
            HumanNudge.status == "pending",
            HumanNudge.due_date < end_of_today,
        )

        count_result = await self.db.execute(
            select(func.count()).select_from(HumanNudge).where(*base_filter)
        )
        count = count_result.scalar() or 0
        if count == 0:
            return None

        top_result = await self.db.execute(
            select(HumanNudge.title)
            .where(*base_filter)
            .order_by(_NUDGE_PRIORITY_ORDER.desc(), HumanNudge.due_date.asc())
            .limit(_TOP_DESCRIPTIONS)
        )
        titles = [row[0] for row in top_result.all()]

        return TodayQueueItem(
            id=f"hot_nudges:{workspace_id}",
            kind="hot_nudges",
            priority=PRIORITY_HOT_NUDGES,
            title=f"{count} nudge{'s' if count != 1 else ''} due today",
            body=" • ".join(_truncate(t) for t in titles),
            count=count,
            cta_label="Work the nudges",
            href="/nudges",
            payload={"titles": titles},
        )

    # ── fresh ad-library prospect batch ───────────────────────────────

    async def _prospect_batch_item(
        self, workspace_id: uuid.UUID, now: datetime
    ) -> TodayQueueItem | None:
        window_start = now - timedelta(hours=_PROSPECT_WINDOW_HOURS)
        base_filter = (
            Contact.workspace_id == workspace_id,
            Contact.source == "ad_library",
            Contact.created_at >= window_start,
        )

        count_result = await self.db.execute(
            select(func.count()).select_from(Contact).where(*base_filter)
        )
        count = count_result.scalar() or 0
        if count == 0:
            return None

        companies_result = await self.db.execute(
            select(Contact.company_name)
            .where(*base_filter, Contact.company_name.isnot(None))
            .order_by(Contact.lead_score.desc())
            .limit(_TOP_DESCRIPTIONS)
        )
        companies = [row[0] for row in companies_result.all()]

        tags_result = await self.db.execute(
            select(Tag.name)
            .distinct()
            .join(ContactTag, ContactTag.tag_id == Tag.id)
            .join(Contact, Contact.id == ContactTag.contact_id)
            .where(*base_filter, Tag.name.in_(_SIGNAL_TAG_NAMES))
        )
        signal_tags = sorted(row[0] for row in tags_result.all())

        body_parts: list[str] = []
        if companies:
            body_parts.append("Top companies: " + ", ".join(companies))
        if signal_tags:
            body_parts.append("Signals: " + ", ".join(signal_tags))

        return TodayQueueItem(
            id=f"prospect_batch:{workspace_id}",
            kind="prospect_batch",
            priority=PRIORITY_PROSPECT_BATCH,
            title=f"{count} fresh advertiser{'s' if count != 1 else ''} from the ad library",
            body=" • ".join(body_parts) or "New ad-library contacts ready to review.",
            count=count,
            cta_label="Review the batch",
            href="/find-leads/ad-library",
            payload={"companies": companies, "signal_tags": signal_tags},
        )

    # ── draft campaigns ───────────────────────────────────────────────

    async def _draft_campaign_items(self, workspace_id: uuid.UUID) -> list[TodayQueueItem]:
        result = await self.db.execute(
            select(Campaign, func.count(CampaignContact.id))
            .outerjoin(CampaignContact, CampaignContact.campaign_id == Campaign.id)
            .where(
                Campaign.workspace_id == workspace_id,
                Campaign.status == CampaignStatus.DRAFT,
            )
            .group_by(Campaign.id)
            .order_by(Campaign.updated_at.desc())
            .limit(_MAX_DRAFT_CAMPAIGNS)
        )

        items: list[TodayQueueItem] = []
        for campaign, enrolled in result.all():
            items.append(
                TodayQueueItem(
                    id=f"draft_campaign:{campaign.id}",
                    kind="draft_campaign",
                    priority=PRIORITY_DRAFT_CAMPAIGN,
                    title=f'Draft campaign "{campaign.name}" ready to launch',
                    body=(
                        f"{enrolled} contact{'s' if enrolled != 1 else ''} enrolled. "
                        "Review the copy and start it."
                    ),
                    count=int(enrolled),
                    cta_label="Review draft",
                    href=f"/campaigns/{campaign.id}",
                    payload={"campaign_id": str(campaign.id), "name": campaign.name},
                )
            )
        return items

    # ── setup gaps (cold-start guidance) ──────────────────────────────

    async def _setup_gap_items(self, workspace_id: uuid.UUID) -> list[TodayQueueItem]:
        items: list[TodayQueueItem] = []

        if not await self._has_active_monitor(workspace_id):
            items.append(
                _setup_gap(
                    workspace_id,
                    gap="monitor",
                    title="The scraper is off — set an ad monitor",
                    body=(
                        "No active ad-library monitor. Save a recurring search so fresh "
                        "advertisers land in your queue every morning."
                    ),
                    cta_label="Set up a monitor",
                    href="/find-leads/ad-library",
                )
            )

        active_offer = await self.db.execute(
            select(Offer.id)
            .where(Offer.workspace_id == workspace_id, Offer.is_active.is_(True))
            .limit(1)
        )
        if active_offer.scalar_one_or_none() is None:
            items.append(
                _setup_gap(
                    workspace_id,
                    gap="offer",
                    title="No active offer",
                    body="Outbound campaigns need an offer to promote. Create or activate one.",
                    cta_label="Create an offer",
                    href="/offers",
                )
            )

        if not await self._autopilot_enabled(workspace_id):
            items.append(
                _setup_gap(
                    workspace_id,
                    gap="autopilot",
                    title="Outbound autopilot is off",
                    body=(
                        "Fresh ad-library contacts won't become a drafted campaign "
                        "overnight. Turn on autopilot and pick a default offer."
                    ),
                    cta_label="Turn on autopilot",
                    href="/settings?tab=lead-sources",
                )
            )

        sms_number = await self.db.execute(
            select(PhoneNumber.id)
            .where(
                PhoneNumber.workspace_id == workspace_id,
                PhoneNumber.is_active.is_(True),
                PhoneNumber.sms_enabled.is_(True),
            )
            .limit(1)
        )
        if sms_number.scalar_one_or_none() is None:
            items.append(
                _setup_gap(
                    workspace_id,
                    gap="phone",
                    title="No SMS-enabled phone number",
                    body="You need an active SMS-enabled number before any campaign can send.",
                    cta_label="Add a number",
                    href="/phone-numbers",
                )
            )

        return items

    async def _autopilot_enabled(self, workspace_id: uuid.UUID) -> bool:
        result = await self.db.execute(
            select(Workspace.settings).where(Workspace.id == workspace_id)
        )
        settings = result.scalar_one_or_none() or {}
        autopilot = settings.get(AUTOPILOT_SETTINGS_KEY, {})
        return isinstance(autopilot, dict) and bool(autopilot.get("enabled", False))

    async def _has_active_monitor(self, workspace_id: uuid.UUID) -> bool:
        result = await self.db.execute(
            select(OutboundMission).where(
                OutboundMission.workspace_id == workspace_id,
                OutboundMission.discovery_config[AD_MONITOR_KEY].isnot(None),
            )
        )
        return any(is_active_monitor(m) for m in result.scalars().all())


def _setup_gap(
    workspace_id: uuid.UUID,
    *,
    gap: str,
    title: str,
    body: str,
    cta_label: str,
    href: str,
) -> TodayQueueItem:
    return TodayQueueItem(
        id=f"setup_gap:{gap}:{workspace_id}",
        kind="setup_gap",
        priority=PRIORITY_SETUP_GAP,
        title=title,
        body=body,
        count=1,
        cta_label=cta_label,
        href=href,
        payload={"gap": gap},
    )


def _truncate(text: str, limit: int = 120) -> str:
    cleaned = " ".join(text.split())
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1] + "…"
