"""Per-workspace neighbour-outreach config stored in ``workspace.settings``.

Single source of truth for the radius, the cap, whether a completed job generates
a list automatically, and which message template the (consent-gated) messaging
path renders. Both the settings API (``GET/PUT .../neighbor-outreach``) and
:mod:`app.services.field_service.neighbor_outreach` read through
:func:`get_neighbor_outreach_config`, so an operator edit takes effect everywhere
with no code change. Mirrors :mod:`app.services.quotes.pricing_config`.

Read leniently: a hand-edited or partial blob never turns a settings read or a job
completion into a 500 — an unparseable config falls back to schema defaults, which
are the safe ones (disabled, print-only).
"""

import structlog

from app.models.workspace import Workspace
from app.schemas.neighbor_outreach import NeighborOutreachSettings

logger = structlog.get_logger()

# Key under ``workspace.settings`` holding the neighbour-outreach config.
SETTINGS_KEY = "neighbor_outreach"


def get_neighbor_outreach_config(workspace: Workspace) -> NeighborOutreachSettings:
    """Return the neighbour-outreach config for a workspace (defaults when unset/invalid)."""
    raw = (workspace.settings or {}).get(SETTINGS_KEY, {})
    if not isinstance(raw, dict):
        raw = {}
    try:
        return NeighborOutreachSettings(**raw)
    except Exception as exc:  # pragma: no cover - defensive: never 500 a read
        logger.warning(
            "neighbor_outreach_config_invalid_blob",
            workspace_id=str(workspace.id),
            error=str(exc),
        )
        return NeighborOutreachSettings()
