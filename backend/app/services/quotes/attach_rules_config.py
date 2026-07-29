"""Per-workspace attach-rule config stored in ``workspace.settings``.

Single source of truth for the cross-sell prompt (which primary service asks for
which add-on, and how hard). Both the settings API (``GET/PUT .../attach-rules``)
and the quote save path read through :func:`get_attach_rules_config`, so an
operator edit takes effect on the next quote with no code change. Mirrors
:mod:`app.services.quotes.pricing_config`.

Read leniently: a hand-edited or partial blob never turns a settings/quote save
into a 500 — an unparseable config falls back to schema defaults, which are
advisory and therefore cannot block a save either. Failing *open* is the right
call here: a broken config must not stand between a rep and a sold job.
"""

import structlog

from app.models.workspace import Workspace
from app.schemas.attach_rules import AttachRulesSettings

logger = structlog.get_logger()

# Key under ``workspace.settings`` holding the attach-rule config.
SETTINGS_KEY = "attach_rules"


def get_attach_rules_config(workspace: Workspace) -> AttachRulesSettings:
    """Return the attach-rule config for a workspace (defaults when unset/invalid)."""
    raw = (workspace.settings or {}).get(SETTINGS_KEY, {})
    if not isinstance(raw, dict):
        raw = {}
    try:
        return AttachRulesSettings(**raw)
    except Exception as exc:  # pragma: no cover - defensive: never 500 a read
        logger.warning(
            "attach_rules_config_invalid_blob",
            workspace_id=str(workspace.id),
            error=str(exc),
        )
        return AttachRulesSettings()
