"""Rebuild last season's holiday-lighting quote as this season's draft.

Finding who to renew already exists (:mod:`.christmas_renewal` turns "lit last
season" into a queryable audience). What did not exist is reusing *what was
actually sold*: a rep re-quoting a returning customer had to re-measure the roof
and retype every line, for a house the crew already knows.

This copies the sold quote into a fresh draft for the current season while leaving
payment, approval, conversion, delivery, and public-link outcomes behind. Prices
carry forward unchanged so the rep can adjust the new draft before sending it.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from copy import deepcopy
from datetime import date

from sqlalchemy import and_, desc, exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.contact import Contact
from app.models.quote import Quote, QuoteLineItem
from app.models.recurring_job import RecurringJobTemplate, ServicePlanType
from app.models.workspace import Workspace
from app.services.seasonal.christmas_renewal import ChristmasSeason, resolve_christmas_season

# Only a quote that actually became work is worth rebuilding. A draft the rep
# abandoned, or one the customer declined, is not "what we did for them".
#
# Must stay a subset of QUOTE_STATUSES: `status` is a Postgres enum, so a value
# outside it is not an empty match but a hard InvalidTextRepresentation error
# that fails the whole query. "accepted" and "converted" were never members,
# which made every renewal lookup raise. `test_renewable_statuses_are_real`
# pins the subset rule so it cannot regress.
#
# A quote that became a job keeps status "approved" (the job is recorded in
# `converted_job_id`), so approval is the single signal that it sold.
RENEWABLE_STATUSES = ("approved",)

# Signals that a quote was holiday-lighting work rather than another service.
_CHRISTMAS_SERVICES = ("christmas", "christmas_lights", "holiday_lighting", "seasonal")


def _is_christmas_quote(quote: Quote) -> bool:
    """True when this quote sold holiday lighting.

    ``primary_service`` is the denormalized category the line items resolve to,
    maintained by ``_recompute_totals`` on every mutation path, so it is the
    cheapest reliable signal.
    """
    primary = str(quote.primary_service or "").strip().lower()
    return any(token in primary for token in _CHRISTMAS_SERVICES)


def _service_unknown(quote: Quote) -> bool:
    """True when this quote never had its service category snapshotted.

    Only these are eligible for the seasonal-plan fallback. A quote that says it
    sold gutter cleaning is *known* not to be holiday lighting, and renewing it
    would put last year's gutter lines on a quote titled "2026 renewal".
    """
    return not str(quote.primary_service or "").strip()


async def find_renewable_quote(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    contact_id: int,
    *,
    season: ChristmasSeason,
) -> Quote | None:
    """The most recent holiday-lighting quote this customer actually bought.

    Bounded to quotes issued *before* the current season opened, so re-running a
    renewal mid-season rebuilds last year's job rather than the draft a rep
    created ten minutes ago.
    """
    result = await db.execute(
        select(Quote)
        .where(
            Quote.workspace_id == workspace_id,
            Quote.contact_id == contact_id,
            Quote.status.in_(RENEWABLE_STATUSES),
            Quote.created_at < season.started_at,
        )
        .options(selectinload(Quote.line_items))
        .order_by(desc(Quote.created_at))
        # A customer buys a handful of jobs a year, not thousands; scanning a few
        # and filtering in Python beats encoding the category test in SQL twice.
        .limit(25)
    )
    candidates = list(result.scalars().all())
    for quote in candidates:
        if _is_christmas_quote(quote):
            return quote

    # Fall back to the seasonal plan row when the category was never snapshotted,
    # but only over quotes whose service is genuinely unknown — never over one
    # that names a different trade.
    uncategorized = [quote for quote in candidates if _service_unknown(quote)]
    if uncategorized and await _had_christmas_plan(db, workspace_id, contact_id, season):
        return uncategorized[0]
    return None


async def _had_christmas_plan(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    contact_id: int,
    season: ChristmasSeason,
) -> bool:
    """Whether a seasonal plan was provisioned for this contact before now."""
    found = await db.execute(
        select(
            exists().where(
                and_(
                    RecurringJobTemplate.workspace_id == workspace_id,
                    RecurringJobTemplate.contact_id == contact_id,
                    RecurringJobTemplate.plan_type == str(ServicePlanType.CHRISTMAS_LIGHTS),
                    RecurringJobTemplate.created_at < season.started_at,
                )
            )
        )
    )
    return bool(found.scalar())


def build_renewal_quote(
    source: Quote,
    *,
    number: str,
    season: ChristmasSeason,
    created_by_id: int | None,
) -> Quote:
    """A fresh draft carrying last season's scope, and none of its outcome.

    Pure: builds the ORM objects and leaves persistence to the caller, so the
    copy rules can be tested without a database.
    """
    renewal = Quote(
        workspace_id=source.workspace_id,
        contact_id=source.contact_id,
        service_location_id=source.service_location_id,
        assigned_user_id=source.assigned_user_id,
        # Same design: the house, the traced roofline and the measured trees are
        # the customer's, not last year's quote's.
        lighting_project_id=source.lighting_project_id,
        seasonal_installation_snapshot=deepcopy(source.seasonal_installation_snapshot),
        seasonal_takedown_included=source.seasonal_takedown_included,
        seasonal_storage_included=source.seasonal_storage_included,
        number=number,
        title=_renewal_title(source, season),
        status="draft",
        issue_date=date.today(),
        currency=source.currency,
        notes=source.notes,
        terms=source.terms,
        tax_amount=source.tax_amount,
        discount_amount=source.discount_amount,
        deposit_percentage=source.deposit_percentage,
        deposit_amount_fixed=source.deposit_amount_fixed,
        # Deep-copied, not shared: these are mutable JSONB blobs, and handing
        # both quotes the same dict means editing this year's proposal silently
        # rewrites last year's settled record.
        proposal_document=deepcopy(source.proposal_document),
        proposal_input=deepcopy(source.proposal_input),
        proposal_input_version=source.proposal_input_version,
        proposal_version=source.proposal_version,
        selected_permanent_kits=list(source.selected_permanent_kits or []),
        created_by_id=created_by_id,
    )
    renewal.line_items = [
        QuoteLineItem(
            name=line.name,
            description=line.description,
            service_category=line.service_category,
            quantity=line.quantity,
            unit_price=line.unit_price,
            discount=line.discount,
            total=line.total,
        )
        for line in source.line_items
    ]
    return renewal


def _renewal_title(source: Quote, season: ChristmasSeason) -> str:
    """Name the draft so a rep can tell it from the quote it came from."""
    base = (source.title or "Holiday lighting").strip() or "Holiday lighting"
    suffix = f" — {season.year} renewal"
    # ``Quote.title`` is String(200); trim the copied part, never the season.
    return base[: 200 - len(suffix)] + suffix


async def renew_last_season_quote(
    db: AsyncSession,
    workspace: Workspace,
    contact: Contact,
    *,
    allocate_number: Callable[[uuid.UUID], Awaitable[str]],
    created_by_id: int | None = None,
) -> Quote | None:
    """Rebuild this contact's last holiday-lighting sale as a new draft.

    ``allocate_number`` is the quote service's own numbering, passed in rather
    than reimplemented: numbers must stay monotonic across the whole workspace,
    and a second scheme here would hand out a number that already exists and
    trip ``uq_quotes_workspace_number``. Taking it as an argument also keeps
    this module free of an import back into the service that calls it.

    Returns ``None`` when there is nothing to renew, so the caller can say so
    plainly rather than creating an empty quote.
    """
    season = resolve_christmas_season(workspace)
    source = await find_renewable_quote(db, workspace.id, contact.id, season=season)
    if source is None:
        return None

    renewal = build_renewal_quote(
        source,
        number=await allocate_number(workspace.id),
        season=season,
        created_by_id=created_by_id,
    )
    db.add(renewal)
    await db.commit()
    await db.refresh(renewal, ["line_items"])
    return renewal
