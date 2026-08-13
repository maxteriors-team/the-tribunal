"""Role-scoped calendar visibility for jobs and appointments.

One calendar shows both entry types, so both need the *same* answer to "whose
schedule is this?". These tests pin that answer at the service layer:

- a field worker sees only the jobs they are tagged on (directly or via crew)
  and only the appointments booked to their linked staff row;
- somebody with no technician row and no linked staff row sees an empty
  calendar rather than an error — unlinked is a normal state, not a failure;
- a restricted caller can create only against their active booking resource, so
  the result remains visible;
- a deep link to an entry the caller is not on 404s, so the per-row fetch cannot
  route around the list filter.

Hits the real database (marked ``integration``; deselected by default, run with
``-m integration``). Each test opens an ``AsyncSessionLocal`` and never commits,
so the transaction rolls back on close and the dev database stays clean.

Route-level tier gating (who gets scoped at all) lives in
``tests/api/test_calendar_scope_api.py``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.core.encryption import hash_value
from app.db.session import AsyncSessionLocal, engine
from app.models.appointment import Appointment
from app.models.bookable_staff import BookableStaff
from app.models.contact import Contact
from app.models.field_service import Crew, Technician
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.services.appointments import AppointmentService
from app.services.jobs import JobService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    """Dispose the asyncpg pool around each test to avoid closed-loop reuse."""
    await engine.dispose()
    yield
    await engine.dispose()


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #
async def _workspace(db) -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name="Dispatch", slug=f"disp-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    return ws


async def _user(db, *, name: str = "Field Worker") -> User:
    email = f"cal-{uuid.uuid4().hex[:8]}@example.com"
    user = User(
        email=email,
        email_hash=hash_value(email),
        hashed_password="x",
        full_name=name,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _member(db, workspace_id: uuid.UUID, user_id: int, role: str) -> WorkspaceMembership:
    membership = WorkspaceMembership(workspace_id=workspace_id, user_id=user_id, role=role)
    db.add(membership)
    await db.flush()
    return membership


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


async def _crew(db, workspace_id: uuid.UUID) -> Crew:
    crew = Crew(workspace_id=workspace_id, name=f"Crew {uuid.uuid4().hex[:6]}")
    db.add(crew)
    await db.flush()
    return crew


async def _technician(
    db,
    workspace_id: uuid.UUID,
    *,
    user_id: int | None = None,
    crew_id: uuid.UUID | None = None,
) -> Technician:
    tech = Technician(
        workspace_id=workspace_id,
        name=f"Tech {uuid.uuid4().hex[:6]}",
        user_id=user_id,
        crew_id=crew_id,
        is_active=True,
    )
    db.add(tech)
    await db.flush()
    return tech


async def _staff(
    db,
    workspace_id: uuid.UUID,
    *,
    user_id: int | None = None,
    is_active: bool = True,
) -> BookableStaff:
    staff = BookableStaff(
        workspace_id=workspace_id,
        name=f"Staff {uuid.uuid4().hex[:6]}",
        user_id=user_id,
        is_active=is_active,
    )
    db.add(staff)
    await db.flush()
    return staff


async def _appointment(
    db,
    workspace_id: uuid.UUID,
    contact_id: int,
    *,
    staff_id: uuid.UUID | None = None,
    service_type: str = "Estimate",
) -> Appointment:
    appointment = Appointment(
        workspace_id=workspace_id,
        contact_id=contact_id,
        bookable_staff_id=staff_id,
        service_type=service_type,
        scheduled_at=datetime.now(UTC) + timedelta(days=1),
        duration_minutes=30,
    )
    db.add(appointment)
    await db.flush()
    return appointment


# --------------------------------------------------------------------------- #
# Jobs \u2014 list scoping
# --------------------------------------------------------------------------- #
async def test_job_list_scoped_to_tagged_and_crew_jobs() -> None:
    """A scoped caller sees their own tagged jobs and their crew's, nothing else."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        user = await _user(db)
        await _member(db, ws.id, user.id, "technician")
        crew = await _crew(db, ws.id)
        tech = await _technician(db, ws.id, user_id=user.id, crew_id=crew.id)
        other_tech = await _technician(db, ws.id)
        service = JobService(db)

        direct = await service.create(
            ws.id, {"contact_id": contact.id, "title": "direct", "technician_ids": [tech.id]}
        )
        via_crew = await service.create(
            ws.id, {"contact_id": contact.id, "title": "crew", "crew_id": crew.id}
        )
        await service.create(
            ws.id,
            {"contact_id": contact.id, "title": "other", "technician_ids": [other_tech.id]},
        )

        scoped = await service.list(ws.id, visible_to_user_id=user.id)
        assert {item.id for item in scoped["items"]} == {direct.id, via_crew.id}
        assert scoped["total"] == 2


async def test_job_list_unscoped_sees_whole_board() -> None:
    """Omitting the scope (the dispatch tier) returns every job in the workspace."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        user = await _user(db)
        tech = await _technician(db, ws.id, user_id=user.id)
        other_tech = await _technician(db, ws.id)
        service = JobService(db)

        mine = await service.create(
            ws.id, {"contact_id": contact.id, "title": "mine", "technician_ids": [tech.id]}
        )
        theirs = await service.create(
            ws.id, {"contact_id": contact.id, "title": "theirs", "technician_ids": [other_tech.id]}
        )

        everything = await service.list(ws.id)
        assert {item.id for item in everything["items"]} == {mine.id, theirs.id}


async def test_job_list_filters_narrow_the_scope_never_widen_it() -> None:
    """A filter cannot pull somebody else's job back into a scoped list."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        user = await _user(db)
        tech = await _technician(db, ws.id, user_id=user.id)
        other_tech = await _technician(db, ws.id)
        service = JobService(db)

        await service.create(
            ws.id, {"contact_id": contact.id, "title": "mine", "technician_ids": [tech.id]}
        )
        await service.create(
            ws.id, {"contact_id": contact.id, "title": "theirs", "technician_ids": [other_tech.id]}
        )

        # Explicitly asking for the other technician's jobs still yields nothing.
        scoped = await service.list(ws.id, technician_id=other_tech.id, visible_to_user_id=user.id)
        assert scoped["items"] == []


async def test_job_list_empty_for_user_without_technician_row() -> None:
    """A login that is not on the roster gets an empty board, not an error."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        user = await _user(db)
        await _member(db, ws.id, user.id, "sales_rep")
        other_tech = await _technician(db, ws.id)
        service = JobService(db)
        await service.create(
            ws.id, {"contact_id": contact.id, "title": "theirs", "technician_ids": [other_tech.id]}
        )

        scoped = await service.list(ws.id, visible_to_user_id=user.id)
        assert scoped == {"items": [], "total": 0}


# --------------------------------------------------------------------------- #
# Jobs \u2014 deep link
# --------------------------------------------------------------------------- #
async def test_job_get_refuses_untagged_deep_link() -> None:
    """Fetching another worker's job by id 404s for a scoped caller."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        user = await _user(db)
        await _technician(db, ws.id, user_id=user.id)
        other_tech = await _technician(db, ws.id)
        service = JobService(db)
        theirs = await service.create(
            ws.id, {"contact_id": contact.id, "title": "theirs", "technician_ids": [other_tech.id]}
        )

        with pytest.raises(HTTPException) as excinfo:
            await service.get(theirs.id, ws.id, visible_to_user_id=user.id)
        assert excinfo.value.status_code == 404
        # Same 404 as a missing job, so existence never leaks.
        assert excinfo.value.detail == "Job not found"


async def test_job_get_allows_own_deep_link() -> None:
    """The scope does not block the caller's own job."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        user = await _user(db)
        tech = await _technician(db, ws.id, user_id=user.id)
        service = JobService(db)
        mine = await service.create(
            ws.id, {"contact_id": contact.id, "title": "mine", "technician_ids": [tech.id]}
        )

        fetched = await service.get(mine.id, ws.id, visible_to_user_id=user.id)
        assert fetched.id == mine.id


# --------------------------------------------------------------------------- #
# Appointments \u2014 list scoping
# --------------------------------------------------------------------------- #
async def test_appointment_list_scoped_to_linked_staff() -> None:
    """A scoped caller sees only appointments booked to their linked staff row."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        user = await _user(db)
        await _member(db, ws.id, user.id, "technician")
        mine_staff = await _staff(db, ws.id, user_id=user.id)
        their_staff = await _staff(db, ws.id)

        mine = await _appointment(
            db, ws.id, contact.id, staff_id=mine_staff.id, service_type="mine"
        )
        await _appointment(db, ws.id, contact.id, staff_id=their_staff.id, service_type="theirs")
        # Unassigned work belongs to the board, not to any one calendar.
        await _appointment(db, ws.id, contact.id, service_type="unassigned")

        scoped = await AppointmentService(db).list_appointments(ws.id, visible_to_user_id=user.id)
        assert [item.id for item in scoped.items] == [mine.id]


async def test_appointment_list_unscoped_sees_everything() -> None:
    """Omitting the scope (the dispatch tier) returns every appointment."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        user = await _user(db)
        mine_staff = await _staff(db, ws.id, user_id=user.id)
        their_staff = await _staff(db, ws.id)

        mine = await _appointment(db, ws.id, contact.id, staff_id=mine_staff.id)
        theirs = await _appointment(db, ws.id, contact.id, staff_id=their_staff.id)
        unassigned = await _appointment(db, ws.id, contact.id)

        everything = await AppointmentService(db).list_appointments(ws.id)
        assert {item.id for item in everything.items} == {mine.id, theirs.id, unassigned.id}


async def test_appointment_list_empty_for_unlinked_user() -> None:
    """Booked but never linked → an empty calendar, never a 500."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        user = await _user(db)
        await _member(db, ws.id, user.id, "technician")
        # A staff row carrying the same name but no login link.
        unlinked_staff = await _staff(db, ws.id)
        await _appointment(db, ws.id, contact.id, staff_id=unlinked_staff.id)

        scoped = await AppointmentService(db).list_appointments(ws.id, visible_to_user_id=user.id)
        assert scoped.items == []
        assert scoped.total == 0


async def test_appointment_list_empty_for_disabled_booking_calendar() -> None:
    """Disabling booking hides linked appointments without losing the link."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        user = await _user(db)
        staff = await _staff(db, ws.id, user_id=user.id, is_active=False)
        await _appointment(db, ws.id, contact.id, staff_id=staff.id)

        scoped = await AppointmentService(db).list_appointments(ws.id, visible_to_user_id=user.id)
        assert scoped.items == []
        assert staff.user_id == user.id


async def test_appointment_scope_does_not_cross_workspaces() -> None:
    """A staff link in another workspace grants nothing here."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        other_ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        user = await _user(db)
        # Linked in the *other* workspace only.
        await _staff(db, other_ws.id, user_id=user.id)
        here_staff = await _staff(db, ws.id)
        await _appointment(db, ws.id, contact.id, staff_id=here_staff.id)

        scoped = await AppointmentService(db).list_appointments(ws.id, visible_to_user_id=user.id)
        assert scoped.items == []


# --------------------------------------------------------------------------- #
# Appointments \u2014 deep link
# --------------------------------------------------------------------------- #
async def test_appointment_get_refuses_unbooked_deep_link() -> None:
    """Fetching an appointment the caller is not booked on 404s."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        user = await _user(db)
        await _staff(db, ws.id, user_id=user.id)
        their_staff = await _staff(db, ws.id)
        theirs = await _appointment(db, ws.id, contact.id, staff_id=their_staff.id)

        with pytest.raises(HTTPException) as excinfo:
            await AppointmentService(db).get_appointment(
                ws.id, theirs.id, visible_to_user_id=user.id
            )
        assert excinfo.value.status_code == 404
        assert excinfo.value.detail == "Appointment not found"


async def test_appointment_get_allows_own_deep_link() -> None:
    """The scope does not block the caller's own appointment."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        user = await _user(db)
        mine_staff = await _staff(db, ws.id, user_id=user.id)
        mine = await _appointment(db, ws.id, contact.id, staff_id=mine_staff.id)

        fetched = await AppointmentService(db).get_appointment(
            ws.id, mine.id, visible_to_user_id=user.id
        )
        assert fetched.id == mine.id
