"""Integration test for the appointments location filter.

Hits the real database (marked ``integration``; deselected by default). Inserts
appointment rows directly (never committing) so the transaction rolls back on
close and the dev database stays clean.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.db.session import AsyncSessionLocal, engine
from app.models.appointment import Appointment, AppointmentStatus
from app.models.contact import Contact
from app.models.workspace import Workspace
from app.services.appointments import AppointmentService
from app.services.field_service import BusinessLocationService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


async def _workspace(db) -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name="Biz", slug=f"biz-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    return ws


async def _contact(db, workspace_id: uuid.UUID) -> Contact:
    contact = Contact(
        workspace_id=workspace_id,
        first_name="Ada",
        last_name="Lovelace",
        email=f"ada-{uuid.uuid4().hex[:6]}@example.com",
        phone_number=f"+1555{uuid.uuid4().int % 10_000_000:07d}",
    )
    db.add(contact)
    await db.flush()
    return contact


async def _appointment(db, workspace_id, contact_id, *, location_id=None) -> Appointment:
    appt = Appointment(
        workspace_id=workspace_id,
        contact_id=contact_id,
        scheduled_at=datetime.now(UTC),
        status=AppointmentStatus.SCHEDULED,
        business_location_id=location_id,
    )
    db.add(appt)
    await db.flush()
    return appt


async def test_list_appointments_filters_by_business_location() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        branch = await BusinessLocationService(db).create(ws.id, {"name": "Austin"})
        at_branch = await _appointment(db, ws.id, contact.id, location_id=branch.id)
        await _appointment(db, ws.id, contact.id, location_id=None)

        service = AppointmentService(db)

        filtered = await service.list_appointments(
            workspace_id=ws.id, business_location_id=branch.id
        )
        assert [item.id for item in filtered.items] == [at_branch.id]
        assert all(
            item.business_location_id == branch.id for item in filtered.items
        )

        every = await service.list_appointments(workspace_id=ws.id)
        assert every.total == 2
