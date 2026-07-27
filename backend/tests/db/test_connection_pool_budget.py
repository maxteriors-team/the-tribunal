"""Regression tests for the Postgres connection-pool budget.

Production once ran ``pool_size=5`` with ``max_overflow=10`` while the same
process hosted the API *and* ~28 background workers. Worker fan-out drained all
15 connections, and because ``get_current_user`` queries the DB on every
authenticated request, each dashboard page load then blocked on pool checkout
until it raised::

    sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 10 reached,
    connection timed out, timeout 30.00

Worker cycles logged ``duration_ms=270977`` while reporting
``items_processed=0`` — time spent entirely waiting for a connection.

These tests pin the two properties that keep that from silently returning:
the pool is big enough to absorb a worker burst, and small enough that two
containers plus migrations stay under the server's ``max_connections``.
"""

from __future__ import annotations

from app.core.config import settings
from app.db.session import engine

# Production Postgres reports ``max_connections=100`` with
# ``superuser_reserved_connections=3``.
SERVER_MAX_CONNECTIONS = 100
SERVER_RESERVED_CONNECTIONS = 3
USABLE_CONNECTIONS = SERVER_MAX_CONNECTIONS - SERVER_RESERVED_CONNECTIONS

# Railway keeps the old container serving until the new one passes ``/readyz``,
# so both hold a full pool at once during a deploy.
CONCURRENT_INSTANCES_DURING_DEPLOY = 2

# ``alembic upgrade head`` (preDeployCommand), backups, and psql sessions.
OPERATIONAL_CONNECTION_HEADROOM = 15


def _peak_connections() -> int:
    """Max connections one instance can hold open at once."""
    return settings.db_pool_size + settings.db_max_overflow


def test_pool_absorbs_a_worker_burst_without_starving_requests() -> None:
    """Peak pool capacity must exceed the burst that caused the outage.

    The frequently-polling workers alone can demand more than the old ceiling:
    ``campaign_worker`` and ``message_test_worker`` each fan out to
    ``MAX_CONCURRENCY=10`` every ``campaign_poll_interval`` (5s) and
    ``voice_campaign_worker`` adds 5 more every 10s. At 15 total connections
    those three could exhaust the pool on their own, leaving nothing for the
    request path.
    """
    burst_from_hot_workers = 10 + 10 + 5

    assert _peak_connections() > burst_from_hot_workers, (
        "Pool must outlast a simultaneous campaign/message-test/voice burst so "
        "authenticated requests can still check out a connection."
    )


def test_pool_fits_under_server_max_connections_during_a_rolling_deploy() -> None:
    """Two full pools plus migration/admin overhead must fit in the server budget."""
    worst_case = (
        _peak_connections() * CONCURRENT_INSTANCES_DURING_DEPLOY
        + OPERATIONAL_CONNECTION_HEADROOM
    )

    assert worst_case <= USABLE_CONNECTIONS, (
        f"Peak demand during a rolling deploy ({worst_case}) exceeds the "
        f"{USABLE_CONNECTIONS} usable server connections. Raise Postgres "
        "max_connections before raising DB_POOL_SIZE/DB_MAX_OVERFLOW."
    )


def test_pool_checkout_fails_fast_rather_than_hanging_the_page() -> None:
    """A saturated pool should surface an error well before proxy timeouts.

    SQLAlchemy's 30s default outlived the request budget, so a starved pool
    showed up as an indefinitely spinning dashboard instead of a clean failure.
    """
    assert settings.db_pool_timeout <= 15


def test_engine_is_built_from_the_configured_budget() -> None:
    """The live engine must reflect the settings, not hard-coded literals."""
    pool = engine.pool

    assert pool.size() == settings.db_pool_size
    assert pool._max_overflow == settings.db_max_overflow
    assert pool._timeout == settings.db_pool_timeout
