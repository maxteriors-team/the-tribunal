"""Parent-origin validation and rate limiting for public embed requests."""

from datetime import UTC, datetime, timedelta
from urllib.parse import unquote, urlparse

from fastapi import HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.encryption import hash_phone
from app.core.rate_limit_helpers import raise_rate_limited
from app.models.demo_request import DemoRequest
from app.services.rate_limiting.embed_limiter import (
    enforce_chat_rate_limits,
    enforce_token_rate_limits,
)

EMBED_PARENT_ORIGIN_HEADER = "X-Embed-Parent-Origin"


def _normalize_http_origin(value: str | None) -> str | None:
    """Return a canonical HTTP(S) origin, rejecting URL-like impostors."""
    if not value or any(char.isspace() or ord(char) < 32 for char in value):
        return None
    if "\\" in value:
        return None

    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError:
        return None

    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        return None

    hostname = parsed.hostname.lower()
    serialized_host = f"[{hostname}]" if ":" in hostname else hostname
    default_port = 80 if parsed.scheme == "http" else 443
    port_suffix = f":{port}" if port is not None and port != default_port else ""
    return f"{parsed.scheme}://{serialized_host}{port_suffix}"


def _trusted_frontend_origins() -> set[str]:
    candidates = [settings.frontend_url, *settings.cors_origins]
    return {origin for value in candidates if (origin := _normalize_http_origin(value))}


def _is_same_origin_embed_fetch(
    request: Request,
    *,
    public_id: str,
    browser_origin: str | None,
) -> bool:
    """Verify a fetch made by our hosted ``/embed/{public_id}`` document."""
    if request.headers.get("sec-fetch-site", "").lower() != "same-origin":
        return False

    referer = request.headers.get("referer")
    try:
        parsed_referer = urlparse(referer or "")
    except ValueError:
        return False

    referer_origin = _normalize_http_origin(f"{parsed_referer.scheme}://{parsed_referer.netloc}")
    if referer_origin not in _trusted_frontend_origins():
        return False
    if browser_origin is not None and browser_origin != referer_origin:
        return False

    path_parts = parsed_referer.path.split("/")
    return len(path_parts) >= 3 and path_parts[1] == "embed" and unquote(path_parts[2]) == public_id


def verified_parent_origin(request: Request, *, public_id: str) -> str:
    """Return a browser-verified parent origin or fail closed with HTTP 403.

    A customer-page request must send a claim matching the browser-controlled
    ``Origin`` header. A same-origin API fetch from our iframe cannot carry the
    parent as ``Origin``; for that case, the claim is accepted only when Fetch
    Metadata and ``Referer`` prove the caller is our matching hosted embed page.
    """
    claimed_header = request.headers.get(EMBED_PARENT_ORIGIN_HEADER)
    claimed_origin = _normalize_http_origin(claimed_header)
    if claimed_origin is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Parent origin header required",
        )

    browser_origin_header = request.headers.get("origin")
    browser_origin = _normalize_http_origin(browser_origin_header)
    if browser_origin_header is not None and browser_origin is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Parent origin could not be verified",
        )

    if browser_origin == claimed_origin:
        return claimed_origin

    if _is_same_origin_embed_fetch(
        request,
        public_id=public_id,
        browser_origin=browser_origin,
    ):
        return claimed_origin

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Parent origin could not be verified",
    )


def is_origin_allowed(origin: str | None, allowed_domains: list[str]) -> bool:
    """Return whether a verified parent origin is configured for an embed agent."""
    normalized_origin = _normalize_http_origin(origin)
    if normalized_origin is None or not allowed_domains:
        return False

    host = urlparse(normalized_origin).hostname or ""
    if not host:
        return False

    host_lower = host.lower()
    for configured_domain in allowed_domains:
        domain = configured_domain.lower().strip().rstrip(".")
        if not domain:
            continue
        if host_lower == domain:
            return True
        if domain.startswith("*."):
            base_domain = domain[2:]
            if host_lower == base_domain or host_lower.endswith(f".{base_domain}"):
                return True

    return False


def enforce_allowed_origin(origin: str | None, allowed_domains: list[str]) -> None:
    """Raise 403 when an embed parent is not configured for the agent."""
    if not is_origin_allowed(origin, allowed_domains):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Parent origin not allowed",
        )


def _seconds_until_window_clears(
    oldest_created_at: datetime | None,
    window_seconds: int,
    now: datetime,
) -> int:
    """Compute seconds until a rolling database rate-limit window has room."""
    if oldest_created_at is None:
        return window_seconds
    if oldest_created_at.tzinfo is None:
        oldest_created_at = oldest_created_at.replace(tzinfo=UTC)
    expires_at = oldest_created_at + timedelta(seconds=window_seconds)
    remaining = int((expires_at - now).total_seconds())
    return max(1, remaining)


class EmbedAccessService:
    """Validate public embed callers and enforce per-endpoint limits."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def require_origin(self, origin: str | None, allowed_domains: list[str]) -> None:
        """Require an allowed browser origin for a public embed request."""
        enforce_allowed_origin(origin, allowed_domains)

    async def enforce_token_limit(self, *, client_ip: str, public_id: str) -> None:
        """Enforce OpenAI Realtime token mint limits."""
        await enforce_token_rate_limits(client_ip=client_ip, public_id=public_id)

    async def enforce_chat_limit(self, *, client_ip: str, public_id: str) -> None:
        """Enforce shared chat/tool/transcript limits."""
        await enforce_chat_rate_limits(client_ip=client_ip, public_id=public_id)

    async def enforce_phone_limit(self, *, client_ip: str, phone_number: str) -> None:
        """Enforce database-backed limits for call/text phone submissions."""
        if phone_number in settings.demo_rate_limit_bypass_phones:
            return

        now = datetime.now(UTC)
        hour_ago = now - timedelta(hours=1)
        day_ago = now - timedelta(days=1)
        hour_seconds = 3600
        day_seconds = 86400

        ip_count_result = await self.db.execute(
            select(func.count(), func.min(DemoRequest.created_at)).where(
                DemoRequest.client_ip == client_ip,
                DemoRequest.created_at >= hour_ago,
            )
        )
        ip_row = ip_count_result.one()
        ip_count = ip_row[0] or 0
        ip_oldest = ip_row[1]

        if ip_count >= settings.demo_ip_rate_limit:
            retry_after = _seconds_until_window_clears(ip_oldest, hour_seconds, now)
            raise_rate_limited(
                retry_after,
                detail="Rate limit exceeded. Please try again later.",
            )

        phone_count_result = await self.db.execute(
            select(func.count(), func.min(DemoRequest.created_at)).where(
                DemoRequest.phone_hash == hash_phone(phone_number),
                DemoRequest.created_at >= day_ago,
            )
        )
        phone_row = phone_count_result.one()
        phone_count = phone_row[0] or 0
        phone_oldest = phone_row[1]

        if phone_count >= settings.demo_phone_rate_limit:
            retry_after = _seconds_until_window_clears(phone_oldest, day_seconds, now)
            raise_rate_limited(
                retry_after,
                detail="This phone number has reached its daily limit. Please try again tomorrow.",
            )
