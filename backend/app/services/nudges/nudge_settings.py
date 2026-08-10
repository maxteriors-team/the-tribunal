"""Defensive parsing for workspace nudge settings stored in JSON."""

from typing import Any


def get_nudge_settings(workspace_settings: object) -> dict[str, Any]:
    """Return a mapping even for legacy NULL or malformed workspace settings."""
    if not isinstance(workspace_settings, dict):
        return {}

    nudge_settings = workspace_settings.get("nudge_settings", {})
    return nudge_settings if isinstance(nudge_settings, dict) else {}
