"""Cancelling an appointment must actually stop the reminders.

Regression cover for a live incident: a customer texted "Cancel", the agent
replied "All set - I canceled your appointment", and the reminder worker texted
her twice more the next day. The agent had no cancel tool, so nothing was ever
cancelled; the row stayed ``scheduled`` and the worker did exactly what it was
told. These tests pin the two halves of that failure — the row really flips, and
the reminder worker really stops picking it up.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, select

from app.core.encryption import hash_phone
from app.db.session import AsyncSessionLocal, engine
from app.models.agent import Agent
from app.models.appointment import Appointment, AppointmentStatus
from app.models.contact import Contact
from app.models.workspace import Workspace
from app.services.appointments.cancellation import cancel_upcoming_appointments

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

NEW_YORK = ZoneInfo("America/New_York")


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.fixture
async def workspace_id():
    """A workspace torn down (cascading) after the test.

    ``cancel_upcoming_appointments`` commits, so rows survive a rollback and
    must be removed explicitly or they leak into later runs.
    """
    ws_id = uuid.uuid4()
    yield ws_id
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Workspace).where(Workspace.id == ws_id))
        await db.commit()


async def _workspace(db, ws_id: uuid.UUID, *, timezone: str = "America/New_York") -> Workspace:
    ws = Workspace(
        id=ws_id,
        name="Maxteriors Lighting",
        slug=f"maxteriors-{ws_id.hex[:8]}",
        settings={"timezone": timezone},
    )
    db.add(ws)
    await db.flush()
    return ws


async def _contact(db, workspace_id: uuid.UUID, **overrides) -> Contact:
    phone = f"+1248555{uuid.uuid4().int % 10000:04d}"
    fields: dict[str, Any] = {
        "workspace_id": workspace_id,
        "first_name": "Stacey",
        "last_name": "Reese",
        "email": "stacey@example.com",
        "phone_number": phone,
        "phone_hash": hash_phone(phone),
        "status": "new",
    }
    fields.update(overrides)
    contact = Contact(**fields)
    db.add(contact)
    await db.flush()
    return contact


async def _agent(db, workspace_id: uuid.UUID) -> Agent:
    agent = Agent(
        workspace_id=workspace_id,
        name="Lead Reactivation",
        system_prompt="You book appointments.",
    )
    db.add(agent)
    await db.flush()
    return agent


async def _appointment(db, workspace_id: uuid.UUID, contact: Contact, *, when: datetime, **kw):
    fields: dict[str, Any] = {
        "workspace_id": workspace_id,
        "contact_id": contact.id,
        "scheduled_at": when,
        "duration_minutes": 30,
        "status": AppointmentStatus.SCHEDULED,
    }
    fields.update(kw)
    appointment = Appointment(**fields)
    db.add(appointment)
    await db.flush()
    return appointment


def _in_days(days: float) -> datetime:
    return datetime.now(UTC) + timedelta(days=days)


class TestCancelUpcomingAppointments:
    async def test_flips_a_scheduled_appointment_to_cancelled(self, workspace_id) -> None:
        async with AsyncSessionLocal() as db:
            await _workspace(db, workspace_id)
            contact = await _contact(db, workspace_id)
            appointment = await _appointment(db, workspace_id, contact, when=_in_days(2))

            result = await cancel_upcoming_appointments(
                db,
                workspace_id=workspace_id,
                contact_id=contact.id,
                reason="total cost",
            )

            assert result.count == 1
            assert result.cancelled[0].appointment_id == appointment.id

        # Committed, not just pending in the caller's transaction.
        async with AsyncSessionLocal() as db:
            row = await db.get(Appointment, appointment.id)
            assert row is not None
            assert row.status == AppointmentStatus.CANCELLED

    async def test_records_the_reason_for_the_operator(self, workspace_id) -> None:
        async with AsyncSessionLocal() as db:
            await _workspace(db, workspace_id)
            contact = await _contact(db, workspace_id)
            appointment = await _appointment(
                db, workspace_id, contact, when=_in_days(2), notes="Gate code 1234"
            )

            await cancel_upcoming_appointments(
                db,
                workspace_id=workspace_id,
                contact_id=contact.id,
                reason="total cost",
            )

        async with AsyncSessionLocal() as db:
            row = await db.get(Appointment, appointment.id)
            assert row is not None
            assert "Gate code 1234" in (row.notes or ""), "existing notes must be preserved"
            assert "total cost" in (row.notes or "")
            assert "customer" in (row.notes or "")

    async def test_cancels_every_upcoming_appointment(self, workspace_id) -> None:
        """"Cancel" over SMS means all of it, not just the next one.

        An SMS thread is one-to-one with a contact, so a customer saying "cancel"
        is not picking one of several rows out of a list she cannot see. Leaving
        a second booking live would keep texting her exactly like the incident
        this module exists to fix.

        (Two live rows on the *same* slot are no longer possible —
        ``uq_appointments_live_contact_slot`` rejects them — so this uses two
        distinct times, which is the remaining legitimate multi-row case.)
        """
        async with AsyncSessionLocal() as db:
            await _workspace(db, workspace_id)
            contact = await _contact(db, workspace_id)
            await _appointment(db, workspace_id, contact, when=_in_days(2))
            await _appointment(db, workspace_id, contact, when=_in_days(5))

            result = await cancel_upcoming_appointments(
                db,
                workspace_id=workspace_id,
                contact_id=contact.id,
            )

            assert result.count == 2

        async with AsyncSessionLocal() as db:
            rows = (
                (
                    await db.execute(
                        select(Appointment).where(Appointment.workspace_id == workspace_id)
                    )
                )
                .scalars()
                .all()
            )
            assert {row.status for row in rows} == {AppointmentStatus.CANCELLED}

    async def test_leaves_past_appointments_alone(self, workspace_id) -> None:
        """A meeting that already happened is history, not a cancellation."""
        async with AsyncSessionLocal() as db:
            await _workspace(db, workspace_id)
            contact = await _contact(db, workspace_id)
            past = await _appointment(db, workspace_id, contact, when=_in_days(-3))
            upcoming = await _appointment(db, workspace_id, contact, when=_in_days(2))

            result = await cancel_upcoming_appointments(
                db,
                workspace_id=workspace_id,
                contact_id=contact.id,
            )

            assert [item.appointment_id for item in result.cancelled] == [upcoming.id]

        async with AsyncSessionLocal() as db:
            row = await db.get(Appointment, past.id)
            assert row is not None
            assert row.status == AppointmentStatus.SCHEDULED

    async def test_nothing_upcoming_is_not_an_error(self, workspace_id) -> None:
        """The caller must be able to say "nothing to cancel" without inventing one."""
        async with AsyncSessionLocal() as db:
            await _workspace(db, workspace_id)
            contact = await _contact(db, workspace_id)

            result = await cancel_upcoming_appointments(
                db,
                workspace_id=workspace_id,
                contact_id=contact.id,
            )

            assert result.count == 0
            assert result.cancelled == ()

    async def test_does_not_touch_another_contacts_appointment(self, workspace_id) -> None:
        async with AsyncSessionLocal() as db:
            await _workspace(db, workspace_id)
            stacey = await _contact(db, workspace_id)
            other = await _contact(db, workspace_id, first_name="Dana", email="dana@example.com")
            other_appt = await _appointment(db, workspace_id, other, when=_in_days(2))
            await _appointment(db, workspace_id, stacey, when=_in_days(2))

            result = await cancel_upcoming_appointments(
                db,
                workspace_id=workspace_id,
                contact_id=stacey.id,
            )

            assert result.count == 1

        async with AsyncSessionLocal() as db:
            row = await db.get(Appointment, other_appt.id)
            assert row is not None
            assert row.status == AppointmentStatus.SCHEDULED

    async def test_tags_the_contact_for_reporting(self, workspace_id) -> None:
        async with AsyncSessionLocal() as db:
            await _workspace(db, workspace_id)
            contact = await _contact(db, workspace_id)
            await _appointment(db, workspace_id, contact, when=_in_days(2))

            await cancel_upcoming_appointments(
                db,
                workspace_id=workspace_id,
                contact_id=contact.id,
            )

        async with AsyncSessionLocal() as db:
            row = await db.get(Contact, contact.id)
            assert row is not None
            assert row.last_appointment_status == "cancelled"


class TestReminderWorkerStopsAfterCancel:
    async def test_cancelled_appointment_is_no_longer_reminder_eligible(self, workspace_id) -> None:
        """The end-to-end guarantee: no more texts.

        Mirrors the reminder worker's own selection criteria. If this query stops
        returning the row, the worker stops texting Stacey.
        """
        async with AsyncSessionLocal() as db:
            await _workspace(db, workspace_id)
            contact = await _contact(db, workspace_id)
            agent = await _agent(db, workspace_id)
            # Two hours out — inside the worker's 25-hour lookahead window.
            await _appointment(
                db,
                workspace_id,
                contact,
                when=datetime.now(UTC) + timedelta(hours=2),
                agent_id=agent.id,
            )
            await db.commit()

            assert await _reminder_candidates(db, workspace_id) == 1, (
                "precondition: the worker would have texted this contact"
            )

            await cancel_upcoming_appointments(
                db,
                workspace_id=workspace_id,
                contact_id=contact.id,
                reason="cost",
            )

        async with AsyncSessionLocal() as db:
            assert await _reminder_candidates(db, workspace_id) == 0


async def _reminder_candidates(db, workspace_id: uuid.UUID) -> int:
    """Count rows the reminder worker would pick up, using its own filters."""
    now = datetime.now(UTC)
    rows = (
        (
            await db.execute(
                select(Appointment).where(
                    Appointment.workspace_id == workspace_id,
                    Appointment.status == "scheduled",
                    Appointment.scheduled_at > now,
                    Appointment.scheduled_at <= now + timedelta(minutes=1500),
                    Appointment.contact_id.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    return len(rows)
