"""Idempotent CRM transitions for the website lead-to-booking funnel.

These helpers mutate and flush inside the caller's transaction; they never
commit. Qualification owns opening the sales opportunity, while booking owns
moving that same open opportunity through :class:`OpportunityService` so stage
activity and automation events keep their canonical shape.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.opportunity import Opportunity
from app.models.pipeline import PipelineStage
from app.services.automations.events import EVENT_LEAD_QUALIFIED, emit_automation_event
from app.services.opportunities.lead_opportunity import open_lead_opportunity
from app.services.opportunities.opportunity_service import OpportunityService

QUALIFICATION_SOURCE = "website_lead_qualification"
SCHEDULED_STAGE_NAME = "Visit/Demo Scheduled"

logger = structlog.get_logger()


async def mark_contact_contacted(db: AsyncSession, contact: Contact) -> bool:
    """Move a raw lead to ``contacted`` without regressing later lifecycle states."""
    if contact.status != "new":
        return False
    contact.status = "contacted"
    await db.flush()
    return True


async def mark_contact_qualified(db: AsyncSession, contact: Contact) -> Opportunity | None:
    """Persist qualification and ensure one open attribution-snapshotted deal.

    Repeated calls keep the original timestamp, reuse the open opportunity, and
    emit no duplicate qualification event. Terminal contacts are never regressed
    or given a new opportunity.
    """
    if contact.status in {"converted", "lost"}:
        return await _get_open_opportunity(db, contact)

    transitioned = contact.status != "qualified"
    if transitioned:
        contact.status = "qualified"
        if contact.qualified_at is None:
            contact.qualified_at = datetime.now(UTC)
    contact.is_qualified = True

    opportunity = await _get_open_opportunity(db, contact)
    if opportunity is None:
        opportunity = await open_lead_opportunity(
            db,
            contact.workspace_id,
            contact,
            source=QUALIFICATION_SOURCE,
        )
    if transitioned:
        await emit_automation_event(
            db,
            workspace_id=contact.workspace_id,
            event_type=EVENT_LEAD_QUALIFIED,
            contact_id=contact.id,
            payload={
                "opportunity_id": str(opportunity.id) if opportunity else None,
                "source": QUALIFICATION_SOURCE,
            },
        )
    await db.flush()
    return opportunity


async def mark_contact_booked(
    db: AsyncSession,
    contact: Contact,
    *,
    stage_name: str = SCHEDULED_STAGE_NAME,
) -> Opportunity | None:
    """Mark a live appointment and move the contact's open deal to its stage."""
    contact.last_appointment_status = "scheduled"

    opportunity = await _get_open_opportunity(db, contact)
    if opportunity is None:
        opportunity = await open_lead_opportunity(
            db,
            contact.workspace_id,
            contact,
            source=QUALIFICATION_SOURCE,
        )
    if opportunity is None:
        await db.flush()
        return None

    stage = await _stage_named(db, opportunity.pipeline_id, stage_name)
    if stage is None:
        logger.warning(
            "lead_funnel_scheduled_stage_missing",
            workspace_id=str(contact.workspace_id),
            contact_id=contact.id,
            opportunity_id=str(opportunity.id),
            stage_name=stage_name,
        )
        await db.flush()
        return opportunity

    await OpportunityService(db).move_stage(
        contact.workspace_id,
        opportunity.id,
        stage.id,
        source="appointment_booking",
    )
    await db.flush()
    return opportunity


async def _get_open_opportunity(db: AsyncSession, contact: Contact) -> Opportunity | None:
    result = await db.execute(
        select(Opportunity)
        .where(
            Opportunity.workspace_id == contact.workspace_id,
            Opportunity.primary_contact_id == contact.id,
            Opportunity.status == "open",
        )
        .order_by(Opportunity.created_at.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _stage_named(
    db: AsyncSession,
    pipeline_id: uuid.UUID,
    stage_name: str,
) -> PipelineStage | None:
    result = await db.execute(
        select(PipelineStage)
        .where(
            PipelineStage.pipeline_id == pipeline_id,
            PipelineStage.name == stage_name,
        )
        .limit(1)
    )
    return result.scalar_one_or_none()
