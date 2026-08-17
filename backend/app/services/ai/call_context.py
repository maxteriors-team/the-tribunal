"""Call context service for voice sessions.

This module extracts call context lookup logic from voice_bridge.py
into a standalone service. Provides:
- CallContext dataclass for structured context
- Database lookup for agent, contact, offer by call ID
- N+1 query prevention with eager loading

Usage:
    context = await lookup_call_context(call_id)
    if context.agent:
        print(f"Agent: {context.agent.name}")
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

from app.db.session import AsyncSessionLocal
from app.models.agent import Agent
from app.services.ai.bandit_arm_selector import BanditArmSelector
from app.services.ai.bandit_context import build_decision_context

logger = structlog.get_logger()


async def _select_prompt_version_for_call(
    db: Any,
    agent_id: Any,
    message_id: Any,
    contact_id: int | None,
    log: Any,
) -> str | None:
    """Select prompt version for a call using multi-armed bandit.

    Args:
        db: Database session
        agent_id: Agent UUID
        message_id: Message UUID for attribution
        contact_id: Contact ID (may be None for inbound)
        log: Logger instance

    Returns:
        Prompt version ID string if selected, None otherwise
    """
    decision_context = await build_decision_context(
        db=db,
        contact_id=contact_id,
        agent_id=agent_id,
        call_time=datetime.now(UTC),
    )

    selector = BanditArmSelector()
    try:
        selected_version, decision = await selector.select_arm(
            db=db,
            agent_id=agent_id,
            message_id=message_id,
            context=decision_context,
        )
        log.info(
            "bandit_arm_selected",
            prompt_version_id=str(selected_version.id),
            version_number=selected_version.version_number,
            decision_type=decision.decision_type,
        )
        return str(selected_version.id)
    except ValueError:
        # No active prompt versions - call proceeds without prompt version tracking
        log.warning("no_active_prompt_versions", agent_id=str(agent_id))
        return None


@dataclass
class CallContext:
    """Context information for a voice call.

    Contains all the information needed to configure a voice session:
    - Agent configuration and settings
    - Contact information for personalization
    - Offer/product information for sales calls
    - Workspace timezone for scheduling
    - Prompt version for attribution

    Attributes:
        agent: Agent model for voice configuration
        contact_info: Contact dictionary (name, phone, email, company)
        offer_info: Offer dictionary (name, description, terms)
        timezone: Workspace timezone (IANA format)
        workspace_id: UUID of the workspace
        conversation_id: UUID of the conversation
        prompt_version_id: UUID of the active prompt version for attribution
    """

    agent: Agent | None = None
    contact_info: dict[str, Any] | None = None
    offer_info: dict[str, Any] | None = None
    timezone: str = "America/New_York"
    workspace_id: str | None = None
    conversation_id: str | None = None
    is_outbound: bool = False
    prompt_version_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


async def _attach_returning_caller_context(
    *,
    db: Any,
    context: CallContext,
    workspace_id: Any,
    contact_id: int,
    current_message_id: Any,
    log: Any,
) -> None:
    """Detect a returning caller and inject a recap into the call context.

    Best-effort: any failure (DB hiccup, embedding outage) is logged and
    swallowed so returning-caller recognition never blocks taking the call. When
    the caller is returning, a voice-friendly recap is attached to
    ``context.contact_info['returning_summary']`` (so it flows through every
    provider's prompt builder) and a compact signal is recorded on
    ``context.metadata``.
    """
    try:
        from app.services.ai.caller_memory_service import (
            build_returning_caller_summary,
            detect_returning_caller,
        )

        info = await detect_returning_caller(
            db,
            workspace_id=workspace_id,
            contact_id=contact_id,
            current_message_id=current_message_id,
        )
        if not info.is_returning:
            return

        summary = build_returning_caller_summary(info, timezone=context.timezone)
        if summary and context.contact_info is not None:
            context.contact_info["returning_summary"] = summary
        context.metadata["returning_caller"] = {
            "is_returning": True,
            "prior_call_count": info.prior_call_count,
            "memory_count": len(info.memories),
        }
        log.info(
            "returning_caller_detected",
            contact_id=contact_id,
            prior_call_count=info.prior_call_count,
            memory_count=len(info.memories),
        )
    except Exception as e:  # noqa: BLE001 - recognition must never break a call
        log.warning("returning_caller_detection_failed", error_type=type(e).__name__)


async def _attach_structured_contact_context_and_memory(
    *,
    db: Any,
    context: CallContext,
    workspace_id: Any,
    contact_id: int,
    log: Any,
) -> None:
    """Attach authoritative CRM state followed by untrusted historical memory."""
    if context.contact_info is None:
        return

    try:
        from app.services.ai.contact_context_snapshot import ContactContextSnapshotService

        snapshot = await ContactContextSnapshotService(db).get_snapshot(
            workspace_id=workspace_id,
            contact_id=contact_id,
        )
        if snapshot is not None:
            context.contact_info["structured_context"] = snapshot.render()
    except Exception as exc:  # noqa: BLE001 - context enrichment must not break calls
        log.warning(
            "contact_context_snapshot_load_failed",
            contact_id=contact_id,
            error_type=type(exc).__name__,
        )

    try:
        from app.services.ai.contact_ai_memory_service import (
            ContactAIMemoryService,
            render_contact_ai_memory_context,
        )

        memory = await ContactAIMemoryService(db).get_context(
            workspace_id=workspace_id,
            contact_id=contact_id,
        )
        if memory is not None:
            context.contact_info["ai_memory_context"] = render_contact_ai_memory_context(memory)
    except Exception as exc:  # noqa: BLE001 - context enrichment must not break calls
        log.warning(
            "contact_ai_memory_load_failed",
            contact_id=contact_id,
            error_type=type(exc).__name__,
        )


async def lookup_call_context(
    call_id: str,
    log: Any = None,
) -> CallContext:
    """Look up agent, contact, and offer context for a call.

    Uses Telnyx call control ID (stored as provider_message_id on Message)
    to find the associated conversation and load all relevant context.

    Args:
        call_id: Telnyx call control ID
        log: Optional logger instance

    Returns:
        CallContext with loaded data
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.models.campaign import CampaignContact
    from app.models.contact import Contact
    from app.models.conversation import Message
    from app.models.offer import Offer
    from app.models.workspace import Workspace

    if log is None:
        log = logger.bind(service="call_context")

    context = CallContext()

    async with AsyncSessionLocal() as db:
        # Look up the message record for this call
        msg_result = await db.execute(
            select(Message)
            .options(selectinload(Message.conversation))
            .where(Message.provider_message_id == call_id)
        )
        message = msg_result.scalar_one_or_none()

        if not message or not message.conversation:
            log.warning("message_not_found_for_call", call_id=call_id)
            return context

        conversation = message.conversation
        context.conversation_id = str(conversation.id)
        context.workspace_id = str(conversation.workspace_id)

        # Get workspace timezone
        workspace_result = await db.execute(
            select(Workspace).where(Workspace.id == conversation.workspace_id)
        )
        workspace = workspace_result.scalar_one_or_none()
        if workspace and workspace.settings:
            context.timezone = workspace.settings.get("timezone", "America/New_York")

        # Look up the assigned agent
        # Priority: conversation.assigned_agent_id > message.agent_id
        agent_id = conversation.assigned_agent_id or message.agent_id
        if agent_id:
            agent_result = await db.execute(select(Agent).where(Agent.id == agent_id))
            context.agent = agent_result.scalar_one_or_none()
            if context.agent:
                log.info(
                    "found_agent_for_call",
                    agent_id=str(context.agent.id),
                    agent_name=context.agent.name,
                    source="conversation" if conversation.assigned_agent_id else "message",
                )

                # Select prompt version using multi-armed bandit
                context.prompt_version_id = await _select_prompt_version_for_call(
                    db=db,
                    agent_id=context.agent.id,
                    message_id=message.id,
                    contact_id=conversation.contact_id,
                    log=log,
                )

        # Look up contact info
        if conversation.contact_id:
            contact_result = await db.execute(
                select(Contact).where(Contact.id == conversation.contact_id)
            )
            contact = contact_result.scalar_one_or_none()
            if contact:
                context.contact_info = {
                    # Internal prompt-control metadata; PromptBuilder does not
                    # render this key to the model as customer profile text.
                    "lead_source_known": contact.first_touch_lead_source_id is not None,
                    "name": f"{contact.first_name} {contact.last_name or ''}".strip(),
                    "phone": contact.phone_number,
                    "email": contact.email,
                    "company": contact.company_name,
                    "status": contact.status,
                    "notes": contact.notes,
                }
                log.info("found_contact_for_call", contact_id=str(contact.id))

                # Returning-caller recognition: detect prior calls / stored
                # caller memories for this contact and inject a recap so the
                # agent greets them as a returning caller instead of cold.
                await _attach_returning_caller_context(
                    db=db,
                    context=context,
                    workspace_id=conversation.workspace_id,
                    contact_id=conversation.contact_id,
                    current_message_id=message.id,
                    log=log,
                )
                await _attach_structured_contact_context_and_memory(
                    db=db,
                    context=context,
                    workspace_id=conversation.workspace_id,
                    contact_id=conversation.contact_id,
                    log=log,
                )

        # Unknown inbound callers have no Contact yet. Keep an explicit false
        # flag so the prompt still asks before save_lead_info creates the row.
        if context.contact_info is None:
            context.contact_info = {"lead_source_known": False}

        # Look up offer info from campaign if applicable
        campaign_contact_result = await db.execute(
            select(CampaignContact)
            .options(selectinload(CampaignContact.campaign))
            .where(CampaignContact.conversation_id == conversation.id)
        )
        campaign_contact = campaign_contact_result.scalar_one_or_none()

        if campaign_contact and campaign_contact.campaign:
            campaign = campaign_contact.campaign
            if campaign.offer_id:
                offer_result = await db.execute(select(Offer).where(Offer.id == campaign.offer_id))
                offer = offer_result.scalar_one_or_none()
                if offer:
                    context.offer_info = {
                        "name": offer.name,
                        "description": offer.description,
                        "discount_type": offer.discount_type,
                        "discount_value": float(offer.discount_value),
                        "terms": offer.terms,
                    }
                    log.info(
                        "found_offer_for_call",
                        offer_id=str(offer.id),
                        offer_name=offer.name,
                    )

    return context


async def save_call_transcript(
    call_id: str,
    transcript_json: str,
    log: Any = None,
) -> bool:
    """Save transcript to the message record for this call.

    Args:
        call_id: Telnyx call control ID (provider_message_id)
        transcript_json: JSON string of transcript entries
        log: Optional logger instance

    Returns:
        True if saved successfully, False otherwise
    """
    from sqlalchemy import update

    from app.models.conversation import Message

    if log is None:
        log = logger.bind(service="call_context")

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                update(Message)
                .where(Message.provider_message_id == call_id)
                .values(transcript=transcript_json)
            )
            await db.commit()
            log.info(
                "transcript_saved",
                call_id=call_id,
                rows_updated=result.rowcount,  # type: ignore[attr-defined]
                transcript_length=len(transcript_json),
            )
            return True
    except Exception as e:
        log.exception("save_transcript_error", error=str(e), call_id=call_id)
        return False


class CallContextService:
    """Service for managing call context throughout a voice session.

    Provides a stateful wrapper around context lookup with caching
    and context enrichment capabilities.

    Attributes:
        call_id: Telnyx call control ID
        context: Loaded CallContext
        logger: Structured logger
    """

    def __init__(self, call_id: str) -> None:
        """Initialize call context service.

        Args:
            call_id: Telnyx call control ID
        """
        self.call_id = call_id
        self.context: CallContext | None = None
        self.logger = logger.bind(service="call_context", call_id=call_id)

    async def load(self) -> CallContext:
        """Load call context from database.

        Returns:
            Loaded CallContext
        """
        self.context = await lookup_call_context(self.call_id, self.logger)
        return self.context

    async def save_transcript(self, transcript_json: str) -> bool:
        """Save transcript for this call.

        Args:
            transcript_json: JSON string of transcript entries

        Returns:
            True if saved successfully
        """
        return await save_call_transcript(self.call_id, transcript_json, self.logger)

    @property
    def agent(self) -> Agent | None:
        """Get the agent for this call."""
        return self.context.agent if self.context else None

    @property
    def contact_info(self) -> dict[str, Any] | None:
        """Get contact info for this call."""
        return self.context.contact_info if self.context else None

    @property
    def offer_info(self) -> dict[str, Any] | None:
        """Get offer info for this call."""
        return self.context.offer_info if self.context else None

    @property
    def timezone(self) -> str:
        """Get timezone for this call."""
        return self.context.timezone if self.context else "America/New_York"
