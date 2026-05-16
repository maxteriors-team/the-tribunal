"""Tests for ``embed_limiter`` — Retry-After contract on the 429 path.

The embed endpoints are unauthenticated and expensive; clients need a real
``Retry-After`` to back off without retry storms.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.services.rate_limiting import embed_limiter


class TestEnforceEmbedRateLimit:
    async def test_allows_under_limit(self) -> None:
        async def fake_check(
            scope: str, identifier: str, limit: int, window_seconds: int
        ) -> tuple[bool, int]:
            del scope, identifier, limit, window_seconds
            return True, 1

        with patch.object(embed_limiter, "_check_and_increment", new=fake_check):
            # Must not raise.
            await embed_limiter.enforce_embed_rate_limit(
                scope="token:ip",
                identifier="1.2.3.4",
                limit=10,
                window_seconds=3600,
            )

    async def test_raises_429_with_retry_after_from_redis_ttl(self) -> None:
        """When Redis reports a live TTL on the limiter key, ``Retry-After``
        must reflect that remaining-window value (clients don't sleep longer
        than necessary)."""

        async def fake_check(
            scope: str, identifier: str, limit: int, window_seconds: int
        ) -> tuple[bool, int]:
            del scope, identifier, limit, window_seconds
            return False, 999

        fake_redis = AsyncMock()
        fake_redis.ttl = AsyncMock(return_value=137)

        async def fake_get_redis() -> AsyncMock:
            return fake_redis

        with (
            patch.object(embed_limiter, "_check_and_increment", new=fake_check),
            patch.object(embed_limiter, "get_redis", new=fake_get_redis),
            pytest.raises(HTTPException) as exc_info,
        ):
            await embed_limiter.enforce_embed_rate_limit(
                scope="token:ip",
                identifier="1.2.3.4",
                limit=10,
                window_seconds=3600,
            )

        assert exc_info.value.status_code == 429
        assert exc_info.value.headers is not None
        assert exc_info.value.headers["Retry-After"] == "137"

    async def test_retry_after_falls_back_to_window_when_ttl_unavailable(
        self,
    ) -> None:
        """Missing key (TTL=-2) or no-expire (TTL=-1) must fall back to the
        configured window — never produce a 0 or negative header value."""

        async def fake_check(
            scope: str, identifier: str, limit: int, window_seconds: int
        ) -> tuple[bool, int]:
            del scope, identifier, limit, window_seconds
            return False, 50

        fake_redis = AsyncMock()
        fake_redis.ttl = AsyncMock(return_value=-2)

        async def fake_get_redis() -> AsyncMock:
            return fake_redis

        with (
            patch.object(embed_limiter, "_check_and_increment", new=fake_check),
            patch.object(embed_limiter, "get_redis", new=fake_get_redis),
            pytest.raises(HTTPException) as exc_info,
        ):
            await embed_limiter.enforce_embed_rate_limit(
                scope="chat:ip",
                identifier="9.9.9.9",
                limit=60,
                window_seconds=3600,
            )

        assert exc_info.value.headers is not None
        assert exc_info.value.headers["Retry-After"] == "3600"

    async def test_retry_after_falls_back_on_ttl_redis_error(self) -> None:
        """A Redis hiccup on the TTL roundtrip must not erase the header —
        callers always get a positive ``Retry-After``."""

        async def fake_check(
            scope: str, identifier: str, limit: int, window_seconds: int
        ) -> tuple[bool, int]:
            del scope, identifier, limit, window_seconds
            return False, 99

        fake_redis = AsyncMock()
        fake_redis.ttl = AsyncMock(side_effect=RuntimeError("redis blip"))

        async def fake_get_redis() -> AsyncMock:
            return fake_redis

        with (
            patch.object(embed_limiter, "_check_and_increment", new=fake_check),
            patch.object(embed_limiter, "get_redis", new=fake_get_redis),
            pytest.raises(HTTPException) as exc_info,
        ):
            await embed_limiter.enforce_embed_rate_limit(
                scope="chat:public_id",
                identifier="abc",
                limit=60,
                window_seconds=3600,
            )

        assert exc_info.value.status_code == 429
        assert exc_info.value.headers is not None
        assert int(exc_info.value.headers["Retry-After"]) > 0

    async def test_fails_open_on_check_redis_error(self) -> None:
        """A Redis outage on the increment path must not lock callers out."""

        async def boom(
            scope: str, identifier: str, limit: int, window_seconds: int
        ) -> tuple[bool, int]:
            del scope, identifier, limit, window_seconds
            raise RuntimeError("redis down")

        with patch.object(embed_limiter, "_check_and_increment", new=boom):
            # Must NOT raise.
            await embed_limiter.enforce_embed_rate_limit(
                scope="token:ip",
                identifier="1.1.1.1",
                limit=10,
                window_seconds=3600,
            )
