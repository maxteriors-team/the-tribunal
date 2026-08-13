"""Emit domain events into the automation engine.

Services call :func:`emit_automation_event` from inside their own transaction
when something automatable happens (a review comes in, a deal moves stage, an
inbound call is missed, …). The event is persisted to ``automation_events`` and
later drained by :class:`app.workers.automation_worker.AutomationWorker`.

Emission is intentionally cheap and side-effect free: it does **not** commit
(the caller owns the transaction) and, by default, only writes a row when the
workspace actually has an active automation listening for that trigger. That
keeps the events table from accumulating rows nobody consumes on the hot paths
that emit them.

One customer-level override applies to every trigger: a contact tagged
``no-automation`` (see :mod:`app.services.automations.opt_out`) never queues an
event, so a single tag mutes automated follow-up for that person without
touching anyone else's.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.automation import Automation
from app.models.automation_event import AutomationEvent
from app.services.automations.opt_out import automation_suppressed

logger = structlog.get_logger()

# Trigger identifiers for event-based automations. These are stored verbatim in
# ``automations.trigger_type`` and matched case-insensitively by the worker.
EVENT_REVIEW_RECEIVED = "review_received"
EVENT_REVIEW_REQUEST_RESPONSE = "review_request_response"
EVENT_OPPORTUNITY_CREATED = "opportunity_created"
EVENT_DEAL_STAGE_CHANGED = "deal_stage_changed"
EVENT_MISSED_CALL = "missed_call"
EVENT_ROLEPLAY_COMPLETED = "roleplay_completed"
EVENT_KNOWLEDGE_DOCUMENT_UPLOADED = "knowledge_document_uploaded"

# Lead funnel lifecycle triggers. ``lead_created`` can be source-scoped; the
# later transitions are emitted only after evidence-backed qualification and a
# durable CRM booking respectively.
EVENT_LEAD_CREATED = "lead_created"
EVENT_LEAD_QUALIFIED = "lead_qualified"
EVENT_APPOINTMENT_BOOKED = "appointment_booked"

# Billing & field-service lifecycle triggers. Each is emitted by exactly one
# transition in its service (quotes/invoices/jobs) inside the producer's
# transaction; see the respective ``*_service`` modules. Payloads carry ids plus
# minimal context (number/total/status) so automation conditions can branch.
EVENT_QUOTE_SENT = "quote_sent"
EVENT_QUOTE_APPROVED = "quote_approved"
EVENT_QUOTE_DECLINED = "quote_declined"
EVENT_QUOTE_CONVERTED = "quote_converted"
EVENT_INVOICE_SENT = "invoice_sent"
EVENT_INVOICE_PAID = "invoice_paid"
EVENT_JOB_SCHEDULED = "job_scheduled"
EVENT_JOB_COMPLETED = "job_completed"

# All event-based triggers the worker drains from ``automation_events`` (as
# opposed to the polling triggers it evaluates against ``contacts`` directly).
AUTOMATION_EVENT_TRIGGERS: frozenset[str] = frozenset(
    {
        EVENT_REVIEW_RECEIVED,
        EVENT_REVIEW_REQUEST_RESPONSE,
        EVENT_OPPORTUNITY_CREATED,
        EVENT_DEAL_STAGE_CHANGED,
        EVENT_MISSED_CALL,
        EVENT_ROLEPLAY_COMPLETED,
        EVENT_KNOWLEDGE_DOCUMENT_UPLOADED,
        EVENT_LEAD_CREATED,
        EVENT_LEAD_QUALIFIED,
        EVENT_APPOINTMENT_BOOKED,
        EVENT_QUOTE_SENT,
        EVENT_QUOTE_APPROVED,
        EVENT_QUOTE_DECLINED,
        EVENT_QUOTE_CONVERTED,
        EVENT_INVOICE_SENT,
        EVENT_INVOICE_PAID,
        EVENT_JOB_SCHEDULED,
        EVENT_JOB_COMPLETED,
    }
)


def event_matches_trigger_config(
    event_type: str,
    trigger_config: dict[str, Any] | None,
    payload: dict[str, Any] | None,
) -> bool:
    """Return whether an event satisfies selectors supported by its trigger.

    Most lifecycle triggers match every event. ``lead_created`` supports lead
    source selectors; ``job_completed`` supports ``lighting_project_only`` so a
    landscape-system owner's guide cannot go out after service calls, permanent
    installs, repairs, or takedowns.
    """
    normalized_type = event_type.strip().lower()
    if normalized_type == EVENT_LEAD_CREATED:
        return lead_created_event_matches(trigger_config, payload)
    if normalized_type == EVENT_JOB_COMPLETED:
        config = trigger_config or {}
        if bool(config.get("lighting_project_only")):
            return bool((payload or {}).get("lighting_project_id"))
    return True


def lead_created_event_matches(
    trigger_config: dict[str, Any] | None,
    payload: dict[str, Any] | None,
) -> bool:
    """Return True if a ``lead_created`` event matches an automation's selectors.

    ``trigger_config`` may narrow a ``lead_created`` automation to specific lead
    sources via any of ``lead_source_public_key``, ``lead_source_id``, or
    ``source_detail``. Semantics are permissive **OR**: the event matches if any
    configured selector matches the event payload, so a landing page can be
    caught either by its stable lead-source key or by a ``source_detail``
    fallback (e.g. an instant-quote page that doesn't always carry click ids).

    When no selectors are configured the automation matches every new lead in
    the workspace (a general "any new lead" trigger). ``source_detail`` is
    compared case-insensitively and whitespace-trimmed.
    """
    config = trigger_config or {}
    data = payload or {}

    selectors: list[bool] = []

    want_key = str(config.get("lead_source_public_key") or "").strip()
    if want_key:
        selectors.append(str(data.get("lead_source_public_key") or "").strip() == want_key)

    want_id = str(config.get("lead_source_id") or "").strip()
    if want_id:
        selectors.append(str(data.get("lead_source_id") or "").strip() == want_id)

    want_detail = str(config.get("source_detail") or "").strip().lower()
    if want_detail:
        got_detail = str(data.get("source_detail") or "").strip().lower()
        selectors.append(got_detail == want_detail)

    if not selectors:
        return True
    return any(selectors)


async def _has_active_listener(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    event_type: str,
) -> bool:
    """Return True if the workspace has an active automation for ``event_type``."""
    result = await db.execute(
        select(Automation.id)
        .where(
            Automation.workspace_id == workspace_id,
            Automation.is_active.is_(True),
            func.lower(Automation.trigger_type) == event_type.lower(),
        )
        .limit(1)
    )
    return result.first() is not None


async def emit_automation_event(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    event_type: str,
    contact_id: int | None = None,
    payload: dict[str, Any] | None = None,
    require_active_automation: bool = True,
) -> AutomationEvent | None:
    """Queue a domain event for automation evaluation (no commit).

    Args:
        db: Active session; the event is added but **not** committed so it
            shares the producer's transaction.
        workspace_id: Tenant the event belongs to.
        event_type: One of :data:`AUTOMATION_EVENT_TRIGGERS`.
        contact_id: Optional contact the event is about.
        payload: Optional event metadata (rating, stage names, ids, …).
        require_active_automation: When True (default) the event is only
            persisted if at least one active automation listens for it.

    Returns:
        The queued :class:`AutomationEvent`, or ``None`` when skipped because
        no automation is listening or the contact opted out of automation.
    """
    if require_active_automation and not await _has_active_listener(db, workspace_id, event_type):
        return None

    # Contact-level kill switch. Deliberately *after* the listener check so a
    # workspace with no automations never pays for this query, and gated on the
    # one choke point every event trigger passes through.
    if await automation_suppressed(db, workspace_id, contact_id):
        logger.info(
            "automation_event_suppressed_by_tag",
            workspace_id=str(workspace_id),
            event_type=event_type,
            contact_id=contact_id,
        )
        return None

    event = AutomationEvent(
        workspace_id=workspace_id,
        event_type=event_type,
        contact_id=contact_id,
        payload=payload or {},
    )
    db.add(event)
    logger.debug(
        "automation_event_emitted",
        workspace_id=str(workspace_id),
        event_type=event_type,
        contact_id=contact_id,
    )
    return event
