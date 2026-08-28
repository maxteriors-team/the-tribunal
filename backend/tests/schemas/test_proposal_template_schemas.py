"""Tests for proposal-template branding schemas.

The logo is operator-supplied and renders as ``<img src>`` on the public,
unauthenticated proposal page and in outbound receipt email, so its scheme is
constrained at both boundaries: rejected on write, dropped on read.
"""

import pytest
from pydantic import ValidationError

from app.schemas.proposal import ProposalTemplateSettings, ProposalTemplateUpdate

# Values that must never reach an ``<img src>``. Case and padding are varied
# deliberately: a naive ``startswith("javascript:")`` check passes the plain
# form and lets the other two through.
NON_HTTP_LOGOS = [
    "javascript:alert(1)",
    "JaVaScRiPt:alert(1)",
    "   javascript:alert(1)   ",
    "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=",
    "ftp://example.com/logo.png",
    "//example.com/logo.png",
]


@pytest.mark.parametrize("value", NON_HTTP_LOGOS)
def test_update_rejects_non_http_logo_url(value: str) -> None:
    """A bad scheme is a 422 at the edge, not a stored value."""
    with pytest.raises(ValidationError):
        ProposalTemplateUpdate(logo_url=value)


@pytest.mark.parametrize(
    "value",
    [
        "https://cdn.example.com/logo.png",
        "http://localhost:8000/static/brand/maxteriors-logo.png",
        "HTTPS://CDN.EXAMPLE.COM/logo.png",
    ],
)
def test_update_accepts_http_logo_url(value: str) -> None:
    assert ProposalTemplateUpdate(logo_url=value).logo_url == value.strip()


def test_update_allows_omitting_or_clearing_the_logo() -> None:
    assert ProposalTemplateUpdate().logo_url is None
    assert ProposalTemplateUpdate(logo_url=None).logo_url is None


@pytest.mark.parametrize("value", NON_HTTP_LOGOS)
def test_settings_read_drops_non_http_logo_without_raising(value: str) -> None:
    """Legacy rows predate write validation, so the read path fails closed.

    Dropping to ``None`` rather than raising matters: this schema is read on
    every proposal render, and a stored bad value must not 500 the page.
    """
    assert ProposalTemplateSettings(logo_url=value).logo_url is None


def test_settings_read_keeps_a_valid_logo() -> None:
    settings = ProposalTemplateSettings(logo_url="https://cdn.example.com/logo.png")
    assert settings.logo_url == "https://cdn.example.com/logo.png"


def test_settings_read_treats_blank_logo_as_absent() -> None:
    assert ProposalTemplateSettings(logo_url="   ").logo_url is None
