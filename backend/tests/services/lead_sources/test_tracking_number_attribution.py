"""Tests for direct attribution from mapped inbound phone numbers."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.services.lead_sources.attribution_service import (
    TRACKING_NUMBER_ATTRIBUTION_CONFIDENCE,
    WEB_FORM_ATTRIBUTION_CONFIDENCE,
    WebAttributionInput,
    apply_tracking_number_attribution,
    apply_web_attribution,
    snapshot_contact_attribution_on_opportunity,
)


def _contact() -> SimpleNamespace:
    return SimpleNamespace(
        id=42,
        workspace_id=uuid.uuid4(),
        first_touch_lead_source_id=None,
        first_touch_lead_source_campaign_id=None,
        first_touch_at=None,
        latest_touch_lead_source_id=None,
        latest_touch_lead_source_campaign_id=None,
        latest_touch_at=None,
        attribution_confidence=None,
        utm_source=None,
        utm_medium=None,
        utm_campaign=None,
        utm_content=None,
        utm_term=None,
        gclid=None,
        fbclid=None,
        landing_page=None,
        referrer=None,
    )


def _db_with_opportunities(*opportunities: SimpleNamespace) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = list(opportunities)
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    return db


async def test_mapped_number_beats_utm_and_preserves_historical_attribution() -> None:
    contact = _contact()
    web_source_id = uuid.uuid4()
    web_campaign_id = uuid.uuid4()
    tracking_source_id = uuid.uuid4()
    tracking_campaign_id = uuid.uuid4()
    web_touch_at = datetime(2026, 1, 1, tzinfo=UTC)
    call_touch_at = datetime(2026, 2, 1, tzinfo=UTC)

    apply_web_attribution(
        contact,
        SimpleNamespace(id=web_source_id),
        WebAttributionInput(
            lead_source_campaign_id=web_campaign_id,
            utm_source="google",
        ),
        now=web_touch_at,
    )

    unattributed_opportunity = SimpleNamespace(
        lead_source_id=None,
        lead_source_campaign_id=None,
        attribution_confidence=None,
    )
    historical_opportunity = SimpleNamespace(
        lead_source_id=web_source_id,
        lead_source_campaign_id=web_campaign_id,
        attribution_confidence=WEB_FORM_ATTRIBUTION_CONFIDENCE,
    )
    db = _db_with_opportunities(unattributed_opportunity, historical_opportunity)
    tracking_number = SimpleNamespace(
        lead_source_id=tracking_source_id,
        lead_source_campaign_id=tracking_campaign_id,
    )

    applied = await apply_tracking_number_attribution(
        db,
        contact,
        tracking_number,
        now=call_touch_at,
    )

    assert applied is True
    assert TRACKING_NUMBER_ATTRIBUTION_CONFIDENCE > WEB_FORM_ATTRIBUTION_CONFIDENCE

    # First-touch remains the original web capture; the mapped call is latest-touch.
    assert contact.first_touch_lead_source_id == web_source_id
    assert contact.first_touch_lead_source_campaign_id == web_campaign_id
    assert contact.first_touch_at == web_touch_at
    assert contact.latest_touch_lead_source_id == tracking_source_id
    assert contact.latest_touch_lead_source_campaign_id == tracking_campaign_id
    assert contact.latest_touch_at == call_touch_at
    assert contact.attribution_confidence == TRACKING_NUMBER_ATTRIBUTION_CONFIDENCE
    assert contact.utm_source == "google"

    # A still-empty opportunity receives the call snapshot; historical data is immutable.
    assert unattributed_opportunity.lead_source_id == tracking_source_id
    assert unattributed_opportunity.lead_source_campaign_id == tracking_campaign_id
    assert unattributed_opportunity.attribution_confidence == TRACKING_NUMBER_ATTRIBUTION_CONFIDENCE
    assert historical_opportunity.lead_source_id == web_source_id
    assert historical_opportunity.lead_source_campaign_id == web_campaign_id
    assert historical_opportunity.attribution_confidence == WEB_FORM_ATTRIBUTION_CONFIDENCE


async def test_unmapped_number_leaves_existing_attribution_unchanged() -> None:
    contact = _contact()
    original_source_id = uuid.uuid4()
    original_touch_at = datetime(2026, 1, 1, tzinfo=UTC)
    contact.first_touch_lead_source_id = original_source_id
    contact.latest_touch_lead_source_id = original_source_id
    contact.first_touch_at = original_touch_at
    contact.latest_touch_at = original_touch_at
    contact.attribution_confidence = WEB_FORM_ATTRIBUTION_CONFIDENCE
    db = _db_with_opportunities()

    applied = await apply_tracking_number_attribution(
        db,
        contact,
        SimpleNamespace(lead_source_id=None, lead_source_campaign_id=None),
    )

    assert applied is False
    assert contact.first_touch_lead_source_id == original_source_id
    assert contact.latest_touch_lead_source_id == original_source_id
    assert contact.first_touch_at == original_touch_at
    assert contact.latest_touch_at == original_touch_at
    assert contact.attribution_confidence == WEB_FORM_ATTRIBUTION_CONFIDENCE
    db.execute.assert_not_awaited()


def test_new_opportunity_snapshots_contacts_latest_tracking_touch() -> None:
    contact = _contact()
    tracking_source_id = uuid.uuid4()
    tracking_campaign_id = uuid.uuid4()
    contact.first_touch_lead_source_id = uuid.uuid4()
    contact.latest_touch_lead_source_id = tracking_source_id
    contact.latest_touch_lead_source_campaign_id = tracking_campaign_id
    contact.attribution_confidence = TRACKING_NUMBER_ATTRIBUTION_CONFIDENCE
    opportunity = SimpleNamespace(
        lead_source_id=None,
        lead_source_campaign_id=None,
        attribution_confidence=None,
    )

    changed = snapshot_contact_attribution_on_opportunity(opportunity, contact)

    assert changed is True
    assert opportunity.lead_source_id == tracking_source_id
    assert opportunity.lead_source_campaign_id == tracking_campaign_id
    assert opportunity.attribution_confidence == TRACKING_NUMBER_ATTRIBUTION_CONFIDENCE
