"""Processes inbound SMS commands (Y/N/approve/reject) for the HITL approval gate.

Intercepts inbound SMS messages from registered human operators and routes
approval/rejection commands to the ApprovalGateService before they reach
normal conversation processing.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar, Protocol

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import hash_phone
from app.models.human_profile import HumanProfile
from app.models.pending_action import PendingAction
from app.models.phone_number import PhoneNumber
from app.models.workspace import WorkspaceMembership
from app.services.approval.approval_gate_service import ApprovalGateService, approval_gate_service
from app.utils.phone import normalize_phone_safe

logger = logging.getLogger(__name__)


class ApprovalCommandKind(StrEnum):
    """Supported inbound operator command intents."""

    APPROVE = "approve"
    REJECT = "reject"


@dataclass(slots=True, frozen=True)
class ApprovalSmsCommand:
    """Normalized approval command extracted from an inbound SMS."""

    kind: ApprovalCommandKind
    normalized_from: str
    normalized_to: str
    original_body: str


class SmsResponder(Protocol):
    """Sends command outcome messages back to the operator."""

    async def send_response(self, *, from_number: str, to_number: str, body: str) -> None:
        """Send a short command outcome response."""
        ...


class TextProviderSmsResponder:
    """SMS responder backed by the configured text-message provider."""

    async def send_response(self, *, from_number: str, to_number: str, body: str) -> None:
        from app.db.session import AsyncSessionLocal
        from app.services.telephony.text_provider import get_text_message_provider

        async with AsyncSessionLocal() as db:
            sms_service = get_text_message_provider()
            try:
                phone_result = await db.execute(
                    select(PhoneNumber).where(PhoneNumber.phone_number == from_number)
                )
                phone_record = phone_result.scalar_one_or_none()
                if phone_record is None:
                    logger.debug("No PhoneNumber record for %s", from_number)
                    return
                await sms_service.send_message(
                    to_number=to_number,
                    from_number=from_number,
                    body=body,
                    db=db,
                    workspace_id=phone_record.workspace_id,
                    phone_number_id=phone_record.id,
                )
            except Exception:
                logger.exception(
                    "Failed to send text response from %s to %s",
                    from_number,
                    to_number,
                )
            finally:
                await sms_service.close()


@dataclass(slots=True, frozen=True)
class ApprovalCommandExecutionResult:
    """Outcome of applying an inbound command to a pending action."""

    action: PendingAction
    response_body: str


class ApprovalCommandHandler(Protocol):
    """Typed handler contract for one inbound approval command kind."""

    @property
    def kind(self) -> ApprovalCommandKind:
        """Inbound command kind handled by this command handler."""
        ...

    async def execute(
        self,
        *,
        db: AsyncSession,
        action: PendingAction,
        user_id: int,
        gate_service: ApprovalGateService,
    ) -> ApprovalCommandExecutionResult:
        """Apply the command to the pending action and return the operator response."""
        ...


@dataclass(slots=True, frozen=True)
class ApproveSmsCommandHandler:
    """Approve the latest pending action."""

    kind: ApprovalCommandKind = ApprovalCommandKind.APPROVE

    async def execute(
        self,
        *,
        db: AsyncSession,
        action: PendingAction,
        user_id: int,
        gate_service: ApprovalGateService,
    ) -> ApprovalCommandExecutionResult:
        approved_action = await gate_service.approve_action(
            db,
            action_id=action.id,
            user_id=user_id,
            channel="sms",
        )
        return ApprovalCommandExecutionResult(
            action=approved_action,
            response_body=f"✓ Approved: {approved_action.description}",
        )


@dataclass(slots=True, frozen=True)
class RejectSmsCommandHandler:
    """Reject the latest pending action."""

    kind: ApprovalCommandKind = ApprovalCommandKind.REJECT

    async def execute(
        self,
        *,
        db: AsyncSession,
        action: PendingAction,
        user_id: int,
        gate_service: ApprovalGateService,
    ) -> ApprovalCommandExecutionResult:
        rejected_action = await gate_service.reject_action(
            db,
            action_id=action.id,
            user_id=user_id,
            channel="sms",
        )
        return ApprovalCommandExecutionResult(
            action=rejected_action,
            response_body=f"✗ Rejected: {rejected_action.description}",
        )


class CommandProcessorService:
    """Processes inbound SMS commands (Y/N/approve/reject) for pending actions."""

    APPROVE_KEYWORDS: ClassVar[set[str]] = {
        "y",
        "yes",
        "approve",
        "ok",
        "go",
        "do it",
        "\U0001f44d",
    }
    REJECT_KEYWORDS: ClassVar[set[str]] = {
        "n",
        "no",
        "reject",
        "deny",
        "stop",
        "cancel",
        "\U0001f44e",
    }

    def __init__(
        self,
        *,
        gate_service: ApprovalGateService = approval_gate_service,
        sms_responder: SmsResponder | None = None,
        command_handlers: tuple[ApprovalCommandHandler, ...] | None = None,
        phone_normalizer: Callable[[str], str | None] = normalize_phone_safe,
    ) -> None:
        self.gate_service = gate_service
        self.sms_responder = sms_responder or TextProviderSmsResponder()
        handlers = command_handlers or (ApproveSmsCommandHandler(), RejectSmsCommandHandler())
        self._command_handlers = {handler.kind: handler for handler in handlers}
        self._phone_normalizer = phone_normalizer

    async def try_process_command(
        self,
        db: AsyncSession,
        from_number: str,
        to_number: str,
        body: str,
    ) -> bool:
        """Attempt to process an SMS as an approval command.

        Returns True if the message was consumed as a command (caller should
        NOT continue with normal SMS processing). Returns False if the message
        is not a recognised command or doesn't come from a known operator.
        """
        command = self._parse_command(
            from_number=from_number,
            to_number=to_number,
            body=body,
        )
        if command is None:
            return False

        normalized_to = command.normalized_to
        normalized_from = command.normalized_from

        # 4. Look up PhoneNumber record for to_number to get workspace_id
        phone_result = await db.execute(
            select(PhoneNumber).where(
                PhoneNumber.phone_number == normalized_to,
            )
        )
        phone_record = phone_result.scalar_one_or_none()
        if phone_record is None:
            logger.debug("No PhoneNumber record for %s", normalized_to)
            return False

        workspace_id: uuid.UUID = phone_record.workspace_id

        # 5. Look up HumanProfile where phone matches from_number AND workspace matches
        profile_result = await db.execute(
            select(HumanProfile).where(
                and_(
                    HumanProfile.phone_hash == hash_phone(normalized_from),
                    HumanProfile.workspace_id == workspace_id,
                    HumanProfile.is_active.is_(True),
                )
            )
        )
        profile = profile_result.scalar_one_or_none()
        if profile is None:
            return False

        # 6. Find the most recent pending action for this workspace
        action_result = await db.execute(
            select(PendingAction)
            .where(
                and_(
                    PendingAction.workspace_id == workspace_id,
                    PendingAction.status == "pending",
                    PendingAction.notification_sent.is_(True),
                )
            )
            .order_by(PendingAction.created_at.desc())
            .limit(1)
        )
        action = action_result.scalar_one_or_none()

        if action is None:
            await self._send_sms_response(
                from_number=normalized_to,
                to_number=normalized_from,
                body="No pending actions to review.",
            )
            return True

        # 7. Resolve user_id from workspace membership
        user_id = await self._resolve_user_id(db, workspace_id)

        handler = self._command_handlers[command.kind]
        result = await handler.execute(
            db=db,
            action=action,
            user_id=user_id,
            gate_service=self.gate_service,
        )
        await self._send_sms_response(
            from_number=normalized_to,
            to_number=normalized_from,
            body=result.response_body,
        )

        logger.info(
            "Processed SMS command from %s: %s action %s",
            normalized_from,
            command.kind.value,
            action.id,
        )
        return True

    def _parse_command(
        self,
        *,
        from_number: str,
        to_number: str,
        body: str,
    ) -> ApprovalSmsCommand | None:
        """Parse and normalize an inbound approval SMS command."""
        normalized_body = body.strip().lower()
        command_kind: ApprovalCommandKind | None = None
        if normalized_body in self.APPROVE_KEYWORDS:
            command_kind = ApprovalCommandKind.APPROVE
        elif normalized_body in self.REJECT_KEYWORDS:
            command_kind = ApprovalCommandKind.REJECT

        if command_kind is None:
            return None

        normalized_to = self._phone_normalizer(to_number)
        normalized_from = self._phone_normalizer(from_number)
        if not normalized_to or not normalized_from:
            logger.debug(
                "Could not normalize phone numbers: from=%s, to=%s",
                from_number,
                to_number,
            )
            return None

        return ApprovalSmsCommand(
            kind=command_kind,
            normalized_from=normalized_from,
            normalized_to=normalized_to,
            original_body=body,
        )

    async def _resolve_user_id(self, db: AsyncSession, workspace_id: uuid.UUID) -> int:
        """Get the owner/admin user_id for the workspace.

        Falls back to the first member if no owner is found.
        """
        # Prefer the workspace owner
        result = await db.execute(
            select(WorkspaceMembership.user_id)
            .where(
                and_(
                    WorkspaceMembership.workspace_id == workspace_id,
                    WorkspaceMembership.role == "owner",
                )
            )
            .limit(1)
        )
        user_id = result.scalar_one_or_none()
        if user_id is not None:
            return int(user_id)

        # Fallback: any member
        result = await db.execute(
            select(WorkspaceMembership.user_id)
            .where(WorkspaceMembership.workspace_id == workspace_id)
            .limit(1)
        )
        user_id = result.scalar_one_or_none()
        if user_id is not None:
            return int(user_id)

        # Should not happen in practice, but return 0 as a safe fallback
        logger.warning("No workspace members found for workspace %s", workspace_id)
        return 0

    async def _send_sms_response(
        self,
        from_number: str,
        to_number: str,
        body: str,
    ) -> None:
        """Send an approval command response via the configured text provider."""
        await self.sms_responder.send_response(
            from_number=from_number,
            to_number=to_number,
            body=body,
        )


command_processor_service = CommandProcessorService()
