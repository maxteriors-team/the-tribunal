"""Pre-booking worker: launch scheduled campaigns, sweep lapsed holds.

Two small, order-independent jobs that make "build the January campaign in
September" more than a note in someone's phone:

**Launch.** A campaign parked in ``scheduled`` with a ``scheduled_start`` in the
future is inert — every campaign worker only picks up ``running`` campaigns. This
worker flips it when the date arrives, through the same
:func:`~app.services.campaigns.campaign_lifecycle.start_campaign` the API button
uses, so the guarantee window, the "no contacts" refusal and the started-at stamp
are identical whether a human or the clock pressed go.

Deliberately scoped to campaigns that carry a pre-booking offer. Scheduled launch
is the feature pre-booking asked for; silently changing when *every* campaign in
the product starts sending would be a behaviour change nobody requested.

**Sweep.** Holds that lapsed without a deposit are marked ``released``. Slot
counting already ignores a lapsed hold (see
:func:`~app.services.prebooking.reservation_service.occupying_reservation_condition`),
so this is bookkeeping, not enforcement: it keeps the operator's reservation list
truthful and frees the same customer to book again.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.campaign import Campaign, CampaignStatus
from app.models.prebooking import PreBookingCampaignConfig
from app.services.campaigns.campaign_lifecycle import (
    CampaignLifecycleError,
    start_campaign,
)
from app.services.prebooking.reservation_service import PreBookingReservationService
from app.workers.base import BaseWorker, WorkerRegistry

# Five minutes. A launch date is a date, not a deadline — nobody notices the
# difference between 09:00 and 09:04, and a tighter loop just spins on an empty
# indexed query all winter.
POLL_INTERVAL_SECONDS = 300


class PreBookingWorker(BaseWorker):
    """Start due pre-booking campaigns and release lapsed slot holds."""

    POLL_INTERVAL_SECONDS = POLL_INTERVAL_SECONDS
    COMPONENT_NAME = "prebooking_worker"
    MAX_CONCURRENCY = 1

    async def _process_items(self) -> None:
        async with AsyncSessionLocal() as db:
            launched = await self._launch_due_campaigns(db)
            released = await PreBookingReservationService(db).release_expired_holds()

        if launched or released:
            self.record_items_processed(launched + released)
            self.logger.info(
                "prebooking_worker_cycle",
                campaigns_launched=launched,
                holds_released=released,
            )

    async def _launch_due_campaigns(self, db: AsyncSession) -> int:
        """Flip scheduled pre-booking campaigns to running once their date lands.

        Ids first, rows one at a time: a rollback expires every instance in the
        session, so holding a list of ORM objects across a failed launch would
        make the *next* campaign's attribute access emit sync IO under asyncio.
        """
        now = datetime.now(UTC)
        due_ids = (
            (
                await db.execute(
                    select(Campaign.id)
                    .join(
                        PreBookingCampaignConfig,
                        PreBookingCampaignConfig.campaign_id == Campaign.id,
                    )
                    .where(
                        Campaign.status == CampaignStatus.SCHEDULED,
                        Campaign.scheduled_start.is_not(None),
                        Campaign.scheduled_start <= now,
                    )
                )
            )
            .scalars()
            .all()
        )

        launched = 0
        for campaign_id in due_ids:
            campaign = await db.get(Campaign, campaign_id)
            if campaign is None:
                continue
            name = campaign.name
            scheduled_start = campaign.scheduled_start
            try:
                result = await start_campaign(db, campaign)
                await db.commit()
            except CampaignLifecycleError as exc:
                # Almost always "no contacts": the operator scheduled a launch
                # and never enrolled the audience. Leave it scheduled and say so
                # rather than burning the campaign into a failed state.
                self.logger.warning(
                    "prebooking_launch_skipped",
                    campaign_id=str(campaign_id),
                    reason=str(exc),
                )
                await db.rollback()
                continue

            launched += 1
            self.logger.info(
                "prebooking_campaign_launched",
                campaign_id=str(campaign_id),
                campaign_name=name,
                contact_count=result.contact_count,
                scheduled_start=scheduled_start.isoformat() if scheduled_start else None,
            )
        return launched


# Singleton registry
_registry = WorkerRegistry(PreBookingWorker)
start_prebooking_worker = _registry.start
stop_prebooking_worker = _registry.stop
get_prebooking_worker = _registry.get
