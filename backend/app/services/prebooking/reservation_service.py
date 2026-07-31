"""Holding, pricing and confirming a pre-booking slot.

The shape of one booking, end to end:

1. **Hold** — a warm contact accepts the offer. The slot is claimed *first*,
   under a row lock on the campaign's config, because the crew calendar is the
   scarce thing; everything after that is paperwork that can be retried.
2. **Quote** — the discounted work is written as an ordinary
   :class:`~app.models.quote.Quote` carrying the offer's deposit terms, and sent,
   which allocates the public proposal token.
3. **Deposit** — the customer pays on the existing public proposal page. There is
   no second payment path: :mod:`app.services.payments.quote_deposit_service`
   owns the Stripe boundary and calls back here from ``mark_deposit_paid``.
4. **Confirm** — the reservation flips to ``confirmed`` and a **provisional job**
   is created so the pre-sold work lands in
   :meth:`app.services.reporting.capacity_service.CapacityService.compute_backlog`
   the moment the money does, instead of being invisible until spring.

Why the provisional job carries no scheduled window: ``backlog_hours`` sizes a
job by ``scheduled_end - scheduled_start`` when it has one. Stamping the whole
target season onto the job (say 1 March to 31 May) would report ~2 200 hours of
backlog for a four-hour house wash and make the gauge useless. The job is
therefore left ``unscheduled`` — which is what it honestly is, work sold with no
date — and counts at ``DEFAULT_JOB_HOURS`` like every other queued job. The
season it was sold into lives on the reservation
(``target_start_date``/``target_end_date``) and in the job title, where dispatch
can read it when the calendar is built.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.core.config import settings
from app.models.campaign import Campaign
from app.models.prebooking import (
    PreBookingCampaignConfig,
    PreBookingReservation,
    PreBookingReservationStatus,
)
from app.models.quote import Quote
from app.schemas.quote import QuoteCreate, QuoteLineItemCreate
from app.services.jobs.job_service import JobService
from app.services.payments.quote_deposit_service import deposit_amount as quote_deposit_amount
from app.services.prebooking.audience import PreBookingAudienceService
from app.services.prebooking.season import describe_season, resolve_season_window
from app.services.prebooking.slots import (
    SlotUsage,
    assemble_slot_usage,
    resolve_deposit_terms,
    resolve_incentive_amount,
)
from app.services.quotes import QuoteService

logger = structlog.get_logger()


class PreBookingError(Exception):
    """A pre-booking reservation could not be made."""


class SlotCapReachedError(PreBookingError):
    """Every slot in the target season is already held or confirmed."""


class ContactNotEligibleError(PreBookingError):
    """The contact opted out, or does not belong to this workspace."""


@dataclass(slots=True)
class HeldSlot:
    """A claimed slot plus the proposal the customer pays through."""

    reservation: PreBookingReservation
    quote: Quote
    deposit_amount: float
    proposal_url: str
    slots_remaining: int


def occupying_reservation_condition(now: datetime) -> ColumnElement[bool]:
    """Reservations that hold a slot at ``now``.

    A ``held`` row stops occupying its slot the instant its hold lapses, so an
    abandoned checkout frees capacity immediately rather than at whatever hour
    the sweep next runs.
    """
    return or_(
        PreBookingReservation.status == PreBookingReservationStatus.CONFIRMED,
        and_(
            PreBookingReservation.status == PreBookingReservationStatus.HELD,
            PreBookingReservation.hold_expires_at > now,
        ),
    )


class PreBookingReservationService:
    """Workspace-scoped slot holding and confirmation."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.log = logger.bind(service="prebooking")

    # ------------------------------------------------------------------ #
    # Slot accounting
    # ------------------------------------------------------------------ #
    async def slot_usage(
        self,
        config: PreBookingCampaignConfig,
        *,
        now: datetime | None = None,
    ) -> SlotUsage:
        """Count live holds and confirmations against the cap."""
        moment = now or datetime.now(UTC)
        rows = (
            await self.db.execute(
                select(PreBookingReservation.status, func.count())
                .where(
                    PreBookingReservation.config_id == config.id,
                    occupying_reservation_condition(moment),
                )
                .group_by(PreBookingReservation.status)
            )
        ).all()
        counts = {status: int(count) for status, count in rows}
        return assemble_slot_usage(
            cap=config.slot_cap,
            held=counts.get(PreBookingReservationStatus.HELD, 0),
            confirmed=counts.get(PreBookingReservationStatus.CONFIRMED, 0),
        )

    # ------------------------------------------------------------------ #
    # Hold
    # ------------------------------------------------------------------ #
    async def hold_slot(
        self,
        workspace_id: uuid.UUID,
        config: PreBookingCampaignConfig,
        *,
        contact_id: int,
        source_quote_id: uuid.UUID | None = None,
        base_amount: float | None = None,
        service_location_id: uuid.UUID | None = None,
        notes: str | None = None,
        created_by_id: int | None = None,
    ) -> HeldSlot:
        """Claim a slot for one contact and issue the deposit-bearing quote.

        Raises :class:`SlotCapReachedError` when the season is full and
        :class:`ContactNotEligibleError` when the contact opted out between the send
        and the click — the one check worth repeating, because the alternative is
        taking money from someone who told us to stop.
        """
        if not await PreBookingAudienceService(self.db).is_eligible(workspace_id, contact_id):
            raise ContactNotEligibleError(
                "This contact is not reachable for this workspace (opted out or not found)."
            )

        existing = await self._active_reservation(config.id, contact_id)
        if existing is not None:
            # A double-click, or a customer returning to a link they never paid.
            # Hand back the same slot and the same proposal rather than eating a
            # second one.
            return await self._existing_slot(config, existing)

        reservation = await self._claim_slot(workspace_id, config, contact_id=contact_id)

        try:
            quote = await self._issue_quote(
                workspace_id,
                config,
                reservation,
                contact_id=contact_id,
                source_quote_id=source_quote_id,
                base_amount=base_amount,
                service_location_id=service_location_id,
                notes=notes,
                created_by_id=created_by_id,
            )
        except Exception:
            # The slot is only worth holding if the customer can actually pay for
            # it. Give it straight back rather than leaving a phantom booking.
            # Re-fetched by id: whatever failed may have left the session rolled
            # back, which expires the instance we are holding.
            await self._release(reservation.id, reason="quote_failed")
            raise

        usage = await self.slot_usage(config)
        self.log.info(
            "prebooking_slot_held",
            workspace_id=str(workspace_id),
            campaign_id=str(config.campaign_id),
            reservation_id=str(reservation.id),
            quote_id=str(quote.id),
            slots_remaining=usage.remaining,
        )
        return HeldSlot(
            reservation=reservation,
            quote=quote,
            deposit_amount=float(reservation.deposit_amount or 0),
            proposal_url=_proposal_url(quote),
            slots_remaining=usage.remaining,
        )

    async def _claim_slot(
        self,
        workspace_id: uuid.UUID,
        config: PreBookingCampaignConfig,
        *,
        contact_id: int,
    ) -> PreBookingReservation:
        """Insert the ``held`` row under a lock on the config row.

        The lock is what makes the cap a guarantee: two customers paying in the
        same second serialize here, so the second one is told the season is full
        instead of both taking the last slot. It is released by the commit at the
        end of this method — deliberately *before* the quote is written, because
        the quote service runs its own transactions and holding a lock across
        them would serialize every booking behind Stripe and email latency.
        """
        now = datetime.now(UTC)
        locked = (
            await self.db.execute(
                select(PreBookingCampaignConfig)
                .where(PreBookingCampaignConfig.id == config.id)
                .with_for_update()
            )
        ).scalar_one()

        # Read every field this method needs *before* any rollback. A rollback
        # expires the loaded instance, and touching an expired attribute later
        # emits a lazy SELECT from sync context, which raises MissingGreenlet
        # under asyncio rather than doing the obvious thing.
        config_id = locked.id
        campaign_id = locked.campaign_id
        cap = locked.slot_cap
        hold_hours = locked.hold_hours
        window = resolve_season_window(
            start_month=locked.service_season_start_month,
            end_month=locked.service_season_end_month,
            year=locked.service_season_year,
        )

        usage = await self.slot_usage(locked, now=now)
        if usage.is_full:
            await self._release_lock(config_id)
            raise SlotCapReachedError(
                f"All {cap} slots for this season are taken. "
                "Raise the cap or point the customer at the next window."
            )

        reservation = PreBookingReservation(
            workspace_id=workspace_id,
            config_id=config_id,
            campaign_id=campaign_id,
            contact_id=contact_id,
            status=PreBookingReservationStatus.HELD,
            target_start_date=window.start,
            target_end_date=window.end,
            held_at=now,
            hold_expires_at=now + timedelta(hours=hold_hours),
        )
        self.db.add(reservation)
        try:
            await self.db.commit()
        except IntegrityError as exc:
            # The partial-unique index caught a concurrent double-click.
            await self._release_lock(config_id)
            existing = await self._active_reservation(config_id, contact_id)
            if existing is None:
                raise
            self.log.info(
                "prebooking_duplicate_hold_ignored",
                reservation_id=str(existing.id),
                error=str(exc),
            )
            return existing
        await self.db.refresh(reservation)
        return reservation

    async def _issue_quote(
        self,
        workspace_id: uuid.UUID,
        config: PreBookingCampaignConfig,
        reservation: PreBookingReservation,
        *,
        contact_id: int,
        source_quote_id: uuid.UUID | None,
        base_amount: float | None,
        service_location_id: uuid.UUID | None,
        notes: str | None,
        created_by_id: int | None,
    ) -> Quote:
        """Write the discounted, deposit-bearing quote and send it.

        Goes through :class:`~app.services.quotes.QuoteService` rather than
        building a ``Quote`` by hand, so numbering, total recomputation, the
        client proposal link and the deposit flow all apply unchanged.
        """
        line_items = await self._resolve_line_items(
            workspace_id,
            config,
            source_quote_id=source_quote_id,
            base_amount=base_amount,
        )
        subtotal = round(sum(item.quantity * item.unit_price for item in line_items), 2)
        incentive = resolve_incentive_amount(
            incentive_type=config.incentive_type,
            incentive_value=float(config.incentive_value),
            subtotal=subtotal,
        )
        deposit_percentage, deposit_fixed = resolve_deposit_terms(
            deposit_type=config.deposit_type,
            deposit_value=float(config.deposit_value),
        )
        season_label = describe_season(
            start_month=config.service_season_start_month,
            end_month=config.service_season_end_month,
            year=config.service_season_year,
        )

        service = QuoteService(self.db)
        detail = await service.create_quote(
            workspace_id,
            QuoteCreate(
                contact_id=contact_id,
                service_location_id=service_location_id,
                title=f"{config.service_description} — {season_label}",
                discount_amount=incentive,
                deposit_percentage=deposit_percentage,
                deposit_amount_fixed=deposit_fixed,
                issue_date=reservation.held_at.date(),
                # The price is guaranteed exactly as long as the slot is.
                expiry_date=reservation.hold_expires_at.date(),
                notes=_quote_notes(season_label, reservation, notes),
                line_items=line_items,
            ),
            created_by_id=created_by_id,
        )
        # Sending allocates the public proposal token and emails the customer the
        # link they pay the deposit through (best-effort, as everywhere else).
        await service.mark_sent(workspace_id, detail.id)

        quote = (await self.db.execute(select(Quote).where(Quote.id == detail.id))).scalar_one()

        reservation.quote_id = quote.id
        reservation.quoted_total = float(quote.total)
        reservation.incentive_amount = incentive
        reservation.deposit_amount = quote_deposit_amount(quote) or 0.0
        await self.db.commit()
        await self.db.refresh(reservation)
        return quote

    async def _resolve_line_items(
        self,
        workspace_id: uuid.UUID,
        config: PreBookingCampaignConfig,
        *,
        source_quote_id: uuid.UUID | None,
        base_amount: float | None,
    ) -> list[QuoteLineItemCreate]:
        """Price the work: copy last year's unsold quote, or use a flat amount.

        Copying the source quote's lines is the point of aiming this at unsold
        quotes — the customer sees the job they already asked about, at a better
        price, rather than a mystery number.
        """
        if source_quote_id is not None:
            source = (
                await self.db.execute(
                    select(Quote)
                    .where(Quote.id == source_quote_id, Quote.workspace_id == workspace_id)
                    .options(selectinload(Quote.line_items))
                )
            ).scalar_one_or_none()
            if source is None:
                raise PreBookingError("Source quote not found in this workspace.")
            if source.line_items:
                return [
                    QuoteLineItemCreate(
                        name=item.name,
                        description=item.description,
                        quantity=float(item.quantity),
                        unit_price=float(item.unit_price),
                        discount=0,
                    )
                    for item in source.line_items
                ]
            base_amount = base_amount if base_amount is not None else float(source.total)

        if base_amount is None or base_amount <= 0:
            raise PreBookingError("A pre-booking quote needs a price.")

        return [
            QuoteLineItemCreate(
                name=config.service_description,
                description=None,
                quantity=1,
                unit_price=round(float(base_amount), 2),
                discount=0,
            )
        ]

    # ------------------------------------------------------------------ #
    # Confirm
    # ------------------------------------------------------------------ #
    async def confirm_reservation_for_quote(self, quote: Quote) -> PreBookingReservation | None:
        """Confirm the reservation a paid deposit belongs to, if any.

        Called from :func:`app.services.payments.quote_deposit_service.mark_deposit_paid`
        on the single transition to paid, so both the Stripe webhook and the
        return-from-checkout backstop land here exactly once. Idempotent: a
        reservation that already has its job keeps it.

        The cap is deliberately **not** re-checked. It gates who may start
        paying; once money has been taken the booking is honoured, even if the
        hold lapsed while the customer was in Stripe. An over-cap season is a
        scheduling conversation — a refused payment is a lost customer.
        """
        reservation = (
            await self.db.execute(
                select(PreBookingReservation)
                .where(
                    PreBookingReservation.quote_id == quote.id,
                    PreBookingReservation.status.in_(
                        (
                            PreBookingReservationStatus.HELD,
                            PreBookingReservationStatus.CONFIRMED,
                        )
                    ),
                )
                .options(selectinload(PreBookingReservation.config))
            )
        ).scalar_one_or_none()
        if reservation is None:
            return None
        if reservation.job_id is not None:
            return reservation

        config = reservation.config
        season_label = describe_season(
            start_month=config.service_season_start_month,
            end_month=config.service_season_end_month,
            year=config.service_season_year,
        )
        job = await JobService(self.db).create(
            reservation.workspace_id,
            {
                "contact_id": reservation.contact_id,
                "service_location_id": quote.service_location_id,
                "title": f"{config.service_description} — {season_label}",
                "description": (
                    f"Pre-booked from campaign quote {quote.number}. Deposit paid; "
                    f"schedule between {reservation.target_start_date.isoformat()} and "
                    f"{reservation.target_end_date.isoformat()}."
                ),
                # No window on purpose — see the module docstring. The job is
                # sold work with no date, which is exactly ``unscheduled``.
                "technician_ids": [],
            },
        )

        reservation.status = PreBookingReservationStatus.CONFIRMED
        reservation.confirmed_at = datetime.now(UTC)
        reservation.job_id = job.id
        # Recording the job on the quote keeps a later approve -> convert
        # idempotent: the conversion sees a job already exists and links it
        # rather than creating a second work order for the same driveway.
        quote.converted_job_id = job.id
        await self.db.commit()

        self.log.info(
            "prebooking_reservation_confirmed",
            reservation_id=str(reservation.id),
            quote_id=str(quote.id),
            job_id=str(job.id),
            target_start=reservation.target_start_date.isoformat(),
        )
        return reservation

    # ------------------------------------------------------------------ #
    # Housekeeping
    # ------------------------------------------------------------------ #
    async def release_expired_holds(self, *, now: datetime | None = None) -> int:
        """Mark lapsed holds ``released``. Returns how many were swept.

        Slot counting already ignores a lapsed hold, so this is bookkeeping
        rather than enforcement: it keeps the reservation list honest for the
        operator reading it, and stops an old hold blocking the same customer
        from booking again through the partial-unique index.
        """
        moment = now or datetime.now(UTC)
        result = await self.db.execute(
            update(PreBookingReservation)
            .where(
                PreBookingReservation.status == PreBookingReservationStatus.HELD,
                PreBookingReservation.hold_expires_at <= moment,
            )
            .values(
                status=PreBookingReservationStatus.RELEASED,
                released_at=moment,
                release_reason="hold_expired",
            )
        )
        await self.db.commit()
        return int(result.rowcount or 0)  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    async def _release_lock(self, config_id: uuid.UUID) -> None:
        """End the locking transaction and make the config readable again.

        ``rollback`` is what releases the ``FOR UPDATE`` lock, but it also expires
        every instance in the session — including the ``config`` the *caller*
        still holds. Re-loading it means a refused booking hands back a usable
        object instead of an attribute access that tries to emit sync IO from an
        async context.
        """
        await self.db.rollback()
        await self.db.get(PreBookingCampaignConfig, config_id)

    async def _active_reservation(
        self, config_id: uuid.UUID, contact_id: int
    ) -> PreBookingReservation | None:
        return (
            await self.db.execute(
                select(PreBookingReservation).where(
                    PreBookingReservation.config_id == config_id,
                    PreBookingReservation.contact_id == contact_id,
                    PreBookingReservation.status.in_(
                        (
                            PreBookingReservationStatus.HELD,
                            PreBookingReservationStatus.CONFIRMED,
                        )
                    ),
                )
            )
        ).scalar_one_or_none()

    async def _existing_slot(
        self,
        config: PreBookingCampaignConfig,
        reservation: PreBookingReservation,
    ) -> HeldSlot:
        quote = (
            await self.db.execute(select(Quote).where(Quote.id == reservation.quote_id))
        ).scalar_one_or_none()
        if quote is None:
            raise PreBookingError("This contact already holds a slot without a quote.")
        usage = await self.slot_usage(config)
        return HeldSlot(
            reservation=reservation,
            quote=quote,
            deposit_amount=float(reservation.deposit_amount or 0),
            proposal_url=_proposal_url(quote),
            slots_remaining=usage.remaining,
        )

    async def _release(self, reservation_id: uuid.UUID, *, reason: str) -> None:
        """Give a slot back. Best-effort: never masks the failure that caused it."""
        try:
            await self.db.rollback()
            await self.db.execute(
                update(PreBookingReservation)
                .where(PreBookingReservation.id == reservation_id)
                .values(
                    status=PreBookingReservationStatus.RELEASED,
                    released_at=datetime.now(UTC),
                    release_reason=reason,
                )
            )
            await self.db.commit()
        except Exception:
            self.log.warning(
                "prebooking_release_failed",
                reservation_id=str(reservation_id),
                reason=reason,
                exc_info=True,
            )


async def load_config_for_campaign(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
) -> PreBookingCampaignConfig | None:
    """Load a campaign's pre-booking offer, scoped to its workspace."""
    return (
        await db.execute(
            select(PreBookingCampaignConfig)
            .join(Campaign, Campaign.id == PreBookingCampaignConfig.campaign_id)
            .where(
                PreBookingCampaignConfig.campaign_id == campaign_id,
                PreBookingCampaignConfig.workspace_id == workspace_id,
            )
        )
    ).scalar_one_or_none()


def _proposal_url(quote: Quote) -> str:
    """Public client-proposal URL for a quote (where the deposit is paid)."""
    return f"{settings.frontend_url}/p/quotes/{quote.public_token}"


def _quote_notes(
    season_label: str,
    reservation: PreBookingReservation,
    operator_notes: str | None,
) -> str:
    """Customer-facing note explaining what the deposit buys."""
    base = (
        f"Pre-booked for {season_label}. Your deposit locks this price and holds "
        f"a spot on the {season_label} schedule; we'll call you to pick an exact "
        f"date closer to the season. Hold expires "
        f"{reservation.hold_expires_at.date().isoformat()}."
    )
    return f"{base}\n\n{operator_notes}" if operator_notes else base
