"""Lighting League rules, durable award lifecycle, and private aggregation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attendance import ATTENDANCE_STATUS_COMPLETE, AttendanceEntry
from app.models.field_service import Job, JobAssignment, JobStatus, Technician
from app.models.quote import Quote
from app.models.technician_xp_award import TechnicianXpAward
from app.services.exceptions import NotFoundError, ValidationError

ATTENDANCE_XP = 25
COMPLETED_JOB_XP = 100
UPSELL_BASE_XP = 100
UPSELL_VALUE_DIVISOR = Decimal("20")
UPSELL_VALUE_BONUS_CAP = 100
MAX_LEVEL = 10


@dataclass(frozen=True, slots=True)
class LevelDefinition:
    number: int
    title: str
    lifetime_xp: int


LEVELS = (
    LevelDefinition(1, "Spark Starter", 0),
    LevelDefinition(2, "Glow Getter", 500),
    LevelDefinition(3, "Beam Builder", 1_250),
    LevelDefinition(4, "Lumen Leader", 2_250),
    LevelDefinition(5, "Circuit Champion", 3_500),
    LevelDefinition(6, "Radiance Ranger", 5_000),
    LevelDefinition(7, "Illumination Ace", 7_000),
    LevelDefinition(8, "Master of Lumens", 9_500),
    LevelDefinition(9, "Light Commander", 12_500),
    LevelDefinition(10, "Lighting Lord", 16_000),
)


@dataclass(frozen=True, slots=True)
class ScoreboardPeriod:
    start_date: date
    end_date: date
    starts_at: datetime
    ends_at: datetime
    timezone: str


@dataclass(frozen=True, slots=True)
class LevelProgress:
    level: LevelDefinition
    next_level: LevelDefinition | None
    xp_into_level: int
    xp_to_next_level: int | None
    progress: float


@dataclass(frozen=True, slots=True)
class TechnicianStanding:
    technician_id: uuid.UUID
    name: str
    rank: int | None
    monthly_xp: int
    level: LevelDefinition
    is_viewer: bool


@dataclass(frozen=True, slots=True)
class TechnicianScoreDetail:
    technician_id: uuid.UUID
    name: str
    lifetime_xp: int
    level_progress: LevelProgress
    attendance_days: int
    completed_jobs: int
    approved_upsells: int
    attendance_xp: int
    job_xp: int
    upsell_xp: int


@dataclass(frozen=True, slots=True)
class TechnicianScoreboard:
    period: ScoreboardPeriod
    standings: tuple[TechnicianStanding, ...]
    viewer_detail: TechnicianScoreDetail | None
    viewer_level_seen: int | None


@dataclass(frozen=True, slots=True)
class _CategoryTotals:
    lifetime_xp: int = 0
    monthly_xp: int = 0
    monthly_count: int = 0


def upsell_xp(total: Decimal | float | int) -> int:
    """Return 100–200 XP from a quote-denominated total."""
    value = max(Decimal("0"), Decimal(str(total)))
    bonus = min(int(value // UPSELL_VALUE_DIVISOR), UPSELL_VALUE_BONUS_CAP)
    return UPSELL_BASE_XP + bonus


def level_for_xp(lifetime_xp: int) -> LevelDefinition:
    """Resolve an XP total against the backend-owned level ladder."""
    return next(level for level in reversed(LEVELS) if lifetime_xp >= level.lifetime_xp)


def level_progress(lifetime_xp: int) -> LevelProgress:
    """Describe exact progress within the current level interval."""
    current = level_for_xp(lifetime_xp)
    next_level = LEVELS[current.number] if current.number < MAX_LEVEL else None
    if next_level is None:
        return LevelProgress(current, None, lifetime_xp - current.lifetime_xp, None, 1.0)
    span = next_level.lifetime_xp - current.lifetime_xp
    into = lifetime_xp - current.lifetime_xp
    return LevelProgress(
        current,
        next_level,
        into,
        next_level.lifetime_xp - lifetime_xp,
        into / span,
    )


def _month_dates(moment: datetime, timezone_name: str) -> tuple[date, date]:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    local_day = moment.astimezone(ZoneInfo(timezone_name)).date()
    start = local_day.replace(day=1)
    next_month = (start + timedelta(days=32)).replace(day=1)
    return start, next_month - timedelta(days=1)


class TechnicianScoreboardService:
    """Own every XP write and workspace-scoped scoreboard read."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _upsert_award(
        self,
        *,
        workspace_id: uuid.UUID,
        technician_id: uuid.UUID,
        category: str,
        source_key: str,
        points: int,
        awarded_at: datetime | None = None,
    ) -> None:
        """Create or reactivate one source without moving its original award time."""
        statement = pg_insert(TechnicianXpAward).values(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            technician_id=technician_id,
            category=category,
            source_key=source_key,
            points=points,
            awarded_at=awarded_at or datetime.now(UTC),
            revoked_at=None,
        )
        await self.db.execute(
            statement.on_conflict_do_update(
                constraint="uq_technician_xp_awards_source",
                set_={"points": points, "revoked_at": None},
            )
        )

    async def _revoke(
        self,
        *,
        workspace_id: uuid.UUID,
        category: str,
        source_key: str,
        technician_ids: set[uuid.UUID] | None = None,
        revoked_at: datetime | None = None,
    ) -> None:
        criteria = [
            TechnicianXpAward.workspace_id == workspace_id,
            TechnicianXpAward.category == category,
            TechnicianXpAward.source_key == source_key,
            TechnicianXpAward.revoked_at.is_(None),
        ]
        if technician_ids is not None:
            if not technician_ids:
                return
            criteria.append(TechnicianXpAward.technician_id.in_(technician_ids))
        moment = revoked_at or datetime.now(UTC)
        await self.db.execute(
            update(TechnicianXpAward)
            .where(*criteria)
            .values(revoked_at=func.greatest(moment, TechnicianXpAward.awarded_at))
        )

    async def reconcile_attendance_days(
        self,
        workspace_id: uuid.UUID,
        user_id: int,
        local_days: set[date],
    ) -> None:
        """Keep one positive award active for each completed local workday."""
        if not local_days:
            return
        technician = await self.db.scalar(
            select(Technician).where(
                Technician.workspace_id == workspace_id,
                Technician.user_id == user_id,
                Technician.is_active.is_(True),
            )
        )
        if technician is None:
            return

        # Import lazily: reporting's package exports quote services during app startup.
        from app.services.reporting.time_windows import (
            get_workspace_reporting_timezone,
            local_date_bounds_utc,
        )

        # simplification: earned dates use today's workspace reporting timezone; persist
        # an immutable earned timezone/date if historical timezone changes are supported.
        timezone_name = await get_workspace_reporting_timezone(self.db, workspace_id)
        first_day = min(local_days)
        last_day = max(local_days)
        starts_at, ends_at = local_date_bounds_utc(first_day, last_day, timezone_name)
        completed_starts = (
            await self.db.scalars(
                select(AttendanceEntry.started_at).where(
                    AttendanceEntry.workspace_id == workspace_id,
                    AttendanceEntry.user_id == user_id,
                    AttendanceEntry.status == ATTENDANCE_STATUS_COMPLETE,
                    AttendanceEntry.started_at >= starts_at,
                    AttendanceEntry.started_at < ends_at,
                )
            )
        ).all()
        zone = ZoneInfo(timezone_name)
        completed_days = {
            started.replace(tzinfo=UTC).astimezone(zone).date()
            if started.tzinfo is None
            else started.astimezone(zone).date()
            for started in completed_starts
        }
        for local_day in local_days:
            source_key = f"attendance:{local_day.isoformat()}"
            if local_day in completed_days:
                await self._upsert_award(
                    workspace_id=workspace_id,
                    technician_id=technician.id,
                    category="attendance",
                    source_key=source_key,
                    points=ATTENDANCE_XP,
                )
            else:
                await self._revoke(
                    workspace_id=workspace_id,
                    category="attendance",
                    source_key=source_key,
                    technician_ids={technician.id},
                )

    async def sync_job_awards(self, job: Job) -> None:
        """Snapshot first-completion assignees, or toggle that snapshot off/on."""
        source_key = f"job:{job.id}"
        existing_ids = set(
            await self.db.scalars(
                select(TechnicianXpAward.technician_id).where(
                    TechnicianXpAward.workspace_id == job.workspace_id,
                    TechnicianXpAward.category == "job",
                    TechnicianXpAward.source_key == source_key,
                )
            )
        )
        if JobStatus(job.status) != JobStatus.COMPLETED:
            await self._revoke(
                workspace_id=job.workspace_id,
                category="job",
                source_key=source_key,
            )
            return

        technician_ids = existing_ids
        if not technician_ids:
            technician_ids = set(
                await self.db.scalars(
                    select(JobAssignment.technician_id)
                    .join(Technician, Technician.id == JobAssignment.technician_id)
                    .where(
                        JobAssignment.job_id == job.id,
                        Technician.workspace_id == job.workspace_id,
                        Technician.is_active.is_(True),
                    )
                )
            )
        for technician_id in technician_ids:
            await self._upsert_award(
                workspace_id=job.workspace_id,
                technician_id=technician_id,
                category="job",
                source_key=source_key,
                points=COMPLETED_JOB_XP,
            )

    async def revoke_job_awards(self, job: Job) -> None:
        """Revoke durable job credit before the source job is deleted."""
        await self._revoke(
            workspace_id=job.workspace_id,
            category="job",
            source_key=f"job:{job.id}",
        )

    async def award_approved_upsell(self, quote: Quote) -> None:
        """Award an approved marked quote to its workspace-linked creator."""
        if not quote.is_onsite_upsell or quote.status != "approved" or quote.created_by_id is None:
            return
        technician_id = await self.db.scalar(
            select(Technician.id).where(
                Technician.workspace_id == quote.workspace_id,
                Technician.user_id == quote.created_by_id,
                Technician.is_active.is_(True),
            )
        )
        if technician_id is None:
            return
        # simplification: quote totals use the workspace operating currency; normalize
        # currencies here if workspaces later support multi-currency quoting.
        await self._upsert_award(
            workspace_id=quote.workspace_id,
            technician_id=technician_id,
            category="upsell",
            source_key=f"upsell:{quote.id}",
            points=upsell_xp(quote.total),
        )

    async def _period(
        self, workspace_id: uuid.UUID, *, now: datetime | None = None
    ) -> ScoreboardPeriod:
        from app.services.reporting.time_windows import (
            get_workspace_reporting_timezone,
            local_date_bounds_utc,
        )

        timezone_name = await get_workspace_reporting_timezone(self.db, workspace_id)
        start_date, end_date = _month_dates(now or datetime.now(UTC), timezone_name)
        starts_at, ends_at = local_date_bounds_utc(start_date, end_date, timezone_name)
        return ScoreboardPeriod(start_date, end_date, starts_at, ends_at, timezone_name)

    async def _totals(
        self,
        workspace_id: uuid.UUID,
        technician_ids: list[uuid.UUID],
        period: ScoreboardPeriod,
    ) -> dict[uuid.UUID, dict[str, _CategoryTotals]]:
        if not technician_ids:
            return {}
        rows = (
            await self.db.execute(
                select(
                    TechnicianXpAward.technician_id,
                    TechnicianXpAward.category,
                    func.coalesce(func.sum(TechnicianXpAward.points), 0),
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    and_(
                                        TechnicianXpAward.awarded_at >= period.starts_at,
                                        TechnicianXpAward.awarded_at < period.ends_at,
                                    ),
                                    TechnicianXpAward.points,
                                ),
                                else_=0,
                            )
                        ),
                        0,
                    ),
                    func.count().filter(
                        TechnicianXpAward.awarded_at >= period.starts_at,
                        TechnicianXpAward.awarded_at < period.ends_at,
                    ),
                )
                .where(
                    TechnicianXpAward.workspace_id == workspace_id,
                    TechnicianXpAward.technician_id.in_(technician_ids),
                    TechnicianXpAward.revoked_at.is_(None),
                )
                .group_by(
                    TechnicianXpAward.technician_id,
                    TechnicianXpAward.category,
                )
            )
        ).all()
        totals: dict[uuid.UUID, dict[str, _CategoryTotals]] = {}
        for technician_id, category, lifetime_xp, monthly_xp, monthly_count in rows:
            totals.setdefault(technician_id, {})[category] = _CategoryTotals(
                int(lifetime_xp), int(monthly_xp), int(monthly_count)
            )
        return totals

    @staticmethod
    def _detail(
        technician: Technician,
        categories: dict[str, _CategoryTotals],
    ) -> TechnicianScoreDetail:
        lifetime_xp = sum(item.lifetime_xp for item in categories.values())
        attendance = categories.get("attendance", _CategoryTotals())
        jobs = categories.get("job", _CategoryTotals())
        upsells = categories.get("upsell", _CategoryTotals())
        return TechnicianScoreDetail(
            technician_id=technician.id,
            name=technician.name,
            lifetime_xp=lifetime_xp,
            level_progress=level_progress(lifetime_xp),
            attendance_days=attendance.monthly_count,
            completed_jobs=jobs.monthly_count,
            approved_upsells=upsells.monthly_count,
            attendance_xp=attendance.monthly_xp,
            job_xp=jobs.monthly_xp,
            upsell_xp=upsells.monthly_xp,
        )

    async def get_scoreboard(
        self,
        workspace_id: uuid.UUID,
        *,
        viewer_user_id: int | None,
        now: datetime | None = None,
    ) -> TechnicianScoreboard:
        period = await self._period(workspace_id, now=now)
        # simplification: crews are sorted in memory; paginate in SQL near 250 active technicians.
        technicians = list(
            await self.db.scalars(
                select(Technician).where(
                    Technician.workspace_id == workspace_id,
                    Technician.is_active.is_(True),
                )
            )
        )
        totals = await self._totals(workspace_id, [item.id for item in technicians], period)
        viewer = next((item for item in technicians if item.user_id == viewer_user_id), None)

        ranked = sorted(
            technicians,
            key=lambda item: (
                -sum(value.monthly_xp for value in totals.get(item.id, {}).values()),
                item.name.casefold(),
                str(item.id),
            ),
        )
        standings: list[TechnicianStanding] = []
        previous_xp: int | None = None
        previous_rank: int | None = None
        for position, technician in enumerate(ranked, start=1):
            categories = totals.get(technician.id, {})
            monthly_xp = sum(value.monthly_xp for value in categories.values())
            lifetime_xp = sum(value.lifetime_xp for value in categories.values())
            rank = None
            if monthly_xp > 0:
                rank = previous_rank if monthly_xp == previous_xp else position
                previous_xp = monthly_xp
                previous_rank = rank
            standings.append(
                TechnicianStanding(
                    technician.id,
                    technician.name,
                    rank,
                    monthly_xp,
                    level_for_xp(lifetime_xp),
                    technician is viewer,
                )
            )

        viewer_detail = self._detail(viewer, totals.get(viewer.id, {})) if viewer else None
        return TechnicianScoreboard(
            period,
            tuple(standings),
            viewer_detail,
            viewer.scoreboard_level_seen if viewer else None,
        )

    async def get_technician_detail(
        self,
        workspace_id: uuid.UUID,
        technician_id: uuid.UUID,
        *,
        requester_user_id: int,
        can_view_peers: bool,
        now: datetime | None = None,
    ) -> TechnicianScoreDetail:
        technician = await self.db.scalar(
            select(Technician).where(
                Technician.id == technician_id,
                Technician.workspace_id == workspace_id,
                Technician.is_active.is_(True),
            )
        )
        if technician is None or (not can_view_peers and technician.user_id != requester_user_id):
            raise NotFoundError("Technician not found")
        period = await self._period(workspace_id, now=now)
        totals = await self._totals(workspace_id, [technician.id], period)
        return self._detail(technician, totals.get(technician.id, {}))

    async def acknowledge_level(
        self,
        workspace_id: uuid.UUID,
        user_id: int,
        level: int,
    ) -> int:
        technician = await self.db.scalar(
            select(Technician)
            .where(
                Technician.workspace_id == workspace_id,
                Technician.user_id == user_id,
                Technician.is_active.is_(True),
            )
            .with_for_update()
        )
        if technician is None:
            raise NotFoundError("Technician not found")
        lifetime_xp = int(
            await self.db.scalar(
                select(func.coalesce(func.sum(TechnicianXpAward.points), 0)).where(
                    TechnicianXpAward.workspace_id == workspace_id,
                    TechnicianXpAward.technician_id == technician.id,
                    TechnicianXpAward.revoked_at.is_(None),
                )
            )
            or 0
        )
        current_level = level_for_xp(lifetime_xp).number
        if not 1 <= level <= current_level:
            raise ValidationError("Level cannot exceed the technician's current achievement")
        technician.scoreboard_level_seen = max(technician.scoreboard_level_seen, level)
        await self.db.flush()
        return technician.scoreboard_level_seen
