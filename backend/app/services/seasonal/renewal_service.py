"""Re-sell last season's holiday lighting, one house at a time.

:mod:`app.services.seasonal.christmas_renewal` answers *who* was lit last season
as a composable SQL predicate, and the pre-booking campaign uses it to text the
whole list at once. That is the bulk motion. This module is the single-customer
motion the bulk one cannot express: an operator picks one house they lit last
year and gets back a draft quote already carrying last season's work.

**Why clone the quote rather than re-measure.** The roofline footage, the tree
and wreath counts, and the negotiated prices are already sitting on the approved
quote that provisioned the signup
(:attr:`~app.models.recurring_job.RecurringJobTemplate.source_quote_id`). Re-deriving
them means re-tracing a photo for a house whose measurements have not changed,
which is exactly the work a renewal is supposed to skip.

**Why the category survives the copy.** ``QuoteLineItem.service_category`` is
what marks a line as seasonal work downstream (attach metrics, reporting, the
proposal's category sections). :meth:`QuoteService._build_line_item` snapshots it
from the price book and deliberately never reads it from a request body, so a
plain create would drop it and the renewal would land untagged. Here the source
is a prior quote *in the same workspace* — trusted server-side data, never client
input — so the copy is applied after creation rather than routed through the
request schema.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.contact import Contact
from app.models.quote import Quote, QuoteLineItem
from app.models.recurring_job import RecurringJobTemplate, ServicePlanType
from app.models.workspace import Workspace
from app.schemas.quote import QuoteCreate, QuoteDetailResponse, QuoteLineItemCreate
from app.services.seasonal.christmas_renewal import (
    ChristmasSeason,
    resolve_christmas_season,
)

logger = structlog.get_logger()

# Title stamped on the draft so the renewal reads as a renewal in the quote list
# rather than as an unexplained second quote for a customer who already bought.
RENEWAL_TITLE = "{year} Christmas Lights — Renewal"

# Fallback tag for a cloned line whose source predates category snapshotting.
# Without it a renewed quote's lines are indistinguishable from hand-typed ones
# and drop out of seasonal reporting, which is the opposite of "tagged like a
# Christmas job".
CHRISTMAS_SERVICE_CATEGORY = "christmas"


class RenewalError(Exception):
    """A renewal could not be built from this contact's history."""


class NoPriorSeasonQuoteError(RenewalError):
    """The contact has a prior-season signup but no quote left to copy.

    Reachable in normal operation: ``source_quote_id`` is ``ON DELETE SET NULL``,
    so deleting an old quote keeps the customer's plan and strands the renewal.
    The operator is told to build the quote by hand rather than handed an empty
    draft that looks like a bug.
    """


@dataclass(frozen=True, slots=True)
class RenewalCandidate:
    """One house that was lit in an earlier season, with what it bought."""

    contact_id: int
    contact_name: str
    quote_id: uuid.UUID
    quote_number: str
    quote_total: float
    line_item_count: int
    #: When the signup was recorded — the season the operator is renewing *from*.
    signed_up_at: datetime


def _prior_season_quote_subquery(
    workspace_id: uuid.UUID, season: ChristmasSeason
) -> Select[tuple[Any, ...]]:
    """Each contact's most recent prior-season holiday signup.

    ``DISTINCT ON`` rather than a ``GROUP BY`` + re-join: a customer who bought in
    several seasons must appear **once**, keyed to their latest quote, and a
    Christmas sale provisions two plan rows (install + takedown) that share a
    quote, so an unaggregated join would list the same house twice.
    """
    return (
        select(
            RecurringJobTemplate.contact_id.label("contact_id"),
            RecurringJobTemplate.source_quote_id.label("quote_id"),
            RecurringJobTemplate.created_at.label("signed_up_at"),
        )
        .where(
            RecurringJobTemplate.workspace_id == workspace_id,
            RecurringJobTemplate.plan_type == str(ServicePlanType.CHRISTMAS_LIGHTS),
            RecurringJobTemplate.created_at < season.started_at,
            RecurringJobTemplate.source_quote_id.is_not(None),
        )
        .distinct(RecurringJobTemplate.contact_id)
        .order_by(
            RecurringJobTemplate.contact_id,
            RecurringJobTemplate.created_at.desc(),
        )
    )


class ChristmasRenewalService:
    """List last season's houses and turn one of them into a draft quote."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.log = logger.bind(component="christmas_renewal_service")

    async def list_candidates(
        self,
        workspace: Workspace,
        *,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
        now: datetime | None = None,
    ) -> tuple[list[RenewalCandidate], int]:
        """Houses lit in an earlier season, newest signup first, with a total count."""
        season = resolve_christmas_season(workspace, now=now)
        prior = _prior_season_quote_subquery(workspace.id, season).subquery()

        line_counts = (
            select(
                QuoteLineItem.quote_id.label("quote_id"),
                func.count().label("line_item_count"),
            )
            .group_by(QuoteLineItem.quote_id)
            .subquery()
        )

        base = (
            select(
                Contact.id,
                Contact.first_name,
                Contact.last_name,
                Quote.id.label("quote_id"),
                Quote.number,
                Quote.total,
                func.coalesce(line_counts.c.line_item_count, 0).label("line_item_count"),
                prior.c.signed_up_at,
            )
            .select_from(prior)
            .join(Contact, Contact.id == prior.c.contact_id)
            # An inner join on the quote drops signups whose quote was deleted:
            # they have nothing to copy, so offering them a one-click renewal
            # would only produce an empty draft.
            .join(Quote, Quote.id == prior.c.quote_id)
            .outerjoin(line_counts, line_counts.c.quote_id == Quote.id)
            # Belt and braces over the workspace-scoped subquery: the contact and
            # the quote must both belong to the caller's workspace, so a stale or
            # cross-tenant id can never widen the result.
            .where(
                Contact.workspace_id == workspace.id,
                Quote.workspace_id == workspace.id,
            )
        )

        if search and search.strip():
            term = f"%{search.strip()}%"
            base = base.where(
                or_(
                    Contact.first_name.ilike(term),
                    Contact.last_name.ilike(term),
                    Quote.number.ilike(term),
                )
            )

        total = await self.db.scalar(select(func.count()).select_from(base.subquery()))
        rows = await self.db.execute(
            base.order_by(prior.c.signed_up_at.desc(), Contact.id).limit(limit).offset(offset)
        )

        candidates = [
            RenewalCandidate(
                contact_id=row.id,
                contact_name=f"{row.first_name} {row.last_name}".strip()
                if row.last_name
                else row.first_name,
                quote_id=row.quote_id,
                quote_number=row.number,
                quote_total=float(row.total),
                line_item_count=int(row.line_item_count),
                signed_up_at=row.signed_up_at,
            )
            for row in rows
        ]
        return candidates, int(total or 0)

    async def create_renewal_quote(
        self,
        workspace: Workspace,
        contact_id: int,
        *,
        created_by_id: int | None = None,
        now: datetime | None = None,
    ) -> QuoteDetailResponse:
        """Clone this contact's last holiday quote into a draft for this season.

        The draft is created through the normal
        :meth:`~app.services.quotes.quote_service.QuoteService.create_quote` path
        so numbering, the workspace default deposit, total recomputation and the
        client proposal link all behave exactly as they do for a hand-built quote.
        """
        # Imported here rather than at module scope: ``app.services.quotes``
        # eagerly imports ``QuoteService``, which reaches back into seasonal
        # pricing — a top-level import closes that cycle.
        from app.services.quotes.quote_service import QuoteService

        season = resolve_christmas_season(workspace, now=now)
        prior = _prior_season_quote_subquery(workspace.id, season).subquery()

        source = await self.db.scalar(
            select(Quote)
            .select_from(prior)
            .join(Quote, Quote.id == prior.c.quote_id)
            .where(
                prior.c.contact_id == contact_id,
                Quote.workspace_id == workspace.id,
            )
            .options(selectinload(Quote.line_items))
        )
        if source is None:
            raise NoPriorSeasonQuoteError(
                "This customer has no prior-season holiday quote left to copy."
            )

        source_lines = sorted(source.line_items, key=lambda li: li.created_at)
        created = await QuoteService(self.db).create_quote(
            workspace.id,
            QuoteCreate(
                contact_id=contact_id,
                service_location_id=source.service_location_id,
                title=RENEWAL_TITLE.format(year=season.year),
                line_items=[
                    QuoteLineItemCreate(
                        name=line.name,
                        description=line.description,
                        quantity=float(line.quantity),
                        unit_price=float(line.unit_price),
                        discount=float(line.discount),
                    )
                    for line in source_lines
                ],
            ),
            created_by_id=created_by_id,
        )

        await self._copy_service_categories(created.id, source_lines)
        self.log.info(
            "christmas_renewal_quote_created",
            workspace_id=str(workspace.id),
            contact_id=contact_id,
            source_quote_id=str(source.id),
            quote_id=str(created.id),
            season_year=season.year,
            line_items=len(source_lines),
        )
        # Re-read so the caller sees the categories that were just written.
        return await QuoteService(self.db).get_quote(workspace.id, created.id)

    async def _copy_service_categories(
        self,
        quote_id: uuid.UUID,
        source_lines: list[QuoteLineItem],
    ) -> None:
        """Carry each source line's seasonal tag onto its clone.

        Matched by position, which is safe because the clone was built from
        ``source_lines`` in this same order moments ago. Every line gets a
        category: the source's own when it has one, otherwise the seasonal
        fallback, so a renewal is never silently untagged.
        """
        new_lines = (
            await self.db.scalars(
                select(QuoteLineItem)
                .where(QuoteLineItem.quote_id == quote_id)
                .order_by(QuoteLineItem.created_at, QuoteLineItem.id)
            )
        ).all()
        if len(new_lines) != len(source_lines):
            # Defensive: an attach rule or hook that injects a line would break
            # positional matching, so tag everything seasonally rather than
            # pairing the wrong description to the wrong category.
            for line in new_lines:
                line.service_category = CHRISTMAS_SERVICE_CATEGORY
        else:
            for new_line, source_line in zip(new_lines, source_lines, strict=True):
                new_line.service_category = (
                    source_line.service_category or CHRISTMAS_SERVICE_CATEGORY
                )
        await self.db.flush()
