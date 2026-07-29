"""Integration tests for the people-search service (DB-backed)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest

from app.core.encryption import hash_value
from app.db.session import AsyncSessionLocal
from app.models.lead_prospect import LeadProspect, ProspectIdentityKind, ProspectStatus
from app.models.outbound_mission import OutboundMission
from app.models.prospect_signal import (
    ProspectSignal,
    ProspectSignalStatus,
    ProspectSignalType,
)
from app.models.workspace import Workspace
from app.schemas.prospect_search import (
    AddToMissionRequest,
    PeopleSearchRequest,
)
from app.services.lead_discovery.prospect_search_service import ProspectSearchService
from app.services.scraping.website_scraper import WebsiteScraperError


class _FakeScraper:
    """Stand-in for WebsiteScraperService returning canned HTML per URL."""

    def __init__(self, pages: dict[str, str]) -> None:
        self._pages = pages
        self.closed = False

    async def scrape_website(self, url: str) -> dict[str, object]:
        if url in self._pages:
            return {"html_content": self._pages[url]}
        raise WebsiteScraperError(f"404 {url}")

    async def close(self) -> None:
        self.closed = True


def _person(workspace_id: uuid.UUID, **kw: object) -> LeadProspect:
    base: dict[str, object] = {
        "workspace_id": workspace_id,
        "identity_kind": ProspectIdentityKind.OWNER_NAME,
        "full_name": "Jane Smith",
        "first_name": "Jane",
        "last_name": "Smith",
        "title": "Head of Marketing",
        "company_name": "Acme Co",
        "website_host": "acme.com",
        "location_label": "Austin, TX",
        "city": "Austin",
        "country_code": "US",
        "source_type": "web_people",
        "lead_score": 60,
        "status": ProspectStatus.NEW,
    }
    base.update(kw)
    return LeadProspect(**base)


@pytest.fixture(autouse=True)
async def _isolate_engine_pool() -> AsyncIterator[None]:
    # Abandon any connections pooled by a prior test's (now-closed) event loop
    # so this test never terminates a socket on a dead loop. close=False drops
    # references without doing I/O on the stale connections.
    from app.db.session import engine

    await engine.dispose(close=False)
    yield
    await engine.dispose(close=False)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_search_people_filters_and_signals() -> None:
    async with AsyncSessionLocal() as db:
        ws = Workspace(id=uuid.uuid4(), name="PS", slug=f"ps-{uuid.uuid4().hex[:8]}")
        db.add(ws)
        await db.flush()

        marketer = _person(ws.id, title="Head of Marketing", lead_score=70)
        engineer = _person(
            ws.id,
            full_name="Bob Jones",
            first_name="Bob",
            last_name="Jones",
            title="Software Engineer",
            lead_score=50,
        )
        company = LeadProspect(
            workspace_id=ws.id,
            identity_kind=ProspectIdentityKind.WEBSITE,
            company_name="Globex",
            website_host="globex.com",
            source_type="meta_ad_library",
            lead_score=90,
            status=ProspectStatus.NEW,
        )
        db.add_all([marketer, engineer, company])
        await db.flush()

        db.add(
            ProspectSignal(
                workspace_id=ws.id,
                prospect_id=marketer.id,
                signal_type=ProspectSignalType.RUNNING_ADS.value,
                strength=85,
                status=ProspectSignalStatus.ACTIVE,
                source="ad_library",
                payload={"platform": "meta"},
            )
        )
        await db.flush()

        service = ProspectSearchService(db)

        # People-only: the company prospect (no name) is excluded.
        all_people = await service.search_people(ws.id, PeopleSearchRequest())
        names = {p.full_name for p in all_people.items}
        assert names == {"Jane Smith", "Bob Jones"}
        assert all_people.total == 2

        # Title filter.
        marketing = await service.search_people(ws.id, PeopleSearchRequest(title="marketing"))
        assert [p.full_name for p in marketing.items] == ["Jane Smith"]

        # Signal filter + attached signals payload.
        with_ads = await service.search_people(
            ws.id, PeopleSearchRequest(signal_types=[ProspectSignalType.RUNNING_ADS.value])
        )
        assert len(with_ads.items) == 1
        assert with_ads.items[0].signals[0].strength == 85

        # Location filter.
        austin = await service.search_people(ws.id, PeopleSearchRequest(location="Austin"))
        assert {p.full_name for p in austin.items} == {"Jane Smith", "Bob Jones"}

        await db.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_add_to_mission_sets_mission_and_skips_foreign() -> None:
    async with AsyncSessionLocal() as db:
        ws = Workspace(id=uuid.uuid4(), name="PS2", slug=f"ps-{uuid.uuid4().hex[:8]}")
        db.add(ws)
        await db.flush()
        mission = OutboundMission(workspace_id=ws.id, name="Q3 Outbound")
        person = _person(ws.id)
        db.add_all([mission, person])
        await db.flush()

        service = ProspectSearchService(db)
        result = await service.add_to_mission(
            ws.id,
            AddToMissionRequest(
                mission_id=mission.id,
                prospect_ids=[person.id, uuid.uuid4()],
            ),
        )
        assert result.added == 1
        assert result.skipped == 1
        await db.refresh(person)
        assert person.mission_id == mission.id

        await db.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reveal_email_infers_and_persists() -> None:
    async with AsyncSessionLocal() as db:
        ws = Workspace(id=uuid.uuid4(), name="PS3", slug=f"ps-{uuid.uuid4().hex[:8]}")
        db.add(ws)
        await db.flush()
        person = _person(ws.id)
        db.add(person)
        await db.flush()

        service = ProspectSearchService(db)
        result = await service.reveal_email(ws.id, person.id)
        assert result.email == "jane.smith@acme.com"
        assert result.candidates
        await db.refresh(person)
        assert person.email_hash == hash_value("jane.smith@acme.com")
        assert (person.provenance or {}).get("email_pattern") == "first.last"

        await db.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reveal_phone_scrapes_and_persists() -> None:
    async with AsyncSessionLocal() as db:
        ws = Workspace(id=uuid.uuid4(), name="PS4", slug=f"ps-{uuid.uuid4().hex[:8]}")
        db.add(ws)
        await db.flush()
        person = _person(ws.id)
        db.add(person)
        await db.flush()

        scraper = _FakeScraper({"https://acme.com": '<a href="tel:+14155550132">Call us</a>'})
        service = ProspectSearchService(db)
        result = await service.reveal_phone(ws.id, person.id, scraper=scraper)

        assert result.phone_number == "+14155550132"
        assert result.source == "tel_link"
        assert result.candidates
        # Injected scraper is not owned, so the service must not close it.
        assert scraper.closed is False
        await db.refresh(person)
        assert person.phone_hash == hash_value("+14155550132")
        assert (person.provenance or {}).get("phone_source") == "tel_link"
        assert (person.provenance or {}).get("phone_status") == "found"

        await db.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reveal_phone_never_overwrites_existing() -> None:
    async with AsyncSessionLocal() as db:
        ws = Workspace(id=uuid.uuid4(), name="PS5", slug=f"ps-{uuid.uuid4().hex[:8]}")
        db.add(ws)
        await db.flush()
        existing = "+12025550111"
        person = _person(ws.id, phone_number=existing, phone_hash=hash_value(existing))
        db.add(person)
        await db.flush()

        scraper = _FakeScraper({"https://acme.com": '<a href="tel:+14155550132">Call us</a>'})
        service = ProspectSearchService(db)
        result = await service.reveal_phone(ws.id, person.id, scraper=scraper)

        # The freshly scraped number is returned as a candidate, but the stored
        # phone is never overwritten.
        assert result.phone_number == existing
        await db.refresh(person)
        assert person.phone_hash == hash_value(existing)
        assert person.phone_number == existing

        await db.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_reveal_phone_no_domain_raises() -> None:
    from app.services.exceptions import ValidationError

    async with AsyncSessionLocal() as db:
        ws = Workspace(id=uuid.uuid4(), name="PS6", slug=f"ps-{uuid.uuid4().hex[:8]}")
        db.add(ws)
        await db.flush()
        person = _person(ws.id, website_host=None, website_url=None)
        db.add(person)
        await db.flush()

        service = ProspectSearchService(db)
        with pytest.raises(ValidationError):
            await service.reveal_phone(ws.id, person.id)

        await db.rollback()
