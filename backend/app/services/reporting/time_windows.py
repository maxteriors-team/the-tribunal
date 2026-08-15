"""Workspace-local reporting windows converted to UTC for timestamp columns."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workspace import Workspace
from app.utils.timezones import resolve_workspace_timezone


async def get_workspace_reporting_timezone(
    db: AsyncSession,
    workspace_id: uuid.UUID,
) -> str:
    """Return a validated IANA timezone for one workspace's business reports."""
    workspace = (
        await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    ).scalar_one_or_none()
    return resolve_workspace_timezone(workspace).key


def local_date_bounds_utc(
    start_date: date,
    end_date: date,
    timezone_name: str,
) -> tuple[datetime, datetime]:
    """Convert inclusive workspace-local dates into a half-open UTC window."""
    zone = ZoneInfo(timezone_name)
    start_local = datetime.combine(start_date, time.min, tzinfo=zone)
    end_local = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=zone)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)
