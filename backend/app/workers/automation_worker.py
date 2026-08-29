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

Condition triggers (evaluated against workspace state, no contact matching):

- ``backlog_below_threshold`` : weeks of booked work fell under the owner's
  threshold, so demand generation should fire. Evaluated once per automation per
  cycle, cooldown-gated, and skipped entirely when crew capacity is unset. See
  :mod:`app.services.automations.conditions`.

Supported action type values
-----------------------------
- ``send_sms``       : send an SMS via Telnyx using a resolved from-number
- ``send_email``     : send an email via Resend to the contact's email
- ``make_call``      : initiate an outbound AI voice call via Telnyx
- ``enroll_campaign``: create a CampaignContact record (idempotent via upsert)
- ``start_drip_campaign``: activate a reactivation drip sequence (and enroll the
                      matched contact when the trigger has one)
- ``apply_tag`` / ``add_tag`` : add a normalized workspace tag to the contact
- ``move_to_stage`` : move the contact's / event's open opportunity to a pipeline
                      stage, creating one in that pipeline when the contact has none
                      (idempotent; re-firing against a settled stage emits nothing)
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
from app.db.session import system_session
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
from app.models.drip_campaign import DripCampaign, DripCampaignStatus
from app.models.email_template import EmailTemplate
from app.models.opportunity import Opportunity
from app.models.phone_number import PhoneNumber
from app.models.pipeline import Pipeline, PipelineStage
from app.models.tag import ContactTag, Tag
from app.models.workspace import Workspace
from app.services.approval.approval_gate_service import approval_gate_service
from app.services.automations.branching import contact_matches_rules, parse_branch_condition
from app.services.automations.conditions import (
    AUTOMATION_CONDITION_TRIGGERS,
    CONDITION_BACKLOG_BELOW_THRESHOLD,
    evaluate_backlog_condition,
)
from app.services.automations.events import (
    AUTOMATION_EVENT_TRIGGERS,
    event_matches_trigger_config,
)
from app.services.automations.opt_out import (
    NO_AUTOMATION_TAG,
    automation_suppressed,
    no_automation_tag_exists,
)
from app.services.automations.runner import (
    END_OF_WORKFLOW,
    MAX_RESUMES,
    MAX_STEPS_PER_RUN,
    WorkflowStep,
    branch_targets,
    normalize_steps,
    step_at,
    wait_duration,
)
from app.services.compliance.quiet_hours import parse_clock
from app.services.email import send_automation_email, send_template_email
from app.services.email_layout import EmailCategory
from app.services.email_opt_out import build_email_unsubscribe_url, email_suppressed
from app.services.idempotency import derive_outbound_key, derive_worker_retry_key
from app.services.lead_sources.attribution_service import (
    snapshot_contact_attribution_on_opportunity,
)
from app.services.leads.funnel_transitions import mark_contact_contacted
from app.services.opportunities.lead_opportunity import opportunity_name
from app.services.outbound.delivery import (
    OutboundDeliveryChannel,
    OutboundDeliveryRequest,
    OutboundDeliveryResult,
    outbound_delivery_service,
)
from app.services.reactivation.drip_runner import enroll_contacts
from app.services.reporting.capacity_service import CapacityService
from app.services.tags import TagService
from app.services.telephony.telnyx_voice import TelnyxVoiceService
from app.utils.phone import normalize_phone_safe
from app.utils.timezones import workspace_timezone_name
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

# Step types handled by the cursor loop itself rather than dispatched as an
# action: they move the cursor instead of doing something to a customer, and so
# never pass through the approval gate.
_WAIT_STEPS = frozenset({"wait", "delay"})
_BRANCH_STEP = "branch"

# Executions resumed per poll cycle. Bounds the work one cycle can pick up when
# a large drip comes due all at once.
MAX_RESUMES_PER_CYCLE = 100


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
        """Resume due workflows, drain queued events, evaluate polling triggers."""
        async with system_session("automation_worker sweeps every workspace") as db:
            # 0) Workflows parked on a ``wait`` whose time has come. First so a
            #    customer mid-sequence is served before new work is taken on.
            await self._resume_scheduled_executions(db)

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

    @staticmethod
    def _acquisition_funnel_id(automation: Automation) -> str | None:
        """Return the explicit acquisition funnel identifier, if configured."""
        value = (automation.trigger_config or {}).get("funnel_id")
        normalized = str(value).strip() if value is not None else ""
        return normalized or None

    # ------------------------------------------------------------------ #
    # Resuming parked workflows                                            #
    # ------------------------------------------------------------------ #

    async def _resume_scheduled_executions(self, db: AsyncSession) -> None:
        """Continue workflows whose ``wait`` has elapsed.

        This is the other half of the ``wait`` step. Without it a parked run is
        simply abandoned: the row sits at ``status='scheduled'`` forever and the
        customer never receives the rest of the sequence.

        Ordering by ``scheduled_for`` serves the longest-overdue customer first,
        which is the fair thing to do when a backlog builds. The query is served
        by the existing ``ix_automation_executions_status_scheduled_for`` index.
        """
        now = datetime.now(UTC)
        result = await db.execute(
            select(AutomationExecution)
            .where(
                AutomationExecution.status == "scheduled",
                AutomationExecution.scheduled_for.is_not(None),
                AutomationExecution.scheduled_for <= now,
            )
            .order_by(AutomationExecution.scheduled_for)
            .limit(MAX_RESUMES_PER_CYCLE)
        )
        executions = list(result.scalars().all())
        if not executions:
            return

        self.logger.info("Resuming scheduled automations", count=len(executions))
        for execution in executions:
            await self.execute_with_retry(
                self._resume_execution,
                execution,
                db,
                item_key=derive_worker_retry_key("automation_resume", execution.id),
            )

    async def _resume_execution(self, execution: AutomationExecution, db: AsyncSession) -> None:
        """Re-enter one parked run at its saved cursor.

        Re-reads the automation and contact rather than trusting anything held
        across the wait — either may have been edited, deactivated or deleted in
        the interim, and a run must not outlive the automation that owns it.
        """
        log = self.logger.bind(
            execution_id=str(execution.id),
            automation_id=str(execution.automation_id),
            step_index=execution.step_index,
        )

        if execution.resume_count >= MAX_RESUMES:
            # A goto cycle with a wait inside it resumes politely and forever;
            # this is where that run is stopped and made visible.
            execution.status = "failed"
            execution.error = (
                f"Workflow resumed {MAX_RESUMES} times without finishing — "
                "check the branch targets for a loop."
            )
            execution.scheduled_for = None
            log.error("automation_resume_budget_exhausted", resume_count=execution.resume_count)
            return

        automation = await db.get(Automation, execution.automation_id)
        if automation is None or not automation.is_active:
            # Paused mid-wait is a deliberate operator act: stop the run rather
            # than deliver the back half of a sequence they switched off.
            execution.status = "failed"
            execution.error = "Automation was deleted or deactivated during a wait step"
            execution.scheduled_for = None
            log.info("automation_resume_abandoned", reason="automation_inactive")
            return

        contact: Contact | None = None
        if execution.contact_id is not None:
            contact = await db.get(Contact, execution.contact_id)
            if contact is None:
                execution.status = "failed"
                execution.error = "Contact was deleted during a wait step"
                execution.scheduled_for = None
                log.info("automation_resume_abandoned", reason="contact_missing")
                return

        if (
            contact is not None
            and self._acquisition_funnel_id(automation) is not None
            and contact.last_appointment_status == "scheduled"
        ):
            execution.status = "completed"
            execution.error = "Acquisition funnel stopped after appointment booking"
            execution.scheduled_for = None
            execution.executed_at = datetime.now(UTC)
            log.info("automation_resume_completed", reason="appointment_booked")
            return

        # Consent can be withdrawn during a wait, and a parked run is exactly
        # where that is most likely to happen. Re-check before sending the rest.
        if contact is not None and await automation_suppressed(
            db, automation.workspace_id, contact.id
        ):
            execution.status = "failed"
            execution.error = f"Contact tagged '{NO_AUTOMATION_TAG}' during a wait step"
            execution.scheduled_for = None
            log.info("automation_resume_abandoned", reason="no_automation_tag")
            return

        execution.resume_count += 1
        execution.status = "pending"
        execution.scheduled_for = None

        log.info("automation_resumed", resume_count=execution.resume_count)
        await self._run_actions(automation, contact, execution.context or {}, execution, db)

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

        # Some event triggers support selectors in trigger_config. Apply them
        # before creating an execution so a source-specific lead workflow — or
        # a lighting-install owner guide — cannot fire on an unrelated event.
        automations = [
            automation
            for automation in automations
            if event_matches_trigger_config(
                event.event_type, automation.trigger_config, event.payload
            )
        ]

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

        # Condition triggers watch workspace state, not contacts: they fire once
        # for the workspace instead of once per matched contact.
        if automation.trigger_type.lower() in AUTOMATION_CONDITION_TRIGGERS:
            await self._evaluate_condition(automation, db)
            return

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
    # Condition triggers (workspace state)                                 #
    # ------------------------------------------------------------------ #

    async def _evaluate_condition(self, automation: Automation, db: AsyncSession) -> None:
        """Route a condition trigger to its evaluator."""
        if automation.trigger_type.lower() == CONDITION_BACKLOG_BELOW_THRESHOLD:
            await self._evaluate_backlog_condition(automation, db)
            return

        self.logger.warning(
            "Unhandled condition trigger — skipping",
            trigger_type=automation.trigger_type,
            automation_id=str(automation.id),
        )

    async def _evaluate_backlog_condition(self, automation: Automation, db: AsyncSession) -> None:
        """Fire demand generation when weeks of booked work fall under the line.

        Reads the fuel gauge (``CapacityService.compute_backlog``) and defers the
        verdict to :func:`~app.services.automations.conditions.evaluate_backlog_condition`,
        which owns the two rules that make this safe to aim at a whole customer
        list: skip silently when ``backlog_weeks`` is ``None`` (capacity unset —
        an unreadable gauge, not an empty tank), and stay quiet for
        ``cooldown_days`` after a fire so a slow month cannot blast the database
        every poll cycle.

        The execution row carries no ``contact_id``/``event_id``: a condition is
        caused by the business, not a person. Postgres treats NULLs as distinct
        in ``uq_automation_execution_contact``, so repeat fires insert cleanly and
        the cooldown — not a unique index — is what bounds them.
        """
        log = self.logger.bind(
            automation_id=str(automation.id),
            trigger_type=automation.trigger_type,
        )

        report = await CapacityService(db).compute_backlog(automation.workspace_id)
        decision = evaluate_backlog_condition(
            automation.trigger_config,
            backlog_weeks=report.backlog_weeks,
            last_triggered_at=automation.last_triggered_at,
        )
        automation.last_evaluated_at = datetime.now(UTC)

        if not decision.should_fire:
            log.debug(
                "backlog_condition_not_fired",
                reason=decision.reason,
                backlog_weeks=decision.backlog_weeks,
                threshold_weeks=decision.threshold_weeks,
                cooldown_until=(
                    None if decision.cooldown_until is None else decision.cooldown_until.isoformat()
                ),
            )
            return

        log.info(
            "backlog_condition_fired",
            backlog_weeks=decision.backlog_weeks,
            threshold_weeks=decision.threshold_weeks,
            cooldown_days=decision.cooldown_days,
        )

        execution = AutomationExecution(
            automation_id=automation.id,
            contact_id=None,
            status="pending",
        )
        db.add(execution)
        await db.flush()
        await self._run_actions(
            automation,
            None,
            {
                "backlog_weeks": decision.backlog_weeks,
                "threshold_weeks": decision.threshold_weeks,
                "backlog_hours": report.backlog_hours,
                "weekly_capacity_hours": report.weekly_capacity_hours,
                "open_job_count": report.job_count,
            },
            execution,
            db,
        )

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
            # The ``no-automation`` kill switch is enforced at
            # ``emit_automation_event`` for event triggers, which polling
            # triggers never pass through — so without this a muted customer
            # still gets texted by never_booked/no_show/contact_tagged.
            not_(no_automation_tag_exists(automation.workspace_id, Contact.id)),
        ]

        if trigger == "booking_created":
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

        elif trigger in AUTOMATION_CONDITION_TRIGGERS:
            # Condition triggers are evaluated against workspace state by
            # _evaluate_condition, which never reaches this contact query.
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
        if await automation_suppressed(db, automation.workspace_id, contact.id):
            return
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
        if contact is not None and await automation_suppressed(
            db, automation.workspace_id, contact.id
        ):
            return

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
        """Walk an automation's steps against *contact* from the saved cursor.

        Shared by the polling-trigger, event-trigger and resume paths.
        ``contact`` may be ``None`` for event triggers without an associated
        contact; steps that require one are skipped with a warning. ``payload``
        provides extra template tokens (e.g. ``{rating}``, ``{stage}``).

        The walk starts at ``execution.step_index``, which is why a workflow
        survives a ``wait``: hitting one persists the *next* cursor and returns
        with the row left ``scheduled``, and a later cycle re-enters here to
        finish the sequence. ``payload`` is merged into ``execution.context`` and
        saved for the same reason — the trigger's tokens are an in-memory
        argument that would otherwise be gone by the time the run resumes.

        Never raises — failures are recorded on the execution row.
        """
        log = self.logger.bind(
            automation_id=str(automation.id),
            contact_id=contact.id if contact else None,
            execution_id=str(execution.id),
        )

        steps = normalize_steps(automation.actions)

        # Persisted context wins on nothing: the live payload refreshes tokens
        # for the step about to run, while keys captured at trigger time survive
        # a wait. Assigned back so the merge is durable for the next resume.
        context: dict[str, Any] = {**(execution.context or {}), **(payload or {})}
        execution.context = context

        cursor = execution.step_index or 0
        steps_run = 0

        try:
            while True:
                step = step_at(steps, cursor)
                if step is None:
                    break  # Cursor ran off the end — the workflow is finished.

                if steps_run >= MAX_STEPS_PER_RUN:
                    # Only reachable via a backward goto. Failing loudly is the
                    # point: a looping workflow is misauthored, and quietly
                    # truncating it would hide that while it kept messaging.
                    execution.status = "failed"
                    execution.error = (
                        f"Workflow ran {MAX_STEPS_PER_RUN} steps in one cycle without "
                        "finishing — check the branch targets for a loop."
                    )
                    execution.step_index = cursor
                    log.error(
                        "automation_step_budget_exhausted",
                        step_index=cursor,
                        steps_run=steps_run,
                    )
                    return
                steps_run += 1

                if step.type in _WAIT_STEPS:
                    delay = wait_duration(step.config)
                    if delay <= timedelta():
                        cursor += 1  # An explicit zero wait is a no-op.
                        continue
                    # Park the run. The cursor points *past* the wait so the
                    # resume does not re-serve the same delay forever.
                    execution.step_index = cursor + 1
                    execution.status = "scheduled"
                    execution.scheduled_for = datetime.now(UTC) + delay
                    log.info(
                        "automation_step_waiting",
                        step_index=cursor,
                        delay_seconds=int(delay.total_seconds()),
                        scheduled_for=execution.scheduled_for.isoformat(),
                    )
                    return  # Do not mark completed — this run is unfinished.

                if step.type == _BRANCH_STEP:
                    cursor = await self._resolve_branch(automation, contact, steps, step, db, log)
                    continue

                status_before_step = contact.status if contact is not None else None
                delivery_result = await self._execute_step(
                    automation, contact, step, context, db, log
                )
                if (
                    automation.trigger_type == "lead_created"
                    and step.type == "send_sms"
                    and contact is not None
                    and status_before_step == "new"
                    and delivery_result is not None
                    and delivery_result.delivered
                ):
                    await mark_contact_contacted(db, contact)
                cursor += 1

            execution.step_index = max(cursor, 0)
            execution.status = "completed"
            execution.executed_at = datetime.now(UTC)
            automation.last_triggered_at = datetime.now(UTC)
            await self._notify_automation_triggered(automation, contact, execution, db)
            log.info("Automation executed successfully", steps_run=steps_run)

        except Exception as exc:
            execution.status = "failed"
            execution.error = str(exc)
            execution.step_index = max(cursor, 0)
            log.exception("Automation execution failed", error=str(exc))

    async def _resolve_branch(
        self,
        automation: Automation,
        contact: Contact | None,
        steps: list[WorkflowStep],
        step: WorkflowStep,
        db: AsyncSession,
        log: Any,
    ) -> int:
        """Evaluate a ``branch`` step and return the cursor to continue at.

        A contactless trigger (workspace conditions) has nobody to ask about, so
        the condition cannot be true; such a run takes the else-path.
        """
        when_true, when_false = branch_targets(steps, step)
        rules, logic = parse_branch_condition(step.config)

        if contact is None:
            matched = False
        else:
            matched = await contact_matches_rules(
                db,
                workspace_id=automation.workspace_id,
                contact_id=contact.id,
                rules=rules,
                logic=logic,
            )

        target = when_true if matched else when_false
        if target.dangling:
            log.warning(
                "automation_branch_target_missing",
                step_index=step.index,
                matched=matched,
                detail="branch names a step id that does not exist — ending run",
            )

        log.info(
            "automation_branch_evaluated",
            step_index=step.index,
            matched=matched,
            rule_count=len(rules),
            next_index=target.index,
        )
        # END_OF_WORKFLOW is negative, which step_at() reads as "finished".
        return target.index if target.index != END_OF_WORKFLOW else END_OF_WORKFLOW

    async def _execute_step(
        self,
        automation: Automation,
        contact: Contact | None,
        step: WorkflowStep,
        payload: dict[str, Any],
        db: AsyncSession,
        log: Any,
    ) -> OutboundDeliveryResult | None:
        """Run one side-effecting step: approval gate, then dispatch.

        Control-flow steps (``wait``, ``branch``) never reach here — they move
        the cursor instead of acting on a customer, so gating them for approval
        would ask an operator to authorise a delay.
        """
        if (
            step.type == "send_sms"
            and contact is not None
            and self._acquisition_funnel_id(automation) is not None
            and contact.last_appointment_status == "scheduled"
        ):
            log.info("automation_sms_skipped", reason="appointment_booked")
            return None
        action_type = step.type
        action_config = step.config

        log.debug("Executing action", action_type=action_type, step_index=step.index)

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
            return None
        elif decision == "blocked":
            log.warning("automation_action_blocked", action_type=action_type)
            return None

        # Actions targeting a contact are skipped when the (event)
        # trigger has none. Checking here lets mypy narrow ``contact``.
        if action_type in _CONTACT_ACTIONS and contact is None:
            log.warning("automation_action_requires_contact", action_type=action_type)
            return None

        if action_type == "send_sms" and contact is not None:
            return await self._action_send_sms(automation, contact, action_config, payload, db)
        elif action_type == "send_email" and contact is not None:
            await self._action_send_email(automation, contact, action_config, payload, db)

        elif action_type == "make_call" and contact is not None:
            await self._action_make_call(automation, contact, action_config, db)

        elif action_type == "enroll_campaign" and contact is not None:
            await self._action_enroll_campaign(automation, contact, action_config, db)

        elif action_type == "start_drip_campaign":
            # Not a _CONTACT_ACTION: starting a drip is a workspace-level
            # act, so a contactless condition trigger can launch one.
            await self._action_start_drip_campaign(automation, contact, action_config, db)

        elif action_type == "move_to_stage":
            # Not a _CONTACT_ACTION: the event path can carry an
            # opportunity_id with no contact, so the handler does its own
            # None-safe resolution.
            await self._action_move_to_stage(automation, contact, action_config, payload, db)

        elif action_type in ("apply_tag", "add_tag") and contact is not None:
            await self._action_apply_tag(contact, action_config, db)

        else:
            log.warning(
                "Unknown action type — skipping",
                action_type=action_type,
            )
        return None

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
    ) -> OutboundDeliveryResult | None:
        """Send an SMS to the contact.

        Config keys:
            message (str): Template string; supports {first_name}, {last_name},
                           {full_name}, {company_name}, {email}, and any event
                           payload token (e.g. {rating}, {stage}).
            fallbacks (dict): Optional per-token defaults used when a token
                           renders blank (e.g. {"first_name": "there"}).
            agent_id (UUID): AI agent that owns the SMS conversation.
            require_consent (bool): Require an explicit ``opted_in`` SMS status.
                           Defaults to False for legacy automations, but global
                           STOP/opt-out suppression always applies.
        """
        message_template: str = config.get("message", "")
        if not message_template:
            self.logger.warning(
                "send_sms action has no message template",
                automation_id=str(automation.id),
            )
            return None

        if not contact.phone_number:
            self.logger.warning(
                "Contact has no phone number",
                contact_id=contact.id,
            )
            return None

        # Leads can arrive with raw US numbers like "(248) 555-0123" from imports
        # or ad-platform webhooks; the provider requires E.164. Normalize here so
        # an unsendable number is skipped cleanly instead of raising downstream.
        to_number = normalize_phone_safe(contact.phone_number)
        if not to_number:
            self.logger.warning(
                "Contact phone not valid E.164 — skipping SMS",
                contact_id=contact.id,
            )
            return None

        message_body = self._render_template(
            message_template, contact, payload, config.get("fallbacks")
        )

        from_number = await self._resolve_from_number(db, contact.id, automation.workspace_id)
        if not from_number:
            self.logger.warning(
                "No from-number available for workspace",
                workspace_id=str(automation.workspace_id),
            )
            return None

        # Event payloads carry the domain object id (job_id, invoice_id, etc.).
        # Include it so retrying one event collapses, while a later second job for
        # the same customer remains a legitimate new send.
        event_identity = next(
            (
                payload[key]
                for key in ("job_id", "invoice_id", "quote_id", "event_id")
                if payload.get(key)
            ),
            None,
        )
        idempotency_parts: tuple[object, ...] = (automation.id, contact.id)
        if event_identity is not None:
            idempotency_parts += (event_identity,)

        raw_agent_id = config.get("agent_id")
        try:
            agent_id = uuid.UUID(str(raw_agent_id)) if raw_agent_id else None
        except (TypeError, ValueError):
            self.logger.warning(
                "send_sms action has invalid agent_id",
                automation_id=str(automation.id),
                agent_id=str(raw_agent_id),
            )
            return None

        workspace = await db.get(Workspace, automation.workspace_id)
        timezone_name = workspace_timezone_name(workspace)
        quiet_start = config.get("quiet_hours_start", "21:00")
        quiet_end = config.get("quiet_hours_end", "08:00")

        result = await outbound_delivery_service.deliver(
            db,
            OutboundDeliveryRequest(
                workspace_id=automation.workspace_id,
                channel=OutboundDeliveryChannel.SMS,
                to=to_number,
                from_=from_number,
                body=message_body,
                contact=contact,
                agent_id=agent_id,
                idempotency_key=derive_outbound_key("automation_sms", *idempotency_parts),
                action_type="automation_sms",
                require_sms_consent=bool(config.get("require_consent")),
                quiet_hours_start=parse_clock(quiet_start),
                quiet_hours_end=parse_clock(quiet_end),
                timezone=timezone_name,
            ),
        )
        self.logger.info(
            "Automation SMS delivery resolved",
            contact_id=contact.id,
            to=to_number,
            status=result.status.value,
            reason=result.reason,
        )
        if result.delivered and result.message is not None and agent_id is not None:
            conversation = await db.get(Conversation, result.message.conversation_id)
            if conversation is not None:
                conversation.assigned_agent_id = agent_id
                conversation.ai_enabled = True
                await db.flush()
        return result

    async def _resolve_email_content(
        self,
        automation: Automation,
        config: dict[str, Any],
        db: AsyncSession,
    ) -> tuple["EmailTemplate | None", str, str, EmailCategory] | None:
        """Pick the copy and category for a ``send_email`` step.

        Returns ``(template, subject_template, body_template, category)``, or
        ``None`` when the step cannot be sent safely — the caller then stops
        without sending. Split out of :meth:`_action_send_email` to keep that
        method inside the branch budget.
        """
        raw_template_id = config.get("template_id")
        if raw_template_id:
            template = await self._load_email_template(automation, raw_template_id, db)
            if template is None:
                # Deleted or cross-workspace: sending the inline fallback would
                # put unreviewed copy in front of a customer.
                return None
            # Body content comes from the template's own blocks.
            return template, template.subject, "", EmailCategory(template.category)

        subject_template = config.get("subject", "")
        body_template = config.get("message") or config.get("body") or ""
        if not subject_template or not body_template:
            self.logger.warning(
                "send_email action missing subject or body",
                automation_id=str(automation.id),
            )
            return None
        category = (
            EmailCategory.TRANSACTIONAL
            if bool(config.get("transactional"))
            else EmailCategory.MARKETING
        )
        return None, subject_template, body_template, category

    async def _action_send_email(
        self,
        automation: Automation,
        contact: Contact,
        config: dict[str, Any],
        payload: dict[str, Any],
        db: AsyncSession,
    ) -> None:
        """Send an email to the contact via Resend.

        Config keys:
            template_id (str): Saved :class:`EmailTemplate` to render. Takes
                precedence over inline subject/message and supplies its own
                category.
            subject (str): Subject template (placeholders supported).
            message / body (str): Body template (placeholders supported).
            transactional (bool): Mark this step as service mail (a
                confirmation or receipt the customer's own action produced), so
                it carries no unsubscribe footer. Defaults to False — a workflow
                send is commercial unless the operator says otherwise.

        Commercial sends are suppressed for contacts who opted out and always
        carry a working unsubscribe link. Both checks live here, on the one path
        workflow email takes.
        """
        if not contact.email:
            self.logger.warning("Contact has no email", contact_id=contact.id)
            return

        resolved = await self._resolve_email_content(automation, config, db)
        if resolved is None:
            return
        template, subject_template, body_template, category = resolved

        unsubscribe_url: str | None = None
        if category is EmailCategory.MARKETING:
            if await email_suppressed(db, contact.id):
                self.logger.info(
                    "automation_email_suppressed",
                    contact_id=contact.id,
                    reason="contact_email_opted_out",
                )
                return
            unsubscribe_url = build_email_unsubscribe_url(contact.id)
            if unsubscribe_url is None:
                # No public origin configured, so any footer link would be dead.
                # Not sending is the correct outcome: a commercial email whose
                # opt-out 404s is worse than one that never went out.
                self.logger.error(
                    "automation_email_blocked",
                    contact_id=contact.id,
                    reason="frontend_url_not_configured",
                    detail="cannot build a working unsubscribe link",
                )
                return

        fallbacks = config.get("fallbacks")
        subject = self._render_template(subject_template, contact, payload, fallbacks)
        event_identity = next(
            (
                payload[key]
                for key in ("job_id", "invoice_id", "quote_id", "event_id")
                if payload.get(key)
            ),
            None,
        )
        idempotency_parts: tuple[object, ...] = (automation.id, contact.id)
        if event_identity is not None:
            idempotency_parts += (event_identity,)
        idempotency_key = derive_outbound_key("automation_email", *idempotency_parts)

        if template is not None:
            sent = await send_template_email(
                to_email=contact.email,
                subject=subject,
                template=template,
                values=self._template_values(contact, payload, fallbacks),
                idempotency_key=idempotency_key,
                unsubscribe_url=unsubscribe_url,
            )
        else:
            body = self._render_template(body_template, contact, payload, fallbacks)
            sent = await send_automation_email(
                to_email=contact.email,
                subject=subject,
                body=body,
                idempotency_key=idempotency_key,
                unsubscribe_url=unsubscribe_url,
                category=category,
                business_name=config.get("business_name"),
                logo_url=config.get("logo_url"),
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

    async def _action_start_drip_campaign(
        self,
        automation: Automation,
        contact: Contact | None,
        config: dict[str, Any],
        db: AsyncSession,
    ) -> None:
        """Start a reactivation drip sequence, enrolling the contact if there is one.

        Config keys:
            drip_campaign_id (str): UUID of the drip campaign to start (required).
            enroll_contact (bool, optional, default True): also enroll the
                trigger's contact. Ignored when the trigger has no contact (e.g.
                ``backlog_below_threshold``), where the point is to open the tap
                on an audience enrolled elsewhere (imports, ``/enroll``).

        Idempotent and safe to re-fire: an already-active campaign is left alone,
        ``enroll_contacts`` skips a contact who is already enrolled, and
        ``started_at`` records the *first* start. A ``completed`` campaign is
        refused rather than resurrected — the same rule the
        ``POST /drip-campaigns/{id}/start`` endpoint enforces, so both paths agree
        on what "start" means.
        """
        campaign_id = self._parse_uuid(config.get("drip_campaign_id"))
        if campaign_id is None:
            self.logger.warning(
                "start_drip_campaign missing or invalid drip_campaign_id",
                automation_id=str(automation.id),
                drip_campaign_id=config.get("drip_campaign_id"),
            )
            return

        result = await db.execute(
            select(DripCampaign).where(
                and_(
                    DripCampaign.id == campaign_id,
                    DripCampaign.workspace_id == automation.workspace_id,
                )
            )
        )
        campaign = result.scalar_one_or_none()
        if campaign is None:
            self.logger.warning(
                "start_drip_campaign: drip campaign not found in workspace",
                drip_campaign_id=str(campaign_id),
                workspace_id=str(automation.workspace_id),
            )
            return

        if campaign.status == DripCampaignStatus.COMPLETED:
            self.logger.warning(
                "start_drip_campaign: campaign already completed — skipping",
                drip_campaign_id=str(campaign_id),
            )
            return

        activated = campaign.status != DripCampaignStatus.ACTIVE
        if activated:
            campaign.status = DripCampaignStatus.ACTIVE
            campaign.started_at = campaign.started_at or datetime.now(UTC)

        enrolled = 0
        if contact is not None and config.get("enroll_contact", True):
            enrolled = await enroll_contacts(campaign, [contact.id], db)

        self.logger.info(
            "Automation started drip campaign",
            drip_campaign_id=str(campaign_id),
            activated=activated,
            enrolled=enrolled,
            contact_id=contact.id if contact else None,
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

    async def _action_move_to_stage(
        self,
        automation: Automation,
        contact: Contact | None,
        config: dict[str, Any],
        payload: dict[str, Any],
        db: AsyncSession,
    ) -> None:
        """Move an open opportunity, creating one for the contact when absent.

        ``stage_id`` chooses the destination. ``pipeline_id`` is optional builder
        context, but when present it must own that stage. Existing opportunities
        and any newly-created opportunity are always constrained to the target
        pipeline, preventing a stage from one pipeline being written onto another.
        """
        stage_id = self._parse_uuid(config.get("stage_id"))
        if stage_id is None:
            self.logger.warning(
                "move_to_stage missing or invalid stage_id",
                automation_id=str(automation.id),
                stage_id=config.get("stage_id"),
            )
            return

        configured_pipeline_id: uuid.UUID | None = None
        if config.get("pipeline_id"):
            configured_pipeline_id = self._parse_uuid(config.get("pipeline_id"))
            if configured_pipeline_id is None:
                self.logger.warning(
                    "move_to_stage has invalid pipeline_id",
                    pipeline_id=config.get("pipeline_id"),
                )
                return

        # Resolve the stage through its workspace-owned pipeline before touching
        # any opportunity. This is the tenant boundary for both moves and creates.
        stage_in_workspace = await db.execute(
            select(PipelineStage)
            .join(Pipeline, Pipeline.id == PipelineStage.pipeline_id)
            .where(
                PipelineStage.id == stage_id,
                Pipeline.workspace_id == automation.workspace_id,
            )
            .limit(1)
        )
        target_stage = stage_in_workspace.scalar_one_or_none()
        if target_stage is None:
            self.logger.warning(
                "move_to_stage: stage not found in workspace",
                stage_id=str(stage_id),
                workspace_id=str(automation.workspace_id),
            )
            return

        pipeline_id = target_stage.pipeline_id
        if configured_pipeline_id is not None and configured_pipeline_id != pipeline_id:
            self.logger.warning(
                "move_to_stage: stage does not belong to configured pipeline",
                stage_id=str(stage_id),
                pipeline_id=str(configured_pipeline_id),
            )
            return

        opportunity_id = await self._resolve_move_opportunity(
            automation, contact, payload, pipeline_id, db
        )
        if opportunity_id is None:
            if contact is None or contact.workspace_id != automation.workspace_id:
                self.logger.warning(
                    "move_to_stage: no workspace contact available to create opportunity",
                    automation_id=str(automation.id),
                    contact_id=contact.id if contact else None,
                )
                return

            opportunity = Opportunity(
                workspace_id=automation.workspace_id,
                pipeline_id=pipeline_id,
                stage_id=stage_id,
                name=opportunity_name(contact),
                primary_contact_id=contact.id,
                source=contact.source or "automation",
                probability=target_stage.probability,
                status="open",
                is_active=True,
            )
            snapshot_contact_attribution_on_opportunity(opportunity, contact)
            db.add(opportunity)
            await db.flush()

            # This write is already downstream of an automation event. Emitting
            # opportunity_created here would let mutually-opposed stage automations
            # generate an unbounded event chain; human/API creation paths own that
            # event instead.
            self.logger.info(
                "Automation created opportunity at stage",
                opportunity_id=str(opportunity.id),
                stage_id=str(stage_id),
            )
            return

        # Imported lazily to avoid any import cycle at module load (mirrors the
        # notify_workspace_event import in _notify_automation_triggered).
        from app.services.opportunities.opportunity_service import OpportunityService

        await OpportunityService(db).move_stage(
            automation.workspace_id,
            opportunity_id,
            stage_id,
            user_id=None,
            source="automation",
            emit_event=False,
        )
        self.logger.info(
            "Automation moved opportunity stage",
            opportunity_id=str(opportunity_id),
            stage_id=str(stage_id),
        )

    async def _resolve_move_opportunity(
        self,
        automation: Automation,
        contact: Contact | None,
        payload: dict[str, Any],
        pipeline_id: uuid.UUID | None,
        db: AsyncSession,
    ) -> uuid.UUID | None:
        """Pick the open opportunity a ``move_to_stage`` action should act on.

        Prefers an explicit ``payload["opportunity_id"]`` (event path), then falls
        back to the contact's newest open, active opportunity. Every lookup is
        scoped to the automation's workspace and destination pipeline.
        """
        payload_oid = self._parse_uuid(payload.get("opportunity_id"))
        if payload_oid is not None:
            filters: list[Any] = [
                Opportunity.id == payload_oid,
                Opportunity.workspace_id == automation.workspace_id,
                Opportunity.is_active.is_(True),
                Opportunity.status == "open",
            ]
            if pipeline_id is not None:
                filters.append(Opportunity.pipeline_id == pipeline_id)
            found = await db.execute(select(Opportunity.id).where(and_(*filters)).limit(1))
            resolved = found.scalar_one_or_none()
            if resolved is not None:
                return resolved

        if contact is not None:
            filters = [
                Opportunity.workspace_id == automation.workspace_id,
                Opportunity.primary_contact_id == contact.id,
                Opportunity.is_active.is_(True),
                Opportunity.status == "open",
            ]
            if pipeline_id is not None:
                filters.append(Opportunity.pipeline_id == pipeline_id)
            found = await db.execute(
                select(Opportunity.id)
                .where(and_(*filters))
                .order_by(Opportunity.created_at.desc())
                .limit(1)
            )
            return found.scalar_one_or_none()

        return None

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_uuid(value: Any) -> uuid.UUID | None:
        """Parse ``value`` as a UUID, returning None for empty/invalid input."""
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return uuid.UUID(text)
        except ValueError:
            return None

    def _render_template(
        self,
        template: str,
        contact: Contact,
        payload: dict[str, Any] | None = None,
        fallbacks: dict[str, Any] | None = None,
    ) -> str:
        """Replace simple {placeholder} tokens in a message template.

        Contact tokens take precedence; event ``payload`` keys fill in extras
        like ``{rating}`` or ``{stage}``. ``fallbacks`` supplies a default for
        any token that would otherwise render blank (e.g. ``{first_name}`` ->
        ``"there"`` when the lead record has no first name). Unknown tokens are
        left untouched.
        """
        replacements = self._template_values(contact, payload, fallbacks)
        result = template
        for key, value in replacements.items():
            result = result.replace(f"{{{key}}}", value)
        return result

    def _template_values(
        self,
        contact: Contact,
        payload: dict[str, Any] | None = None,
        fallbacks: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        """Build the ``{token} -> value`` map for one contact.

        Shared by inline copy and stored email templates so a token means the
        same thing wherever an operator writes it — two maps would drift, and
        the drift would only show up in a customer's inbox.
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
        # Fill blanks (missing/empty tokens) with caller-supplied fallbacks so a
        # personalized template still reads naturally for sparse lead records.
        for key, fallback in (fallbacks or {}).items():
            if not replacements.get(str(key)):
                replacements[str(key)] = "" if fallback is None else str(fallback)
        return replacements

    async def _load_email_template(
        self,
        automation: Automation,
        raw_template_id: Any,
        db: AsyncSession,
    ) -> EmailTemplate | None:
        """Load a workspace-scoped, active email template, or ``None``.

        Scoped to the automation's workspace so a stale or hand-edited
        ``template_id`` can never render another tenant's copy into this
        workspace's mail.
        """
        try:
            template_id = uuid.UUID(str(raw_template_id))
        except (ValueError, AttributeError, TypeError):
            self.logger.warning(
                "automation_email_template_invalid_id",
                automation_id=str(automation.id),
                template_id=str(raw_template_id),
            )
            return None

        result = await db.execute(
            select(EmailTemplate).where(
                EmailTemplate.id == template_id,
                EmailTemplate.workspace_id == automation.workspace_id,
            )
        )
        template = result.scalar_one_or_none()

        if template is None:
            self.logger.warning(
                "automation_email_template_missing",
                automation_id=str(automation.id),
                template_id=str(template_id),
            )
            return None
        if not template.is_active:
            self.logger.info(
                "automation_email_template_inactive",
                automation_id=str(automation.id),
                template_id=str(template_id),
            )
            return None
        return template

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
