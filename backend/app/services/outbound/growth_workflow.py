"""High-level outbound growth workflow for the CRM assistant."""

import uuid
from dataclasses import dataclass
from typing import Any, Literal

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.scope import get_workspace_owned, select_workspace_owned
from app.models.agent import Agent
from app.models.campaign import Campaign, CampaignContact, CampaignStatus, CampaignType
from app.models.contact import Contact
from app.models.offer import Offer
from app.models.phone_number import PhoneNumber
from app.models.segment import Segment
from app.services.contacts.contact_filters import apply_contact_filters

WorkflowStatus = Literal["needs_input", "draft_ready"]
ResponderAction = Literal["recommended_existing", "created_draft", "create_recommended"]


@dataclass(frozen=True, slots=True)
class WorkflowMissingInput:
    """A missing decision needed before creating an outbound draft."""

    field: Literal["offer_id", "segment_id", "from_phone_number"]
    question: str
    options: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class CampaignDraftPlan:
    """Deterministic campaign copy plan derived from offer and segment context."""

    name: str
    description: str
    angle: str
    initial_message: str
    follow_up_message: str
    qualification_criteria: str


@dataclass(frozen=True, slots=True)
class ResponderRecommendation:
    """Responder agent recommendation or created draft result."""

    action: ResponderAction
    agent_id: str | None
    name: str
    rationale: str
    system_prompt: str | None = None


class OutboundGrowthWorkflowService:
    """Orchestrate outbound campaign setup from a high-level assistant intent."""

    def __init__(self, db: AsyncSession, workspace_id: uuid.UUID) -> None:
        self.db = db
        self.workspace_id = workspace_id
        self.log = structlog.get_logger(service="outbound_growth_workflow")

    async def plan(self, args: dict[str, Any]) -> dict[str, Any]:
        """Select context, draft copy, preview samples, and optionally create draft records."""
        intent = str(args.get("intent") or "let's reach out to some people").strip()
        create_draft = bool(args.get("create_draft", True))
        create_responder_agent = bool(args.get("create_responder_agent", False))

        offer_id = _parse_uuid(args.get("offer_id"))
        segment_id = _parse_uuid(args.get("segment_id"))
        from_phone_number = _clean_optional_string(args.get("from_phone_number"))

        offer = await self._resolve_offer(offer_id)
        segment = await self._resolve_segment(segment_id)
        selected_phone = await self._resolve_phone_number(from_phone_number)

        missing_inputs = await self._collect_missing_inputs(offer, segment, selected_phone)
        if missing_inputs:
            return {
                "success": True,
                "status": "needs_input",
                "intent": intent,
                "missing_inputs": [
                    {
                        "field": missing.field,
                        "question": missing.question,
                        "options": missing.options,
                    }
                    for missing in missing_inputs
                ],
                "next_approval_step": (
                    "Choose an offer, segment, and sending number before I create an "
                    "outbound draft."
                ),
            }

        assert offer is not None
        assert segment is not None
        assert selected_phone is not None

        preview_contacts = await self._preview_contacts(segment)
        draft_plan = _build_campaign_plan(intent, offer, segment)
        responder = await self._resolve_responder_agent(
            offer=offer,
            segment=segment,
            create_responder_agent=create_responder_agent,
        )
        campaign = None
        enrolled_count = 0
        if create_draft:
            campaign = await self._create_campaign_draft(
                plan=draft_plan,
                offer=offer,
                agent_id=_uuid_or_none(responder.agent_id),
                from_phone_number=selected_phone,
            )
            enrolled_count = await self._enroll_preview_contacts(campaign, preview_contacts)
            await self.db.flush()

        return {
            "success": True,
            "status": "draft_ready",
            "intent": intent,
            "offer": _serialize_offer(offer),
            "segment": await self._serialize_segment(segment),
            "draft": {
                "campaign_id": str(campaign.id) if campaign else None,
                "name": draft_plan.name,
                "description": draft_plan.description,
                "status": CampaignStatus.DRAFT.value,
                "created": campaign is not None,
                "enrolled_preview_contacts": enrolled_count,
            },
            "angles": [draft_plan.angle],
            "messages": {
                "initial": draft_plan.initial_message,
                "follow_up": draft_plan.follow_up_message,
                "qualification_criteria": draft_plan.qualification_criteria,
            },
            "previews": [
                {
                    "contact_id": contact["id"],
                    "contact_name": contact["name"],
                    "company": contact["company"],
                    "message": _render_message(draft_plan.initial_message, contact),
                }
                for contact in preview_contacts
            ],
            "responder_agent": {
                "action": responder.action,
                "agent_id": responder.agent_id,
                "name": responder.name,
                "rationale": responder.rationale,
                "system_prompt": responder.system_prompt,
            },
            "next_approval_step": _next_approval_step(campaign),
        }

    async def _resolve_offer(self, offer_id: uuid.UUID | None) -> Offer | None:
        if offer_id is not None:
            return await get_workspace_owned(self.db, Offer, offer_id, self.workspace_id)
        result = await self.db.execute(
            select_workspace_owned(Offer, self.workspace_id)
            .order_by(Offer.is_active.desc(), Offer.updated_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _resolve_segment(self, segment_id: uuid.UUID | None) -> Segment | None:
        if segment_id is not None:
            return await get_workspace_owned(self.db, Segment, segment_id, self.workspace_id)
        result = await self.db.execute(
            select_workspace_owned(Segment, self.workspace_id)
            .order_by(Segment.contact_count.desc(), Segment.updated_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _resolve_phone_number(self, requested_number: str | None) -> str | None:
        query = select_workspace_owned(
            PhoneNumber,
            self.workspace_id,
            PhoneNumber.is_active.is_(True),
            PhoneNumber.sms_enabled.is_(True),
        )
        if requested_number is not None:
            query = query.where(PhoneNumber.phone_number == requested_number)
        result = await self.db.execute(query.order_by(PhoneNumber.created_at.desc()).limit(1))
        phone = result.scalar_one_or_none()
        return phone.phone_number if phone is not None else None

    async def _collect_missing_inputs(
        self,
        offer: Offer | None,
        segment: Segment | None,
        from_phone_number: str | None,
    ) -> list[WorkflowMissingInput]:
        missing_inputs: list[WorkflowMissingInput] = []
        if offer is None:
            missing_inputs.append(
                WorkflowMissingInput(
                    field="offer_id",
                    question="Which offer should this outbound campaign promote?",
                    options=await self._offer_options(),
                )
            )
        if segment is None:
            missing_inputs.append(
                WorkflowMissingInput(
                    field="segment_id",
                    question="Which contact segment should receive this campaign?",
                    options=await self._segment_options(),
                )
            )
        if from_phone_number is None:
            missing_inputs.append(
                WorkflowMissingInput(
                    field="from_phone_number",
                    question="Which SMS-enabled phone number should send the campaign?",
                    options=await self._phone_options(),
                )
            )
        return missing_inputs

    async def _offer_options(self) -> list[dict[str, Any]]:
        result = await self.db.execute(
            select_workspace_owned(Offer, self.workspace_id)
            .order_by(Offer.is_active.desc(), Offer.updated_at.desc())
            .limit(5)
        )
        return [_serialize_offer(offer) for offer in result.scalars().all()]

    async def _segment_options(self) -> list[dict[str, Any]]:
        result = await self.db.execute(
            select_workspace_owned(Segment, self.workspace_id)
            .order_by(Segment.contact_count.desc(), Segment.updated_at.desc())
            .limit(5)
        )
        return [await self._serialize_segment(segment) for segment in result.scalars().all()]

    async def _phone_options(self) -> list[dict[str, Any]]:
        result = await self.db.execute(
            select_workspace_owned(
                PhoneNumber,
                self.workspace_id,
                PhoneNumber.is_active.is_(True),
                PhoneNumber.sms_enabled.is_(True),
            )
            .order_by(PhoneNumber.created_at.desc())
            .limit(5)
        )
        return [
            {"id": str(phone.id), "phone_number": phone.phone_number, "name": phone.friendly_name}
            for phone in result.scalars().all()
        ]

    async def _serialize_segment(self, segment: Segment) -> dict[str, Any]:
        return {
            "id": str(segment.id),
            "name": segment.name,
            "description": segment.description,
            "contact_count": await self._count_segment_contacts(segment),
        }

    async def _count_segment_contacts(self, segment: Segment) -> int:
        definition = segment.definition or {}
        query = apply_contact_filters(
            select(func.count(Contact.id)),
            self.workspace_id,
            filter_rules=definition.get("rules"),
            filter_logic=definition.get("logic", "and"),
        ).where(Contact.workspace_id == self.workspace_id)
        result = await self.db.execute(query)
        count = result.scalar()
        return int(count or 0)

    async def _preview_contacts(self, segment: Segment) -> list[dict[str, Any]]:
        definition = segment.definition or {}
        query = apply_contact_filters(
            select(Contact),
            self.workspace_id,
            filter_rules=definition.get("rules"),
            filter_logic=definition.get("logic", "and"),
        )
        query = (
            query.where(Contact.workspace_id == self.workspace_id)
            .order_by(Contact.created_at.desc())
            .limit(3)
        )
        result = await self.db.execute(query)
        return [_serialize_contact(contact) for contact in result.scalars().all()]

    async def _resolve_responder_agent(
        self,
        *,
        offer: Offer,
        segment: Segment,
        create_responder_agent: bool,
    ) -> ResponderRecommendation:
        existing = await self._find_existing_responder_agent()
        if existing is not None:
            return ResponderRecommendation(
                action="recommended_existing",
                agent_id=str(existing.id),
                name=existing.name,
                rationale=(
                    "Use the existing active text/both responder so replies stay in the "
                    "current operating model."
                ),
            )

        prompt = _build_responder_prompt(offer, segment)
        if create_responder_agent:
            agent = Agent(
                workspace_id=self.workspace_id,
                name=f"{offer.name} Responder",
                description=f"Handles replies for outbound campaigns to {segment.name}.",
                channel_mode="text",
                system_prompt=prompt,
                enabled_tools=["book_appointment"],
                is_active=False,
            )
            self.db.add(agent)
            await self.db.flush()
            return ResponderRecommendation(
                action="created_draft",
                agent_id=str(agent.id),
                name=agent.name,
                rationale="Created an inactive responder draft for review before campaign launch.",
                system_prompt=prompt,
            )

        return ResponderRecommendation(
            action="create_recommended",
            agent_id=None,
            name=f"{offer.name} Responder",
            rationale="No active text responder exists; create one before starting the campaign.",
            system_prompt=prompt,
        )

    async def _find_existing_responder_agent(self) -> Agent | None:
        result = await self.db.execute(
            select_workspace_owned(
                Agent,
                self.workspace_id,
                Agent.is_active.is_(True),
                Agent.channel_mode.in_(["text", "both"]),
            )
            .order_by(Agent.updated_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _create_campaign_draft(
        self,
        *,
        plan: CampaignDraftPlan,
        offer: Offer,
        agent_id: uuid.UUID | None,
        from_phone_number: str,
    ) -> Campaign:
        campaign = Campaign(
            workspace_id=self.workspace_id,
            agent_id=agent_id,
            offer_id=offer.id,
            name=plan.name,
            description=plan.description,
            campaign_type=CampaignType.SMS,
            status=CampaignStatus.DRAFT,
            from_phone_number=from_phone_number,
            initial_message=plan.initial_message,
            ai_enabled=True,
            qualification_criteria=plan.qualification_criteria,
            follow_up_enabled=True,
            follow_up_message=plan.follow_up_message,
            sending_days=[0, 1, 2, 3, 4],
            timezone="America/New_York",
        )
        self.db.add(campaign)
        await self.db.flush()
        return campaign

    async def _enroll_preview_contacts(
        self,
        campaign: Campaign,
        preview_contacts: list[dict[str, Any]],
    ) -> int:
        # Add rows directly instead of appending to the lazy
        # ``campaign.campaign_contacts`` collection: touching an unloaded
        # collection on a flushed instance emits a synchronous lazy load,
        # which raises MissingGreenlet under the async engine.
        for contact in preview_contacts:
            self.db.add(
                CampaignContact(
                    campaign_id=campaign.id,
                    contact_id=int(contact["id"]),
                )
            )
        return len(preview_contacts)


def _parse_uuid(raw_value: Any) -> uuid.UUID | None:
    if raw_value in (None, ""):
        return None
    try:
        return uuid.UUID(str(raw_value))
    except (TypeError, ValueError):
        return None


def _uuid_or_none(raw_value: str | None) -> uuid.UUID | None:
    if raw_value is None:
        return None
    return _parse_uuid(raw_value)


def _clean_optional_string(raw_value: Any) -> str | None:
    if raw_value is None:
        return None
    value = str(raw_value).strip()
    return value or None


def _serialize_offer(offer: Offer) -> dict[str, Any]:
    return {
        "id": str(offer.id),
        "name": offer.name,
        "description": offer.description,
        "headline": offer.headline,
        "cta_text": offer.cta_text,
        "is_active": offer.is_active,
    }


def _serialize_contact(contact: Contact) -> dict[str, Any]:
    return {
        "id": contact.id,
        "name": contact.full_name,
        "first_name": contact.first_name,
        "company": contact.company_name,
    }


def _build_campaign_plan(intent: str, offer: Offer, segment: Segment) -> CampaignDraftPlan:
    cta = offer.cta_text or "book a quick time"
    headline = offer.headline or offer.name
    angle = f"Lead with {headline} for {segment.name}, then ask for a low-friction booking reply."
    initial_message = (
        f"Hi {{first_name}}, quick note — {headline}. Would you like me to help you {cta.lower()}?"
    )
    follow_up_message = (
        f"Hi {{first_name}}, just bumping this in case {offer.name} would be useful. "
        "Want details or should I close the loop?"
    )
    qualification_criteria = (
        "Qualified when the contact expresses interest, asks for pricing/details, "
        "or agrees to schedule an appointment."
    )
    campaign_name = f"{offer.name} → {segment.name}"
    description = f"Assistant-created draft from intent: {intent}"
    return CampaignDraftPlan(
        name=campaign_name[:255],
        description=description,
        angle=angle,
        initial_message=initial_message,
        follow_up_message=follow_up_message,
        qualification_criteria=qualification_criteria,
    )


def _build_responder_prompt(offer: Offer, segment: Segment) -> str:
    return (
        f"You handle SMS replies for the {offer.name} outbound campaign to {segment.name}. "
        "Be concise, answer questions honestly, qualify interest, respect opt-outs immediately, "
        "and book an appointment when the contact is ready."
    )


def _render_message(template: str, contact: dict[str, Any]) -> str:
    return template.replace("{first_name}", str(contact.get("first_name") or "there")).replace(
        "{company_name}", str(contact.get("company") or "your team")
    )


def _next_approval_step(campaign: Campaign | None) -> str:
    if campaign is None:
        return "Review the proposed copy and responder, then ask me to create the draft campaign."
    return (
        f"Review draft campaign {campaign.id}, approve the responder setup, "
        "then explicitly confirm start_campaign to begin outreach."
    )
