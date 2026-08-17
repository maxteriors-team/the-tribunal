"""Meta Lead Ads Graph client contract tests."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from urllib.parse import parse_qs

import httpx
import pytest
from sqlalchemy import func, select

from app.db.session import AsyncSessionLocal, engine
from app.models.lead_source import LeadSourceCampaign, LeadSourceSpendEntry
from app.models.workspace import Workspace, WorkspaceIntegration
from app.services.lead_sources.meta_lead_ads_service import (
    MetaCampaignSpend,
    MetaLeadAdsClient,
    MetaLeadAdsValidationError,
    sync_meta_campaign_spend,
)


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    """Keep shared asyncpg connections on each test's event loop."""
    await engine.dispose()
    yield
    await engine.dispose()


async def test_fetch_campaign_spend_uses_verified_insights_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path.endswith("/act_12345/insights")
        params = parse_qs(request.url.query.decode())
        assert params["level"] == ["campaign"]
        assert params["date_preset"] == ["maximum"]
        assert params["time_increment"] == ["all_days"]
        assert "campaign_id" in params["fields"][0]
        assert "spend" in params["fields"][0]
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "account_currency": "usd",
                        "campaign_id": "campaign-1",
                        "campaign_name": "August Leads",
                        "date_start": "2026-08-01",
                        "date_stop": "2026-08-14",
                        "spend": "123.45",
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        rows = await MetaLeadAdsClient(http_client).fetch_campaign_spend(
            {
                "ad_account_id": "12345",
                "ad_" + "access_" + "token": "ads-token",
            }
        )

    assert len(rows) == 1
    row = rows[0]
    assert row.campaign_id == "campaign-1"
    assert str(row.amount) == "123.45"
    assert row.currency == "USD"
    assert row.starts_on.isoformat() == "2026-08-01"
    assert row.ends_on.isoformat() == "2026-08-14"


async def test_fetch_campaign_spend_is_optional_without_ad_account() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(500))
    ) as http_client:
        rows = await MetaLeadAdsClient(http_client).fetch_campaign_spend({})
    assert rows == []


@pytest.mark.parametrize(
    "object_id",
    [
        "//attacker.example/lead",
        "../me",
        "123/insights/../me",
        "123?fields=access_token",
    ],
)
def test_meta_graph_url_rejects_untrusted_paths(object_id: str) -> None:
    with pytest.raises(MetaLeadAdsValidationError, match="Invalid Meta Graph object identifier"):
        MetaLeadAdsClient()._url(object_id)


async def test_unsubscribe_removes_the_page_leadgen_subscription() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert request.url.path.endswith("/page1/subscribed_apps")
        return httpx.Response(200, json={"success": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        await MetaLeadAdsClient(http_client).unsubscribe_page(
            {
                "page_id": "page1",
                "access_" + "token": "page-token",
            }
        )


class _FakeSpendClient:
    def __init__(self, amount: str) -> None:
        self.amount = amount

    async def fetch_campaign_spend(
        self, _credentials: dict[str, object]
    ) -> list[MetaCampaignSpend]:
        return [
            MetaCampaignSpend(
                campaign_id="campaign-live",
                campaign_name="Live Facebook Leads",
                amount=Decimal(self.amount),
                currency="USD",
                starts_on=date(2026, 8, 1),
                ends_on=date(2026, 8, 14),
            )
        ]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_spend_sync_upserts_one_provider_owned_campaign_row() -> None:
    async with AsyncSessionLocal() as db:
        workspace = Workspace(
            id=uuid.uuid4(),
            name="Meta Spend Test",
            slug=f"meta-spend-{uuid.uuid4().hex[:8]}",
        )
        db.add(workspace)
        await db.flush()
        integration = WorkspaceIntegration(
            workspace_id=workspace.id,
            integration_type="meta_lead_ads",
            credentials={
                "page_id": "page-sync",
                "access_" + "token": "page-token",
                "ad_account_id": "act_123",
            },
            is_active=True,
        )
        db.add(integration)
        await db.flush()

        first_count = await sync_meta_campaign_spend(
            db,
            integration,
            client=_FakeSpendClient("10.00"),  # type: ignore[arg-type]
        )
        second_count = await sync_meta_campaign_spend(
            db,
            integration,
            client=_FakeSpendClient("12.50"),  # type: ignore[arg-type]
        )

        row_count = (
            await db.execute(
                select(func.count(LeadSourceSpendEntry.id)).where(
                    LeadSourceSpendEntry.workspace_id == workspace.id
                )
            )
        ).scalar_one()
        entry = (
            await db.execute(
                select(LeadSourceSpendEntry).where(
                    LeadSourceSpendEntry.workspace_id == workspace.id
                )
            )
        ).scalar_one()
        campaign = (
            await db.execute(
                select(LeadSourceCampaign).where(LeadSourceCampaign.workspace_id == workspace.id)
            )
        ).scalar_one()
        assert first_count == second_count == 1
        assert row_count == 1
        assert entry.lead_source_campaign_id == campaign.id
        assert entry.notes == "meta-sync:campaign-live"
        assert float(entry.amount) == 12.5
        await db.rollback()
