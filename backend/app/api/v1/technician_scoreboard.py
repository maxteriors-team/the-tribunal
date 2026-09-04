"""Authenticated, tenant-scoped Lighting League endpoints."""

import uuid

from fastapi import APIRouter

from app.api.deps import DB, CanReadJobs, TransactionalDB
from app.api.service_errors import ServiceErrorRoute
from app.core.permissions import Capability, role_can
from app.schemas.technician_scoreboard import (
    TechnicianLevelAcknowledgementRequest,
    TechnicianLevelAcknowledgementResponse,
    TechnicianScoreboardDetail,
    TechnicianScoreboardLevel,
    TechnicianScoreboardPeriod,
    TechnicianScoreboardResponse,
    TechnicianScoreboardRules,
    TechnicianScoreboardStanding,
)
from app.services.technician_scoreboard import (
    ATTENDANCE_XP,
    COMPLETED_JOB_XP,
    LEVELS,
    UPSELL_BASE_XP,
    UPSELL_VALUE_BONUS_CAP,
    UPSELL_VALUE_DIVISOR,
    TechnicianScoreboardService,
    TechnicianScoreDetail,
)

router = APIRouter(route_class=ServiceErrorRoute)


def _detail_response(detail: TechnicianScoreDetail) -> TechnicianScoreboardDetail:
    progress = detail.level_progress
    next_level = progress.next_level
    return TechnicianScoreboardDetail(
        technician_id=detail.technician_id,
        name=detail.name,
        lifetime_xp=detail.lifetime_xp,
        monthly_xp=detail.attendance_xp + detail.job_xp + detail.upsell_xp,
        level_number=progress.level.number,
        level_title=progress.level.title,
        current_level_threshold=progress.level.lifetime_xp,
        next_level_number=next_level.number if next_level else None,
        next_level_title=next_level.title if next_level else None,
        next_level_threshold=next_level.lifetime_xp if next_level else None,
        xp_into_level=progress.xp_into_level,
        xp_to_next_level=progress.xp_to_next_level,
        level_progress=progress.progress,
        attendance_days=detail.attendance_days,
        completed_jobs=detail.completed_jobs,
        approved_upsells=detail.approved_upsells,
        attendance_xp=detail.attendance_xp,
        job_xp=detail.job_xp,
        upsell_xp=detail.upsell_xp,
    )


@router.get("", response_model=TechnicianScoreboardResponse)
async def get_technician_scoreboard(
    workspace_id: uuid.UUID,
    db: DB,
    membership: CanReadJobs,
) -> TechnicianScoreboardResponse:
    """Return public standings plus only the linked viewer's private breakdown."""
    snapshot = await TechnicianScoreboardService(db).get_scoreboard(
        workspace_id, viewer_user_id=membership.user_id
    )
    return TechnicianScoreboardResponse(
        period=TechnicianScoreboardPeriod(
            start_date=snapshot.period.start_date,
            end_date=snapshot.period.end_date,
            starts_at=snapshot.period.starts_at,
            ends_at=snapshot.period.ends_at,
            timezone=snapshot.period.timezone,
        ),
        rules=TechnicianScoreboardRules(
            attendance_day_xp=ATTENDANCE_XP,
            completed_job_xp=COMPLETED_JOB_XP,
            upsell_base_xp=UPSELL_BASE_XP,
            upsell_value_divisor=int(UPSELL_VALUE_DIVISOR),
            upsell_value_bonus_cap=UPSELL_VALUE_BONUS_CAP,
            upsell_max_xp=UPSELL_BASE_XP + UPSELL_VALUE_BONUS_CAP,
        ),
        levels=[
            TechnicianScoreboardLevel(
                number=level.number,
                title=level.title,
                lifetime_xp=level.lifetime_xp,
            )
            for level in LEVELS
        ],
        standings=[
            TechnicianScoreboardStanding(
                technician_id=row.technician_id,
                name=row.name,
                rank=row.rank,
                monthly_xp=row.monthly_xp,
                level_number=row.level.number,
                level_title=row.level.title,
                is_viewer=row.is_viewer,
            )
            for row in snapshot.standings
        ],
        viewer_detail=(
            _detail_response(snapshot.viewer_detail) if snapshot.viewer_detail else None
        ),
        viewer_level_seen=snapshot.viewer_level_seen,
    )


@router.get(
    "/technicians/{technician_id}",
    response_model=TechnicianScoreboardDetail,
)
async def get_technician_scoreboard_detail(
    workspace_id: uuid.UUID,
    technician_id: uuid.UUID,
    db: DB,
    membership: CanReadJobs,
) -> TechnicianScoreboardDetail:
    """Return self detail, or peer detail only to office job writers."""
    detail = await TechnicianScoreboardService(db).get_technician_detail(
        workspace_id,
        technician_id,
        requester_user_id=membership.user_id,
        can_view_peers=role_can(membership.role, Capability.JOBS_WRITE),
    )
    return _detail_response(detail)


@router.post(
    "/me/acknowledge-level",
    response_model=TechnicianLevelAcknowledgementResponse,
)
async def acknowledge_technician_level(
    workspace_id: uuid.UUID,
    payload: TechnicianLevelAcknowledgementRequest,
    db: TransactionalDB,
    membership: CanReadJobs,
) -> TechnicianLevelAcknowledgementResponse:
    """Monotonically acknowledge only a level the linked technician has reached."""
    level_seen = await TechnicianScoreboardService(db).acknowledge_level(
        workspace_id,
        membership.user_id,
        payload.level,
    )
    return TechnicianLevelAcknowledgementResponse(level_seen=level_seen)
