"""Proposal template settings stored in ``workspace.settings``.

Single source of truth for the per-workspace branding + boilerplate rendered on
client proposals. Both the settings API (``PUT/GET .../proposal-template``) and
the public proposal page read through :func:`get_proposal_template`, so an
operator edit in settings is reflected on every proposal with no code change —
the "add to it in the future" contract. Mirrors the read-with-defaults pattern
of :mod:`app.services.sla.speed_to_lead` and the reputation settings.
"""

from app.models.workspace import Workspace
from app.schemas.proposal import ProposalTemplateSettings

# Key under ``workspace.settings`` holding the proposal template config.
SETTINGS_KEY = "proposal_template"


def get_proposal_template(workspace: Workspace) -> ProposalTemplateSettings:
    """Return the proposal template for a workspace (defaults when unset).

    ``business_name`` falls back to the workspace name so a brand-new workspace
    renders a sensible proposal before the operator customizes anything.
    """
    raw = (workspace.settings or {}).get(SETTINGS_KEY, {})
    if not isinstance(raw, dict):
        raw = {}
    template = ProposalTemplateSettings(**raw)
    if not template.business_name:
        template.business_name = workspace.name
    return template
