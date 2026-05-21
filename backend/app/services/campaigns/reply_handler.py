"""Classify inbound replies to outbound campaigns and trigger follow-up actions."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.campaign import Campaign, CampaignContact, CampaignContactStatus
from app.models.contact import Contact
from app.models.conversation import Conversation, Message
from app.models.drip_campaign import ResponseCategory
from app.models.opportunity import Opportunity, OpportunityActivity
from app.models.opt_out import GlobalOptOut
from app.models.pending_action import PendingAction
from app.models.pipeline import Pipeline, PipelineStage
from app.services.ai.openai_credentials import get_openai_bearer_token
from app.services.push_notifications import push_notification_service
from app.services.reactivation.response_classifier import classify_response

logger = structlog.get_logger()

_WARM_REPLY_CATEGORIES = frozenset(
    {
        ResponseCategory.INTERESTED,
        ResponseCategory.QUESTION,
        ResponseCategory.OBJECTION,
        ResponseCategory.BOOKED,
        ResponseCategory.HUMAN_NEEDED,
    }
)
_HIGH_RISK_CATEGORIES = frozenset(
    {
        ResponseCategory.OPT_OUT,
        ResponseCategory.WRONG_PERSON,
        ResponseCategory.ANGRY,
        ResponseCategory.HUMAN_NEEDED,
    }
)
_OPPORTUNITY_CATEGORIES = frozenset(
    {
        ResponseCategory.INTERESTED,
        ResponseCategory.QUESTION,
        ResponseCategory.OBJECTION,
        ResponseCategory.BOOKED,
    }
)
_CANCEL_CATEGORIES = frozenset(
    {
        ResponseCategory.OPT_OUT,
        ResponseCategory.WRONG_PERSON,
        ResponseCategory.ANGRY,
    }
)


@dataclass(frozen=True, slots=True)
class CampaignReplyHandlingResult:
    """Outcome of campaign reply handling."""

    campaign_contact_id: uuid.UUID
    campaign_id: uuid.UUID
    category: ResponseCategory
    handoff_created: bool
    opportunity_id: uuid.UUID | None


async def handle_campaign_reply(
    db: AsyncSession,
    *,
    message: Message,
    log: structlog.BoundLogger | None = None,
) -> CampaignReplyHandlingResult | None:
    """Classify and apply campaign-specific side effects for an inbound reply."""
    active_log = log or logger.bind(service="campaign_reply_handler")
    campaign_contact = await _get_campaign_contact(db, message.conversation_id)
    if campaign_contact is None or campaign_contact.campaign is None:
        active_log.debug("not_a_campaign_reply", conversation_id=str(message.conversation_id))
        return None

    campaign = campaign_contact.campaign
    if (
        campaign_contact.last_reply_at is not None
        and campaign_contact.last_reply_at >= message.created_at
        and campaign_contact.messages_received > 0
    ):
        active_log.info(
            "campaign_reply_duplicate_skipped",
            campaign_id=str(campaign.id),
            campaign_contact_id=str(campaign_contact.id),
            message_id=str(message.id),
        )
        return None

    conversation = await db.get(Conversation, message.conversation_id)
    context = await _load_conversation_context(db, message.conversation_id)
    category = await classify_response(
        message.body,
        conversation_context=context,
        openai_api_key=get_openai_bearer_token() or None,
    )

    now = datetime.now(UTC)
    _update_campaign_contact(campaign_contact, campaign, category, now)
    if conversation is not None:
        _update_conversation(conversation, campaign, category)

    opportunity = await _upsert_opportunity(db, campaign_contact, category, message, now)
    await _record_opt_out(db, campaign_contact, category, message, conversation, now)
    handoff_created = await _create_handoff_if_needed(
        db,
        campaign_contact=campaign_contact,
        campaign=campaign,
        category=category,
        message=message,
        conversation=conversation,
        opportunity=opportunity,
    )

    await db.commit()

    if handoff_created:
        await _notify_handoff(db, campaign, campaign_contact, category, message, conversation)

    active_log.info(
        "campaign_reply_classified",
        campaign_id=str(campaign.id),
        campaign_contact_id=str(campaign_contact.id),
        category=category.value,
        handoff_created=handoff_created,
        opportunity_id=str(opportunity.id) if opportunity else None,
    )
    return CampaignReplyHandlingResult(
        campaign_contact_id=campaign_contact.id,
        campaign_id=campaign.id,
        category=category,
        handoff_created=handoff_created,
        opportunity_id=opportunity.id if opportunity else None,
    )


async def _get_campaign_contact(
    db: AsyncSession,
    conversation_id: uuid.UUID,
) -> CampaignContact | None:
    result = await db.execute(
        select(CampaignContact)
        .options(
            selectinload(CampaignContact.campaign),
            selectinload(CampaignContact.contact),
        )
        .where(CampaignContact.conversation_id == conversation_id)
    )
    return result.scalar_one_or_none()


async def _load_conversation_context(
    db: AsyncSession,
    conversation_id: uuid.UUID,
) -> list[dict[str, str]]:
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(8)
    )
    messages = list(reversed(result.scalars().all()))
    return [
        {
            "role": "assistant" if message.direction == "outbound" else "user",
            "content": message.body,
        }
        for message in messages
    ]


def _update_campaign_contact(
    campaign_contact: CampaignContact,
    campaign: Campaign,
    category: ResponseCategory,
    now: datetime,
) -> None:
    campaign.replies_received += 1
    campaign_contact.messages_received += 1
    campaign_contact.last_reply_at = now
    campaign_contact.next_follow_up_at = None

    if category in _CANCEL_CATEGORIES:
        campaign_contact.status = CampaignContactStatus.OPTED_OUT
        campaign_contact.opted_out = True
        campaign_contact.opted_out_at = now
        campaign.contacts_opted_out += 1
    elif category in {ResponseCategory.INTERESTED, ResponseCategory.BOOKED}:
        campaign_contact.status = CampaignContactStatus.QUALIFIED
        campaign_contact.is_qualified = True
        campaign_contact.qualified_at = now
        campaign_contact.qualification_notes = f"Inbound reply classified as {category.value}."
        campaign.contacts_qualified += 1
    else:
        campaign_contact.status = CampaignContactStatus.REPLIED

    if category == ResponseCategory.BOOKED:
        campaign.appointments_booked += 1


def _update_conversation(
    conversation: Conversation,
    campaign: Campaign,
    category: ResponseCategory,
) -> None:
    if campaign.agent_id and conversation.assigned_agent_id != campaign.agent_id:
        conversation.assigned_agent_id = campaign.agent_id

    if category in _HIGH_RISK_CATEGORIES:
        conversation.ai_paused = True
    elif campaign.ai_enabled:
        conversation.ai_enabled = True


async def _upsert_opportunity(
    db: AsyncSession,
    campaign_contact: CampaignContact,
    category: ResponseCategory,
    message: Message,
    now: datetime,
) -> Opportunity | None:
    if category not in _OPPORTUNITY_CATEGORIES:
        return None

    existing_result = await db.execute(
        select(Opportunity)
        .where(Opportunity.workspace_id == campaign_contact.campaign.workspace_id)
        .where(Opportunity.primary_contact_id == campaign_contact.contact_id)
        .where(Opportunity.source == "campaign")
        .where(Opportunity.status == "open")
        .order_by(Opportunity.created_at.desc())
        .limit(1)
    )
    opportunity = existing_result.scalar_one_or_none()
    stage = await _get_or_create_stage(db, campaign_contact.campaign.workspace_id, category)

    if opportunity is None:
        contact_name = _contact_name(campaign_contact.contact)
        opportunity = Opportunity(
            workspace_id=campaign_contact.campaign.workspace_id,
            pipeline_id=stage.pipeline_id,
            stage_id=stage.id,
            primary_contact_id=campaign_contact.contact_id,
            name=f"{contact_name} - {campaign_contact.campaign.name}",
            description=f"Inbound campaign reply: {message.body[:500]}",
            probability=stage.probability,
            source="campaign",
            stage_changed_at=now,
        )
        if campaign_contact.contact is not None:
            opportunity.contacts.append(campaign_contact.contact)
        db.add(opportunity)
        await db.flush()
    elif opportunity.stage_id != stage.id:
        old_stage_id = opportunity.stage_id
        opportunity.pipeline_id = stage.pipeline_id
        opportunity.stage_id = stage.id
        opportunity.probability = stage.probability
        opportunity.stage_changed_at = now
        db.add(
            OpportunityActivity(
                opportunity_id=opportunity.id,
                activity_type="campaign_reply_classified",
                old_value=str(old_stage_id) if old_stage_id else None,
                new_value=stage.name,
                description=f"Campaign reply classified as {category.value}.",
            )
        )

    return opportunity


async def _get_or_create_stage(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    category: ResponseCategory,
) -> PipelineStage:
    pipeline_result = await db.execute(
        select(Pipeline)
        .where(Pipeline.workspace_id == workspace_id)
        .where(Pipeline.is_active)
        .order_by(Pipeline.created_at.asc())
        .limit(1)
    )
    pipeline = pipeline_result.scalar_one_or_none()
    if pipeline is None:
        pipeline = Pipeline(
            workspace_id=workspace_id,
            name="Sales Pipeline",
            description="Default pipeline for campaign replies.",
        )
        db.add(pipeline)
        await db.flush()

    stage_name = "Booked" if category == ResponseCategory.BOOKED else "Qualified"
    stage_result = await db.execute(
        select(PipelineStage)
        .where(PipelineStage.pipeline_id == pipeline.id)
        .where(PipelineStage.name == stage_name)
        .limit(1)
    )
    stage = stage_result.scalar_one_or_none()
    if stage is not None:
        return stage

    stage = PipelineStage(
        pipeline_id=pipeline.id,
        name=stage_name,
        order=2 if category == ResponseCategory.BOOKED else 1,
        probability=80 if category == ResponseCategory.BOOKED else 25,
        stage_type="active",
    )
    db.add(stage)
    await db.flush()
    return stage


async def _record_opt_out(
    db: AsyncSession,
    campaign_contact: CampaignContact,
    category: ResponseCategory,
    message: Message,
    conversation: Conversation | None,
    now: datetime,
) -> None:
    if category != ResponseCategory.OPT_OUT or conversation is None:
        return

    existing_result = await db.execute(
        select(GlobalOptOut)
        .where(GlobalOptOut.workspace_id == campaign_contact.campaign.workspace_id)
        .where(GlobalOptOut.phone_number == conversation.contact_phone)
    )
    if existing_result.scalar_one_or_none() is not None:
        return

    db.add(
        GlobalOptOut(
            workspace_id=campaign_contact.campaign.workspace_id,
            phone_number=conversation.contact_phone,
            opted_out_at=now,
            opt_out_keyword=message.body[:50],
            source_campaign_id=campaign_contact.campaign_id,
            source_message_id=message.id,
        )
    )


async def _create_handoff_if_needed(
    db: AsyncSession,
    *,
    campaign_contact: CampaignContact,
    campaign: Campaign,
    category: ResponseCategory,
    message: Message,
    conversation: Conversation | None,
    opportunity: Opportunity | None,
) -> bool:
    if category not in _WARM_REPLY_CATEGORIES and category not in _HIGH_RISK_CATEGORIES:
        return False

    existing_result = await db.execute(
        select(PendingAction)
        .where(PendingAction.workspace_id == campaign.workspace_id)
        .where(PendingAction.action_type == "campaign_reply_handoff")
        .where(PendingAction.status == "pending")
        .where(PendingAction.context["message_id"].as_string() == str(message.id))
        .limit(1)
    )
    if existing_result.scalar_one_or_none() is not None:
        return False

    urgency = "high" if category in _HIGH_RISK_CATEGORIES else "normal"
    db.add(
        PendingAction(
            workspace_id=campaign.workspace_id,
            agent_id=campaign.agent_id,
            action_type="campaign_reply_handoff",
            action_payload={
                "category": category.value,
                "reply_text": message.body,
                "recommended_action": _recommended_action(category),
            },
            description=_handoff_description(campaign_contact, campaign, category),
            context={
                "source": "campaign_reply_classifier",
                "campaign_id": str(campaign.id),
                "campaign_contact_id": str(campaign_contact.id),
                "conversation_id": str(conversation.id) if conversation else None,
                "contact_id": campaign_contact.contact_id,
                "message_id": str(message.id),
                "opportunity_id": str(opportunity.id) if opportunity else None,
                "category": category.value,
            },
            urgency=urgency,
        )
    )
    return True


async def _notify_handoff(
    db: AsyncSession,
    campaign: Campaign,
    campaign_contact: CampaignContact,
    category: ResponseCategory,
    message: Message,
    conversation: Conversation | None,
) -> None:
    try:
        await push_notification_service.send_to_workspace_members(
            db=db,
            workspace_id=str(campaign.workspace_id),
            title="Campaign reply needs review",
            body=f"{_contact_name(campaign_contact.contact)} replied: {message.body[:100]}",
            data={
                "type": "campaign_reply_handoff",
                "category": category.value,
                "campaignId": str(campaign.id),
                "conversationId": str(conversation.id) if conversation else None,
                "screen": (
                    f"/(tabs)/messages/{conversation.id}" if conversation else "/pending-actions"
                ),
            },
            notification_type="message",
            channel_id="messages",
        )
    except Exception:
        logger.exception(
            "campaign_reply_handoff_notification_failed",
            campaign_id=str(campaign.id),
            campaign_contact_id=str(campaign_contact.id),
        )


def _contact_name(contact: Contact | None) -> str:
    if contact is None:
        return "Contact"
    return contact.full_name


def _recommended_action(category: ResponseCategory) -> str:
    return {
        ResponseCategory.INTERESTED: "Reply quickly and qualify the lead.",
        ResponseCategory.QUESTION: "Answer the question and invite the next step.",
        ResponseCategory.OBJECTION: "Review the objection before sending a tailored response.",
        ResponseCategory.NOT_NOW: "Pause follow-up and set a future nurture reminder.",
        ResponseCategory.WRONG_PERSON: (
            "Verify the contact record and suppress future outreach if needed."
        ),
        ResponseCategory.OPT_OUT: "Confirm opt-out compliance and avoid further outreach.",
        ResponseCategory.ANGRY: "Human review required before any further contact.",
        ResponseCategory.BOOKED: "Confirm appointment details and update the pipeline.",
        ResponseCategory.HUMAN_NEEDED: "Human review required before automation continues.",
    }.get(category, "Review the reply before continuing automation.")


def _handoff_description(
    campaign_contact: CampaignContact,
    campaign: Campaign,
    category: ResponseCategory,
) -> str:
    return (
        f"{_contact_name(campaign_contact.contact)} replied to campaign "
        f"{campaign.name} and was classified as {category.value}."
    )
