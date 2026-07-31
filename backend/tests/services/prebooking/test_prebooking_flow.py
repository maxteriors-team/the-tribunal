"""Real-DB integration tests for the pre-booking flow.

The four things that must be true for a pre-booking campaign to be trustworthy
with a customer's money and a crew's calendar:

1. the **slot cap** is a hard stop, not a suggestion;
2. every issued quote carries the offer's **deposit** and its discount;
3. a paid deposit produces a **provisional job** that shows up in backlog;
4. the **audience never includes someone who opted out**.

Marked ``integration`` and deselected by default; run with ``pytest -m integration``.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import hash_phone, hash_value
from app.db.session import AsyncSessionLocal
from app.models.campaign import Campaign, CampaignContact, CampaignType
from app.models.contact import Contact
from app.models.field_service import Job, JobStatus
from app.models.opt_out import GlobalOptOut
from app.models.prebooking import (
    PreBookingAmountType,
    PreBookingCampaignConfig,
    PreBookingReservation,
    PreBookingReservationStatus,
)
from app.models.quote import Quote
from app.models.recurring_job import (
    RecurrenceFrequency,
    RecurringJobTemplate,
    ServicePlanType,
)
from app.models.workspace import Workspace
from app.schemas.pricing import ChristmasConfig
from app.schemas.quote import QuoteCreate, QuoteLineItemCreate
from app.services.payments import quote_deposit_service as deposit
from app.services.prebooking.audience import PreBookingAudienceService
from app.services.prebooking.reservation_service import (
    PreBookingReservationService,
    SlotCapReachedError,
)
from app.services.quotes import QuoteService
from app.services.reporting.capacity_service import CapacityService
from app.services.seasonal import current_season

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


# --------------------------------------------------------------------------- #
# Fixtures-by-hand (this package has no ORM factories; see tests/factories.py)
# --------------------------------------------------------------------------- #
async def _make_workspace(db: AsyncSession) -> Workspace:
    ws = Workspace(
        id=uuid.uuid4(),
        name="Maxteriors Exteriors",
        slug=f"prebook-{uuid.uuid4().hex[:8]}",
        settings={},
    )
    db.add(ws)
    await db.flush()
    return ws


async def _make_contact(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    sms_consent_status: str = "opted_in",
) -> Contact:
    phone = f"+1555{uuid.uuid4().int % 10_000_000:07d}"
    email = f"owner-{uuid.uuid4().hex[:8]}@example.com"
    contact = Contact(
        workspace_id=workspace_id,
        first_name="Dana",
        last_name="Homeowner",
        phone_number=phone,
        phone_hash=hash_phone(phone),
        email=email,
        email_hash=hash_value(email),
        sms_consent_status=sms_consent_status,
    )
    db.add(contact)
    await db.flush()
    return contact


async def _make_campaign(db: AsyncSession, workspace_id: uuid.UUID) -> Campaign:
    campaign = Campaign(
        workspace_id=workspace_id,
        name="Spring 2027 pre-book",
        campaign_type=CampaignType.SMS,
        from_phone_number="+15550001111",
        initial_message="Lock in spring now, {first_name}",
    )
    db.add(campaign)
    await db.flush()
    return campaign


async def _make_offer(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    *,
    slot_cap: int = 2,
    incentive_value: float = 15,
    deposit_value: float = 25,
    hold_hours: int = 72,
) -> PreBookingCampaignConfig:
    config = PreBookingCampaignConfig(
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        service_season_start_month=3,
        service_season_end_month=5,
        service_season_year=datetime.now(UTC).year + 1,
        service_description="Spring house wash + gutter clean",
        incentive_type=PreBookingAmountType.PERCENTAGE,
        incentive_value=incentive_value,
        deposit_type=PreBookingAmountType.PERCENTAGE,
        deposit_value=deposit_value,
        slot_cap=slot_cap,
        hold_hours=hold_hours,
    )
    db.add(config)
    await db.flush()
    return config


async def _campaign_with_offer(
    db: AsyncSession, **offer_kwargs: object
) -> tuple[Workspace, Campaign, PreBookingCampaignConfig]:
    ws = await _make_workspace(db)
    campaign = await _make_campaign(db, ws.id)
    config = await _make_offer(db, ws.id, campaign.id, **offer_kwargs)  # type: ignore[arg-type]
    return ws, campaign, config


# --------------------------------------------------------------------------- #
# 1. Slot cap
# --------------------------------------------------------------------------- #
async def test_slot_cap_refuses_the_customer_after_the_last_slot() -> None:
    """The cap is the crew calendar's only defence against a good week of sales."""
    async with AsyncSessionLocal() as db:
        ws, _campaign, config = await _campaign_with_offer(db, slot_cap=1)
        first = await _make_contact(db, ws.id)
        second = await _make_contact(db, ws.id)
        service = PreBookingReservationService(db)

        held = await service.hold_slot(ws.id, config, contact_id=first.id, base_amount=450)
        assert held.reservation.status is PreBookingReservationStatus.HELD
        assert held.slots_remaining == 0

        with pytest.raises(SlotCapReachedError, match="All 1 slots"):
            await service.hold_slot(ws.id, config, contact_id=second.id, base_amount=450)

        usage = await service.slot_usage(config)
        assert usage.held == 1
        assert usage.is_full is True
        assert usage.oversold == 0

        # The refused customer left no wreckage behind.
        rows = (
            (
                await db.execute(
                    select(PreBookingReservation).where(
                        PreBookingReservation.config_id == config.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1


async def test_the_same_contact_clicking_twice_does_not_eat_two_slots() -> None:
    async with AsyncSessionLocal() as db:
        ws, _campaign, config = await _campaign_with_offer(db, slot_cap=2)
        contact = await _make_contact(db, ws.id)
        service = PreBookingReservationService(db)

        first = await service.hold_slot(ws.id, config, contact_id=contact.id, base_amount=450)
        again = await service.hold_slot(ws.id, config, contact_id=contact.id, base_amount=450)

        assert again.reservation.id == first.reservation.id
        assert again.quote.id == first.quote.id
        assert (await service.slot_usage(config)).occupied == 1


async def test_two_customers_paying_at_once_cannot_both_take_the_last_slot() -> None:
    """The row lock, not the counting, is what makes the cap a guarantee.

    Sequential enforcement is easy; this is the case that actually costs a
    Saturday if it is wrong — two clicks landing in the same instant on separate
    connections.
    """
    async with AsyncSessionLocal() as setup:
        ws, _campaign, config = await _campaign_with_offer(setup, slot_cap=1)
        first = await _make_contact(setup, ws.id)
        second = await _make_contact(setup, ws.id)
        await setup.commit()
        workspace_id, config_id = ws.id, config.id
        contact_ids = (first.id, second.id)

    async def _race(contact_id: int) -> str:
        async with AsyncSessionLocal() as db:
            offer = await db.get(PreBookingCampaignConfig, config_id)
            assert offer is not None
            try:
                await PreBookingReservationService(db).hold_slot(
                    workspace_id, offer, contact_id=contact_id, base_amount=450
                )
            except SlotCapReachedError:
                return "refused"
            return "held"

    outcomes = await asyncio.gather(*(_race(cid) for cid in contact_ids))
    assert sorted(outcomes) == ["held", "refused"]

    async with AsyncSessionLocal() as db:
        offer = await db.get(PreBookingCampaignConfig, config_id)
        assert offer is not None
        usage = await PreBookingReservationService(db).slot_usage(offer)
        assert usage.occupied == 1
        assert usage.oversold == 0


async def test_a_lapsed_hold_gives_its_slot_back() -> None:
    """An abandoned checkout must not hold a May slot until May."""
    async with AsyncSessionLocal() as db:
        ws, _campaign, config = await _campaign_with_offer(db, slot_cap=1)
        ghost = await _make_contact(db, ws.id)
        buyer = await _make_contact(db, ws.id)
        service = PreBookingReservationService(db)

        stale = await service.hold_slot(ws.id, config, contact_id=ghost.id, base_amount=450)
        stale.reservation.hold_expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()

        # Counted as free the instant it lapses — no sweep required.
        assert (await service.slot_usage(config)).is_full is False
        resold = await service.hold_slot(ws.id, config, contact_id=buyer.id, base_amount=450)
        assert resold.reservation.id != stale.reservation.id

        swept = await service.release_expired_holds()
        assert swept >= 1
        refreshed = await db.get(PreBookingReservation, stale.reservation.id)
        assert refreshed is not None
        assert refreshed.status is PreBookingReservationStatus.RELEASED
        assert refreshed.release_reason == "hold_expired"


# --------------------------------------------------------------------------- #
# 2. Deposit terms ride the existing quote deposit flow
# --------------------------------------------------------------------------- #
async def test_the_issued_quote_carries_the_discount_and_the_deposit() -> None:
    async with AsyncSessionLocal() as db:
        ws, _campaign, config = await _campaign_with_offer(db, incentive_value=15, deposit_value=25)
        contact = await _make_contact(db, ws.id)

        held = await PreBookingReservationService(db).hold_slot(
            ws.id, config, contact_id=contact.id, base_amount=450
        )

        quote = held.quote
        # $450 less the 15% early-booking discount.
        assert float(quote.discount_amount) == 67.5
        assert float(quote.total) == 382.5
        # A deposit is owed under the offer's terms, and it is the *existing*
        # quote deposit path that will collect it.
        assert float(quote.deposit_percentage) == 25.0
        assert quote.deposit_amount_fixed is None
        assert deposit.deposit_amount(quote) == 95.62
        assert held.deposit_amount == 95.62
        # Sent, so the public proposal page (and its Stripe checkout) resolves.
        assert quote.status == "sent"
        assert quote.public_token is not None
        assert held.proposal_url.endswith(quote.public_token)

        reservation = held.reservation
        assert float(reservation.quoted_total) == 382.5
        assert float(reservation.incentive_amount) == 67.5
        assert float(reservation.deposit_amount) == 95.62
        assert reservation.target_start_date.month == 3
        assert reservation.target_end_date.month == 5


async def test_a_fixed_deposit_maps_onto_the_quotes_fixed_field() -> None:
    async with AsyncSessionLocal() as db:
        ws, campaign, _config = await _campaign_with_offer(db)
        config = await db.get(PreBookingCampaignConfig, _config.id)
        assert config is not None
        config.deposit_type = PreBookingAmountType.FIXED
        config.deposit_value = 99
        await db.commit()
        contact = await _make_contact(db, ws.id)

        held = await PreBookingReservationService(db).hold_slot(
            ws.id, config, contact_id=contact.id, base_amount=450
        )
        assert held.quote.deposit_percentage is None
        assert float(held.quote.deposit_amount_fixed) == 99.0
        assert held.deposit_amount == 99.0
        assert campaign.id == held.reservation.campaign_id


async def test_last_years_unsold_quote_is_re_offered_at_the_discount() -> None:
    """Aiming at unsold quotes only pays off if the customer recognises the job."""
    async with AsyncSessionLocal() as db:
        ws, _campaign, config = await _campaign_with_offer(db)
        contact = await _make_contact(db, ws.id)
        source = await QuoteService(db).create_quote(
            ws.id,
            QuoteCreate(
                contact_id=contact.id,
                title="Last spring's estimate",
                line_items=[
                    QuoteLineItemCreate(name="House wash", quantity=1, unit_price=400.0),
                    QuoteLineItemCreate(name="Gutter clean", quantity=1, unit_price=200.0),
                ],
            ),
        )

        held = await PreBookingReservationService(db).hold_slot(
            ws.id, config, contact_id=contact.id, source_quote_id=source.id
        )

        lines = (
            (
                await db.execute(
                    select(Quote)
                    .where(Quote.id == held.quote.id)
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .one()
        )
        assert float(lines.subtotal) == 600.0
        assert float(lines.discount_amount) == 90.0  # 15% of 600
        assert float(lines.total) == 510.0


# --------------------------------------------------------------------------- #
# 3. A paid deposit becomes a provisional job in backlog
# --------------------------------------------------------------------------- #
async def test_paid_deposit_confirms_the_slot_and_queues_a_provisional_job() -> None:
    async with AsyncSessionLocal() as db:
        ws, _campaign, config = await _campaign_with_offer(db)
        contact = await _make_contact(db, ws.id)
        service = PreBookingReservationService(db)
        held = await service.hold_slot(ws.id, config, contact_id=contact.id, base_amount=450)

        # Exactly what the Stripe webhook does.
        transitioned = await deposit.mark_deposit_paid(db, held.quote, payment_intent_id="pi_123")
        assert transitioned is True

        reservation = await db.get(PreBookingReservation, held.reservation.id)
        assert reservation is not None
        await db.refresh(reservation)
        assert reservation.status is PreBookingReservationStatus.CONFIRMED
        assert reservation.confirmed_at is not None
        assert reservation.job_id is not None

        job = await db.get(Job, reservation.job_id)
        assert job is not None
        # Sold work with no date is exactly ``unscheduled`` — and a job with no
        # window is sized by the backlog report's default rather than by a
        # three-month season, which would report thousands of phantom hours.
        assert job.status is JobStatus.UNSCHEDULED
        assert job.scheduled_start is None
        assert job.scheduled_end is None
        assert job.contact_id == contact.id
        assert "Spring house wash" in job.title
        assert reservation.target_start_date.isoformat() in (job.description or "")

        # The conversion chain stays auditable and a later approve->convert will
        # reuse this job instead of creating a second one.
        assert held.quote.converted_job_id == job.id


async def test_confirming_twice_does_not_create_a_second_job() -> None:
    """Stripe retries webhooks; the reconcile backstop fires on return, too."""
    async with AsyncSessionLocal() as db:
        ws, _campaign, config = await _campaign_with_offer(db)
        contact = await _make_contact(db, ws.id)
        service = PreBookingReservationService(db)
        held = await service.hold_slot(ws.id, config, contact_id=contact.id, base_amount=450)

        await deposit.mark_deposit_paid(db, held.quote)
        assert await deposit.mark_deposit_paid(db, held.quote) is False
        await service.confirm_reservation_for_quote(held.quote)

        jobs = (await db.execute(select(Job).where(Job.workspace_id == ws.id))).scalars().all()
        assert len(jobs) == 1


async def test_provisional_jobs_are_counted_in_backlog_weeks() -> None:
    """The whole point: pre-sold work must show on the fuel gauge immediately."""
    async with AsyncSessionLocal() as db:
        ws, _campaign, config = await _campaign_with_offer(db, slot_cap=3)
        service = PreBookingReservationService(db)

        before = await CapacityService(db).compute_backlog(ws.id, weekly_capacity_hours=40)
        assert before.job_count == 0
        assert before.backlog_weeks == 0.0

        for _ in range(2):
            contact = await _make_contact(db, ws.id)
            held = await service.hold_slot(ws.id, config, contact_id=contact.id, base_amount=450)
            await deposit.mark_deposit_paid(db, held.quote)

        after = await CapacityService(db).compute_backlog(ws.id, weekly_capacity_hours=40)
        assert after.job_count == 2
        assert after.unscheduled_job_count == 2
        # Sized at the report's default (4h) because the work has no window yet,
        # and flagged as assumed so the operator knows which part is a guess.
        assert after.assumed_duration_job_count == 2
        assert after.backlog_hours == 8.0
        assert after.backlog_weeks == 0.2


async def test_an_unpaid_hold_stays_out_of_backlog() -> None:
    """A hold is a promise, not sold work. Only money puts it on the gauge."""
    async with AsyncSessionLocal() as db:
        ws, _campaign, config = await _campaign_with_offer(db)
        contact = await _make_contact(db, ws.id)
        await PreBookingReservationService(db).hold_slot(
            ws.id, config, contact_id=contact.id, base_amount=450
        )

        report = await CapacityService(db).compute_backlog(ws.id, weekly_capacity_hours=40)
        assert report.job_count == 0


# --------------------------------------------------------------------------- #
# 4. Audience
# --------------------------------------------------------------------------- #
async def _past_customer(db: AsyncSession, ws: Workspace, **kwargs: object) -> Contact:
    contact = await _make_contact(db, ws.id, **kwargs)  # type: ignore[arg-type]
    db.add(
        Job(
            workspace_id=ws.id,
            contact_id=contact.id,
            title="Last autumn's gutter clean",
            status=JobStatus.COMPLETED,
        )
    )
    await db.flush()
    return contact


async def _unsold_quote_holder(db: AsyncSession, ws: Workspace, **kwargs: object) -> Contact:
    contact = await _make_contact(db, ws.id, **kwargs)  # type: ignore[arg-type]
    created = await QuoteService(db).create_quote(
        ws.id,
        QuoteCreate(
            contact_id=contact.id,
            title="Never got back to us",
            line_items=[QuoteLineItemCreate(name="House wash", quantity=1, unit_price=400.0)],
        ),
    )
    await QuoteService(db).mark_sent(ws.id, created.id)
    return contact


async def test_audience_excludes_opted_out_contacts() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        campaign = await _make_campaign(db, ws.id)

        reachable_customer = await _past_customer(db, ws)
        reachable_quote = await _unsold_quote_holder(db, ws)
        # 1. Consent withdrawn on the contact record.
        consent_revoked = await _past_customer(db, ws, sms_consent_status="opted_out")
        # 2. Texted STOP — a workspace-wide suppression keyed on the phone hash.
        texted_stop = await _past_customer(db, ws)
        db.add(
            GlobalOptOut(
                workspace_id=ws.id,
                phone_number=texted_stop.phone_number,
                opt_out_keyword="STOP",
            )
        )
        # 3. Clicked unsubscribe in an email — recorded on that enrollment.
        unsubscribed = await _unsold_quote_holder(db, ws)
        other_campaign = await _make_campaign(db, ws.id)
        db.add(
            CampaignContact(
                campaign_id=other_campaign.id,
                contact_id=unsubscribed.id,
                opted_out=True,
                opted_out_at=datetime.now(UTC),
            )
        )
        # A cold contact: no job, no quote. Warm-only means warm-only.
        cold = await _make_contact(db, ws.id)
        await db.commit()

        service = PreBookingAudienceService(db)
        ids = await service.resolve_contact_ids(ws.id, campaign.id)

        assert set(ids) == {reachable_customer.id, reachable_quote.id}
        for excluded in (consent_revoked, texted_stop, unsubscribed, cold):
            assert excluded.id not in ids

        counts = await service.preview(ws.id, campaign.id)
        assert counts.total == 2
        assert counts.excluded_opted_out == 3
        assert counts.excluded_already_enrolled == 0

        # And the per-contact gate agrees with the set-based one.
        assert await service.is_eligible(ws.id, reachable_customer.id) is True
        assert await service.is_eligible(ws.id, texted_stop.id) is False
        assert await service.is_eligible(ws.id, consent_revoked.id) is False


async def test_audience_skips_contacts_already_enrolled_in_this_campaign() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        campaign = await _make_campaign(db, ws.id)
        enrolled = await _past_customer(db, ws)
        fresh = await _past_customer(db, ws)
        db.add(CampaignContact(campaign_id=campaign.id, contact_id=enrolled.id))
        await db.commit()

        service = PreBookingAudienceService(db)
        assert await service.resolve_contact_ids(ws.id, campaign.id) == [fresh.id]

        counts = await service.preview(ws.id, campaign.id)
        assert counts.total == 1
        assert counts.excluded_already_enrolled == 1
        # Sizing the audience before a campaign exists counts nobody as enrolled.
        assert (await service.preview(ws.id, None)).total == 2


async def test_audience_slices_can_be_narrowed_to_one_source() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        campaign = await _make_campaign(db, ws.id)
        customer = await _past_customer(db, ws)
        quote_holder = await _unsold_quote_holder(db, ws)
        await db.commit()

        service = PreBookingAudienceService(db)
        only_customers = await service.resolve_contact_ids(
            ws.id, campaign.id, include_unsold_quotes=False
        )
        only_quotes = await service.resolve_contact_ids(
            ws.id, campaign.id, include_past_customers=False
        )
        neither = await service.resolve_contact_ids(
            ws.id, campaign.id, include_past_customers=False, include_unsold_quotes=False
        )

        assert only_customers == [customer.id]
        assert only_quotes == [quote_holder.id]
        # Neither slice selected means nobody — never "everyone".
        assert neither == []


async def test_a_contact_who_opted_out_after_the_send_cannot_be_sold_a_slot() -> None:
    """The last gate before money changes hands."""
    async with AsyncSessionLocal() as db:
        ws, _campaign, config = await _campaign_with_offer(db)
        contact = await _make_contact(db, ws.id)
        db.add(
            GlobalOptOut(
                workspace_id=ws.id,
                phone_number=contact.phone_number,
                opt_out_keyword="STOP",
            )
        )
        await db.commit()

        from app.services.prebooking.reservation_service import ContactNotEligibleError

        with pytest.raises(ContactNotEligibleError):
            await PreBookingReservationService(db).hold_slot(
                ws.id, config, contact_id=contact.id, base_amount=450
            )


# --------------------------------------------------------------------------- #
# Renewal: last season's holiday-lighting customers
# --------------------------------------------------------------------------- #
# Signup dates are placed *relative to the live season boundary* rather than
# hard-coded, so these tests still mean the same thing next January.
SEASON = current_season(ChristmasConfig())
LAST_SEASON = SEASON.started_at - timedelta(days=30)
THIS_SEASON = SEASON.started_at + timedelta(days=1)


async def _christmas_signup(
    db: AsyncSession,
    ws: Workspace,
    *,
    signed_at: datetime,
    **kwargs: object,
) -> Contact:
    """A contact whose approved seasonal quote provisioned a lighting plan.

    Writes the row the approval provisioner writes, back-dated to the season the
    signup belonged to — ``created_at`` is what the renewal predicate reads.
    """
    contact = await _make_contact(db, ws.id, **kwargs)  # type: ignore[arg-type]
    db.add(
        RecurringJobTemplate(
            workspace_id=ws.id,
            contact_id=contact.id,
            plan_type=str(ServicePlanType.CHRISTMAS_LIGHTS),
            title="Holiday Lighting — Install",
            frequency=str(RecurrenceFrequency.YEARLY),
            interval=1,
            next_run_at=signed_at,
            created_at=signed_at,
        )
    )
    await db.flush()
    return contact


async def test_the_renewal_slice_finds_last_seasons_lighting_customers() -> None:
    """The cheapest booking of the winter: the house that was lit last year.

    A gutter customer and a lighting customer are both "past customers" to the
    broad slice. Only the seasonal slice tells them apart, which is the entire
    point of aiming a renewal push.
    """
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        campaign = await _make_campaign(db, ws.id)
        gutters_only = await _past_customer(db, ws)
        last_season = await _christmas_signup(db, ws, signed_at=LAST_SEASON)
        # Signed inside the season currently being sold — already booked, so not
        # a renewal target.
        this_season = await _christmas_signup(db, ws, signed_at=THIS_SEASON)
        await db.commit()

        renewals = await PreBookingAudienceService(db).resolve_contact_ids(
            ws.id,
            campaign.id,
            include_past_customers=False,
            include_unsold_quotes=False,
            include_prior_season_christmas=True,
        )

        assert renewals == [last_season.id]
        assert gutters_only.id not in renewals
        assert this_season.id not in renewals


async def test_the_renewal_slice_is_off_by_default_but_counted_anyway() -> None:
    """An operator sees the number before deciding to aim at it."""
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        campaign = await _make_campaign(db, ws.id)
        await _christmas_signup(db, ws, signed_at=LAST_SEASON)
        await db.commit()

        service = PreBookingAudienceService(db)
        default_audience = await service.resolve_contact_ids(
            ws.id, campaign.id, include_past_customers=False, include_unsold_quotes=False
        )
        counts = await service.preview(ws.id, campaign.id)

        # Off by default: the narrow slice never silently widens an existing push.
        assert default_audience == []
        assert counts.prior_season_christmas == 1


async def test_seasons_back_bounds_how_far_a_win_back_reaches() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        campaign = await _make_campaign(db, ws.id)
        recent = await _christmas_signup(db, ws, signed_at=LAST_SEASON)
        ancient = await _christmas_signup(
            db, ws, signed_at=SEASON.started_at - timedelta(days=365 * 4)
        )
        await db.commit()

        service = PreBookingAudienceService(db)
        bounded = await service.resolve_contact_ids(
            ws.id,
            campaign.id,
            include_past_customers=False,
            include_unsold_quotes=False,
            include_prior_season_christmas=True,
            seasons_back=2,
        )
        unbounded = await service.resolve_contact_ids(
            ws.id,
            campaign.id,
            include_past_customers=False,
            include_unsold_quotes=False,
            include_prior_season_christmas=True,
        )

        assert bounded == [recent.id]
        assert sorted(unbounded) == sorted([recent.id, ancient.id])


async def test_a_renewal_target_who_opted_out_is_still_suppressed() -> None:
    """Being last year's best customer does not override STOP."""
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        campaign = await _make_campaign(db, ws.id)
        await _christmas_signup(db, ws, signed_at=LAST_SEASON, sms_consent_status="opted_out")
        await db.commit()

        renewals = await PreBookingAudienceService(db).resolve_contact_ids(
            ws.id,
            campaign.id,
            include_past_customers=False,
            include_unsold_quotes=False,
            include_prior_season_christmas=True,
        )

        assert renewals == []
