"""Fail-closed rollout guard for Permanent proposal card payments."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from app.core.config import settings

if TYPE_CHECKING:
    from app.models.quote import Quote


def proposal_payments_enabled(quote: Quote) -> bool:
    """Require operator allowlisting plus the tenant-controlled workspace flag."""
    workspace_settings = quote.workspace.settings if quote.workspace else None
    return (
        quote.workspace_id in settings.proposal_payment_pilot_workspace_ids
        and isinstance(workspace_settings, Mapping)
        and workspace_settings.get("proposal_payments_enabled") is True
    )
