"""Who can be renewed — the list behind the Renew Last Season's Homes screen.

:mod:`app.services.seasonal.christmas_renewal_quote` answers "rebuild *this*
customer's last sale", and the pre-booking campaign texts the whole warm list at
once. Neither answers the question the screen actually asks: *which customers
could I renew right now?*

Deliberately thin. The eligibility rule lives in
:func:`~app.services.seasonal.christmas_renewal.prior_season_christmas_condition`
and the per-customer rebuild lives in ``christmas_renewal_quote``; this module
only finds the contacts that rule already matches and attaches enough of their
last sale to make a row worth clicking. Re-deriving either rule here would let
the list drift from the button.

The list is intentionally *optimistic*: it matches on the seasonal plan row,
which is the same signal the renewal's own fallback uses. A contact whose prior
quote turns out not to be holiday lighting still appears and gets a clean 404
from the renewal endpoint. The alternative — running the full per-contact
category test for every row — costs a query per contact to save a rare wasted
click.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.quote import Quote
from app.models.recurring_job import RecurringJobTemplate, ServicePlanType
from app.models.workspace import Workspace
from app.services.seasonal.christmas_renewal import (
    ChristmasSeason,
    resolve_christmas_season,
)
from app.services.seasonal.christmas_renewal_quote import RENEWABLE_STATUSES


@dataclass(frozen=True, slots=True)
class RenewalCandidate:
    """One house lit in an earlier season, with the sale a renewal would rebuild."""

    contact_id: int
    contact_name: str
    #: Best-known prior sale, for the row subtitle. ``None`` when the plan row
    #: outlived the quote it came from.
    quote_number: str | None
    quote_total: float | None
    #: When the seasonal plan was created — the season being renewed *from*.
    signed_up_at: datetime


def _latest_prior_signup(
    workspace_id: uuid.UUID, season: ChristmasSeason
) -> Select[tuple[Any, ...]]:
    """Each contact's most recent pre-season holiday signup, one row per contact.

    ``DISTINCT ON`` rather than ``GROUP BY``: a seasonal sale provisions two plan
    rows (install and takedown) sharing one quote, so an unaggregated join would
    list the same house twice.
    """
    return (
        select(
            RecurringJobTemplate.contact_id.label("contact_id"),
            RecurringJobTemplate.created_at.label("signed_up_at"),
        )
        .where(
            RecurringJobTemplate.workspace_id == workspace_id,
            RecurringJobTemplate.plan_type == str(ServicePlanType.CHRISTMAS_LIGHTS),
            RecurringJobTemplate.created_at < season.started_at,
        )
        .distinct(RecurringJobTemplate.contact_id)
        .order_by(RecurringJobTemplate.contact_id, RecurringJobTemplate.created_at.desc())
    )


async def list_renewal_candidates(
    db: AsyncSession,
    workspace: Workspace,
    *,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
    now: datetime | None = None,
) -> tuple[list[RenewalCandidate], int, int]:
    """Houses lit in an earlier season, newest signup first.

    Returns the page, the total number of matches, and the season being sold.
    """
    season = resolve_christmas_season(workspace, now=now)
    prior = _latest_prior_signup(workspace.id, season).subquery()

    # The customer's most recent pre-season sale, for the row's subtitle only. A
    # LATERAL keeps it to one row per contact without a second round trip. The
    # renewal endpoint re-resolves the real source quote when the rep clicks, so
    # this is display — never the thing that gets copied.
    last_sale = (
        select(Quote.number.label("number"), Quote.total.label("total"))
        .where(
            Quote.workspace_id == workspace.id,
            Quote.contact_id == prior.c.contact_id,
            Quote.status.in_(RENEWABLE_STATUSES),
            Quote.created_at < season.started_at,
        )
        .order_by(Quote.created_at.desc())
        .limit(1)
        .lateral()
    )

    base = (
        select(
            Contact.id,
            Contact.first_name,
            Contact.last_name,
            prior.c.signed_up_at,
            last_sale.c.number,
            last_sale.c.total,
        )
        .select_from(prior)
        .join(Contact, Contact.id == prior.c.contact_id)
        .outerjoin(last_sale, true())
        # Belt and braces over the workspace-scoped subquery: the contact must
        # also belong to the caller's workspace, so a stale id can never widen
        # the result across tenants.
        .where(Contact.workspace_id == workspace.id)
    )

    if search and search.strip():
        term = f"%{search.strip()}%"
        base = base.where(
            or_(
                Contact.first_name.ilike(term),
                Contact.last_name.ilike(term),
                last_sale.c.number.ilike(term),
            )
        )

    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = await db.execute(
        base.order_by(prior.c.signed_up_at.desc(), Contact.id).limit(limit).offset(offset)
    )

    candidates = [
        RenewalCandidate(
            contact_id=row.id,
            contact_name=" ".join(filter(None, (row.first_name, row.last_name))).strip(),
            quote_number=row.number,
            quote_total=float(row.total) if row.total is not None else None,
            signed_up_at=row.signed_up_at,
        )
        for row in rows
    ]
    return candidates, int(total), season.year
