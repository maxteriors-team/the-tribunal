"""Tests for lead-source attribution and ROI schemas."""

import uuid
from datetime import date, datetime

import pytest
from pydantic import ValidationError

from app.models.lead_source import LeadSourceType
from app.schemas.contact import ContactUpdate
from app.schemas.lead_source import (
    AttributionConfidenceLevel,
    AttributionConfidenceSummary,
    LeadSourceCampaignCreate,
    LeadSourceCreate,
    LeadSourceResponse,
    LeadSourceROIStats,
    LeadSourceSpendEntryCreate,
    LeadSourceWinnerSummary,
    SourceROIRow,
)
from app.schemas.opportunity import OpportunityUpdate


class TestLeadSourceSchemas:
    """Lead-source schemas remain backward-compatible while exposing source type."""

    def test_create_defaults_to_other_source_type(self) -> None:
        lead_source = LeadSourceCreate(name="Website", allowed_domains=["example.com"])

        assert lead_source.source_type is LeadSourceType.OTHER
        assert lead_source.action == "collect"

    def test_create_accepts_ranked_source_type(self) -> None:
        lead_source = LeadSourceCreate(name="Meta", source_type="facebook_ads")

        assert lead_source.source_type is LeadSourceType.FACEBOOK_ADS

    def test_response_keeps_legacy_instantiation_compatible(self) -> None:
        now = datetime.now()
        response = LeadSourceResponse(
            id=uuid.uuid4(),
            workspace_id=uuid.uuid4(),
            name="Legacy",
            public_key="ls_abc12345",
            allowed_domains=[],
            enabled=True,
            action="collect",
            action_config={},
            created_at=now,
            updated_at=now,
        )

        assert response.source_type is LeadSourceType.OTHER
        assert response.endpoint_url == ""


class TestLeadSourceCampaignSchemas:
    """Campaign schemas validate provider IDs and flight windows."""

    def test_campaign_create_validates_date_range(self) -> None:
        with pytest.raises(ValidationError):
            LeadSourceCampaignCreate(
                lead_source_id=uuid.uuid4(),
                name="Summer Google",
                started_on=date(2026, 7, 1),
                ended_on=date(2026, 6, 30),
            )

    def test_campaign_create_accepts_metadata(self) -> None:
        campaign = LeadSourceCampaignCreate(
            lead_source_id=uuid.uuid4(),
            name="Summer Google",
            platform_campaign_id="123",
            campaign_metadata={"network": "search"},
        )

        assert campaign.platform_campaign_id == "123"
        assert campaign.campaign_metadata == {"network": "search"}


class TestLeadSourceSpendEntrySchemas:
    """Ad spend schemas normalize money metadata and reject invalid ranges."""

    def test_spend_entry_normalizes_currency(self) -> None:
        spend = LeadSourceSpendEntryCreate(
            lead_source_id=uuid.uuid4(),
            spend_starts_on=date(2026, 6, 1),
            spend_ends_on=date(2026, 6, 30),
            amount=2500,
            currency="usd",
        )

        assert spend.currency == "USD"
        assert spend.amount == 2500

    def test_spend_entry_rejects_negative_amount(self) -> None:
        with pytest.raises(ValidationError):
            LeadSourceSpendEntryCreate(
                lead_source_id=uuid.uuid4(),
                spend_starts_on=date(2026, 6, 1),
                spend_ends_on=date(2026, 6, 30),
                amount=-1,
            )

    def test_spend_entry_rejects_reversed_dates(self) -> None:
        with pytest.raises(ValidationError):
            LeadSourceSpendEntryCreate(
                lead_source_id=uuid.uuid4(),
                spend_starts_on=date(2026, 6, 30),
                spend_ends_on=date(2026, 6, 1),
                amount=100,
            )


class TestLeadAttributionSchemas:
    """Contact and opportunity schemas expose attribution with bounded confidence."""

    def test_contact_update_accepts_attribution_fields(self) -> None:
        source_id = uuid.uuid4()
        update = ContactUpdate(
            first_touch_lead_source_id=source_id,
            attribution_confidence=0.82,
            utm_source="google",
            landing_page="https://example.com/offer",
        )

        assert update.first_touch_lead_source_id == source_id
        assert update.attribution_confidence == 0.82

    def test_opportunity_update_accepts_closed_won_attribution_snapshot(self) -> None:
        source_id = uuid.uuid4()
        update = OpportunityUpdate(
            lead_source_id=source_id,
            lead_source_campaign_id=uuid.uuid4(),
            attribution_confidence=1.0,
        )

        assert update.lead_source_id == source_id
        assert update.attribution_confidence == 1.0

    def test_attribution_confidence_rejects_above_one(self) -> None:
        with pytest.raises(ValidationError):
            ContactUpdate(attribution_confidence=1.01)


class TestLeadSourceROISchemas:
    """Dashboard ROI schemas describe ranked rows plus the winner card."""

    def test_roi_stats_defaults_to_ranked_source_types(self) -> None:
        stats = LeadSourceROIStats()

        assert stats.source_types_ranked == [
            LeadSourceType.FACEBOOK_ADS,
            LeadSourceType.GOOGLE_ADS,
            LeadSourceType.ORGANIC,
            LeadSourceType.PHONE_RADIO,
        ]
        assert stats.winner.has_winner is False

    def test_roi_row_and_winner_summary_accept_confidence_rollup(self) -> None:
        source_id = uuid.uuid4()
        confidence = AttributionConfidenceSummary(
            average_score=0.9,
            level=AttributionConfidenceLevel.HIGH,
            attributed_closed_won_jobs=4,
            total_closed_won_jobs=5,
        )
        row = SourceROIRow(
            rank=1,
            source_type=LeadSourceType.GOOGLE_ADS,
            source_name="Google Ads",
            lead_source_id=source_id,
            spend=1000,
            closed_won_jobs=5,
            closed_won_revenue=10000,
            roi_multiple=10,
            net_revenue=9000,
            currency="usd",
            attribution_confidence=confidence,
            is_winner=True,
        )
        winner = LeadSourceWinnerSummary(
            has_winner=True,
            source_type=row.source_type,
            source_name=row.source_name,
            lead_source_id=row.lead_source_id,
            rank_by="roi",
            spend=row.spend,
            closed_won_jobs=row.closed_won_jobs,
            closed_won_revenue=row.closed_won_revenue,
            roi_multiple=row.roi_multiple,
            net_revenue=row.net_revenue,
            currency="usd",
            reason="Google Ads has the highest ROI.",
            attribution_confidence=confidence,
        )

        assert row.currency == "USD"
        assert row.attribution_confidence.level is AttributionConfidenceLevel.HIGH
        assert winner.currency == "USD"
        assert winner.source_type is LeadSourceType.GOOGLE_ADS
