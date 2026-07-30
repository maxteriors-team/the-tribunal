"""Workspace policy for structured lead-source capture at manual intake.

The policy lives under one namespaced key in ``workspace.settings``. Reads are
lenient so a malformed hand-edited JSON blob cannot break contact creation or
the settings UI; invalid data falls back to the safe default (not required).
"""

import structlog
from pydantic import ValidationError

from app.models.workspace import Workspace
from app.schemas.lead_source import LeadSourceCaptureSettings

logger = structlog.get_logger()

SETTINGS_KEY = "lead_source_capture"


def get_lead_source_capture_settings(workspace: Workspace) -> LeadSourceCaptureSettings:
    """Return the workspace's manual-intake policy, defaulting when unset/invalid."""
    raw = (workspace.settings or {}).get(SETTINGS_KEY, {})
    if not isinstance(raw, dict):
        raw = {}
    try:
        return LeadSourceCaptureSettings(**raw)
    except (TypeError, ValidationError) as exc:  # pragma: no cover - defensive
        logger.warning(
            "lead_source_capture_settings_invalid_blob",
            workspace_id=str(workspace.id),
            error=str(exc),
        )
        return LeadSourceCaptureSettings()
