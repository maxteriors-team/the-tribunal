"""Automation worker — evaluates trigger-based automations and executes their actions.

Poll cycle
----------
1. Load all active automations.
2. For each automation evaluate its trigger to find matching contacts that have
   NOT yet been processed (no row in ``automation_executions``).
3. For each new matching contact, execute every action in the automation's
   ``actions`` list.
4. Record an ``AutomationExecution`` row so the contact is not re-processed.
5. Update ``automation.last_evaluated_at`` so subsequent cycles can bound
   contact queries by recency (avoiding full-table scans on large datasets).

Supported trigger_type values
------------------------------
- ``appointment_booked``  / ``booking_created``  : contact.last_appointment_status == "scheduled"
- ``no_show``                                     : contact.last_appointment_status == "no_show"
- ``contact_tagged``                              : contact has a specific tag, tagged recently
- ``never_booked``                                : contact has conversations but no appointments,
                                                    last contact older than N days

Supported action type values
-----------------------------
- ``send_sms``       : send an SMS via Telnyx using a resolved from-number
- ``enroll_campaign``: create a CampaignContact record (idempotent via upsert)
- ``apply_tag``      : add a tag string to contact.tags (ARRAY column)
- ``wait`` / ``delay``: no-op in the current cycle (action is recorded as
                        "scheduled" and re-evaluated on subsequent poll)
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, exists, not_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.automation import Automation
from app.models.automation_execution import AutomationExecution
from app.models.campaign import Campaign, CampaignContact, CampaignContactStatus, CampaignStatus
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.phone_number import PhoneNumber
from app.services.approval.approval_gate_service import approval_gate_service
from app.services.telephony.telnyx import TelnyxSMSService
from app.workers.base import BaseWorker, WorkerRegistry
from app.workers.retryable import RetryableWorker

# Maximum contacts to process per automation per poll cycle.
MAX_CONTACTS_PER_AUTOMATION = 50

# Default look-back window when last_evaluated_at is None (first run).
DEFAULT_LOOKBACK_DAYS = 30

# Default "never booked" inactivity threshold (days).
DEFAULT_NEVER_BOOKED_DAYS = 7


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
        """Load active automations and evaluate each one."""
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Automation).where(Automation.is_active.is_(True)))
            automations = result.scalars().all()

            if not automations:
                return

            self.logger.debug("Evaluating automations", count=len(automations))

            for automation in automations:
                await self.execute_with_retry(
                    self._evaluate_automation,
                    automation,
                    db,
                    item_key=f"automation:{automation.id}",
                )

            await db.commit()

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
                item_key=f"automation:{automation.id}:contact:{contact.id}",
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
        """Contacts who carry a specific tag and were updated recently.

        The ``tags`` column is a PostgreSQL ARRAY(Text).  SQLAlchemy exposes
        the ``any_()`` / ``contains()`` operators for array columns.
        """
        if not tag_name:
            return []

        # ARRAY contains operator: Contact.tags.any_(tag_name) works for
        # simple text arrays — fall back to a "contains" style filter.
        result = await db.execute(
            select(Contact)
            .where(
                and_(
                    *base_filters,
                    Contact.tags.is_not(None),
                    Contact.tags.contains([tag_name]),
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
        """Execute all actions for *automation* against *contact*,
        then record the execution."""

        log = self.logger.bind(
            automation_id=str(automation.id),
            contact_id=contact.id,
        )

        execution = AutomationExecution(
            automation_id=automation.id,
            contact_id=contact.id,
            status="pending",
        )
        db.add(execution)
        await db.flush()  # get execution.id without committing

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
                        "contact_id": contact.id,
                    },
                )

                if decision == "pending":
                    log.info("automation_action_pending_approval", action_type=action_type)
                    continue
                elif decision == "blocked":
                    log.warning("automation_action_blocked", action_type=action_type)
                    continue

                if action_type == "send_sms":
                    await self._action_send_sms(automation, contact, action_config, db)

                elif action_type == "enroll_campaign":
                    await self._action_enroll_campaign(automation, contact, action_config, db)

                elif action_type == "apply_tag":
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
            log.info("Automation executed successfully")

        except Exception as exc:
            execution.status = "failed"
            execution.error = str(exc)
            log.exception("Automation execution failed", error=str(exc))

    # ------------------------------------------------------------------ #
    # Individual action implementations                                    #
    # ------------------------------------------------------------------ #

    async def _action_send_sms(
        self,
        automation: Automation,
        contact: Contact,
        config: dict[str, Any],
        db: AsyncSession,
    ) -> None:
        """Send an SMS to the contact.

        Config keys:
            message (str): Template string; supports {first_name}, {last_name},
                           {full_name}, {company_name}.
        """
        if not settings.telnyx_api_key:
            self.logger.warning("No Telnyx API key configured; cannot send automation SMS")
            return

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

        message_body = self._render_template(message_template, contact)

        from_number = await self._resolve_from_number(db, contact.id, automation.workspace_id)
        if not from_number:
            self.logger.warning(
                "No from-number available for workspace",
                workspace_id=str(automation.workspace_id),
            )
            return

        sms_service = TelnyxSMSService(settings.telnyx_api_key)
        try:
            await sms_service.send_message(
                to_number=contact.phone_number,
                from_number=from_number,
                body=message_body,
                db=db,
                workspace_id=automation.workspace_id,
            )
            self.logger.info(
                "Automation SMS sent",
                contact_id=contact.id,
                to=contact.phone_number,
            )
        finally:
            await sms_service.close()

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
        db: AsyncSession,  # noqa: ARG002
    ) -> None:
        """Append a tag to contact.tags (ARRAY column).

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

        existing: list[str] = list(contact.tags or [])
        if tag not in existing:
            contact.tags = existing + [tag]
            self.logger.info(
                "Tag applied to contact",
                contact_id=contact.id,
                tag=tag,
            )

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _render_template(self, template: str, contact: Contact) -> str:
        """Replace simple {placeholder} tokens in a message template."""
        full_name = " ".join(filter(None, [contact.first_name, contact.last_name]))
        replacements: dict[str, str] = {
            "first_name": contact.first_name or "",
            "last_name": contact.last_name or "",
            "full_name": full_name,
            "company_name": contact.company_name or "",
            "email": contact.email or "",
        }
        result = template
        for key, value in replacements.items():
            result = result.replace(f"{{{key}}}", value)
        return result

    async def _resolve_from_number(
        self,
        db: AsyncSession,
        contact_id: int,
        workspace_id: uuid.UUID,
    ) -> str | None:
        """Resolve the best from-number for an outbound automation SMS.

        Strategy 1: Reuse the number from an existing conversation with this
                     contact in this workspace.
        Strategy 2: Any active, SMS-enabled phone number owned by the workspace.
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

        # Strategy 2 — any workspace number
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


# ---------------------------------------------------------------------------
# Singleton registry (mirrors the pattern used by all other workers)
# ---------------------------------------------------------------------------

_registry = WorkerRegistry(AutomationWorker)
start_automation_worker = _registry.start
stop_automation_worker = _registry.stop
get_automation_worker = _registry.get
