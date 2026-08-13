"""Focused integration tests for lead funnel CRM transitions."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.core.encryption import hash_phone
from app.db.session import AsyncSessionLocal
from app.models.contact import Contact
from app.models.opportunity import Opportunity, OpportunityActivity
from app.models.pipeline import PipelineStage
from app.models.workspace import Workspace
from app.services.leads.funnel_transitions import (
    SCHEDULED_STAGE_NAME,
    mark_contact_booked,
    mark_contact_contacted,
    mark_contact_qualified,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def _fixture(db: object) -> tuple[Workspace, Contact]:
    workspace = Workspace(
        id=uuid.uuid4(),
        name="Lead Funnel",
        slug=f"lead-funnel-{uuid.uuid4().hex[:8]}",
        settings={"auto_pipeline": {"enabled": True}},
    )
    db.add(workspace)  # type: ignore[attr-defined]
    await db.flush()  # type: ignore[attr-defined]
    phone = f"+1512555{uuid.uuid4().int % 10000:04d}"
    contact = Contact(
        workspace_id=workspace.id,
        first_name="Jamie",
        last_name="Lead",
        phone_number=phone,
        phone_hash=hash_phone(phone),
        source="lead_form",
        status="new",
    )
    db.add(contact)  # type: ignore[attr-defined]
    await db.flush()  # type: ignore[attr-defined]
    return workspace, contact


async def test_qualification_does_not_regress_terminal_contact() -> None:
    async with AsyncSessionLocal() as db:
        _workspace, contact = await _fixture(db)
        contact.status = "lost"

        await mark_contact_qualified(db, contact)

        assert contact.status == "lost"
        assert contact.is_qualified is False
        assert contact.qualified_at is None
        await db.rollback()


async def test_funnel_transitions_are_idempotent() -> None:
    async with AsyncSessionLocal() as db:
        _workspace, contact = await _fixture(db)

        assert await mark_contact_contacted(db, contact) is True
        assert contact.status == "contacted"
        assert await mark_contact_contacted(db, contact) is False

        first = await mark_contact_qualified(db, contact)
        qualified_at = contact.qualified_at
        second = await mark_contact_qualified(db, contact)

        assert contact.status == "qualified"
        assert contact.is_qualified is True
        assert qualified_at is not None
        assert contact.qualified_at == qualified_at
        assert first is not None
        assert second is not None
        assert second.id == first.id
        count = await db.scalar(
            select(func.count())
            .select_from(Opportunity)
            .where(Opportunity.primary_contact_id == contact.id)
        )
        assert count == 1

        booked_first = await mark_contact_booked(db, contact)
        booked_second = await mark_contact_booked(db, contact)
        assert booked_first is not None
        assert booked_second is not None
        assert contact.last_appointment_status == "scheduled"
        stage_name = await db.scalar(
            select(PipelineStage.name).where(PipelineStage.id == booked_first.stage_id)
        )
        assert stage_name == SCHEDULED_STAGE_NAME
        activity_count = await db.scalar(
            select(func.count())
            .select_from(OpportunityActivity)
            .where(
                OpportunityActivity.opportunity_id == booked_first.id,
                OpportunityActivity.activity_type == "stage_changed",
            )
        )
        assert activity_count == 1
        await db.rollback()
