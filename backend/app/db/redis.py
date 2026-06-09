"""Redis connection management."""

import asyncio

import redis.asyncio as redis

from app.core.config import settings

redis_client: redis.Redis | None = None
_redis_lock = asyncio.Lock()


async def get_redis() -> redis.Redis:
    """Get the shared Redis client, creating it on first use.

    The client is backed by an explicit ``ConnectionPool`` with bounded
    concurrency, socket timeouts, and periodic health checks so a hung
    Redis node can't silently stall every request waiting on a connection.
    Singleton creation is guarded by an ``asyncio.Lock`` to prevent two
    concurrent tasks from racing and leaking a pool on cold start.
    """
    global redis_client
    if redis_client is not None:
        return redis_client

    async with _redis_lock:
        # Re-check under the lock: another task may have created the client
        # while we were waiting to acquire it.
        if redis_client is None:
            pool = redis.ConnectionPool.from_url(
                settings.redis_url,
                # Headroom over the worker count (currently 24 heartbeat-required
                # workers) plus concurrent-probe slack. The /readyz heartbeat
                # check itself borrows a single connection (MGET round-trip), so
                # this cap is defensive rather than load-bearing.
                max_connections=50,
                socket_timeout=5,
                socket_connect_timeout=2,
                health_check_interval=30,
                retry_on_timeout=True,
                decode_responses=True,
            )
            redis_client = redis.Redis(connection_pool=pool)
        return redis_client


async def close_redis() -> None:
    """Close Redis connection and dispose of the underlying pool."""
    global redis_client
    async with _redis_lock:
        if redis_client is not None:
            client = redis_client
            redis_client = None
            await client.aclose()
            await client.connection_pool.disconnect()
