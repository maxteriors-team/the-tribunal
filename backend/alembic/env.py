"""Alembic environment configuration."""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.core.config import settings
from app.db.base import Base
from app.models import (  # noqa: F401 - Import all models to register them
    APIKey,
    Agent,
    Appointment,
    Automation,
    AutomationExecution,
    BanditDecision,
    CallFeedback,
    CallOutcome,
    Campaign,
    CampaignContact,
    CampaignNumberPool,
    CampaignReport,
    Contact,
    ContactTag,
    Conversation,
    DemoRequest,
    GlobalOptOut,
    LeadDiscoveryJob,
    LeadEnrichmentResult,
    LeadMagnet,
    LeadProspect,
    Message,
    MessageTemplate,
    MessageTest,
    Offer,
    OfferLeadMagnet,
    Opportunity,
    OpportunityActivity,
    OpportunityLineItem,
    OutboundMission,
    OutboundSequence,
    OutboundSequenceEnrollment,
    OutboundSequenceStepAttempt,
    PhoneNumber,
    PhoneNumberDailyStats,
    Pipeline,
    PipelineStage,
    PromptVersion,
    PromptVersionStats,
    Segment,
    Tag,
    TestContact,
    TestVariant,
    User,
    Workspace,
    WorkspaceIntegration,
    WorkspaceInvitation,
    WorkspaceMembership,
)
from app.models.improvement_suggestion import ImprovementSuggestion  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


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
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations with a connection."""
    context.configure(connection=connection, target_metadata=target_metadata)

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
