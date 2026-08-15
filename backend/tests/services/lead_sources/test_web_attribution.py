"""Tests for web attribution stamping and server-side campaign resolution.

The stamping cases use lightweight contacts; the integration case proves an
untrusted campaign UUID cannot cross the source established by click signals.
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.db.session import AsyncSessionLocal, engine
from app.models.lead_source import LeadSource, LeadSourceCampaign, LeadSourceType
from app.models.workspace import Workspace
from app.services.lead_sources.attribution_service import (
    WEB_FORM_ATTRIBUTION_CONFIDENCE,
    WebAttributionInput,
    apply_web_attribution,
    resolve_web_attribution,
)


def _blank_contact() -> SimpleNamespace:
    """A contact with all attribution fields unset, mirroring the ORM columns."""
    return SimpleNamespace(
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


def _lead_source() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4())


def test_fresh_capture_sets_first_and_latest_touch():
    contact = _blank_contact()
    source = _lead_source()
    campaign_id = uuid.uuid4()
    now = datetime(2025, 1, 1, tzinfo=UTC)

    apply_web_attribution(
        contact,
        source,
        WebAttributionInput(
            lead_source_campaign_id=campaign_id,
            utm_source="google",
            gclid="abc123",
            landing_page="https://example.com/lp",
        ),
        now=now,
    )

    assert contact.first_touch_lead_source_id == source.id
    assert contact.first_touch_lead_source_campaign_id == campaign_id
    assert contact.first_touch_at == now
    assert contact.latest_touch_lead_source_id == source.id
    assert contact.latest_touch_at == now
    assert contact.utm_source == "google"
    assert contact.gclid == "abc123"
    assert contact.landing_page == "https://example.com/lp"


def test_default_confidence_when_unspecified():
    contact = _blank_contact()
    apply_web_attribution(contact, _lead_source(), WebAttributionInput())
    assert contact.attribution_confidence == WEB_FORM_ATTRIBUTION_CONFIDENCE


def test_explicit_confidence_is_respected():
    contact = _blank_contact()
    apply_web_attribution(contact, _lead_source(), WebAttributionInput(attribution_confidence=0.5))
    assert contact.attribution_confidence == 0.5


def test_returning_contact_preserves_first_touch_but_refreshes_latest():
    contact = _blank_contact()
    first_source = _lead_source()
    first_time = datetime(2025, 1, 1, tzinfo=UTC)
    apply_web_attribution(contact, first_source, WebAttributionInput(), now=first_time)

    second_source = _lead_source()
    second_time = datetime(2025, 2, 1, tzinfo=UTC)
    apply_web_attribution(contact, second_source, WebAttributionInput(), now=second_time)

    # First touch is sticky.
    assert contact.first_touch_lead_source_id == first_source.id
    assert contact.first_touch_at == first_time
    # Latest touch follows the most recent submission.
    assert contact.latest_touch_lead_source_id == second_source.id
    assert contact.latest_touch_at == second_time


def test_blank_submission_does_not_erase_existing_tracking_fields():
    contact = _blank_contact()
    source = _lead_source()
    apply_web_attribution(contact, source, WebAttributionInput(utm_source="google", gclid="abc123"))

    # A later submission with no tracking signal must not wipe the captured ids.
    apply_web_attribution(contact, source, WebAttributionInput())

    assert contact.utm_source == "google"
    assert contact.gclid == "abc123"


def test_tracking_fields_update_when_new_values_present():
    contact = _blank_contact()
    source = _lead_source()
    apply_web_attribution(contact, source, WebAttributionInput(utm_source="google"))
    apply_web_attribution(contact, source, WebAttributionInput(utm_source="facebook"))
    assert contact.utm_source == "facebook"


@pytest.fixture
async def _fresh_engine_pool():
    """Keep shared asyncpg connections on this test's event loop."""
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_campaign_uuid_must_belong_to_the_resolved_source(_fresh_engine_pool) -> None:
    async with AsyncSessionLocal() as db:
        workspace = Workspace(name="Attribution resolution", slug=f"attr-{uuid.uuid4().hex[:8]}")
        db.add(workspace)
        await db.flush()

        capture_source = LeadSource(
            workspace_id=workspace.id,
            name="Website",
            public_key=uuid.uuid4().hex[:20],
            source_type=LeadSourceType.OTHER,
            allowed_domains=[],
            action_config={},
        )
        facebook_source = LeadSource(
            workspace_id=workspace.id,
            name="Facebook Ads",
            public_key=uuid.uuid4().hex[:20],
            source_type=LeadSourceType.FACEBOOK_ADS,
            allowed_domains=[],
            action_config={},
        )
        db.add_all([capture_source, facebook_source])
        await db.flush()
        facebook_campaign = LeadSourceCampaign(
            workspace_id=workspace.id,
            lead_source_id=facebook_source.id,
            name="Summer Facebook",
            platform_campaign_id=f"meta-{uuid.uuid4().hex}",
            campaign_metadata={},
        )
        db.add(facebook_campaign)
        await db.flush()

        unverified = await resolve_web_attribution(
            db,
            workspace_id=workspace.id,
            capture_source=capture_source,
            requested_campaign_id=facebook_campaign.id,
            utm_source=None,
            utm_campaign=None,
            fbclid=None,
            gclid=None,
        )
        assert unverified.lead_source.id == capture_source.id
        assert unverified.campaign_id is None

        verified = await resolve_web_attribution(
            db,
            workspace_id=workspace.id,
            capture_source=capture_source,
            requested_campaign_id=facebook_campaign.id,
            utm_source=None,
            utm_campaign=None,
            fbclid="verified-click-id",
            gclid=None,
        )
        assert verified.lead_source.id == facebook_source.id
        assert verified.campaign_id == facebook_campaign.id

        await db.rollback()
