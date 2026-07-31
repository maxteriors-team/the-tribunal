"""The warm database: who a pre-booking campaign is allowed to talk to.

Pre-booking is a bet on trust that already exists. A stranger will not wire a
deposit in September for work in April; a customer whose gutters you cleaned last
autumn, or who asked for a price and never pulled the trigger, will. So this
audience is deliberately **not** cold traffic:

- **past customers** — a completed :class:`~app.models.field_service.Job`, or an
  approved :class:`~app.models.quote.Quote`;
- **unsold quotes** — a quote left in
  :data:`~app.models.quote.UNSOLD_QUOTE_STATUSES` (``sent`` / ``expired``), the
  same constant the unsold-quote revival worker runs on, so "unsold" has exactly
  one definition in the codebase;
- **prior-season holiday-lighting customers** — opt-in and off by default,
  because it is far narrower than the other two: the homes that were lit last
  year. Its season arithmetic lives in
  :mod:`app.services.seasonal.christmas_renewal` rather than here, so a renewal
  campaign, a report and a saved segment all agree on which season a signup
  belonged to.

The slices are OR'd, so a renewal push is built by turning the two broad slices
*off* and the seasonal one *on* — no second audience concept, and the preview
counts each slice separately so the operator sees the size before committing.

Nothing here invents a query language. Operator narrowing rides the existing
segment machinery (:mod:`app.services.segments.segment_repository`, which resolves
saved :class:`~app.models.segment.Segment` rules through the shared contact filter
engine), and the suppression rule is the set-based twin of the per-contact gate
the reactivation drip runs before every send
(:meth:`app.services.rate_limiting.opt_out_manager.OptOutManager.check_opt_out`).

Three ways a contact says stop, all three honoured:

1. ``STOP`` to an SMS — a :class:`~app.models.opt_out.GlobalOptOut` row, matched
   on the deterministic ``phone_hash`` because the number itself is encrypted;
2. an operator or agent recording consent withdrawal —
   ``Contact.sms_consent_status == "opted_out"``;
3. an email unsubscribe — recorded as ``CampaignContact.opted_out`` on the
   enrollment the link came from (see :mod:`app.api.v1.email_unsubscribe`), which
   is workspace-wide intent even though it is stored per campaign.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, and_, exists, false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.campaign import Campaign, CampaignContact
from app.models.contact import Contact
from app.models.field_service import Job, JobStatus
from app.models.opt_out import GlobalOptOut
from app.models.quote import UNSOLD_QUOTE_STATUSES, Quote
from app.models.workspace import Workspace
from app.schemas.pricing import ChristmasConfig
from app.services.seasonal import (
    current_season,
    prior_season_christmas_condition,
    resolve_christmas_season,
)
from app.services.segments.segment_repository import (
    build_segment_contacts_query,
    get_segment_by_id,
)

# Consent-of-record value that means "do not contact" on
# :attr:`app.models.contact.Contact.sms_consent_status`.
CONSENT_OPTED_OUT = "opted_out"

# A quote in one of these statuses means the customer bought. ``approved`` is the
# sales-side proof of a past customer even when the job was delivered outside the
# CRM (imported history, work booked before the workspace onboarded).
WON_QUOTE_STATUSES = ("approved",)


@dataclass(frozen=True, slots=True)
class AudienceCounts:
    """Who is in the warm audience, and who was held back and why."""

    total: int
    past_customers: int
    unsold_quotes: int
    prior_season_christmas: int
    excluded_opted_out: int
    excluded_already_enrolled: int


def past_customer_condition(workspace_id: uuid.UUID) -> ColumnElement[bool]:
    """Contacts with delivered work or an approved quote in this workspace."""
    return or_(
        exists().where(
            and_(
                Job.contact_id == Contact.id,
                Job.workspace_id == workspace_id,
                Job.status == JobStatus.COMPLETED,
            )
        ),
        exists().where(
            and_(
                Quote.contact_id == Contact.id,
                Quote.workspace_id == workspace_id,
                Quote.status.in_(WON_QUOTE_STATUSES),
            )
        ),
    )


def unsold_quote_condition(workspace_id: uuid.UUID) -> ColumnElement[bool]:
    """Contacts holding an issued-but-undecided quote."""
    return exists().where(
        and_(
            Quote.contact_id == Contact.id,
            Quote.workspace_id == workspace_id,
            Quote.status.in_(UNSOLD_QUOTE_STATUSES),
        )
    )


def opted_out_condition(workspace_id: uuid.UUID) -> ColumnElement[bool]:
    """True for a contact who has told this workspace to stop, by any channel.

    Set-based equivalent of the reactivation drip's per-send opt-out gate; kept
    as one expression so the preview count, the enrollment and the eligibility
    check before taking a deposit can never disagree about who is suppressed.
    """
    return or_(
        Contact.sms_consent_status == CONSENT_OPTED_OUT,
        exists().where(
            and_(
                GlobalOptOut.workspace_id == workspace_id,
                GlobalOptOut.phone_hash == Contact.phone_hash,
            )
        ),
        exists().where(
            and_(
                CampaignContact.contact_id == Contact.id,
                CampaignContact.opted_out.is_(True),
                CampaignContact.campaign_id == Campaign.id,
                Campaign.workspace_id == workspace_id,
            )
        ),
    )


def enrolled_in_campaign_condition(campaign_id: uuid.UUID | None) -> ColumnElement[bool]:
    """True for a contact already enrolled in this campaign.

    ``None`` means "no campaign yet" — the wizard sizing an audience before the
    campaign row exists — and nobody can be enrolled in a campaign that does not
    exist, so the predicate is ``false``.
    """
    if campaign_id is None:
        return false()
    return exists().where(
        and_(
            CampaignContact.contact_id == Contact.id,
            CampaignContact.campaign_id == campaign_id,
        )
    )


def warm_condition(
    workspace_id: uuid.UUID,
    *,
    include_past_customers: bool,
    include_unsold_quotes: bool,
    prior_season_christmas: ColumnElement[bool] | None = None,
) -> ColumnElement[bool]:
    """The "warm database" predicate for the requested slices.

    ``prior_season_christmas`` is passed in already built rather than named by a
    flag, because resolving a season needs the workspace's pricing config — a
    read this pure predicate builder has no session to perform.

    With no slice selected the predicate is ``false``: a pre-booking campaign
    aimed at nobody warm is a mistake worth surfacing as an empty audience rather
    than quietly widening to the whole contact table.
    """
    clauses: list[ColumnElement[bool]] = []
    if include_past_customers:
        clauses.append(past_customer_condition(workspace_id))
    if include_unsold_quotes:
        clauses.append(unsold_quote_condition(workspace_id))
    if prior_season_christmas is not None:
        clauses.append(prior_season_christmas)
    if not clauses:
        return false()
    return or_(*clauses)


class PreBookingAudienceService:
    """Resolve and count the warm audience for a pre-booking campaign."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _prior_season_christmas(
        self,
        workspace_id: uuid.UUID,
        *,
        seasons_back: int | None,
    ) -> ColumnElement[bool]:
        """The prior-season holiday-lighting predicate for this workspace.

        The season boundary comes from the workspace's own Christmas config, so a
        business that installs in October is not measured against a November
        default. A missing workspace resolves against schema defaults rather than
        raising: the caller is already scoped by ``workspace_id``.
        """
        workspace = await self.db.get(Workspace, workspace_id)
        season = (
            resolve_christmas_season(workspace)
            if workspace is not None
            else current_season(ChristmasConfig())
        )
        return prior_season_christmas_condition(workspace_id, season, seasons_back=seasons_back)

    async def _base_query(
        self,
        workspace_id: uuid.UUID,
        *,
        segment_id: uuid.UUID | None,
    ) -> Select[Any]:
        """Start from a saved segment when given one, else every contact.

        Segment resolution goes through the segment repository so an operator's
        saved rules mean the same thing here as they do on the contacts page.
        """
        if segment_id is None:
            return select(Contact).where(Contact.workspace_id == workspace_id)

        segment = await get_segment_by_id(segment_id, workspace_id, self.db)
        if segment is None:
            raise ValueError("Segment not found")
        # The repository is untyped at the boundary (it builds queries from JSON
        # rules); the cast records what it actually returns.
        query: Select[Any] = build_segment_contacts_query(workspace_id, segment.definition)
        return query

    async def resolve_contact_ids(
        self,
        workspace_id: uuid.UUID,
        campaign_id: uuid.UUID | None,
        *,
        include_past_customers: bool = True,
        include_unsold_quotes: bool = True,
        include_prior_season_christmas: bool = False,
        seasons_back: int | None = None,
        segment_id: uuid.UUID | None = None,
        limit: int | None = None,
    ) -> list[int]:
        """Contact ids eligible to receive the pre-booking offer.

        Warm, not opted out by any channel, and not already enrolled in this
        campaign. Ordered newest-engaged first so a truncated run reaches the
        contacts most likely to answer.
        """
        seasonal = (
            await self._prior_season_christmas(workspace_id, seasons_back=seasons_back)
            if include_prior_season_christmas
            else None
        )
        query = (await self._base_query(workspace_id, segment_id=segment_id)).where(
            warm_condition(
                workspace_id,
                include_past_customers=include_past_customers,
                include_unsold_quotes=include_unsold_quotes,
                prior_season_christmas=seasonal,
            ),
            ~opted_out_condition(workspace_id),
            ~enrolled_in_campaign_condition(campaign_id),
        )
        query = query.with_only_columns(Contact.id).order_by(
            Contact.last_engaged_at.desc().nulls_last(), Contact.id.desc()
        )
        if limit is not None:
            query = query.limit(limit)

        result = await self.db.execute(query)
        return [row[0] for row in result.all()]

    async def preview(
        self,
        workspace_id: uuid.UUID,
        campaign_id: uuid.UUID | None,
        *,
        include_past_customers: bool = True,
        include_unsold_quotes: bool = True,
        include_prior_season_christmas: bool = False,
        seasons_back: int | None = None,
        segment_id: uuid.UUID | None = None,
    ) -> AudienceCounts:
        """Count the audience and the two reasons contacts were held back.

        Every slice is counted whether or not it is selected, so an operator can
        see that 143 homes were lit last season *before* deciding to aim at them.
        """
        base = await self._base_query(workspace_id, segment_id=segment_id)

        async def _count(*conditions: ColumnElement[bool]) -> int:
            counted = base.where(*conditions).with_only_columns(Contact.id).order_by(None)
            total = await self.db.scalar(select(func.count()).select_from(counted.subquery()))
            return int(total or 0)

        seasonal = await self._prior_season_christmas(workspace_id, seasons_back=seasons_back)
        warm = warm_condition(
            workspace_id,
            include_past_customers=include_past_customers,
            include_unsold_quotes=include_unsold_quotes,
            prior_season_christmas=seasonal if include_prior_season_christmas else None,
        )
        opted_out = opted_out_condition(workspace_id)
        enrolled = enrolled_in_campaign_condition(campaign_id)

        return AudienceCounts(
            total=await _count(warm, ~opted_out, ~enrolled),
            past_customers=await _count(past_customer_condition(workspace_id), ~opted_out),
            unsold_quotes=await _count(unsold_quote_condition(workspace_id), ~opted_out),
            prior_season_christmas=await _count(seasonal, ~opted_out),
            excluded_opted_out=await _count(warm, opted_out),
            excluded_already_enrolled=await _count(warm, ~opted_out, enrolled),
        )

    async def is_eligible(self, workspace_id: uuid.UUID, contact_id: int) -> bool:
        """Whether one contact may still be sold a pre-booking slot.

        Checked again at reservation time because an opt-out can arrive between
        the campaign send and the customer clicking through, and taking a deposit
        from someone who has since said stop is the one failure here that costs
        money to unwind.
        """
        found = await self.db.scalar(
            select(Contact.id).where(
                Contact.id == contact_id,
                Contact.workspace_id == workspace_id,
                ~opted_out_condition(workspace_id),
            )
        )
        return found is not None
