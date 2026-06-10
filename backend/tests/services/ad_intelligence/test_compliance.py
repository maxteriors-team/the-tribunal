"""Tests for ad-library compliance guardrails."""

from __future__ import annotations

import pytest

from app.services.ad_intelligence import compliance
from app.services.ad_intelligence.errors import AdLibraryProviderUnavailableError


def test_raw_scrape_blocked_by_default(monkeypatch) -> None:
    monkeypatch.setattr(compliance.settings, "ad_library_allow_raw_scrape", False, raising=False)
    with pytest.raises(AdLibraryProviderUnavailableError):
        compliance.ensure_raw_scrape_allowed("test")


def test_raw_scrape_allowed_when_flagged(monkeypatch) -> None:
    monkeypatch.setattr(compliance.settings, "ad_library_allow_raw_scrape", True, raising=False)
    # Should not raise.
    compliance.ensure_raw_scrape_allowed("test")


def test_redact_snapshot_url_strips_token() -> None:
    url = "https://www.facebook.com/ads/archive/render_ad/?id=123&access_token=SECRET"
    redacted = compliance.redact_snapshot_url(url)
    assert redacted is not None
    assert "SECRET" not in redacted
    assert "access_token" not in redacted
    assert redacted.startswith("https://www.facebook.com/ads/archive/render_ad/")


def test_redact_snapshot_url_handles_none() -> None:
    assert compliance.redact_snapshot_url(None) is None


def test_snapshot_rendering_flag(monkeypatch) -> None:
    monkeypatch.setattr(
        compliance.settings, "ad_library_snapshot_rendering_enabled", False, raising=False
    )
    assert compliance.is_snapshot_rendering_enabled() is False
    monkeypatch.setattr(
        compliance.settings, "ad_library_snapshot_rendering_enabled", True, raising=False
    )
    assert compliance.is_snapshot_rendering_enabled() is True
