"""The shared booking finalizer: row, rep assignment, SMS, and calendar invite.

Every AI booking path funnels through :func:`finalize_booking`, so this is where
the "did the appointment actually become real" guarantees are pinned.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.core.encryption import hash_phone
from app.db.session import AsyncSessionLocal, engine
from app.models.agent import Agent
from app.models.appointment import Appointment, AppointmentStatus
from app.models.automation import Automation
from app.models.automation_event import AutomationEvent
from app.models.automation_execution import AutomationExecution
from app.models.bookable_staff import BookableStaff
from app.models.contact import Contact
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.services.appointments import booking_finalizer
from app.services.appointments.booking_finalizer import (
    deliver_booking_notifications,
    finalize_booking,
)
from app.services.appointments.lifecycle_sms import build_confirmation_body
from app.services.google_calendar import GoogleCalendarError, GoogleEvent

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

NEW_YORK = ZoneInfo("America/New_York")


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.fixture
async def workspace_id():
    """A workspace that is torn down (cascading) after the test.

    ``finalize_booking`` commits, so rows survive a rollback and must be removed
    explicitly or they leak into later runs.
    """
    ws_id = uuid.uuid4()
    yield ws_id
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Workspace).where(Workspace.id == ws_id))
        await db.commit()


async def _workspace(db, ws_id: uuid.UUID, *, timezone: str = "America/New_York") -> Workspace:
    ws = Workspace(
        id=ws_id,
        name="Sparkle Exteriors",
        slug=f"sparkle-{ws_id.hex[:8]}",
        settings={"timezone": timezone},
    )
    db.add(ws)
    await db.flush()
    return ws


async def _contact(db, workspace_id: uuid.UUID, **overrides) -> Contact:
    phone = f"+1512555{uuid.uuid4().int % 10000:04d}"
    fields: dict[str, Any] = {
        "workspace_id": workspace_id,
        "first_name": "Dana",
        "last_name": "Reyes",
        "email": "dana@example.com",
        "phone_number": phone,
        "phone_hash": hash_phone(phone),
        "status": "new",
    }
    fields.update(overrides)
    contact = Contact(**fields)
    db.add(contact)
    await db.flush()
    return contact


async def _agent(db, workspace_id: uuid.UUID, *, strategy: str = "single", **overrides) -> Agent:
    agent = Agent(
        workspace_id=workspace_id,
        name="Reactivation Agent",
        system_prompt="You book appointments.",
        assignment_strategy=strategy,
        **overrides,
    )
    db.add(agent)
    await db.flush()
    return agent


async def _staff(db, workspace_id: uuid.UUID, agent_id: uuid.UUID, **overrides) -> BookableStaff:
    fields: dict[str, Any] = {
        "workspace_id": workspace_id,
        "agent_id": agent_id,
        "name": "Sam Rivera",
        "email": "sam@example.com",
    }
    fields.update(overrides)
    staff = BookableStaff(**fields)
    db.add(staff)
    await db.flush()
    return staff


async def _owner(db, workspace_id: uuid.UUID) -> User:
    user = User(
        email=f"owner-{uuid.uuid4().hex[:8]}@example.com",
        full_name="Ollie Owner",
        hashed_password="x",
    )
    db.add(user)
    await db.flush()
    db.add(WorkspaceMembership(user_id=user.id, workspace_id=workspace_id, role="owner"))
    await db.flush()
    return user


class TestAppointmentRow:
    async def test_creates_a_scheduled_appointment(self, workspace_id) -> None:
        async with AsyncSessionLocal() as db:
            await _workspace(db, workspace_id)
            contact = await _contact(db, workspace_id)
            agent = await _agent(db, workspace_id)

            appointment = await finalize_booking(
                db,
                workspace_id=workspace_id,
                contact=contact,
                agent=agent,
                scheduled_at=datetime(2099, 6, 10, 14, 0, tzinfo=NEW_YORK),
                duration_minutes=45,
                notes="Gate code 1234",
                notify=False,
            )

            assert appointment.id is not None
            assert appointment.status == AppointmentStatus.SCHEDULED
            assert appointment.duration_minutes == 45
            assert appointment.notes == "Gate code 1234"
            assert appointment.contact_id == contact.id
            assert appointment.agent_id == agent.id

    async def test_row_survives_the_session(self, workspace_id) -> None:
        """The booking must be committed, not left pending in the caller's tx."""
        async with AsyncSessionLocal() as db:
            await _workspace(db, workspace_id)
            contact = await _contact(db, workspace_id)
            await finalize_booking(
                db,
                workspace_id=workspace_id,
                contact=contact,
                scheduled_at=datetime(2099, 6, 10, 14, 0, tzinfo=NEW_YORK),
                duration_minutes=30,
                notify=False,
            )

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
            assert len(rows) == 1

    async def test_stores_the_instant_the_caller_supplied(self, workspace_id) -> None:
        async with AsyncSessionLocal() as db:
            await _workspace(db, workspace_id)
            contact = await _contact(db, workspace_id)
            appointment = await finalize_booking(
                db,
                workspace_id=workspace_id,
                contact=contact,
                scheduled_at=datetime(2099, 6, 10, 14, 0, tzinfo=NEW_YORK),
                duration_minutes=30,
                notify=False,
            )
            # 2 PM EDT is 18:00 UTC — the row must not drift.
            assert appointment.scheduled_at.astimezone(UTC).hour == 18
            assert appointment.scheduled_at.astimezone(NEW_YORK).hour == 14

    async def test_naive_datetime_is_refused(self, workspace_id) -> None:
        """A naive value means the customer's zone was lost upstream."""
        async with AsyncSessionLocal() as db:
            await _workspace(db, workspace_id)
            contact = await _contact(db, workspace_id)
            with pytest.raises(ValueError, match="timezone-aware"):
                await finalize_booking(
                    db,
                    workspace_id=workspace_id,
                    contact=contact,
                    scheduled_at=datetime(2099, 6, 10, 14, 0),
                    duration_minutes=30,
                    notify=False,
                )

    async def test_contact_must_belong_to_booking_workspace(self, workspace_id) -> None:
        other_workspace_id = uuid.uuid4()
        async with AsyncSessionLocal() as db:
            await _workspace(db, workspace_id)
            await _workspace(db, other_workspace_id)
            contact = await _contact(db, other_workspace_id)

            with pytest.raises(ValueError, match="contact does not belong"):
                await finalize_booking(
                    db,
                    workspace_id=workspace_id,
                    contact=contact,
                    scheduled_at=datetime(2099, 6, 10, 14, 0, tzinfo=NEW_YORK),
                    duration_minutes=30,
                    notify=False,
                )

    async def test_agent_must_belong_to_booking_workspace(self, workspace_id) -> None:
        other_workspace_id = uuid.uuid4()
        async with AsyncSessionLocal() as db:
            await _workspace(db, workspace_id)
            await _workspace(db, other_workspace_id)
            contact = await _contact(db, workspace_id)
            agent = await _agent(db, other_workspace_id)

            with pytest.raises(ValueError, match="agent does not belong"):
                await finalize_booking(
                    db,
                    workspace_id=workspace_id,
                    contact=contact,
                    agent=agent,
                    scheduled_at=datetime(2099, 6, 10, 14, 0, tzinfo=NEW_YORK),
                    duration_minutes=30,
                    notify=False,
                )


class TestAvailabilityVerification:
    async def test_blocked_google_slot_is_not_persisted(self, workspace_id, monkeypatch) -> None:
        google_slot_open = AsyncMock(return_value=False)
        monkeypatch.setattr(booking_finalizer, "is_time_available", google_slot_open)

        async with AsyncSessionLocal() as db:
            await _workspace(db, workspace_id)
            contact = await _contact(db, workspace_id)
            agent = await _agent(db, workspace_id)
            owner = await _owner(db, workspace_id)
            staff = await _staff(db, workspace_id, agent.id, user_id=owner.id)

            with pytest.raises(GoogleCalendarError, match="no longer available"):
                await finalize_booking(
                    db,
                    workspace_id=workspace_id,
                    contact=contact,
                    agent=agent,
                    scheduled_at=datetime(2099, 6, 10, 14, 0, tzinfo=NEW_YORK),
                    duration_minutes=30,
                    assigned_staff_id=staff.id,
                    verify_availability=True,
                    notify=False,
                )

            appointment_count = await db.scalar(
                select(func.count(Appointment.id)).where(Appointment.workspace_id == workspace_id)
            )
            assert appointment_count == 0


class TestRepAssignment:
    async def test_round_robin_agent_gets_a_rep(self, workspace_id) -> None:
        async with AsyncSessionLocal() as db:
            await _workspace(db, workspace_id)
            contact = await _contact(db, workspace_id)
            agent = await _agent(db, workspace_id, strategy="round_robin")
            owner = await _owner(db, workspace_id)
            staff = await _staff(db, workspace_id, agent.id, user_id=owner.id)

            appointment = await finalize_booking(
                db,
                workspace_id=workspace_id,
                contact=contact,
                agent=agent,
                scheduled_at=datetime(2099, 6, 10, 14, 0, tzinfo=NEW_YORK),
                duration_minutes=30,
                notify=False,
            )
            assert appointment.bookable_staff_id == staff.id

    async def test_caller_supplied_staff_is_used_verbatim(self, workspace_id) -> None:
        """A caller that already routed must not have the choice re-rolled."""
        async with AsyncSessionLocal() as db:
            await _workspace(db, workspace_id)
            contact = await _contact(db, workspace_id)
            agent = await _agent(db, workspace_id, strategy="round_robin")
            first = await _staff(db, workspace_id, agent.id, name="First", priority=10)
            await _staff(db, workspace_id, agent.id, name="Second", email="second@example.com")

            appointment = await finalize_booking(
                db,
                workspace_id=workspace_id,
                contact=contact,
                agent=agent,
                scheduled_at=datetime(2099, 6, 10, 14, 0, tzinfo=NEW_YORK),
                duration_minutes=30,
                assigned_staff_id=first.id,
                notify=False,
            )
            assert appointment.bookable_staff_id == first.id

    async def test_supplied_staff_does_not_consume_a_round_robin_turn(self, workspace_id) -> None:
        async with AsyncSessionLocal() as db:
            await _workspace(db, workspace_id)
            contact = await _contact(db, workspace_id)
            agent = await _agent(db, workspace_id, strategy="round_robin")
            staff = await _staff(db, workspace_id, agent.id, assignment_count=3)

            await finalize_booking(
                db,
                workspace_id=workspace_id,
                contact=contact,
                agent=agent,
                scheduled_at=datetime(2099, 6, 10, 14, 0, tzinfo=NEW_YORK),
                duration_minutes=30,
                assigned_staff_id=staff.id,
                notify=False,
            )
            await db.refresh(staff)
            assert staff.assignment_count == 3

    async def test_single_strategy_leaves_the_appointment_unassigned(self, workspace_id) -> None:
        """Today's live shape: no staff pool, so the owner picks it up."""
        async with AsyncSessionLocal() as db:
            await _workspace(db, workspace_id)
            contact = await _contact(db, workspace_id)
            agent = await _agent(db, workspace_id, strategy="single")

            appointment = await finalize_booking(
                db,
                workspace_id=workspace_id,
                contact=contact,
                agent=agent,
                scheduled_at=datetime(2099, 6, 10, 14, 0, tzinfo=NEW_YORK),
                duration_minutes=30,
                notify=False,
            )
            assert appointment.bookable_staff_id is None

    async def test_routing_failure_still_books(self, workspace_id, monkeypatch) -> None:
        """An unassigned appointment is recoverable; a lost booking is not."""

        async def _boom(*_args, **_kwargs):
            raise RuntimeError("router down")

        monkeypatch.setattr(
            "app.services.calendar.staff_assignment.resolve_staff_for_booking", _boom
        )
        async with AsyncSessionLocal() as db:
            await _workspace(db, workspace_id)
            contact = await _contact(db, workspace_id)
            agent = await _agent(db, workspace_id, strategy="round_robin")

            appointment = await finalize_booking(
                db,
                workspace_id=workspace_id,
                contact=contact,
                agent=agent,
                scheduled_at=datetime(2099, 6, 10, 14, 0, tzinfo=NEW_YORK),
                duration_minutes=30,
                notify=False,
            )
            assert appointment.id is not None
            assert appointment.bookable_staff_id is None


class TestFunnelFinalization:
    async def test_booking_moves_crm_emits_event_and_stops_only_acquisition_funnel(
        self, workspace_id
    ) -> None:
        async with AsyncSessionLocal() as db:
            workspace = await _workspace(db, workspace_id)
            workspace.settings = {"auto_pipeline": {"enabled": True}}
            contact = await _contact(db, workspace_id)
            acquisition = Automation(
                workspace_id=workspace_id,
                name="Acquisition funnel",
                trigger_type="lead_created",
                trigger_config={"funnel_id": "acquisition:test"},
                actions=[],
                is_active=True,
            )
            unrelated = Automation(
                workspace_id=workspace_id,
                name="Appointment reminder",
                trigger_type="appointment_booked",
                trigger_config={},
                actions=[],
                is_active=True,
            )
            db.add_all([acquisition, unrelated])
            await db.flush()
            acquisition_run = AutomationExecution(
                automation_id=acquisition.id,
                contact_id=contact.id,
                status="scheduled",
                context={},
            )
            unrelated_run = AutomationExecution(
                automation_id=unrelated.id,
                contact_id=contact.id,
                status="scheduled",
                context={},
            )
            db.add_all([acquisition_run, unrelated_run])
            await db.commit()

            appointment = await finalize_booking(
                db,
                workspace_id=workspace_id,
                contact=contact,
                agent=None,
                scheduled_at=datetime(2099, 6, 10, 14, 0, tzinfo=NEW_YORK),
                duration_minutes=30,
                service_type="phone_call",
                notify=False,
            )

            await db.refresh(contact)
            await db.refresh(acquisition_run)
            await db.refresh(unrelated_run)
            assert appointment.status == AppointmentStatus.SCHEDULED
            assert contact.last_appointment_status == "scheduled"
            assert acquisition_run.status == "completed"
            assert unrelated_run.status == "scheduled"
            event = await db.scalar(
                select(AutomationEvent).where(
                    AutomationEvent.workspace_id == workspace_id,
                    AutomationEvent.event_type == "appointment_booked",
                    AutomationEvent.contact_id == contact.id,
                )
            )
            assert event is not None
            assert event.payload["appointment_id"] == appointment.id
            assert event.payload["service_type"] == "phone_call"
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(Appointment)
                    .where(
                        Appointment.workspace_id == workspace_id,
                        Appointment.contact_id == contact.id,
                    )
                )
                == 1
            )


class TestCallTypeContract:
    async def test_video_sync_persists_real_meet_link(self, workspace_id, monkeypatch) -> None:
        async with AsyncSessionLocal() as db:
            workspace = await _workspace(db, workspace_id)
            contact = await _contact(db, workspace_id)
            agent = await _agent(db, workspace_id)
            owner = await _owner(db, workspace_id)
            staff = await _staff(db, workspace_id, agent.id, user_id=owner.id)
            appointment = Appointment(
                workspace_id=workspace_id,
                contact_id=contact.id,
                scheduled_at=datetime(2099, 6, 10, 14, 0, tzinfo=NEW_YORK),
                duration_minutes=30,
                status="scheduled",
                service_type="video_call",
            )
            db.add(appointment)
            await db.commit()
            create = AsyncMock(
                return_value=GoogleEvent(
                    event_id="event-1",
                    html_link="https://calendar.google.com/event-1",
                    meet_link="https://meet.google.com/abc-defg-hij",
                )
            )
            monkeypatch.setattr("app.services.google_calendar.create_event", create)

            await booking_finalizer.sync_appointment_external_events(
                db,
                appointment=appointment,
                contact=contact,
                workspace=workspace,
                staff=staff,
                log=booking_finalizer.logger,
            )

            assert appointment.meeting_url == "https://meet.google.com/abc-defg-hij"
            assert appointment.sync_status == "synced"
            assert create.await_args.kwargs["conference"] is True

    async def test_inline_external_sync_returns_video_link_to_caller(
        self, workspace_id, monkeypatch
    ) -> None:
        async with AsyncSessionLocal() as db:
            await _workspace(db, workspace_id)
            contact = await _contact(db, workspace_id)
            agent = await _agent(db, workspace_id)
            owner = await _owner(db, workspace_id)
            staff = await _staff(db, workspace_id, agent.id, user_id=owner.id)
            create = AsyncMock(
                return_value=GoogleEvent(
                    event_id="event-inline",
                    html_link="https://calendar.google.com/event-inline",
                    meet_link="https://meet.google.com/inline-link",
                )
            )
            monkeypatch.setattr("app.services.google_calendar.create_event", create)
            monkeypatch.setattr(
                "app.services.zoom.zoom_configured_for_user",
                AsyncMock(return_value=False),
            )

            appointment = await finalize_booking(
                db,
                workspace_id=workspace_id,
                contact=contact,
                agent=agent,
                scheduled_at=datetime(2099, 6, 10, 14, 0, tzinfo=NEW_YORK),
                duration_minutes=30,
                service_type="video_call",
                assigned_staff_id=staff.id,
                notify=False,
                sync_external_events_before_return=True,
            )

            assert appointment.sync_status == "synced"
            assert appointment.meeting_url == "https://meet.google.com/inline-link"
            assert create.await_args.kwargs["conference"] is True

    async def test_phone_call_never_requests_conference_or_meet(
        self, workspace_id, monkeypatch
    ) -> None:
        async with AsyncSessionLocal() as db:
            workspace = await _workspace(db, workspace_id)
            contact = await _contact(db, workspace_id)
            agent = await _agent(db, workspace_id)
            owner = await _owner(db, workspace_id)
            staff = await _staff(db, workspace_id, agent.id, user_id=owner.id)
            appointment = Appointment(
                workspace_id=workspace_id,
                contact_id=contact.id,
                scheduled_at=datetime(2099, 6, 10, 14, 0, tzinfo=NEW_YORK),
                duration_minutes=30,
                status="scheduled",
                service_type="phone_call",
            )
            db.add(appointment)
            await db.commit()
            create = AsyncMock(
                return_value=GoogleEvent(
                    event_id="event-phone",
                    html_link="https://calendar.google.com/event-phone",
                    meet_link="https://meet.google.com/should-not-persist",
                )
            )
            monkeypatch.setattr("app.services.google_calendar.create_event", create)

            await booking_finalizer.sync_appointment_external_events(
                db,
                appointment=appointment,
                contact=contact,
                workspace=workspace,
                staff=staff,
                log=booking_finalizer.logger,
            )

            assert create.await_args.kwargs["conference"] is False
            assert create.await_args.kwargs["location"] == f"Phone call: {contact.phone_number}"
            assert appointment.meeting_url is None

    async def test_disconnected_video_records_not_connected_without_fake_url(
        self, workspace_id, monkeypatch
    ) -> None:
        async with AsyncSessionLocal() as db:
            workspace = await _workspace(db, workspace_id)
            contact = await _contact(db, workspace_id)
            agent = await _agent(db, workspace_id)
            owner = await _owner(db, workspace_id)
            staff = await _staff(db, workspace_id, agent.id, user_id=owner.id)
            appointment = Appointment(
                workspace_id=workspace_id,
                contact_id=contact.id,
                scheduled_at=datetime(2099, 6, 10, 14, 0, tzinfo=NEW_YORK),
                duration_minutes=30,
                status="scheduled",
                service_type="video_call",
            )
            db.add(appointment)
            await db.commit()
            monkeypatch.setattr(
                "app.services.google_calendar.create_event",
                AsyncMock(side_effect=GoogleCalendarError("Google Calendar is not connected")),
            )

            await booking_finalizer.sync_appointment_external_events(
                db,
                appointment=appointment,
                contact=contact,
                workspace=workspace,
                staff=staff,
                log=booking_finalizer.logger,
            )

            assert appointment.sync_status == "not_connected"
            assert appointment.meeting_url is None
            assert "not connected" in (appointment.sync_error or "").lower()

    async def test_phone_and_failed_video_confirmation_copy_is_truthful(self) -> None:
        contact = Contact(first_name="Dana", phone_number="+15125550123")
        phone = Appointment(
            scheduled_at=datetime(2099, 6, 10, 14, 0, tzinfo=UTC),
            service_type="phone_call",
        )
        failed_video = Appointment(
            scheduled_at=datetime(2099, 6, 10, 14, 0, tzinfo=UTC),
            service_type="video_call",
            sync_status="failed",
        )

        assert "+15125550123" in build_confirmation_body(contact, phone, None, None)
        failed_copy = build_confirmation_body(contact, failed_video, None, None)
        assert "follow up with the video link" in failed_copy
        assert "meet.google.com" not in failed_copy


class TestNotifications:
    @pytest.fixture
    def captured(self, monkeypatch) -> dict[str, Any]:
        """Capture the SMS and email side effects instead of sending them."""
        sink: dict[str, Any] = {"sms": [], "email": []}

        async def _fake_sms(**kwargs):
            sink["sms"].append(kwargs)

        async def _fake_email(**kwargs):
            sink["email"].append(kwargs)
            return True

        async def _fake_attendee_email(**kwargs):
            sink["attendee_email"].append(kwargs)
            return True

        sink["attendee_email"] = []
        monkeypatch.setattr(booking_finalizer, "send_lifecycle_sms", _fake_sms)
        monkeypatch.setattr(booking_finalizer, "send_appointment_booked_notification", _fake_email)
        monkeypatch.setattr(
            booking_finalizer,
            "send_appointment_confirmation_to_attendee",
            _fake_attendee_email,
        )
        return sink

    async def _book(self, workspace_id, **overrides) -> int:
        async with AsyncSessionLocal() as db:
            ws = await _workspace(db, workspace_id)
            contact = await _contact(db, workspace_id, **overrides.pop("contact_fields", {}))
            agent = await _agent(db, workspace_id, **overrides.pop("agent_fields", {}))
            await _owner(db, workspace_id)
            staff_id = None
            if overrides.pop("with_staff", False):
                staff = await _staff(db, workspace_id, agent.id)
                staff_id = staff.id
            appointment = await finalize_booking(
                db,
                workspace_id=ws.id,
                contact=contact,
                agent=agent,
                scheduled_at=datetime(2099, 6, 10, 14, 0, tzinfo=NEW_YORK),
                duration_minutes=60,
                service_type="Estimate",
                assigned_staff_id=staff_id,
                notify=False,
                **overrides,
            )
            return appointment.id

    async def test_customer_gets_a_confirmation_text(self, workspace_id, captured) -> None:
        appointment_id = await self._book(workspace_id)
        await deliver_booking_notifications(appointment_id)

        assert len(captured["sms"]) == 1
        body = captured["sms"][0]["body_text"]
        assert "confirmed" in body.lower()
        # Rendered in the workspace zone, not the stored UTC.
        assert "2:00 PM" in body
        assert "Wednesday, June 10" in body

    async def test_confirmation_is_idempotent_per_appointment(self, workspace_id, captured) -> None:
        appointment_id = await self._book(workspace_id)
        await deliver_booking_notifications(appointment_id)
        await deliver_booking_notifications(appointment_id)

        keys = {call["idempotency_parts"] for call in captured["sms"]}
        assert keys == {(appointment_id,)}

    async def test_live_text_booking_can_suppress_the_generic_confirmation(
        self, workspace_id, captured
    ) -> None:
        appointment_id = await self._book(workspace_id)
        await deliver_booking_notifications(appointment_id, send_customer_sms=False)

        assert captured["sms"] == []
        assert len(captured["attendee_email"]) == 1
        assert len(captured["email"]) == 1

    async def test_invite_goes_to_the_assigned_rep(self, workspace_id, captured) -> None:
        appointment_id = await self._book(workspace_id, with_staff=True)
        await deliver_booking_notifications(appointment_id)

        assert captured["email"][0]["to_email"] == "sam@example.com"
        assert captured["email"][0]["owner_name"] == "Sam Rivera"

    async def test_invite_falls_back_to_the_workspace_owner(self, workspace_id, captured) -> None:
        """Every workspace today has no staff pool, so this is the live path."""
        appointment_id = await self._book(workspace_id)
        await deliver_booking_notifications(appointment_id)

        assert captured["email"][0]["to_email"].startswith("owner-")

    async def test_invite_carries_a_parseable_ics(self, workspace_id, captured) -> None:
        appointment_id = await self._book(workspace_id)
        await deliver_booking_notifications(appointment_id)

        ics = captured["email"][0]["ics_content"]
        assert "BEGIN:VCALENDAR" in ics
        assert "METHOD:REQUEST" in ics
        # 2 PM Eastern on 2099-06-10 is 18:00 UTC (EDT).
        assert "DTSTART:20990610T180000Z" in ics
        assert "DTEND:20990610T190000Z" in ics
        assert f"UID:appointment-{appointment_id}@" in ics

    async def test_invite_location_is_the_service_address(self, workspace_id, captured) -> None:
        appointment_id = await self._book(
            workspace_id,
            contact_fields={
                "address_line1": "123 Main St",
                "address_city": "Austin",
                "address_state": "TX",
                "address_zip": "78701",
            },
        )
        await deliver_booking_notifications(appointment_id)

        ics = captured["email"][0]["ics_content"].replace("\r\n ", "")
        assert "LOCATION:123 Main St\\, Austin\\, TX 78701" in ics

    async def test_email_failure_does_not_suppress_the_text(
        self, workspace_id, captured, monkeypatch
    ) -> None:
        async def _boom(**_kwargs):
            raise RuntimeError("resend down")

        monkeypatch.setattr(booking_finalizer, "send_appointment_booked_notification", _boom)
        appointment_id = await self._book(workspace_id)

        await deliver_booking_notifications(appointment_id)

        assert len(captured["sms"]) == 1

    async def test_customer_gets_an_invite_email(self, workspace_id, captured) -> None:
        appointment_id = await self._book(workspace_id)
        await deliver_booking_notifications(appointment_id)

        assert len(captured["attendee_email"]) == 1
        sent = captured["attendee_email"][0]
        assert sent["to_email"] == "dana@example.com"
        ics = sent["ics_content"]
        assert "BEGIN:VCALENDAR" in ics
        assert "DTSTART:20990610T180000Z" in ics
        assert f"UID:appointment-{appointment_id}@" in ics
        assert "dana@example.com" in ics

    async def test_attendee_email_skipped_when_agent_disables_it(
        self, workspace_id, captured
    ) -> None:
        appointment_id = await self._book(
            workspace_id, agent_fields={"confirmation_email_enabled": False}
        )
        await deliver_booking_notifications(appointment_id)

        assert captured["attendee_email"] == []
        # The rep invite and the customer text are unaffected.
        assert len(captured["sms"]) == 1
        assert len(captured["email"]) == 1

    async def test_attendee_email_skipped_without_an_address(self, workspace_id, captured) -> None:
        appointment_id = await self._book(workspace_id, contact_fields={"email": None})
        await deliver_booking_notifications(appointment_id)

        assert captured["attendee_email"] == []
        assert len(captured["sms"]) == 1

    async def test_attendee_email_failure_does_not_suppress_the_rep_invite(
        self, workspace_id, captured, monkeypatch
    ) -> None:
        async def _boom(**_kwargs):
            raise RuntimeError("resend down")

        monkeypatch.setattr(booking_finalizer, "send_appointment_confirmation_to_attendee", _boom)
        appointment_id = await self._book(workspace_id)

        await deliver_booking_notifications(appointment_id)

        assert len(captured["sms"]) == 1
        assert len(captured["email"]) == 1

    async def test_missing_appointment_is_a_no_op(self, workspace_id, captured) -> None:
        await deliver_booking_notifications(999_999_999)
        assert captured["sms"] == []
        assert captured["email"] == []
        assert captured["attendee_email"] == []


class TestDuplicateGuard:
    async def test_same_contact_and_time_returns_the_existing_booking(self, workspace_id) -> None:
        """A retry must not produce two rows, two texts, and two invites."""
        async with AsyncSessionLocal() as db:
            await _workspace(db, workspace_id)
            contact = await _contact(db, workspace_id)
            when = datetime(2099, 6, 10, 14, 0, tzinfo=NEW_YORK)

            first = await finalize_booking(
                db,
                workspace_id=workspace_id,
                contact=contact,
                scheduled_at=when,
                duration_minutes=30,
                notify=False,
            )
            second = await finalize_booking(
                db,
                workspace_id=workspace_id,
                contact=contact,
                scheduled_at=when,
                duration_minutes=30,
                notify=False,
            )

            assert second.id == first.id
            rows = (
                (
                    await db.execute(
                        select(Appointment).where(Appointment.workspace_id == workspace_id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1

    async def test_a_different_time_books_normally(self, workspace_id) -> None:
        async with AsyncSessionLocal() as db:
            await _workspace(db, workspace_id)
            contact = await _contact(db, workspace_id)

            first = await finalize_booking(
                db,
                workspace_id=workspace_id,
                contact=contact,
                scheduled_at=datetime(2099, 6, 10, 14, 0, tzinfo=NEW_YORK),
                duration_minutes=30,
                notify=False,
            )
            second = await finalize_booking(
                db,
                workspace_id=workspace_id,
                contact=contact,
                scheduled_at=datetime(2099, 6, 11, 14, 0, tzinfo=NEW_YORK),
                duration_minutes=30,
                notify=False,
            )
            assert second.id != first.id

    async def test_a_cancelled_booking_does_not_block_rebooking(self, workspace_id) -> None:
        async with AsyncSessionLocal() as db:
            await _workspace(db, workspace_id)
            contact = await _contact(db, workspace_id)
            when = datetime(2099, 6, 10, 14, 0, tzinfo=NEW_YORK)

            first = await finalize_booking(
                db,
                workspace_id=workspace_id,
                contact=contact,
                scheduled_at=when,
                duration_minutes=30,
                notify=False,
            )
            first.status = AppointmentStatus.CANCELLED
            await db.commit()

            second = await finalize_booking(
                db,
                workspace_id=workspace_id,
                contact=contact,
                scheduled_at=when,
                duration_minutes=30,
                notify=False,
            )
            assert second.id != first.id

    async def test_a_different_contact_at_the_same_time_is_allowed(self, workspace_id) -> None:
        async with AsyncSessionLocal() as db:
            await _workspace(db, workspace_id)
            one = await _contact(db, workspace_id)
            two = await _contact(db, workspace_id, first_name="Other", email="other@example.com")
            when = datetime(2099, 6, 10, 14, 0, tzinfo=NEW_YORK)

            first = await finalize_booking(
                db,
                workspace_id=workspace_id,
                contact=one,
                scheduled_at=when,
                duration_minutes=30,
                notify=False,
            )
            second = await finalize_booking(
                db,
                workspace_id=workspace_id,
                contact=two,
                scheduled_at=when,
                duration_minutes=30,
                notify=False,
            )
            assert second.id != first.id


class TestDuplicateIndexBackstop:
    """The database rule behind the application guard.

    ``_find_duplicate`` is a read followed by a write. Two tool calls racing (the
    live incident: one model turn booked, the next turn booked again 61 seconds
    later) can both read "no duplicate" and both insert. Only the partial unique
    index actually prevents the second row.
    """

    async def test_index_rejects_a_second_live_row_on_the_same_slot(self, workspace_id) -> None:
        """Insert straight past the application guard; the database must refuse."""
        when = datetime(2099, 6, 10, 14, 0, tzinfo=NEW_YORK)
        async with AsyncSessionLocal() as db:
            await _workspace(db, workspace_id)
            contact = await _contact(db, workspace_id)
            await finalize_booking(
                db,
                workspace_id=workspace_id,
                contact=contact,
                scheduled_at=when,
                duration_minutes=30,
                notify=False,
            )
            contact_id = contact.id

        async with AsyncSessionLocal() as db:
            db.add(
                Appointment(
                    workspace_id=workspace_id,
                    contact_id=contact_id,
                    scheduled_at=when,
                    duration_minutes=30,
                    status=AppointmentStatus.SCHEDULED,
                )
            )
            with pytest.raises(IntegrityError):
                await db.commit()

    async def test_losing_the_race_returns_the_winning_booking(self, workspace_id) -> None:
        """A booking the customer confirmed must not surface as an error.

        Simulates the race by letting a competing row commit *after*
        ``finalize_booking`` has run its duplicate check.
        """
        when = datetime(2099, 6, 10, 14, 0, tzinfo=NEW_YORK)
        async with AsyncSessionLocal() as db:
            await _workspace(db, workspace_id)
            contact = await _contact(db, workspace_id)
            await db.commit()
            contact_id = contact.id

        async with AsyncSessionLocal() as competitor:
            winner = Appointment(
                workspace_id=workspace_id,
                contact_id=contact_id,
                scheduled_at=when,
                duration_minutes=30,
                status=AppointmentStatus.SCHEDULED,
            )
            competitor.add(winner)
            await competitor.commit()
            winner_id = winner.id

        async with AsyncSessionLocal() as db:
            contact = await db.get(Contact, contact_id)
            assert contact is not None
            original_find = booking_finalizer._find_duplicate
            calls = {"n": 0}

            async def _blind_first_check(*args, **kwargs):
                # First call runs before the competing row is visible to this
                # session's snapshot; later calls (the recovery path) see it.
                calls["n"] += 1
                if calls["n"] == 1:
                    return None
                return await original_find(*args, **kwargs)

            booking_finalizer._find_duplicate = _blind_first_check
            try:
                result = await finalize_booking(
                    db,
                    workspace_id=workspace_id,
                    contact=contact,
                    scheduled_at=when,
                    duration_minutes=30,
                    notify=False,
                )
            finally:
                booking_finalizer._find_duplicate = original_find

            assert result.id == winner_id, "must return the booking that won the race"

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
            assert len(rows) == 1, "the losing insert must leave no row behind"


class TestInviteOrganizer:
    async def test_organizer_is_not_the_attendee(self, workspace_id, monkeypatch) -> None:
        """A self-organized event hides Accept/Decline in clients like Gmail."""
        sink: list[dict[str, Any]] = []

        async def _fake_email(**kwargs):
            sink.append(kwargs)
            return True

        async def _fake_sms(**_kwargs):
            return None

        monkeypatch.setattr(booking_finalizer, "send_appointment_booked_notification", _fake_email)
        monkeypatch.setattr(booking_finalizer, "send_lifecycle_sms", _fake_sms)

        async with AsyncSessionLocal() as db:
            await _workspace(db, workspace_id)
            contact = await _contact(db, workspace_id)
            agent = await _agent(db, workspace_id)
            staff = await _staff(db, workspace_id, agent.id)
            appointment = await finalize_booking(
                db,
                workspace_id=workspace_id,
                contact=contact,
                agent=agent,
                scheduled_at=datetime(2099, 6, 10, 14, 0, tzinfo=NEW_YORK),
                duration_minutes=30,
                assigned_staff_id=staff.id,
                notify=False,
            )

        await deliver_booking_notifications(appointment.id)

        ics = sink[0]["ics_content"].replace("\r\n ", "")
        organizer = next(line for line in ics.split("\r\n") if line.startswith("ORGANIZER"))
        attendee = next(line for line in ics.split("\r\n") if line.startswith("ATTENDEE"))
        assert "sam@example.com" in attendee
        assert "sam@example.com" not in organizer
        assert "mailto:" in organizer
