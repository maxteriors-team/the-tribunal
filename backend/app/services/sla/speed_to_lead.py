"""Speed-to-lead SLA: configuration, first-response recording, and metrics.

The "speed to lead" SLA measures the time between a lead first reaching out
(first inbound message or call) and the first AI/team response. Markers are
denormalized onto :class:`~app.models.conversation.Conversation` at message
time so SLA rollups and the public proof badge never scan the messages table.

Behaviour is gated per workspace via ``workspace.settings["speed_to_lead"]``::

    {
        "enabled": true,
        "sla_seconds": 60,
        "alert_enabled": true,
        "badge_enabled": false,
        "badge_window_days": 30,
    }
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.models.workspace import Workspace

# Settings key under ``workspace.settings`` holding the feature configuration.
SETTINGS_KEY = "speed_to_lead"

# Default SLA target: respond to a new lead within 60 seconds.
DEFAULT_SLA_SECONDS = 60

# Window for the public proof badge / dashboard rollup.
DEFAULT_BADGE_WINDOW_DAYS = 30

# Minimum measured leads before the public proof badge is shown, so a brand-new
# workspace never publishes a misleading "100%" headline from a tiny sample.
MIN_LEADS_FOR_PUBLIC_BADGE = 5

# Bounds so operator-supplied config can't produce nonsensical SLAs.
_MIN_SLA_SECONDS = 5
_MAX_SLA_SECONDS = 3600
_MIN_WINDOW_DAYS = 1
_MAX_WINDOW_DAYS = 365


@dataclass(slots=True, frozen=True)
class SpeedToLeadSettings:
    """Per-workspace configuration for the speed-to-lead SLA."""

    enabled: bool = True
    sla_seconds: int = DEFAULT_SLA_SECONDS
    alert_enabled: bool = True
    badge_enabled: bool = False
    badge_window_days: int = DEFAULT_BADGE_WINDOW_DAYS


@dataclass(slots=True, frozen=True)
class SLAMetrics:
    """First-response SLA rollup over a recent window."""

    window_days: int
    sla_seconds: int
    leads_measured: int
    within_sla: int
    pct_within_sla: float | None  # None when no leads measured
    avg_response_seconds: int | None
    median_response_seconds: int | None
    fastest_response_seconds: int | None


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def get_speed_to_lead_settings(workspace: Workspace) -> SpeedToLeadSettings:
    """Return the speed-to-lead settings for a workspace (defaults when unset)."""
    raw = (workspace.settings or {}).get(SETTINGS_KEY, {})
    if not isinstance(raw, dict):
        raw = {}
    try:
        sla_seconds = int(raw.get("sla_seconds", DEFAULT_SLA_SECONDS))
    except (TypeError, ValueError):
        sla_seconds = DEFAULT_SLA_SECONDS
    try:
        window_days = int(raw.get("badge_window_days", DEFAULT_BADGE_WINDOW_DAYS))
    except (TypeError, ValueError):
        window_days = DEFAULT_BADGE_WINDOW_DAYS
    return SpeedToLeadSettings(
        enabled=bool(raw.get("enabled", True)),
        sla_seconds=_clamp(sla_seconds, _MIN_SLA_SECONDS, _MAX_SLA_SECONDS),
        alert_enabled=bool(raw.get("alert_enabled", True)),
        badge_enabled=bool(raw.get("badge_enabled", False)),
        badge_window_days=_clamp(window_days, _MIN_WINDOW_DAYS, _MAX_WINDOW_DAYS),
    )


def _as_aware(value: datetime | None) -> datetime:
    """Coerce a timestamp to a timezone-aware UTC datetime."""
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def mark_inbound_lead(conversation: Conversation, occurred_at: datetime | None = None) -> None:
    """Record when a lead first reached out (first inbound message/call).

    Pure in-place mutation — the caller is responsible for committing in the
    same transaction. Idempotent: only the earliest inbound timestamp sticks.
    """
    if conversation.first_inbound_at is None:
        conversation.first_inbound_at = _as_aware(occurred_at)


def record_first_response(
    conversation: Conversation, occurred_at: datetime | None = None
) -> int | None:
    """Record the first AI/team response to an inbound-led conversation.

    Returns the time-to-first-response in seconds when this call set the first
    response, else ``None`` (no inbound anchor yet, or already responded). Pure
    in-place mutation; the caller commits.
    """
    if conversation.first_inbound_at is None or conversation.first_response_at is not None:
        return None
    responded_at = _as_aware(occurred_at)
    anchor = _as_aware(conversation.first_inbound_at)
    seconds = max(0, int(round((responded_at - anchor).total_seconds())))
    conversation.first_response_at = responded_at
    conversation.first_response_seconds = seconds
    return seconds


async def record_first_response_and_maybe_alert(
    db: AsyncSession,
    conversation: Conversation,
    occurred_at: datetime | None,
    log: Any,
) -> int | None:
    """Record the first response and alert workspace members on an SLA miss.

    The DB mutation is persisted by the caller's surrounding commit; the breach
    alert (push notification) is best-effort and never raises.
    """
    seconds = record_first_response(conversation, occurred_at)
    if seconds is None:
        return None

    workspace = await db.get(Workspace, conversation.workspace_id)
    if workspace is None:
        return seconds
    config = get_speed_to_lead_settings(workspace)

    log.info(
        "speed_to_lead_first_response",
        conversation_id=str(conversation.id),
        first_response_seconds=seconds,
        sla_seconds=config.sla_seconds,
        breached=seconds > config.sla_seconds,
    )

    if not (config.enabled and config.alert_enabled and seconds > config.sla_seconds):
        return seconds

    try:
        from app.services.push_notifications import push_notification_service

        await push_notification_service.send_to_workspace_members(
            db=db,
            workspace_id=str(conversation.workspace_id),
            title="Speed-to-lead SLA missed",
            body=(
                f"A new lead waited {seconds}s for a first reply (target {config.sla_seconds}s)."
            ),
            data={
                "type": "sla_breach",
                "conversationId": str(conversation.id),
                "firstResponseSeconds": str(seconds),
            },
            notification_type="sla",
            channel_id="alerts",
        )
    except Exception as exc:  # noqa: BLE001 - alerting must never break delivery
        log.warning("speed_to_lead_alert_failed", error=str(exc))

    return seconds


async def compute_sla_metrics(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    sla_seconds: int,
    window_days: int = DEFAULT_BADGE_WINDOW_DAYS,
) -> SLAMetrics:
    """Aggregate first-response SLA performance over the recent window."""
    cutoff = datetime.now(UTC) - timedelta(days=window_days)

    result = await db.execute(
        select(
            func.count(),
            func.count().filter(Conversation.first_response_seconds <= sla_seconds),
            func.avg(Conversation.first_response_seconds),
            func.percentile_cont(0.5).within_group(Conversation.first_response_seconds.asc()),
            func.min(Conversation.first_response_seconds),
        ).where(
            Conversation.workspace_id == workspace_id,
            Conversation.first_response_at >= cutoff,
            Conversation.first_response_seconds.isnot(None),
        )
    )
    total, within, avg_secs, median_secs, fastest = result.one()

    total = int(total or 0)
    within = int(within or 0)
    pct = round(within / total * 100, 1) if total else None

    return SLAMetrics(
        window_days=window_days,
        sla_seconds=sla_seconds,
        leads_measured=total,
        within_sla=within,
        pct_within_sla=pct,
        avg_response_seconds=int(round(avg_secs)) if avg_secs is not None else None,
        median_response_seconds=int(round(median_secs)) if median_secs is not None else None,
        fastest_response_seconds=int(fastest) if fastest is not None else None,
    )
