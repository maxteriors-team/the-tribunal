"""Turn a completed job into leads from the surrounding street.

The neighbours who watched a crew work are the warmest cold audience in home
services — it is what makes a wrapped truck and a yard sign *compound* rather than
just generate impressions. This service is the workflow around that:

1. **Generate** — on completion (or on demand), find the sites within the
   workspace's radius via :mod:`app.services.field_service.jobsite_radius` and
   persist them as a :class:`~app.models.neighbor_outreach.NeighborOutreachBatch`
   with one entry per neighbour. One batch per job and one entry per
   ``(batch, location)`` are database constraints, so a regenerate tops the list up
   and can never re-queue a house an operator already worked.
2. **Work** — per-entry status transitions (``pending`` → ``contacted`` /
   ``skipped`` / ``converted``) plus notes.
3. **Output, channel-agnostic** — either an :meth:`~NeighborOutreachService.export`
   for door hangers, a canvass route, or direct mail (the default), or
   :meth:`~NeighborOutreachService.enroll_in_campaign`, which enrolls *only* the
   neighbours that already map to a consented contact into an existing campaign.

**Why print is the default and messaging is the exception.** A radius search
returns addresses, not permission. Texting or emailing strangers because they live
near a job is a TCPA/CAN-SPAM problem, not a growth channel — so the messaging path
is gated three ways: the workspace must set ``allow_messaging``, the entry must map
to a known :class:`~app.models.contact.Contact`, and that contact must clear
:class:`app.services.compliance.OutboundComplianceService` (global opt-out from
:class:`app.models.opt_out.GlobalOptOut`) *and* carry recorded consent. Every
rejection is persisted on the entry in ``messaging_blocked_reason`` so the decision
is auditable months later. A street of strangers producing zero enrollments is the
correct outcome, not a bug.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.scope import select_workspace_owned
from app.models.campaign import Campaign, CampaignContact
from app.models.contact import Contact
from app.models.field_service import Job, JobStatus, ServiceLocation
from app.models.neighbor_outreach import (
    NeighborOutreachBatch,
    NeighborOutreachChannel,
    NeighborOutreachEntry,
    NeighborOutreachStatus,
)
from app.models.workspace import Workspace
from app.schemas.neighbor_outreach import (
    NeighborOutreachBatchResponse,
    NeighborOutreachCampaignRequest,
    NeighborOutreachCampaignResponse,
    NeighborOutreachEntryResponse,
    NeighborOutreachEntryUpdate,
    NeighborOutreachExportResponse,
    NeighborOutreachExportRow,
    NeighborOutreachSettings,
)
from app.services.compliance.outbound_compliance import (
    DirectOutboundComplianceRequest,
    OutboundComplianceService,
)
from app.services.field_service.exceptions import (
    JobNotFoundError,
    JobSiteNotGeocodedError,
    NeighborCampaignNotFoundError,
    NeighborMessagingDisabledError,
    NeighborOutreachBatchNotFoundError,
    NeighborOutreachEntryNotFoundError,
)
from app.services.field_service.jobsite_radius import (
    clamp_max_neighbors,
    clamp_radius_meters,
    find_nearby_locations,
)
from app.services.field_service.neighbor_outreach_config import get_neighbor_outreach_config

logger = structlog.get_logger()

# Consent-of-record value on :attr:`app.models.contact.Contact.sms_consent_status`.
# Matches :attr:`app.services.compliance.OutboundComplianceService.OPTED_IN`.
CONSENT_OPTED_IN = "opted_in"

# ``messaging_blocked_reason`` vocabulary. The opt-out and consent strings are the
# same ones :class:`OutboundComplianceService` emits, so there is one vocabulary
# across the codebase rather than a parallel set of neighbour-specific reasons.
BLOCK_NO_CONTACT = "no_contact"
BLOCK_MISSING_CONSENT = "missing_sms_consent"
BLOCK_GLOBAL_OPT_OUT = "global_opt_out"
BLOCK_NO_PHONE_NUMBER = "no_phone_number"
BLOCK_NO_EMAIL_ADDRESS = "no_email_address"
BLOCK_MESSAGING_DISABLED = "messaging_disabled"

# Statuses that mean "already worked" — a messaging run leaves them alone.
_WORKED_STATUSES = frozenset(
    {
        NeighborOutreachStatus.CONTACTED,
        NeighborOutreachStatus.SKIPPED,
        NeighborOutreachStatus.CONVERTED,
    }
)

_ENTRY_LOAD_OPTIONS = (
    selectinload(NeighborOutreachEntry.service_location),
    selectinload(NeighborOutreachEntry.contact),
)


def messaging_block_reason(  # noqa: PLR0911 - a flat gate chain reads better than nesting
    *,
    channel: NeighborOutreachChannel,
    has_contact: bool,
    phone_number: str | None,
    email: str | None,
    consent_status: str | None,
    compliance_reason: str | None,
) -> str | None:
    """Why this neighbour may not be messaged; ``None`` when messaging is allowed.

    Pure, so the whole compliance decision is provable without a database. The
    order encodes the priority of the failure an operator most needs to see:

    1. ``print`` needs no permission at all — a door hanger is not a message.
    2. **No contact record** is the hard stop. A location harvested from a radius
       is an address, not a person who agreed to hear from you.
    3. A missing phone/email means there is nothing to send *to*.
    4. ``compliance_reason`` is the verdict handed in from
       :class:`app.services.compliance.OutboundComplianceService` — the
       authoritative global opt-out check (``global_opt_out``). Passed in rather
       than re-implemented so this function cannot drift from the shared layer.
    5. Recorded consent. Checked here for **both** channels: this schema has a
       single ``sms_consent_status`` consent-of-record and no separate email
       consent column, so email inherits the same gate. That errs strict on
       purpose — cold-emailing a neighbour is precisely what must not happen.
    """
    if channel is NeighborOutreachChannel.PRINT:
        return None
    if not has_contact:
        return BLOCK_NO_CONTACT
    if channel is NeighborOutreachChannel.SMS and not phone_number:
        return BLOCK_NO_PHONE_NUMBER
    if channel is NeighborOutreachChannel.EMAIL and not email:
        return BLOCK_NO_EMAIL_ADDRESS
    if compliance_reason is not None:
        return compliance_reason
    if (consent_status or "unknown") != CONSENT_OPTED_IN:
        return BLOCK_MISSING_CONSENT
    return None


class NeighborOutreachService:
    """Generate, work, export, and (consent-gated) message a job's neighbours."""

    def __init__(
        self,
        db: AsyncSession,
        compliance: OutboundComplianceService | None = None,
    ) -> None:
        self.db = db
        self.compliance = compliance or OutboundComplianceService()

    # ------------------------------------------------------------------ #
    # Lookups
    # ------------------------------------------------------------------ #
    async def _get_job(self, job_id: uuid.UUID, workspace_id: uuid.UUID) -> Job:
        job = (
            await self.db.execute(
                select_workspace_owned(
                    Job,
                    workspace_id,
                    Job.id == job_id,
                    options=[selectinload(Job.service_location)],
                )
            )
        ).scalar_one_or_none()
        if job is None:
            raise JobNotFoundError()
        return job

    async def _get_batch(
        self, job_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> NeighborOutreachBatch | None:
        return (
            await self.db.execute(
                select_workspace_owned(
                    NeighborOutreachBatch,
                    workspace_id,
                    NeighborOutreachBatch.job_id == job_id,
                )
            )
        ).scalar_one_or_none()

    async def _entries(
        self, batch_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> Sequence[NeighborOutreachEntry]:
        query = select_workspace_owned(
            NeighborOutreachEntry,
            workspace_id,
            NeighborOutreachEntry.batch_id == batch_id,
            options=list(_ENTRY_LOAD_OPTIONS),
        ).order_by(NeighborOutreachEntry.distance_meters, NeighborOutreachEntry.id)
        return (await self.db.execute(query)).scalars().all()

    async def _workspace(self, workspace_id: uuid.UUID) -> Workspace:
        workspace = (
            await self.db.execute(select(Workspace).where(Workspace.id == workspace_id))
        ).scalar_one_or_none()
        if workspace is None:  # pragma: no cover - callers are workspace-scoped already
            raise JobNotFoundError("Workspace not found")
        return workspace

    async def _config(self, workspace_id: uuid.UUID) -> NeighborOutreachSettings:
        return get_neighbor_outreach_config(await self._workspace(workspace_id))

    # ------------------------------------------------------------------ #
    # Response building
    # ------------------------------------------------------------------ #
    @staticmethod
    def _entry_response(entry: NeighborOutreachEntry) -> NeighborOutreachEntryResponse:
        response = NeighborOutreachEntryResponse.model_validate(entry)
        location = entry.service_location
        response.label = location.name if location is not None else None
        contact = entry.contact
        response.customer_name = contact.full_name if contact is not None else None
        # Messaging is allowed only when nothing blocked it *and* a contact record
        # stands behind the address. Both, never either.
        response.messageable = (
            entry.messaging_blocked_reason is None and entry.contact_id is not None
        )
        return response

    def _batch_response(
        self,
        batch: NeighborOutreachBatch,
        entries: Sequence[NeighborOutreachEntry],
    ) -> NeighborOutreachBatchResponse:
        """Assemble the batch payload from an explicitly-loaded entry list.

        Built field by field rather than via ``model_validate(batch)``: the response
        declares an ``entries`` field, and ``from_attributes`` would resolve it off
        the ORM relationship of the same name — a lazy load, which raises
        ``MissingGreenlet`` under asyncio. ``entries`` is always the caller's
        already-awaited, distance-ordered list.
        """
        items = [self._entry_response(entry) for entry in entries]
        return NeighborOutreachBatchResponse(
            id=batch.id,
            job_id=batch.job_id,
            origin_location_id=batch.origin_location_id,
            origin_latitude=batch.origin_latitude,
            origin_longitude=batch.origin_longitude,
            radius_meters=batch.radius_meters,
            generated_at=batch.generated_at,
            created_at=batch.created_at,
            entries=items,
            total=len(items),
            pending_count=sum(1 for item in items if item.status is NeighborOutreachStatus.PENDING),
            messageable_count=sum(1 for item in items if item.messageable),
        )

    # ------------------------------------------------------------------ #
    # Compliance resolution
    # ------------------------------------------------------------------ #
    async def _resolve_block_reason(
        self,
        *,
        workspace_id: uuid.UUID,
        channel: NeighborOutreachChannel,
        contact: Contact | None,
        now: datetime,
    ) -> str | None:
        """Run the shared compliance layer, then compose the final block reason."""
        compliance_reason: str | None = None
        if contact is not None:
            result = await self.compliance.evaluate_direct(
                DirectOutboundComplianceRequest(
                    workspace_id=workspace_id,
                    channel=str(channel),
                    action_type="neighbor_outreach",
                    now=now,
                    phone_number=contact.phone_number,
                    sms_consent_status=contact.sms_consent_status,
                    contact_id=contact.id,
                    # Quiet hours belong to the send itself, not to eligibility —
                    # a neighbour is not permanently ineligible because it is 9pm.
                    quiet_hours_start=None,
                    quiet_hours_end=None,
                ),
                self.db,
            )
            if not result.allowed:
                compliance_reason = result.reason

        return messaging_block_reason(
            channel=channel,
            has_contact=contact is not None,
            phone_number=contact.phone_number if contact is not None else None,
            email=contact.email if contact is not None else None,
            consent_status=contact.sms_consent_status if contact is not None else None,
            compliance_reason=compliance_reason,
        )

    # ------------------------------------------------------------------ #
    # Generation
    # ------------------------------------------------------------------ #
    async def generate_for_job(
        self,
        job_id: uuid.UUID,
        workspace_id: uuid.UUID,
        *,
        radius_meters: int | None = None,
        max_neighbors: int | None = None,
    ) -> NeighborOutreachBatchResponse:
        """Generate (or top up) the neighbour list for a job.

        Idempotent by construction: an existing batch for the job is reused and only
        *new* locations are appended, so statuses an operator already set survive a
        regenerate and no house is ever queued twice for the same job.
        """
        job = await self._get_job(job_id, workspace_id)
        config = await self._config(workspace_id)

        location = job.service_location
        if location is None or location.latitude is None or location.longitude is None:
            raise JobSiteNotGeocodedError()

        radius = clamp_radius_meters(
            radius_meters if radius_meters is not None else config.radius_meters
        )
        cap = clamp_max_neighbors(
            max_neighbors if max_neighbors is not None else config.max_neighbors
        )

        nearby = await find_nearby_locations(
            self.db,
            workspace_id=workspace_id,
            origin_lat=location.latitude,
            origin_lng=location.longitude,
            radius_meters=radius,
            exclude_job_id=job.id,
            max_results=cap,
        )

        batch = await self._get_batch(job_id, workspace_id)
        if batch is None:
            batch = NeighborOutreachBatch(
                workspace_id=workspace_id,
                job_id=job.id,
                origin_location_id=location.id,
                origin_latitude=location.latitude,
                origin_longitude=location.longitude,
                radius_meters=int(radius),
            )
            self.db.add(batch)
            await self.db.flush()
        else:
            # A widened radius is recorded so the snapshot still explains the list.
            batch.radius_meters = max(batch.radius_meters, int(radius))
            batch.generated_at = datetime.now(UTC)

        existing_location_ids = {
            row[0]
            for row in (
                await self.db.execute(
                    select(NeighborOutreachEntry.service_location_id).where(
                        NeighborOutreachEntry.batch_id == batch.id
                    )
                )
            ).all()
        }

        now = datetime.now(UTC)
        # Print is the default channel; the messaging gate only *upgrades* an entry
        # when a consented contact stands behind it and the workspace opted in.
        default_channel = (
            NeighborOutreachChannel.SMS if config.allow_messaging else NeighborOutreachChannel.PRINT
        )
        added = 0
        for match in nearby:
            candidate = match.row
            if candidate.id in existing_location_ids:
                continue
            contact = await self._load_contact(candidate.contact_id, workspace_id)
            block_reason = (
                await self._resolve_block_reason(
                    workspace_id=workspace_id,
                    channel=default_channel,
                    contact=contact,
                    now=now,
                )
                if config.allow_messaging
                else BLOCK_MESSAGING_DISABLED
            )
            self.db.add(
                NeighborOutreachEntry(
                    workspace_id=workspace_id,
                    batch_id=batch.id,
                    service_location_id=candidate.id,
                    contact_id=contact.id if contact is not None else None,
                    distance_meters=match.distance_meters,
                    status=NeighborOutreachStatus.PENDING,
                    channel=(
                        default_channel if block_reason is None else NeighborOutreachChannel.PRINT
                    ),
                    messaging_blocked_reason=block_reason,
                )
            )
            added += 1

        await self.db.flush()
        logger.info(
            "neighbor_outreach_generated",
            workspace_id=str(workspace_id),
            job_id=str(job.id),
            batch_id=str(batch.id),
            radius_meters=radius,
            found=len(nearby),
            added=added,
        )
        return self._batch_response(batch, await self._entries(batch.id, workspace_id))

    async def _load_contact(
        self, contact_id: int | None, workspace_id: uuid.UUID
    ) -> Contact | None:
        """Workspace-scoped contact fetch (``None`` for an address-only location)."""
        if contact_id is None:
            return None
        return (
            await self.db.execute(
                select_workspace_owned(Contact, workspace_id, Contact.id == contact_id)
            )
        ).scalar_one_or_none()

    async def maybe_generate_on_completion(self, job: Job) -> None:
        """Generate a neighbour list when a job completes, if the workspace opted in.

        Called from :class:`app.services.jobs.JobService` on the status transition.
        Generation is read-only marketing prep — it sends nothing — but it must never
        be able to fail a work-order update, so it runs inside a ``SAVEPOINT`` and
        swallows its own errors: a rollback there leaves the caller's transaction
        usable, where a bare ``except`` around a failed flush would poison it.
        """
        if job.status != JobStatus.COMPLETED:
            return
        config = await self._config(job.workspace_id)
        if not (config.enabled and config.auto_generate_on_completion):
            return
        try:
            async with self.db.begin_nested():
                await self.generate_for_job(job.id, job.workspace_id)
        except Exception as exc:
            logger.warning(
                "neighbor_outreach_autogenerate_failed",
                workspace_id=str(job.workspace_id),
                job_id=str(job.id),
                error=str(exc),
            )

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    async def get_for_job(
        self, job_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> NeighborOutreachBatchResponse:
        """The job's neighbour list, or a 404-mapped error when none was generated."""
        await self._get_job(job_id, workspace_id)
        batch = await self._get_batch(job_id, workspace_id)
        if batch is None:
            raise NeighborOutreachBatchNotFoundError()
        return self._batch_response(batch, await self._entries(batch.id, workspace_id))

    async def export(
        self, job_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> NeighborOutreachExportResponse:
        """The print/canvass list: one row per neighbour, with its postal address.

        This is the channel-agnostic default output — a door-hanger walk list, a
        canvass route, or a direct-mail merge. The addresses are decrypted out of
        :class:`~app.models.field_service.ServiceLocation`, so this payload is
        customer PII: dispatcher-gated, workspace-scoped, and never written to a
        public path such as ``backend/static/``.
        """
        await self._get_job(job_id, workspace_id)
        batch = await self._get_batch(job_id, workspace_id)
        if batch is None:
            raise NeighborOutreachBatchNotFoundError()

        entries = await self._entries(batch.id, workspace_id)
        rows = [
            NeighborOutreachExportRow(
                entry_id=entry.id,
                service_location_id=entry.service_location_id,
                label=entry.service_location.name if entry.service_location else None,
                customer_name=entry.contact.full_name if entry.contact else None,
                address_line1=_site_field(entry.service_location, "address_line1"),
                address_line2=_site_field(entry.service_location, "address_line2"),
                city=_site_field(entry.service_location, "city"),
                state=_site_field(entry.service_location, "state"),
                postal_code=_site_field(entry.service_location, "postal_code"),
                country=_site_field(entry.service_location, "country") or "US",
                latitude=entry.service_location.latitude if entry.service_location else None,
                longitude=entry.service_location.longitude if entry.service_location else None,
                distance_meters=entry.distance_meters,
                status=entry.status,
                channel=entry.channel,
            )
            for entry in entries
        ]
        return NeighborOutreachExportResponse(
            job_id=job_id,
            batch_id=batch.id,
            radius_meters=batch.radius_meters,
            generated_at=batch.generated_at,
            rows=rows,
            total=len(rows),
        )

    # ------------------------------------------------------------------ #
    # Working the list
    # ------------------------------------------------------------------ #
    async def update_entry(
        self,
        entry_id: uuid.UUID,
        workspace_id: uuid.UUID,
        data: NeighborOutreachEntryUpdate,
    ) -> NeighborOutreachEntryResponse:
        """Set an entry's status/channel/notes.

        A channel change to ``sms``/``email`` is refused when the entry has no
        consented contact behind it — the same gate as generation, enforced here too
        so a hand-edited PATCH cannot route a stranger into the messaging path.
        """
        entry = (
            await self.db.execute(
                select_workspace_owned(
                    NeighborOutreachEntry,
                    workspace_id,
                    NeighborOutreachEntry.id == entry_id,
                    options=list(_ENTRY_LOAD_OPTIONS),
                )
            )
        ).scalar_one_or_none()
        if entry is None:
            raise NeighborOutreachEntryNotFoundError()

        now = datetime.now(UTC)
        if data.channel is not None and data.channel is not entry.channel:
            if data.channel is NeighborOutreachChannel.PRINT:
                entry.channel = data.channel
            else:
                config = await self._config(workspace_id)
                if not config.allow_messaging:
                    raise NeighborMessagingDisabledError()
                reason = await self._resolve_block_reason(
                    workspace_id=workspace_id,
                    channel=data.channel,
                    contact=entry.contact,
                    now=now,
                )
                if reason is not None:
                    entry.messaging_blocked_reason = reason
                    await self.db.flush()
                    raise NeighborMessagingDisabledError(
                        f"This neighbor cannot be messaged: {reason}"
                    )
                entry.channel = data.channel
                entry.messaging_blocked_reason = None

        if data.status is not None and data.status is not entry.status:
            entry.status = data.status
            entry.status_changed_at = now
            if data.status is NeighborOutreachStatus.CONTACTED and entry.contacted_at is None:
                entry.contacted_at = now

        if data.notes is not None:
            entry.notes = data.notes

        await self.db.flush()
        await self.db.refresh(entry)
        return self._entry_response(entry)

    # ------------------------------------------------------------------ #
    # Messaging path (consented contacts only)
    # ------------------------------------------------------------------ #
    async def enroll_in_campaign(
        self,
        job_id: uuid.UUID,
        workspace_id: uuid.UUID,
        request: NeighborOutreachCampaignRequest,
    ) -> NeighborOutreachCampaignResponse:
        """Enroll the consented subset of a batch into an existing campaign.

        Every entry is re-evaluated against the compliance layer *now* rather than
        trusting the flag written at generation time — a neighbour may have texted
        STOP in between. Blocked entries are left ``pending`` on the ``print``
        channel with a fresh ``messaging_blocked_reason``, and counted in
        ``blocked_by_reason`` so the run is auditable.
        """
        await self._get_job(job_id, workspace_id)
        if request.channel is NeighborOutreachChannel.PRINT:
            raise NeighborMessagingDisabledError("Print entries are exported, not messaged")

        config = await self._config(workspace_id)
        if not config.allow_messaging:
            raise NeighborMessagingDisabledError()

        batch = await self._get_batch(job_id, workspace_id)
        if batch is None:
            raise NeighborOutreachBatchNotFoundError()

        campaign = (
            await self.db.execute(
                select_workspace_owned(Campaign, workspace_id, Campaign.id == request.campaign_id)
            )
        ).scalar_one_or_none()
        if campaign is None:
            raise NeighborCampaignNotFoundError()

        entries = await self._entries(batch.id, workspace_id)
        already_enrolled = {
            row[0]
            for row in (
                await self.db.execute(
                    select(CampaignContact.contact_id).where(
                        CampaignContact.campaign_id == campaign.id
                    )
                )
            ).all()
        }

        now = datetime.now(UTC)
        enrolled: list[uuid.UUID] = []
        blocked: Counter[str] = Counter()
        for entry in entries:
            if entry.status in _WORKED_STATUSES:
                blocked["already_worked"] += 1
                continue
            reason = await self._resolve_block_reason(
                workspace_id=workspace_id,
                channel=request.channel,
                contact=entry.contact,
                now=now,
            )
            entry.messaging_blocked_reason = reason
            if reason is not None:
                entry.channel = NeighborOutreachChannel.PRINT
                blocked[reason] += 1
                continue
            if entry.contact_id is None:  # pragma: no cover - implied by BLOCK_NO_CONTACT
                blocked[BLOCK_NO_CONTACT] += 1
                continue
            if entry.contact_id not in already_enrolled:
                self.db.add(CampaignContact(campaign_id=campaign.id, contact_id=entry.contact_id))
                already_enrolled.add(entry.contact_id)
                campaign.total_contacts += 1
            entry.channel = request.channel
            entry.status = NeighborOutreachStatus.CONTACTED
            entry.status_changed_at = now
            entry.contacted_at = now
            enrolled.append(entry.id)

        await self.db.flush()
        logger.info(
            "neighbor_outreach_enrolled",
            workspace_id=str(workspace_id),
            job_id=str(job_id),
            campaign_id=str(campaign.id),
            channel=str(request.channel),
            enrolled=len(enrolled),
            blocked=dict(blocked),
        )
        return NeighborOutreachCampaignResponse(
            job_id=job_id,
            batch_id=batch.id,
            campaign_id=campaign.id,
            channel=request.channel,
            enrolled_entry_ids=enrolled,
            enrolled_count=len(enrolled),
            skipped_count=sum(blocked.values()),
            blocked_by_reason=dict(blocked),
        )


def _site_field(location: ServiceLocation | None, field: str) -> str | None:
    """Read one decrypted postal field off a site, tolerating a detached row."""
    if location is None:
        return None
    value = getattr(location, field, None)
    return value if isinstance(value, str) else None
