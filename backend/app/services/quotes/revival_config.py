"""Per-workspace unsold-quote revival config stored in ``workspace.settings``.

Mirrors :mod:`app.services.quotes.followup_config`. The two sequences are
deliberately separate blobs so an operator can run the first-14-days cadence
without ever opting into long-range revival, or the other way around.
"""

import structlog

from app.models.workspace import Workspace
from app.schemas.quote_revival import QuoteRevivalSettings

logger = structlog.get_logger()

SETTINGS_KEY = "unsold_quote_revival"


def get_quote_revival_config(workspace: Workspace) -> QuoteRevivalSettings:
    """Return validated settings, falling back safely when JSONB was hand-edited."""
    raw = (workspace.settings or {}).get(SETTINGS_KEY, {})
    if not isinstance(raw, dict):
        raw = {}
    try:
        return QuoteRevivalSettings(**raw)
    except Exception as exc:  # pragma: no cover - defensive against manual JSONB edits
        logger.warning(
            "quote_revival_config_invalid_blob",
            workspace_id=str(workspace.id),
            error=str(exc),
        )
        return QuoteRevivalSettings()
