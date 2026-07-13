"""Auto-open pipeline opportunities for new inbound leads.

Drops a new lead onto the Opportunities board so operators can work it without
any manual data entry — the "new leads automatically go into the pipeline" flow.
Idempotent per contact: a contact never gets a second *open* card, so wiring
this into multiple inbound funnels (lead form, embed widget, offer opt-ins,
inbound SMS, inbound call) is safe.

Gated per workspace via ``workspace.settings["auto_pipeline"]["enabled"]``
(default ON), stored in the JSONB ``settings`` column — no migration required.
A won/lost/abandoned deal never blocks a new card, so a returning lead whose
previous deal already closed still gets a fresh opportunity.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.opportunity import Opportunity
from app.models.workspace import Workspace
from app.services.opportunities.default_pipeline import get_default_pipeline_first_stage

logger = structlog.get_logger()

# Settings key under ``workspace.settings`` holding the feature configuration.
SETTINGS_KEY = "auto_pipeline"

# Only an ``open`` deal blocks a new auto-created card. Closed deals
# (won/lost/abandoned) should not stop a returning lead from re-entering the
# pipeline.
_OPEN_STATUS = "open"


def auto_pipeline_enabled(workspace: Workspace) -> bool:
    """Whether new inbound leads should auto-open a pipeline card (default True)."""
    raw = (workspace.settings or {}).get(SETTINGS_KEY, {})
    if not isinstance(raw, dict):
        return True
    return bool(raw.get("enabled", True))


def _opportunity_name(contact: Contact) -> str:
    """Human-readable deal name derived from the contact (never blank)."""
    full_name = " ".join(p for p in (contact.first_name, contact.last_name) if p).strip()
    company = (contact.company_name or "").strip()
    if full_name and company:
        return f"{full_name} — {company}"[:255]
    return (full_name or company or "New lead")[:255]


async def open_lead_opportunity(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    contact: Contact,
    *,
    source: str | None = None,
) -> Opportunity | None:
    """Open a deduped opportunity for ``contact`` in the default pipeline's first stage.

    Returns the created :class:`Opportunity`, or ``None`` when auto-pipeline is
    disabled for the workspace or the contact already has an open card. Flushes
    but does not commit — the caller owns the surrounding transaction.
    """
    log = logger.bind(component="auto_pipeline", workspace_id=str(workspace_id))

    # A contact created in the same transaction may not have an id yet.
    if contact.id is None:
        await db.flush()

    workspace = await db.get(Workspace, workspace_id)
    if workspace is None or not auto_pipeline_enabled(workspace):
        return None

    # Dedupe: never fork a second open card for the same contact.
    existing = await db.execute(
        select(Opportunity.id)
        .where(
            Opportunity.workspace_id == workspace_id,
            Opportunity.primary_contact_id == contact.id,
            Opportunity.status == _OPEN_STATUS,
        )
        .limit(1)
    )
    if existing.scalar_one_or_none() is not None:
        return None

    pipeline, stage = await get_default_pipeline_first_stage(db, workspace_id)

    opportunity = Opportunity(
        workspace_id=workspace_id,
        pipeline_id=pipeline.id,
        stage_id=stage.id if stage else None,
        primary_contact_id=contact.id,
        name=_opportunity_name(contact),
        probability=stage.probability if stage else 0,
        source=source,
        status=_OPEN_STATUS,
    )
    db.add(opportunity)
    await db.flush()

    log.info(
        "auto_pipeline_opportunity_opened",
        opportunity_id=str(opportunity.id),
        contact_id=contact.id,
        pipeline_id=str(pipeline.id),
        stage_id=str(stage.id) if stage else None,
        source=source,
    )
    return opportunity
