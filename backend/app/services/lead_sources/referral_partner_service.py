"""Referral partners: workspace-scoped CRUD plus the production scoreboard.

The scoreboard answers the two questions a home-service owner actually has about
their referral network:

1. **Who sends work?** Rank partners by canonical booked revenue, with the referral
   count, close rate, and average job value behind it.
2. **Who went quiet?** A partner with real history who has sent nothing in the
   last N days is not a statistic — it is today's call list. That filter is the
   highest-value thing here, so it is a first-class flag on every row and an
   optional filter on the query.

Both read the attribution that already exists: referrals come from
:attr:`app.models.contact.Contact.referral_partner_id` (the lead the partner
sent) and booked production from the canonical quote/legacy-opportunity ledger,
using each opportunity snapshot before the contact fallback. There is no second
revenue definition.

Aggregation is split into two grouped queries and one pure assembly function
(:func:`build_scoreboard`), mirroring
:func:`app.services.dashboard.lead_source_roi_service.assemble_roi_stats`, so
every division, boundary, and empty-denominator case is unit-testable with
fabricated aggregates and no database.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import distinct, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.db.scope import get_workspace_owned, select_workspace_owned
from app.models.contact import Contact
from app.models.referral_partner import ReferralPartner, ReferralPartnerType
from app.models.referral_partner_logo import ReferralPartnerLogo
from app.schemas.referral_partner import (
    DEFAULT_QUIET_AFTER_DAYS,
    ReferralPartnerListResponse,
    ReferralPartnerResponse,
    ReferralPartnerScoreboardResponse,
    ReferralPartnerScoreboardRow,
)
from app.services.lead_sources.exceptions import (
    ReferralPartnerContactNotFoundError,
    ReferralPartnerNameConflictError,
    ReferralPartnerNotFoundError,
)

SECONDS_PER_DAY = 86_400


@dataclass(frozen=True)
class PartnerReferralAggregate:
    """Raw per-partner counters, before any rate is derived.

    Attributes:
        partner_id: The partner these counters belong to.
        name: Partner display name.
        company: Partner's company, when known.
        partner_type: Relationship kind, for grouping.
        is_active: Whether the partner is still in the active roster.
        referrals_sent: Leads the partner sent (referred contacts).
        referrals_closed: Referred leads that produced at least one booked job.
            Bounded by ``referrals_sent`` when assembled, which keeps
            ``close_rate`` a real rate.
        jobs_closed: Booked jobs credited to the partner. Can exceed
            ``referrals_closed`` when one referred customer buys twice.
        total_revenue: Canonical booked revenue credited to the partner.
        last_referral_at: When the most recent referred lead arrived.
    """

    partner_id: uuid.UUID
    name: str
    company: str | None = None
    partner_type: ReferralPartnerType = ReferralPartnerType.OTHER
    is_active: bool = True
    referrals_sent: int = 0
    referrals_closed: int = 0
    jobs_closed: int = 0
    total_revenue: float = 0.0
    last_referral_at: datetime | None = None


def days_since(moment: datetime | None, now: datetime) -> int | None:
    """Whole days elapsed since ``moment``, or ``None`` when it never happened.

    Floors to whole days so the "quiet for N days" boundary is a clean integer
    comparison rather than a fractional one that flickers with the clock. A
    future-dated referral (clock skew, backdated import) floors to ``0`` instead
    of going negative, so it reads as "just now" rather than as ancient.
    """
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    elapsed = (now - moment).total_seconds()
    return max(int(elapsed // SECONDS_PER_DAY), 0)


def build_scoreboard_row(
    aggregate: PartnerReferralAggregate,
    *,
    now: datetime,
    quiet_after_days: int = DEFAULT_QUIET_AFTER_DAYS,
) -> ReferralPartnerScoreboardRow:
    """Derive one partner's rates from raw counters.

    Rates return ``None`` rather than ``0.0`` when their denominator is zero: a
    brand-new partner with no referrals has an *unknown* close rate, and showing
    "0%" would libel them on the owner's screen.
    """
    referrals_sent = max(aggregate.referrals_sent, 0)
    jobs_closed = max(aggregate.jobs_closed, 0)
    # A booked job whose contact link was severed cannot be traced back to a
    # specific referred lead, so it still counts in jobs/revenue but can never
    # push the rate past 100%.
    referrals_closed = min(max(aggregate.referrals_closed, 0), referrals_sent)
    revenue = round(max(aggregate.total_revenue, 0.0), 2)

    close_rate = round(referrals_closed / referrals_sent, 4) if referrals_sent > 0 else None
    average_job_value = round(revenue / jobs_closed, 2) if jobs_closed > 0 else None

    elapsed_days = days_since(aggregate.last_referral_at, now)
    gone_quiet = (
        referrals_sent > 0 and elapsed_days is not None and elapsed_days >= quiet_after_days
    )

    return ReferralPartnerScoreboardRow(
        partner_id=aggregate.partner_id,
        name=aggregate.name,
        company=aggregate.company,
        partner_type=aggregate.partner_type,
        is_active=aggregate.is_active,
        referrals_sent=referrals_sent,
        jobs_closed=jobs_closed,
        close_rate=close_rate,
        total_revenue=revenue,
        average_job_value=average_job_value,
        last_referral_at=aggregate.last_referral_at,
        days_since_last_referral=elapsed_days,
        is_gone_quiet=gone_quiet,
    )


def build_scoreboard(
    aggregates: list[PartnerReferralAggregate],
    *,
    now: datetime,
    quiet_after_days: int = DEFAULT_QUIET_AFTER_DAYS,
    gone_quiet_only: bool = False,
) -> ReferralPartnerScoreboardResponse:
    """Assemble and rank the scoreboard from raw per-partner counters.

    Pure function (no I/O) so the ranking, rate denominators, and gone-quiet
    boundary can be tested with fabricated aggregates.

    Ranked by booked revenue descending. Ties break on referral volume then
    name, so the order is deterministic instead of shuffling between requests.
    ``gone_quiet_only`` narrows the result to the call list — partners with at
    least one historical referral and nothing inside the window. Totals always
    describe the returned rows, so a filtered view never reports the whole
    network's revenue.
    """
    rows = [
        build_scoreboard_row(aggregate, now=now, quiet_after_days=quiet_after_days)
        for aggregate in aggregates
    ]
    if gone_quiet_only:
        rows = [row for row in rows if row.is_gone_quiet]

    rows.sort(key=lambda row: (-row.total_revenue, -row.referrals_sent, row.name.lower()))

    return ReferralPartnerScoreboardResponse(
        items=rows,
        total=len(rows),
        quiet_after_days=quiet_after_days,
        gone_quiet_only=gone_quiet_only,
        total_referrals_sent=sum(row.referrals_sent for row in rows),
        total_jobs_closed=sum(row.jobs_closed for row in rows),
        total_revenue=round(sum(row.total_revenue for row in rows), 2),
    )


class ReferralPartnerService:
    """Workspace-scoped CRUD and scoreboard reads for referral partners."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # --- CRUD --------------------------------------------------------------- #

    async def _get(self, partner_id: uuid.UUID, workspace_id: uuid.UUID) -> ReferralPartner:
        """Fetch a workspace-owned partner or raise a tenant-safe 404."""
        partner = await get_workspace_owned(self.db, ReferralPartner, partner_id, workspace_id)
        if partner is None:
            raise ReferralPartnerNotFoundError()
        return partner

    async def _assert_contact_in_workspace(
        self, contact_id: int | None, workspace_id: uuid.UUID
    ) -> None:
        """Reject linking a partner to another tenant's contact."""
        if contact_id is None:
            return
        if await get_workspace_owned(self.db, Contact, contact_id, workspace_id) is None:
            raise ReferralPartnerContactNotFoundError()

    async def _flush_unique(self) -> None:
        """Flush, translating the (workspace_id, name) unique violation."""
        try:
            await self.db.flush()
        except IntegrityError as exc:
            raise ReferralPartnerNameConflictError() from exc

    async def list(
        self,
        workspace_id: uuid.UUID,
        *,
        is_active: bool | None = None,
        partner_type: ReferralPartnerType | None = None,
    ) -> ReferralPartnerListResponse:
        """List partners, optionally filtered by active state or relationship."""
        criteria: list[ColumnElement[bool]] = []
        if is_active is not None:
            criteria.append(ReferralPartner.is_active.is_(is_active))
        if partner_type is not None:
            criteria.append(ReferralPartner.partner_type == partner_type)
        query = select_workspace_owned(ReferralPartner, workspace_id, *criteria).order_by(
            ReferralPartner.name
        )
        rows = (await self.db.execute(query)).scalars().all()
        items = [ReferralPartnerResponse.model_validate(row) for row in rows]
        return ReferralPartnerListResponse(items=items, total=len(items))

    async def get(self, partner_id: uuid.UUID, workspace_id: uuid.UUID) -> ReferralPartnerResponse:
        """Return one partner and lightweight logo presence metadata."""
        partner = await self._get(partner_id, workspace_id)
        has_logo = (
            await self.db.scalar(
                select(ReferralPartnerLogo.id).where(
                    ReferralPartnerLogo.referral_partner_id == partner.id,
                    ReferralPartnerLogo.workspace_id == workspace_id,
                )
            )
            is not None
        )
        return ReferralPartnerResponse.model_validate(partner).model_copy(
            update={"has_logo": has_logo}
        )

    async def create(
        self, workspace_id: uuid.UUID, data: dict[str, Any]
    ) -> ReferralPartnerResponse:
        """Create a partner, validating any linked contact stays in-tenant."""
        await self._assert_contact_in_workspace(data.get("contact_id"), workspace_id)
        partner = ReferralPartner(workspace_id=workspace_id, **data)
        self.db.add(partner)
        await self._flush_unique()
        await self.db.refresh(partner)
        return ReferralPartnerResponse.model_validate(partner)

    async def update(
        self, partner_id: uuid.UUID, workspace_id: uuid.UUID, data: dict[str, Any]
    ) -> ReferralPartnerResponse:
        """Apply a partial update to a partner."""
        partner = await self._get(partner_id, workspace_id)
        if "contact_id" in data:
            await self._assert_contact_in_workspace(data["contact_id"], workspace_id)
        for key, value in data.items():
            setattr(partner, key, value)
        await self._flush_unique()
        await self.db.refresh(partner)
        return ReferralPartnerResponse.model_validate(partner)

    async def delete(self, partner_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
        """Delete a partner. Referred leads/jobs keep their history (FK SET NULL)."""
        await self.db.delete(await self._get(partner_id, workspace_id))

    # --- Scoreboard --------------------------------------------------------- #

    async def _referral_counters(
        self, workspace_id: uuid.UUID
    ) -> dict[uuid.UUID, tuple[int, datetime | None]]:
        """Referrals sent and last referral date, per partner, in one query."""
        result = await self.db.execute(
            select(
                Contact.referral_partner_id,
                func.count(),
                func.max(Contact.created_at),
            )
            .where(
                Contact.workspace_id == workspace_id,
                Contact.referral_partner_id.is_not(None),
            )
            .group_by(Contact.referral_partner_id)
        )
        return {
            partner_id: (int(sent or 0), last_at)
            for partner_id, sent, last_at in result.all()
            if partner_id is not None
        }

    async def _booked_counters(
        self, workspace_id: uuid.UUID
    ) -> dict[uuid.UUID, tuple[int, float, int]]:
        """Canonical booked jobs, revenue, and converted leads, per partner."""
        # Local import avoids the eager reporting package import cycle through
        # quote/opportunity services during application startup.
        from app.services.reporting.booked_revenue import booked_revenue_events_query

        events = booked_revenue_events_query(
            workspace_id,
            date(1900, 1, 1),
            date(9998, 12, 31),
            timezone_name="UTC",
        ).subquery("referral_partner_bookings")
        result = await self.db.execute(
            select(
                events.c.referral_partner_id,
                func.count(events.c.event_id),
                func.coalesce(func.sum(events.c.amount), 0),
                func.count(distinct(events.c.contact_id)),
            )
            .where(events.c.referral_partner_id.is_not(None))
            .group_by(events.c.referral_partner_id)
        )
        return {
            partner_id: (int(jobs or 0), float(revenue or 0), int(converted or 0))
            for partner_id, jobs, revenue, converted in result.all()
            if partner_id is not None
        }

    async def scoreboard(
        self,
        workspace_id: uuid.UUID,
        *,
        quiet_after_days: int = DEFAULT_QUIET_AFTER_DAYS,
        gone_quiet_only: bool = False,
        is_active: bool | None = None,
        partner_type: ReferralPartnerType | None = None,
        now: datetime | None = None,
    ) -> ReferralPartnerScoreboardResponse:
        """Per-partner production, ranked by canonical booked revenue descending.

        Every partner in scope appears (at zero) unless ``gone_quiet_only``
        narrows the view, so a partner who has never referred is visible as
        someone to activate rather than missing entirely.
        """
        criteria: list[ColumnElement[bool]] = []
        if is_active is not None:
            criteria.append(ReferralPartner.is_active.is_(is_active))
        if partner_type is not None:
            criteria.append(ReferralPartner.partner_type == partner_type)
        partners = (
            (
                await self.db.execute(
                    select_workspace_owned(ReferralPartner, workspace_id, *criteria)
                )
            )
            .scalars()
            .all()
        )

        referrals = await self._referral_counters(workspace_id)
        booked = await self._booked_counters(workspace_id)

        aggregates = []
        for partner in partners:
            sent, last_at = referrals.get(partner.id, (0, None))
            jobs, revenue, converted = booked.get(partner.id, (0, 0.0, 0))
            aggregates.append(
                PartnerReferralAggregate(
                    partner_id=partner.id,
                    name=partner.name,
                    company=partner.company,
                    partner_type=partner.partner_type,
                    is_active=partner.is_active,
                    referrals_sent=sent,
                    referrals_closed=converted,
                    jobs_closed=jobs,
                    total_revenue=revenue,
                    last_referral_at=last_at,
                )
            )

        return build_scoreboard(
            aggregates,
            now=now or datetime.now(UTC),
            quiet_after_days=quiet_after_days,
            gone_quiet_only=gone_quiet_only,
        )
