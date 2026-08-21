"""Integration coverage for the internal time and attendance MVP.

Requires local PostgreSQL migrated through ``20260821_attendance_pauses``.
"""

from __future__ import annotations

import csv
import hashlib
import io
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_membership, get_transactional_db
from app.api.v1 import attendance as attendance_api
from app.db.session import AsyncSessionLocal, engine, transaction_boundary
from app.models.attendance import (
    ATTENDANCE_SOURCE_CLOCK,
    ATTENDANCE_SOURCE_MANUAL,
    ATTENDANCE_STATUS_COMPLETE,
    ATTENDANCE_STATUS_OPEN,
    ATTENDANCE_STATUS_VOID,
    AttendanceEntry,
    AttendanceEvent,
    AttendanceExport,
    AttendancePause,
)
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.schemas.attendance import (
    AttendanceClockInRequest,
    AttendanceClockOutRequest,
    AttendanceEntryUpdateRequest,
    AttendanceExportRequest,
    AttendanceManualEntryRequest,
    AttendancePauseRequest,
    AttendanceVoidRequest,
)
from app.services.attendance import AttendanceService
from app.services.exceptions import ConflictError

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class Seed:
    workspace_id: uuid.UUID
    other_workspace_id: uuid.UUID
    admin_id: int
    member_id: int
    second_member_id: int
    outsider_id: int


@asynccontextmanager
async def _seeded() -> AsyncIterator[Seed]:
    await engine.dispose()
    workspace_id = uuid.uuid4()
    other_workspace_id = uuid.uuid4()
    user_ids: list[int] = []
    async with AsyncSessionLocal() as db:
        workspace = Workspace(
            id=workspace_id,
            name="Attendance Test Co",
            slug=f"attendance-{uuid.uuid4().hex[:10]}",
            settings={"timezone": "America/New_York"},
        )
        other_workspace = Workspace(
            id=other_workspace_id,
            name="Other Attendance Co",
            slug=f"attendance-other-{uuid.uuid4().hex[:10]}",
            settings={"timezone": "UTC"},
        )
        users = [
            User(
                email=f"admin-{uuid.uuid4().hex}@example.com",
                hashed_password="x",
                full_name="Admin",
            ),
            User(
                email=f"member-{uuid.uuid4().hex}@example.com",
                hashed_password="x",
                full_name="Member",
            ),
            User(
                email=f"second-{uuid.uuid4().hex}@example.com",
                hashed_password="x",
                full_name="Second Member",
            ),
            User(
                email=f"outside-{uuid.uuid4().hex}@example.com",
                hashed_password="x",
                full_name="Outsider",
            ),
        ]
        db.add_all([workspace, other_workspace, *users])
        await db.flush()
        user_ids = [user.id for user in users]
        db.add_all(
            [
                WorkspaceMembership(workspace_id=workspace_id, user_id=users[0].id, role="owner"),
                WorkspaceMembership(
                    workspace_id=workspace_id, user_id=users[1].id, role="technician"
                ),
                WorkspaceMembership(workspace_id=workspace_id, user_id=users[2].id, role="member"),
                WorkspaceMembership(
                    workspace_id=other_workspace_id,
                    user_id=users[3].id,
                    role="owner",
                ),
            ]
        )
        await db.commit()
        seed = Seed(
            workspace_id=workspace_id,
            other_workspace_id=other_workspace_id,
            admin_id=users[0].id,
            member_id=users[1].id,
            second_member_id=users[2].id,
            outsider_id=users[3].id,
        )
    try:
        yield seed
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(Workspace).where(Workspace.id.in_([workspace_id, other_workspace_id]))
            )
            await db.commit()
            await db.execute(delete(User).where(User.id.in_(user_ids)))
            await db.commit()
        await engine.dispose()


async def _membership(
    db: AsyncSession, workspace_id: uuid.UUID, user_id: int
) -> WorkspaceMembership:
    return (
        await db.execute(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == user_id,
            )
        )
    ).scalar_one()


async def test_clock_actions_are_idempotent_and_audited() -> None:
    async with _seeded() as seed, AsyncSessionLocal() as db:
        membership = await _membership(db, seed.workspace_id, seed.member_id)
        service = AttendanceService(db)
        clock_in_request = AttendanceClockInRequest(request_id=uuid.uuid4(), note="On site")

        first_in = await service.clock_in(seed.workspace_id, membership, clock_in_request)
        retry_in = await service.clock_in(seed.workspace_id, membership, clock_in_request)
        assert retry_in.id == first_in.id

        clock_out_request = AttendanceClockOutRequest(request_id=uuid.uuid4())
        first_out = await service.clock_out(seed.workspace_id, membership, clock_out_request)
        retry_out = await service.clock_out(seed.workspace_id, membership, clock_out_request)
        assert retry_out.id == first_out.id == first_in.id
        assert first_out.status == ATTENDANCE_STATUS_COMPLETE

        events = list(
            (
                await db.execute(
                    select(AttendanceEvent)
                    .where(AttendanceEvent.entry_id == first_in.id)
                    .order_by(AttendanceEvent.created_at)
                )
            )
            .scalars()
            .all()
        )
        assert [event.action for event in events] == ["clock_in", "clock_out"]
        assert all("note" not in event.changes for event in events)
        assert events[0].changes["note_present"] is True


async def test_pause_resume_are_idempotent_audited_and_excluded_from_worked_time() -> None:
    async with _seeded() as seed, AsyncSessionLocal() as db:
        membership = await _membership(db, seed.workspace_id, seed.member_id)
        service = AttendanceService(db)
        clocked_in = await service.clock_in(
            seed.workspace_id,
            membership,
            AttendanceClockInRequest(request_id=uuid.uuid4()),
        )
        entry = await db.get(AttendanceEntry, clocked_in.id)
        assert entry is not None
        entry.started_at = datetime.now(UTC) - timedelta(hours=2)
        await db.flush()

        pause_request = AttendancePauseRequest(request_id=uuid.uuid4())
        paused = await service.pause_shift(seed.workspace_id, membership, pause_request)
        pause_retry = await service.pause_shift(seed.workspace_id, membership, pause_request)
        assert paused.id == pause_retry.id == entry.id
        assert paused.is_paused is True
        assert paused.pause_started_at is not None

        with pytest.raises(ConflictError, match="already paused"):
            await service.pause_shift(
                seed.workspace_id,
                membership,
                AttendancePauseRequest(request_id=uuid.uuid4()),
            )

        first_pause = (
            await db.execute(
                select(AttendancePause).where(AttendancePause.entry_id == entry.id)
            )
        ).scalar_one()
        first_pause.started_at = datetime.now(UTC) - timedelta(minutes=30)
        await db.flush()

        resume_request = AttendancePauseRequest(request_id=uuid.uuid4())
        resumed = await service.resume_shift(seed.workspace_id, membership, resume_request)
        resume_retry = await service.resume_shift(seed.workspace_id, membership, resume_request)
        assert resumed.id == resume_retry.id == entry.id
        assert resumed.is_paused is False
        assert 1790 <= resumed.paused_seconds <= 1810

        await service.pause_shift(
            seed.workspace_id,
            membership,
            AttendancePauseRequest(request_id=uuid.uuid4()),
        )
        pauses = list(
            (
                await db.execute(
                    select(AttendancePause)
                    .where(AttendancePause.entry_id == entry.id)
                    .order_by(AttendancePause.started_at)
                )
            )
            .scalars()
            .all()
        )
        assert len(pauses) == 2

        clock_out_request = AttendanceClockOutRequest(request_id=uuid.uuid4())
        complete = await service.clock_out(seed.workspace_id, membership, clock_out_request)
        assert complete.status == ATTENDANCE_STATUS_COMPLETE
        assert complete.is_paused is False
        assert 1790 <= complete.paused_seconds <= 1810
        assert complete.duration_seconds == (
            complete.gross_duration_seconds - complete.paused_seconds
        )

        await db.refresh(pauses[-1])
        assert pauses[-1].end_action == "clock_out"
        assert pauses[-1].end_request_id == clock_out_request.request_id
        events = list(
            (
                await db.execute(
                    select(AttendanceEvent)
                    .where(AttendanceEvent.entry_id == entry.id)
                    .order_by(AttendanceEvent.created_at)
                )
            )
            .scalars()
            .all()
        )
        assert [event.action for event in events] == [
            "clock_in",
            "pause",
            "resume",
            "pause",
            "clock_out",
        ]


async def test_overlap_rejected_manual_reason_audited_and_void_not_deleted() -> None:
    async with _seeded() as seed, AsyncSessionLocal() as db:
        admin = await _membership(db, seed.workspace_id, seed.admin_id)
        service = AttendanceService(db)
        started = datetime.now(UTC) - timedelta(days=2)
        first = await service.create_manual_entry(
            seed.workspace_id,
            admin,
            AttendanceManualEntryRequest(
                request_id=uuid.uuid4(),
                reason="Missed shift entered from signed timesheet",
                user_id=seed.member_id,
                started_at=started,
                ended_at=started + timedelta(hours=8),
                note="Crew A",
            ),
        )
        with pytest.raises(ConflictError, match="overlaps"):
            await service.create_manual_entry(
                seed.workspace_id,
                admin,
                AttendanceManualEntryRequest(
                    request_id=uuid.uuid4(),
                    reason="Second paper record",
                    user_id=seed.member_id,
                    started_at=started + timedelta(hours=1),
                    ended_at=started + timedelta(hours=2),
                ),
            )

        voided = await service.void_entry(
            seed.workspace_id,
            admin,
            first.id,
            AttendanceVoidRequest(request_id=uuid.uuid4(), reason="Duplicate paper record"),
        )
        assert voided.status == ATTENDANCE_STATUS_VOID
        persisted = await db.get(AttendanceEntry, first.id)
        assert persisted is not None
        assert persisted.status == ATTENDANCE_STATUS_VOID
        events = list(
            (
                await db.execute(
                    select(AttendanceEvent)
                    .where(AttendanceEvent.entry_id == first.id)
                    .order_by(AttendanceEvent.created_at)
                )
            )
            .scalars()
            .all()
        )
        assert [event.action for event in events] == ["manual_create", "void"]
        assert events[0].reason == "Missed shift entered from signed timesheet"
        assert events[1].reason == "Duplicate paper record"
        assert "reason" not in events[1].changes


async def test_admin_mutation_retries_are_idempotent_and_scoped() -> None:
    async with _seeded() as seed, AsyncSessionLocal() as db:
        admin = await _membership(db, seed.workspace_id, seed.admin_id)
        service = AttendanceService(db)
        started = datetime.now(UTC) - timedelta(days=4)
        entry = await service.create_manual_entry(
            seed.workspace_id,
            admin,
            AttendanceManualEntryRequest(
                request_id=uuid.uuid4(),
                reason="Imported signed timecard",
                user_id=seed.member_id,
                started_at=started,
                ended_at=started + timedelta(hours=7),
            ),
        )

        edit_request_id = uuid.uuid4()
        update = AttendanceEntryUpdateRequest(
            request_id=edit_request_id,
            reason="Corrected against the signed timecard",
            ended_at=started + timedelta(hours=8),
        )
        first_edit = await service.update_entry(seed.workspace_id, admin, entry.id, update)
        retry_edit = await service.update_entry(seed.workspace_id, admin, entry.id, update)
        assert retry_edit.id == first_edit.id
        assert retry_edit.duration_seconds == first_edit.duration_seconds == 8 * 3600

        edit_events = list(
            (
                await db.execute(
                    select(AttendanceEvent).where(
                        AttendanceEvent.workspace_id == seed.workspace_id,
                        AttendanceEvent.request_id == edit_request_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert [event.action for event in edit_events] == ["edit"]

        with pytest.raises(ConflictError, match="request_id has already been used"):
            await service.void_entry(
                seed.workspace_id,
                admin,
                entry.id,
                AttendanceVoidRequest(
                    request_id=edit_request_id,
                    reason="A reused edit key cannot void an entry",
                ),
            )

        void_request = AttendanceVoidRequest(
            request_id=uuid.uuid4(),
            reason="Duplicate record confirmed by manager",
        )
        first_void = await service.void_entry(seed.workspace_id, admin, entry.id, void_request)
        retry_void = await service.void_entry(seed.workspace_id, admin, entry.id, void_request)
        assert first_void.status == retry_void.status == ATTENDANCE_STATUS_VOID
        void_events = list(
            (
                await db.execute(
                    select(AttendanceEvent).where(
                        AttendanceEvent.workspace_id == seed.workspace_id,
                        AttendanceEvent.request_id == void_request.request_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert [event.action for event in void_events] == ["void"]


async def test_csv_is_safe_audited_and_excludes_open_void_and_other_workspace() -> None:
    async with _seeded() as seed, AsyncSessionLocal() as db:
        zone = ZoneInfo("America/New_York")
        local_day = date.today() - timedelta(days=3)
        start = datetime.combine(local_day, time(hour=9), tzinfo=zone).astimezone(UTC)
        complete = AttendanceEntry(
            workspace_id=seed.workspace_id,
            user_id=seed.member_id,
            started_at=start,
            ended_at=start + timedelta(hours=1, minutes=30),
            status=ATTENDANCE_STATUS_COMPLETE,
            source=ATTENDANCE_SOURCE_MANUAL,
            note="@SUM(1+1)",
            created_by_id=seed.admin_id,
        )
        open_entry = AttendanceEntry(
            workspace_id=seed.workspace_id,
            user_id=seed.second_member_id,
            started_at=start,
            ended_at=None,
            status=ATTENDANCE_STATUS_OPEN,
            source=ATTENDANCE_SOURCE_CLOCK,
            note="=OPEN()",
            created_by_id=seed.second_member_id,
        )
        void_entry = AttendanceEntry(
            workspace_id=seed.workspace_id,
            user_id=seed.member_id,
            started_at=start,
            ended_at=start + timedelta(hours=2),
            status=ATTENDANCE_STATUS_VOID,
            source=ATTENDANCE_SOURCE_MANUAL,
            note="+VOID()",
            created_by_id=seed.admin_id,
        )
        foreign_entry = AttendanceEntry(
            workspace_id=seed.other_workspace_id,
            user_id=seed.outsider_id,
            started_at=start,
            ended_at=start + timedelta(hours=4),
            status=ATTENDANCE_STATUS_COMPLETE,
            source=ATTENDANCE_SOURCE_MANUAL,
            note="-FOREIGN()",
            created_by_id=seed.outsider_id,
        )
        db.add_all([complete, open_entry, void_entry, foreign_entry])
        member = await db.get(User, seed.member_id)
        assert member is not None
        member.full_name = "=CMD|' /C calc'!A0"
        await db.flush()

        admin = await _membership(db, seed.workspace_id, seed.admin_id)
        request_id = uuid.uuid4()
        result = await AttendanceService(db).export_csv(
            seed.workspace_id,
            admin,
            AttendanceExportRequest(
                request_id=request_id,
                date_from=local_day,
                date_to=local_day,
            ),
        )
        assert result.content.endswith(b"\r\n")
        assert b"\r\n" in result.content
        rows = list(csv.DictReader(io.StringIO(result.content.decode("utf-8"))))
        assert len(rows) == 1
        assert rows[0]["entry_id"] == str(complete.id)
        assert rows[0]["employee_name"].startswith("'=")
        assert rows[0]["note"].startswith("'@")
        assert rows[0]["gross_hours"] == "1.5000"
        assert rows[0]["paused_hours"] == "0.0000"
        assert rows[0]["total_hours"] == "1.5000"
        assert rows[0]["clock_in"].endswith("-04:00")

        audit = (
            await db.execute(
                select(AttendanceExport).where(
                    AttendanceExport.workspace_id == seed.workspace_id,
                    AttendanceExport.request_id == request_id,
                )
            )
        ).scalar_one()
        assert audit.row_count == 1
        assert audit.total_seconds == 5400
        assert audit.entry_ids == [str(complete.id)]
        assert audit.sha256 == hashlib.sha256(result.content).hexdigest()
        assert not hasattr(audit, "content")


@asynccontextmanager
async def _test_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield


def _api_app(seed: Seed, principal: dict[str, Any]) -> FastAPI:
    app = FastAPI(lifespan=_test_lifespan)

    async def override_db() -> AsyncIterator[AsyncSession]:
        async with AsyncSessionLocal() as db:
            yield db

    async def override_transactional_db() -> AsyncIterator[AsyncSession]:
        async with AsyncSessionLocal() as db, transaction_boundary(db):
            yield db

    async def override_membership() -> MagicMock:
        membership = MagicMock()
        membership.workspace_id = seed.workspace_id
        membership.user_id = principal["user_id"]
        membership.role = principal["role"]
        return membership

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_transactional_db] = override_transactional_db
    app.dependency_overrides[get_membership] = override_membership
    app.include_router(
        attendance_api.router,
        prefix="/api/v1/workspaces/{workspace_id}/attendance",
    )
    return app


async def test_api_authorization_and_cross_workspace_target_are_enforced() -> None:
    async with _seeded() as seed:
        started = datetime.now(UTC) - timedelta(hours=2)
        async with AsyncSessionLocal() as db:
            db.add_all(
                [
                    AttendanceEntry(
                        workspace_id=seed.workspace_id,
                        user_id=seed.member_id,
                        started_at=started,
                        ended_at=started + timedelta(hours=1),
                        status=ATTENDANCE_STATUS_COMPLETE,
                        source=ATTENDANCE_SOURCE_CLOCK,
                    ),
                    AttendanceEntry(
                        workspace_id=seed.workspace_id,
                        user_id=seed.second_member_id,
                        started_at=started,
                        ended_at=started + timedelta(hours=1),
                        status=ATTENDANCE_STATUS_COMPLETE,
                        source=ATTENDANCE_SOURCE_CLOCK,
                    ),
                ]
            )
            await db.commit()

        principal: dict[str, Any] = {"user_id": seed.member_id, "role": "technician"}
        app = _api_app(seed, principal)
        transport = ASGITransport(app=app)
        today = date.today()
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            own = await client.get(
                f"/api/v1/workspaces/{seed.workspace_id}/attendance/me",
                params={
                    "date_from": (today - timedelta(days=1)).isoformat(),
                    "date_to": today.isoformat(),
                },
            )
            assert own.status_code == 200, own.text
            assert set(own.json()) == {"timezone", "entries", "total_seconds", "open_entry"}
            assert {entry["user_id"] for entry in own.json()["entries"]} == {seed.member_id}

            forbidden = await client.get(
                f"/api/v1/workspaces/{seed.workspace_id}/attendance/entries",
                params={
                    "date_from": (today - timedelta(days=1)).isoformat(),
                    "date_to": today.isoformat(),
                },
            )
            assert forbidden.status_code == 403

            principal.update(user_id=seed.admin_id, role="owner")
            cross_workspace = await client.post(
                f"/api/v1/workspaces/{seed.workspace_id}/attendance/entries",
                json={
                    "request_id": str(uuid.uuid4()),
                    "reason": "Paper correction",
                    "user_id": seed.outsider_id,
                    "started_at": started.isoformat(),
                    "ended_at": (started + timedelta(hours=1)).isoformat(),
                },
            )
            assert cross_workspace.status_code == 404
