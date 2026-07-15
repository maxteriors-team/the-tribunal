"""Tests for ``app.api.webhooks.calcom_handlers``.

Each handler is exercised against real Cal.com payload fixtures
(``tests/fixtures/webhooks/calcom/``) with the database session, SMS
side-effects, email notification, push notifications, and campaign
helpers stubbed at the module level.

The goal is to pin the *behavior contracts* the router relies on:

- ``handle_booking_created`` creates an Appointment row, tags the
  contact, fires confirmation SMS / owner email exactly once per
  *new* booking, and idempotently updates an existing row.
- ``handle_booking_rescheduled`` updates the existing appointment and
  resets ``reminder_sent_at`` so the reminder worker re-fires.
- ``handle_booking_cancelled`` marks the appointment ``cancelled`` and
  fires the rebook SMS only for *attendee*-initiated cancellations.
- ``handle_meeting_ended`` distinguishes completion vs no-show and
  applies the matching contact tag + lifecycle SMS.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.webhooks import calcom_handlers as handlers
from app.models.appointment import AppointmentStatus
from tests.fixtures.webhooks import load_calcom_data


def _make_log() -> MagicMock:
    """Logger stub where ``.bind(...)`` returns the same MagicMock.

    The handlers immediately reassign ``log = log.bind(...)`` and then
    invoke ``.info`` / ``.warning`` on the rebound logger, so we need a
    stub that funnels every call back into the same mock for assertion.
    """
    log = MagicMock()
    log.bind = MagicMock(return_value=log)
    return log


# --------------------------------------------------------------------------- #
# Shared mock plumbing
# --------------------------------------------------------------------------- #


class _Result:
    """Stand-in for an ``execute()`` result that supports the call patterns
    used by the handlers (``scalar_one_or_none`` / ``scalars().all`` / ``first``).
    """

    def __init__(
        self,
        scalar: Any = None,
        scalars_list: list[Any] | None = None,
        first: Any = None,
    ) -> None:
        self._scalar = scalar
        self._scalars_list = scalars_list or []
        self._first = first

    def scalar_one_or_none(self) -> Any:
        return self._scalar

    def scalars(self) -> MagicMock:
        wrapper = MagicMock()
        wrapper.all = MagicMock(return_value=self._scalars_list)
        wrapper.first = MagicMock(
            return_value=self._scalars_list[0] if self._scalars_list else None
        )
        return wrapper

    def first(self) -> Any:
        return self._first


def _make_db(execute_returns: list[Any]) -> MagicMock:
    """Build a mock AsyncSession whose ``execute`` yields each result in turn."""
    db = MagicMock()
    db.execute = AsyncMock(side_effect=list(execute_returns))
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.flush = AsyncMock()
    db.get = AsyncMock(return_value=None)
    return db


def _patch_session_local(monkeypatch: pytest.MonkeyPatch, db: MagicMock) -> None:
    """Patch ``AsyncSessionLocal()`` so the ``async with`` yields ``db``."""

    class _CM:
        async def __aenter__(self) -> MagicMock:  # noqa: N805
            return db

        async def __aexit__(self, *exc: Any) -> None:  # noqa: N805
            return None

    monkeypatch.setattr(handlers, "AsyncSessionLocal", lambda: _CM())


def _stub_side_effects(monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
    """Stub every external side-effect helper used by the handlers.

    Returns a dict of the stubs so individual tests can assert against
    them. Helpers are patched on the ``calcom_handlers`` module
    namespace (i.e. the names the handler functions actually resolve).
    """
    stubs: dict[str, MagicMock] = {}

    push = MagicMock()
    push.send_to_workspace_members = AsyncMock(return_value=None)
    monkeypatch.setattr(handlers, "push_notification_service", push)
    stubs["push"] = push

    send_lifecycle_sms = AsyncMock(return_value=None)
    monkeypatch.setattr(handlers, "send_lifecycle_sms", send_lifecycle_sms)
    stubs["send_lifecycle_sms"] = send_lifecycle_sms

    find_recent_voice_message = AsyncMock(return_value=None)
    monkeypatch.setattr(handlers, "find_recent_voice_message", find_recent_voice_message)
    stubs["find_recent_voice_message"] = find_recent_voice_message

    resolve_campaign_id = AsyncMock(return_value=None)
    monkeypatch.setattr(handlers, "resolve_campaign_id", resolve_campaign_id)
    stubs["resolve_campaign_id"] = resolve_campaign_id

    get_workspace_owner = AsyncMock(return_value=None)
    monkeypatch.setattr(handlers, "get_workspace_owner", get_workspace_owner)
    stubs["get_workspace_owner"] = get_workspace_owner

    spawn_background_task = MagicMock(return_value=None)
    monkeypatch.setattr(handlers, "spawn_background_task", spawn_background_task)
    stubs["spawn_background_task"] = spawn_background_task

    send_appointment_booked = MagicMock(return_value=MagicMock())
    monkeypatch.setattr(handlers, "send_appointment_booked_notification", send_appointment_booked)
    stubs["send_appointment_booked_notification"] = send_appointment_booked

    tag_service = MagicMock()
    tag_service.add_tag_to_contact = AsyncMock(return_value=None)
    tag_service_factory = MagicMock(return_value=tag_service)
    monkeypatch.setattr(handlers, "TagService", tag_service_factory)
    stubs["tag_service"] = tag_service

    increment_guarantee = AsyncMock(return_value=None)
    monkeypatch.setattr(handlers, "increment_completed_and_check_guarantee", increment_guarantee)
    stubs["increment_completed_and_check_guarantee"] = increment_guarantee

    build_confirmation_body = MagicMock(return_value="Confirmation SMS body")
    monkeypatch.setattr(handlers, "build_confirmation_body", build_confirmation_body)
    stubs["build_confirmation_body"] = build_confirmation_body

    return stubs


def _make_contact(
    *,
    contact_id: int = 100,
    workspace_id: uuid.UUID | None = None,
) -> MagicMock:
    contact = MagicMock()
    contact.id = contact_id
    contact.workspace_id = workspace_id or uuid.uuid4()
    contact.first_name = "Test"
    contact.last_name = "Client"
    contact.phone_number = "+14155552671"
    contact.email = "client@example.com"
    contact.last_appointment_status = None
    contact.noshow_count = 0
    return contact


def _make_appointment(
    *,
    appt_id: int = 500,
    workspace_id: uuid.UUID | None = None,
    contact_id: int = 100,
    status: str = "scheduled",
    campaign_id: Any = None,
    agent_id: Any = None,
) -> MagicMock:
    appt = MagicMock()
    appt.id = appt_id
    appt.workspace_id = workspace_id or uuid.uuid4()
    appt.contact_id = contact_id
    appt.agent_id = agent_id
    appt.campaign_id = campaign_id
    appt.status = status
    appt.scheduled_at = datetime(2026, 6, 1, 15, 0, tzinfo=UTC)
    appt.reminder_sent_at = datetime(2026, 5, 20, tzinfo=UTC)
    return appt


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def booking_created() -> dict[str, Any]:
    return load_calcom_data("booking_created.json")


@pytest.fixture
def booking_rescheduled() -> dict[str, Any]:
    return load_calcom_data("booking_rescheduled.json")


@pytest.fixture
def booking_cancelled_by_attendee() -> dict[str, Any]:
    return load_calcom_data("booking_cancelled_by_attendee.json")


@pytest.fixture
def booking_cancelled_by_host() -> dict[str, Any]:
    return load_calcom_data("booking_cancelled_by_host.json")


@pytest.fixture
def meeting_ended_completed() -> dict[str, Any]:
    return load_calcom_data("meeting_ended_completed.json")


@pytest.fixture
def meeting_ended_no_show() -> dict[str, Any]:
    return load_calcom_data("meeting_ended_no_show.json")


# --------------------------------------------------------------------------- #
# handle_booking_created
# --------------------------------------------------------------------------- #


async def test_booking_created_returns_early_when_no_attendees() -> None:
    log = _make_log()

    await handlers.handle_booking_created({"uid": "x", "startTime": "x"}, log)

    log.warning.assert_any_call("no_attendees_in_booking")


async def test_booking_created_returns_when_required_fields_missing() -> None:
    log = _make_log()

    await handlers.handle_booking_created(
        {"uid": "", "startTime": "", "attendees": [{"email": "x@y.z"}]},
        log,
    )

    log.warning.assert_any_call("missing_required_fields")


async def test_booking_created_returns_when_contact_not_found(
    monkeypatch: pytest.MonkeyPatch,
    booking_created: dict[str, Any],
) -> None:
    _stub_side_effects(monkeypatch)

    async def _find_contact(*args: Any, **kwargs: Any) -> Any:
        return None

    monkeypatch.setattr(handlers, "find_contact_by_attendee", _find_contact)
    db = _make_db(execute_returns=[])
    _patch_session_local(monkeypatch, db)

    await handlers.handle_booking_created(booking_created, _make_log())

    db.commit.assert_not_awaited()


async def test_booking_created_new_appointment_full_flow(
    monkeypatch: pytest.MonkeyPatch,
    booking_created: dict[str, Any],
) -> None:
    """New booking → tag, status, SMS, push, email, no double-book alert."""
    stubs = _stub_side_effects(monkeypatch)
    workspace_id = uuid.uuid4()
    contact = _make_contact(workspace_id=workspace_id)

    monkeypatch.setattr(
        handlers,
        "find_contact_by_attendee",
        AsyncMock(return_value=contact),
    )
    stubs["get_workspace_owner"].return_value = (
        "owner@acmehome.example",
        "Jane Owner",
    )

    workspace = MagicMock()
    workspace.id = workspace_id
    workspace.settings = {"timezone": "America/Los_Angeles"}

    # execute() call order in handle_booking_created with a NEW booking:
    #   1. Agent lookup (eventTypeId present)
    #   2. BookableStaff lookup by event type (returns [] → none)
    #   3. Appointment lookup by uid          (returns None → new)
    #   4. Workspace lookup for SMS timezone
    #   5. Other-scheduled-appointments query (returns [] → no double-book)
    db = _make_db(
        execute_returns=[
            _Result(scalar=None),  # Agent
            _Result(scalars_list=[]),  # BookableStaff
            _Result(scalar=None),  # Existing Appointment
            _Result(scalar=workspace),  # Workspace
            _Result(scalars_list=[]),  # Other scheduled
        ]
    )

    def _refresh(obj: Any) -> Any:
        # ``refresh`` should populate the row id Cal.com handlers read.
        if not getattr(obj, "id", None):
            obj.id = 777
        return None

    db.refresh = AsyncMock(side_effect=_refresh)
    _patch_session_local(monkeypatch, db)

    await handlers.handle_booking_created(booking_created, _make_log())

    # Contact lifecycle marker moved through normalized TagService
    stubs["tag_service"].add_tag_to_contact.assert_any_await(
        workspace_id=contact.workspace_id,
        contact_id=contact.id,
        name="appointment-scheduled",
    )
    assert contact.last_appointment_status == "scheduled"

    # Appointment created (db.add called with a new Appointment)
    add_calls = [c.args[0] for c in db.add.call_args_list]
    appointment_added = [a for a in add_calls if type(a).__name__ == "Appointment"]
    assert len(appointment_added) == 1
    appt = appointment_added[0]
    assert appt.calcom_booking_uid == "calcom-booking-uid-created-001"
    assert appt.sync_status == "synced"

    db.commit.assert_awaited()
    stubs["build_confirmation_body"].assert_called_once()
    stubs["send_lifecycle_sms"].assert_awaited_once()
    stubs["spawn_background_task"].assert_called_once()
    # Booking-confirmation push fires for new appointment
    stubs["push"].send_to_workspace_members.assert_awaited()


async def test_booking_created_existing_appointment_does_not_send_sms(
    monkeypatch: pytest.MonkeyPatch,
    booking_created: dict[str, Any],
) -> None:
    """Idempotency: a retry that finds an existing Appointment must NOT
    re-send the confirmation SMS or re-queue the owner email.

    This is the ``is_new_booking`` per-row guard documented in
    :mod:`app.api.webhooks.calcom`.
    """
    stubs = _stub_side_effects(monkeypatch)
    workspace_id = uuid.uuid4()
    contact = _make_contact(workspace_id=workspace_id)
    existing_appt = _make_appointment(
        workspace_id=workspace_id,
        contact_id=contact.id,
    )

    monkeypatch.setattr(
        handlers,
        "find_contact_by_attendee",
        AsyncMock(return_value=contact),
    )

    db = _make_db(
        execute_returns=[
            _Result(scalar=None),  # Agent
            _Result(scalars_list=[]),  # BookableStaff
            _Result(scalar=existing_appt),  # Existing Appointment found
            _Result(scalars_list=[]),  # Other scheduled
        ]
    )
    _patch_session_local(monkeypatch, db)

    await handlers.handle_booking_created(booking_created, _make_log())

    # No new Appointment added — we mutated the existing one in place.
    add_types = {type(c.args[0]).__name__ for c in db.add.call_args_list}
    assert "Appointment" not in add_types

    # Critical: SMS + owner email must NOT fire on the retry.
    stubs["send_lifecycle_sms"].assert_not_awaited()
    stubs["spawn_background_task"].assert_not_called()


async def test_booking_created_double_booking_triggers_alert(
    monkeypatch: pytest.MonkeyPatch,
    booking_created: dict[str, Any],
) -> None:
    """Existing scheduled appointment(s) for the contact → double-book push."""
    stubs = _stub_side_effects(monkeypatch)
    workspace_id = uuid.uuid4()
    contact = _make_contact(workspace_id=workspace_id)
    earlier_appt = _make_appointment(
        appt_id=900,
        workspace_id=workspace_id,
        contact_id=contact.id,
    )
    earlier_appt.created_at = datetime(2026, 5, 1, tzinfo=UTC)

    monkeypatch.setattr(
        handlers,
        "find_contact_by_attendee",
        AsyncMock(return_value=contact),
    )

    workspace = MagicMock()
    workspace.settings = {"timezone": "UTC"}

    db = _make_db(
        execute_returns=[
            _Result(scalar=None),  # Agent
            _Result(scalars_list=[]),  # BookableStaff
            _Result(scalar=None),  # New Appointment
            _Result(scalar=workspace),  # Workspace for SMS
            _Result(scalars_list=[earlier_appt]),  # One earlier scheduled
        ]
    )

    def _refresh(obj: Any) -> Any:
        if not getattr(obj, "id", None):
            obj.id = 901
        return None

    db.refresh = AsyncMock(side_effect=_refresh)
    _patch_session_local(monkeypatch, db)

    log = _make_log()
    await handlers.handle_booking_created(booking_created, log)

    # Two push notifications: booking-confirmation + double-booking alert.
    assert stubs["push"].send_to_workspace_members.await_count == 2
    titles = [
        call.kwargs["title"] for call in stubs["push"].send_to_workspace_members.await_args_list
    ]
    assert any("Double Booking" in t for t in titles)


# --------------------------------------------------------------------------- #
# handle_booking_rescheduled
# --------------------------------------------------------------------------- #


async def test_booking_rescheduled_returns_when_uid_or_starttime_missing() -> None:
    log = _make_log()

    await handlers.handle_booking_rescheduled({}, log)

    log.warning.assert_any_call("missing_required_fields")


async def test_booking_rescheduled_returns_when_appointment_missing(
    monkeypatch: pytest.MonkeyPatch,
    booking_rescheduled: dict[str, Any],
) -> None:
    _stub_side_effects(monkeypatch)
    db = _make_db(execute_returns=[_Result(scalar=None)])
    _patch_session_local(monkeypatch, db)
    log = _make_log()

    await handlers.handle_booking_rescheduled(booking_rescheduled, log)

    log.warning.assert_any_call("appointment_not_found")
    db.commit.assert_not_awaited()


async def test_booking_rescheduled_updates_and_resets_reminder(
    monkeypatch: pytest.MonkeyPatch,
    booking_rescheduled: dict[str, Any],
) -> None:
    stubs = _stub_side_effects(monkeypatch)
    workspace_id = uuid.uuid4()
    contact = _make_contact(workspace_id=workspace_id)
    appt = _make_appointment(
        workspace_id=workspace_id,
        contact_id=contact.id,
        agent_id=None,
    )
    workspace = MagicMock()
    workspace.settings = {"timezone": "America/Los_Angeles"}

    db = _make_db(
        execute_returns=[
            _Result(scalar=appt),  # Appointment lookup
            _Result(scalar=contact),  # Contact lookup for SMS
            _Result(scalar=workspace),  # Workspace lookup for tz
            _Result(scalar=contact),  # Contact lookup for push
        ]
    )
    _patch_session_local(monkeypatch, db)

    await handlers.handle_booking_rescheduled(booking_rescheduled, _make_log())

    # Reminder was reset so the worker re-fires for the new time.
    assert appt.reminder_sent_at is None
    assert appt.sync_status == "synced"
    # Rescheduled SMS fired
    stubs["send_lifecycle_sms"].assert_awaited_once()
    # Push notification fired
    stubs["push"].send_to_workspace_members.assert_awaited()


# --------------------------------------------------------------------------- #
# handle_booking_cancelled
# --------------------------------------------------------------------------- #


async def test_booking_cancelled_returns_when_uid_missing() -> None:
    log = _make_log()

    await handlers.handle_booking_cancelled({}, log)

    log.warning.assert_any_call("missing_booking_uid")


async def test_booking_cancelled_returns_when_appointment_missing(
    monkeypatch: pytest.MonkeyPatch,
    booking_cancelled_by_attendee: dict[str, Any],
) -> None:
    _stub_side_effects(monkeypatch)
    db = _make_db(execute_returns=[_Result(scalar=None)])
    _patch_session_local(monkeypatch, db)
    log = _make_log()

    await handlers.handle_booking_cancelled(booking_cancelled_by_attendee, log)

    log.warning.assert_any_call("appointment_not_found")


async def test_booking_cancelled_by_attendee_fires_rebook_sms(
    monkeypatch: pytest.MonkeyPatch,
    booking_cancelled_by_attendee: dict[str, Any],
) -> None:
    stubs = _stub_side_effects(monkeypatch)
    workspace_id = uuid.uuid4()
    contact = _make_contact(workspace_id=workspace_id)
    appt = _make_appointment(workspace_id=workspace_id, contact_id=contact.id)

    db = _make_db(
        execute_returns=[
            _Result(scalar=appt),  # Appointment
            _Result(scalar=contact),  # Contact for tag update
            _Result(scalar=contact),  # Contact for SMS
            _Result(scalar=contact),  # Contact for push
        ]
    )
    _patch_session_local(monkeypatch, db)

    await handlers.handle_booking_cancelled(
        booking_cancelled_by_attendee,
        _make_log(),
    )

    assert appt.status == AppointmentStatus.CANCELLED
    stubs["tag_service"].add_tag_to_contact.assert_any_await(
        workspace_id=contact.workspace_id,
        contact_id=contact.id,
        name="appointment-cancelled",
    )
    assert contact.last_appointment_status == "cancelled"
    stubs["send_lifecycle_sms"].assert_awaited_once()
    stubs["push"].send_to_workspace_members.assert_awaited()


async def test_booking_cancelled_by_host_skips_rebook_sms(
    monkeypatch: pytest.MonkeyPatch,
    booking_cancelled_by_host: dict[str, Any],
) -> None:
    """Host-initiated cancellations must NOT prompt the attendee to rebook."""
    stubs = _stub_side_effects(monkeypatch)
    workspace_id = uuid.uuid4()
    contact = _make_contact(workspace_id=workspace_id)
    appt = _make_appointment(workspace_id=workspace_id, contact_id=contact.id)

    db = _make_db(
        execute_returns=[
            _Result(scalar=appt),  # Appointment
            _Result(scalar=contact),  # Contact for tag update
            _Result(scalar=contact),  # Contact for push (no SMS lookup branch)
        ]
    )
    _patch_session_local(monkeypatch, db)

    await handlers.handle_booking_cancelled(
        booking_cancelled_by_host,
        _make_log(),
    )

    assert appt.status == AppointmentStatus.CANCELLED
    stubs["send_lifecycle_sms"].assert_not_awaited()


# --------------------------------------------------------------------------- #
# handle_meeting_ended
# --------------------------------------------------------------------------- #


async def test_meeting_ended_returns_when_uid_missing() -> None:
    log = _make_log()

    await handlers.handle_meeting_ended({}, log)

    log.warning.assert_any_call("missing_booking_uid")


async def test_meeting_ended_returns_when_appointment_missing(
    monkeypatch: pytest.MonkeyPatch,
    meeting_ended_completed: dict[str, Any],
) -> None:
    _stub_side_effects(monkeypatch)
    db = _make_db(execute_returns=[_Result(scalar=None)])
    _patch_session_local(monkeypatch, db)
    log = _make_log()

    await handlers.handle_meeting_ended(meeting_ended_completed, log)

    log.warning.assert_any_call("appointment_not_found")


async def test_meeting_ended_terminal_state_short_circuits(
    monkeypatch: pytest.MonkeyPatch,
    meeting_ended_completed: dict[str, Any],
) -> None:
    """Idempotency: appointment already COMPLETED or CANCELLED → no-op."""
    stubs = _stub_side_effects(monkeypatch)
    appt = _make_appointment(status=AppointmentStatus.COMPLETED)

    db = _make_db(execute_returns=[_Result(scalar=appt)])
    _patch_session_local(monkeypatch, db)

    await handlers.handle_meeting_ended(meeting_ended_completed, _make_log())

    db.commit.assert_not_awaited()
    stubs["send_lifecycle_sms"].assert_not_awaited()


async def test_meeting_ended_marks_completed_and_increments_guarantee(
    monkeypatch: pytest.MonkeyPatch,
    meeting_ended_completed: dict[str, Any],
) -> None:
    stubs = _stub_side_effects(monkeypatch)
    workspace_id = uuid.uuid4()
    contact = _make_contact(workspace_id=workspace_id)
    campaign_id = uuid.uuid4()
    appt = _make_appointment(
        workspace_id=workspace_id,
        contact_id=contact.id,
        campaign_id=campaign_id,
    )

    db = _make_db(
        execute_returns=[
            _Result(scalar=appt),  # Appointment
            _Result(scalar=contact),  # Contact for tag
            _Result(scalar=contact),  # Contact for post-meeting SMS branch
        ]
    )
    _patch_session_local(monkeypatch, db)

    await handlers.handle_meeting_ended(meeting_ended_completed, _make_log())

    assert appt.status == AppointmentStatus.COMPLETED
    stubs["tag_service"].add_tag_to_contact.assert_any_await(
        workspace_id=contact.workspace_id,
        contact_id=contact.id,
        name="showed-up",
    )
    assert contact.last_appointment_status == "completed"
    stubs["increment_completed_and_check_guarantee"].assert_awaited_once()
    # No agent → post_meeting_template branch doesn't fire
    stubs["send_lifecycle_sms"].assert_not_awaited()


async def test_meeting_ended_marks_no_show_and_increments_count(
    monkeypatch: pytest.MonkeyPatch,
    meeting_ended_no_show: dict[str, Any],
) -> None:
    stubs = _stub_side_effects(monkeypatch)
    workspace_id = uuid.uuid4()
    contact = _make_contact(workspace_id=workspace_id)
    contact.noshow_count = 1
    appt = _make_appointment(
        workspace_id=workspace_id,
        contact_id=contact.id,
        agent_id=None,
    )

    db = _make_db(
        execute_returns=[
            _Result(scalar=appt),  # Appointment
            _Result(scalar=contact),  # Contact for tag update
            _Result(scalar=contact),  # Contact for no-show SMS
        ]
    )
    _patch_session_local(monkeypatch, db)

    await handlers.handle_meeting_ended(meeting_ended_no_show, _make_log())

    assert appt.status == AppointmentStatus.NO_SHOW
    stubs["tag_service"].add_tag_to_contact.assert_any_await(
        workspace_id=contact.workspace_id,
        contact_id=contact.id,
        name="no-show",
    )
    assert contact.last_appointment_status == "no_show"
    assert contact.noshow_count == 2
    # No agent → default no-show SMS body is sent
    stubs["send_lifecycle_sms"].assert_awaited_once()
    # No campaign → guarantee tracker not invoked
    stubs["increment_completed_and_check_guarantee"].assert_not_awaited()


# --------------------------------------------------------------------------- #
# Router-level integration — signature validation + replay rejection
# --------------------------------------------------------------------------- #


import hashlib  # noqa: E402
import hmac  # noqa: E402
import json as _json  # noqa: E402
import time  # noqa: E402
from collections.abc import AsyncIterator  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.api.webhooks import calcom as calcom_module  # noqa: E402
from app.api.webhooks.calcom import router as calcom_router  # noqa: E402
from app.core.config import settings as app_settings  # noqa: E402


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


def _make_signed_request(
    payload: dict[str, Any],
    secret: str,
) -> tuple[bytes, dict[str, str]]:
    body = _json.dumps(payload).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    headers = {
        "content-type": "application/json",
        "x-cal-signature-256": signature,
        "x-cal-timestamp": str(int(time.time())),
    }
    return body, headers


def _make_app() -> FastAPI:
    app = FastAPI(lifespan=_test_lifespan)
    app.include_router(calcom_router, prefix="/webhooks/calcom")
    return app


async def _client() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=_make_app()),
        base_url="http://testserver",
    )


async def test_router_rejects_request_without_signature(
    monkeypatch: pytest.MonkeyPatch,
    booking_created: dict[str, Any],
) -> None:
    """Missing ``x-cal-signature-256`` → 403 and no handler invocation."""
    monkeypatch.setattr(app_settings, "skip_webhook_verification", False)
    monkeypatch.setattr(app_settings, "calcom_webhook_secret", "secret-xyz")

    handler = AsyncMock()
    monkeypatch.setitem(
        calcom_module._EVENT_DISPATCH,
        "BOOKING_CREATED",
        handler,
    )

    async with await _client() as ac:
        response = await ac.post(
            "/webhooks/calcom/booking",
            content=_json.dumps(
                {
                    "trigger": "BOOKING_CREATED",
                    "createdAt": "2026-05-15T10:00:00Z",
                    "data": booking_created,
                }
            ),
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 403
    handler.assert_not_awaited()


async def test_router_rejects_request_with_invalid_signature(
    monkeypatch: pytest.MonkeyPatch,
    booking_created: dict[str, Any],
) -> None:
    monkeypatch.setattr(app_settings, "skip_webhook_verification", False)
    monkeypatch.setattr(app_settings, "calcom_webhook_secret", "secret-xyz")

    handler = AsyncMock()
    monkeypatch.setitem(
        calcom_module._EVENT_DISPATCH,
        "BOOKING_CREATED",
        handler,
    )

    async with await _client() as ac:
        response = await ac.post(
            "/webhooks/calcom/booking",
            content=_json.dumps(
                {
                    "trigger": "BOOKING_CREATED",
                    "createdAt": "2026-05-15T10:00:00Z",
                    "data": booking_created,
                }
            ),
            headers={
                "content-type": "application/json",
                "x-cal-signature-256": "deadbeef" * 8,
                "x-cal-timestamp": str(int(time.time())),
            },
        )

    assert response.status_code == 403
    handler.assert_not_awaited()


async def test_router_rejects_stale_timestamp(
    monkeypatch: pytest.MonkeyPatch,
    booking_created: dict[str, Any],
) -> None:
    """Timestamp older than 5 minutes → 403 (replay-attack protection)."""
    secret = "secret-xyz"
    monkeypatch.setattr(app_settings, "skip_webhook_verification", False)
    monkeypatch.setattr(app_settings, "calcom_webhook_secret", secret)

    payload = {
        "trigger": "BOOKING_CREATED",
        "createdAt": "2026-05-15T10:00:00Z",
        "data": booking_created,
    }
    body = _json.dumps(payload).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    stale_ts = str(int(time.time()) - 3600)  # 1 hour old

    async with await _client() as ac:
        response = await ac.post(
            "/webhooks/calcom/booking",
            content=body,
            headers={
                "content-type": "application/json",
                "x-cal-signature-256": sig,
                "x-cal-timestamp": stale_ts,
            },
        )

    assert response.status_code == 403


async def test_router_accepts_valid_signature_and_dispatches(
    monkeypatch: pytest.MonkeyPatch,
    booking_created: dict[str, Any],
) -> None:
    secret = "secret-xyz"
    monkeypatch.setattr(app_settings, "skip_webhook_verification", False)
    monkeypatch.setattr(app_settings, "calcom_webhook_secret", secret)

    handler = AsyncMock()
    monkeypatch.setitem(
        calcom_module._EVENT_DISPATCH,
        "BOOKING_CREATED",
        handler,
    )
    # Force the dedupe slot claim to succeed (avoid talking to Redis).
    monkeypatch.setattr(
        calcom_module,
        "_claim_webhook_delivery",
        AsyncMock(return_value=True),
    )

    payload = {
        "trigger": "BOOKING_CREATED",
        "createdAt": "2026-05-15T10:00:00Z",
        "data": booking_created,
    }
    body, headers = _make_signed_request(payload, secret)

    async with await _client() as ac:
        response = await ac.post(
            "/webhooks/calcom/booking",
            content=body,
            headers=headers,
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    handler.assert_awaited_once()


async def test_router_replay_returns_200_without_invoking_handler(
    monkeypatch: pytest.MonkeyPatch,
    booking_created: dict[str, Any],
) -> None:
    """Replay of a previously-seen delivery → 200 + ``deduped: true``,
    handler never fires. Mirrors the dedupe contract documented in
    :mod:`app.api.webhooks.calcom`.
    """
    secret = "secret-xyz"
    monkeypatch.setattr(app_settings, "skip_webhook_verification", False)
    monkeypatch.setattr(app_settings, "calcom_webhook_secret", secret)

    handler = AsyncMock()
    monkeypatch.setitem(
        calcom_module._EVENT_DISPATCH,
        "BOOKING_CREATED",
        handler,
    )
    # Second delivery → dedupe slot already taken → False.
    monkeypatch.setattr(
        calcom_module,
        "_claim_webhook_delivery",
        AsyncMock(return_value=False),
    )

    payload = {
        "trigger": "BOOKING_CREATED",
        "createdAt": "2026-05-15T10:00:00Z",
        "data": booking_created,
    }
    body, headers = _make_signed_request(payload, secret)

    async with await _client() as ac:
        response = await ac.post(
            "/webhooks/calcom/booking",
            content=body,
            headers=headers,
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "deduped": "true"}
    handler.assert_not_awaited()
