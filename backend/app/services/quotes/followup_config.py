"""Per-workspace post-estimate follow-up config stored in ``workspace.settings``.

The cadence is deliberately capped at day 14. A separate unsold-quote revival
workflow starts later (30/60/90 days), so this boundary is the shared safety rail
that prevents both systems from messaging the same quote window.
"""

import structlog

from app.models.workspace import Workspace
from app.schemas.quote_followup import QuoteFollowupSettings

logger = structlog.get_logger()

SETTINGS_KEY = "post_estimate_followup"


def get_quote_followup_config(workspace: Workspace) -> QuoteFollowupSettings:
    """Return validated settings, falling back safely when JSONB was hand-edited."""
    raw = (workspace.settings or {}).get(SETTINGS_KEY, {})
    if not isinstance(raw, dict):
        raw = {}
    try:
        return QuoteFollowupSettings(**raw)
    except Exception as exc:  # pragma: no cover - defensive against manual JSONB edits
        logger.warning(
            "quote_followup_config_invalid_blob",
            workspace_id=str(workspace.id),
            error=str(exc),
        )
        return QuoteFollowupSettings()
