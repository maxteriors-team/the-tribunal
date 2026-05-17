"""Service for managing call outcomes."""

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.call_outcome import CallOutcome, ClassifiedBy, OutcomeType
from app.models.conversation import Message
from app.models.prompt_version import PromptVersion
from app.services.ai.bandit_reward_service import record_bandit_reward

logger = structlog.get_logger()


class CallOutcomeService:
    """Service for call outcome management.

    Handles creating and updating call outcomes with proper attribution
    to prompt versions for performance analysis.
    """

    async def create_outcome(
        self,
        db: AsyncSession,
        message_id: uuid.UUID,
        outcome_type: str,
        *,
        prompt_version_id: uuid.UUID | None = None,
        signals: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        classified_by: str = "hangup_cause",
        classification_confidence: float | None = None,
        raw_hangup_cause: str | None = None,
    ) -> CallOutcome:
        """Create a call outcome record.

        Args:
            db: Database session
            message_id: Message (call) ID
            outcome_type: Type of outcome
            prompt_version_id: Prompt version used for attribution
            signals: Flexible outcome signals
            context: Decision-time context for bandit learning
            classified_by: Classification method
            classification_confidence: Confidence score
            raw_hangup_cause: Original hangup cause from provider

        Returns:
            Created CallOutcome
        """
        log = logger.bind(
            service="call_outcome",
            message_id=str(message_id),
            outcome_type=outcome_type,
        )

        # Check if outcome already exists
        existing_result = await db.execute(
            select(CallOutcome).where(CallOutcome.message_id == message_id)
        )
        existing = existing_result.scalar_one_or_none()

        if existing:
            log.info("outcome_already_exists", existing_id=str(existing.id))
            # Update existing instead
            return await self.update_outcome(
                db=db,
                outcome_id=existing.id,
                outcome_type=outcome_type,
                signals=signals,
                classified_by=classified_by,
                classification_confidence=classification_confidence,
            )

        # Get prompt_version_id from message if not provided
        if prompt_version_id is None:
            msg_result = await db.execute(
                select(Message.prompt_version_id).where(Message.id == message_id)
            )
            prompt_version_id = msg_result.scalar_one_or_none()

        outcome = CallOutcome(
            message_id=message_id,
            prompt_version_id=prompt_version_id,
            outcome_type=outcome_type,
            signals=signals or {},
            context=context or {},
            classified_by=classified_by,
            classification_confidence=classification_confidence,
            raw_hangup_cause=raw_hangup_cause,
        )

        db.add(outcome)
        await db.commit()
        await db.refresh(outcome)

        log.info("outcome_created", outcome_id=str(outcome.id))

        # Update prompt version counters (denormalized)
        if prompt_version_id:
            await self._update_version_counters(db, prompt_version_id, outcome_type, signals)

        # Record bandit reward if a decision exists for this message
        try:
            await record_bandit_reward(db, outcome)
        except Exception as e:
            # Don't fail outcome creation if reward recording fails
            log.warning("bandit_reward_recording_failed", error=str(e))

        return outcome

    async def update_outcome(
        self,
        db: AsyncSession,
        outcome_id: uuid.UUID,
        *,
        outcome_type: str | None = None,
        signals: dict[str, Any] | None = None,
        classified_by: str | None = None,
        classification_confidence: float | None = None,
    ) -> CallOutcome:
        """Update an existing call outcome.

        Args:
            db: Database session
            outcome_id: Outcome ID to update
            outcome_type: New outcome type
            signals: New or merged signals
            classified_by: New classification method
            classification_confidence: New confidence

        Returns:
            Updated CallOutcome
        """
        log = logger.bind(service="call_outcome", outcome_id=str(outcome_id))

        result = await db.execute(select(CallOutcome).where(CallOutcome.id == outcome_id))
        outcome = result.scalar_one_or_none()
        if not outcome:
            raise ValueError(f"CallOutcome {outcome_id} not found")

        old_outcome_type = outcome.outcome_type

        if outcome_type is not None:
            outcome.outcome_type = OutcomeType(outcome_type)

        if signals is not None:
            # Merge signals with existing
            existing_signals = outcome.signals or {}
            existing_signals.update(signals)
            outcome.signals = existing_signals

        if classified_by is not None:
            outcome.classified_by = ClassifiedBy(classified_by)

        if classification_confidence is not None:
            outcome.classification_confidence = classification_confidence

        await db.commit()
        await db.refresh(outcome)

        log.info(
            "outcome_updated",
            old_type=old_outcome_type,
            new_type=outcome.outcome_type,
        )

        return outcome

    async def get_outcome(
        self,
        db: AsyncSession,
        message_id: uuid.UUID,
    ) -> CallOutcome | None:
        """Get call outcome for a message.

        Args:
            db: Database session
            message_id: Message ID

        Returns:
            CallOutcome or None
        """
        result = await db.execute(select(CallOutcome).where(CallOutcome.message_id == message_id))
        return result.scalar_one_or_none()

    async def _update_version_counters(
        self,
        db: AsyncSession,
        prompt_version_id: uuid.UUID,
        outcome_type: str,
        signals: dict[str, Any] | None,
    ) -> None:
        """Update denormalized counters on prompt version."""
        result = await db.execute(
            select(PromptVersion).where(PromptVersion.id == prompt_version_id)
        )
        version = result.scalar_one_or_none()
        if not version:
            return

        version.total_calls += 1

        # Count successful calls (completed or better outcomes)
        success_types = {"completed", "appointment_booked", "lead_qualified"}
        if outcome_type in success_types:
            version.successful_calls += 1

        # Count bookings
        if outcome_type == "appointment_booked" or (signals and signals.get("appointment_booked")):
            version.booked_appointments += 1

        await db.commit()


# Convenience function for creating outcome from hangup webhook


async def create_outcome_from_hangup(
    db: AsyncSession,
    message_id: uuid.UUID,
    hangup_cause: str,
    duration_secs: int,
    booking_outcome: str | None = None,
    *,
    contact_id: int | None = None,
    agent_id: uuid.UUID | None = None,
) -> CallOutcome:
    """Create call outcome from Telnyx hangup webhook data.

    Maps hangup causes to outcome types and builds signals dict.
    Optionally builds decision context for bandit learning.

    Args:
        db: Database session
        message_id: Message (call) ID
        hangup_cause: Telnyx hangup cause code
        duration_secs: Call duration in seconds
        booking_outcome: Optional booking outcome ("success", "failed", etc.)
        contact_id: Optional contact ID for context building
        agent_id: Optional agent ID for context building
    """
    from app.services.ai.bandit_context import build_decision_context

    # Map hangup causes to outcome types
    cause_to_outcome = {
        "normal_clearing": "completed",
        "originator_cancel": "rejected",
        "user_busy": "busy",
        "no_answer": "no_answer",
        "call_rejected": "rejected",
        "unallocated_number": "failed",
        "network_out_of_order": "failed",
        "normal_temporary_failure": "failed",
    }

    outcome_type = cause_to_outcome.get(hangup_cause, "completed")

    # Override if booking was successful
    if booking_outcome == "success":
        outcome_type = "appointment_booked"

    # Build signals
    signals: dict[str, Any] = {
        "duration_seconds": duration_secs,
        "call_completed": outcome_type in {"completed", "appointment_booked", "lead_qualified"},
    }

    if booking_outcome:
        signals["booking_outcome"] = booking_outcome
        signals["appointment_booked"] = booking_outcome == "success"
        signals["booking_attempted"] = True

    # Build context if we have enough info
    context: dict[str, Any] | None = None
    if agent_id is not None:
        import contextlib

        with contextlib.suppress(Exception):
            context = await build_decision_context(
                db=db,
                contact_id=contact_id,
                agent_id=agent_id,
                call_time=datetime.now(UTC),
            )

    service = CallOutcomeService()
    return await service.create_outcome(
        db=db,
        message_id=message_id,
        outcome_type=outcome_type,
        signals=signals,
        context=context,
        classified_by="hangup_cause",
        raw_hangup_cause=hangup_cause,
    )
