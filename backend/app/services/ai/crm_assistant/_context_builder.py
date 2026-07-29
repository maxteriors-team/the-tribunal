"""Live workspace context injected into the CRM assistant's system messages.

Without this the assistant was context-blind: it saw a static prompt and
nothing else. It did not know today's date (while being told to "summarize
yesterday"), the business's name, which campaigns exist, which agents exist,
what the pipeline stages are called, or which tags are in use. Every one of
those had to be discovered through a tool call, guessed, or answered wrong.

Prompt-cache safety
-------------------
``_summarizer`` deliberately keeps ``messages[0]`` byte-identical across turns
so OpenAI's prefix cache keeps hitting. This context is therefore emitted as a
**second** system message, never merged into the static prefix. The static
prefix stays cacheable; only this short, changing block misses.

The block is bounded (``_MAX_ITEMS`` per list) so a workspace with 400 tags
cannot crowd out the conversation.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.scope import select_workspace_owned
from app.models.agent import Agent
from app.models.campaign import Campaign, CampaignStatus
from app.models.contact import Contact
from app.models.pipeline import Pipeline, PipelineStage
from app.models.tag import Tag
from app.models.workspace import Workspace
from app.services.compliance.quiet_hours import resolve_zone

logger = structlog.get_logger()

# Per-list cap. Enough to be useful for name resolution, small enough that the
# block stays a few hundred tokens on a busy workspace.
_MAX_ITEMS = 15

# Campaign states an operator would call "live" when they say "my campaigns".
_LIVE_CAMPAIGN_STATUSES = (
    CampaignStatus.RUNNING.value,
    CampaignStatus.SCHEDULED.value,
    CampaignStatus.PAUSED.value,
)


@dataclass(slots=True)
class WorkspaceContext:
    """Facts about the workspace the assistant is operating in right now."""

    now: datetime
    timezone_name: str
    business_name: str | None = None
    business_description: str | None = None
    contact_count: int = 0
    live_campaigns: list[str] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)
    pipeline_stages: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    def to_system_message(self) -> str:
        """Render the context block sent as the second system message."""

        local_now = self.now.astimezone(resolve_zone(self.timezone_name))
        lines = [
            "## Current workspace context",
            "Live facts about this workspace. Prefer these over assumptions, but "
            "still call a tool before making a claim about a specific record.",
            "",
            f"- Now: {local_now.strftime('%A %d %B %Y, %H:%M')} ({self.timezone_name})",
            f"- Today's date: {local_now.date().isoformat()}",
        ]
        if self.business_name:
            lines.append(f"- Business: {self.business_name}")
        if self.business_description:
            lines.append(f"- About: {self.business_description}")
        lines.append(f"- Contacts on file: {self.contact_count}")

        for label, values in (
            ("Campaigns (running/scheduled/paused)", self.live_campaigns),
            ("AI agents", self.agents),
            ("Pipeline stages", self.pipeline_stages),
            ("Tags in use", self.tags),
        ):
            if values:
                lines.append(f"- {label}: {_render_capped(values)}")

        return "\n".join(lines)


def _render_capped(values: list[str]) -> str:
    """Join a vocabulary list, capped so one busy workspace cannot flood context.

    The queries already ``LIMIT``, but the cap is re-applied here so the size
    guarantee holds no matter how the dataclass was constructed. Truncation is
    stated explicitly — a silently short list would read as a complete one.
    """

    if len(values) <= _MAX_ITEMS:
        return ", ".join(values)
    shown = ", ".join(values[:_MAX_ITEMS])
    return f"{shown} (+{len(values) - _MAX_ITEMS} more)"


async def _scalar_count(db: AsyncSession, model: Any, workspace_id: uuid.UUID) -> int:
    total = await db.scalar(
        select_workspace_owned(model, workspace_id)
        .with_only_columns(func.count())
        .select_from(model)
    )
    return int(total) if total is not None else 0


async def _names(db: AsyncSession, column: Any, stmt: Any) -> list[str]:
    result = await db.execute(stmt.limit(_MAX_ITEMS))
    return [str(value) for value in result.scalars().all() if value]


async def build_workspace_context(
    db: AsyncSession,
    workspace_id: uuid.UUID,
) -> WorkspaceContext:
    """Gather live workspace facts for the assistant's context message.

    Queries run sequentially: they share one ``AsyncSession``, which is not
    safe for concurrent statements on a single connection (the same constraint
    that forces sequential tool execution in ``_processor``).
    """

    workspace = await db.get(Workspace, workspace_id)
    settings: dict[str, Any] = workspace.settings if workspace else {}
    timezone_name = str(settings.get("timezone") or "UTC")

    context = WorkspaceContext(
        now=datetime.now(UTC),
        timezone_name=timezone_name,
        business_name=workspace.name if workspace else None,
        business_description=workspace.description if workspace else None,
    )

    context.contact_count = await _scalar_count(db, Contact, workspace_id)
    context.live_campaigns = await _names(
        db,
        Campaign.name,
        select_workspace_owned(Campaign, workspace_id)
        .where(Campaign.status.in_(_LIVE_CAMPAIGN_STATUSES))
        .with_only_columns(Campaign.name)
        .order_by(Campaign.created_at.desc()),
    )
    context.agents = await _names(
        db,
        Agent.name,
        select_workspace_owned(Agent, workspace_id)
        .where(Agent.is_active.is_(True))
        .with_only_columns(Agent.name)
        .order_by(Agent.created_at.desc()),
    )
    context.pipeline_stages = await _names(
        db,
        PipelineStage.name,
        select(PipelineStage.name)
        .join(Pipeline, Pipeline.id == PipelineStage.pipeline_id)
        .where(Pipeline.workspace_id == workspace_id)
        .order_by(PipelineStage.order),
    )
    context.tags = await _names(
        db,
        Tag.name,
        select_workspace_owned(Tag, workspace_id).with_only_columns(Tag.name).order_by(Tag.name),
    )
    return context


async def build_context_message(
    db: AsyncSession,
    workspace_id: uuid.UUID,
) -> dict[str, str] | None:
    """Build the second system message, or ``None`` if context is unavailable.

    Never raises: a failure here must degrade the assistant to its previous
    context-blind behaviour, not break the whole conversation.
    """

    try:
        context = await build_workspace_context(db, workspace_id)
    except Exception:
        logger.exception(
            "crm_assistant_context_build_failed",
            workspace_id=str(workspace_id),
        )
        return None
    return {"role": "system", "content": context.to_system_message()}


def resolve_timezone(name: str) -> ZoneInfo:
    """Re-exported for callers that need the resolved zone."""

    return resolve_zone(name)
