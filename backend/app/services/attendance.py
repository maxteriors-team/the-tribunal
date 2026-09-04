"""Workspace-scoped time and attendance operations."""

from __future__ import annotations

import csv
import hashlib
import io
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Capability, role_can
from app.models.attendance import (
    ATTENDANCE_PAUSE_END_CLOCK_OUT,
    ATTENDANCE_PAUSE_END_RESUME,
    ATTENDANCE_PAUSE_END_VOID,
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
    AttendanceAdminReportResponse,
    AttendanceClockInRequest,
    AttendanceClockOutRequest,
    AttendanceDateRange,
    AttendanceEntryResponse,
    AttendanceEntryUpdateRequest,
    AttendanceExportRequest,
    AttendanceManualEntryRequest,
    AttendancePauseRequest,
    AttendanceReportResponse,
    AttendanceVoidRequest,
)
from app.services.exceptions import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.services.technician_scoreboard import TechnicianScoreboardService

MAX_ATTENDANCE_ROWS = 5000


@dataclass(frozen=True)
class AttendanceExportResult:
    content: bytes
    filename: str
    sha256: str
    row_count: int


@dataclass(frozen=True)
class _Authorization:
    membership: WorkspaceMembership
    user: User
    workspace: Workspace


class AttendanceService:
    """Attendance data access with authorization enforced on every operation."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _authorize(
        self,
        workspace_id: uuid.UUID,
        membership: WorkspaceMembership,
        capability: Capability,
    ) -> _Authorization:
        row = (
            await self.db.execute(
                select(WorkspaceMembership, User, Workspace)
                .join(User, User.id == WorkspaceMembership.user_id)
                .join(Workspace, Workspace.id == WorkspaceMembership.workspace_id)
                .where(
                    WorkspaceMembership.workspace_id == workspace_id,
                    WorkspaceMembership.user_id == membership.user_id,
                    User.is_active.is_(True),
                    Workspace.is_active.is_(True),
                )
            )
        ).first()
        if row is None:
            raise NotFoundError("Active workspace membership not found")
        current_membership, user, workspace = row
        if not role_can(current_membership.role, capability):
            raise PermissionDeniedError("You do not have permission to access attendance data")
        return _Authorization(current_membership, user, workspace)

    async def _active_user(self, workspace_id: uuid.UUID, user_id: int) -> User:
        user = (
            await self.db.execute(
                select(User)
                .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
                .where(
                    WorkspaceMembership.workspace_id == workspace_id,
                    User.id == user_id,
                    User.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if user is None:
            raise NotFoundError("Active workspace member not found")
        return user

    @staticmethod
    def _validate_range(date_range: AttendanceDateRange) -> None:
        if date_range.date_to < date_range.date_from:
            raise ValidationError("date_to must be on or after date_from")
        if (date_range.date_to - date_range.date_from).days > 61:
            raise ValidationError("Attendance date ranges cannot exceed 62 days")

    @staticmethod
    def _workspace_zone(workspace: Workspace) -> tuple[str, ZoneInfo]:
        settings = workspace.settings if isinstance(workspace.settings, dict) else {}
        name = str(settings.get("timezone") or "UTC")
        try:
            return name, ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            return "UTC", ZoneInfo("UTC")

    async def _reconcile_scoreboard_days(
        self,
        workspace_id: uuid.UUID,
        user_id: int,
        workspace: Workspace,
        *starts_at: datetime,
    ) -> None:
        _name, zone = self._workspace_zone(workspace)
        await TechnicianScoreboardService(self.db).reconcile_attendance_days(
            workspace_id,
            user_id,
            {started.astimezone(zone).date() for started in starts_at},
        )

    @classmethod
    def _utc_bounds(
        cls, workspace: Workspace, date_range: AttendanceDateRange
    ) -> tuple[str, ZoneInfo, datetime, datetime]:
        cls._validate_range(date_range)
        timezone_name, zone = cls._workspace_zone(workspace)
        start = datetime.combine(date_range.date_from, time.min, tzinfo=zone).astimezone(UTC)
        end = datetime.combine(
            date_range.date_to + timedelta(days=1), time.min, tzinfo=zone
        ).astimezone(UTC)
        return timezone_name, zone, start, end

    @staticmethod
    def _pauses(entry: AttendanceEntry) -> list[AttendancePause]:
        if "pauses" in sa_inspect(entry).unloaded:
            return []
        return entry.pauses

    @classmethod
    def _active_pause(cls, entry: AttendanceEntry) -> AttendancePause | None:
        return next((pause for pause in cls._pauses(entry) if pause.ended_at is None), None)

    @classmethod
    def _duration_parts(
        cls, entry: AttendanceEntry, *, now: datetime | None = None
    ) -> tuple[int, int, int]:
        calculated_at = now or datetime.now(UTC)
        endpoint = entry.ended_at or calculated_at
        gross_seconds = max(0, int((endpoint - entry.started_at).total_seconds()))
        paused_seconds = sum(
            max(
                0,
                int((min(pause.ended_at or endpoint, endpoint) - pause.started_at).total_seconds()),
            )
            for pause in cls._pauses(entry)
        )
        paused_seconds = min(gross_seconds, paused_seconds)
        return gross_seconds, paused_seconds, gross_seconds - paused_seconds

    @classmethod
    def _duration_seconds(cls, entry: AttendanceEntry, *, now: datetime | None = None) -> int:
        return cls._duration_parts(entry, now=now)[2]

    @classmethod
    def _response(
        cls,
        entry: AttendanceEntry,
        user: User,
        *,
        now: datetime | None = None,
    ) -> AttendanceEntryResponse:
        calculated_at = now or datetime.now(UTC)
        gross_seconds, paused_seconds, seconds = cls._duration_parts(entry, now=calculated_at)
        active_pause = cls._active_pause(entry) if entry.status == ATTENDANCE_STATUS_OPEN else None
        return AttendanceEntryResponse(
            id=entry.id,
            user_id=entry.user_id,
            employee_name=user.full_name or user.email,
            employee_email=user.email,
            started_at=entry.started_at,
            ended_at=entry.ended_at,
            status=entry.status,  # type: ignore[arg-type]
            source=entry.source,  # type: ignore[arg-type]
            note=entry.note,
            duration_seconds=seconds,
            duration_hours=round(seconds / 3600, 4),
            gross_duration_seconds=gross_seconds,
            paused_seconds=paused_seconds,
            is_paused=active_pause is not None,
            pause_started_at=active_pause.started_at if active_pause else None,
            calculated_at=calculated_at,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
        )

    @staticmethod
    def _total_seconds(entries: list[AttendanceEntry]) -> int:
        return sum(
            AttendanceService._duration_seconds(entry)
            for entry in entries
            if entry.status == ATTENDANCE_STATUS_COMPLETE
        )

    async def _range_rows(
        self,
        workspace_id: uuid.UUID,
        start: datetime,
        end: datetime,
        *,
        user_id: int | None = None,
        complete_only: bool = False,
    ) -> list[tuple[AttendanceEntry, User]]:
        statement = (
            select(AttendanceEntry, User)
            .join(User, User.id == AttendanceEntry.user_id)
            .where(
                AttendanceEntry.workspace_id == workspace_id,
                AttendanceEntry.started_at >= start,
                AttendanceEntry.started_at < end,
            )
            .order_by(AttendanceEntry.started_at.asc(), AttendanceEntry.id.asc())
            .limit(MAX_ATTENDANCE_ROWS + 1)
        )
        if user_id is not None:
            statement = statement.where(AttendanceEntry.user_id == user_id)
        if complete_only:
            statement = statement.where(AttendanceEntry.status == ATTENDANCE_STATUS_COMPLETE)
        rows = list((await self.db.execute(statement)).tuples().all())
        if len(rows) > MAX_ATTENDANCE_ROWS:
            raise ValidationError(f"Attendance result exceeds {MAX_ATTENDANCE_ROWS} rows")
        return rows

    async def get_my_report(
        self,
        workspace_id: uuid.UUID,
        membership: WorkspaceMembership,
        date_range: AttendanceDateRange,
    ) -> AttendanceReportResponse:
        auth = await self._authorize(workspace_id, membership, Capability.ATTENDANCE_USE)
        timezone_name, _zone, start, end = self._utc_bounds(auth.workspace, date_range)
        rows = await self._range_rows(workspace_id, start, end, user_id=auth.membership.user_id)
        open_entry = (
            await self.db.execute(
                select(AttendanceEntry).where(
                    AttendanceEntry.workspace_id == workspace_id,
                    AttendanceEntry.user_id == auth.membership.user_id,
                    AttendanceEntry.status == ATTENDANCE_STATUS_OPEN,
                )
            )
        ).scalar_one_or_none()
        now = datetime.now(UTC)
        responses = [self._response(entry, user, now=now) for entry, user in rows]
        return AttendanceReportResponse(
            timezone=timezone_name,
            entries=responses,
            total_seconds=self._total_seconds([entry for entry, _user in rows]),
            open_entry=self._response(open_entry, auth.user, now=now) if open_entry else None,
        )

    async def list_entries(
        self,
        workspace_id: uuid.UUID,
        membership: WorkspaceMembership,
        date_range: AttendanceDateRange,
        *,
        user_id: int | None = None,
    ) -> AttendanceAdminReportResponse:
        auth = await self._authorize(workspace_id, membership, Capability.ATTENDANCE_MANAGE)
        if user_id is not None:
            await self._active_user(workspace_id, user_id)
        timezone_name, _zone, start, end = self._utc_bounds(auth.workspace, date_range)
        rows = await self._range_rows(workspace_id, start, end, user_id=user_id)
        entries = [entry for entry, _user in rows]
        return AttendanceAdminReportResponse(
            timezone=timezone_name,
            entries=[self._response(entry, user) for entry, user in rows],
            total_seconds=self._total_seconds(entries),
            open_count=sum(entry.status == ATTENDANCE_STATUS_OPEN for entry in entries),
            employee_count=len({entry.user_id for entry in entries}),
        )

    async def _entry_for_request(
        self,
        workspace_id: uuid.UUID,
        request_id: uuid.UUID,
        *,
        clock_out: bool = False,
    ) -> AttendanceEntry | None:
        request_column = (
            AttendanceEntry.clock_out_request_id
            if clock_out
            else AttendanceEntry.clock_in_request_id
        )
        return (
            await self.db.execute(
                select(AttendanceEntry).where(
                    AttendanceEntry.workspace_id == workspace_id,
                    request_column == request_id,
                )
            )
        ).scalar_one_or_none()

    async def _admin_retry(
        self,
        workspace_id: uuid.UUID,
        request_id: uuid.UUID,
        entry_id: uuid.UUID,
        action: str,
    ) -> AttendanceEntryResponse | None:
        event = (
            await self.db.execute(
                select(AttendanceEvent).where(
                    AttendanceEvent.workspace_id == workspace_id,
                    AttendanceEvent.request_id == request_id,
                )
            )
        ).scalar_one_or_none()
        if event is None:
            return None
        if event.action != action or event.entry_id != entry_id:
            raise ConflictError("request_id has already been used")
        entry, user = await self._entry_and_user(workspace_id, entry_id)
        return self._response(entry, user)

    @staticmethod
    def _assert_request_owner(
        entry: AttendanceEntry, user_id: int, *, expected_source: str
    ) -> None:
        if entry.user_id != user_id or entry.source != expected_source:
            raise ConflictError("request_id has already been used")

    async def _employee_retry(
        self,
        workspace_id: uuid.UUID,
        request_id: uuid.UUID,
        user_id: int,
        action: str,
    ) -> AttendanceEntryResponse | None:
        event = (
            await self.db.execute(
                select(AttendanceEvent).where(
                    AttendanceEvent.workspace_id == workspace_id,
                    AttendanceEvent.request_id == request_id,
                )
            )
        ).scalar_one_or_none()
        if event is None:
            return None
        if event.action != action:
            raise ConflictError("request_id has already been used")
        entry, user = await self._entry_and_user(workspace_id, event.entry_id)
        self._assert_request_owner(entry, user_id, expected_source=ATTENDANCE_SOURCE_CLOCK)
        return self._response(entry, user)

    @classmethod
    def _close_active_pause(
        cls,
        entry: AttendanceEntry,
        *,
        ended_at: datetime,
        request_id: uuid.UUID,
        action: str,
    ) -> AttendancePause | None:
        pause = cls._active_pause(entry)
        if pause is None:
            return None
        if ended_at <= pause.started_at:
            raise ConflictError("The active pause starts in the future")
        pause.ended_at = ended_at
        pause.end_request_id = request_id
        pause.end_action = action
        return pause

    async def clock_in(
        self,
        workspace_id: uuid.UUID,
        membership: WorkspaceMembership,
        payload: AttendanceClockInRequest,
    ) -> AttendanceEntryResponse:
        auth = await self._authorize(workspace_id, membership, Capability.ATTENDANCE_USE)
        existing = await self._entry_for_request(workspace_id, payload.request_id)
        if existing is not None:
            self._assert_request_owner(
                existing, auth.membership.user_id, expected_source=ATTENDANCE_SOURCE_CLOCK
            )
            return self._response(existing, auth.user)

        open_entry = (
            await self.db.execute(
                select(AttendanceEntry)
                .where(
                    AttendanceEntry.workspace_id == workspace_id,
                    AttendanceEntry.user_id == auth.membership.user_id,
                    AttendanceEntry.status == ATTENDANCE_STATUS_OPEN,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if open_entry is not None:
            raise ConflictError("You already have an open attendance entry")

        now = datetime.now(UTC)
        entry = AttendanceEntry(
            workspace_id=workspace_id,
            user_id=auth.membership.user_id,
            started_at=now,
            status=ATTENDANCE_STATUS_OPEN,
            source=ATTENDANCE_SOURCE_CLOCK,
            note=payload.note,
            created_by_id=auth.membership.user_id,
            updated_by_id=auth.membership.user_id,
            clock_in_request_id=payload.request_id,
        )
        try:
            async with self.db.begin_nested():
                self.db.add(entry)
                await self.db.flush()
                self.db.add(
                    AttendanceEvent(
                        workspace_id=workspace_id,
                        entry_id=entry.id,
                        actor_id=auth.membership.user_id,
                        action="clock_in",
                        request_id=payload.request_id,
                        changes={
                            "request_id": str(payload.request_id),
                            "started_at": now.isoformat(),
                            "status": ATTENDANCE_STATUS_OPEN,
                            "source": ATTENDANCE_SOURCE_CLOCK,
                            "note_present": payload.note is not None,
                        },
                    )
                )
                await self.db.flush()
        except IntegrityError as exc:
            retry = await self._entry_for_request(workspace_id, payload.request_id)
            if retry is not None:
                self._assert_request_owner(
                    retry, auth.membership.user_id, expected_source=ATTENDANCE_SOURCE_CLOCK
                )
                return self._response(retry, auth.user)
            raise ConflictError("Attendance entry overlaps an existing interval") from exc
        return self._response(entry, auth.user, now=now)

    async def clock_out(
        self,
        workspace_id: uuid.UUID,
        membership: WorkspaceMembership,
        payload: AttendanceClockOutRequest,
    ) -> AttendanceEntryResponse:
        auth = await self._authorize(workspace_id, membership, Capability.ATTENDANCE_USE)
        existing = await self._entry_for_request(workspace_id, payload.request_id, clock_out=True)
        if existing is not None:
            self._assert_request_owner(
                existing, auth.membership.user_id, expected_source=ATTENDANCE_SOURCE_CLOCK
            )
            return self._response(existing, auth.user)

        entry = (
            await self.db.execute(
                select(AttendanceEntry)
                .where(
                    AttendanceEntry.workspace_id == workspace_id,
                    AttendanceEntry.user_id == auth.membership.user_id,
                    AttendanceEntry.status == ATTENDANCE_STATUS_OPEN,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if entry is None:
            retry = await self._entry_for_request(workspace_id, payload.request_id, clock_out=True)
            if retry is not None:
                self._assert_request_owner(
                    retry, auth.membership.user_id, expected_source=ATTENDANCE_SOURCE_CLOCK
                )
                return self._response(retry, auth.user)
            raise ConflictError("You do not have an open attendance entry")

        now = datetime.now(UTC)
        if now <= entry.started_at:
            raise ConflictError("The open entry starts in the future")
        was_paused = self._active_pause(entry) is not None
        try:
            async with self.db.begin_nested():
                self._close_active_pause(
                    entry,
                    ended_at=now,
                    request_id=payload.request_id,
                    action=ATTENDANCE_PAUSE_END_CLOCK_OUT,
                )
                entry.ended_at = now
                entry.status = ATTENDANCE_STATUS_COMPLETE
                entry.updated_by_id = auth.membership.user_id
                entry.clock_out_request_id = payload.request_id
                self.db.add(
                    AttendanceEvent(
                        workspace_id=workspace_id,
                        entry_id=entry.id,
                        actor_id=auth.membership.user_id,
                        action="clock_out",
                        request_id=payload.request_id,
                        changes={
                            "request_id": str(payload.request_id),
                            "ended_at": now.isoformat(),
                            "status": ATTENDANCE_STATUS_COMPLETE,
                            "closed_active_pause": was_paused,
                        },
                    )
                )
                await self.db.flush()
        except IntegrityError as exc:
            retry = await self._entry_for_request(workspace_id, payload.request_id, clock_out=True)
            if retry is not None:
                self._assert_request_owner(
                    retry, auth.membership.user_id, expected_source=ATTENDANCE_SOURCE_CLOCK
                )
                return self._response(retry, auth.user)
            raise ConflictError("Unable to close attendance entry") from exc
        await self._reconcile_scoreboard_days(
            workspace_id, entry.user_id, auth.workspace, entry.started_at
        )
        return self._response(entry, auth.user)

    async def pause_shift(
        self,
        workspace_id: uuid.UUID,
        membership: WorkspaceMembership,
        payload: AttendancePauseRequest,
    ) -> AttendanceEntryResponse:
        auth = await self._authorize(workspace_id, membership, Capability.ATTENDANCE_USE)
        retry = await self._employee_retry(
            workspace_id, payload.request_id, auth.membership.user_id, "pause"
        )
        if retry is not None:
            return retry

        entry = (
            await self.db.execute(
                select(AttendanceEntry)
                .where(
                    AttendanceEntry.workspace_id == workspace_id,
                    AttendanceEntry.user_id == auth.membership.user_id,
                    AttendanceEntry.status == ATTENDANCE_STATUS_OPEN,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if entry is None:
            raise ConflictError("You do not have an open attendance entry")
        self._assert_request_owner(
            entry, auth.membership.user_id, expected_source=ATTENDANCE_SOURCE_CLOCK
        )
        if self._active_pause(entry) is not None:
            raise ConflictError("Your attendance clock is already paused")

        now = datetime.now(UTC)
        if now <= entry.started_at:
            raise ConflictError("The open entry starts in the future")
        try:
            async with self.db.begin_nested():
                pause = AttendancePause(
                    entry=entry,
                    started_at=now,
                    start_request_id=payload.request_id,
                )
                entry.updated_by_id = auth.membership.user_id
                self.db.add(pause)
                self.db.add(
                    AttendanceEvent(
                        workspace_id=workspace_id,
                        entry_id=entry.id,
                        actor_id=auth.membership.user_id,
                        action="pause",
                        request_id=payload.request_id,
                        changes={
                            "request_id": str(payload.request_id),
                            "paused_at": now.isoformat(),
                        },
                    )
                )
                await self.db.flush()
        except IntegrityError as exc:
            retry = await self._employee_retry(
                workspace_id, payload.request_id, auth.membership.user_id, "pause"
            )
            if retry is not None:
                return retry
            raise ConflictError("Unable to pause attendance clock") from exc
        return self._response(entry, auth.user, now=now)

    async def resume_shift(
        self,
        workspace_id: uuid.UUID,
        membership: WorkspaceMembership,
        payload: AttendancePauseRequest,
    ) -> AttendanceEntryResponse:
        auth = await self._authorize(workspace_id, membership, Capability.ATTENDANCE_USE)
        retry = await self._employee_retry(
            workspace_id, payload.request_id, auth.membership.user_id, "resume"
        )
        if retry is not None:
            return retry

        entry = (
            await self.db.execute(
                select(AttendanceEntry)
                .where(
                    AttendanceEntry.workspace_id == workspace_id,
                    AttendanceEntry.user_id == auth.membership.user_id,
                    AttendanceEntry.status == ATTENDANCE_STATUS_OPEN,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if entry is None:
            raise ConflictError("You do not have an open attendance entry")
        self._assert_request_owner(
            entry, auth.membership.user_id, expected_source=ATTENDANCE_SOURCE_CLOCK
        )
        active_pause = self._active_pause(entry)
        if active_pause is None:
            raise ConflictError("Your attendance clock is not paused")

        now = datetime.now(UTC)
        try:
            async with self.db.begin_nested():
                self._close_active_pause(
                    entry,
                    ended_at=now,
                    request_id=payload.request_id,
                    action=ATTENDANCE_PAUSE_END_RESUME,
                )
                entry.updated_by_id = auth.membership.user_id
                self.db.add(
                    AttendanceEvent(
                        workspace_id=workspace_id,
                        entry_id=entry.id,
                        actor_id=auth.membership.user_id,
                        action="resume",
                        request_id=payload.request_id,
                        changes={
                            "request_id": str(payload.request_id),
                            "paused_at": active_pause.started_at.isoformat(),
                            "resumed_at": now.isoformat(),
                        },
                    )
                )
                await self.db.flush()
        except IntegrityError as exc:
            retry = await self._employee_retry(
                workspace_id, payload.request_id, auth.membership.user_id, "resume"
            )
            if retry is not None:
                return retry
            raise ConflictError("Unable to resume attendance clock") from exc
        return self._response(entry, auth.user, now=now)

    async def create_manual_entry(
        self,
        workspace_id: uuid.UUID,
        membership: WorkspaceMembership,
        payload: AttendanceManualEntryRequest,
    ) -> AttendanceEntryResponse:
        auth = await self._authorize(workspace_id, membership, Capability.ATTENDANCE_MANAGE)
        target = await self._active_user(workspace_id, payload.user_id)
        existing = await self._entry_for_request(workspace_id, payload.request_id)
        if existing is not None:
            self._assert_request_owner(
                existing, payload.user_id, expected_source=ATTENDANCE_SOURCE_MANUAL
            )
            return self._response(existing, target)

        started_at = payload.started_at.astimezone(UTC)
        ended_at = payload.ended_at.astimezone(UTC)
        if ended_at <= started_at:
            raise ValidationError("ended_at must be after started_at")
        entry = AttendanceEntry(
            workspace_id=workspace_id,
            user_id=payload.user_id,
            started_at=started_at,
            ended_at=ended_at,
            status=ATTENDANCE_STATUS_COMPLETE,
            source=ATTENDANCE_SOURCE_MANUAL,
            note=payload.note,
            created_by_id=auth.membership.user_id,
            updated_by_id=auth.membership.user_id,
            clock_in_request_id=payload.request_id,
        )
        try:
            async with self.db.begin_nested():
                self.db.add(entry)
                await self.db.flush()
                self.db.add(
                    AttendanceEvent(
                        workspace_id=workspace_id,
                        entry_id=entry.id,
                        actor_id=auth.membership.user_id,
                        action="manual_create",
                        request_id=payload.request_id,
                        reason=payload.reason,
                        changes={
                            "request_id": str(payload.request_id),
                            "started_at": started_at.isoformat(),
                            "ended_at": ended_at.isoformat(),
                            "status": ATTENDANCE_STATUS_COMPLETE,
                            "source": ATTENDANCE_SOURCE_MANUAL,
                            "note_present": payload.note is not None,
                        },
                    )
                )
                await self.db.flush()
        except IntegrityError as exc:
            retry = await self._entry_for_request(workspace_id, payload.request_id)
            if retry is not None:
                self._assert_request_owner(
                    retry, payload.user_id, expected_source=ATTENDANCE_SOURCE_MANUAL
                )
                return self._response(retry, target)
            raise ConflictError("Attendance entry overlaps an existing interval") from exc
        await self._reconcile_scoreboard_days(
            workspace_id, entry.user_id, auth.workspace, entry.started_at
        )
        return self._response(entry, target)

    async def _entry_and_user(
        self, workspace_id: uuid.UUID, entry_id: uuid.UUID, *, lock: bool = False
    ) -> tuple[AttendanceEntry, User]:
        statement = (
            select(AttendanceEntry, User)
            .join(User, User.id == AttendanceEntry.user_id)
            .where(
                AttendanceEntry.workspace_id == workspace_id,
                AttendanceEntry.id == entry_id,
            )
        )
        if lock:
            statement = statement.with_for_update(of=AttendanceEntry)
        row = (await self.db.execute(statement)).first()
        if row is None:
            raise NotFoundError("Attendance entry not found")
        entry, user = row
        await self._active_user(workspace_id, entry.user_id)
        return entry, user

    async def update_entry(
        self,
        workspace_id: uuid.UUID,
        membership: WorkspaceMembership,
        entry_id: uuid.UUID,
        payload: AttendanceEntryUpdateRequest,
    ) -> AttendanceEntryResponse:
        auth = await self._authorize(workspace_id, membership, Capability.ATTENDANCE_MANAGE)
        retry = await self._admin_retry(workspace_id, payload.request_id, entry_id, "edit")
        if retry is not None:
            return retry
        entry, target = await self._entry_and_user(workspace_id, entry_id, lock=True)
        if entry.status == ATTENDANCE_STATUS_VOID:
            raise ConflictError("Voided attendance entries cannot be edited")

        old_start = entry.started_at
        new_start = (
            payload.started_at.astimezone(UTC)
            if payload.started_at is not None
            else entry.started_at
        )
        new_end = (
            payload.ended_at.astimezone(UTC) if payload.ended_at is not None else entry.ended_at
        )
        if new_end is None:
            raise ValidationError("Clock out before correcting an attendance entry")
        if new_end <= new_start:
            raise ValidationError("ended_at must be after started_at")
        if any(
            pause.started_at < new_start or pause.ended_at is None or pause.ended_at > new_end
            for pause in self._pauses(entry)
        ):
            # simplification: pause intervals are immutable; void and re-enter until audited pause
            # corrections have their own UI and endpoint.
            raise ValidationError("Corrected shift times must contain every recorded pause")

        changes: dict[str, object] = {"request_id": str(payload.request_id)}
        if "started_at" in payload.model_fields_set:
            changes["started_at"] = {
                "from": entry.started_at.isoformat(),
                "to": new_start.isoformat(),
            }
        if "ended_at" in payload.model_fields_set:
            changes["ended_at"] = {
                "from": entry.ended_at.isoformat() if entry.ended_at else None,
                "to": new_end.isoformat() if new_end else None,
            }
        if "note" in payload.model_fields_set:
            changes["note_changed"] = True
        old_status = entry.status
        new_status = ATTENDANCE_STATUS_COMPLETE
        if new_status != old_status:
            changes["status"] = {"from": old_status, "to": new_status}

        try:
            async with self.db.begin_nested():
                entry.started_at = new_start
                entry.ended_at = new_end
                entry.status = new_status
                if "note" in payload.model_fields_set:
                    entry.note = payload.note
                entry.updated_by_id = auth.membership.user_id
                self.db.add(
                    AttendanceEvent(
                        workspace_id=workspace_id,
                        entry_id=entry.id,
                        actor_id=auth.membership.user_id,
                        action="edit",
                        request_id=payload.request_id,
                        reason=payload.reason,
                        changes=changes,
                    )
                )
                await self.db.flush()
        except IntegrityError as exc:
            retry = await self._admin_retry(workspace_id, payload.request_id, entry_id, "edit")
            if retry is not None:
                return retry
            raise ConflictError("Attendance entry overlaps an existing interval") from exc
        await self._reconcile_scoreboard_days(
            workspace_id, entry.user_id, auth.workspace, old_start, entry.started_at
        )
        return self._response(entry, target)

    async def void_entry(
        self,
        workspace_id: uuid.UUID,
        membership: WorkspaceMembership,
        entry_id: uuid.UUID,
        payload: AttendanceVoidRequest,
    ) -> AttendanceEntryResponse:
        auth = await self._authorize(workspace_id, membership, Capability.ATTENDANCE_MANAGE)
        retry = await self._admin_retry(workspace_id, payload.request_id, entry_id, "void")
        if retry is not None:
            return retry
        entry, target = await self._entry_and_user(workspace_id, entry_id, lock=True)
        if entry.status == ATTENDANCE_STATUS_VOID:
            raise ConflictError("Attendance entry is already void")
        previous_status = entry.status
        ended_at = entry.ended_at or datetime.now(UTC)
        if ended_at <= entry.started_at:
            raise ConflictError("Correct the future start time before voiding this entry")
        was_paused = self._active_pause(entry) is not None
        try:
            async with self.db.begin_nested():
                self._close_active_pause(
                    entry,
                    ended_at=ended_at,
                    request_id=payload.request_id,
                    action=ATTENDANCE_PAUSE_END_VOID,
                )
                entry.ended_at = ended_at
                entry.status = ATTENDANCE_STATUS_VOID
                entry.updated_by_id = auth.membership.user_id
                self.db.add(
                    AttendanceEvent(
                        workspace_id=workspace_id,
                        entry_id=entry.id,
                        actor_id=auth.membership.user_id,
                        action="void",
                        request_id=payload.request_id,
                        reason=payload.reason,
                        changes={
                            "request_id": str(payload.request_id),
                            "status": {
                                "from": previous_status,
                                "to": ATTENDANCE_STATUS_VOID,
                            },
                            "closed_active_pause": was_paused,
                        },
                    )
                )
                await self.db.flush()
        except IntegrityError as exc:
            retry = await self._admin_retry(workspace_id, payload.request_id, entry_id, "void")
            if retry is not None:
                return retry
            raise ConflictError("request_id has already been used") from exc
        await self._reconcile_scoreboard_days(
            workspace_id, entry.user_id, auth.workspace, entry.started_at
        )
        return self._response(entry, target)

    @staticmethod
    def _safe_csv_text(value: object | None) -> str:
        text_value = "" if value is None else str(value)
        stripped = text_value.lstrip(" \t\r\n")
        if stripped.startswith(("=", "+", "-", "@")):
            return "'" + text_value
        return text_value

    async def export_csv(
        self,
        workspace_id: uuid.UUID,
        membership: WorkspaceMembership,
        payload: AttendanceExportRequest,
    ) -> AttendanceExportResult:
        auth = await self._authorize(workspace_id, membership, Capability.ATTENDANCE_MANAGE)
        if payload.user_id is not None:
            await self._active_user(workspace_id, payload.user_id)
        duplicate = (
            await self.db.execute(
                select(AttendanceExport.id).where(
                    AttendanceExport.workspace_id == workspace_id,
                    AttendanceExport.request_id == payload.request_id,
                )
            )
        ).scalar_one_or_none()
        if duplicate is not None:
            raise ConflictError("request_id has already been used for an export")

        timezone_name, zone, start, end = self._utc_bounds(auth.workspace, payload)
        rows = await self._range_rows(
            workspace_id,
            start,
            end,
            user_id=payload.user_id,
            complete_only=True,
        )
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\r\n")
        writer.writerow(
            [
                "employee_id",
                "employee_name",
                "employee_email",
                "work_date",
                "clock_in",
                "clock_out",
                "gross_hours",
                "paused_hours",
                "total_hours",
                "source",
                "note",
                "entry_id",
            ]
        )
        total_seconds = 0
        entry_ids: list[str] = []
        for entry, user in rows:
            if entry.ended_at is None:
                continue
            gross_seconds, paused_seconds, seconds = self._duration_parts(entry)
            total_seconds += seconds
            entry_ids.append(str(entry.id))
            local_start = entry.started_at.astimezone(zone)
            local_end = entry.ended_at.astimezone(zone)
            cells = [
                entry.user_id,
                user.full_name or user.email,
                user.email,
                local_start.date().isoformat(),
                local_start.isoformat(),
                local_end.isoformat(),
                f"{gross_seconds / 3600:.4f}",
                f"{paused_seconds / 3600:.4f}",
                f"{seconds / 3600:.4f}",
                entry.source,
                entry.note,
                entry.id,
            ]
            writer.writerow([self._safe_csv_text(cell) for cell in cells])
        content = output.getvalue().encode("utf-8")
        digest = hashlib.sha256(content).hexdigest()
        audit = AttendanceExport(
            workspace_id=workspace_id,
            created_by_id=auth.membership.user_id,
            request_id=payload.request_id,
            start_date=payload.date_from,
            end_date=payload.date_to,
            user_id=payload.user_id,
            row_count=len(entry_ids),
            total_seconds=total_seconds,
            entry_ids=entry_ids,
            sha256=digest,
        )
        try:
            async with self.db.begin_nested():
                self.db.add(audit)
                await self.db.flush()
        except IntegrityError as exc:
            raise ConflictError("request_id has already been used for an export") from exc
        filename = (
            f"attendance_raw_hours_{payload.date_from.isoformat()}_"
            f"{payload.date_to.isoformat()}.csv"
        )
        return AttendanceExportResult(
            content=content,
            filename=filename,
            sha256=digest,
            row_count=len(entry_ids),
        )
