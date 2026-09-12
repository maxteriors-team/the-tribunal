"""Reading and writing the per-step ledger.

Two jobs, and the second is why the first exists.

**Recording.** :func:`record_step_run` appends one row per step the worker
resolves, so "which touches actually went out" stops being a question only the
provider logs can answer.

**Asking about the run.** A branch condition normally asks about a *record* —
is this quote still unsold, is this invoice still owing. Some of the most
valuable questions are instead about the *run*: when did we last talk to this
person in this sequence, and have they replied since? No column on any record
holds that; it lives in the ledger. :func:`run_scoped_value` answers those,
and :mod:`app.services.automations.branching` splices the answers into an
otherwise ordinary condition evaluation.

``replied_since_last_touch`` is the rule this was built for. Ported from
``unsold_quote_worker``, including the detail that makes it correct: before the
first touch there is no last-touch clock, so it falls back to a short recent
window rather than treating months of unrelated history as a live conversation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import hash_phone
from app.models.automation_step_run import (
    OUTCOME_SENT,
    AutomationStepRun,
)
from app.models.conversation import Conversation, Message, MessageDirection

__all__ = [
    "RUN_SCOPED_FIELDS",
    "DEFAULT_FRESH_REPLY_WINDOW_DAYS",
    "last_touch_at",
    "record_step_run",
    "replied_since_last_touch",
    "run_scoped_value",
    "touch_count",
]

# With no touch recorded yet, an inbound message inside this window still counts
# as a live conversation. Matches ``unsold_quote_worker.FRESH_REPLY_WINDOW_DAYS``
# so a ported sequence behaves identically.
DEFAULT_FRESH_REPLY_WINDOW_DAYS = 14

# Condition fields that are about the *run* rather than the subject record.
# ``branching`` peels these off before delegating the rest to the subject's
# filter module, which only knows about columns.
RUN_SCOPED_FIELDS: frozenset[str] = frozenset(
    {
        "replied_since_last_touch",
        "touch_count",
    }
)


async def record_step_run(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    execution_id: uuid.UUID,
    automation_id: uuid.UUID,
    step_index: int,
    step_type: str,
    outcome: str,
    contact_id: int | None = None,
    step_id: str | None = None,
    reason: str | None = None,
    detail: dict[str, Any] | None = None,
) -> AutomationStepRun:
    """Append one row to the ledger.

    Added to the session but deliberately not committed: the caller owns the
    transaction, and a ledger row must land or not land together with the step
    it describes.
    """
    row = AutomationStepRun(
        workspace_id=workspace_id,
        execution_id=execution_id,
        automation_id=automation_id,
        contact_id=contact_id,
        step_index=step_index,
        step_id=step_id,
        step_type=step_type,
        outcome=outcome,
        reason=reason,
        detail=detail or {},
    )
    db.add(row)
    return row


async def last_touch_at(
    db: AsyncSession,
    execution_id: uuid.UUID,
    *,
    workspace_id: uuid.UUID | None = None,
) -> datetime | None:
    """When this run last reached the customer, or ``None`` if it never has.

    Only :data:`~app.models.automation_step_run.OUTCOME_SENT` counts. A step
    skipped for consent or held at the approval gate did not touch anybody, and
    letting it move this clock would suppress the next real message.

    ``workspace_id`` is redundant given ``execution_id`` is a primary key, and
    is passed anyway: the worker reads through a tenant-exempt system session,
    so every query against a workspace-scoped table states its tenant rather
    than inheriting one.
    """
    query = select(func.max(AutomationStepRun.created_at)).where(
        AutomationStepRun.execution_id == execution_id,
        AutomationStepRun.outcome == OUTCOME_SENT,
    )
    if workspace_id is not None:
        query = query.where(AutomationStepRun.workspace_id == workspace_id)
    latest: datetime | None = await db.scalar(query)
    return latest


async def touch_count(
    db: AsyncSession,
    execution_id: uuid.UUID,
    *,
    workspace_id: uuid.UUID | None = None,
) -> int:
    """How many messages this run has actually delivered."""
    query = select(func.count(AutomationStepRun.id)).where(
        AutomationStepRun.execution_id == execution_id,
        AutomationStepRun.outcome == OUTCOME_SENT,
    )
    if workspace_id is not None:
        query = query.where(AutomationStepRun.workspace_id == workspace_id)
    total = await db.scalar(query)
    return int(total or 0)


async def replied_since_last_touch(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    execution_id: uuid.UUID,
    contact_id: int | None,
    contact_phone: str | None = None,
    now: datetime | None = None,
    fresh_window_days: int = DEFAULT_FRESH_REPLY_WINDOW_DAYS,
) -> bool:
    """Whether the customer has said something we should not talk over.

    Measured from this run's last delivered message when there is one — a reply
    to our own nudge means a human should take it from here. Before the first
    touch, an old record may legitimately carry months of unrelated history, so
    only genuinely recent inbound traffic counts.

    Matched on contact id *and* phone hash because a reply can arrive on a
    conversation that was never linked to the contact row.
    """
    moment = now or datetime.now(UTC)
    cutoff = await last_touch_at(db, execution_id, workspace_id=workspace_id) or moment - timedelta(
        days=fresh_window_days
    )

    identity = []
    if contact_id is not None:
        identity.append(Conversation.contact_id == contact_id)
    if contact_phone:
        identity.append(Conversation.contact_phone_hash == hash_phone(contact_phone))
    if not identity:
        return False

    found = await db.scalar(
        select(
            exists().where(
                and_(
                    Message.conversation_id == Conversation.id,
                    Conversation.workspace_id == workspace_id,
                    or_(*identity),
                    Message.direction == MessageDirection.INBOUND,
                    Message.created_at >= cutoff,
                )
            )
        )
    )
    return bool(found)


async def run_scoped_value(
    db: AsyncSession,
    field: str,
    *,
    workspace_id: uuid.UUID,
    execution_id: uuid.UUID,
    contact_id: int | None,
    contact_phone: str | None = None,
    now: datetime | None = None,
) -> Any:
    """Resolve one :data:`RUN_SCOPED_FIELDS` name to a comparable value."""
    if field == "replied_since_last_touch":
        return await replied_since_last_touch(
            db,
            workspace_id=workspace_id,
            execution_id=execution_id,
            contact_id=contact_id,
            contact_phone=contact_phone,
            now=now,
        )
    if field == "touch_count":
        return await touch_count(db, execution_id, workspace_id=workspace_id)
    raise ValueError(f"Unknown run-scoped condition field: {field}")
