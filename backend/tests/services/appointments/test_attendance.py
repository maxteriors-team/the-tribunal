"""Attendance marking must leave one contact state, whoever marked it.

An in-app control that only set ``appointments.status`` used to produce a
no-show that
``noshow_reengagement_worker`` (which selects on
``contacts.last_appointment_status`` + the ``no-show`` tag) and the ``no_show``
automation trigger could not see.

The unit tests pin the helper's rules; the integration tests (``-m
integration``) prove the operator-facing ``PUT /appointments/{id}`` path runs
them against a real database.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from app.core.encryption import hash_phone
from app.db.session import AsyncSessionLocal, engine
from app.models.appointment import Appointment, AppointmentStatus
from app.models.contact import Contact
from app.models.tag import ContactTag, Tag
from app.models.workspace import Workspace
from app.schemas.appointment import AppointmentUpdate
from app.services.appointments import AppointmentService, attendance
from app.services.appointments.attendance import (
    NO_SHOW_TAG,
    SHOWED_UP_TAG,
    record_attendance_outcome,
)

# ---------------------------------------------------------------------------
# Unit tests (no DB)
# ---------------------------------------------------------------------------


def _contact(**kw: Any) -> Contact:
    base: dict[str, Any] = {
        "id": 7,
        "workspace_id": uuid.uuid4(),
        "first_name": "Ada",
        "phone_number": "+15125550000",
        "noshow_count": 0,
        "last_appointment_status": None,
    }
    base.update(kw)
    return Contact(**base)


def _appointment(contact: Contact, status: AppointmentStatus) -> Appointment:
    return Appointment(
        id=42,
        workspace_id=contact.workspace_id,
        contact_id=contact.id,
        scheduled_at=datetime.now(UTC),
        status=status,
    )


def _db_returning(contact: Contact | None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=contact)
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.commit = AsyncMock()
    return db


@pytest.fixture
def tag_service(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Stub ``TagService`` in the attendance module's namespace."""
    service = MagicMock()
    service.add_tag_to_contact = AsyncMock(return_value=None)
    monkeypatch.setattr(attendance, "TagService", MagicMock(return_value=service))
    return service


async def test_no_show_applies_tag_status_and_counter(tag_service: MagicMock) -> None:
    contact = _contact()
    db = _db_returning(contact)
    appointment = _appointment(contact, AppointmentStatus.NO_SHOW)

    await record_attendance_outcome(db, appointment, previous_status="scheduled")

    tag_service.add_tag_to_contact.assert_awaited_once_with(
        workspace_id=contact.workspace_id,
        contact_id=contact.id,
        name=NO_SHOW_TAG,
    )
    assert contact.last_appointment_status == "no_show"
    assert contact.noshow_count == 1
    db.commit.assert_not_awaited()  # the caller owns the transaction


async def test_re_marking_a_no_show_does_not_double_count(tag_service: MagicMock) -> None:
    """A replayed webhook or a second click is one absence, not two."""
    contact = _contact(noshow_count=1, last_appointment_status="no_show")
    db = _db_returning(contact)
    appointment = _appointment(contact, AppointmentStatus.NO_SHOW)

    await record_attendance_outcome(db, appointment, previous_status=AppointmentStatus.NO_SHOW)

    assert contact.noshow_count == 1
    assert contact.last_appointment_status == "no_show"


async def test_completed_applies_showed_up_tag_and_leaves_counter(
    tag_service: MagicMock,
) -> None:
    contact = _contact(noshow_count=2)
    db = _db_returning(contact)
    appointment = _appointment(contact, AppointmentStatus.COMPLETED)

    await record_attendance_outcome(db, appointment, previous_status="scheduled")

    tag_service.add_tag_to_contact.assert_awaited_once_with(
        workspace_id=contact.workspace_id,
        contact_id=contact.id,
        name=SHOWED_UP_TAG,
    )
    assert contact.last_appointment_status == "completed"
    assert contact.noshow_count == 2  # a completion never clears history


@pytest.mark.parametrize("status", [AppointmentStatus.SCHEDULED, AppointmentStatus.CANCELLED])
async def test_undecided_and_cancelled_write_nothing(
    tag_service: MagicMock, status: AppointmentStatus
) -> None:
    """Only attended/absent decide a show-up rate; a call-off is neither."""
    contact = _contact()
    db = _db_returning(contact)

    result = await record_attendance_outcome(
        db, _appointment(contact, status), previous_status="scheduled"
    )

    assert result is None
    tag_service.add_tag_to_contact.assert_not_awaited()
    assert contact.last_appointment_status is None
    assert contact.noshow_count == 0


async def test_missing_contact_is_survivable(tag_service: MagicMock) -> None:
    contact = _contact()
    db = _db_returning(None)

    result = await record_attendance_outcome(
        db, _appointment(contact, AppointmentStatus.NO_SHOW), previous_status="scheduled"
    )

    assert result is None
    tag_service.add_tag_to_contact.assert_not_awaited()


# ---------------------------------------------------------------------------
# Integration tests (real DB; run with `-m integration`)
# ---------------------------------------------------------------------------


@pytest.fixture
async def _fresh_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


async def _persist_workspace(db: Any) -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name="Attend", slug=f"attend-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    return ws


async def _persist_contact(db: Any, workspace_id: uuid.UUID) -> Contact:
    phone = f"+1512555{uuid.uuid4().int % 10000:04d}"
    contact = Contact(
        workspace_id=workspace_id,
        first_name="Grace",
        phone_number=phone,
        phone_hash=hash_phone(phone),
    )
    db.add(contact)
    await db.flush()
    return contact


async def _persist_appointment(db: Any, workspace_id: uuid.UUID, contact_id: int) -> Appointment:
    appointment = Appointment(
        workspace_id=workspace_id,
        contact_id=contact_id,
        scheduled_at=datetime.now(UTC) - timedelta(hours=2),
        status=AppointmentStatus.SCHEDULED,
    )
    db.add(appointment)
    await db.flush()
    return appointment


async def _tag_names(db: Any, contact_id: int) -> set[str]:
    rows = await db.execute(
        select(Tag.name)
        .join(ContactTag, ContactTag.tag_id == Tag.id)
        .where(ContactTag.contact_id == contact_id)
    )
    return set(rows.scalars().all())


@pytest.mark.integration
@pytest.mark.asyncio
async def test_in_app_no_show_matches_the_webhook_contract(_fresh_engine_pool: None) -> None:
    """``PUT /appointments/{id}`` to ``no_show`` writes tag + status + counter."""
    async with AsyncSessionLocal() as db:
        ws = await _persist_workspace(db)
        contact = await _persist_contact(db, ws.id)
        appointment = await _persist_appointment(db, ws.id, contact.id)

        await AppointmentService(db).update_appointment(
            ws.id, appointment.id, AppointmentUpdate(status="no_show")
        )

        await db.refresh(contact)
        assert appointment.status == AppointmentStatus.NO_SHOW
        assert contact.last_appointment_status == "no_show"
        assert contact.noshow_count == 1
        assert NO_SHOW_TAG in await _tag_names(db, contact.id)

        # Re-marking the same absence must stay at one.
        await AppointmentService(db).update_appointment(
            ws.id, appointment.id, AppointmentUpdate(status="no_show")
        )
        await db.refresh(contact)
        assert contact.noshow_count == 1

        await db.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_in_app_completed_applies_showed_up_tag(_fresh_engine_pool: None) -> None:
    async with AsyncSessionLocal() as db:
        ws = await _persist_workspace(db)
        contact = await _persist_contact(db, ws.id)
        appointment = await _persist_appointment(db, ws.id, contact.id)

        await AppointmentService(db).update_appointment(
            ws.id, appointment.id, AppointmentUpdate(status="completed")
        )

        await db.refresh(contact)
        assert contact.last_appointment_status == "completed"
        assert contact.noshow_count == 0
        assert SHOWED_UP_TAG in await _tag_names(db, contact.id)

        await db.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_editing_notes_never_touches_attendance(_fresh_engine_pool: None) -> None:
    """A non-status edit must not manufacture a lifecycle tag."""
    async with AsyncSessionLocal() as db:
        ws = await _persist_workspace(db)
        contact = await _persist_contact(db, ws.id)
        appointment = await _persist_appointment(db, ws.id, contact.id)

        await AppointmentService(db).update_appointment(
            ws.id, appointment.id, AppointmentUpdate(notes="Bring the ladder")
        )

        await db.refresh(contact)
        assert contact.last_appointment_status is None
        assert await _tag_names(db, contact.id) == set()

        await db.rollback()
