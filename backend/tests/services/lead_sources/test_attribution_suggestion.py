"""Unit tests for the lead-source attribution suggestion heuristic.

These exercise the pure ``suggest_source_type`` function with fabricated
tracking signals, so the channel-guessing logic is covered without a database.
"""

from app.models.lead_source import LeadSourceType
from app.services.lead_sources.attribution_service import (
    _AttributionSignals,
    suggest_source_type,
)


def test_gclid_implies_google_ads():
    signals = _AttributionSignals(gclid="abc123", utm_source="facebook")
    # Click id beats a conflicting utm_source.
    assert suggest_source_type(signals) == LeadSourceType.GOOGLE_ADS


def test_fbclid_implies_facebook_ads():
    assert (
        suggest_source_type(_AttributionSignals(fbclid="xyz789"))
        == LeadSourceType.FACEBOOK_ADS
    )


def test_utm_source_facebook_variants():
    for utm in ("facebook", "Instagram", "META", "fb", "ig"):
        assert (
            suggest_source_type(_AttributionSignals(utm_source=utm))
            == LeadSourceType.FACEBOOK_ADS
        )


def test_utm_source_google_variants():
    for utm in ("google", "AdWords", "gads"):
        assert (
            suggest_source_type(_AttributionSignals(utm_source=utm))
            == LeadSourceType.GOOGLE_ADS
        )


def test_utm_source_organic():
    for utm in ("organic", "seo", "direct", "referral"):
        assert (
            suggest_source_type(_AttributionSignals(utm_source=utm))
            == LeadSourceType.ORGANIC
        )


def test_legacy_source_phone_maps_to_phone_radio():
    for source in ("inbound_call", "phone", "call", "radio"):
        assert (
            suggest_source_type(_AttributionSignals(source=source))
            == LeadSourceType.PHONE_RADIO
        )


def test_no_signals_returns_none():
    assert suggest_source_type(_AttributionSignals()) is None
    # An unrecognized utm_source is inconclusive, not a wrong guess.
    assert suggest_source_type(_AttributionSignals(utm_source="newsletter")) is None
