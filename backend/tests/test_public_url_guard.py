"""The deployed environment must not ship localhost customer links.

Regression guard for a silent production failure: ``PUBLIC_BASE_URL`` defaults to
``http://localhost:8000``, so every tracked short link in an outbound SMS was
prefixed with localhost. Telnyx reported ``delivered``, the operator saw success,
and the customer got a link their phone could not open. Real proposals went out
that way before this check existed.
"""

import pytest
import structlog

from app.core.config import settings
from app.main import _validate_public_urls

log = structlog.get_logger()


def test_localhost_sms_prefix_stops_a_deployed_boot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "public_base_url", "http://localhost:8000")
    monkeypatch.setattr(settings, "frontend_url", "https://app.example.com")

    with pytest.raises(RuntimeError, match="PUBLIC_BASE_URL"):
        _validate_public_urls(log)


def test_localhost_email_link_stops_a_deployed_boot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "public_base_url", "https://api.example.com")
    monkeypatch.setattr(settings, "frontend_url", "http://127.0.0.1:3000")

    with pytest.raises(RuntimeError, match="FRONTEND_URL"):
        _validate_public_urls(log)


def test_blank_public_url_stops_a_deployed_boot(monkeypatch: pytest.MonkeyPatch) -> None:
    """A cleared variable yields `/r/abc`, which resolves nowhere.

    The likeliest moment to clear one of these is a domain migration.
    """
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "public_base_url", "   ")
    monkeypatch.setattr(settings, "frontend_url", "https://app.example.com")

    with pytest.raises(RuntimeError, match="empty"):
        _validate_public_urls(log)


def test_schemeless_public_url_stops_a_deployed_boot(monkeypatch: pytest.MonkeyPatch) -> None:
    """`example.com` (no scheme) yields `example.com/r/abc`.

    Phones often refuse to linkify that, and the shortener's "already our
    domain" check reads an empty netloc and re-shortens its own links. This is
    the classic typo when repointing at a new custom domain.
    """
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "public_base_url", "api.maxteriorslighting.com")
    monkeypatch.setattr(settings, "frontend_url", "https://app.example.com")

    with pytest.raises(RuntimeError, match="scheme"):
        _validate_public_urls(log)


def test_a_future_custom_domain_boots_fine(monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard checks reachability, not a specific hostname.

    Moving off the railway/vercel hostnames must not require a code change.
    """
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "public_base_url", "https://api.maxteriorslighting.com")
    monkeypatch.setattr(settings, "frontend_url", "https://app.maxteriorslighting.com")

    _validate_public_urls(log)


def test_real_public_urls_boot_fine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "public_base_url", "https://api.example.com")
    monkeypatch.setattr(settings, "frontend_url", "https://app.example.com")

    _validate_public_urls(log)


def test_local_development_still_uses_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    """Developers keep localhost defaults; the guard only applies once deployed."""
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "public_base_url", "http://localhost:8000")
    monkeypatch.setattr(settings, "frontend_url", "http://localhost:3000")

    _validate_public_urls(log)
