"""Per-workspace sales-pricing config stored in ``workspace.settings``.

Single source of truth for the proposal *engine* (tax, Wisetack financing, cash
pricing, commission, Good/Better/Best tiers, Care Plan, savings, bistro) — the
uploaded wizard's ``CONFIG`` minus the fixture catalog. Both the settings API
(``GET/PUT .../pricing``) and the proposal-pricing service read through
:func:`get_pricing_config`, so an operator edit is reflected everywhere with no
code change. Mirrors :mod:`app.services.quotes.proposal_template`.

Read leniently: a hand-edited or partial blob never turns a settings/proposal
read into a 500 — an unparseable config falls back to schema defaults.
"""

import structlog

from app.models.workspace import Workspace
from app.schemas.pricing import PricingSettings

logger = structlog.get_logger()

# Key under ``workspace.settings`` holding the pricing config.
SETTINGS_KEY = "pricing"


def get_pricing_config(workspace: Workspace) -> PricingSettings:
    """Return the pricing config for a workspace (defaults when unset/invalid)."""
    raw = (workspace.settings or {}).get(SETTINGS_KEY, {})
    if not isinstance(raw, dict):
        raw = {}
    try:
        return PricingSettings(**raw)
    except Exception as exc:  # pragma: no cover - defensive: never 500 a read
        logger.warning(
            "pricing_config_invalid_blob",
            workspace_id=str(workspace.id),
            error=str(exc),
        )
        return PricingSettings()
