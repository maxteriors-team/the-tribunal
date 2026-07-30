"""Integration tests for :class:`NeighborOutreachService` and the SQL radius search.

Hits the real database (marked ``integration``; deselected by default, run with
``-m integration``). Each test opens an ``AsyncSessionLocal`` and never commits, so
the transaction rolls back on close and the dev database stays clean.

The maths and the compliance gate are covered by ``test_jobsite_radius.py`` and
``test_neighbor_outreach_compliance.py``. What needs Postgres is everything the
pure functions cannot prove:

- the SQL bounding-box prefilter and the haversine refinement agree end to end, so
  a house outside the radius is excluded by the *query*, not only by the assembler;
- ``latitude``/``longitude`` really are queryable plain floats while ``city``/
  ``postal_code`` stay encrypted and unqueryable;
- rows with null coordinates are filtered in SQL rather than raising;
- the job's own site and the customer's other sites drop out through the real
  ``exclude_job_id`` resolution;
- regeneration is idempotent against the unique constraints and preserves statuses
  an operator already set;
- a ``GlobalOptOut`` row blocks enrollment through the shared compliance layer;
- every read stays inside one workspace.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import Text, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import hash_value
from app.db.session import AsyncSessionLocal, engine
from app.models.campaign import Campaign, CampaignContact, CampaignType
from app.models.contact import Contact
from app.models.field_service import Job, JobStatus, ServiceLocation
from app.models.neighbor_outreach import (
    NeighborOutreachChannel,
    NeighborOutreachEntry,
    NeighborOutreachStatus,
)
from app.models.opt_out import GlobalOptOut
from app.models.workspace import Workspace
from app.schemas.neighbor_outreach import (
    NeighborOutreachCampaignRequest,
    NeighborOutreachEntryUpdate,
)
from app.services.field_service.exceptions import (
    JobSiteNotGeocodedError,
    NeighborMessagingDisabledError,
    NeighborOutreachBatchNotFoundError,
)
from app.services.field_service.jobsite_radius import (
    EARTH_RADIUS_METERS,
    find_nearby_locations,
)
from app.services.field_service.neighbor_outreach import (
    BLOCK_GLOBAL_OPT_OUT,
    BLOCK_MESSAGING_DISABLED,
    BLOCK_MISSING_CONSENT,
    NeighborOutreachService,
)
from app.services.field_service.neighbor_outreach_config import SETTINGS_KEY

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# A residential block in Minneapolis. All offsets below are in metres from here.
ORIGIN_LAT = 44.9778
ORIGIN_LNG = -93.2650


@pytest.fixture(autouse=True)
async def _fresh_engine_pool() -> AsyncIterator[None]:
    """Dispose the shared asyncpg pool around each test (fresh event loop)."""
    await engine.dispose()
    yield
    await engine.dispose()


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #
def _north(meters: float) -> float:
    """Latitude ``meters`` due north of the origin."""
    return ORIGIN_LAT + math.degrees(meters / EARTH_RADIUS_METERS)


async def _workspace(db: AsyncSession, settings: dict[str, object] | None = None) -> Workspace:
    workspace = Workspace(
        id=uuid.uuid4(),
        name="Neighbors",
        slug=f"nb-{uuid.uuid4().hex[:8]}",
        settings=settings or {},
    )
    db.add(workspace)
    await db.flush()
    return workspace


async def _contact(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    consent: str = "unknown",
    phone: str | None = None,
) -> Contact:
    email = f"n-{uuid.uuid4().hex[:8]}@example.com"
    contact = Contact(
        workspace_id=workspace_id,
        first_name="Neighbor",
        last_name=uuid.uuid4().hex[:6],
        email=email,
        email_hash=hash_value(email),
        phone_number=phone or f"+1555{uuid.uuid4().int % 10_000_000:07d}",
        sms_consent_status=consent,
    )
    db.add(contact)
    await db.flush()
    return contact


async def _location(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    contact_id: int,
    *,
    lat: float | None,
    lng: float | None,
    name: str = "Site",
    is_active: bool = True,
) -> ServiceLocation:
    location = ServiceLocation(
        workspace_id=workspace_id,
        contact_id=contact_id,
        name=name,
        address_line1="100 Oak St",
        city="Minneapolis",
        postal_code="55401",
        state="MN",
        latitude=lat,
        longitude=lng,
        is_active=is_active,
    )
    db.add(location)
    await db.flush()
    return location


async def _job(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    contact_id: int,
    location_id: uuid.UUID | None,
    *,
    status: JobStatus = JobStatus.COMPLETED,
) -> Job:
    job = Job(
        workspace_id=workspace_id,
        contact_id=contact_id,
        service_location_id=location_id,
        title="Driveway wash",
        status=status,
    )
    db.add(job)
    await db.flush()
    return job


async def _finished_job_on_a_street(
    db: AsyncSession,
    *,
    settings: dict[str, object] | None = None,
) -> tuple[Workspace, Job, ServiceLocation]:
    """A completed job whose site sits at the origin."""
    workspace = await _workspace(db, settings)
    customer = await _contact(db, workspace.id)
    site = await _location(
        db, workspace.id, customer.id, lat=ORIGIN_LAT, lng=ORIGIN_LNG, name="Job site"
    )
    job = await _job(db, workspace.id, customer.id, site.id)
    return workspace, job, site


# --------------------------------------------------------------------------- #
# The SQL radius search
# --------------------------------------------------------------------------- #
class TestFindNearbyLocations:
    """Bounding box in SQL + haversine in Python, end to end against Postgres."""

    async def test_finds_neighbours_inside_the_radius(self) -> None:
        async with AsyncSessionLocal() as db:
            workspace, job, _site = await _finished_job_on_a_street(db)
            neighbour_contact = await _contact(db, workspace.id)
            neighbour = await _location(
                db, workspace.id, neighbour_contact.id, lat=_north(60), lng=ORIGIN_LNG
            )

            found = await find_nearby_locations(
                db,
                workspace_id=workspace.id,
                origin_lat=ORIGIN_LAT,
                origin_lng=ORIGIN_LNG,
                radius_meters=150,
                exclude_job_id=job.id,
            )
            assert [match.row.id for match in found] == [neighbour.id]
            assert found[0].distance_meters == pytest.approx(60, abs=1)

    async def test_excludes_houses_beyond_the_radius(self) -> None:
        """Outside the circle *and* outside the box: the SQL filter drops it."""
        async with AsyncSessionLocal() as db:
            workspace, job, _site = await _finished_job_on_a_street(db)
            far_contact = await _contact(db, workspace.id)
            await _location(db, workspace.id, far_contact.id, lat=_north(400), lng=ORIGIN_LNG)

            found = await find_nearby_locations(
                db,
                workspace_id=workspace.id,
                origin_lat=ORIGIN_LAT,
                origin_lng=ORIGIN_LNG,
                radius_meters=150,
                exclude_job_id=job.id,
            )
            assert found == []

    async def test_boundary_conditions_at_the_radius_edge(self) -> None:
        async with AsyncSessionLocal() as db:
            workspace, job, _site = await _finished_job_on_a_street(db)
            inside_contact = await _contact(db, workspace.id)
            outside_contact = await _contact(db, workspace.id)
            inside = await _location(
                db, workspace.id, inside_contact.id, lat=_north(149), lng=ORIGIN_LNG
            )
            await _location(db, workspace.id, outside_contact.id, lat=_north(151), lng=ORIGIN_LNG)

            found = await find_nearby_locations(
                db,
                workspace_id=workspace.id,
                origin_lat=ORIGIN_LAT,
                origin_lng=ORIGIN_LNG,
                radius_meters=150,
                exclude_job_id=job.id,
            )
            assert [match.row.id for match in found] == [inside.id]

    async def test_null_coordinates_are_skipped_not_crashed(self) -> None:
        """An ungeocoded site is filtered in SQL; the query must not error."""
        async with AsyncSessionLocal() as db:
            workspace, job, _site = await _finished_job_on_a_street(db)
            ungeocoded_contact = await _contact(db, workspace.id)
            good_contact = await _contact(db, workspace.id)
            await _location(db, workspace.id, ungeocoded_contact.id, lat=None, lng=None)
            await _location(db, workspace.id, ungeocoded_contact.id, lat=_north(20), lng=None)
            good = await _location(
                db, workspace.id, good_contact.id, lat=_north(40), lng=ORIGIN_LNG
            )

            found = await find_nearby_locations(
                db,
                workspace_id=workspace.id,
                origin_lat=ORIGIN_LAT,
                origin_lng=ORIGIN_LNG,
                radius_meters=150,
                exclude_job_id=job.id,
            )
            assert [match.row.id for match in found] == [good.id]

    async def test_own_site_is_excluded(self) -> None:
        async with AsyncSessionLocal() as db:
            workspace, job, site = await _finished_job_on_a_street(db)
            found = await find_nearby_locations(
                db,
                workspace_id=workspace.id,
                origin_lat=ORIGIN_LAT,
                origin_lng=ORIGIN_LNG,
                radius_meters=150,
                exclude_job_id=job.id,
            )
            assert site.id not in {match.row.id for match in found}

    async def test_same_customers_other_sites_are_excluded(self) -> None:
        """The customer's rental next door is not a neighbour lead."""
        async with AsyncSessionLocal() as db:
            workspace, job, _site = await _finished_job_on_a_street(db)
            same_customer_id = job.contact_id
            rental = await _location(
                db, workspace.id, same_customer_id, lat=_north(30), lng=ORIGIN_LNG, name="Rental"
            )
            stranger_contact = await _contact(db, workspace.id)
            stranger = await _location(
                db, workspace.id, stranger_contact.id, lat=_north(50), lng=ORIGIN_LNG
            )

            found = await find_nearby_locations(
                db,
                workspace_id=workspace.id,
                origin_lat=ORIGIN_LAT,
                origin_lng=ORIGIN_LNG,
                radius_meters=150,
                exclude_job_id=job.id,
            )
            found_ids = {match.row.id for match in found}
            assert rental.id not in found_ids
            assert found_ids == {stranger.id}

    async def test_inactive_sites_are_excluded_by_default(self) -> None:
        async with AsyncSessionLocal() as db:
            workspace, job, _site = await _finished_job_on_a_street(db)
            retired_contact = await _contact(db, workspace.id)
            await _location(
                db,
                workspace.id,
                retired_contact.id,
                lat=_north(40),
                lng=ORIGIN_LNG,
                is_active=False,
            )
            found = await find_nearby_locations(
                db,
                workspace_id=workspace.id,
                origin_lat=ORIGIN_LAT,
                origin_lng=ORIGIN_LNG,
                radius_meters=150,
                exclude_job_id=job.id,
            )
            assert found == []

    async def test_another_workspaces_street_is_invisible(self) -> None:
        async with AsyncSessionLocal() as db:
            workspace, job, _site = await _finished_job_on_a_street(db)
            other_workspace = await _workspace(db)
            other_contact = await _contact(db, other_workspace.id)
            await _location(
                db, other_workspace.id, other_contact.id, lat=_north(20), lng=ORIGIN_LNG
            )

            found = await find_nearby_locations(
                db,
                workspace_id=workspace.id,
                origin_lat=ORIGIN_LAT,
                origin_lng=ORIGIN_LNG,
                radius_meters=150,
                exclude_job_id=job.id,
            )
            assert found == []

    async def test_results_are_capped_and_nearest_first(self) -> None:
        async with AsyncSessionLocal() as db:
            workspace, job, _site = await _finished_job_on_a_street(db)
            for meters in (120, 20, 80, 40):
                contact = await _contact(db, workspace.id)
                await _location(db, workspace.id, contact.id, lat=_north(meters), lng=ORIGIN_LNG)

            found = await find_nearby_locations(
                db,
                workspace_id=workspace.id,
                origin_lat=ORIGIN_LAT,
                origin_lng=ORIGIN_LNG,
                radius_meters=150,
                exclude_job_id=job.id,
                max_results=2,
            )
            distances = [match.distance_meters for match in found]
            assert len(found) == 2
            assert distances == sorted(distances)
            assert distances[0] == pytest.approx(20, abs=1)

    async def test_encrypted_postal_fields_are_not_used_for_filtering(self) -> None:
        """Sanity check on the premise: ``city`` is ciphertext at rest, not text.

        If this ever fails, ``ServiceLocation.city`` stopped being encrypted and the
        module docstring's "lat/lng only" constraint needs revisiting.
        """
        async with AsyncSessionLocal() as db:
            workspace = await _workspace(db)
            contact = await _contact(db, workspace.id)
            location = await _location(db, workspace.id, contact.id, lat=ORIGIN_LAT, lng=ORIGIN_LNG)
            raw_city = (
                await db.execute(
                    select(cast(ServiceLocation.__table__.c.city, Text)).where(
                        ServiceLocation.id == location.id
                    )
                )
            ).scalar_one()
            assert location.city == "Minneapolis"
            assert raw_city != "Minneapolis", "city stopped being encrypted at rest"


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #
class TestGenerateForJob:
    """Persisting the list, and never working the same neighbour twice."""

    async def test_generates_one_entry_per_neighbour(self) -> None:
        async with AsyncSessionLocal() as db:
            workspace, job, _site = await _finished_job_on_a_street(
                db, settings={SETTINGS_KEY: {"enabled": True, "radius_meters": 150}}
            )
            for meters in (30, 70):
                contact = await _contact(db, workspace.id)
                await _location(db, workspace.id, contact.id, lat=_north(meters), lng=ORIGIN_LNG)

            batch = await NeighborOutreachService(db).generate_for_job(job.id, workspace.id)
            assert batch.total == 2
            assert batch.pending_count == 2
            assert batch.radius_meters == 150
            assert [entry.status for entry in batch.entries] == [
                NeighborOutreachStatus.PENDING,
                NeighborOutreachStatus.PENDING,
            ]

    async def test_default_channel_is_print_when_messaging_is_off(self) -> None:
        """Print/canvass is the default output; messaging is the opt-in exception."""
        async with AsyncSessionLocal() as db:
            workspace, job, _site = await _finished_job_on_a_street(
                db, settings={SETTINGS_KEY: {"enabled": True}}
            )
            contact = await _contact(db, workspace.id, consent="opted_in")
            await _location(db, workspace.id, contact.id, lat=_north(30), lng=ORIGIN_LNG)

            batch = await NeighborOutreachService(db).generate_for_job(job.id, workspace.id)
            entry = batch.entries[0]
            assert entry.channel is NeighborOutreachChannel.PRINT
            assert entry.messaging_blocked_reason == BLOCK_MESSAGING_DISABLED
            assert entry.messageable is False

    async def test_consented_neighbour_is_messageable_when_allowed(self) -> None:
        async with AsyncSessionLocal() as db:
            workspace, job, _site = await _finished_job_on_a_street(
                db, settings={SETTINGS_KEY: {"enabled": True, "allow_messaging": True}}
            )
            contact = await _contact(db, workspace.id, consent="opted_in")
            await _location(db, workspace.id, contact.id, lat=_north(30), lng=ORIGIN_LNG)

            batch = await NeighborOutreachService(db).generate_for_job(job.id, workspace.id)
            entry = batch.entries[0]
            assert entry.channel is NeighborOutreachChannel.SMS
            assert entry.messaging_blocked_reason is None
            assert entry.messageable is True

    async def test_unconsented_neighbour_stays_print_even_when_messaging_allowed(self) -> None:
        async with AsyncSessionLocal() as db:
            workspace, job, _site = await _finished_job_on_a_street(
                db, settings={SETTINGS_KEY: {"enabled": True, "allow_messaging": True}}
            )
            contact = await _contact(db, workspace.id, consent="unknown")
            await _location(db, workspace.id, contact.id, lat=_north(30), lng=ORIGIN_LNG)

            batch = await NeighborOutreachService(db).generate_for_job(job.id, workspace.id)
            entry = batch.entries[0]
            assert entry.channel is NeighborOutreachChannel.PRINT
            assert entry.messaging_blocked_reason == BLOCK_MISSING_CONSENT
            assert entry.messageable is False

    async def test_opted_out_neighbour_stays_print(self) -> None:
        """A ``GlobalOptOut`` row is honoured at generation time."""
        async with AsyncSessionLocal() as db:
            workspace, job, _site = await _finished_job_on_a_street(
                db, settings={SETTINGS_KEY: {"enabled": True, "allow_messaging": True}}
            )
            phone = f"+1555{uuid.uuid4().int % 10_000_000:07d}"
            contact = await _contact(db, workspace.id, consent="opted_in", phone=phone)
            await _location(db, workspace.id, contact.id, lat=_north(30), lng=ORIGIN_LNG)
            db.add(GlobalOptOut(workspace_id=workspace.id, phone_number=phone))
            await db.flush()

            batch = await NeighborOutreachService(db).generate_for_job(job.id, workspace.id)
            entry = batch.entries[0]
            assert entry.channel is NeighborOutreachChannel.PRINT
            assert entry.messaging_blocked_reason == BLOCK_GLOBAL_OPT_OUT
            assert entry.messageable is False

    async def test_regenerating_is_idempotent(self) -> None:
        """The unique constraint means a second run cannot duplicate the street."""
        async with AsyncSessionLocal() as db:
            workspace, job, _site = await _finished_job_on_a_street(
                db, settings={SETTINGS_KEY: {"enabled": True}}
            )
            contact = await _contact(db, workspace.id)
            await _location(db, workspace.id, contact.id, lat=_north(30), lng=ORIGIN_LNG)

            service = NeighborOutreachService(db)
            first = await service.generate_for_job(job.id, workspace.id)
            second = await service.generate_for_job(job.id, workspace.id)

            assert first.id == second.id
            assert second.total == 1
            count = (
                await db.execute(
                    select(func.count(NeighborOutreachEntry.id)).where(
                        NeighborOutreachEntry.batch_id == first.id
                    )
                )
            ).scalar_one()
            assert count == 1

    async def test_regenerating_preserves_operator_statuses(self) -> None:
        """A neighbour already worked is never reset to ``pending``."""
        async with AsyncSessionLocal() as db:
            workspace, job, _site = await _finished_job_on_a_street(
                db, settings={SETTINGS_KEY: {"enabled": True}}
            )
            contact = await _contact(db, workspace.id)
            await _location(db, workspace.id, contact.id, lat=_north(30), lng=ORIGIN_LNG)

            service = NeighborOutreachService(db)
            batch = await service.generate_for_job(job.id, workspace.id)
            await service.update_entry(
                batch.entries[0].id,
                workspace.id,
                NeighborOutreachEntryUpdate(status=NeighborOutreachStatus.CONVERTED),
            )

            regenerated = await service.generate_for_job(job.id, workspace.id)
            assert regenerated.entries[0].status is NeighborOutreachStatus.CONVERTED
            assert regenerated.pending_count == 0

    async def test_regenerating_appends_a_newly_built_house(self) -> None:
        async with AsyncSessionLocal() as db:
            workspace, job, _site = await _finished_job_on_a_street(
                db, settings={SETTINGS_KEY: {"enabled": True}}
            )
            first_contact = await _contact(db, workspace.id)
            await _location(db, workspace.id, first_contact.id, lat=_north(30), lng=ORIGIN_LNG)

            service = NeighborOutreachService(db)
            await service.generate_for_job(job.id, workspace.id)

            later_contact = await _contact(db, workspace.id)
            await _location(db, workspace.id, later_contact.id, lat=_north(60), lng=ORIGIN_LNG)
            topped_up = await service.generate_for_job(job.id, workspace.id)
            assert topped_up.total == 2

    async def test_ungeocoded_job_site_is_a_clear_error(self) -> None:
        """ "No coordinates" and "no neighbours" must not look the same to an operator."""
        async with AsyncSessionLocal() as db:
            workspace = await _workspace(db, {SETTINGS_KEY: {"enabled": True}})
            customer = await _contact(db, workspace.id)
            site = await _location(db, workspace.id, customer.id, lat=None, lng=None)
            job = await _job(db, workspace.id, customer.id, site.id)

            with pytest.raises(JobSiteNotGeocodedError):
                await NeighborOutreachService(db).generate_for_job(job.id, workspace.id)

    async def test_job_with_no_site_at_all_is_a_clear_error(self) -> None:
        async with AsyncSessionLocal() as db:
            workspace = await _workspace(db, {SETTINGS_KEY: {"enabled": True}})
            customer = await _contact(db, workspace.id)
            job = await _job(db, workspace.id, customer.id, None)

            with pytest.raises(JobSiteNotGeocodedError):
                await NeighborOutreachService(db).generate_for_job(job.id, workspace.id)

    async def test_respects_the_configured_radius(self) -> None:
        async with AsyncSessionLocal() as db:
            workspace, job, _site = await _finished_job_on_a_street(
                db, settings={SETTINGS_KEY: {"enabled": True, "radius_meters": 50}}
            )
            near_contact = await _contact(db, workspace.id)
            far_contact = await _contact(db, workspace.id)
            await _location(db, workspace.id, near_contact.id, lat=_north(30), lng=ORIGIN_LNG)
            await _location(db, workspace.id, far_contact.id, lat=_north(120), lng=ORIGIN_LNG)

            batch = await NeighborOutreachService(db).generate_for_job(job.id, workspace.id)
            assert batch.total == 1
            assert batch.radius_meters == 50

    async def test_per_run_override_beats_the_config(self) -> None:
        async with AsyncSessionLocal() as db:
            workspace, job, _site = await _finished_job_on_a_street(
                db, settings={SETTINGS_KEY: {"enabled": True, "radius_meters": 50}}
            )
            far_contact = await _contact(db, workspace.id)
            await _location(db, workspace.id, far_contact.id, lat=_north(120), lng=ORIGIN_LNG)

            batch = await NeighborOutreachService(db).generate_for_job(
                job.id, workspace.id, radius_meters=200
            )
            assert batch.total == 1
            assert batch.radius_meters == 200


# --------------------------------------------------------------------------- #
# Completion hook
# --------------------------------------------------------------------------- #
class TestAutoGenerateOnCompletion:
    """Only a completed job in an opted-in workspace produces a list."""

    async def test_completion_generates_when_enabled(self) -> None:
        async with AsyncSessionLocal() as db:
            workspace, job, _site = await _finished_job_on_a_street(
                db,
                settings={SETTINGS_KEY: {"enabled": True, "auto_generate_on_completion": True}},
            )
            contact = await _contact(db, workspace.id)
            await _location(db, workspace.id, contact.id, lat=_north(30), lng=ORIGIN_LNG)

            service = NeighborOutreachService(db)
            await service.maybe_generate_on_completion(job)
            batch = await service.get_for_job(job.id, workspace.id)
            assert batch.total == 1

    async def test_disabled_workspace_generates_nothing(self) -> None:
        async with AsyncSessionLocal() as db:
            workspace, job, _site = await _finished_job_on_a_street(db)
            contact = await _contact(db, workspace.id)
            await _location(db, workspace.id, contact.id, lat=_north(30), lng=ORIGIN_LNG)

            service = NeighborOutreachService(db)
            await service.maybe_generate_on_completion(job)
            with pytest.raises(NeighborOutreachBatchNotFoundError):
                await service.get_for_job(job.id, workspace.id)

    async def test_auto_generate_off_generates_nothing(self) -> None:
        async with AsyncSessionLocal() as db:
            workspace, job, _site = await _finished_job_on_a_street(
                db,
                settings={SETTINGS_KEY: {"enabled": True, "auto_generate_on_completion": False}},
            )
            contact = await _contact(db, workspace.id)
            await _location(db, workspace.id, contact.id, lat=_north(30), lng=ORIGIN_LNG)

            service = NeighborOutreachService(db)
            await service.maybe_generate_on_completion(job)
            with pytest.raises(NeighborOutreachBatchNotFoundError):
                await service.get_for_job(job.id, workspace.id)

    async def test_unfinished_job_generates_nothing(self) -> None:
        async with AsyncSessionLocal() as db:
            workspace = await _workspace(db, {SETTINGS_KEY: {"enabled": True}})
            customer = await _contact(db, workspace.id)
            site = await _location(db, workspace.id, customer.id, lat=ORIGIN_LAT, lng=ORIGIN_LNG)
            job = await _job(db, workspace.id, customer.id, site.id, status=JobStatus.SCHEDULED)

            service = NeighborOutreachService(db)
            await service.maybe_generate_on_completion(job)
            with pytest.raises(NeighborOutreachBatchNotFoundError):
                await service.get_for_job(job.id, workspace.id)

    async def test_an_ungeocoded_site_does_not_break_completion(self) -> None:
        """A marketing list must never be able to fail a work-order update."""
        async with AsyncSessionLocal() as db:
            workspace = await _workspace(db, {SETTINGS_KEY: {"enabled": True}})
            customer = await _contact(db, workspace.id)
            site = await _location(db, workspace.id, customer.id, lat=None, lng=None)
            job = await _job(db, workspace.id, customer.id, site.id)

            service = NeighborOutreachService(db)
            await service.maybe_generate_on_completion(job)
            # Session still usable after the swallowed failure.
            assert (
                await db.execute(select(func.count(Job.id)).where(Job.id == job.id))
            ).scalar_one() == 1


# --------------------------------------------------------------------------- #
# Working the list, export, enrollment
# --------------------------------------------------------------------------- #
class TestWorkingTheList:
    """Status transitions, the print export, and the consent-gated messaging path."""

    async def test_status_transition_records_timestamps(self) -> None:
        async with AsyncSessionLocal() as db:
            workspace, job, _site = await _finished_job_on_a_street(
                db, settings={SETTINGS_KEY: {"enabled": True}}
            )
            contact = await _contact(db, workspace.id)
            await _location(db, workspace.id, contact.id, lat=_north(30), lng=ORIGIN_LNG)

            service = NeighborOutreachService(db)
            batch = await service.generate_for_job(job.id, workspace.id)
            updated = await service.update_entry(
                batch.entries[0].id,
                workspace.id,
                NeighborOutreachEntryUpdate(
                    status=NeighborOutreachStatus.CONTACTED, notes="Hanger on the door"
                ),
            )
            assert updated.status is NeighborOutreachStatus.CONTACTED
            assert updated.contacted_at is not None
            assert updated.status_changed_at is not None
            assert updated.notes == "Hanger on the door"

    async def test_cannot_switch_a_stranger_onto_the_sms_channel(self) -> None:
        """A hand-crafted PATCH must not route an unconsented neighbour into messaging."""
        async with AsyncSessionLocal() as db:
            workspace, job, _site = await _finished_job_on_a_street(
                db, settings={SETTINGS_KEY: {"enabled": True, "allow_messaging": True}}
            )
            contact = await _contact(db, workspace.id, consent="unknown")
            await _location(db, workspace.id, contact.id, lat=_north(30), lng=ORIGIN_LNG)

            service = NeighborOutreachService(db)
            batch = await service.generate_for_job(job.id, workspace.id)
            with pytest.raises(NeighborMessagingDisabledError):
                await service.update_entry(
                    batch.entries[0].id,
                    workspace.id,
                    NeighborOutreachEntryUpdate(channel=NeighborOutreachChannel.SMS),
                )

    async def test_export_carries_the_street_address(self) -> None:
        async with AsyncSessionLocal() as db:
            workspace, job, _site = await _finished_job_on_a_street(
                db, settings={SETTINGS_KEY: {"enabled": True}}
            )
            contact = await _contact(db, workspace.id)
            await _location(
                db, workspace.id, contact.id, lat=_north(30), lng=ORIGIN_LNG, name="102 Oak"
            )

            service = NeighborOutreachService(db)
            await service.generate_for_job(job.id, workspace.id)
            export = await service.export(job.id, workspace.id)
            assert export.total == 1
            row = export.rows[0]
            assert row.address_line1 == "100 Oak St"
            assert row.city == "Minneapolis"
            assert row.postal_code == "55401"
            assert row.label == "102 Oak"
            assert row.distance_meters == pytest.approx(30, abs=1)

    async def test_export_before_generation_is_a_clear_404(self) -> None:
        async with AsyncSessionLocal() as db:
            _workspace_row, job, _site = await _finished_job_on_a_street(db)
            with pytest.raises(NeighborOutreachBatchNotFoundError):
                await NeighborOutreachService(db).export(job.id, job.workspace_id)

    async def test_enrollment_only_takes_consented_neighbours(self) -> None:
        async with AsyncSessionLocal() as db:
            workspace, job, _site = await _finished_job_on_a_street(
                db, settings={SETTINGS_KEY: {"enabled": True, "allow_messaging": True}}
            )
            consented = await _contact(db, workspace.id, consent="opted_in")
            stranger = await _contact(db, workspace.id, consent="unknown")
            await _location(db, workspace.id, consented.id, lat=_north(30), lng=ORIGIN_LNG)
            await _location(db, workspace.id, stranger.id, lat=_north(60), lng=ORIGIN_LNG)
            campaign = Campaign(
                workspace_id=workspace.id,
                name="Neighbors",
                campaign_type=CampaignType.SMS,
            )
            db.add(campaign)
            await db.flush()

            service = NeighborOutreachService(db)
            await service.generate_for_job(job.id, workspace.id)
            result = await service.enroll_in_campaign(
                job.id,
                workspace.id,
                NeighborOutreachCampaignRequest(campaign_id=campaign.id),
            )

            assert result.enrolled_count == 1
            assert result.blocked_by_reason == {BLOCK_MISSING_CONSENT: 1}
            enrolled_contact_ids = {
                row[0]
                for row in (
                    await db.execute(
                        select(CampaignContact.contact_id).where(
                            CampaignContact.campaign_id == campaign.id
                        )
                    )
                ).all()
            }
            assert enrolled_contact_ids == {consented.id}

    async def test_enrollment_respects_the_opt_out_list(self) -> None:
        """Consent on record is not enough: STOP wins, at enrollment time."""
        async with AsyncSessionLocal() as db:
            workspace, job, _site = await _finished_job_on_a_street(
                db, settings={SETTINGS_KEY: {"enabled": True, "allow_messaging": True}}
            )
            phone = f"+1555{uuid.uuid4().int % 10_000_000:07d}"
            contact = await _contact(db, workspace.id, consent="opted_in", phone=phone)
            await _location(db, workspace.id, contact.id, lat=_north(30), lng=ORIGIN_LNG)
            campaign = Campaign(
                workspace_id=workspace.id,
                name="Neighbors",
                campaign_type=CampaignType.SMS,
            )
            db.add(campaign)
            await db.flush()

            service = NeighborOutreachService(db)
            await service.generate_for_job(job.id, workspace.id)

            # They text STOP after the list was generated.
            db.add(GlobalOptOut(workspace_id=workspace.id, phone_number=phone))
            await db.flush()

            result = await service.enroll_in_campaign(
                job.id,
                workspace.id,
                NeighborOutreachCampaignRequest(campaign_id=campaign.id),
            )
            assert result.enrolled_count == 0
            assert result.blocked_by_reason == {BLOCK_GLOBAL_OPT_OUT: 1}
            assert (
                await db.execute(
                    select(func.count(CampaignContact.id)).where(
                        CampaignContact.campaign_id == campaign.id
                    )
                )
            ).scalar_one() == 0

    async def test_enrollment_is_refused_when_messaging_is_disabled(self) -> None:
        async with AsyncSessionLocal() as db:
            workspace, job, _site = await _finished_job_on_a_street(
                db, settings={SETTINGS_KEY: {"enabled": True}}
            )
            campaign = Campaign(
                workspace_id=workspace.id,
                name="Neighbors",
                campaign_type=CampaignType.SMS,
            )
            db.add(campaign)
            await db.flush()

            with pytest.raises(NeighborMessagingDisabledError):
                await NeighborOutreachService(db).enroll_in_campaign(
                    job.id,
                    workspace.id,
                    NeighborOutreachCampaignRequest(campaign_id=campaign.id),
                )
