"""Database session management."""

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

# Engine configuration is tuned for an async (asyncpg) Postgres workload that
# may sit idle behind a load balancer / PgBouncer and that needs to survive
# transient network blips without leaking dead connections into request handlers.
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    # Hard cap on persistent connections kept open in the pool.
    pool_size=settings.db_pool_size,
    # Extra connections we are willing to open above ``pool_size`` under burst
    # load. They are closed (not returned to the pool) once checked back in.
    max_overflow=settings.db_max_overflow,
    # Recycle connections every 30 minutes. Defends against silent TCP drops
    # from upstream proxies / NAT timeouts (Railway, PgBouncer, cloud LBs) that
    # would otherwise surface as ``InterfaceError`` on the next checkout.
    pool_recycle=1800,
    # Max seconds a request will wait for a free connection before raising
    # ``TimeoutError``. Bounds tail latency under saturation — a stuck pool
    # fails fast instead of piling up requests indefinitely.
    pool_timeout=settings.db_pool_timeout,
    # Issue a lightweight ``SELECT 1`` on checkout. Catches connections the
    # server has closed (restarts, idle timeouts) and transparently reconnects
    # so individual requests do not see ``DisconnectionError``.
    pool_pre_ping=True,
    # LIFO checkout keeps a small hot working set of connections busy while
    # letting the rest go idle, so ``pool_recycle`` can actually retire them.
    # FIFO (the default) round-robins every connection and defeats recycling.
    pool_use_lifo=True,
    connect_args={
        # asyncpg-specific: forwarded as ``SET <key> = <value>`` on each new
        # backend connection.
        "server_settings": {
            # Postgres JIT (LLVM) compilation has high per-query overhead and
            # is known to interact poorly with asyncpg's prepared-statement
            # cache (MagicStack/asyncpg#727). Disabling it gives more
            # predictable latency for OLTP-style queries.
            "jit": "off",
            # Tag every backend connection so ``pg_stat_activity`` /
            # ``pg_stat_statements`` clearly attribute load to this service.
            # Invaluable when sharing a database with workers, migrations,
            # or psql sessions.
            "application_name": "aicrm-backend",
        },
    },
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def commit_open_transaction(session: AsyncSession) -> None:
    """Commit the active transaction for a request/unit-of-work boundary."""
    if not session.in_transaction():
        return

    try:
        await session.commit()
    except BaseException:
        await rollback_open_transaction(session)
        raise


async def rollback_open_transaction(session: AsyncSession) -> None:
    """Rollback the active transaction for a failed request/unit-of-work boundary."""
    if session.in_transaction():
        await session.rollback()


@asynccontextmanager
async def transaction_boundary(session: AsyncSession) -> AsyncIterator[AsyncSession]:
    """Own commit/rollback for one application unit of work.

    Callers inside the boundary may flush/refresh to materialize database-generated
    values, but must not commit or rollback themselves.
    """
    try:
        yield session
    except BaseException:
        await rollback_open_transaction(session)
        raise
    else:
        await commit_open_transaction(session)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that provides a database session without owning commit/rollback."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
