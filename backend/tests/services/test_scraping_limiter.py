"""Unit tests for the per-workspace Google Places scraping rate limiter.

Covers the pure-function helpers and the ``enforce_scraping_rate_limit``
contract: it must raise 429 with a numeric ``Retry-After`` header when either
the hourly or daily quota is exhausted, and must fail-open on Redis errors.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.services.rate_limiting import scraping_limiter


class TestBucketHelpers:
    """Bucket strings must be deterministic and Redis-key-safe."""

    def test_hour_bucket_format(self) -> None:
        now = datetime(2026, 5, 14, 9, 37, 12, tzinfo=UTC)
        assert scraping_limiter._hour_bucket(now) == "2026051409"

    def test_day_bucket_format(self) -> None:
        now = datetime(2026, 5, 14, 9, 37, 12, tzinfo=UTC)
        assert scraping_limiter._day_bucket(now) == "20260514"

    def test_seconds_until_next_hour_midmorning(self) -> None:
        # 09:37:00 → 23 minutes = 1380 seconds until 10:00:00.
        now = datetime(2026, 5, 14, 9, 37, 0, tzinfo=UTC)
        assert scraping_limiter._seconds_until_next_hour(now) == 23 * 60

    def test_seconds_until_midnight_midday(self) -> None:
        # 09:00:00 → 15 hours until next midnight.
        now = datetime(2026, 5, 14, 9, 0, 0, tzinfo=UTC)
        assert scraping_limiter._seconds_until_midnight(now) == 15 * 3600

    def test_seconds_helpers_never_zero(self) -> None:
        # Even on a window boundary we must return a positive TTL so Redis
        # doesn't get a 0-second EXPIRE (which would delete the key).
        boundary = datetime(2026, 5, 14, 10, 0, 0, tzinfo=UTC)
        assert scraping_limiter._seconds_until_next_hour(boundary) >= 1
        assert scraping_limiter._seconds_until_midnight(boundary) >= 1


class TestEnforceScrapingRateLimit:
    """``enforce_scraping_rate_limit`` is the public contract."""

    async def test_allows_when_under_both_limits(self) -> None:
        workspace_id = uuid.uuid4()

        async def fake_check(key: str, limit: int, expire_seconds: int) -> tuple[bool, int]:
            del key, limit, expire_seconds
            return True, 1

        with patch.object(scraping_limiter, "_check_and_increment", new=fake_check):
            # Must not raise.
            await scraping_limiter.enforce_scraping_rate_limit(workspace_id)

    async def test_raises_429_with_retry_after_when_hourly_exhausted(
        self,
    ) -> None:
        workspace_id = uuid.uuid4()

        async def fake_check(key: str, limit: int, expire_seconds: int) -> tuple[bool, int]:
            # First call is the hourly window — reject it.
            del limit, expire_seconds
            assert ":hour:" in key
            return False, 999

        with (
            patch.object(scraping_limiter, "_check_and_increment", new=fake_check),
            pytest.raises(HTTPException) as exc_info,
        ):
            await scraping_limiter.enforce_scraping_rate_limit(workspace_id)

        assert exc_info.value.status_code == 429
        assert exc_info.value.headers is not None
        retry_after = exc_info.value.headers.get("Retry-After")
        assert retry_after is not None
        # Must be an integer string representing a positive duration.
        assert int(retry_after) > 0
        assert "Hourly" in exc_info.value.detail

    async def test_raises_429_with_retry_after_when_daily_exhausted(
        self,
    ) -> None:
        workspace_id = uuid.uuid4()
        calls: list[str] = []

        async def fake_check(key: str, limit: int, expire_seconds: int) -> tuple[bool, int]:
            del limit, expire_seconds
            calls.append(key)
            # Hour check passes, day check fails.
            if ":hour:" in key:
                return True, 5
            return False, 101

        with (
            patch.object(scraping_limiter, "_check_and_increment", new=fake_check),
            pytest.raises(HTTPException) as exc_info,
        ):
            await scraping_limiter.enforce_scraping_rate_limit(workspace_id)

        # Both windows were consulted.
        assert any(":hour:" in k for k in calls)
        assert any(":day:" in k for k in calls)

        assert exc_info.value.status_code == 429
        assert exc_info.value.headers is not None
        retry_after = exc_info.value.headers.get("Retry-After")
        assert retry_after is not None
        assert int(retry_after) > 0
        assert "Daily" in exc_info.value.detail

    async def test_fails_open_on_redis_error(self) -> None:
        """A Redis outage must not lock every workspace out of search."""
        workspace_id = uuid.uuid4()

        async def boom(key: str, limit: int, expire_seconds: int) -> tuple[bool, int]:
            del key, limit, expire_seconds
            raise RuntimeError("redis down")

        with patch.object(scraping_limiter, "_check_and_increment", new=boom):
            # Must NOT raise.
            await scraping_limiter.enforce_scraping_rate_limit(workspace_id)

    async def test_uses_canonical_redis_key_format(self) -> None:
        """Key format is part of the API contract for ops dashboards."""
        workspace_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
        captured: list[str] = []

        async def fake_check(key: str, limit: int, expire_seconds: int) -> tuple[bool, int]:
            del limit, expire_seconds
            captured.append(key)
            return True, 1

        with patch.object(scraping_limiter, "_check_and_increment", new=fake_check):
            await scraping_limiter.enforce_scraping_rate_limit(workspace_id)

        assert len(captured) == 2
        hour_key, day_key = captured
        assert hour_key.startswith(f"scraping:ws:{workspace_id}:hour:")
        assert day_key.startswith(f"scraping:ws:{workspace_id}:day:")

    async def test_respects_custom_limits(self) -> None:
        """Callers can pass smaller caps for stricter workspaces/tiers."""
        workspace_id = uuid.uuid4()
        observed_limits: list[int] = []

        async def fake_check(key: str, limit: int, expire_seconds: int) -> tuple[bool, int]:
            del key, expire_seconds
            observed_limits.append(limit)
            return True, 1

        with patch.object(scraping_limiter, "_check_and_increment", new=fake_check):
            await scraping_limiter.enforce_scraping_rate_limit(
                workspace_id, hourly_limit=5, daily_limit=25
            )

        assert observed_limits == [5, 25]


class TestDefaultLimits:
    """The product spec is 20/hour, 100/day — pin those values."""

    def test_hourly_default_is_20(self) -> None:
        assert scraping_limiter.SCRAPING_HOURLY_LIMIT == 20

    def test_daily_default_is_100(self) -> None:
        assert scraping_limiter.SCRAPING_DAILY_LIMIT == 100
