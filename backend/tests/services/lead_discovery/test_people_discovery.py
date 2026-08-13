"""Integration tests for web_people discovery-job execution (DB-backed)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.lead_discovery_job import (
    DiscoveryJobStatus,
    DiscoverySourceType,
    LeadDiscoveryJob,
)
from app.models.lead_prospect import LeadProspect
from app.models.workspace import Workspace
from app.services.lead_discovery.people_discovery import run_people_discovery_job
from app.services.lead_discovery.types import (
    LeadDiscoveryRequest,
    ProviderResult,
    RawLead,
)


class _FakePeopleProvider:
    """Stand-in WebPeopleLeadProvider that returns canned leads (no crawl)."""

    source_type = "web_people"

    def __init__(self, leads: tuple[RawLead, ...]) -> None:
        self._leads = leads

    async def search(self, request: LeadDiscoveryRequest) -> ProviderResult:
        return ProviderResult(
            source_type="web_people",
            leads=self._leads,
            requested_count=request.max_results,
            raw_count=len(self._leads),
        )

    async def close(self) -> None:
        return None


def _lead(name: str, title: str, email: str | None = None) -> RawLead:
    first, _, last = name.partition(" ")
    return RawLead(
        source_type="web_people",
        name=name,
        full_name=name,
        first_name=first,
        last_name=last,
        title=title,
        email=email,
        website="https://acme.com",
        website_host="acme.com",
        source_metadata={"confidence": 80, "email_unverified": email is not None},
    )


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
async def test_run_people_discovery_upserts_prospects() -> None:
    async with AsyncSessionLocal() as db:
        ws = Workspace(id=uuid.uuid4(), name="Pd", slug=f"pd-{uuid.uuid4().hex[:8]}")
        db.add(ws)
        await db.flush()
        job = LeadDiscoveryJob(
            workspace_id=ws.id,
            source_type=DiscoverySourceType.WEB_PEOPLE,
            query="acme team",
            params={"domain": "acme.com", "max_results": 10},
            status=DiscoveryJobStatus.PENDING,
            requested_count=10,
        )
        db.add(job)
        await db.flush()

        provider = _FakePeopleProvider(
            (
                _lead("Jane Smith", "CEO", email="jane@acme.com"),
                _lead("Bob Jones", "CTO"),
            )
        )
        outcome = await run_people_discovery_job(db, job, provider=provider)  # type: ignore[arg-type]
        assert outcome.discovered_count == 2
        assert job.status == DiscoveryJobStatus.SUCCEEDED

        rows = (
            (await db.execute(select(LeadProspect).where(LeadProspect.workspace_id == ws.id)))
            .scalars()
            .all()
        )
        assert {r.full_name for r in rows} == {"Jane Smith", "Bob Jones"}
        jane = next(r for r in rows if r.full_name == "Jane Smith")
        assert jane.email == "jane@acme.com"
        assert (jane.provenance or {}).get("email_status") == "unverified"

        # Re-running the same job dedupes (no new rows created).
        job2 = LeadDiscoveryJob(
            workspace_id=ws.id,
            source_type=DiscoverySourceType.WEB_PEOPLE,
            params={"domain": "acme.com"},
            status=DiscoveryJobStatus.PENDING,
            requested_count=10,
        )
        db.add(job2)
        await db.flush()
        outcome2 = await run_people_discovery_job(
            db,
            job2,
            provider=_FakePeopleProvider(  # type: ignore[arg-type]
                (_lead("Jane Smith", "CEO", email="jane@acme.com"),)
            ),
        )
        assert outcome2.discovered_count == 0
        assert outcome2.duplicate_count == 1

        await db.rollback()
