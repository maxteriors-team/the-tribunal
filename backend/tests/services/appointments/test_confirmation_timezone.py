"""A confirmation text must quote the hour the customer actually agreed to.

Regression for a live incident: a customer accepted "Tuesday, Aug 18 at 2:00 PM
(Eastern)" in an SMS thread and was immediately texted "Your appointment is
confirmed for Tuesday, August 18 at 6:00 PM". 2 PM Eastern is 18:00Z, and the
confirmation renderer fell back to UTC while the booking agent fell back to
Eastern — so the same row was quoted twice, in two zones, and the customer read
the wrong one.

Nothing in provisioning or onboarding writes ``workspace.settings["timezone"]``,
so the fallback *is* the production path for every workspace. These tests pin
the unset-timezone case specifically.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.models.agent import Agent
from app.models.appointment import Appointment
from app.models.contact import Contact
from app.models.workspace import Workspace
from app.services.appointments.lifecycle_sms import build_confirmation_body
from app.utils.timezones import resolve_workspace_timezone

# 2:00 PM Eastern on the day Greg booked.
GREGS_SLOT = datetime(2026, 8, 18, 18, 0, tzinfo=UTC)


def _workspace(settings: dict | None) -> Workspace:
    return Workspace(id=uuid.uuid4(), name="Maxteriors Lighting", settings=settings)


def _contact(first_name: str = "Greg") -> Contact:
    return Contact(id=1, workspace_id=uuid.uuid4(), first_name=first_name)


def _appointment(scheduled_at: datetime = GREGS_SLOT) -> Appointment:
    return Appointment(id=1, contact_id=1, scheduled_at=scheduled_at, duration_minutes=30)


def test_unset_workspace_timezone_renders_the_booked_eastern_hour() -> None:
    body = build_confirmation_body(
        contact=_contact(),
        appointment=_appointment(),
        workspace=_workspace({}),
        agent=None,
    )
    assert "2:00 PM" in body
    assert "6:00 PM" not in body
    assert "Tuesday, August 18" in body


def test_missing_settings_dict_does_not_shift_the_hour() -> None:
    body = build_confirmation_body(
        contact=_contact(),
        appointment=_appointment(),
        workspace=_workspace(None),
        agent=None,
    )
    assert "2:00 PM" in body


def test_no_workspace_at_all_still_renders_eastern() -> None:
    body = build_confirmation_body(
        contact=_contact(),
        appointment=_appointment(),
        workspace=None,
        agent=None,
    )
    assert "2:00 PM" in body


def test_configured_timezone_is_honoured_over_the_default() -> None:
    body = build_confirmation_body(
        contact=_contact(),
        appointment=_appointment(),
        workspace=_workspace({"timezone": "America/Denver"}),
        agent=None,
    )
    assert "12:00 PM" in body


def test_evening_booking_does_not_roll_onto_the_wrong_day() -> None:
    """The failure mode is worse than an offset: UTC also moves the date.

    8:00 PM Eastern is 00:00Z the *next* day, so a UTC render told the customer
    a different weekday than the one they agreed to.
    """
    eight_pm_eastern = datetime(2026, 8, 19, 0, 0, tzinfo=UTC)
    body = build_confirmation_body(
        contact=_contact(),
        appointment=_appointment(eight_pm_eastern),
        workspace=_workspace({}),
        agent=None,
    )
    assert "Tuesday, August 18" in body
    assert "8:00 PM" in body
    assert "Wednesday" not in body


def test_agent_template_placeholders_use_the_same_zone() -> None:
    agent = Agent(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        name="Lighting Agent",
        reminder_template="See you {appointment_datetime}!",
    )
    body = build_confirmation_body(
        contact=_contact(),
        appointment=_appointment(),
        workspace=_workspace({}),
        agent=agent,
    )
    assert body == "See you Tuesday, August 18 at 2:00 PM!"


def test_unparseable_timezone_falls_back_instead_of_shifting() -> None:
    assert str(resolve_workspace_timezone(_workspace({"timezone": "Not/AZone"}))) == (
        "America/New_York"
    )
    assert str(resolve_workspace_timezone(_workspace({"timezone": "   "}))) == "America/New_York"
