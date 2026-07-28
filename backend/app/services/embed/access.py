"""Origin validation and rate limiting for public embed requests."""

from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from fastapi import HTTPException, status
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


def is_origin_allowed(origin: str | None, allowed_domains: list[str]) -> bool:
    """Return whether an Origin header is allowed for an embed agent.

    Only browser ``Origin`` is accepted. ``Referer`` remains intentionally ignored
    because it is commonly omitted and is not a trustworthy security boundary.
    """
    if not origin or not allowed_domains:
        return False

    try:
        parsed = urlparse(origin)
    except ValueError:
        return False

    host = parsed.hostname or ""
    if not host:
        return False

    host_lower = host.lower()
    for configured_domain in allowed_domains:
        domain = configured_domain.lower().strip()
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
    """Raise 403 when an embed request origin is not configured for the agent."""
    if not is_origin_allowed(origin, allowed_domains):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Origin not allowed",
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
