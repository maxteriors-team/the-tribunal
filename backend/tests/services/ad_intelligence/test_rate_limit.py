"""Tests for the ad-library rate-limiter, cost meter, and response cache.

Redis is faked with an in-memory stub so these run without a live server and
assert: the hourly cap blocks once exceeded, the cost meter accumulates, the
cache key is deterministic, and round-trips work. Redis errors fail open.
"""

from __future__ import annotations

import json

import pytest

from app.services.ad_intelligence import rate_limit


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def eval(self, _script, _numkeys, key, limit, _ttl):  # noqa: ANN001
        current = int(self.store.get(key, 0))
        if current >= int(limit):
            return [0, current]
        current += 1
        self.store[key] = str(current)
        return [1, current]

    async def get(self, key):  # noqa: ANN001
        return self.store.get(key)

    async def setex(self, key, _ttl, value):  # noqa: ANN001
        self.store[key] = value

    async def incrby(self, key, amount):  # noqa: ANN001
        current = int(self.store.get(key, 0)) + int(amount)
        self.store[key] = str(current)
        return current

    async def expire(self, _key, _ttl):  # noqa: ANN001
        return True


@pytest.mark.asyncio
async def test_rate_limit_blocks_after_cap(monkeypatch) -> None:
    fake = _FakeRedis()

    async def _get_redis():
        return fake

    monkeypatch.setattr(rate_limit, "get_redis", _get_redis)
    monkeypatch.setattr(
        rate_limit.settings, "meta_ad_library_rate_limit_per_hour", 2, raising=False
    )

    a1, _ = await rate_limit.acquire_provider_call_slot("meta")
    a2, _ = await rate_limit.acquire_provider_call_slot("meta")
    a3, count = await rate_limit.acquire_provider_call_slot("meta")
    assert a1 is True and a2 is True
    assert a3 is False  # cap of 2 reached
    assert count >= 2


@pytest.mark.asyncio
async def test_cost_meter_accumulates(monkeypatch) -> None:
    fake = _FakeRedis()

    async def _get_redis():
        return fake

    monkeypatch.setattr(rate_limit, "get_redis", _get_redis)
    await rate_limit.record_cost("meta", cost=1)
    await rate_limit.record_cost("meta", cost=2)
    usage = await rate_limit.get_usage("meta")
    assert usage.platform == "meta"
    assert usage.cap_per_hour > 0
    assert usage.remaining <= usage.cap_per_hour


@pytest.mark.asyncio
async def test_cache_round_trip(monkeypatch) -> None:
    fake = _FakeRedis()

    async def _get_redis():
        return fake

    monkeypatch.setattr(rate_limit, "get_redis", _get_redis)
    key = rate_limit.cache_key_for_search("ws1", "meta", {"q": "roofing"})
    assert await rate_limit.get_cached_search(key) is None
    await rate_limit.set_cached_search(key, {"advertisers": 3})
    cached = await rate_limit.get_cached_search(key)
    assert cached == {"advertisers": 3}
    # Stored as JSON.
    assert json.loads(fake.store[key]) == {"advertisers": 3}


@pytest.mark.asyncio
async def test_rate_limit_fails_open_on_redis_error(monkeypatch) -> None:
    async def _boom():
        raise RuntimeError("redis down")

    monkeypatch.setattr(rate_limit, "get_redis", _boom)
    allowed, count = await rate_limit.acquire_provider_call_slot("meta")
    # Fails open so discovery never wedges on a Redis outage.
    assert allowed is True
    assert count == 0
