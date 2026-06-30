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
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.automation import Automation
from app.models.automation_event import AutomationEvent

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
        no automation is listening.
    """
    if require_active_automation and not await _has_active_listener(db, workspace_id, event_type):
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
