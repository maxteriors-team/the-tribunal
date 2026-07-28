"""Inbound caller spam screening.

Before an inbound call is auto-answered by an AI agent, the caller's number is
screened against three signals and a per-workspace spam policy is applied:

1. **Global opt-out** — numbers on the workspace :class:`GlobalOptOut` list
   (the same list enforced on outbound) are treated as having withdrawn
   consent and are rejected.
2. **Blocklist** — explicit numbers the workspace has banned, configured under
   ``workspace.settings["inbound_screening"]["blocklist"]``. Conversations the
   operator has manually marked :class:`ConversationStatus.BLOCKED` are also
   honoured.
3. **Reputation** — a per-number reputation map
   (``...["reputation"]`` → ``{number: "spam"|"suspect"}``, typically populated
   from an external reputation feed) plus a behavioural burst heuristic
   (an unusual volume of recent inbound calls from the same number).

The screener returns a :class:`ScreeningOutcome` describing the decision
(allow / low_priority / challenge / reject) and the reason. The call handler
persists this on the inbound call's :class:`Message` and acts on it:

* ``reject`` — hang up without answering.
* ``challenge`` — answer to voicemail/identity challenge instead of the AI.
* ``low_priority`` — answer normally but flag for de-prioritised handling.
* ``allow`` — normal handling.

Screening is **fail-open**: any unexpected error degrades to ``allow`` so a
screening bug never silently drops legitimate calls.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import hash_phone
from app.models.conversation import (
    Conversation,
    ConversationStatus,
    Message,
    MessageChannel,
    MessageDirection,
)
from app.models.workspace import Workspace
from app.services.rate_limiting.opt_out_manager import OptOutManager

logger = structlog.get_logger()

# Settings key under ``workspace.settings`` holding the feature configuration.
SETTINGS_KEY = "inbound_screening"

# Defaults for the behavioural burst heuristic.
DEFAULT_BURST_THRESHOLD = 6
DEFAULT_BURST_WINDOW_MINUTES = 60


class SpamDecision(StrEnum):
    """Outcome of screening an inbound caller."""

    ALLOW = "allow"
    LOW_PRIORITY = "low_priority"
    CHALLENGE = "challenge"
    REJECT = "reject"


@dataclass(slots=True, frozen=True)
class ScreeningOutcome:
    """Result of screening an inbound caller against the spam policy."""

    decision: SpamDecision = SpamDecision.ALLOW
    reason: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def is_rejected(self) -> bool:
        """The caller should not be connected to an agent at all."""
        return self.decision is SpamDecision.REJECT

    @property
    def needs_challenge(self) -> bool:
        """The caller should be screened (voicemail / identity challenge)."""
        return self.decision is SpamDecision.CHALLENGE

    @property
    def is_low_priority(self) -> bool:
        """The caller is suspicious but allowed; handle at low priority."""
        return self.decision is SpamDecision.LOW_PRIORITY


@dataclass(slots=True, frozen=True)
class InboundScreeningSettings:
    """Per-workspace configuration for inbound caller screening."""

    enabled: bool = True
    blocklist: frozenset[str] = field(default_factory=frozenset)
    reputation: dict[str, str] = field(default_factory=dict)
    burst_threshold: int = DEFAULT_BURST_THRESHOLD
    burst_window_minutes: int = DEFAULT_BURST_WINDOW_MINUTES


def get_inbound_screening_settings(workspace: Workspace) -> InboundScreeningSettings:
    """Return the screening settings for a workspace (defaults when unset)."""
    raw = (workspace.settings or {}).get(SETTINGS_KEY, {})
    if not isinstance(raw, dict):
        raw = {}

    blocklist_raw = raw.get("blocklist") or []
    blocklist = frozenset(str(n) for n in blocklist_raw if n)

    reputation_raw = raw.get("reputation") or {}
    reputation = (
        {str(k): str(v).lower() for k, v in reputation_raw.items()}
        if isinstance(reputation_raw, dict)
        else {}
    )

    try:
        burst_threshold = int(raw.get("burst_threshold", DEFAULT_BURST_THRESHOLD))
    except (TypeError, ValueError):
        burst_threshold = DEFAULT_BURST_THRESHOLD
    try:
        burst_window = int(raw.get("burst_window_minutes", DEFAULT_BURST_WINDOW_MINUTES))
    except (TypeError, ValueError):
        burst_window = DEFAULT_BURST_WINDOW_MINUTES

    return InboundScreeningSettings(
        enabled=bool(raw.get("enabled", True)),
        blocklist=blocklist,
        reputation=reputation,
        burst_threshold=max(burst_threshold, 1),
        burst_window_minutes=max(burst_window, 1),
    )


class InboundCallScreener:
    """Screen inbound callers against opt-out / blocklist / reputation signals."""

    def __init__(self, opt_out_manager: OptOutManager | None = None) -> None:
        self.opt_out_manager = opt_out_manager or OptOutManager()
        self.logger = logger.bind(component="inbound_call_screener")

    async def screen(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        from_number: str,
        log: Any | None = None,
    ) -> ScreeningOutcome:
        """Screen an inbound caller and return the spam policy decision.

        Args:
            db: Database session.
            workspace_id: Workspace receiving the call.
            from_number: Caller number in E.164 format.
            log: Optional bound logger.

        Returns:
            A :class:`ScreeningOutcome`. Fail-open: any error yields ``allow``.
        """
        log = (log or self.logger).bind(from_number=from_number)

        try:
            return await self._screen(db, workspace_id, from_number, log)
        except Exception as exc:  # fail-open — never drop a call on a screen bug
            log.warning("inbound_screening_failed_open", error=str(exc))
            return ScreeningOutcome(
                decision=SpamDecision.ALLOW,
                reason="screening_error",
                details={"error": str(exc)},
            )

    async def _screen(  # noqa: PLR0911
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        from_number: str,
        log: Any,
    ) -> ScreeningOutcome:
        workspace = await db.get(Workspace, workspace_id)
        settings = (
            get_inbound_screening_settings(workspace)
            if workspace is not None
            else InboundScreeningSettings()
        )

        if not settings.enabled:
            return ScreeningOutcome(decision=SpamDecision.ALLOW, reason="screening_disabled")

        # 1. Global opt-out — the caller has withdrawn consent.
        if from_number and await self.opt_out_manager.check_opt_out(workspace_id, from_number, db):
            log.info("inbound_screened_opt_out")
            return ScreeningOutcome(decision=SpamDecision.REJECT, reason="global_opt_out")

        # 2a. Explicit workspace blocklist.
        if from_number and from_number in settings.blocklist:
            log.info("inbound_screened_blocklist")
            return ScreeningOutcome(decision=SpamDecision.REJECT, reason="blocklist")

        # 2b. Operator-blocked conversation for this caller.
        if from_number and await self._is_conversation_blocked(db, workspace_id, from_number):
            log.info("inbound_screened_conversation_blocked")
            return ScreeningOutcome(decision=SpamDecision.REJECT, reason="conversation_blocked")

        # 3a. Reputation feed label.
        label = settings.reputation.get(from_number) if from_number else None
        if label in ("spam", "fraud", "robocall"):
            log.info("inbound_screened_reputation_spam", label=label)
            return ScreeningOutcome(
                decision=SpamDecision.REJECT,
                reason="reputation_spam",
                details={"label": label},
            )
        if label in ("suspect", "suspicious", "unknown_risk"):
            log.info("inbound_screened_reputation_suspect", label=label)
            return ScreeningOutcome(
                decision=SpamDecision.CHALLENGE,
                reason="reputation_suspect",
                details={"label": label},
            )

        # 3b. Behavioural burst — unusual recent inbound call volume.
        if from_number:
            recent_calls = await self._recent_inbound_call_count(
                db, workspace_id, from_number, settings.burst_window_minutes
            )
            if recent_calls >= settings.burst_threshold:
                log.info(
                    "inbound_screened_high_call_volume",
                    recent_calls=recent_calls,
                    threshold=settings.burst_threshold,
                )
                return ScreeningOutcome(
                    decision=SpamDecision.LOW_PRIORITY,
                    reason="high_call_volume",
                    details={
                        "recent_calls": recent_calls,
                        "window_minutes": settings.burst_window_minutes,
                    },
                )

        return ScreeningOutcome(decision=SpamDecision.ALLOW)

    async def _is_conversation_blocked(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        from_number: str,
    ) -> bool:
        """Return True if any conversation for this caller is operator-blocked."""
        result = await db.execute(
            select(Conversation.id)
            .where(
                Conversation.workspace_id == workspace_id,
                Conversation.contact_phone_hash == hash_phone(from_number),
                Conversation.status == ConversationStatus.BLOCKED,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def _recent_inbound_call_count(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        from_number: str,
        window_minutes: int,
    ) -> int:
        """Count recent inbound voice calls from this caller within the window."""
        cutoff = datetime.now(UTC) - timedelta(minutes=window_minutes)
        result = await db.execute(
            select(func.count(Message.id))
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(
                Conversation.workspace_id == workspace_id,
                Conversation.contact_phone_hash == hash_phone(from_number),
                Message.direction == MessageDirection.INBOUND,
                Message.channel == MessageChannel.VOICE,
                Message.created_at >= cutoff,
            )
        )
        return int(result.scalar() or 0)
