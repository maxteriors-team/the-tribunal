"""Alembic environment configuration."""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.core.config import settings
from app.db.base import Base
from app.db.model_registry import import_model_modules

import_model_modules()

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _descending_op_index_names() -> frozenset[str]:
    """Names of indexes that declare a descending ``postgresql_ops`` ordering.

    SQLAlchemy's autogenerate cannot compare expression/functional indexes: a
    ``col DESC`` index reflected from PostgreSQL is rendered as an opaque
    expression, while the ORM side declares it via ``postgresql_ops``. The two
    never compare equal, so ``alembic check`` reports a phantom drop+recreate on
    every run even though the database already matches the model exactly.

    We auto-detect these indexes from the metadata (rather than hard-coding
    names) so newly added ``DESC`` indexes are suppressed automatically. The
    indexes are still authored explicitly in their owning migrations; we only
    exclude them from the autogenerate *comparison*.
    """
    names: set[str] = set()
    for table in target_metadata.tables.values():
        for index in table.indexes:
            ops = index.kwargs.get("postgresql_ops") or {}
            if any(str(value).upper().startswith("DESC") for value in ops.values()):
                if index.name:
                    names.add(index.name)
    return frozenset(names)


_DESCENDING_OP_INDEX_NAMES = _descending_op_index_names()

# Tables a migration owns end-to-end: created by its ``upgrade()`` and dropped by
# its ``downgrade()``, deliberately outliving the upgrade so the reverse can
# restore the data it rewrote. They have no ORM model by design, so autogenerate
# would otherwise propose dropping them and ``alembic check`` would fail on any
# database the migration has actually run against.
_MIGRATION_OWNED_TABLES = frozenset({"pipeline_restructure_backup"})


def include_object(obj, name, type_, reflected, compare_to):  # noqa: ANN001, ANN201
    """Exclude known autogenerate false positives.

    Applies to both the reflected (database) and metadata (ORM) sides so the
    object is never proposed for drop or recreate. See
    :func:`_descending_op_index_names` and :data:`_MIGRATION_OWNED_TABLES` for
    the rationale.
    """
    excluded_by_type = {
        "index": _DESCENDING_OP_INDEX_NAMES,
        "table": _MIGRATION_OWNED_TABLES,
    }
    return name not in excluded_by_type.get(type_, frozenset())


def get_url() -> str:
    """Get database URL from settings."""
    return settings.database_url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations with a connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in async mode."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
