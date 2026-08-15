"""Canonical booked-revenue queries shared by every reporting surface.

A booking is an approved quote at the time it was approved.  Older/manual deals
that were closed won without an approved quote remain reportable as legacy
bookings, but a linked approved quote always wins so revenue is never counted
twice.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, exists, func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import CompoundSelect

from app.models.contact import Contact
from app.models.opportunity import Opportunity
from app.models.quote import Quote
from app.services.reporting.time_windows import local_date_bounds_utc

_APPROVED_QUOTE_STATUS = "approved"
_WON_OPPORTUNITY_STATUS = "won"
_DEFAULT_ATTRIBUTION_CONFIDENCE = 1.0


@dataclass(frozen=True, slots=True)
class BookedRevenueTotals:
    """Booked jobs and their value inside one reporting window."""

    count: int = 0
    revenue: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class BookedRevenueAttribution:
    """Booked revenue grouped by the immutable/fallback acquisition snapshot."""

    lead_source_id: uuid.UUID | None
    lead_source_campaign_id: uuid.UUID | None
    count: int
    revenue: Decimal
    weighted_confidence: Decimal


def _quote_booked_at() -> ColumnElement[Any]:
    """Best available booking timestamp, including pre-``approved_at`` rows."""
    return func.coalesce(Quote.approved_at, Quote.updated_at, Quote.created_at)


def _approved_quote_exists_for_opportunity() -> Any:
    """Correlated check used to suppress a duplicate legacy won event."""
    return exists(
        select(literal(1)).where(
            Quote.workspace_id == Opportunity.workspace_id,
            Quote.opportunity_id == Opportunity.id,
            Quote.status == _APPROVED_QUOTE_STATUS,
        )
    )


def booked_revenue_events_query(
    workspace_id: uuid.UUID,
    start_date: date,
    end_date: date,
    *,
    timezone_name: str,
) -> CompoundSelect[Any]:
    """Return canonical booking events for aggregate/report attribution queries."""
    start_utc, end_utc = local_date_bounds_utc(start_date, end_date, timezone_name)
    booked_at = _quote_booked_at()

    quote_events = (
        select(
            literal("quote").label("event_kind"),
            Quote.id.label("event_id"),
            Quote.total.label("amount"),
            func.coalesce(Quote.contact_id, Opportunity.primary_contact_id).label("contact_id"),
            func.coalesce(
                Opportunity.referral_partner_id,
                Contact.referral_partner_id,
            ).label("referral_partner_id"),
            func.coalesce(
                Opportunity.lead_source_id,
                Contact.first_touch_lead_source_id,
            ).label("lead_source_id"),
            func.coalesce(
                Opportunity.lead_source_campaign_id,
                Contact.first_touch_lead_source_campaign_id,
            ).label("lead_source_campaign_id"),
            func.coalesce(
                Opportunity.attribution_confidence,
                Contact.attribution_confidence,
                _DEFAULT_ATTRIBUTION_CONFIDENCE,
            ).label("attribution_confidence"),
        )
        .select_from(Quote)
        .outerjoin(
            Opportunity,
            and_(
                Opportunity.id == Quote.opportunity_id,
                Opportunity.workspace_id == Quote.workspace_id,
            ),
        )
        .outerjoin(
            Contact,
            and_(
                Contact.id == func.coalesce(Quote.contact_id, Opportunity.primary_contact_id),
                Contact.workspace_id == Quote.workspace_id,
            ),
        )
        .where(
            Quote.workspace_id == workspace_id,
            Quote.status == _APPROVED_QUOTE_STATUS,
            booked_at >= start_utc,
            booked_at < end_utc,
        )
    )

    legacy_won_events = (
        select(
            literal("opportunity").label("event_kind"),
            Opportunity.id.label("event_id"),
            Opportunity.amount.label("amount"),
            Opportunity.primary_contact_id.label("contact_id"),
            func.coalesce(
                Opportunity.referral_partner_id,
                Contact.referral_partner_id,
            ).label("referral_partner_id"),
            func.coalesce(
                Opportunity.lead_source_id,
                Contact.first_touch_lead_source_id,
            ).label("lead_source_id"),
            func.coalesce(
                Opportunity.lead_source_campaign_id,
                Contact.first_touch_lead_source_campaign_id,
            ).label("lead_source_campaign_id"),
            func.coalesce(
                Opportunity.attribution_confidence,
                Contact.attribution_confidence,
                _DEFAULT_ATTRIBUTION_CONFIDENCE,
            ).label("attribution_confidence"),
        )
        .select_from(Opportunity)
        .outerjoin(
            Contact,
            and_(
                Contact.id == Opportunity.primary_contact_id,
                Contact.workspace_id == Opportunity.workspace_id,
            ),
        )
        .where(
            Opportunity.workspace_id == workspace_id,
            Opportunity.status == _WON_OPPORTUNITY_STATUS,
            Opportunity.closed_date >= start_date,
            Opportunity.closed_date <= end_date,
            ~_approved_quote_exists_for_opportunity(),
        )
    )

    return union_all(quote_events, legacy_won_events)


async def get_booked_revenue_totals(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    start_date: date,
    end_date: date,
    *,
    timezone_name: str,
) -> BookedRevenueTotals:
    """Aggregate canonical booked jobs without double-counting quote-backed wins."""
    events = booked_revenue_events_query(
        workspace_id,
        start_date,
        end_date,
        timezone_name=timezone_name,
    ).subquery("booked_revenue_events")
    row = (
        await db.execute(
            select(
                func.count(events.c.event_id),
                func.coalesce(func.sum(events.c.amount), 0),
            )
        )
    ).one()
    return BookedRevenueTotals(count=int(row[0] or 0), revenue=Decimal(str(row[1] or 0)))


async def get_booked_revenue_by_attribution(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    start_date: date,
    end_date: date,
    *,
    timezone_name: str,
) -> list[BookedRevenueAttribution]:
    """Aggregate canonical bookings by source/campaign for ROI reporting."""
    events = booked_revenue_events_query(
        workspace_id,
        start_date,
        end_date,
        timezone_name=timezone_name,
    ).subquery("attributed_booked_revenue_events")
    rows = (
        await db.execute(
            select(
                events.c.lead_source_id,
                events.c.lead_source_campaign_id,
                func.count(events.c.event_id),
                func.coalesce(func.sum(events.c.amount), 0),
                func.coalesce(
                    func.sum(events.c.amount * events.c.attribution_confidence),
                    0,
                ),
            ).group_by(
                events.c.lead_source_id,
                events.c.lead_source_campaign_id,
            )
        )
    ).all()
    return [
        BookedRevenueAttribution(
            lead_source_id=row[0],
            lead_source_campaign_id=row[1],
            count=int(row[2] or 0),
            revenue=Decimal(str(row[3] or 0)),
            weighted_confidence=Decimal(str(row[4] or 0)),
        )
        for row in rows
    ]
