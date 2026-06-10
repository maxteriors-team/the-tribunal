"""Saved ad-library monitors (recurring ICP searches).

A "monitor" is a saved search + ICP thresholds + a re-scan schedule. Monitors
reuse the existing :class:`~app.models.outbound_mission.OutboundMission` rails:
the monitor config lives under ``discovery_config["ad_monitor"]`` and the
mission's ``last_run_at`` / ``next_run_at`` drive scheduling.

Re-running a monitor enqueues a fresh ad-library :class:`LeadDiscoveryJob`; the
discovery worker then re-queries the advertisers and (because the upsert is
idempotent and the signal engine recomputes) refreshes active/stop times — which
is exactly what proves "still running the same ad over time".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead_discovery_job import (
    DiscoveryJobStatus,
    DiscoverySourceType,
    LeadDiscoveryJob,
)
from app.models.outbound_mission import OutboundMission

AD_MONITOR_KEY = "ad_monitor"

_PLATFORM_TO_SOURCE = {
    "meta": DiscoverySourceType.META_AD_LIBRARY,
    "google": DiscoverySourceType.GOOGLE_ADS_TRANSPARENCY,
}


def compute_next_run(interval_hours: int, *, now: datetime | None = None) -> datetime:
    """Return the next scheduled run time."""
    return (now or datetime.now(UTC)) + timedelta(hours=max(1, interval_hours))


def monitor_config(mission: OutboundMission) -> dict[str, Any] | None:
    """Return the ad-monitor config block on a mission, if present."""
    config = (mission.discovery_config or {}).get(AD_MONITOR_KEY)
    return config if isinstance(config, dict) else None


def is_active_monitor(mission: OutboundMission) -> bool:
    """Whether a mission is an active ad-library monitor."""
    config = monitor_config(mission)
    return bool(config and config.get("is_active", True))


def build_monitor_config(
    *,
    name: str,
    search: dict[str, Any],
    icp_thresholds: dict[str, Any],
    schedule_interval_hours: int,
    is_active: bool = True,
) -> dict[str, Any]:
    """Assemble the ``ad_monitor`` config block stored on a mission."""
    return {
        "name": name,
        "search": search,
        "icp_thresholds": icp_thresholds,
        "schedule_interval_hours": schedule_interval_hours,
        "is_active": is_active,
    }


def job_params_from_search(search: dict[str, Any]) -> dict[str, Any]:
    """Map a saved search blob into discovery-job params."""
    return {
        "country": search.get("country", "US"),
        "search_terms": search.get("search_terms"),
        "page_id": search.get("page_id"),
        "page_name": search.get("page_name"),
        "ad_delivery_date_min": search.get("ad_delivery_date_min"),
        "ad_delivery_date_max": search.get("ad_delivery_date_max"),
        "sort_by": search.get("sort_by", "longest_running"),
        "max_results": search.get("max_results", 50),
        "use_thirdparty_fallback": search.get("use_thirdparty_fallback", False),
    }


def create_discovery_job_for_monitor(
    db: AsyncSession,
    mission: OutboundMission,
    *,
    requested_by_id: int | None = None,
) -> LeadDiscoveryJob:
    """Create (add to session) a pending discovery job for a monitor mission."""
    config = monitor_config(mission) or {}
    search = config.get("search") or {}
    platform = str(search.get("platform") or "meta")
    source_type = _PLATFORM_TO_SOURCE.get(platform, DiscoverySourceType.META_AD_LIBRARY)
    params = job_params_from_search(search)

    job = LeadDiscoveryJob(
        workspace_id=mission.workspace_id,
        mission_id=mission.id,
        requested_by_id=requested_by_id,
        source_type=source_type,
        source_label=config.get("name") or mission.name,
        query=search.get("search_terms"),
        params=params,
        status=DiscoveryJobStatus.PENDING,
        requested_count=int(params.get("max_results") or 50),
    )
    db.add(job)
    return job


async def due_monitor_missions(
    db: AsyncSession,
    *,
    limit: int = 10,
    now: datetime | None = None,
) -> list[OutboundMission]:
    """Return active monitor missions whose next run is due.

    Locked ``FOR UPDATE SKIP LOCKED`` so multiple replicas don't double-schedule.
    """
    moment = now or datetime.now(UTC)
    result = await db.execute(
        select(OutboundMission)
        .where(
            OutboundMission.discovery_config[AD_MONITOR_KEY].isnot(None),
            (OutboundMission.next_run_at.is_(None)) | (OutboundMission.next_run_at <= moment),
        )
        .order_by(OutboundMission.next_run_at.asc().nullsfirst())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return [m for m in result.scalars().all() if is_active_monitor(m)]


def mark_monitor_scheduled(mission: OutboundMission, *, now: datetime | None = None) -> None:
    """Stamp a monitor mission's last/next run after enqueuing a job."""
    moment = now or datetime.now(UTC)
    config = monitor_config(mission) or {}
    interval = int(config.get("schedule_interval_hours") or 24)
    mission.last_run_at = moment
    mission.next_run_at = compute_next_run(interval, now=moment)


def monitor_to_response_dict(mission: OutboundMission) -> dict[str, Any]:
    """Shape a monitor mission into the API response dict."""
    config = monitor_config(mission) or {}
    return {
        "id": mission.id,
        "workspace_id": mission.workspace_id,
        "name": config.get("name") or mission.name,
        "search": config.get("search") or {},
        "icp_thresholds": config.get("icp_thresholds") or {},
        "schedule_interval_hours": int(config.get("schedule_interval_hours") or 24),
        "is_active": bool(config.get("is_active", True)),
        "last_run_at": mission.last_run_at,
        "next_run_at": mission.next_run_at,
        "created_at": mission.created_at,
        "updated_at": mission.updated_at,
    }
