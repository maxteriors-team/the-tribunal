"""Automation worker — evaluates trigger-based automations and executes their actions.

Poll cycle
----------
1. Drain pending ``automation_events`` (event-based triggers) and run matching
   automations against each event's contact.
2. Load all active automations and evaluate polling triggers to find matching
   contacts that have NOT yet been processed (no row in ``automation_executions``).
3. For each new matching contact/event, execute every action in the automation's
   ``actions`` list (each gated through the approval system).
4. Record an ``AutomationExecution`` row so the contact/event is not re-processed.
5. Update ``automation.last_evaluated_at`` so subsequent cycles can bound
   contact queries by recency (avoiding full-table scans on large datasets).

Supported trigger_type values
------------------------------
Polling triggers (evaluated against ``contacts``):

- ``appointment_booked`` / ``booking_created`` : contact.last_appointment_status == "scheduled"
- ``no_show``                                  : contact.last_appointment_status == "no_show"
- ``contact_tagged``                           : contact has a specific tag, tagged recently
- ``never_booked``                             : contact has conversations but no appointments

Event triggers (drained from ``automation_events``, emitted by services):

- ``review_received`` / ``review_request_response`` : a review / rating came in
- ``opportunity_created`` / ``deal_stage_changed``  : pipeline activity
- ``missed_call``                                   : inbound call went unanswered
- ``roleplay_completed``                            : a practice-arena run finished
- ``knowledge_document_uploaded``                   : a knowledge doc was added

Supported action type values
-----------------------------
- ``send_sms``       : send an SMS via Telnyx using a resolved from-number
- ``send_email``     : send an email via Resend to the contact's email
- ``make_call``      : initiate an outbound AI voice call via Telnyx
- ``enroll_campaign``: create a CampaignContact record (idempotent via upsert)
- ``apply_tag`` / ``add_tag`` : add a normalized workspace tag to the contact
- ``wait`` / ``delay``: no-op in the current cycle (action is recorded as
                        "scheduled" and re-evaluated on subsequent poll)

Actions that target a contact (SMS/email/call/tag/enroll) are skipped with a
warning when an event has no associated contact (e.g. roleplay/knowledge).
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, exists, func, not_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.automation import Automation
from app.models.automation_event import (
    EVENT_STATUS_PENDING,
    EVENT_STATUS_PROCESSED,
    AutomationEvent,
)
from app.models.automation_execution import AutomationExecution
from app.models.campaign import Campaign, CampaignContact, CampaignContactStatus, CampaignStatus
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.phone_number import PhoneNumber
from app.models.tag import ContactTag, Tag
from app.services.approval.approval_gate_service import approval_gate_service
from app.services.automations.events import AUTOMATION_EVENT_TRIGGERS
from app.services.email import send_automation_email
from app.services.idempotency import derive_outbound_key, derive_worker_retry_key
from app.services.tags import TagService
from app.services.telephony.telnyx_voice import TelnyxVoiceService
from app.services.telephony.text_provider import get_text_message_provider
from app.workers.base import BaseWorker, WorkerRegistry
from app.workers.retryable import RetryableWorker

# Maximum contacts to process per automation per poll cycle.
MAX_CONTACTS_PER_AUTOMATION = 50

# Maximum queued events to drain per poll cycle.
MAX_EVENTS_PER_CYCLE = 100

# Default look-back window when last_evaluated_at is None (first run).
DEFAULT_LOOKBACK_DAYS = 30

# Default "never booked" inactivity threshold (days).
DEFAULT_NEVER_BOOKED_DAYS = 7

# Action types that require an associated contact. Skipped (with a warning) when
# an event trigger has no contact (e.g. roleplay_completed, knowledge upload).
_CONTACT_ACTIONS = frozenset(
    {"send_sms", "send_email", "make_call", "enroll_campaign", "apply_tag", "add_tag"}
)


class AutomationWorker(RetryableWorker, BaseWorker):
    """Executes trigger-based automations against contacts."""

    POLL_INTERVAL_SECONDS = 60
    COMPONENT_NAME = "automation_worker"
    # Per-(automation, contact) executions mix DB writes with SMS sends.
    MAX_CONCURRENCY = 5
    max_retries = 3
    backoff_base_seconds = 2.0

    # ------------------------------------------------------------------ #
    # BaseWorker interface                                                 #
    # ------------------------------------------------------------------ #

    async def _process_items(self) -> None:
        """Drain queued events, then evaluate active polling automations."""
        async with AsyncSessionLocal() as db:
            # 1) Event-based triggers (review/opportunity/missed_call/...).
            await self._process_events(db)

            # 2) Polling triggers evaluated against contacts.
            result = await db.execute(select(Automation).where(Automation.is_active.is_(True)))
            automations = result.scalars().all()

            if automations:
                self.logger.debug("Evaluating automations", count=len(automations))
                for automation in automations:
                    await self.execute_with_retry(
                        self._evaluate_automation,
                        automation,
                        db,
                        item_key=derive_worker_retry_key("automation", automation.id),
                    )

            await db.commit()

    # ------------------------------------------------------------------ #
    # Event-based triggers                                                 #
    # ------------------------------------------------------------------ #

    async def _process_events(self, db: AsyncSession) -> None:
        """Drain pending ``automation_events`` and run matching automations."""
        result = await db.execute(
            select(AutomationEvent)
            .where(AutomationEvent.status == EVENT_STATUS_PENDING)
            .order_by(AutomationEvent.created_at)
            .limit(MAX_EVENTS_PER_CYCLE)
        )
        events = list(result.scalars().all())
        if not events:
            return

        self.logger.info("Draining automation events", count=len(events))
        for event in events:
            await self.execute_with_retry(
                self._process_event,
                event,
                db,
                item_key=derive_worker_retry_key("automation_event", event.id),
            )

    async def _process_event(self, event: AutomationEvent, db: AsyncSession) -> None:
        """Run every active automation listening for ``event``'s type.

        The event is marked ``processed`` once all matching automations have
        been attempted. Per-(automation, event) dedupe (via the partial unique
        index and an explicit pre-check) keeps retries from double-running.
        Per-automation failures are recorded on the execution row and never
        abort the whole event (mirrors the contact-trigger path).
        """
        log = self.logger.bind(event_id=str(event.id), event_type=event.event_type)

        matches = await db.execute(
            select(Automation).where(
                Automation.workspace_id == event.workspace_id,
                Automation.is_active.is_(True),
                func.lower(Automation.trigger_type) == event.event_type.lower(),
            )
        )
        automations = list(matches.scalars().all())

        contact: Contact | None = None
        if event.contact_id is not None:
            contact = await db.get(Contact, event.contact_id)

        for automation in automations:
            await self._execute_event_for_automation(automation, event, contact, db)

        event.status = EVENT_STATUS_PROCESSED
        event.processed_at = datetime.now(UTC)
        log.info("Automation event processed", matched=len(automations))

    # ------------------------------------------------------------------ #
    # Automation evaluation                                                #
    # ------------------------------------------------------------------ #

    async def _evaluate_automation(self, automation: Automation, db: AsyncSession) -> None:
        """Evaluate a single automation: find matching contacts, run actions."""
        log = self.logger.bind(
            automation_id=str(automation.id),
            trigger_type=automation.trigger_type,
        )

        since = automation.last_evaluated_at or (
            datetime.now(UTC) - timedelta(days=DEFAULT_LOOKBACK_DAYS)
        )

        contacts = await self._get_trigger_contacts(automation, since, db)
        if not contacts:
            automation.last_evaluated_at = datetime.now(UTC)
            return

        log.info("Trigger matched contacts", count=len(contacts))

        for contact in contacts:
            await self.execute_with_retry(
                self._execute_for_contact,
                automation,
                contact,
                db,
                item_key=derive_worker_retry_key(
                    "automation", automation.id, "contact", contact.id
                ),
            )

        automation.last_evaluated_at = datetime.now(UTC)

    # ------------------------------------------------------------------ #
    # Trigger evaluators                                                   #
    # ------------------------------------------------------------------ #

    async def _get_trigger_contacts(
        self,
        automation: Automation,
        since: datetime,
        db: AsyncSession,
    ) -> list[Contact]:
        """Return contacts that match the automation's trigger and have not
        yet been processed by this automation."""

        trigger = automation.trigger_type.lower()

        # Sub-query: contacts already executed for this automation
        already_executed = (
            select(AutomationExecution.contact_id)
            .where(AutomationExecution.automation_id == automation.id)
            .scalar_subquery()
        )

        base_filters = [
            Contact.workspace_id == automation.workspace_id,
            not_(Contact.id.in_(already_executed)),
        ]

        if trigger in ("appointment_booked", "booking_created"):
            contacts = await self._contacts_appointment_booked(base_filters, since, db)

        elif trigger == "no_show":
            contacts = await self._contacts_no_show(base_filters, since, db)

        elif trigger == "contact_tagged":
            tag_name: str = automation.trigger_config.get("tag", "")
            contacts = await self._contacts_tagged(base_filters, tag_name, since, db)

        elif trigger == "never_booked":
            inactivity_days: int = int(
                automation.trigger_config.get("inactivity_days", DEFAULT_NEVER_BOOKED_DAYS)
            )
            contacts = await self._contacts_never_booked(base_filters, inactivity_days, db)

        elif trigger in AUTOMATION_EVENT_TRIGGERS:
            # Event-based triggers are handled by the event-draining path
            # (_process_events), not by polling contacts — skip silently.
            return []

        else:
            self.logger.warning(
                "Unknown trigger_type — skipping",
                trigger_type=automation.trigger_type,
                automation_id=str(automation.id),
            )
            return []

        return contacts

    async def _contacts_appointment_booked(
        self,
        base_filters: list[Any],
        since: datetime,
        db: AsyncSession,
    ) -> list[Contact]:
        """Contacts whose last appointment status became 'scheduled' recently."""
        result = await db.execute(
            select(Contact)
            .where(
                and_(
                    *base_filters,
                    Contact.last_appointment_status == "scheduled",
                    Contact.updated_at >= since,
                )
            )
            .limit(MAX_CONTACTS_PER_AUTOMATION)
        )
        return list(result.scalars().all())

    async def _contacts_no_show(
        self,
        base_filters: list[Any],
        since: datetime,
        db: AsyncSession,
    ) -> list[Contact]:
        """Contacts whose last appointment status became 'no_show' recently."""
        result = await db.execute(
            select(Contact)
            .where(
                and_(
                    *base_filters,
                    Contact.last_appointment_status == "no_show",
                    Contact.updated_at >= since,
                )
            )
            .limit(MAX_CONTACTS_PER_AUTOMATION)
        )
        return list(result.scalars().all())

    async def _contacts_tagged(
        self,
        base_filters: list[Any],
        tag_name: str,
        since: datetime,
        db: AsyncSession,
    ) -> list[Contact]:
        """Contacts who carry a specific normalized tag and were updated recently."""
        tag = tag_name.strip()
        if not tag:
            return []

        result = await db.execute(
            select(Contact)
            .join(ContactTag, ContactTag.contact_id == Contact.id)
            .join(Tag, Tag.id == ContactTag.tag_id)
            .where(
                and_(
                    *base_filters,
                    Tag.workspace_id == Contact.workspace_id,
                    Tag.name == tag,
                    Contact.updated_at >= since,
                )
            )
            .limit(MAX_CONTACTS_PER_AUTOMATION)
        )
        return list(result.scalars().all())

    async def _contacts_never_booked(
        self,
        base_filters: list[Any],
        inactivity_days: int,
        db: AsyncSession,
    ) -> list[Contact]:
        """Contacts who have at least one conversation but no appointments,
        and whose last conversation activity is older than *inactivity_days*.
        """
        cutoff = datetime.now(UTC) - timedelta(days=inactivity_days)

        # Must have at least one conversation
        has_conversation = exists(
            select(Conversation.id).where(Conversation.contact_id == Contact.id)
        )

        result = await db.execute(
            select(Contact)
            .where(
                and_(
                    *base_filters,
                    Contact.last_appointment_status.is_(None),
                    has_conversation,
                    Contact.updated_at <= cutoff,
                )
            )
            .limit(MAX_CONTACTS_PER_AUTOMATION)
        )
        return list(result.scalars().all())

    # ------------------------------------------------------------------ #
    # Action executor                                                      #
    # ------------------------------------------------------------------ #

    async def _execute_for_contact(
        self,
        automation: Automation,
        contact: Contact,
        db: AsyncSession,
    ) -> None:
        """Execute all actions for *automation* against a polling-matched *contact*."""
        execution = AutomationExecution(
            automation_id=automation.id,
            contact_id=contact.id,
            status="pending",
        )
        db.add(execution)
        await db.flush()  # get execution.id without committing
        await self._run_actions(automation, contact, {}, execution, db)

    async def _execute_event_for_automation(
        self,
        automation: Automation,
        event: AutomationEvent,
        contact: Contact | None,
        db: AsyncSession,
    ) -> None:
        """Execute *automation*'s actions for a single drained *event*.

        Idempotent per (automation, event): a pre-check (backed by the partial
        unique index ``uq_automation_execution_event``) means re-draining the
        same event never re-runs an automation that already executed for it.
        """
        existing = await db.execute(
            select(AutomationExecution.id)
            .where(
                AutomationExecution.automation_id == automation.id,
                AutomationExecution.event_id == event.id,
            )
            .limit(1)
        )
        if existing.first() is not None:
            return

        execution = AutomationExecution(
            automation_id=automation.id,
            contact_id=event.contact_id,
            event_id=event.id,
            status="pending",
        )
        db.add(execution)
        await db.flush()
        await self._run_actions(automation, contact, event.payload or {}, execution, db)

    async def _run_actions(  # noqa: PLR0912 - action dispatch is inherently branchy
        self,
        automation: Automation,
        contact: Contact | None,
        payload: dict[str, Any],
        execution: AutomationExecution,
        db: AsyncSession,
    ) -> None:
        """Run an automation's action list against *contact*, recording results.

        Shared by the polling-trigger and event-trigger paths. ``contact`` may
        be ``None`` for event triggers without an associated contact; actions
        that require one are skipped with a warning. ``payload`` provides extra
        template tokens (e.g. ``{rating}``, ``{stage}``) for message rendering.
        Never raises — failures are recorded on the execution row.
        """
        log = self.logger.bind(
            automation_id=str(automation.id),
            contact_id=contact.id if contact else None,
            execution_id=str(execution.id),
        )

        try:
            for action in automation.actions:
                action_type: str = str(action.get("type", "")).lower()
                action_config: dict[str, Any] = action.get("config", {})

                log.debug("Executing action", action_type=action_type)

                # Check approval gate (automation has no agent_id)
                decision, _gate_result = await approval_gate_service.check_and_execute_or_queue(
                    db=db,
                    agent_id=None,
                    workspace_id=automation.workspace_id,
                    action_type=action_type,
                    action_payload=action_config,
                    description=f"Automation '{automation.name}': {action_type}",
                    context={
                        "source": "automation",
                        "automation_id": str(automation.id),
                        "contact_id": contact.id if contact else None,
                    },
                )

                if decision == "pending":
                    log.info("automation_action_pending_approval", action_type=action_type)
                    continue
                elif decision == "blocked":
                    log.warning("automation_action_blocked", action_type=action_type)
                    continue

                # Actions targeting a contact are skipped when the (event)
                # trigger has none. Checking here lets mypy narrow ``contact``.
                if action_type in _CONTACT_ACTIONS and contact is None:
                    log.warning("automation_action_requires_contact", action_type=action_type)
                    continue

                if action_type == "send_sms" and contact is not None:
                    await self._action_send_sms(automation, contact, action_config, payload, db)

                elif action_type == "send_email" and contact is not None:
                    await self._action_send_email(automation, contact, action_config, payload, db)

                elif action_type == "make_call" and contact is not None:
                    await self._action_make_call(automation, contact, action_config, db)

                elif action_type == "enroll_campaign" and contact is not None:
                    await self._action_enroll_campaign(automation, contact, action_config, db)

                elif action_type in ("apply_tag", "add_tag") and contact is not None:
                    await self._action_apply_tag(contact, action_config, db)

                elif action_type in ("wait", "delay"):
                    # Schedule the execution for later — skip remaining actions
                    delay_hours: int = int(action_config.get("hours", 1))
                    execution.status = "scheduled"
                    execution.scheduled_for = datetime.now(UTC) + timedelta(hours=delay_hours)
                    log.info(
                        "Action delayed",
                        delay_hours=delay_hours,
                        scheduled_for=execution.scheduled_for.isoformat(),
                    )
                    return  # Do not mark as completed yet

                else:
                    log.warning(
                        "Unknown action type — skipping",
                        action_type=action_type,
                    )

            execution.status = "completed"
            execution.executed_at = datetime.now(UTC)
            automation.last_triggered_at = datetime.now(UTC)
            await self._notify_automation_triggered(automation, contact, execution, db)
            log.info("Automation executed successfully")

        except Exception as exc:
            execution.status = "failed"
            execution.error = str(exc)
            log.exception("Automation execution failed", error=str(exc))

    async def _notify_automation_triggered(
        self,
        automation: Automation,
        contact: Contact | None,
        execution: AutomationExecution,
        db: AsyncSession,
    ) -> None:
        """Push + email workspace members when an automation runs (best-effort)."""
        from app.services.notifications import notify_workspace_event

        title = "Automation triggered"
        body = f"Automation '{automation.name}' ran for your workspace."
        details = {
            "Automation": automation.name,
            "Trigger": automation.trigger_type,
        }
        if contact is not None:
            who = contact.full_name or contact.email or contact.phone_number
            if who:
                details["Contact"] = who
        try:
            await notify_workspace_event(
                db,
                workspace_id=automation.workspace_id,
                notification_type="automation",
                title=title,
                body=body,
                data={
                    "type": "automation",
                    "automationId": str(automation.id),
                    "screen": "/(tabs)/automations",
                },
                channel_id="automations",
                email_subject=title,
                email_heading="Automation Triggered",
                email_intro=body,
                email_details=details,
                dedupe_key=str(execution.id),
            )
        except Exception:
            self.logger.warning(
                "automation_notification_failed",
                automation_id=str(automation.id),
            )

    # ------------------------------------------------------------------ #
    # Individual action implementations                                    #
    # ------------------------------------------------------------------ #

    async def _action_send_sms(
        self,
        automation: Automation,
        contact: Contact,
        config: dict[str, Any],
        payload: dict[str, Any],
        db: AsyncSession,
    ) -> None:
        """Send an SMS to the contact.

        Config keys:
            message (str): Template string; supports {first_name}, {last_name},
                           {full_name}, {company_name}, {email}, and any event
                           payload token (e.g. {rating}, {stage}).
        """
        message_template: str = config.get("message", "")
        if not message_template:
            self.logger.warning(
                "send_sms action has no message template",
                automation_id=str(automation.id),
            )
            return

        if not contact.phone_number:
            self.logger.warning(
                "Contact has no phone number",
                contact_id=contact.id,
            )
            return

        message_body = self._render_template(message_template, contact, payload)

        from_number = await self._resolve_from_number(db, contact.id, automation.workspace_id)
        if not from_number:
            self.logger.warning(
                "No from-number available for workspace",
                workspace_id=str(automation.workspace_id),
            )
            return

        sms_service = get_text_message_provider()
        try:
            idempotency_key = derive_outbound_key("automation_sms", automation.id, contact.id)
            await sms_service.send_message(
                to_number=contact.phone_number,
                from_number=from_number,
                body=message_body,
                db=db,
                workspace_id=automation.workspace_id,
                idempotency_key=idempotency_key,
            )
            self.logger.info(
                "Automation SMS sent",
                contact_id=contact.id,
                to=contact.phone_number,
            )
        finally:
            await sms_service.close()

    async def _action_send_email(
        self,
        automation: Automation,
        contact: Contact,
        config: dict[str, Any],
        payload: dict[str, Any],
        db: AsyncSession,
    ) -> None:
        """Send a transactional email to the contact via Resend.

        Config keys:
            subject (str): Subject template (placeholders supported).
            message / body (str): Body template (placeholders supported). Plain
                text is rendered into a simple HTML paragraph block.
        """
        subject_template: str = config.get("subject", "")
        body_template: str = config.get("message") or config.get("body") or ""
        if not subject_template or not body_template:
            self.logger.warning(
                "send_email action missing subject or body",
                automation_id=str(automation.id),
            )
            return

        if not contact.email:
            self.logger.warning("Contact has no email", contact_id=contact.id)
            return

        subject = self._render_template(subject_template, contact, payload)
        body = self._render_template(body_template, contact, payload)
        idempotency_key = derive_outbound_key("automation_email", automation.id, contact.id)

        sent = await send_automation_email(
            to_email=contact.email,
            subject=subject,
            body=body,
            idempotency_key=idempotency_key,
        )
        if sent:
            self.logger.info(
                "Automation email sent",
                contact_id=contact.id,
                to=contact.email,
            )
        else:
            self.logger.warning(
                "Automation email not sent (provider unavailable or failed)",
                contact_id=contact.id,
            )

    async def _action_make_call(
        self,
        automation: Automation,
        contact: Contact,
        config: dict[str, Any],
        db: AsyncSession,
    ) -> None:
        """Initiate an outbound AI voice call to the contact via Telnyx.

        Config keys:
            agent_id (str, optional): Voice agent UUID to handle the call.
            connection_id (str, optional): Telnyx connection id override.
        """
        if not settings.telnyx_api_key:
            self.logger.warning(
                "make_call action skipped: Telnyx not configured",
                automation_id=str(automation.id),
            )
            return
        if not contact.phone_number:
            self.logger.warning("Contact has no phone number", contact_id=contact.id)
            return

        from_number = await self._resolve_from_number(
            db, contact.id, automation.workspace_id, voice=True
        )
        if not from_number:
            self.logger.warning(
                "No voice from-number available for workspace",
                workspace_id=str(automation.workspace_id),
            )
            return

        agent_id: uuid.UUID | None = None
        agent_id_str = str(config.get("agent_id", "")).strip()
        if agent_id_str:
            try:
                agent_id = uuid.UUID(agent_id_str)
            except ValueError:
                self.logger.warning("make_call has invalid agent_id", agent_id=agent_id_str)
                return

        api_base = settings.api_base_url or "http://localhost:8000"
        webhook_url = f"{api_base}/webhooks/telnyx/voice"
        connection_id = str(config.get("connection_id", "")) or settings.telnyx_connection_id

        voice_service = TelnyxVoiceService(settings.telnyx_api_key)
        idempotency_key = derive_outbound_key("automation_call", automation.id, contact.id)
        try:
            await voice_service.initiate_call(
                to_number=contact.phone_number,
                from_number=from_number,
                connection_id=connection_id or None,
                webhook_url=webhook_url,
                db=db,
                workspace_id=automation.workspace_id,
                contact_phone=contact.phone_number,
                agent_id=agent_id,
                idempotency_key=idempotency_key,
            )
        finally:
            await voice_service.close()
        self.logger.info(
            "Automation call initiated",
            contact_id=contact.id,
            to=contact.phone_number,
        )

    async def _action_enroll_campaign(
        self,
        automation: Automation,
        contact: Contact,
        config: dict[str, Any],
        db: AsyncSession,
    ) -> None:
        """Enroll the contact into a campaign.

        Config keys:
            campaign_id (str): UUID of the target campaign.
        """
        campaign_id_str: str = str(config.get("campaign_id", ""))
        if not campaign_id_str:
            self.logger.warning(
                "enroll_campaign action missing campaign_id",
                automation_id=str(automation.id),
            )
            return

        try:
            campaign_id = uuid.UUID(campaign_id_str)
        except ValueError:
            self.logger.warning(
                "enroll_campaign has invalid campaign_id",
                campaign_id=campaign_id_str,
            )
            return

        # Verify the campaign exists and belongs to the same workspace
        campaign_result = await db.execute(
            select(Campaign).where(
                and_(
                    Campaign.id == campaign_id,
                    Campaign.workspace_id == automation.workspace_id,
                    Campaign.status.in_(
                        [
                            CampaignStatus.RUNNING.value,
                            CampaignStatus.SCHEDULED.value,
                        ]
                    ),
                )
            )
        )
        campaign = campaign_result.scalar_one_or_none()
        if not campaign:
            self.logger.warning(
                "enroll_campaign: campaign not found or not active",
                campaign_id=str(campaign_id),
            )
            return

        # Upsert campaign_contact (ignore if already enrolled)
        stmt = (
            pg_insert(CampaignContact)
            .values(
                id=uuid.uuid4(),
                campaign_id=campaign_id,
                contact_id=contact.id,
                status=CampaignContactStatus.PENDING.value,
                messages_sent=0,
                messages_received=0,
                follow_ups_sent=0,
                opted_out=False,
                is_qualified=False,
                priority=0,
            )
            .on_conflict_do_nothing(
                constraint="uq_campaign_contact",
            )
        )
        await db.execute(stmt)

        # Increment total_contacts counter (best-effort; may be slightly off
        # if the row already existed and on_conflict_do_nothing fired)
        campaign.total_contacts += 1

        self.logger.info(
            "Contact enrolled in campaign",
            contact_id=contact.id,
            campaign_id=str(campaign_id),
        )

    async def _action_apply_tag(
        self,
        contact: Contact,
        config: dict[str, Any],
        db: AsyncSession,
    ) -> None:
        """Apply a normalized workspace tag to the contact.

        Config keys:
            tag (str): Tag name to apply.
        """
        tag: str = str(config.get("tag", "")).strip()
        if not tag:
            self.logger.warning(
                "apply_tag action missing tag value",
                contact_id=contact.id,
            )
            return

        await TagService(db).add_tag_to_contact(
            workspace_id=contact.workspace_id,
            contact_id=contact.id,
            name=tag,
        )
        self.logger.info(
            "Tag applied to contact",
            contact_id=contact.id,
            tag=tag,
        )

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _render_template(
        self,
        template: str,
        contact: Contact,
        payload: dict[str, Any] | None = None,
    ) -> str:
        """Replace simple {placeholder} tokens in a message template.

        Contact tokens take precedence; event ``payload`` keys fill in extras
        like ``{rating}`` or ``{stage}``. Unknown tokens are left untouched.
        """
        full_name = " ".join(filter(None, [contact.first_name, contact.last_name]))
        replacements: dict[str, str] = {
            str(key): "" if value is None else str(value) for key, value in (payload or {}).items()
        }
        replacements.update(
            {
                "first_name": contact.first_name or "",
                "last_name": contact.last_name or "",
                "full_name": full_name,
                "company_name": contact.company_name or "",
                "email": contact.email or "",
            }
        )
        result = template
        for key, value in replacements.items():
            result = result.replace(f"{{{key}}}", value)
        return result

    async def _resolve_from_number(
        self,
        db: AsyncSession,
        contact_id: int,
        workspace_id: uuid.UUID,
        *,
        voice: bool = False,
    ) -> str | None:
        """Resolve the best from-number for an outbound automation message/call.

        Strategy 1: Reuse the number from an existing conversation with this
                     contact in this workspace.
        Strategy 2: Any active phone number owned by the workspace that has the
                     required capability (``voice_enabled`` or ``sms_enabled``).
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

        # Strategy 2 — any workspace number with the required capability
        capability = (
            PhoneNumber.voice_enabled.is_(True) if voice else PhoneNumber.sms_enabled.is_(True)
        )
        result = await db.execute(
            select(PhoneNumber.phone_number)
            .where(
                and_(
                    PhoneNumber.workspace_id == workspace_id,
                    PhoneNumber.is_active.is_(True),
                    capability,
                )
            )
            .order_by(PhoneNumber.created_at)
            .limit(1)
        )
        phone = result.scalar_one_or_none()
        if phone:
            return str(phone)

        return None


# ---------------------------------------------------------------------------
# Singleton registry (mirrors the pattern used by all other workers)
# ---------------------------------------------------------------------------

_registry = WorkerRegistry(AutomationWorker)
start_automation_worker = _registry.start
stop_automation_worker = _registry.stop
get_automation_worker = _registry.get
