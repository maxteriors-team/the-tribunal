"""Per-workspace unsold-quote follow-up config stored in ``workspace.settings``.

Single source of truth for the quiet-quote sequence: whether it runs, on which
days after ``issue_date``, where the high-value line sits, and which quiet-hours
window applies. Both the settings API (``GET/PUT .../unsold-quotes``) and
:mod:`app.workers.unsold_quote_worker` read through
:func:`get_unsold_quote_config`, so an operator edit takes effect on the next
poll with no code change. Mirrors :mod:`app.services.quotes.pricing_config`.

Read leniently: a hand-edited or partial blob never turns a settings read into a
500. Note the failure direction differs from the attach rules — an unparseable
config here degrades to the **disabled** defaults, because failing open would
mean texting past customers from a config nobody can read.
"""

import structlog

from app.models.workspace import Workspace
from app.schemas.unsold_quotes import UnsoldQuoteSettings

logger = structlog.get_logger()

# Key under ``workspace.settings`` holding the unsold-quote config.
SETTINGS_KEY = "unsold_quotes"


def get_unsold_quote_config(workspace: Workspace) -> UnsoldQuoteSettings:
    """Return the unsold-quote config for a workspace (defaults when unset/invalid)."""
    raw = (workspace.settings or {}).get(SETTINGS_KEY, {})
    if not isinstance(raw, dict):
        raw = {}
    try:
        return UnsoldQuoteSettings(**raw)
    except Exception as exc:  # pragma: no cover - defensive: never 500 a read
        logger.warning(
            "unsold_quote_config_invalid_blob",
            workspace_id=str(workspace.id),
            error=str(exc),
        )
        return UnsoldQuoteSettings()
