"""Never-booked re-engagement worker.

Sends re-engagement messages to contacts who replied to outreach (have at
least one inbound message) but never booked an appointment.

Qualifying contacts:
  - Belong to the agent's workspace
  - Have ≥ 1 inbound message (they engaged but never booked)
  - Do NOT have the "appointment-scheduled" tag
  - Do NOT have the "never-booked-reengaged" tag (already sent max attempts)
  - Last message activity was > agent.never_booked_delay_days days ago
  - Not opted out

After sending, the contact receives the "never-booked-reengaged" tag so the
sequence does not fire again (the max-attempts gate is effectively 1 send per
contact per agent; for repeat sequences remove the tag and adjust logic).
"""

import re
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, exists, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.agent import Agent
from app.models.contact import Contact
from app.models.conversation import Conversation, Message
from app.models.phone_number import PhoneNumber
from app.services.rate_limiting.opt_out_manager import OptOutManager
from app.services.telephony.text_provider import get_text_message_provider
from app.workers.base import BaseWorker, WorkerRegistry
from app.workers.retryable import RetryableWorker

MAX_CONTACTS_PER_TICK = 20

_DEFAULT_NEVER_BOOKED_TEMPLATE = (
    "Hi {first_name}, just checking in — we're still offering our free video ads "
    "strategy session. Book your spot: {booking_link}"
)


class NeverBookedWorker(RetryableWorker, BaseWorker):
    """Background worker for never-booked lead re-engagement."""

    POLL_INTERVAL_SECONDS = 3600  # once per hour
    COMPONENT_NAME = "never_booked_worker"
    # Per-lead SMS sends; conservative to avoid spiking shared rate budgets.
    MAX_CONCURRENCY = 5
    max_retries = 3
    backoff_base_seconds = 2.0

    def __init__(self) -> None:
        super().__init__()
        self.opt_out_manager = OptOutManager()

    async def _process_items(self) -> None:
        """Process all agents with never-booked re-engagement enabled."""
        async with AsyncSessionLocal() as db:
            agent_result = await db.execute(
                select(Agent).where(Agent.never_booked_reengagement_enabled.is_(True))
            )
            agents = agent_result.scalars().all()

            if not agents:
                return

            for agent in agents:
                await self.execute_with_retry(
                    self._process_agent,
                    agent,
                    db,
                    item_key=f"agent:{agent.id}",
                )

    async def _process_agent(self, agent: Agent, db: AsyncSession) -> None:
        """Find qualifying contacts for this agent and send re-engagement SMS."""
        now = datetime.now(UTC)
        activity_cutoff = now - timedelta(days=agent.never_booked_delay_days)

        # Subquery: conversations for this workspace that have ≥ 1 inbound message
        has_inbound = exists(
            select(Message.id)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(
                and_(
                    Conversation.contact_id == Contact.id,
                    Conversation.workspace_id == agent.workspace_id,
                    Message.direction == "inbound",
                )
            )
        )

        # Subquery: most-recent message timestamp across all conversations for contact
        # We check last_message_at on the conversation (denormalized, always updated)
        has_recent_conversation = exists(
            select(Conversation.id).where(
                and_(
                    Conversation.contact_id == Contact.id,
                    Conversation.workspace_id == agent.workspace_id,
                    Conversation.last_message_at.is_not(None),
                    Conversation.last_message_at <= activity_cutoff,
                )
            )
        )

        result = await db.execute(
            select(Contact)
            .where(
                and_(
                    Contact.workspace_id == agent.workspace_id,
                    has_inbound,
                    has_recent_conversation,
                    # Never booked — no "appointment-scheduled" tag
                    ~Contact.tags.contains(["appointment-scheduled"]),
                    # Not already re-engaged
                    ~Contact.tags.contains(["never-booked-reengaged"]),
                )
            )
            .order_by(Contact.updated_at)
            .limit(MAX_CONTACTS_PER_TICK)
        )
        contacts = result.scalars().all()

        if contacts:
            self.logger.info(
                "Processing never-booked re-engagement",
                agent_id=str(agent.id),
                count=len(contacts),
            )

        for contact in contacts:
            await self.execute_with_retry(
                self._send_reengagement,
                contact,
                agent,
                db,
                item_key=f"never_booked:{agent.id}:contact:{contact.id}",
            )

    async def _send_reengagement(
        self,
        contact: Contact,
        agent: Agent,
        db: AsyncSession,
    ) -> None:
        """Send a single never-booked re-engagement SMS."""
        log = self.logger.bind(contact_id=contact.id, agent_id=str(agent.id))

        contact_phone = contact.phone_number
        if not contact_phone:
            log.warning("Contact has no phone number")
            return

        # TCPA compliance — skip opted-out contacts
        is_opted_out = await self.opt_out_manager.check_opt_out(
            contact.workspace_id, contact_phone, db
        )
        if is_opted_out:
            log.info("Skipping never-booked re-engagement — contact opted out")
            # Mark as sent so we don't keep checking
            await self._tag_contact(contact, "never-booked-reengaged", db)
            await db.commit()
            return

        from_number = await self._resolve_from_number(
            db, contact.id, contact.workspace_id, agent.id
        )
        if not from_number:
            log.warning("Could not resolve from number, will retry next tick")
            return

        template = agent.never_booked_template or _DEFAULT_NEVER_BOOKED_TEMPLATE
        body = self._render_template(template, contact, agent)

        sms_service = get_text_message_provider()
        try:
            message = await sms_service.send_message(
                to_number=contact_phone,
                from_number=from_number,
                body=body,
                db=db,
                workspace_id=contact.workspace_id,
                agent_id=agent.id,
            )
            log.info("Never-booked re-engagement SMS sent", message_id=str(message.id))
            await self._tag_contact(contact, "never-booked-reengaged", db)
            await db.commit()
        except Exception as exc:
            log.exception("Failed to send never-booked re-engagement SMS", error=str(exc))
        finally:
            await sms_service.close()

    @staticmethod
    async def _tag_contact(contact: Contact, tag: str, db: AsyncSession) -> None:
        """Append a tag to contact.tags using PostgreSQL array_append (idempotent)."""
        await db.execute(
            text(
                "UPDATE contacts "
                "SET tags = array_append(COALESCE(tags, ARRAY[]::text[]), :tag) "
                "WHERE id = :contact_id AND NOT (COALESCE(tags, ARRAY[]::text[]) @> ARRAY[:tag])"
            ),
            {"tag": tag, "contact_id": contact.id},
        )
        current = list(contact.tags or [])
        if tag not in current:
            current.append(tag)
        contact.tags = current

    def _render_template(self, template: str, contact: Contact, agent: Agent) -> str:
        """Render a template with {first_name} and {booking_link} placeholders."""
        first_name = contact.first_name or "there"
        booking_link = self._build_booking_link(contact, agent)

        replacements: dict[str, str] = {
            "first_name": first_name,
            "last_name": contact.last_name or "",
            "booking_link": booking_link,
            "reschedule_link": booking_link,
        }

        message = template
        for placeholder, value in replacements.items():
            try:
                pattern = re.compile(rf"\{{{placeholder}\}}", re.IGNORECASE)
                message = pattern.sub(value, message)
            except Exception:
                self.logger.warning(
                    "Placeholder replacement failed",
                    placeholder=placeholder,
                )
        return message

    def _build_booking_link(self, contact: Contact, agent: Agent) -> str:
        """Generate a Cal.com booking URL if agent has an event type configured."""
        if not agent.calcom_event_type_id or not settings.calcom_api_key:
            return ""
        try:
            from app.services.calendar.calcom import CalComService

            calcom = CalComService(settings.calcom_api_key)
            contact_name = (
                " ".join(filter(None, [contact.first_name, contact.last_name]))
                or contact.first_name
            )
            return calcom.generate_booking_url(
                event_type_id=agent.calcom_event_type_id,
                contact_email=contact.email or "",
                contact_name=contact_name,
                contact_phone=contact.phone_number,
            )
        except Exception:
            self.logger.warning(
                "Could not generate booking link",
                agent_id=str(agent.id),
            )
            return ""

    async def _resolve_from_number(
        self,
        db: AsyncSession,
        contact_id: int,
        workspace_id: uuid.UUID,
        agent_id: uuid.UUID,
    ) -> str | None:
        """Resolve the best from-number for the SMS.

        Strategy 1: Existing conversation with this contact (reuse same number).
        Strategy 2: Agent's assigned phone number.
        Strategy 3: Any active SMS-enabled workspace phone number.
        """
        # Strategy 1 — existing conversation
        result = await db.execute(
            select(Conversation.workspace_phone)
            .where(
                and_(
                    Conversation.contact_id == contact_id,
                    Conversation.workspace_id == workspace_id,
                )
            )
            .order_by(Conversation.last_message_at.desc().nulls_last())
            .limit(1)
        )
        phone = result.scalar_one_or_none()
        if phone:
            return str(phone)

        # Strategy 2 — agent's assigned phone number
        result = await db.execute(
            select(PhoneNumber.phone_number)
            .where(
                and_(
                    PhoneNumber.assigned_agent_id == agent_id,
                    PhoneNumber.is_active.is_(True),
                    PhoneNumber.sms_enabled.is_(True),
                )
            )
            .limit(1)
        )
        phone = result.scalar_one_or_none()
        if phone:
            return str(phone)

        # Strategy 3 — any active SMS-enabled workspace phone number
        result = await db.execute(
            select(PhoneNumber.phone_number)
            .where(
                and_(
                    PhoneNumber.workspace_id == workspace_id,
                    PhoneNumber.is_active.is_(True),
                    PhoneNumber.sms_enabled.is_(True),
                )
            )
            .order_by(PhoneNumber.created_at)
            .limit(1)
        )
        phone = result.scalar_one_or_none()
        if phone:
            return str(phone)

        return None


# Singleton registry
_registry = WorkerRegistry(NeverBookedWorker)
start_never_booked_worker = _registry.start
stop_never_booked_worker = _registry.stop
get_never_booked_worker = _registry.get
