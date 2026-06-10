"""Config-gated email-finder adapter (Hunter / Apollo).

Optional enrichment step: given a domain (and optionally a name), ask a
third-party email-finder for a likely contact email. Off unless
``email_finder_provider`` + ``email_finder_api_key`` are configured; returns
``None`` when disabled so callers degrade gracefully to traced/public emails.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import structlog

from app.core.config import settings

logger = structlog.get_logger()


@dataclass(slots=True)
class FoundEmail:
    """An email returned by a third-party finder."""

    email: str
    confidence: int | None = None
    source: str = "email_finder"


def is_enabled() -> bool:
    """Whether an email-finder provider is configured."""
    return bool(settings.email_finder_provider and settings.email_finder_api_key)


async def find_email_for_domain(
    domain: str,
    *,
    full_name: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> FoundEmail | None:
    """Look up a likely email for ``domain`` via the configured provider.

    Supports ``hunter`` (Domain/Email Finder) and ``apollo`` shapes. Returns
    ``None`` on any failure or when disabled — never raises into the caller.
    """
    if not is_enabled() or not domain:
        return None

    provider = settings.email_finder_provider.lower()
    own_client = client is None
    http = client or httpx.AsyncClient(timeout=httpx.Timeout(15.0))
    try:
        if provider == "hunter":
            return await _hunter(http, domain, full_name)
        if provider == "apollo":
            return await _apollo(http, domain, full_name)
        logger.warning("email_finder_unknown_provider", provider=provider)
        return None
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        logger.info("email_finder_failed", provider=provider, error=type(exc).__name__)
        return None
    finally:
        if own_client:
            await http.aclose()


async def _hunter(
    client: httpx.AsyncClient, domain: str, full_name: str | None
) -> FoundEmail | None:
    params = {"domain": domain, "api_key": settings.email_finder_api_key}
    if full_name:
        params["full_name"] = full_name
    endpoint = "email-finder" if full_name else "domain-search"
    response = await client.get(f"https://api.hunter.io/v2/{endpoint}", params=params)
    if response.status_code != 200:
        return None
    data = (response.json() or {}).get("data") or {}
    if full_name:
        email = data.get("email")
        if not email:
            return None
        return FoundEmail(email=email, confidence=data.get("score"), source="hunter")
    emails = data.get("emails") or []
    if emails and isinstance(emails, list):
        first = emails[0]
        email = first.get("value")
        if not email:
            return None
        return FoundEmail(email=email, confidence=first.get("confidence"), source="hunter")
    return None


async def _apollo(
    client: httpx.AsyncClient, domain: str, full_name: str | None
) -> FoundEmail | None:
    payload: dict[str, object] = {"api_key": settings.email_finder_api_key, "domain": domain}
    if full_name:
        payload["name"] = full_name
    response = await client.post("https://api.apollo.io/v1/people/match", json=payload)
    if response.status_code != 200:
        return None
    person = (response.json() or {}).get("person") or {}
    email = person.get("email")
    return FoundEmail(email=email, source="apollo") if email else None
