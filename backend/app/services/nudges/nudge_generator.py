"""Service for generating human nudges from contact data."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.workspace import Workspace
from app.services.nudges.strategies import (
    AnniversaryNudgeStrategy,
    ApprovalsWaitingNudgeStrategy,
    BirthdayNudgeStrategy,
    CoolingNudgeStrategy,
    CustomDateNudgeStrategy,
    DealStallNudgeStrategy,
    FollowUpNudgeStrategy,
    HotLeadNudgeStrategy,
    MonitorIdleNudgeStrategy,
    NoShowRecoveryNudgeStrategy,
    NudgeContext,
    NudgeStrategy,
    OutboundBatchReadyNudgeStrategy,
    ReferralAskNudgeStrategy,
    UnresponsiveNudgeStrategy,
)
from app.services.nudges.strategies.base import build_nudge_message

logger = logging.getLogger(__name__)

DEFAULT_LEAD_DAYS = 3
DEFAULT_COOLING_DAYS = 30
ALL_NUDGE_TYPES = [
    "birthday",
    "anniversary",
    "custom",
    "cooling",
    "follow_up",
    "deal_milestone",
    "noshow_recovery",
    "unresponsive",
    "hot_lead",
    "referral_ask",
    # Workspace-level operator nudges (contact_id is NULL).
    "outbound_batch_ready",
    "approvals_waiting",
    "monitor_idle",
]

# Order matters: the orchestrator preserves legacy query ordering for tests
# that pin db.execute side_effects to a specific sequence.
_STRATEGY_REGISTRY: list[tuple[str, type[NudgeStrategy]]] = [
    ("birthday", BirthdayNudgeStrategy),
    ("anniversary", AnniversaryNudgeStrategy),
    ("custom", CustomDateNudgeStrategy),
    ("cooling", CoolingNudgeStrategy),
    ("follow_up", FollowUpNudgeStrategy),
    ("deal_milestone", DealStallNudgeStrategy),
    ("unresponsive", UnresponsiveNudgeStrategy),
    ("noshow_recovery", NoShowRecoveryNudgeStrategy),
    ("hot_lead", HotLeadNudgeStrategy),
    ("referral_ask", ReferralAskNudgeStrategy),
    ("outbound_batch_ready", OutboundBatchReadyNudgeStrategy),
    ("approvals_waiting", ApprovalsWaitingNudgeStrategy),
    ("monitor_idle", MonitorIdleNudgeStrategy),
]

_DATE_NUDGE_TYPES = frozenset({"birthday", "anniversary", "custom"})


class NudgeGeneratorService:
    """Generates HumanNudge rows by dispatching to per-type strategy classes."""

    async def generate_for_workspace(self, db: AsyncSession, workspace: Workspace) -> int:
        """Generate nudges for all contacts in workspace. Returns count of new nudges."""
        nudge_settings = workspace.settings.get("nudge_settings", {})
        if not isinstance(nudge_settings, dict):
            nudge_settings = {}

        if not nudge_settings.get("enabled", True):
            return 0

        raw_lead = nudge_settings.get("lead_days", DEFAULT_LEAD_DAYS)
        lead_days = int(raw_lead) if raw_lead is not None else DEFAULT_LEAD_DAYS
        raw_cooling = nudge_settings.get("cooling_days", DEFAULT_COOLING_DAYS)
        cooling_days = int(raw_cooling) if raw_cooling is not None else DEFAULT_COOLING_DAYS
        enabled_types: list[str] = nudge_settings.get("nudge_types", ALL_NUDGE_TYPES)

        # Date strategies share this pre-fetched candidate set so we don't
        # requery once per type.
        result = await db.execute(
            select(Contact).where(
                Contact.workspace_id == workspace.id,
                Contact.important_dates.isnot(None),
            )
        )
        date_contacts = list(result.scalars().all())

        context = NudgeContext(
            workspace_id=workspace.id,
            lead_days=lead_days,
            cooling_days=cooling_days,
            enabled_types=enabled_types,
            date_contacts=date_contacts,
        )

        count = 0
        for type_key, strategy_cls in _STRATEGY_REGISTRY:
            if type_key not in enabled_types:
                continue
            if type_key in _DATE_NUDGE_TYPES and not date_contacts:
                continue
            count += await strategy_cls().generate(db, context)

        if count > 0:
            await db.commit()
            logger.info("Generated %d nudges for workspace %s", count, workspace.id)

        return count

    def _build_nudge_message(
        self,
        contact: Contact,
        nudge_type: str,
        date_str: str | None = None,
        days_until: int | None = None,
        label: str | None = None,
    ) -> tuple[str, str, str | None]:
        """Returns (title, message, suggested_action) for a nudge type."""
        return build_nudge_message(
            contact,
            nudge_type,
            date_str=date_str,
            days_until=days_until,
            label=label,
        )


nudge_generator_service = NudgeGeneratorService()
