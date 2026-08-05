"""Put a sent quote on the sales board.

Sending a proposal is the strongest buying signal a home-service business gets,
and until this shipped it left no trace on the Opportunities board: an operator
could quote ten jobs and the pipeline would still look empty. On first send this
either advances the contact's open deal to ``Quote Sent / Follow Up`` or opens a
card there when they have none.

Deliberately **not** routed through the automation engine.
:func:`app.services.automations.events.emit_automation_event` defaults to
``require_active_automation=True``, so it drops the event unless the operator has
already built a matching automation — which would make "sent quotes go into the
pipeline" true only for workspaces that had already automated it. This is a
direct service call instead, mirroring
:func:`app.services.opportunities.lead_opportunity.open_lead_opportunity`.

Gated per workspace by ``workspace.settings["auto_pipeline"]["on_quote_sent"]``,
**default ON** — a separate flag from ``auto_pipeline.enabled``, which governs
raw *inbound leads* and is deliberately opt-in. Deals never move backwards: a
quote sent on a deal already at or past ``Quote Sent / Follow Up`` is a no-op.

Two per-contact off-switches also apply: the ``no-automation`` tag (preventive,
see :mod:`app.services.automations.opt_out`) and a card the operator already
removed from the pipeline (retroactive, see
:mod:`app.services.opportunities.pipeline_removal`).

Flushes but does not commit — the caller (``QuoteService._ensure_sent_state``)
owns the transaction that commits the send.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.opportunity import Opportunity
from app.models.pipeline import PipelineStage
from app.models.workspace import Workspace
from app.services.automations.opt_out import automation_suppressed
from app.services.lead_sources.attribution_service import (
    snapshot_contact_attribution_on_opportunity,
)
from app.services.opportunities.default_pipeline import (
    QUOTE_SENT_STAGE_NAME,
    get_default_pipeline_first_stage,
)
from app.services.opportunities.lead_opportunity import SETTINGS_KEY, opportunity_name
from app.services.opportunities.pipeline_removal import removed_card_exists

logger = structlog.get_logger()

__all__ = ["ON_QUOTE_SENT_KEY", "on_quote_sent_enabled", "place_quote_on_pipeline"]

# Settings flag under ``workspace.settings["auto_pipeline"]``.
ON_QUOTE_SENT_KEY = "on_quote_sent"

# Only an ``open`` deal is advanced; a won/lost/abandoned deal is history.
_OPEN_STATUS = "open"

# Source recorded on a card this module opens, so the board can tell an
# automatic quote-driven deal from one an operator typed in.
_SOURCE = "quote_sent"


def on_quote_sent_enabled(workspace: Workspace) -> bool:
    """Whether a sent quote should move/open a pipeline card (default True).

    Default-on, unlike ``auto_pipeline.enabled``: a sent quote means someone was
    quoted a price, which belongs on a *sales* board on its own merit, whereas a
    raw inbound lead does not.
    """
    raw = (workspace.settings or {}).get(SETTINGS_KEY, {})
    if not isinstance(raw, dict):
        return True
    return bool(raw.get(ON_QUOTE_SENT_KEY, True))


async def _quote_sent_stage(db: AsyncSession, pipeline_id: uuid.UUID) -> PipelineStage | None:
    """The pipeline's quote-sent stage, or ``None`` when it has no such column.

    Exact name first, then a case-insensitive ``quote sent`` match so a workspace
    that renamed the stage slightly still advances. A pipeline with nothing
    resembling it is left alone rather than guessed at — dropping a deal into an
    arbitrary column is worse than not moving it.
    """
    stages = (
        (
            await db.execute(
                select(PipelineStage)
                .where(PipelineStage.pipeline_id == pipeline_id)
                .order_by(PipelineStage.order.asc())
            )
        )
        .scalars()
        .all()
    )
    for stage in stages:
        if stage.name == QUOTE_SENT_STAGE_NAME:
            return stage
    for stage in stages:
        if "quote sent" in stage.name.lower():
            return stage
    return None


async def _open_opportunity_for(
    db: AsyncSession, workspace_id: uuid.UUID, contact_id: int
) -> Opportunity | None:
    result = await db.execute(
        select(Opportunity)
        .where(
            Opportunity.workspace_id == workspace_id,
            Opportunity.primary_contact_id == contact_id,
            Opportunity.status == _OPEN_STATUS,
        )
        .order_by(Opportunity.created_at.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def place_quote_on_pipeline(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    contact: Contact,
    *,
    quote_id: uuid.UUID | None = None,
) -> Opportunity | None:
    """Advance or open ``contact``'s deal at ``Quote Sent / Follow Up``.

    Returns the affected :class:`Opportunity`, or ``None`` when the workspace
    disabled the behaviour, the pipeline has no quote-sent stage, or the deal is
    already at/past that stage.
    """
    log = logger.bind(
        component="quote_pipeline",
        workspace_id=str(workspace_id),
        contact_id=contact.id,
        quote_id=str(quote_id) if quote_id else None,
    )

    workspace = await db.get(Workspace, workspace_id)
    if workspace is None or not on_quote_sent_enabled(workspace):
        return None

    # This call never touches the event bus, so it needs its own check against
    # the same contact-level kill switch ``emit_automation_event`` honours.
    if await automation_suppressed(db, workspace_id, contact.id):
        log.info("quote_pipeline_suppressed_by_tag")
        return None

    existing = await _open_opportunity_for(db, workspace_id, contact.id)
    if existing is not None:
        return await _advance_existing(db, workspace_id, existing, log)

    # "Remove from pipeline" has to stick, or the button looks broken: the next
    # quote send would silently put the card back.
    removed = await db.execute(select(removed_card_exists(workspace_id, contact.id)))
    if removed.scalar():
        log.info("quote_pipeline_suppressed_by_removal")
        return None

    return await _open_at_quote_sent(db, workspace_id, contact, log)


async def _advance_existing(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    opportunity: Opportunity,
    log: structlog.BoundLogger,
) -> Opportunity | None:
    """Move an open deal forward to the quote-sent stage, never backwards."""
    target = await _quote_sent_stage(db, opportunity.pipeline_id)
    if target is None:
        log.info("quote_pipeline_stage_missing", pipeline_id=str(opportunity.pipeline_id))
        return None

    if opportunity.stage_id == target.id:
        return None

    current = (
        await db.execute(select(PipelineStage).where(PipelineStage.id == opportunity.stage_id))
    ).scalar_one_or_none()
    if current is not None and current.order > target.order:
        # Already further along (negotiating, won). A quote re-send must not
        # drag a deal back down the board.
        log.info(
            "quote_pipeline_no_backward_move",
            opportunity_id=str(opportunity.id),
            current_stage=current.name,
        )
        return None

    # Delegate so the activity log, probability, ``stage_changed_at`` and the
    # ``deal_stage_changed`` event all come from one place.
    from app.services.opportunities.opportunity_service import OpportunityService

    moved = await OpportunityService(db).move_stage(
        workspace_id,
        opportunity.id,
        target.id,
        user_id=None,
        source="quote_sent",
    )
    await db.flush()
    log.info(
        "quote_pipeline_opportunity_advanced",
        opportunity_id=str(opportunity.id),
        stage=target.name,
    )
    return moved


async def _open_at_quote_sent(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    contact: Contact,
    log: structlog.BoundLogger,
) -> Opportunity | None:
    """Open a new card directly in the quote-sent stage."""
    pipeline, _first_stage = await get_default_pipeline_first_stage(db, workspace_id)
    target = await _quote_sent_stage(db, pipeline.id)
    if target is None:
        log.info("quote_pipeline_stage_missing", pipeline_id=str(pipeline.id))
        return None

    opportunity = Opportunity(
        workspace_id=workspace_id,
        pipeline_id=pipeline.id,
        stage_id=target.id,
        primary_contact_id=contact.id,
        name=opportunity_name(contact),
        probability=target.probability,
        source=_SOURCE,
        status=_OPEN_STATUS,
    )
    snapshot_contact_attribution_on_opportunity(opportunity, contact)
    db.add(opportunity)
    await db.flush()

    log.info(
        "quote_pipeline_opportunity_opened",
        opportunity_id=str(opportunity.id),
        pipeline_id=str(pipeline.id),
        stage=target.name,
    )
    return opportunity
