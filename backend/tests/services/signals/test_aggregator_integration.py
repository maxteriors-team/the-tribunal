"""Integration tests for the signal aggregator (DB-backed)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.lead_prospect import LeadProspect, ProspectIdentityKind, ProspectStatus
from app.models.prospect_signal import ProspectSignal, ProspectSignalType
from app.models.workspace import Workspace
from app.services.signals.aggregator import SignalAggregator
from app.services.signals.providers.ad_tech import AdTechSignalProvider


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
async def test_aggregator_upserts_rows_and_folds_score() -> None:
    async with AsyncSessionLocal() as db:
        ws = Workspace(id=uuid.uuid4(), name="Sg", slug=f"sg-{uuid.uuid4().hex[:8]}")
        db.add(ws)
        await db.flush()
        prospect = LeadProspect(
            workspace_id=ws.id,
            identity_kind=ProspectIdentityKind.WEBSITE,
            full_name="Jane Smith",
            website_host="acme.com",
            lead_score=20,
            status=ProspectStatus.NEW,
        )
        db.add(prospect)
        await db.flush()

        # Inject ad_tech pixels so no network I/O happens; other providers off.
        aggregator = SignalAggregator(
            providers=[
                AdTechSignalProvider(pixels={"meta_pixel": True, "google_ads": True}),
            ]
        )
        signals = await aggregator.run(db, prospect)
        assert len(signals) == 1

        rows = (
            (
                await db.execute(
                    select(ProspectSignal).where(ProspectSignal.prospect_id == prospect.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].signal_type == ProspectSignalType.AD_TECH.value
        assert rows[0].strength == 70
        # Strength folded into the lead score (max).
        assert prospect.lead_score == 70

        # Re-run is idempotent: still one row, no evidence duplication.
        await aggregator.run(db, prospect)
        rows2 = (
            (
                await db.execute(
                    select(ProspectSignal).where(ProspectSignal.prospect_id == prospect.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows2) == 1
        signal_evidence = [e for e in prospect.evidence if e.get("type") == "signal"]
        assert len(signal_evidence) == 1

        await db.rollback()
