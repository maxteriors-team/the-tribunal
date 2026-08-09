"""Workspace timezone resolution.

Every customer-facing time in this product is stored as an aware UTC instant and
rendered back into a workspace-local wall clock at the last moment. That render
step used to be copy-pasted into each caller, and the copies disagreed about the
fallback when a workspace has no ``settings["timezone"]`` — which is *every*
workspace, because nothing in provisioning or onboarding writes that key.

The booking side (``BaseToolExecutor``, ``CallContext``) defaulted to
``America/New_York``: the AI agent offers "2:00 PM Eastern", the customer agrees,
and 18:00Z is stored. The confirmation and reminder texts defaulted to ``UTC``
and rendered that same row back as "6:00 PM". Same appointment, two zones, and
the wrong one was the one the customer read.

So the fallback here is deliberately the *booking* default, not UTC: it is the
zone that decided the instant in the first place, and rendering in any other zone
tells the customer about an appointment nobody agreed to.
"""

from __future__ import annotations

import zoneinfo
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from app.models.workspace import Workspace

logger = structlog.get_logger()

__all__ = ["DEFAULT_WORKSPACE_TIMEZONE", "resolve_workspace_timezone", "workspace_timezone_name"]


DEFAULT_WORKSPACE_TIMEZONE = "America/New_York"


def workspace_timezone_name(workspace: Workspace | None) -> str:
    """Return the workspace's configured IANA zone name, or the default."""
    tz_name = ((workspace.settings if workspace is not None else None) or {}).get("timezone")
    if isinstance(tz_name, str) and tz_name.strip():
        return tz_name.strip()
    return DEFAULT_WORKSPACE_TIMEZONE


def resolve_workspace_timezone(workspace: Workspace | None) -> zoneinfo.ZoneInfo:
    """Return the tzinfo used to render times for this workspace's customers.

    Falls back to :data:`DEFAULT_WORKSPACE_TIMEZONE` when the workspace has no
    timezone configured, and again when the configured value is not a real IANA
    zone — a typo in workspace settings must not silently shift every quoted
    time by the UTC offset.
    """
    tz_name = workspace_timezone_name(workspace)
    try:
        return zoneinfo.ZoneInfo(tz_name)
    except (KeyError, ValueError, zoneinfo.ZoneInfoNotFoundError):
        logger.warning(
            "workspace_timezone_invalid",
            workspace_id=str(workspace.id) if workspace is not None else None,
            configured=tz_name,
            using=DEFAULT_WORKSPACE_TIMEZONE,
        )
        return zoneinfo.ZoneInfo(DEFAULT_WORKSPACE_TIMEZONE)
