"""Unit tests for apply_web_attribution.

Exercises the first/latest-touch stamping logic with a lightweight fake contact
so no database is required. Covers fresh capture, returning-contact behavior
(preserve first touch, refresh latest touch), tracking-field overwrite rules,
and confidence defaulting.
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from app.services.lead_sources.attribution_service import (
    WEB_FORM_ATTRIBUTION_CONFIDENCE,
    WebAttributionInput,
    apply_web_attribution,
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
    apply_web_attribution(
        contact, _lead_source(), WebAttributionInput(attribution_confidence=0.5)
    )
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
    apply_web_attribution(
        contact, source, WebAttributionInput(utm_source="google", gclid="abc123")
    )

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
