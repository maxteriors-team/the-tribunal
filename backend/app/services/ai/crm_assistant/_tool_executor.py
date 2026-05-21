"""CRM tool executor — runs database-backed operations on behalf of the assistant."""

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.appointment import Appointment
from app.models.campaign import Campaign, CampaignContact
from app.models.contact import Contact
from app.models.conversation import Conversation, Message
from app.models.offer import Offer
from app.models.opportunity import Opportunity
from app.schemas.agent import AgentCreate, AgentUpdate
from app.schemas.offer import OfferCreate, OfferUpdate
from app.services.approval.approval_gate_service import approval_gate_service
from app.services.campaigns.campaign_lifecycle import (
    CampaignLifecycleError,
    count_campaign_contacts,
    get_campaign_for_workspace,
    pause_campaign,
    resume_campaign,
    start_campaign,
    summarize_campaign,
)
from app.services.outbound.growth_workflow import OutboundGrowthWorkflowService

_APPROVAL_GATED_TOOLS = {
    "send_sms",
    "send_initial_message",
    "start_campaign",
    "resume_campaign",
    "create_agent",
    "update_agent",
    "assign_ai_responder",
}


class CRMToolExecutor:
    """Execute CRM tool calls on behalf of the assistant."""

    def __init__(self, db: AsyncSession, workspace_id: uuid.UUID, user_id: int) -> None:
        self.db = db
        self.workspace_id = workspace_id
        self.user_id = user_id
        self.log = structlog.get_logger(service="crm_tool_executor")

    @staticmethod
    def _is_explicitly_confirmed(args: dict[str, Any]) -> bool:
        return bool(args.get("confirmed") or args.get("user_confirmed"))

    async def _queue_pending_action(
        self,
        function_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        payload = {
            key: value
            for key, value in arguments.items()
            if key not in {"confirmed", "user_confirmed"}
        }
        decision, metadata = await approval_gate_service.check_and_execute_or_queue(
            db=self.db,
            agent_id=None,
            workspace_id=self.workspace_id,
            action_type=f"crm_assistant.{function_name}",
            action_payload=payload,
            description=self._describe_pending_action(function_name, payload),
            context={"source": "crm_assistant", "user_id": self.user_id},
            urgency=(
                "high"
                if function_name
                in {"send_sms", "send_initial_message", "start_campaign", "resume_campaign"}
                else "normal"
            ),
            require_approval_without_agent=True,
        )
        if decision != "pending" or metadata is None:
            return {"success": False, "error": "Approval gate did not create a pending action"}
        return {
            "success": False,
            "pending_approval": True,
            "pending_action_id": metadata["action_id"],
            "message": "Approval required before I can run this outbound CRM action.",
        }

    @staticmethod
    def _describe_pending_action(function_name: str, payload: dict[str, Any]) -> str:
        descriptions = {
            "send_sms": f"Send SMS to contact {payload.get('contact_id')}",
            "send_initial_message": (
                f"Send initial message for campaign {payload.get('campaign_id')} "
                f"to contact {payload.get('contact_id')}"
            ),
            "start_campaign": f"Start campaign {payload.get('campaign_id')}",
            "resume_campaign": f"Resume campaign {payload.get('campaign_id')}",
            "create_agent": f"Create AI agent {payload.get('name', '(unnamed)')}",
            "update_agent": f"Update AI agent {payload.get('agent_id')}",
            "assign_ai_responder": (
                f"Assign AI responder {payload.get('agent_id')} "
                f"to conversation {payload.get('conversation_id')}"
            ),
        }
        return descriptions.get(function_name, f"Run {function_name}")

    async def execute(self, function_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a tool call to the appropriate handler."""
        handlers: dict[str, Any] = {
            "search_contacts": self._search_contacts,
            "create_contact": self._create_contact,
            "list_campaigns": self._list_campaigns,
            "list_agents": self._list_agents,
            "send_sms": self._send_sms,
            "send_initial_message": self._send_initial_message,
            "start_campaign": self._start_campaign,
            "pause_campaign": self._pause_campaign,
            "resume_campaign": self._resume_campaign,
            "summarize_campaign": self._summarize_campaign,
            "create_agent": self._create_agent,
            "update_agent": self._update_agent,
            "assign_ai_responder": self._assign_ai_responder,
            "get_conversation": self._get_conversation,
            "list_recent_conversations": self._list_recent_conversations,
            "list_appointments": self._list_appointments,
            "get_dashboard_stats": self._get_dashboard_stats,
            "list_opportunities": self._list_opportunities,
            "list_offers": self._list_offers,
            "get_offer_details": self._get_offer_details,
            "create_offer_draft": self._create_offer_draft,
            "update_offer_draft": self._update_offer_draft,
            "plan_outbound_growth_workflow": self._plan_outbound_growth_workflow,
        }
        handler = handlers.get(function_name)
        if not handler:
            return {"success": False, "error": f"Unknown function: {function_name}"}
        try:
            if function_name in _APPROVAL_GATED_TOOLS and not self._is_explicitly_confirmed(
                arguments
            ):
                return await self._queue_pending_action(function_name, arguments)
            return await handler(arguments)  # type: ignore[no-any-return]
        except Exception:
            self.log.exception("tool_execution_failed", function_name=function_name)
            return {"success": False, "error": f"Failed to execute {function_name}"}

    # ── Handlers ────────────────────────────────────────────────────────

    @staticmethod
    def _serialize_offer_summary(offer: Offer) -> dict[str, Any]:
        return {
            "id": str(offer.id),
            "name": offer.name,
            "description": offer.description,
            "discount_type": offer.discount_type,
            "discount_value": offer.discount_value,
            "is_active": offer.is_active,
            "headline": offer.headline,
            "offer_price": offer.offer_price,
            "cta_text": offer.cta_text,
            "valid_until": offer.valid_until.isoformat() if offer.valid_until else None,
        }

    @staticmethod
    def _serialize_offer_details(offer: Offer) -> dict[str, Any]:
        return {
            **CRMToolExecutor._serialize_offer_summary(offer),
            "terms": offer.terms,
            "valid_from": offer.valid_from.isoformat() if offer.valid_from else None,
            "subheadline": offer.subheadline,
            "regular_price": offer.regular_price,
            "savings_amount": offer.savings_amount,
            "guarantee_type": offer.guarantee_type,
            "guarantee_days": offer.guarantee_days,
            "guarantee_text": offer.guarantee_text,
            "urgency_type": offer.urgency_type,
            "urgency_text": offer.urgency_text,
            "scarcity_count": offer.scarcity_count,
            "value_stack_items": offer.value_stack_items or [],
            "cta_subtext": offer.cta_subtext,
            "is_public": offer.is_public,
            "public_slug": offer.public_slug,
            "require_email": offer.require_email,
            "require_phone": offer.require_phone,
            "require_name": offer.require_name,
            "page_views": offer.page_views,
            "opt_ins": offer.opt_ins,
            "created_at": offer.created_at.isoformat() if offer.created_at else None,
            "updated_at": offer.updated_at.isoformat() if offer.updated_at else None,
        }

    @staticmethod
    def _parse_uuid(raw_value: Any) -> uuid.UUID | None:
        try:
            return uuid.UUID(str(raw_value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_offer_id(raw_offer_id: Any) -> uuid.UUID | None:
        return CRMToolExecutor._parse_uuid(raw_offer_id)

    @staticmethod
    def _without_confirmation(args: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value for key, value in args.items() if key not in {"confirmed", "user_confirmed"}
        }

    @staticmethod
    def _serialize_agent(agent: Agent) -> dict[str, Any]:
        return {
            "id": str(agent.id),
            "name": agent.name,
            "description": agent.description,
            "channel_mode": agent.channel_mode,
            "voice_provider": agent.voice_provider,
            "voice_id": agent.voice_id,
            "language": agent.language,
            "system_prompt": agent.system_prompt,
            "temperature": agent.temperature,
            "is_active": agent.is_active,
        }

    async def _get_offer_for_workspace(self, offer_id: uuid.UUID) -> Offer | None:
        result = await self.db.execute(
            select(Offer).where(
                Offer.id == offer_id,
                Offer.workspace_id == self.workspace_id,
            )
        )
        return result.scalar_one_or_none()

    async def _get_campaign_for_workspace(self, campaign_id: uuid.UUID) -> Campaign | None:
        return await get_campaign_for_workspace(self.db, campaign_id, self.workspace_id)

    async def _get_agent_for_workspace(self, agent_id: uuid.UUID) -> Agent | None:
        result = await self.db.execute(
            select(Agent).where(
                Agent.id == agent_id,
                Agent.workspace_id == self.workspace_id,
            )
        )
        return result.scalar_one_or_none()

    async def _get_conversation_for_workspace(
        self,
        conversation_id: uuid.UUID,
    ) -> Conversation | None:
        result = await self.db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.workspace_id == self.workspace_id,
            )
        )
        return result.scalar_one_or_none()

    async def _search_contacts(self, args: dict[str, Any]) -> dict[str, Any]:
        query = args["query"]
        limit = min(args.get("limit", 10), 50)
        pattern = f"%{query}%"

        stmt = (
            select(Contact)
            .where(Contact.workspace_id == self.workspace_id)
            .where(
                (Contact.first_name.ilike(pattern))
                | (Contact.last_name.ilike(pattern))
                | (Contact.email.ilike(pattern))
                | (Contact.phone_number.ilike(pattern))
                | (Contact.company_name.ilike(pattern))
            )
            .order_by(Contact.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        contacts = result.scalars().all()

        return {
            "success": True,
            "data": [
                {
                    "id": c.id,
                    "first_name": c.first_name,
                    "last_name": c.last_name,
                    "phone": c.phone_number,
                    "email": c.email,
                    "status": c.status,
                    "company": c.company_name,
                }
                for c in contacts
            ],
            "count": len(contacts),
        }

    async def _create_contact(self, args: dict[str, Any]) -> dict[str, Any]:
        phone = args["phone"]
        # Check for duplicate
        existing = await self.db.execute(
            select(Contact).where(
                Contact.workspace_id == self.workspace_id,
                Contact.phone_number == phone,
            )
        )
        if existing.scalar_one_or_none():
            return {"success": False, "error": "Contact with this phone already exists"}

        contact = Contact(
            workspace_id=self.workspace_id,
            first_name=args["first_name"],
            last_name=args.get("last_name"),
            phone_number=phone,
            email=args.get("email"),
            notes=args.get("notes"),
        )
        self.db.add(contact)
        await self.db.flush()

        return {
            "success": True,
            "data": {
                "id": contact.id,
                "first_name": contact.first_name,
                "last_name": contact.last_name,
                "phone": contact.phone_number,
            },
        }

    async def _list_campaigns(self, args: dict[str, Any]) -> dict[str, Any]:
        limit = min(args.get("limit", 10), 50)
        stmt = (
            select(Campaign)
            .where(Campaign.workspace_id == self.workspace_id)
            .order_by(Campaign.created_at.desc())
            .limit(limit)
        )
        if args.get("status"):
            stmt = stmt.where(Campaign.status == args["status"])

        result = await self.db.execute(stmt)
        campaigns = result.scalars().all()

        return {
            "success": True,
            "data": [
                {
                    "id": str(c.id),
                    "name": c.name,
                    "status": c.status,
                    "type": c.campaign_type,
                }
                for c in campaigns
            ],
            "count": len(campaigns),
        }

    async def _list_agents(self, args: dict[str, Any]) -> dict[str, Any]:
        limit = min(args.get("limit", 10), 50)
        stmt = (
            select(Agent)
            .where(Agent.workspace_id == self.workspace_id)
            .order_by(Agent.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        agents = result.scalars().all()

        return {
            "success": True,
            "data": [
                {
                    "id": str(a.id),
                    "name": a.name,
                    "channel_mode": a.channel_mode,
                    "is_active": a.is_active,
                }
                for a in agents
            ],
            "count": len(agents),
        }

    async def _send_sms(self, args: dict[str, Any]) -> dict[str, Any]:
        from app.core.config import settings
        from app.services.telephony.telnyx import TelnyxSMSService

        contact_id = args["contact_id"]
        body = args["body"]

        # Look up contact
        result = await self.db.execute(
            select(Contact).where(
                Contact.id == contact_id,
                Contact.workspace_id == self.workspace_id,
            )
        )
        contact = result.scalar_one_or_none()
        if not contact:
            return {"success": False, "error": "Contact not found"}

        # Get a workspace phone number to send from
        from app.models.phone_number import PhoneNumber

        phone_result = await self.db.execute(
            select(PhoneNumber).where(PhoneNumber.workspace_id == self.workspace_id).limit(1)
        )
        phone = phone_result.scalar_one_or_none()
        if not phone:
            return {"success": False, "error": "No phone number available in workspace"}

        telnyx_key = settings.telnyx_api_key
        if not telnyx_key:
            return {"success": False, "error": "SMS not configured"}

        sms_service = TelnyxSMSService(telnyx_key)
        try:
            await sms_service.send_message(
                to_number=contact.phone_number,
                from_number=phone.phone_number,
                body=body,
                db=self.db,
                workspace_id=self.workspace_id,
            )
        finally:
            await sms_service.close()

        return {"success": True, "message": f"SMS sent to {contact.first_name}"}

    async def _send_initial_message(self, args: dict[str, Any]) -> dict[str, Any]:
        campaign_id = self._parse_uuid(args.get("campaign_id"))
        if campaign_id is None:
            return {"success": False, "error": "Invalid campaign_id"}
        contact_id = args.get("contact_id")
        if contact_id is None:
            return {"success": False, "error": "contact_id is required"}

        campaign = await self._get_campaign_for_workspace(campaign_id)
        if campaign is None:
            return {"success": False, "error": "Campaign not found"}
        if not campaign.initial_message:
            return {"success": False, "error": "Campaign has no initial message"}

        return await self._send_sms(
            {"contact_id": contact_id, "body": campaign.initial_message, "confirmed": True}
        )

    async def _start_campaign(self, args: dict[str, Any]) -> dict[str, Any]:
        campaign_id = self._parse_uuid(args.get("campaign_id"))
        if campaign_id is None:
            return {"success": False, "error": "Invalid campaign_id"}

        campaign = await self._get_campaign_for_workspace(campaign_id)
        if campaign is None:
            return {"success": False, "error": "Campaign not found"}

        try:
            lifecycle_result = await start_campaign(self.db, campaign)
        except CampaignLifecycleError as exc:
            return {"success": False, "error": str(exc)}

        await self.db.flush()
        return {
            "success": True,
            "message": lifecycle_result.message,
            "data": {
                "campaign_id": str(campaign.id),
                "status": lifecycle_result.status.value,
                "contact_count": lifecycle_result.contact_count,
            },
        }

    async def _pause_campaign(self, args: dict[str, Any]) -> dict[str, Any]:
        campaign_id = self._parse_uuid(args.get("campaign_id"))
        if campaign_id is None:
            return {"success": False, "error": "Invalid campaign_id"}

        campaign = await self._get_campaign_for_workspace(campaign_id)
        if campaign is None:
            return {"success": False, "error": "Campaign not found"}

        try:
            lifecycle_result = await pause_campaign(campaign)
        except CampaignLifecycleError as exc:
            return {"success": False, "error": str(exc)}

        await self.db.flush()
        return {
            "success": True,
            "message": lifecycle_result.message,
            "data": {"campaign_id": str(campaign.id), "status": lifecycle_result.status.value},
        }

    async def _resume_campaign(self, args: dict[str, Any]) -> dict[str, Any]:
        campaign_id = self._parse_uuid(args.get("campaign_id"))
        if campaign_id is None:
            return {"success": False, "error": "Invalid campaign_id"}

        campaign = await self._get_campaign_for_workspace(campaign_id)
        if campaign is None:
            return {"success": False, "error": "Campaign not found"}

        try:
            lifecycle_result = await resume_campaign(self.db, campaign)
        except CampaignLifecycleError as exc:
            return {"success": False, "error": str(exc)}

        await self.db.flush()
        return {
            "success": True,
            "message": lifecycle_result.message,
            "data": {
                "campaign_id": str(campaign.id),
                "status": lifecycle_result.status.value,
                "contact_count": lifecycle_result.contact_count,
            },
        }

    async def _summarize_campaign(self, args: dict[str, Any]) -> dict[str, Any]:
        campaign_id = self._parse_uuid(args.get("campaign_id"))
        if campaign_id is None:
            return {"success": False, "error": "Invalid campaign_id"}

        campaign = await self._get_campaign_for_workspace(campaign_id)
        if campaign is None:
            return {"success": False, "error": "Campaign not found"}

        summary = summarize_campaign(campaign)
        total_contacts = await count_campaign_contacts(self.db, campaign_id)
        status_result = await self.db.execute(
            select(CampaignContact.status, func.count(CampaignContact.id))
            .where(CampaignContact.campaign_id == campaign_id)
            .group_by(CampaignContact.status)
        )
        status_counts = {
            (status.value if hasattr(status, "value") else str(status)): count
            for status, count in status_result.all()
        }
        summary["enrolled_contacts"] = total_contacts
        summary["contact_status_counts"] = status_counts
        return {"success": True, "data": summary}

    async def _plan_outbound_growth_workflow(self, args: dict[str, Any]) -> dict[str, Any]:
        service = OutboundGrowthWorkflowService(db=self.db, workspace_id=self.workspace_id)
        return await service.plan(args)

    async def _create_agent(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            agent_in = AgentCreate(**self._without_confirmation(args))
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

        agent = Agent(workspace_id=self.workspace_id, **agent_in.model_dump())
        self.db.add(agent)
        await self.db.flush()
        return {"success": True, "data": self._serialize_agent(agent)}

    async def _update_agent(self, args: dict[str, Any]) -> dict[str, Any]:
        agent_id = self._parse_uuid(args.get("agent_id"))
        if agent_id is None:
            return {"success": False, "error": "Invalid agent_id"}

        agent = await self._get_agent_for_workspace(agent_id)
        if agent is None:
            return {"success": False, "error": "Agent not found"}

        update_args = {
            key: value
            for key, value in self._without_confirmation(args).items()
            if key != "agent_id"
        }
        try:
            agent_in = AgentUpdate(**update_args)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

        update_data = agent_in.model_dump(exclude_unset=True)
        if not update_data:
            return {"success": False, "error": "No agent fields provided"}
        for field, value in update_data.items():
            setattr(agent, field, value)
        await self.db.flush()
        return {"success": True, "data": self._serialize_agent(agent)}

    async def _assign_ai_responder(self, args: dict[str, Any]) -> dict[str, Any]:
        conversation_id = self._parse_uuid(args.get("conversation_id"))
        agent_id = self._parse_uuid(args.get("agent_id"))
        if conversation_id is None:
            return {"success": False, "error": "Invalid conversation_id"}
        if agent_id is None:
            return {"success": False, "error": "Invalid agent_id"}

        conversation = await self._get_conversation_for_workspace(conversation_id)
        if conversation is None:
            return {"success": False, "error": "Conversation not found"}
        agent = await self._get_agent_for_workspace(agent_id)
        if agent is None:
            return {"success": False, "error": "Agent not found"}

        conversation.assigned_agent_id = agent.id
        conversation.ai_enabled = args.get("ai_enabled", True)
        conversation.ai_paused = False
        conversation.ai_paused_until = None
        await self.db.flush()
        return {
            "success": True,
            "message": f"Assigned {agent.name} as AI responder",
            "data": {"conversation_id": str(conversation.id), "agent_id": str(agent.id)},
        }

    async def _get_conversation(self, args: dict[str, Any]) -> dict[str, Any]:
        contact_id = args["contact_id"]
        limit = min(args.get("limit", 20), 100)

        # Find conversation with this contact
        conv_result = await self.db.execute(
            select(Conversation)
            .where(
                Conversation.workspace_id == self.workspace_id,
                Conversation.contact_id == contact_id,
            )
            .order_by(Conversation.last_message_at.desc())
            .limit(1)
        )
        conversation = conv_result.scalar_one_or_none()
        if not conversation:
            return {"success": True, "data": [], "count": 0}

        msg_result = await self.db.execute(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        messages = msg_result.scalars().all()

        return {
            "success": True,
            "data": [
                {
                    "direction": m.direction,
                    "body": m.body,
                    "channel": m.channel,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
                for m in reversed(messages)
            ],
            "count": len(messages),
        }

    async def _list_recent_conversations(self, args: dict[str, Any]) -> dict[str, Any]:
        limit = min(args.get("limit", 10), 50)
        stmt = (
            select(Conversation)
            .where(Conversation.workspace_id == self.workspace_id)
            .order_by(Conversation.last_message_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        conversations = result.scalars().all()

        return {
            "success": True,
            "data": [
                {
                    "id": str(c.id),
                    "contact_phone": c.contact_phone,
                    "last_message": c.last_message_preview,
                    "last_message_at": c.last_message_at.isoformat() if c.last_message_at else None,
                    "unread_count": c.unread_count,
                }
                for c in conversations
            ],
            "count": len(conversations),
        }

    async def _list_appointments(self, args: dict[str, Any]) -> dict[str, Any]:
        limit = min(args.get("limit", 10), 50)
        stmt = (
            select(Appointment)
            .where(
                Appointment.workspace_id == self.workspace_id,
                Appointment.scheduled_at >= datetime.now(UTC),
            )
            .order_by(Appointment.scheduled_at)
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        appointments = result.scalars().all()

        return {
            "success": True,
            "data": [
                {
                    "id": a.id,
                    "contact_id": a.contact_id,
                    "scheduled_at": a.scheduled_at.isoformat() if a.scheduled_at else None,
                    "duration_minutes": a.duration_minutes,
                    "status": a.status,
                    "notes": a.notes,
                }
                for a in appointments
            ],
            "count": len(appointments),
        }

    async def _get_dashboard_stats(self, _args: dict[str, Any]) -> dict[str, Any]:
        contacts_count = await self.db.scalar(
            select(func.count())
            .select_from(Contact)
            .where(Contact.workspace_id == self.workspace_id)
        )
        campaigns_count = await self.db.scalar(
            select(func.count())
            .select_from(Campaign)
            .where(Campaign.workspace_id == self.workspace_id)
        )
        conversations_count = await self.db.scalar(
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.workspace_id == self.workspace_id)
        )
        appointments_count = await self.db.scalar(
            select(func.count())
            .select_from(Appointment)
            .where(
                Appointment.workspace_id == self.workspace_id,
                Appointment.scheduled_at >= datetime.now(UTC),
            )
        )

        return {
            "success": True,
            "data": {
                "contacts": contacts_count or 0,
                "campaigns": campaigns_count or 0,
                "conversations": conversations_count or 0,
                "upcoming_appointments": appointments_count or 0,
            },
        }

    async def _list_opportunities(self, args: dict[str, Any]) -> dict[str, Any]:
        limit = min(args.get("limit", 10), 50)
        stmt = (
            select(Opportunity)
            .where(Opportunity.workspace_id == self.workspace_id)
            .order_by(Opportunity.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        opportunities = result.scalars().all()

        return {
            "success": True,
            "data": [
                {
                    "id": str(o.id),
                    "name": o.name,
                    "status": o.status,
                    "amount": float(o.amount) if o.amount else None,
                    "probability": o.probability,
                }
                for o in opportunities
            ],
            "count": len(opportunities),
        }

    async def _list_offers(self, args: dict[str, Any]) -> dict[str, Any]:
        limit = min(args.get("limit", 10), 50)
        stmt = (
            select(Offer)
            .where(Offer.workspace_id == self.workspace_id)
            .order_by(Offer.created_at.desc())
            .limit(limit)
        )
        if args.get("active_only"):
            stmt = stmt.where(Offer.is_active.is_(True))

        result = await self.db.execute(stmt)
        offers = result.scalars().all()

        return {
            "success": True,
            "data": [self._serialize_offer_summary(offer) for offer in offers],
            "count": len(offers),
        }

    async def _get_offer_details(self, args: dict[str, Any]) -> dict[str, Any]:
        offer_id = self._parse_offer_id(args.get("offer_id"))
        if offer_id is None:
            return {"success": False, "error": "Invalid offer_id"}

        offer = await self._get_offer_for_workspace(offer_id)
        if offer is None:
            return {"success": False, "error": "Offer not found"}

        return {"success": True, "data": self._serialize_offer_details(offer)}

    async def _create_offer_draft(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            offer_in = OfferCreate(**{**args, "is_active": False})
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

        offer = Offer(
            workspace_id=self.workspace_id,
            **offer_in.model_dump(mode="json"),
        )
        self.db.add(offer)
        await self.db.flush()

        return {"success": True, "data": self._serialize_offer_details(offer)}

    async def _update_offer_draft(self, args: dict[str, Any]) -> dict[str, Any]:
        offer_id = self._parse_offer_id(args.get("offer_id"))
        if offer_id is None:
            return {"success": False, "error": "Invalid offer_id"}

        offer = await self._get_offer_for_workspace(offer_id)
        if offer is None:
            return {"success": False, "error": "Offer not found"}

        update_args = {key: value for key, value in args.items() if key != "offer_id"}
        try:
            offer_in = OfferUpdate(**update_args)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

        update_data = offer_in.model_dump(exclude_unset=True, mode="json")
        if not update_data:
            return {"success": False, "error": "No offer fields provided"}

        for field, value in update_data.items():
            setattr(offer, field, value)

        await self.db.flush()

        return {"success": True, "data": self._serialize_offer_details(offer)}
