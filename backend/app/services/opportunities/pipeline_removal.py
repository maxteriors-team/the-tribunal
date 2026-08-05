"""Taking a deal off the sales board, and making that stick.

Automatic pipeline cards need an off-switch that behaves. If "Remove from
pipeline" only deleted the card, the next quote send would put it straight back
and the button would look broken.

So removal is *sticky per contact*: a card removed here is marked
``status='abandoned'`` **and** ``is_active=False``, and
:mod:`app.services.opportunities.quote_opportunity` refuses to open a new card
for a contact that carries that mark. The pair is the marker — ``abandoned``
alone is reachable through ordinary status edits, so both columns must agree
before automation treats a contact as opted out of the board.

An operator can always put the deal back by hand; this only stops *automation*
from doing it for them.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import Exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.opportunity import Opportunity, OpportunityActivity

logger = structlog.get_logger()

__all__ = [
    "REMOVED_STATUS",
    "removed_card_exists",
    "remove_from_pipeline",
]

# Closed-lost-ish status a removed card takes. Matches the existing migration
# precedent for retiring a deal without destroying its history.
REMOVED_STATUS = "abandoned"


def removed_card_exists(workspace_id: uuid.UUID, contact_id: int) -> Exists:
    """``EXISTS`` predicate: this contact has had a pipeline card removed.

    Index-backed on ``opportunities.primary_contact_id`` and stops at the first
    match, so the quote-send hot path pays one indexed probe.
    """
    return (
        select(Opportunity.id)
        .where(
            Opportunity.workspace_id == workspace_id,
            Opportunity.primary_contact_id == contact_id,
            Opportunity.status == REMOVED_STATUS,
            Opportunity.is_active.is_(False),
        )
        .exists()
    )


async def remove_from_pipeline(
    db: AsyncSession,
    opportunity: Opportunity,
    *,
    user_id: int | None = None,
) -> Opportunity:
    """Take ``opportunity`` off the board, keeping its history.

    Idempotent. Flushes but does not commit — the caller owns the transaction.
    """
    if opportunity.status == REMOVED_STATUS and not opportunity.is_active:
        return opportunity

    previous_status = opportunity.status
    opportunity.status = REMOVED_STATUS
    opportunity.is_active = False

    db.add(
        OpportunityActivity(
            opportunity_id=opportunity.id,
            user_id=user_id,
            activity_type="status_changed",
            old_value=previous_status,
            new_value=REMOVED_STATUS,
            description=(
                "Removed from the pipeline. Automation will not re-add this "
                "contact; add a deal manually to put them back."
            ),
        )
    )
    await db.flush()

    logger.info(
        "opportunity_removed_from_pipeline",
        opportunity_id=str(opportunity.id),
        workspace_id=str(opportunity.workspace_id),
        previous_status=previous_status,
    )
    return opportunity
